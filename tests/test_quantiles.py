"""Independent known quantiles and cross-surface regression, with isolated fixtures."""
import copy,csv,io,json,uuid
from decimal import Decimal
from unittest.mock import patch
from django.test import SimpleTestCase,Client
from django.core.exceptions import ValidationError
from app import analysis_quantiles as q,analysis_engine as eng,analysis_pivot as pv,topic_workspace as ws,topic_snapshots as ss
from app.models import AnalysisModel,Topic,Record
from .test_platform import PlatformCase
from .test_derived import ADMIN,ROWS,source_tables
from .test_metric_registry import payload

class QuantileMathTests(SimpleTestCase):
    fields={'value':{'type':'float'}}
    def calc(self,values,p=50,agg='percentile',**extra):
        m={'agg':agg,'field':'value',**({'percentile':p} if agg=='percentile' else {}),**extra};q.validate(m,self.fields)
        return q.calculate('sample',m,self.fields,[{'value':v} for v in values])
    def test_known_linear_quantiles_and_endpoints(self):
        for p,expected in [(0,-10),(25,-2.5),(50,5),(75,32.5),(90,73),(95,86.5),(100,100)]:
            with self.subTest(p=p):self.assertEqual(self.calc([-10,0,10,100],p)[0],Decimal(str(expected)))
    def test_median_even_odd_repeated_one_and_null(self):
        for values,expected in [([10,20],15),([9,1,4],4),([2,2,2],2),([None,8],8),([None,None],None),([],None)]:
            with self.subTest(values=values):self.assertEqual(self.calc(values,agg='median')[0],expected)
    def test_fractional_percent_and_metadata(self):
        v,info=self.calc([0,10,None],12.5);self.assertEqual(v,Decimal('1.25'));self.assertEqual((info['source_rows'],info['valid_rows'],info['missing_rows']),(3,2,1));self.assertEqual((info['lower_rank'],info['upper_rank'],info['lower_value'],info['upper_value']),(1,2,0,10));self.assertTrue(info['interpolated']);self.assertEqual(info['method'],'linear_n_minus_1')
        self.assertFalse(self.calc([0,10,20],50)[1]['interpolated'])
    def test_permutation_invariance_no_source_mutation(self):
        values=[9,None,-8,0,9,1];before=copy.deepcopy(values)
        self.assertEqual(self.calc(values,90),self.calc(list(reversed(values)),90));self.assertEqual(values,before)
    def test_parameter_validation(self):
        for p in [None,True,False,'90',{},[],float('nan'),float('inf'),-0.1,100.01,10**1000]:
            with self.subTest(p=str(p)[:20]),self.assertRaises(ValidationError):self.calc([1,2],p)
        for m in [{'agg':'median','field':'value','percentile':50},{'agg':'sum','field':'value','percentile':90},{'agg':'median','field':'value','denominator':'value'},{'agg':'median','field':'unknown'}]:
            with self.assertRaises(ValidationError):q.validate(m,self.fields)
    def test_non_numeric_or_non_finite_is_not_silently_dropped(self):
        for v in [True,'2',[],{},float('nan'),float('inf'),Decimal('NaN'),Decimal('Infinity'),10**400]:
            with self.subTest(v=str(v)[:20]),self.assertRaises(ValidationError):self.calc([1,v])
    def test_units_and_missing_unit_fail_closed(self):
        fields={'value':{'type':'float','unit_field':'unit'}};m={'agg':'median','field':'value'}
        for unit in ['V',None,'',[],{}]:
            with self.subTest(unit=unit),self.assertRaises(ValidationError):q.calculate('sample',m,fields,[{'value':1,'unit':'A'},{'value':2,'unit':unit}])
        self.assertEqual(q.calculate('sample',m,fields,[{'value':1,'unit':'A'},{'value':None}])[1]['unit'],'A')
    def test_dynamic_unit_field(self):
        with self.assertRaises(ValidationError):q.calculate('measurements',{'agg':'median','field':'value'},self.fields,[{'value':1,'unit':'A'},{'value':2,'unit':'V'}])

