import json,tempfile,uuid
from pathlib import Path
from datetime import datetime
from django.conf import settings
from django.test import TestCase,Client
from django.contrib.auth.models import User,Group
from django.core.exceptions import ValidationError
from app.models import ImportBatch,ImportRow,Record,CodingRule,CodeAllocation,AnalysisModel,Topic
from app.ingestion import convert,fingerprint,stage_file,commit_batch
from app.coding import allocate,validate_rule
from app.analytics import quality_state
from app.analysis_engine import run_analysis,validate_definition

class PlatformCase(TestCase):
    def setUp(self):
        self.admin=User.objects.create_user('admin',password='test-password')
        g=Group.objects.create(name='admin');self.admin.groups.add(g)
        self.quality=User.objects.create_user('quality',password='test-password')
        g=Group.objects.create(name='quality');self.quality.groups.add(g)
        self.batch=ImportBatch.objects.create(filename='unit-test.xlsx',file_hash='t',file_path='none',status='staged')
    def row(self,dataset,values,status='valid'):
        return ImportRow.objects.create(batch=self.batch,sheet=dataset,row_number=2,dataset=dataset,business_key=values['id'],raw=values,normalized=values,record_hash=fingerprint(values),status=status)
    def record(self,dataset,values):
        row=self.row(dataset,values,'committed');return Record.objects.create(dataset=dataset,business_key=values['id'],values=values,record_hash=row.record_hash,source_row=row)
    def post(self,url,data):return self.client.post(url,json.dumps(data),content_type='application/json')
    def checked_model_update(self,model,**changes):
        candidate={key:model[key] for key in ('name','dataset','definition','is_public')};candidate.update(changes)
        body=dict(version=model['version'],candidate=candidate,scope={},links=None)
        preview=self.post(f'/api/models/{model["id"]}/change-preview',body);self.assertEqual(preview.status_code,200,preview.content)
        return self.post(f'/api/models/{model["id"]}/change',dict(**body,receipt=preview.json()['receipt'],reason='测试核对新旧定义',acknowledged=True,request_id=str(uuid.uuid4())))

class ImportSafetyTests(PlatformCase):
    def test_ids_and_blank_text(self):
        f={'type':'str','required':True};self.assertEqual(convert('000019',f),'000019')
        for value in [19,'   ','=A1']:
            with self.assertRaises(ValueError):convert(value,f)
    def test_duplicate_commit_does_not_multiply(self):
        value={'id':'D01','name':'生产','owner':'经理'}
        self.row('departments',value);self.row('departments',value)
        commit_batch(self.batch.id);commit_batch(self.batch.id)
        self.assertEqual(Record.objects.count(),1)
        self.assertEqual(self.batch.rows.filter(status='duplicate').count(),1)
    def test_existing_content_conflict_is_quarantined(self):
        original=self.record('departments',{'id':'D01','name':'原部门','owner':'甲'})
        changed=self.row('departments',{'id':'D01','name':'被改名','owner':'甲'})
        commit_batch(self.batch.id);changed.refresh_from_db();original.refresh_from_db()
        self.assertEqual(changed.status,'conflict');self.assertEqual(original.values['name'],'原部门')
    def test_references_rechecked_at_commit(self):
        employee=self.row('employees',{'id':'E00001','department_id':'D-MISSING'})
        commit_batch(self.batch.id);employee.refresh_from_db();self.assertEqual(employee.status,'invalid');self.assertFalse(Record.objects.exists())
    def test_real_workbook_replay(self):
        path=next((settings.BASE_DIR/'outputs').glob('*/01_基础档案_模拟.xlsx'))
        with tempfile.TemporaryDirectory() as temp,self.settings(BASE_DIR=Path(temp)):
            batch,repeated=stage_file(path);self.assertFalse(repeated);self.assertFalse(batch.summary.get('invalid'))
            commit_batch(batch.id);self.assertEqual(Record.objects.count(),440)  # 32设备及56独立资源位
            replay,repeated=stage_file(path);self.assertTrue(repeated);self.assertEqual(replay.id,batch.id);self.assertEqual(Record.objects.count(),440)
    def test_repair_preserves_raw_and_requires_admin(self):
        r=self.row('departments',{'id':'D01','name':'原始空值','owner':None},'invalid')
        self.client.force_login(self.admin)
        response=self.post(f'/api/imports/{self.batch.id}/rows/{r.id}/repair',{'expected_row_hash':r.record_hash,'values':{'id':'D01','name':'生产','owner':'计划经理'}})
        self.assertEqual(response.status_code,200);r.refresh_from_db();self.assertIsNone(r.raw['owner']);self.assertEqual(r.normalized['owner'],'计划经理')
        commit_batch(self.batch.id);self.assertEqual(Record.objects.get().values['name'],'生产')
    def test_csrf_required_for_write(self):
        c=Client(enforce_csrf_checks=True);c.force_login(self.admin)
        self.assertEqual(c.post('/api/issues','{}',content_type='application/json').status_code,403)

