import json,uuid,copy
from unittest.mock import patch
from django.test import SimpleTestCase,Client
from django.core.exceptions import ValidationError
from django.contrib.auth.models import User,Group
from app import business_groups as bg,topic_workspace as ws,topic_snapshots as ss
from app.analysis_engine import run_analysis,validate_definition
from app.import_review import ReviewConflict
from app.models import BusinessGrouping,BusinessGroupingVersion,AnalysisModel,Topic,Record,AuditEvent
from tests.test_platform import PlatformCase

ADMIN=type('Admin',(),{'is_authenticated':True,'is_active':True,'is_superuser':True})()
def payload():return {'name':'功率段','dataset':'products','field':'power_kw','mode':'range','note':'用于模拟产品结构核对，非业务批准分段','rules':[{'label':'小功率','lower':None,'upper':'7.5'},{'label':'中功率','lower':'7.5','upper':'15'},{'label':'大功率','lower':'15','upper':None}]}
def enumeration():return {'name':'产品族归类','dataset':'products','field':'family','mode':'enum','note':'演练精确匹配与未归类','rules':[{'label':'标准电机','values':['YE3','YE4']},{'label':'变频电机','values':['YVF2']}]}

class GroupRuleTests(SimpleTestCase):
    def test_inclusive_lower_exclusive_upper_and_open_ends(self):
        p=bg.validate(ADMIN,payload())
        self.assertEqual([bg.classify(x,p) for x in [-1,0,7.499,7.5,14.99,15,1e6]],['小功率']*3+['中功率']*2+['大功率']*2)
    def test_enum_exact_no_strip_or_case_folding(self):
        p=bg.validate(ADMIN,enumeration())
        self.assertEqual([bg.classify(x,p) for x in ['YE3','YE4','ye3',' YE3','YVF2']],['标准电机','标准电机','未归类','未归类','变频电机'])
    def test_missing_unmatched_and_invalid_are_distinct(self):
        p=payload();p['rules']=[{'label':'样本','lower':'1','upper':'3'}];p=bg.validate(ADMIN,p)
        self.assertEqual([bg.classify(x,p) for x in [None,'',0,'2',True,float('inf'),2]],['未填写','未填写','未归类','值类型异常','值类型异常','值类型异常','样本'])
    def test_overlap_empty_reverse_and_nonfinite_rejected(self):
        for a,b in [('4','3'),('3','3'),('NaN','5'),('1','Infinity'),(True,'3'),('1e16',None),(None,None)]:
            p=payload();p['rules'][1].update(lower=a,upper=b)
            with self.subTest(a=a,b=b),self.assertRaises(ValidationError):bg.validate(ADMIN,p)
    def test_adjacent_decimal_edges_and_gaps_are_valid(self):
        p=payload();p['rules']=[{'label':'A','lower':'0.1','upper':'0.2'},{'label':'B','lower':'0.2','upper':'0.3'}];p=bg.validate(ADMIN,p)
        self.assertEqual([bg.classify(x,p) for x in [0.1,0.2,0.3]],['A','B','未归类'])
    def test_enum_duplicates_and_reserved_labels_rejected(self):
        for change in ['value','same_label','reserved','blank']:
            p=enumeration()
            if change=='value':p['rules'][1]['values']=['YE3']
            if change=='same_label':p['rules'][1]['label']='标准电机'
            if change=='reserved':p['rules'][1]['label']='未填写'
            if change=='blank':p['rules'][1]['values']=['']
            with self.assertRaises(ValidationError):bg.validate(ADMIN,p)
    def test_bounds_and_unknown_keys_limit_definition_size(self):
        for change in ['rules','values','code','note']:
            p=enumeration()
            if change=='rules':p['rules']=p['rules']*16
            if change=='values':p['rules'][0]['values']=[str(i) for i in range(501)]
            if change=='code':p['sql']='SELECT anything'
            if change=='note':p['note']=''
            with self.assertRaises(ValidationError):bg.validate(ADMIN,p)
    def test_field_modes_and_variable_units_rejected(self):
        for ds,field,mode in [('products','family','range'),('products','power_kw','enum'),('units','assembly_at','enum'),('bi_inventory','available_qty','range')]:
            p=payload();p.update(dataset=ds,field=field,mode=mode)
            with self.assertRaises(ValidationError):bg.validate(ADMIN,p)