class QuantileAnalysisTests(SimpleTestCase):
    def definition(self,**extra):return {'dimension':'family','metrics':[{'agg':'median','field':'produced_qty'},{'agg':'percentile','field':'produced_qty','percentile':90}],'chart':'table',**extra}
    def calc(self,d=None,rows=None,ds='bi_work_orders',scope=None,path=None):
        with patch('app.analysis_engine.semantic.rows',return_value=ROWS if rows is None else rows),patch('app.bi_scope.analytics.tables',return_value=source_tables()),patch('app.analysis_pivot.receipt',return_value={}):return eng.run_analysis(ADMIN,ds,d or self.definition(),scope,path)
    def test_default_labels_and_effective_samples(self):
        d=self.definition();before=copy.deepcopy(d);r=self.calc(d);self.assertEqual(d,before);self.assertIn('P90',r['labels'][1]);self.assertEqual(r['measures'][1]['percentile'],90);self.assertEqual(r['rows'][0]['m0'],5);self.assertEqual(r['rows'][0]['m1'],8.2);self.assertEqual(r['rows'][0]['quantiles']['m1']['valid_rows'],2)
    def test_pivot_totals_recompute_from_raw_not_group_percentiles(self):
        d=self.definition(chart='pivot',pivot={'dimension':'product_id'});r=self.calc(d);p=r['pivot'];self.assertEqual(p['grand_total']['m0'],1);self.assertEqual(p['grand_total']['m1'],7.4);self.assertNotEqual(p['grand_total']['m1'],sum(x['m1'] for x in p['row_totals'])/len(p['row_totals']));self.assertEqual(p['grand_total']['quantiles']['m1']['valid_rows'],3)
        out=pv.export_rows(r);self.assertEqual(out[-1][-2],3);self.assertIn('linear_n_minus_1',out[-1][-1]);self.assertIn('"percentile":90',out[-1][-1])
    def test_pivot_mixed_unit_total_blocks_only_that_total(self):
        d={'dimension':'unit','metrics':[{'agg':'median','field':'balance_qty'}],'chart':'pivot','pivot':{'dimension':'category'}}
        rows=[{'id':'I1','unit':'kg','balance_qty':2,'category':'材料'},{'id':'I2','unit':'件','balance_qty':8,'category':'材料'}]
        r=self.calc(d,rows,'bi_inventory');self.assertTrue(r['pivot']['grand_total']['blocked']);self.assertEqual({c['m0'] for c in r['pivot']['cells']},{2,8})
    def test_chart_cannot_compare_cross_group_dynamic_units(self):
        d={'dimension':'unit','metrics':[{'agg':'percentile','field':'value','percentile':90}],'chart':'bar'}
        rows=[{'id':'M1','unit':'A','value':1},{'id':'M2','unit':'V','value':2}]
        # Raw dataset unit check is exercised directly; bar global guard matches the same function.
        with self.assertRaises(ValidationError):q.validate_units('measurements','value',{'value':{'type':'float'}},rows)
        d['chart']='donut'
        with self.assertRaises(ValidationError):eng.validate_definition(ADMIN,'measurements',d)
    def test_filter_scope_drill_and_missing_stats_preserved(self):
        d=self.definition(drilldown=[{'dimension':'product_id','grain':'value'}]);r=self.calc(d,scope={'family':'A'},path=['A']);self.assertEqual(r['matched'],2);self.assertEqual(r['rows'][0]['m1'],8.2)
        r=self.calc(self.definition(filters=[{'field':'produced_qty','op':'gte','value':2}]));self.assertEqual(r['rows'][0]['m1'],9)
        r=self.calc(rows=[{**ROWS[0],'produced_qty':None}]);self.assertIsNone(r['rows'][0]['m0']);self.assertEqual(r['rows'][0]['quantiles']['m0']['missing_rows'],1)
        self.assertEqual(self.calc(rows=[])['rows'],[])
    def test_scatter_quantile_axes_and_samples(self):
        d=self.definition(chart='scatter',scatter={'x':'m0','y':'m1'});s=self.calc(d)['scatter'];p=s['points'][0];self.assertEqual((p['x'],p['y']),(5,8.2));self.assertEqual(p['valid_inputs'],{'x':2,'y':2});self.assertEqual(s['axes']['x']['unit'],'台')
    def test_derived_quantiles_retain_unit_and_strict_missing_rule(self):
        d=self.definition(derived=[{'label':'典型水平差','expression':'m1 - m0','unit':'台'}],display_metric='d0');r=self.calc(d);self.assertEqual(r['rows'][0]['d0'],3.2)
        r=self.calc(d,[{**ROWS[0],'produced_qty':None},ROWS[1]]);self.assertEqual(r['rows'][0]['m0'],9);self.assertIsNone(r['rows'][0]['d0']);self.assertIn('缺失',str(r['derived_notes']))

