from copy import deepcopy
from unittest.mock import patch
from django.test import SimpleTestCase
from django.core.exceptions import ValidationError
from app.analysis_engine import run_analysis,validate_definition
from app.derived_metrics import compile_definitions
from app.models import Record
from app.schema import SCHEMAS
from tests.test_platform import PlatformCase

def definition():
    return {'dimension':'family','metrics':[{'agg':'sum','field':'total_cost_cents','label':'暂估总成本（分）'},
      {'agg':'sum','field':'produced_qty','label':'装配台数'}],
      'derived':[{'label':'暂估单位成本','expression':'m0 / m1','unit':'元/台'}],
      'display_metric':'d0','chart':'bar','sort':'desc'}

ROWS=[{'id':'W1','product_id':'P1','family':'A','total_cost_cents':10000,'produced_qty':1},
      {'id':'W2','product_id':'P1','family':'A','total_cost_cents':30000,'produced_qty':9},
      {'id':'W3','product_id':'P2','family':'B','total_cost_cents':1000,'produced_qty':0}]
def source_tables():
    tables={key:[] for key in SCHEMAS};tables['products']=[{'id':'P1','family':'A'},{'id':'P2','family':'B'}];tables['work_orders']=deepcopy(ROWS)
    return tables

ADMIN=type('Admin',(),{'is_authenticated':True,'is_active':True,'is_superuser':True})()

class DerivedArithmeticTests(SimpleTestCase):
    def run_model(self,d=None,rows=None,dataset='bi_work_orders',scope=None):
        with patch('app.analysis_engine.semantic.rows',return_value=ROWS if rows is None else rows),patch('app.bi_scope.analytics.tables',return_value=source_tables()):
            return run_analysis(ADMIN,dataset,d or definition(),scope)
    def test_group_quotient_not_average_of_unit_costs(self):
        r=self.run_model();self.assertEqual(r['rows'][0]['d0'],40)
        self.assertNotEqual(r['rows'][0]['d0'],(100+300/9)/2)
        self.assertEqual(r['display_metric'],'d0');self.assertEqual(r['measures'][2]['dependencies'],['m0','m1'])
    def test_zero_denominator_null_and_last_in_both_sort_orders(self):
        for sort in ['asc','desc']:
            d=definition();d['sort']=sort;r=self.run_model(d)
            self.assertEqual(r['rows'][-1]['dimension'],'B');self.assertIsNone(r['rows'][-1]['d0'])
            self.assertEqual(r['derived_notes'][0]['reason'],'分母为零')
    def test_any_missing_input_pauses_derived_without_erasing_basic_aggregate(self):
        rows=deepcopy(ROWS);rows[1]['produced_qty']=None;r=self.run_model(rows=rows)
        a=next(x for x in r['rows'] if x['dimension']=='A')
        self.assertEqual(a['m0'],40000);self.assertEqual(a['m1'],1);self.assertIsNone(a['d0'])
    def test_percentage_output_converts_once(self):
        d=definition();d['metrics'][0]['field']='released_qty';d['derived'][0].update(label='放行覆盖',unit='%')
        r=self.run_model(d,[dict(id='1',family='A',released_qty=2,produced_qty=5)])
        self.assertEqual(r['rows'][0]['d0'],40)
    def test_rejects_money_plus_motor_and_incorrect_output_unit(self):
        for expr,unit in [('m0+m1','元'),('m0/m1','%'),('m0-m1','台')]:
            d=definition();d['derived'][0].update(expression=expr,unit=unit)
            with self.assertRaises(ValidationError):self.run_model(d)
    def test_ast_forbids_code_attributes_power_booleans_and_derived_chains(self):
        for expr in ['__import__("os")','m0.__class__','m0[0]','m0 ** 999','True * m0',
                     'm0 if m1 else 0','[m0]','d0 / m1','m4 / m1','m0 // m1','m0 % m1','1e999*m0']:
            d=definition();d['derived'][0]['expression']=expr
            with self.subTest(expr=expr),self.assertRaises(ValidationError):self.run_model(d)
    def test_bounded_expressions_and_result_overflow(self):
        d=definition();d['derived'][0]['expression']='m0'+('*1'*30)
        with self.assertRaises(ValidationError):self.run_model(d)
        d['derived'][0]['expression']='m0 / m1 * 1000000000 * 1000000000'
        r=self.run_model(d);self.assertIsNone(r['rows'][0]['d0']);self.assertIn('范围',r['derived_notes'][0]['reason'])
    def test_formulas_support_parentheses_constants_and_time_conversion(self):
        d={'dimension':'workshop','metrics':[{'agg':'sum','field':'downtime_minutes'}, {'agg':'sum','field':'fault_minutes'}],
           'derived':[{'label':'其他停机小时','expression':'(m0 - m1) * 0.5 + (m0 - m1) / 2','unit':'小时'}]}
        r=self.run_model(d,[dict(id='1',workshop='A',downtime_minutes=120,fault_minutes=30)],'bi_equipment_day')
        self.assertEqual(r['rows'][0]['d0'],1.5)
    def test_selected_metric_drives_sort_and_donut_restriction(self):
        d=definition();d['display_metric']='m1';r=self.run_model(d);self.assertEqual(r['rows'][0]['m1'],10)
        d['display_metric']='d9'
        with self.assertRaises(ValidationError):self.run_model(d)
        d.update(display_metric='d0',chart='donut')
        with self.assertRaises(ValidationError):self.run_model(d)
    def test_units_unknown_and_non_numeric_measures_are_rejected(self):
        for agg,field in [('sum','power_kw'),('max','family')]:
            d=definition();d['metrics'][0].update(agg=agg,field=field)
            with self.assertRaises(ValidationError):self.run_model(d)
    def test_dynamic_quantities_cancel_but_mixed_units_do_not_sum(self):
        d={'dimension':'unit','metrics':[{'agg':'sum','field':'available_qty'},{'agg':'sum','field':'balance_qty'}],
           'derived':[{'label':'可用比例','expression':'m0 / m1','unit':'%'}],'display_metric':'d0','chart':'bar'}
        rows=[dict(id='1',unit='kg',available_qty=5,balance_qty=10),dict(id='2',unit='件',available_qty=3,balance_qty=3)]
        r=self.run_model(d,rows,'bi_inventory');self.assertEqual([x['d0'] for x in r['rows']],[50,100])
        d['dimension']=''
        with self.assertRaises(ValidationError):self.run_model(d,rows,'bi_inventory')
    def test_resource_invalid_state_cannot_be_bypassed_by_custom_formula(self):
        d={'metrics':[{'agg':'sum','field':'busy_minutes'},{'agg':'sum','field':'available_minutes'}],
           'derived':[{'label':'占用比例','expression':'m0/m1','unit':'%'}]}
        r=self.run_model(d,[dict(id='1',busy_minutes=30,available_minutes=60,integrity='异常')],'bi_resource_day')
        self.assertIsNone(r['rows'][0]['d0']);self.assertIn('资源',r['derived_notes'][0]['reason'])
    def test_scope_and_empty_population_are_preserved(self):
        r=self.run_model(scope={'family':'A'});self.assertEqual(r['matched'],2);self.assertEqual(r['rows'][0]['d0'],40)
        r=self.run_model(scope={'family':'不存在'});self.assertEqual(r['rows'],[]);self.assertEqual(r['derived_notes'],[])
    def test_three_formulas_have_stable_keys_and_percent_base_scale(self):
        d=definition();d['metrics']=[{'agg':'ratio','field':'released_qty','denominator':'produced_qty'}]
        d['derived']=[{'label':'百分数','expression':'m0','unit':'%'},{'label':'比例','expression':'m0','unit':'倍'},
                      {'label':'两倍百分数','expression':'m0 * 2','unit':'%'}];d['display_metric']='d1'
        r=self.run_model(d,[dict(id='1',family='A',released_qty=2,produced_qty=5)])
        self.assertEqual([r['rows'][0][f'd{i}'] for i in range(3)],[40,.4,80])
        d['derived'].append(d['derived'][0])
        with self.assertRaises(ValidationError):self.run_model(d)

