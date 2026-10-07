import copy,json,csv,io,uuid
from unittest.mock import patch
from decimal import Decimal
from django.contrib.auth.models import User,Group
from django.core.exceptions import ValidationError,PermissionDenied
from django.test import Client
from app import cost_scenarios as cs
from app.models import Record,CostScenario,AuditEvent
from app.import_review import ReviewConflict
from tests.test_platform import PlatformCase

class CostScenarioTests(PlatformCase):
    def setUp(self):
        super().setUp();self.client.force_login(self.admin)
        self.record('products',{'id':'P1','family':'YE4','model':'YE4-TEST'})
        self.record('materials',{'id':'M1','name':'铜线','category':'铜线','unit':'kg','unit_cost_cents':333})
        self.record('materials',{'id':'M2','name':'轴','category':'轴','unit':'件','unit_cost_cents':125})
        for wo,qty in [('W1',2),('W2',3),('W3',0)]:
            self.record('work_orders',{'id':wo,'product_id':'P1','planned_end':'2026-09-25','planned_qty':qty or 10})
            for i in range(qty):self.record('units',{'id':f'{wo}-SN{i}','work_order_id':wo,'product_id':'P1','assembly_at':'2026-09-25T10:00:00'})
        for key,wo,mat,qty in [('L1','W1','M1',-1.005),('L2','W1','M2',-2),('L3','W2','M1',-2)]:
            self.record('inventory_movements',{'id':key,'work_order_id':wo,'material_id':mat,'occurred':'2026-09-24T10:00:00','movement':'生产领料','qty_signed':qty})
        for wo,values in [('W1',[585,101,202,3]),('W2',[666,150,100,7])]:
            for category,value in zip(cs.COST_TYPES,values):self.record('costs',{'id':f'{wo}-{category}','work_order_id':wo,'category':category,'amount_cents':value,'occurred':'2026-09-25','status':'暂估未结账','basis':'模拟依据'})
    def base(self,user=None):return cs.current_baseline(user or self.admin,{})
    def params(self,b):return [{'name':name,'material_rates':{k:('10' if i==0 and k=='铜线' else '0') for k in b['categories']},'labor_rate':'-5' if i==0 else '0','overhead_rate':'0'} for i,name in enumerate(['价格压力','保持基线'])]
    def input(self,b=None,parent_id=None):
        b=b or self.base();return {'scope':b['scope'],'parent_id':str(parent_id) if parent_id else None,'baseline_token':cs.digest(b),'assumptions':self.params(b)}
    def save(self,body=None):
        data=body or self.input();run=cs.evaluate(self.admin,data)
        return cs.save(self.admin,{'request_id':str(uuid.uuid4()),'name':'成本情景测试','note':'模拟价格敏感性试算用途','input':data,'calculation_token':run['calculation_token']})
    def change(self,key,**values):
        r=Record.objects.get(business_key=key);r.values.update(values);r.save();return r
    def test_baseline_reconciles_and_inactive_orders_are_visible(self):
        b=self.base();t=cs.public_baseline(b)['totals']
        self.assertEqual(t,{'selected':3,'eligible':2,'excluded':1,'produced_qty':5,'base_cents':1814})
        self.assertEqual(b['problems'],[]);self.assertEqual(len(b['sources']),22)
        self.assertEqual(b['rows'][0]['material_recomputed_cents'],585)
        self.assertFalse(b['rows'][2]['eligible']);self.assertIn('不推算未来',b['rows'][2]['excluded_reason'])
    def test_individual_rounding_and_delta_bridge_reconcile(self):
        out=cs.evaluate(self.admin,self.input());a,b=out['results']
        self.assertEqual((a['totals']['scenario_cents'],a['totals']['delta_cents']),(1902,88))
        self.assertEqual(a['rows'][0]['scenario_cents'],919);self.assertEqual(a['rows'][1]['scenario_cents'],983)
        self.assertEqual(sum(r['delta_cents'] for r in a['bridge']),88)
        self.assertEqual(a['totals']['baseline_unit_yuan'],3.628);self.assertEqual(a['totals']['scenario_unit_yuan'],3.804)
        self.assertEqual(b['totals']['scenario_cents'],1814);self.assertEqual(b['totals']['delta_cents'],0)
        self.assertEqual(a['by_config'][0]['qty'],5)
    def test_zero_assumptions_reproduce_all_lines_exactly(self):
        b=self.base();params=self.params(b)
        for c in params:c['material_rates']={k:'0' for k in b['categories']};c['labor_rate']='0'
        for result in cs.simulate(b,cs.assumptions(params,b['categories'])):
            self.assertEqual(result['totals']['delta_cents'],0)
            self.assertTrue(all(r['delta_cents']==0 for r in result['rows']))
            self.assertTrue(all(x['delta_cents']==0 for r in result['rows'] for x in r['material_lines']))
    def test_bad_scope_and_unknown_product_do_not_fall_back(self):
        for s in [{'family':'unknown'},{'product_id':'missing'},{'from':'2026-09-30','to':'2026-09-20'},{'customer_id':'C1'},{'from':'20260925'}]:
            with self.assertRaises((ValueError,ValidationError)):cs.current_baseline(self.admin,s)
        b=cs.current_baseline(self.admin,{'from':'2027-01-01'});self.assertEqual(cs.public_baseline(b)['totals']['selected'],0)
        with self.assertRaises(ValidationError):cs.simulate(b,cs.assumptions(self.params(b),b['categories']))
    def test_future_events_excluded_from_fixed_cutoff(self):
        self.record('costs',{'id':'FUTURE','work_order_id':'W1','category':'材料','amount_cents':999,'occurred':'2026-10-02','status':'未来','basis':'未来事件'})
        self.assertEqual(cs.public_baseline(self.base())['totals']['base_cents'],1814)
        self.assertNotIn(cs.digest(['costs','FUTURE']),self.base()['sources'])
    def test_mismatch_blocks_entire_scenario_not_just_bad_order(self):
        self.change('W1-材料',amount_cents=586);b=self.base()
        self.assertIn('领料参考金额与材料归集金额不一致',[x['message'] for x in b['problems']])
        with self.assertRaises(ValidationError):cs.evaluate(self.admin,self.input(b))
        self.assertFalse(CostScenario.objects.exists())
    def test_missing_cost_category_is_not_zero(self):
        Record.objects.get(business_key='W1-返工增耗').delete();b=self.base()
        self.assertTrue(any('四类成本' in x['message'] for x in b['problems']))
    def test_return_or_unknown_movement_blocks_unsupported_revaluation(self):
        self.change('L1',movement='生产退料',qty_signed=1.005);b=self.base()
        self.assertTrue(any('不支持关联' in x['message'] for x in b['problems']))
    def test_fractional_pieces_wrong_sign_missing_material_and_units_rejected(self):
        for values in [{'qty_signed':-1.5},{'qty_signed':2},{'material_id':'missing'}]:
            original=copy.deepcopy(Record.objects.get(business_key='L2').values);self.change('L2',**values)
            self.assertTrue(self.base()['problems']);self.change('L2',**original)
        self.change('M2',unit='吨');self.assertTrue(any('单位未适配' in x['message'] for x in self.base()['problems']))
    def test_zero_output_with_cost_does_not_generate_unit_cost(self):
        for r in Record.objects.filter(dataset='units',business_key__startswith='W1'):r.delete()
        b=self.base();self.assertTrue(any('没有装配台数' in x['message'] for x in b['problems']))
    def test_negative_or_nonfinite_amounts_and_prices_are_blocked(self):
        for key,field,val in [('W1-直接人工','amount_cents',-1),('M1','unit_cost_cents',0)]:
            original=copy.deepcopy(Record.objects.get(business_key=key).values);self.change(key,**{field:val});self.assertTrue(self.base()['problems']);self.change(key,**original)
        for value in ['NaN','Infinity',True,'1e999']:
            with self.assertRaises(ValidationError):cs.number(value,'测试')
    def test_assumptions_reject_unknown_keys_outliers_precision_and_code(self):
        b=self.base()
        for value in ['-80.01','200.01','0.001','NaN','Infinity','1+1',True,10]:
            data=self.params(b);data[0]['labor_rate']=value
            with self.assertRaises(ValidationError):cs.assumptions(data,b['categories'])
        data=self.params(b);data[0]['material_rates']['不存在']='1'
        with self.assertRaises(ValidationError):cs.assumptions(data,b['categories'])
        data=self.params(b);data[1]['name']=data[0]['name']
        with self.assertRaises(ValidationError):cs.assumptions(data,b['categories'])
    def test_roles_protected_and_finance_never_sees_personnel(self):
        finance=User.objects.create_user('finance');finance.groups.add(Group.objects.create(name='finance'))
        b=self.base(finance);self.assertNotIn('labor_entries',str(b['sources']));self.assertNotIn('employee_id',json.dumps(b))
        with self.assertRaises(PermissionDenied):self.base(self.quality)
        self.client.force_login(self.quality);self.assertEqual(self.client.get('/api/cost-scenarios').status_code,403)
        self.assertEqual(self.post('/api/cost-scenarios/baseline',{'scope':{},'parent_id':None}).status_code,403)
    def test_immutable_save_and_export_uses_frozen_data(self):
        saved=self.save();original=copy.deepcopy(saved.payload);self.change('W1-直接人工',amount_cents=1000)
        self.assertEqual(cs.get(self.admin,saved.pk).payload,original)
        with self.assertRaises(ValidationError):saved.save()
        self.assertEqual(self.post('/api/cost-scenarios/'+str(saved.pk),{}).status_code,405)
        response=self.client.get(f'/api/cost-scenarios/{saved.pk}/export');rows=list(csv.DictReader(io.StringIO(response.content.decode('utf-8-sig'))))
        self.assertEqual(len(rows),4);self.assertEqual(rows[0]['基线金额分'],'891');self.assertEqual(rows[0]['假设金额分'],'919')
        doc=self.client.get(f'/api/cost-scenarios/{saved.pk}/export?format=json').json();self.assertEqual(cs.digest(doc['payload']),doc['payload_hash'])
    def test_child_reuses_saved_baseline_after_current_data_changes(self):
        saved=self.save();old=saved.payload['baseline'];self.change('W1-直接人工',amount_cents=1000)
        body=self.input(old,saved.pk);body['assumptions'][0]['labor_rate']='0';child=self.save(body)
        self.assertEqual(child.parent_id,saved.pk);self.assertEqual(child.payload['baseline'],old)
        self.assertEqual(child.payload['results'][0]['totals']['scenario_cents'],1914)
        self.assertEqual(CostScenario.objects.count(),2)
    def test_saved_baseline_cannot_silently_change_scope_or_model(self):
        saved=self.save()
        with self.assertRaises(ValidationError):cs.baseline(self.admin,{'scope':{'family':'YE4'},'parent_id':str(saved.pk)})
        with patch('app.cost_scenarios.calculation_hash',return_value='changed'):
            with self.assertRaises(ReviewConflict):cs.baseline(self.admin,{'scope':{},'parent_id':str(saved.pk)})
            self.assertEqual(cs.get(self.admin,saved.pk).payload_hash,saved.payload_hash)
    def test_stale_baseline_or_result_blocks_save(self):
        data=self.input();self.change('W1-直接人工',amount_cents=1000)
        with self.assertRaises(ReviewConflict):cs.evaluate(self.admin,data)
        data=self.input();run=cs.evaluate(self.admin,data)
        with self.assertRaises(ReviewConflict):cs.save(self.admin,{'request_id':str(uuid.uuid4()),'name':'错误值','note':'故意使用过期结果','input':data,'calculation_token':'wrong'})
        self.assertFalse(CostScenario.objects.exists())
    def test_idempotent_save_retries_and_different_content_rejected(self):
        data=self.input();run=cs.evaluate(self.admin,data);request={'request_id':str(uuid.uuid4()),'name':'同一申请','note':'重试相同试算结果','input':data,'calculation_token':run['calculation_token']}
        saved=cs.save(self.admin,request);self.change('W1-直接人工',amount_cents=999)
        self.assertEqual(cs.save(self.admin,request).pk,saved.pk);self.assertEqual(CostScenario.objects.count(),1)
        with self.assertRaises(ReviewConflict):cs.save(self.admin,{**request,'name':'改名'})
    def test_owner_isolation_and_permission_revocation(self):
        saved=self.save();other=User.objects.create_user('other');other.groups.add(Group.objects.get(name='admin'));self.client.force_login(other)
        self.assertEqual(self.client.get(f'/api/cost-scenarios/{saved.pk}').status_code,404);self.assertEqual(cs.options(other)['saved'],[])
        self.admin.groups.clear();self.admin.groups.add(Group.objects.get(name='quality'))
        with self.assertRaises(PermissionDenied):cs.get(self.admin,saved.pk)
    def test_integrity_metadata_and_payload_protected(self):
        saved=self.save();CostScenario.objects.filter(pk=saved.pk).update(note='被改写')
        with self.assertRaises(ReviewConflict):cs.get(self.admin,saved.pk)
    def test_audit_failure_rolls_back_save(self):
        with patch('app.cost_scenarios.AuditEvent.objects.create',side_effect=RuntimeError('audit unavailable')):
            with self.assertRaises(RuntimeError):self.save()
        self.assertFalse(CostScenario.objects.exists())
    def test_csrf_auth_and_source_pages(self):
        secure=Client(enforce_csrf_checks=True);secure.force_login(self.admin)
        self.assertEqual(secure.post('/api/cost-scenarios/save','{}',content_type='application/json').status_code,403)
        saved=self.save();d=cs.evidence(self.admin,{'work_order_id':'W1','page':1},saved.pk)
        self.assertEqual(d['row']['material_recomputed_cents'],585);self.assertEqual(d['sources'][0]['filename'],'unit-test.xlsx')
        self.assertEqual(cs.evidence(self.admin,{'work_order_id':'W1','page':2},saved.pk)['sources'],[])
        for args in [{'work_order_id':'missing','page':1},{'work_order_id':'W1','page':True}]:
            with self.assertRaises(ValidationError):cs.evidence(self.admin,args,saved.pk)
        self.client.logout();self.assertEqual(self.client.get('/api/cost-scenarios').status_code,401)
    def test_readonly_preview_never_writes_facts_or_saved_runs(self):
        before=list(Record.objects.values_list('id','values','revision'));cs.evaluate(self.admin,self.input())
        self.assertEqual(before,list(Record.objects.values_list('id','values','revision')));self.assertFalse(CostScenario.objects.exists())
    def test_baseline_changes_during_source_capture_are_rejected(self):
        original=cs.sources
        def changed(*args):
            value=original(*args);self.change('W1-直接人工',amount_cents=777);return value
        with patch('app.cost_scenarios.sources',side_effect=changed):
            with self.assertRaises(ReviewConflict):self.base()
        self.assertEqual(Record.objects.get(business_key='W1-直接人工').values['amount_cents'],101)
