import copy,csv,io,json,uuid
from unittest.mock import patch
from django.test import SimpleTestCase,Client
from django.core.exceptions import ValidationError
from django.core.cache import cache
from app import analysis_scatter as scatter,analysis_engine as eng,topic_workspace as ws,topic_snapshots as ss
from app.models import Record,AnalysisModel,Topic,AuditEvent
from app.import_review import ReviewConflict
from .test_platform import PlatformCase
from .test_derived import ADMIN,ROWS,definition,source_tables

def model():return {**definition(),'chart':'scatter','scatter':{'x':'m1','y':'d0'}}
class ScatterCalculationTests(SimpleTestCase):
    def calc(self,d=None,rows=None,ds='bi_work_orders',scope=None):
        with patch('app.analysis_engine.semantic.rows',return_value=ROWS if rows is None else rows),patch('app.bi_scope.analytics.tables',return_value=source_tables()),patch('app.analysis_pivot.receipt',return_value={}):return eng.run_analysis(ADMIN,ds,d or model(),scope)
    def test_one_point_per_group_derived_values_and_units(self):
        d=model();before=copy.deepcopy(d);r=self.calc(d);s=r['scatter'];self.assertEqual(d,before)
        self.assertEqual(s['axes']['x']['unit'],'台');self.assertEqual(s['axes']['y']['unit'],'元/台');self.assertEqual(len(s['points']),2)
        a=next(p for p in s['points'] if p['dimension']=='A');self.assertEqual((a['x'],a['y'],a['row_count']),(10,40,2));self.assertEqual(a['valid_inputs'],{'x':2,'y':2})
    def test_zero_denominator_kept_but_not_plotted(self):
        s=self.calc()['scatter'];p=next(p for p in s['points'] if not p['plotted']);self.assertEqual(p['x'],0);self.assertIsNone(p['y']);self.assertEqual(s['omitted'],1);self.assertIn('纵轴',p['reason'])
    def test_independent_axis_missingness_is_disclosed(self):
        d={**model(),'metrics':[{'agg':'avg','field':'total_cost_cents'},{'agg':'avg','field':'produced_qty'}],'derived':[],'display_metric':'m0','scatter':{'x':'m0','y':'m1'}}
        rows=[{**ROWS[0],'total_cost_cents':None},{**ROWS[1],'produced_qty':None}];p=self.calc(d,rows)['scatter']['points'][0]
        self.assertEqual(p['row_count'],2);self.assertEqual(p['valid_inputs'],{'x':1,'y':1});self.assertTrue(p['plotted'])
    def test_zero_negative_constant_and_empty(self):
        d={**model(),'metrics':[{'agg':'sum','field':'produced_qty'},{'agg':'sum','field':'total_cost_cents'}],'derived':[],'display_metric':'m0','scatter':{'x':'m0','y':'m1'}}
        p=self.calc(d,[{**ROWS[0],'produced_qty':0,'total_cost_cents':-5}])['scatter']['points'][0];self.assertTrue(p['plotted']);self.assertEqual((p['x'],p['y']),(0,-5));self.assertEqual(self.calc(d,[])['scatter']['points'],[])
    def test_overlapping_coordinates_keep_distinct_groups(self):
        rows=[{**ROWS[0],'family':x} for x in ['A','B','C']];s=self.calc(rows=rows)['scatter'];self.assertEqual(s['plotted'],3);self.assertEqual(len({p['key'] for p in s['points']}),3)
    def test_invalid_axes_shape_missing_dimension_and_non_numeric(self):
        for p in [None,{},[],{'x':[],'y':'m1'},{'x':'m1','y':'m1'},{'x':'m9','y':'m1'},{'x':'m1','y':'d0','sql':'x'}]:
            with self.subTest(p=p),self.assertRaises(ValidationError):self.calc({**model(),'scatter':p})
        for d in [{**model(),'dimension':''},{**model(),'chart':'bar'},{**model(),'pivot':{'dimension':'product_id'}},{**model(),'metrics':[{'agg':'min','field':'family'},{'agg':'count'}],'derived':[],'display_metric':'m0','scatter':{'x':'m0','y':'m1'}}]:
            with self.assertRaises(ValidationError):self.calc(d)
    def test_count_distinct_and_ratio_axes(self):
        d={**model(),'metrics':[{'agg':'count'},{'agg':'distinct','field':'product_id'}],'derived':[],'display_metric':'m0','scatter':{'x':'m0','y':'m1'}}
        s=self.calc(d)['scatter'];self.assertEqual(s['axes']['x']['unit'],'工单');self.assertEqual(s['axes']['y']['unit'],'配置')
        d['metrics'][1]={'agg':'ratio','field':'produced_qty','denominator':'planned_qty'}
        s=self.calc(d,[{**r,'planned_qty':20} for r in ROWS])['scatter'];self.assertEqual(s['axes']['y']['unit'],'%');self.assertEqual(s['points'][0]['y'],25)
    def test_dimensionally_invalid_ratio_rejected(self):
        d={**model(),'metrics':[{'agg':'count'},{'agg':'ratio','field':'total_cost_cents','denominator':'produced_qty'}],'derived':[],'display_metric':'m0','scatter':{'x':'m0','y':'m1'}}
        with self.assertRaises(ValidationError):self.calc(d)
    def test_unit_conflict_on_second_axis_even_first_is_count(self):
        d={'dimension':'category','chart':'scatter','metrics':[{'agg':'count'},{'agg':'sum','field':'balance_qty'}],'scatter':{'x':'m0','y':'m1'}}
        rows=[{'id':'I1','category':'A','unit':'件','balance_qty':2},{'id':'I2','category':'B','unit':'kg','balance_qty':3}]
        with self.assertRaises(ValidationError):self.calc(d,rows,'bi_inventory')
        rows[1]['unit']='件';self.assertEqual(self.calc(d,rows,'bi_inventory')['scatter']['axes']['y']['unit'],'件')
        rows[1]['unit']=None
        with self.assertRaises(ValidationError):self.calc(d,rows,'bi_inventory')
    def test_maximum_groups_rejects_no_truncation(self):
        with self.assertRaises(ValidationError):self.calc(rows=[{**ROWS[0],'family':str(i)} for i in range(1001)])
    def test_colliding_display_names_rejected(self):
        with self.assertRaises(ValidationError):self.calc(rows=[{**ROWS[0],'family':None},{**ROWS[0],'family':'未填写'}])
    def test_unknown_quantity_unit_does_not_claim_comparability(self):
        d={'dimension':'family','chart':'scatter','metrics':[{'agg':'count'},{'agg':'sum','field':'unregistered'}],'scatter':{'x':'m0','y':'m1'}}
        with self.assertRaises(ValidationError):scatter.unit('unknown',d,{'unregistered':{'name':'unregistered','type':'float','label':'未登记数量'}},[],'m1',[{'unregistered':1}])
    def test_scope_filters_and_sort_apply(self):
        r=self.calc({**model(),'filters':[{'field':'produced_qty','op':'gte','value':1}]},scope={'family':'A'});self.assertEqual(r['matched'],2);self.assertEqual(len(r['scatter']['points']),1)
    def test_unknown_point_no_fallback_and_export_keeps_omitted(self):
        r=self.calc()
        for k in [None,'missing',1]:
            with self.assertRaises(ValidationError):scatter.selection(r,k)
        exported=scatter.export_rows(r);self.assertEqual(len(exported),3);self.assertFalse(exported[-1][-2])
    def test_code_or_source_drift_during_calculation_rejected(self):
        with patch('app.analysis_engine.semantic.rows',return_value=ROWS),patch('app.bi_scope.analytics.tables',return_value=source_tables()),patch('app.analysis_pivot.receipt',side_effect=[{'v':1},{'v':2}]):
            with self.assertRaises(ReviewConflict):eng.run_analysis(ADMIN,'bi_work_orders',model())