class QuantileWorkflowTests(PlatformCase):
    def setUp(self):
        super().setUp();self.client.force_login(self.admin)
        self.d={'dimension':'family','metrics':[{'agg':'median','field':'price_cents'},{'agg':'percentile','field':'price_cents','percentile':90}],'filters':[],'chart':'table'}
        for i,(f,value) in enumerate([('YE3',100),('YE3',200),('YE4',900),('YE4',None)]):self.record('products',{'id':f'P{i}','family':f,'model':'M'+str(i%2),'price_cents':value})
    def topic(self,d=None,reference=True):
        m=AnalysisModel.objects.create(name='分位模型',dataset='products',definition=d or self.d,owner='admin');t=Topic.objects.create(name='分位专题',owner='admin',layout=[{'model_id':m.pk,'span':2}]);ctx=ws.context(self.admin,t.pk);conf={'scope':{},'reference_scope':{'family':'YE3'} if reference else None,'primary_label':'全部','reference_label':'YE3'};r=ws.run(self.admin,t.pk,{'context_token':ctx['context_token'],'config':conf});return t,ctx,conf,r
    def test_nested_module_urls_share_current_entry_version(self):
        html=self.client.get('/').content.decode();mapping=json.loads(html.split('<script type="importmap">')[1].split('</script>')[0])['imports']
        versions=set()
        for name in ['app','quantiles','metrics','topics','topic_snapshots','analysis_pivot','analysis_scatter','analysis_drill','derived']:
            target=mapping['/static/'+name+'.js'];self.assertTrue(target.startswith('/static/'+name+'.js?v='));versions.add(target.split('?v=')[1])
        self.assertEqual(len(versions),1);self.assertIn('app.js?v='+next(iter(versions)),html)
    def test_save_reopen_exact_parameter_and_sensitive_permissions(self):
        r=self.post('/api/models',{'name':'P90单价','dataset':'products','definition':self.d});self.assertEqual(r.status_code,200,r.content);self.assertEqual(r.json()['definition'],self.d)
        self.assertEqual(self.client.get('/api/models').json()[0]['definition'],self.d)
        self.client.force_login(self.quality);self.assertEqual(self.post('/api/analyze',{'dataset':'products','definition':self.d}).status_code,400);self.assertEqual(self.client.get('/api/models').json(),[])
    def test_source_and_scatter_export_include_quantile_definition(self):
        d={**self.d,'chart':'scatter','scatter':{'x':'m0','y':'m1'}};p={'dataset':'products','definition':d,'scope':{},'path':[]};r=self.post('/api/analyze',p).json();out=self.post('/api/analyze/scatter/export',{**p,'revision':r['scatter']['revision'],'kind':'result'});self.assertEqual(out.status_code,200,out.content)
        data=out.json();file=self.client.get(data['download_url']).content.decode('utf-8-sig');self.assertIn('valid_rows',file);self.assertIn('linear_n_minus_1',file);self.assertIn('190',file)
        point=r['scatter']['points'][0];ev=self.post('/api/analyze/scatter/evidence',{**p,'revision':r['scatter']['revision'],'selection':point['key'],'page':1}).json();self.assertEqual(ev['total'],2);self.assertEqual(ev['rows'][0]['source']['file'],'unit-test.xlsx')
    def test_drill_export_keeps_method_sample_size_and_formula_escaping(self):
        self.record('products',{'id':'PF','family':'=1+1','model':'M','price_cents':3})
        p={'dataset':'products','definition':self.d,'scope':{},'path':[]};r=self.post('/api/analyze/explore',p);self.assertEqual(r.status_code,200,r.content)
        out=self.post('/api/analyze/explore/export',{**p,'revision':r.json()['revision'],'kind':'result'});self.assertEqual(out.status_code,200,out.content);text=out.json()['csv'];self.assertIn('linear_n_minus_1',text);self.assertIn("'=1+1",text)
    def test_topic_export_regular_pivot_and_scatter_samples(self):
        for d in [self.d,{**self.d,'chart':'pivot','pivot':{'dimension':'model'}},{**self.d,'chart':'scatter','scatter':{'x':'m0','y':'m1'}}]:
            for reference in [False,True]:
                with self.subTest(chart=d['chart'],ref=reference):
                    t,ctx,conf,r=self.topic(d,reference);out,_=ws.export_rows(self.admin,t.pk,{'context_token':ctx['context_token'],'facts_token':r['facts_token'],'config':conf,'slot':0});self.assertTrue(all(len(x)==len(out[0]) for x in out));self.assertIn('linear_n_minus_1',json.dumps(out));self.assertIn('valid_rows',json.dumps(out))
    def test_snapshot_freezes_values_and_samples_for_each_shape(self):
        for d in [self.d,{**self.d,'chart':'pivot','pivot':{'dimension':'model'}},{**self.d,'chart':'scatter','scatter':{'x':'m0','y':'m1'}}]:
            with self.subTest(chart=d['chart']):
                t,ctx,conf,r=self.topic(d);s=ss.create(self.admin,t.pk,{'request_id':str(uuid.uuid4()),'context_token':ctx['context_token'],'facts_token':r['facts_token'],'config':conf,'name':'冻结分位','note':'保留真实样本计数和分位定义'});before=copy.deepcopy(s.payload);out=ss.export_rows(s);self.assertTrue(all(len(x)==len(out[0]) for x in out));self.assertIn('linear_n_minus_1',json.dumps(out))
                with patch('app.analysis_quantiles.NOTICE','changed future notice'):self.assertEqual(ss.export_rows(s),out)
                rec=Record.objects.get(business_key='P0');old=copy.deepcopy(rec.values);rec.values['price_cents']=999;rec.revision+=1;rec.save();self.assertEqual(ss.export_rows(s),out);s.refresh_from_db();self.assertEqual(s.payload,before);rec.values=old;rec.revision+=1;rec.save()
    def test_metric_publish_requires_separate_review_and_pins_percentile(self):
        for i,v in enumerate([10,20,100]):self.record('energy',{'id':str(i),'workshop':'A','kwh':v})
        p=payload();p['measure']={'agg':'percentile','field':'kwh','percentile':90};p['unit']='kWh'
        r=self.post('/api/metrics',{'key':'ENERGY_P90','dataset':'energy','payload':p});self.assertEqual(r.status_code,200,r.content);v=r.json()
        def act(v,action,**extra):return self.post('/api/metrics/'+str(v['id']),{'action':action,'revision':v['revision'],**extra})
        v=act(v,'submit').json();self.assertEqual(v['evidence']['rows'][0]['m0'],84);self.assertEqual(v['evidence']['rows'][0]['quantiles']['m0']['valid_rows'],3);self.assertIn('quantile_notice',v['evidence']);self.assertEqual(act(v,'publish',reason='不能编写人员自己审批').status_code,403)
        self.client.force_login(self.quality);v=act(v,'publish',reason='核对三条样本，P90线性插值为84千瓦时。').json();self.assertEqual(v['status'],'published');d={'metric_ref':{'key':'ENERGY_P90','version':1},'chart':'table'};result=eng.run_analysis(self.quality,'energy',d);self.assertEqual(result['rows'][0]['m0'],84)
        self.assertEqual(self.post('/api/analyze',{'dataset':'energy','definition':{**d,'metrics':[{'agg':'percentile','field':'kwh','percentile':50}]}}).status_code,400)