class DerivedIntegrationTests(PlatformCase):
    def test_save_reload_topic_permissions_and_optimistic_version(self):
        self.client.force_login(self.admin)
        payload={'name':'暂估单位成本','dataset':'bi_work_orders','definition':definition(),'is_public':True}
        saved=self.post('/api/models',payload);self.assertEqual(saved.status_code,200);m=saved.json()
        self.assertEqual(m['definition'],payload['definition'])
        t=self.post('/api/topics',{'name':'成本公式专题','layout':[{'model_id':m['id'],'span':2}],'is_public':True})
        self.assertEqual(t.status_code,200)
        self.assertEqual(self.checked_model_update(m,name='改名').status_code,200)
        self.assertEqual(self.post('/api/models',m).status_code,409)
        self.client.force_login(self.quality)
        self.assertEqual(self.client.get('/api/models').json(),[])
        self.assertEqual(self.post('/api/analyze',payload).status_code,400)
        self.assertEqual(self.post('/api/analyze/evidence',payload).status_code,400)
        self.assertEqual(Record.objects.count(),0)
    def test_evidence_uses_same_scope_group_and_only_authorized_fields(self):
        self.client.force_login(self.admin);d=definition();data={'dataset':'bi_work_orders','definition':d,'scope':{'family':'A'},'group':'A'}
        with patch('app.analysis_engine.semantic.rows',return_value=deepcopy(ROWS)),patch('app.bi_scope.analytics.tables',return_value=source_tables()):
            result=self.post('/api/analyze',data);evidence=self.post('/api/analyze/evidence',data)
        self.assertEqual(result.status_code,200);self.assertEqual(evidence.status_code,200)
        self.assertEqual(result.json()['matched'],evidence.json()['total']);self.assertEqual(evidence.json()['total'],2)
    def test_published_reference_cannot_take_unreviewed_formula(self):
        d=definition();d.update(metric_ref={'key':'ANY','version':1},metrics=[])
        with self.assertRaisesMessage(ValidationError,'未审核派生公式'):validate_definition(self.admin,'bi_work_orders',d)