class GroupIntegrationTests(PlatformCase):
    def setUp(self):
        super().setUp();self.client.force_login(self.admin)
        self.saved=bg.save(self.admin,{'code':'MOTOR.POWER','payload':payload()});self.ref=self.saved['versions'][0]['ref']
        self.d={'dimension':'power_kw','grain':'value','grouping_ref':self.ref,'metrics':[{'agg':'count'},{'agg':'sum','field':'price_cents'}],'chart':'bar'}
        for i,power in enumerate([1.5,7.5,15,22,None]):self.record('products',{'id':f'P{i}','power_kw':power,'family':'YE3','price_cents':100*(i+1)})
    def test_grouped_counts_amounts_rule_order_and_receipt(self):
        r=run_analysis(self.admin,'products',self.d)
        self.assertEqual([x['dimension'] for x in r['rows']],['小功率','中功率','大功率','未填写'])
        self.assertEqual([x['m0'] for x in r['rows']],[1,1,2,1]);self.assertEqual(sum(x['m1'] for x in r['rows']),1500)
        self.assertEqual(r['grouping_receipt']['payload'],bg.validate(self.admin,payload()));self.assertEqual(r['dimension_label'],'功率段')
    def test_preview_all_counts_and_exact_boundary_samples(self):
        r=self.post('/api/groupings/preview',payload()).json()
        self.assertEqual(r['total'],5);self.assertEqual(sum(x['count'] for x in r['rows']),5)
        self.assertEqual(next(x['samples'][0]['value'] for x in r['rows'] if x['label']=='中功率'),7.5)
    def test_evidence_group_and_filters_match_aggregate(self):
        definition={**self.d,'filters':[{'field':'power_kw','op':'gte','value':'7.5'}]}
        r=self.post('/api/analyze',{'dataset':'products','definition':definition}).json()
        e=self.post('/api/analyze/evidence',{'dataset':'products','definition':definition,'group':'大功率'}).json()
        self.assertEqual(e['total'],2);self.assertEqual(sum(x['row_count'] for x in r['rows']),3)
        self.assertEqual({x['values']['id'] for x in e['rows']},{'P2','P3'})
    def test_new_version_does_not_change_prior_result(self):
        before=run_analysis(self.admin,'products',self.d);p=payload();p['rules'][0]['upper']='10';p['rules'][1]['lower']='10'
        new=bg.save(self.admin,{'revision':1,'payload':p},self.saved['id']);self.assertEqual(new['versions'][0]['ref']['version'],2)
        self.assertEqual(run_analysis(self.admin,'products',self.d),before)
        changed=run_analysis(self.admin,'products',{**self.d,'grouping_ref':new['versions'][0]['ref']})
        self.assertEqual(changed['rows'][0]['row_count'],2)
    def test_reject_stale_version_unknown_fields_and_unchanged_save(self):
        url='/api/groupings/'+self.saved['id'];p=payload();p['note']='改变用途说明形成新版本'
        self.assertEqual(self.post(url,{'payload':p,'revision':0}).status_code,409)
        self.assertEqual(self.post(url,{'payload':payload(),'revision':1}).status_code,400)
        self.assertEqual(self.post(url,{'payload':p,'revision':1,'ignore':True}).status_code,400)
    def test_cannot_change_source_or_mode_across_versions(self):
        with self.assertRaises(ValidationError):bg.save(self.admin,{'revision':1,'payload':enumeration()},self.saved['id'])
    def test_personal_isolation_in_list_detail_and_analysis(self):
        other=User.objects.create_user('other');other.groups.add(Group.objects.get(name='admin'));self.client.force_login(other)
        self.assertEqual(self.client.get('/api/groupings').json()['rows'],[])
        self.assertEqual(self.client.get('/api/groupings/'+self.saved['id']).status_code,404)
        self.assertEqual(self.post('/api/analyze',{'dataset':'products','definition':self.d}).status_code,400)
    def test_field_permission_checked_again_after_role_change(self):
        p=payload();p['field']='price_cents';saved=bg.save(self.admin,{'code':'MONEY.BAND','payload':p})
        d={**self.d,'dimension':'price_cents','grouping_ref':saved['versions'][0]['ref'],'metrics':[{'agg':'count'}]}
        self.admin.groups.set([Group.objects.get(name='quality')])
        self.assertEqual(self.post('/api/analyze',{'dataset':'products','definition':d}).status_code,400)
        self.assertEqual(len(self.client.get('/api/groupings').json()['rows']),1)
    def test_reference_cannot_override_field_dataset_grain_or_hash(self):
        for d,ds in [({**self.d,'dimension':'family'},'products'),({**self.d,'grain':'month'},'products'),(self.d,'bi_units'),({**self.d,'grouping_ref':{**self.ref,'hash':'x'}},'products'),({**self.d,'grouping_ref':{**self.ref,'version':True}},'products')]:
            with self.assertRaises(ValidationError):validate_definition(self.admin,ds,d)
    def test_archive_keeps_old_models_and_restore_history(self):
        before=run_analysis(self.admin,'products',self.d)
        a=bg.archive(self.admin,self.saved['id'],{'revision':1,'archived':True});self.assertTrue(a['archived'])
        self.assertEqual(run_analysis(self.admin,'products',self.d),before)
        with self.assertRaises(ValidationError):bg.save(self.admin,{'revision':2,'payload':payload()},self.saved['id'])
        self.assertFalse(bg.archive(self.admin,self.saved['id'],{'revision':2,'archived':False})['archived'])
    def test_tampering_pauses_even_if_recipe_was_cached(self):
        run_analysis(self.admin,'products',self.d)
        v=BusinessGroupingVersion.objects.get(grouping_id=self.saved['id']);v.payload['name']='篡改';v.save()
        with self.assertRaises(ReviewConflict):run_analysis(self.admin,'products',self.d)
    def test_shared_model_rejected_and_private_save_preserves_ref(self):
        p={'name':'个人分类','dataset':'products','definition':self.d,'is_public':True}
        self.assertEqual(self.post('/api/models',p).status_code,400)
        p['is_public']=False;self.assertEqual(self.post('/api/models',p).json()['definition']['grouping_ref'],self.ref)
    def test_roles_auth_and_csrf(self):
        self.client.force_login(self.quality)
        self.assertEqual(self.post('/api/groupings',{'code':'ABC','payload':payload()}).status_code,403)
        self.assertEqual(self.post('/api/groupings/preview',payload()).status_code,403)
        c=Client(enforce_csrf_checks=True);c.force_login(self.admin)
        self.assertEqual(c.post('/api/groupings','{}',content_type='application/json').status_code,403)
        self.client.logout();self.assertEqual(self.client.get('/api/groupings').status_code,401)
    def test_audit_failure_rolls_back_both_version_and_revision(self):
        p=payload();p['name']='新名'
        with patch('app.business_groups.AuditEvent.objects.create',side_effect=RuntimeError('fail')):
            with self.assertRaises(RuntimeError):bg.save(self.admin,{'revision':1,'payload':p},self.saved['id'])
        self.assertEqual(BusinessGrouping.objects.get(pk=self.saved['id']).revision,1);self.assertEqual(BusinessGroupingVersion.objects.count(),1)
        self.assertEqual(Record.objects.count(),5)
    def test_topic_export_and_snapshot_pin_recipe_and_evidence(self):
        m=AnalysisModel.objects.create(name='功率',owner='admin',dataset='products',definition=self.d)
        t=Topic.objects.create(name='功率结构',owner='admin',layout=[{'model_id':m.pk,'span':2}])
        conf={'scope':{},'reference_scope':None,'primary_label':'当前','reference_label':'参照'};ctx=ws.context(self.admin,t.pk)
        run=ws.run(self.admin,t.pk,{'context_token':ctx['context_token'],'config':conf})
        rows,_=ws.export_rows(self.admin,t.pk,{'context_token':ctx['context_token'],'facts_token':run['facts_token'],'config':conf,'slot':0})
        self.assertIn('分组摘要',rows[0]);self.assertEqual(rows[1][rows[0].index('分组摘要')],self.ref['hash'])
        snap=ss.create(self.admin,t.pk,{'request_id':str(uuid.uuid4()),'context_token':ctx['context_token'],'facts_token':run['facts_token'],'config':conf,'name':'功率结构留存','note':'模拟固定业务分组的来源复核'})
        old=copy.deepcopy(snap.payload);p=payload();p['name']='另存新版';bg.save(self.admin,{'payload':p,'revision':1},self.saved['id'])
        self.assertEqual(ss.detail(self.admin,t.pk,snap.pk)['result'],old['result'])
        evidence=ss.evidence(self.admin,t.pk,snap.pk,{'slot':0,'side':'primary','page':1,'group':'大功率'})
        self.assertEqual(evidence['total'],2);self.assertEqual({r['values']['power_kw'] for r in evidence['rows']},{15,22})
        self.assertFalse(ss.compare_current(self.admin,t.pk,snap.pk).get('blocked'))