class AnalysisTests(PlatformCase):
    def test_weighted_group_average_and_filter(self):
        for i,(group,value) in enumerate([('A',10),('A',20),('B',90)]):self.record('energy',{'id':str(i),'workshop':group,'kwh':value})
        defn={'dimension':'workshop','metrics':[{'agg':'avg','field':'kwh'},{'agg':'sum','field':'kwh'}],'filters':[{'field':'kwh','op':'gte','value':'10'}],'chart':'bar'}
        r=run_analysis(self.admin,'energy',defn);self.assertEqual(r['rows'],[{'dimension':'A','row_count':2,'m0':15,'m1':30},{'dimension':'B','row_count':1,'m0':90,'m1':90}])
    def test_money_permission_in_data_and_models(self):
        self.record('products',{'id':'CP.00001.A','family':'YE3','price_cents':123456})
        self.client.force_login(self.quality);r=self.client.get('/api/records/products');self.assertNotIn('price_cents',r.json()['rows'][0]['values'])
        self.assertEqual(self.client.get('/api/records/costs').status_code,403)
        d={'dimension':'family','metrics':[{'agg':'sum','field':'price_cents'}]}
        self.assertEqual(self.post('/api/analyze',{'dataset':'products','definition':d}).status_code,400)
        AnalysisModel.objects.create(name='秘密金额过滤',dataset='products',is_public=True,definition={'dimension':'family','metrics':[{'agg':'count'}],'filters':[{'field':'price_cents','op':'eq','value':'123456'}]})
        self.assertEqual(self.client.get('/api/models').json(),[])
    def test_finite_filters_and_no_expression_eval(self):
        for value in ['NaN','Infinity','__import__("os")']:
            with self.assertRaises(ValidationError):validate_definition(self.admin,'energy',{'dimension':'workshop','metrics':[{'agg':'sum','field':'kwh'}],'filters':[{'field':'kwh','op':'gte','value':value}]})
        with self.assertRaises(ValidationError):validate_definition(self.admin,'energy',{'dimension':'workshop','metrics':[{'agg':'eval','field':'kwh'}]})
    def test_save_reload_and_stale_version(self):
        self.client.force_login(self.admin);payload={'name':'按日分析','dataset':'units','definition':{'dimension':'assembly_at','grain':'day','metrics':[{'agg':'count'}],'chart':'line'}}
        r=self.post('/api/models',payload);self.assertEqual(r.status_code,200);saved=r.json()
        self.assertEqual(self.client.get('/api/models').json()[0]['definition'],payload['definition'])
        r=self.checked_model_update(saved,name='修改后');self.assertEqual(r.json()['model']['version'],2)
        self.assertEqual(self.post('/api/models',saved).status_code,409)
        topic=self.post('/api/topics',{'name':'质量专题','layout':[{'model_id':saved['id'],'span':2}]}).json()
        self.assertEqual(Topic.objects.get(pk=topic['id']).layout,[{'model_id':saved['id'],'span':2}])

class CodingTests(PlatformCase):
    def setUp(self):
        super().setUp();self.rule=CodingRule.objects.create(key='motor',name='SN',prefix='M',width=3,date_format='%y%m%d',reset_period='day',separator='')
    def test_preview_does_not_consume_and_allocate_is_unique(self):
        at=datetime(2026,10,3);preview=allocate(self.rule.pk,at,2,'admin',True)
        self.assertEqual(preview,['M261003001','M261003002']);self.assertEqual(CodeAllocation.objects.count(),0)
        self.assertEqual(allocate(self.rule.pk,at,2,'admin'),preview);self.assertEqual(allocate(self.rule.pk,at,1,'admin'),['M261003003'])
        self.assertEqual(allocate(self.rule.pk,datetime(2026,10,4),1,'admin'),['M261004001'])
    def test_cross_rule_collision_is_rejected(self):
        allocate(self.rule.pk,datetime(2026,10,3),1,'admin');r=CodingRule.objects.create(key='another',name='另一个规则',prefix='M',width=3,date_format='%y%m%d',reset_period='day',separator='')
        with self.assertRaises(ValidationError):allocate(r.pk,datetime(2026,10,3),1,'admin')
    def test_imported_legacy_number_is_reserved(self):
        self.record('units',{'id':'M261003001'})
        with self.assertRaises(ValidationError):allocate(self.rule.pk,datetime(2026,10,3),1,'admin')
    def test_reset_format_must_be_unique_across_periods(self):
        with self.assertRaises(ValidationError):validate_rule({'key':'test_rule','name':'测试','prefix':'T','date_format':'%Y%m','reset_period':'day','width':3})

class QualityTests(TestCase):
    def test_missing_item_failed_first_and_voided_sessions(self):
        specs=[{'id':'S1','product_id':'P1','version':'A','mandatory':True,'unit':'Ω','lsl':1,'usl':2},{'id':'S2','product_id':'P1','version':'A','mandatory':True,'unit':'MΩ','lsl':100,'usl':None}]
        base={'unit_id':'U1','equipment_id':'E1','spec_version':'A','voided':False,'complete':True,'result':'合格'}
        sessions=[{**base,'id':'T1','attempt':1,'tested':'2026-09-21T12:00:00','result':'不合格'},{**base,'id':'T2','attempt':2,'tested':'2026-09-21T13:00:00'},{**base,'id':'T3','attempt':3,'tested':'2026-09-21T14:00:00','voided':True},{**base,'id':'T4','unit_id':'U2','attempt':1,'tested':'2026-09-21T12:00:00','complete':False,'result':'不完整'}]
        measurements=[]
        for sid,values in [('T1',[3,200]),('T2',[1.5,200]),('T4',[1.5])]:
            for i,v in enumerate(values):measurements.append({'id':sid+str(i),'session_id':sid,'spec_id':specs[i]['id'],'value':v,'unit':specs[i]['unit'],'result':'不合格' if sid=='T1' and i==0 else '合格'})
        data={'units':[{'id':'U1','product_id':'P1'},{'id':'U2','product_id':'P1'}],'test_specs':specs,'test_sessions':sessions,'measurements':measurements}
        groups,mismatch=quality_state(data);self.assertEqual(len(groups['U1']),2);self.assertEqual(groups['U1'][0]['calculated_result'],'不合格');self.assertEqual(groups['U1'][1]['calculated_result'],'合格');self.assertFalse(groups['U2'][0]['calculated_complete']);self.assertEqual(mismatch,[])