class ScatterAPITests(PlatformCase):
    def setUp(self):
        super().setUp();self.client.force_login(self.admin)
        self.d={'dimension':'family','metrics':[{'agg':'count'},{'agg':'avg','field':'price_cents'}],'chart':'scatter','scatter':{'x':'m0','y':'m1'}}
        self.p={'dataset':'products','definition':self.d,'scope':{},'path':[]}
        for i,f in enumerate(['YE3','YE3','YE4']):self.record('products',{'id':f'P{i}','family':f,'model':'M'+str(i%2),'price_cents':100+i*100})
    def result(self):
        r=self.post('/api/analyze',self.p);self.assertEqual(r.status_code,200,r.content);return r.json()
    def ev(self,r,**extra):return self.post('/api/analyze/scatter/evidence',{**self.p,'revision':r['scatter']['revision'],'selection':r['scatter']['points'][0]['key'],**extra})
    def export(self,r,**extra):return self.post('/api/analyze/scatter/export',{**self.p,'revision':r['scatter']['revision'],'kind':'result',**extra})
    def test_point_evidence_count_and_excel_rows(self):
        r=self.result();d=self.ev(r);self.assertEqual(d.status_code,200,d.content);self.assertEqual(d.json()['total'],2);self.assertEqual(d.json()['rows'][0]['source']['file'],'unit-test.xlsx');self.assertEqual(d['Cache-Control'],'no-store')
    def test_requires_receipt_changed_data_scope_and_code(self):
        r=self.result();self.assertEqual(self.ev(r,revision=None).status_code,400);self.assertEqual(self.ev(r,scope={'family':'YE3'}).status_code,409)
        self.record('products',{'id':'P9','family':'YE3','price_cents':1});self.assertEqual(self.ev(r).status_code,409);self.assertEqual(self.export(r).status_code,409)
        r=self.result()
        with patch('app.metric_registry.calculation_hash',return_value='changed'):self.assertEqual(self.ev(r).status_code,409)
    def test_unknown_selection_payload_and_page_rejected(self):
        r=self.result()
        for extra in [{'selection':None},{'selection':'bad'},{'page':True},{'page':0},{'path':['YE3']},{'sql':'x'}]:
            with self.subTest(extra=extra):self.assertEqual(self.ev(r,**extra).status_code,400)
    def test_auth_field_role_csrf(self):
        r=self.result();self.client.force_login(self.quality);self.assertEqual(self.ev(r).status_code,400);self.client.logout();self.assertEqual(self.ev(r).status_code,401)
        secure=Client(enforce_csrf_checks=True);secure.force_login(self.admin);self.assertEqual(secure.post('/api/analyze/scatter/evidence',json.dumps(self.p),content_type='application/json').status_code,403)
    def test_full_export_and_selected_source(self):
        r=self.result();before=list(Record.objects.values());out=self.export(r);self.assertEqual(out.status_code,200,out.content);file=self.client.get(out.json()['download_url']);rows=list(csv.reader(io.StringIO(file.content.decode('utf-8-sig'))));self.assertEqual(out.json()['rows'],2);self.assertEqual(rows[4][0],'YE3');self.assertEqual(rows[4][1:5],['2','配置','150','分/台']);self.assertEqual(before,list(Record.objects.values()))
        point=r['scatter']['points'][0];d=self.export(r,kind='evidence',selection=point['key']).json();self.assertEqual(d['rows'],2);text=self.client.get(d['download_url']).content.decode('utf-8-sig');self.assertNotIn('P2',text)
    def test_export_unknown_mode_audit_failure_and_formula_escaping(self):
        r=self.result();self.assertEqual(self.export(r,kind='bad').status_code,400)
        with patch('app.analysis_scatter_views.AuditEvent.objects.create',side_effect=ValueError('failed')),patch('app.analysis_scatter_views.cache.set') as setter:
            self.assertEqual(self.export(r).status_code,400);setter.assert_not_called()
        self.record('products',{'id':'PX','family':'=1+1','price_cents':1});r=self.result();d=self.export(r).json();self.assertIn("'=1+1",self.client.get(d['download_url']).content.decode('utf-8-sig'))
    def test_download_identity_role_and_expiry(self):
        r=self.result();d=self.export(r).json();self.client.force_login(self.quality);self.assertEqual(self.client.get(d['download_url']).status_code,400);self.client.force_login(self.admin)
        with patch('app.analysis_explore_views.access.role',return_value='viewer'):self.assertEqual(self.client.get(d['download_url']).status_code,400)
        cache.delete('analysis-export:'+d['download_url'].split('/')[-1]);self.assertEqual(self.client.get(d['download_url']).status_code,400)
    def topic(self):
        m=AnalysisModel.objects.create(name='散点',dataset='products',definition=self.d,owner='admin');t=Topic.objects.create(name='散点专题',owner='admin',layout=[{'model_id':m.pk,'span':2}]);ctx=ws.context(self.admin,t.pk);conf={'scope':{},'reference_scope':{'family':'YE3'},'primary_label':'A','reference_label':'B'};r=ws.run(self.admin,t.pk,{'context_token':ctx['context_token'],'config':conf});return t,ctx,conf,r
    def test_saved_model_topic_two_ranges_and_export_coordinates(self):
        saved=self.post('/api/models',{'name':'双轴模型','dataset':'products','definition':self.d,'is_public':False});self.assertEqual(saved.status_code,200,saved.content);self.assertEqual(saved.json()['definition']['scatter'],self.d['scatter'])
        t,ctx,conf,r=self.topic();c=r['cards'][0];self.assertEqual(c['primary']['scatter']['plotted'],2);self.assertEqual(c['reference']['scatter']['plotted'],1)
        rows,_=ws.export_rows(self.admin,t.pk,{'context_token':ctx['context_token'],'facts_token':r['facts_token'],'config':conf,'slot':0});self.assertEqual(len(rows),4);self.assertIn('分析定义',rows[0]);self.assertIn('横轴完整输入行数',rows[0])
    def test_snapshot_keeps_coordinates_and_frozen_source(self):
        t,ctx,conf,r=self.topic();s=ss.create(self.admin,t.pk,{'request_id':str(uuid.uuid4()),'context_token':ctx['context_token'],'facts_token':r['facts_token'],'config':conf,'name':'散点冻结','note':'保存模拟散点坐标和全部来源'});before=copy.deepcopy(s.payload)
        rec=Record.objects.get(business_key='P0');rec.values['price_cents']=999;rec.revision+=1;rec.save()
        d=ss.evidence(self.admin,t.pk,s.pk,{'slot':0,'side':'primary','group':'YE3','page':1});self.assertEqual(d['total'],2);self.assertNotEqual(d['rows'][0]['values']['price_cents'],999)
        self.assertEqual(len(ss.export_rows(s)),7);s.refresh_from_db();self.assertEqual(s.payload,before)
        c=ss.compare_current(self.admin,t.pk,s.pk);self.assertFalse(c['blocked']);self.assertTrue(c['cards'][0]['comparison']['rows'])
