import copy,csv,io,json,uuid
from unittest.mock import patch
from django.test import SimpleTestCase,Client
from django.core.exceptions import ValidationError
from django.core.cache import cache
from app import analysis_pivot as pv,analysis_engine as eng,topic_workspace as ws,topic_snapshots as ss
from app.models import AnalysisModel,Topic,Record,AuditEvent
from .test_platform import PlatformCase
from .test_derived import ADMIN,ROWS,definition,source_tables

def model():return {**definition(),'chart':'pivot','pivot':{'dimension':'product_id','grain':'value'}}
class PivotCalculationTests(SimpleTestCase):
    def calc(self,d=None,rows=None,ds='bi_work_orders',scope=None):
        with patch('app.analysis_engine.semantic.rows',return_value=ROWS if rows is None else rows),patch('app.bi_scope.analytics.tables',return_value=source_tables()),patch('app.analysis_pivot.receipt',return_value={}):
            return eng.run_analysis(ADMIN,ds,d or model(),scope)
    def test_derived_total_recomputed_not_sum_or_average(self):
        d=model();before=copy.deepcopy(d);r=self.calc(d);p=r['pivot'];self.assertEqual(d,before)
        self.assertEqual(p['grand_total']['d0'],41);self.assertEqual(p['grand_total']['row_count'],3)
        self.assertEqual(p['row_totals'][0]['d0'],40);self.assertEqual(len(p['cells']),4)
    def test_empty_cells_not_zero_count_and_zero_denominator(self):
        p=self.calc()['pivot'];empty=next(c for c in p['cells'] if c['empty']);self.assertIsNone(empty['m0']);self.assertEqual(empty['row_count'],0)
        zero=next(c for c in p['cells'] if c['row_count']==1);self.assertIsNone(zero['d0']);self.assertIn('分母为零',zero['reason'])
    def test_ratio_total_uses_paired_rows(self):
        d={**model(),'metrics':[{'agg':'ratio','field':'total_cost_cents','denominator':'produced_qty'}],'derived':[],'display_metric':'m0'}
        rows=[{**r,'total_cost_cents':v} for r,v in zip(ROWS,[1,9,None])];p=self.calc(d,rows)['pivot'];self.assertEqual(p['grand_total']['m0'],100);self.assertEqual(p['grand_total']['components'][0]['excluded_null_rows'],1)
    def test_basic_ratio_zero_reason(self):
        d={**model(),'metrics':[{'agg':'ratio','field':'total_cost_cents','denominator':'produced_qty'}],'derived':[],'display_metric':'m0'}
        c=self.calc(d,[ROWS[2]])['pivot']['grand_total'];self.assertIsNone(c['m0']);self.assertIn('分母为零',c['reason'])
    def test_average_and_distinct_totals(self):
        d={**model(),'metrics':[{'agg':'avg','field':'produced_qty'},{'agg':'distinct','field':'product_id'}],'derived':[],'display_metric':'m0'}
        p=self.calc(d)['pivot'];self.assertAlmostEqual(p['grand_total']['m0'],10/3);self.assertEqual(p['grand_total']['m1'],2)
    def test_count_empty_cell_null(self):
        d={**model(),'metrics':[{'agg':'count'}],'derived':[],'display_metric':'m0'}
        p=self.calc(d)['pivot'];self.assertEqual(p['grand_total']['m0'],3);self.assertTrue(all(c['m0'] is None for c in p['cells'] if c['empty']))
    def test_missing_input_derived_null_basic_retained(self):
        rows=copy.deepcopy(ROWS);rows[0]['produced_qty']=None;c=self.calc(rows=rows)['pivot']['grand_total'];self.assertIsNone(c['d0']);self.assertEqual(c['m0'],41000);self.assertIn('缺失',c['reason'])
    def test_missing_label_literal_and_total_distinct(self):
        rows=[{**r,'family':f} for r,f in zip(ROWS,[None,'未填写','合计'])];p=self.calc(rows=rows)['pivot'];self.assertEqual({x['label'] for x in p['rows']},{'未填写','未填写（原文）','合计'});self.assertEqual(len({x['key'] for x in p['rows']}),3)
        for axis in p['rows']:self.assertEqual(len(pv.select(rows,model(),{'row':axis['key'],'column':None})),1)
    def test_zero_negative_numeric_axis_and_negative_value(self):
        d={**model(),'dimension':'produced_qty'};p=self.calc(d,[{**r,'total_cost_cents':-r['total_cost_cents']} for r in ROWS])['pivot'];self.assertIn('0',{r['label'] for r in p['rows']});self.assertEqual(p['grand_total']['m0'],-41000)
    def test_selection_row_column_cell_and_grand(self):
        d=model();p=self.calc()['pivot'];a=next(x['key'] for x in p['rows'] if x['label']=='A');b=next(x['key'] for x in p['columns'] if x['label']=='P2')
        self.assertEqual(len(pv.select(ROWS,d,{'row':a,'column':None})),2);self.assertEqual(len(pv.select(ROWS,d,{'row':None,'column':b})),1);self.assertEqual(pv.select(ROWS,d,{'row':a,'column':b}),[]);self.assertEqual(len(pv.select(ROWS,d,{'row':None,'column':None})),3)
    def test_unknown_axes_no_fallback(self):
        for sel in [None,{},[],{'row':'bad','column':None},{'row':True,'column':None},{'row':None,'column':None,'extra':1}]:
            with self.subTest(sel=sel),self.assertRaises(ValidationError):pv.select(ROWS,model(),sel)
    def test_month_day_grains(self):
        d={**model(),'dimension':'planned_end','grain':'month','pivot':{'dimension':'planned_end','grain':'day'}};p=self.calc(d,[{**r,'planned_end':day} for r,day in zip(ROWS,['2026-09-01','2026-09-02',None])])['pivot'];self.assertEqual(len(p['rows']),2);self.assertEqual(len(p['columns']),3)
    def test_invalid_axis_fields_grains_and_shapes(self):
        for p in [None,{},[],{'dimension':[]},{'dimension':'NO'},{'dimension':'family'},{'dimension':'product_id','grain':'day'},{'dimension':'product_id','sql':'x'}]:
            with self.subTest(p=p),self.assertRaises(ValidationError):self.calc({**model(),'pivot':p})
    def test_empty_row_dimension_rejected(self):
        with self.assertRaises(ValidationError):self.calc({**model(),'dimension':''})
    def test_cardinality_limit_rejects_no_truncation(self):
        for field,n in [('family',201),('product_id',51)]:
            with self.subTest(field=field),self.assertRaises(ValidationError):self.calc(rows=[{**ROWS[0],'id':str(i),field:str(i)} for i in range(n)])
    def test_maximum_axes_and_all_cells(self):
        rows=[{**ROWS[0],'id':str(i),'family':str(i),'product_id':str(i%50)} for i in range(200)];p=self.calc(rows=rows)['pivot'];self.assertEqual(len(p['cells']),10000);self.assertEqual(p['grand_total']['row_count'],200)
    def test_empty_scope_grand_null(self):
        p=self.calc(rows=[])['pivot'];self.assertEqual(p['rows'],[]);self.assertIsNone(p['grand_total']['d0']);self.assertTrue(p['grand_total']['empty'])
    def test_mixed_units_only_conflicting_margins_blocked(self):
        d={'dimension':'unit','pivot':{'dimension':'category'},'chart':'pivot','metrics':[{'agg':'sum','field':'balance_qty'}]};rows=[{'id':'I1','unit':'件','category':'原料','balance_qty':2},{'id':'I2','unit':'kg','category':'原料','balance_qty':3}]
        p=self.calc(d,rows,'bi_inventory')['pivot'];self.assertTrue(p['grand_total']['blocked']);self.assertIsNone(p['grand_total']['m0']);self.assertEqual({c['m0'] for c in p['cells']},{2,3});self.assertEqual({c['units']['m0'] for c in p['cells']},{'件','kg'})
    def test_unknown_units_blocked(self):
        d={'dimension':'unit','pivot':{'dimension':'category'},'chart':'pivot','metrics':[{'agg':'sum','field':'balance_qty'}]};p=self.calc(d,[{'id':'I1','category':'原料','balance_qty':2}],'bi_inventory')['pivot'];self.assertIn('单位缺失',p['grand_total']['blocked'])
    def test_filters_scope_and_sort_applied_before_totals(self):
        d={**model(),'filters':[{'field':'produced_qty','op':'gte','value':1}]};p=self.calc(d,scope={'family':'A'})['pivot'];self.assertEqual(p['grand_total']['row_count'],2);self.assertEqual(p['grand_total']['d0'],40)
    def test_export_includes_cells_and_all_margins_once(self):
        r=self.calc();rows=pv.export_rows(r);self.assertEqual(len(rows),10);self.assertEqual(rows[-1][0],'总计');self.assertEqual(rows[-1][-2],3)
    def test_comparison_keeps_nonadditive_margin_values(self):
        r=self.calc();c=ws.compare(r,r);self.assertTrue(c['pivot']);self.assertEqual(c['matrix']['grand_total']['values'][2]['primary'],41);self.assertEqual(c['matrix']['grand_total']['values'][2]['delta'],0)

class PivotAPITests(PlatformCase):
    def setUp(self):
        super().setUp();self.client.force_login(self.admin)
        self.d={'dimension':'family','metrics':[{'agg':'count'},{'agg':'avg','field':'price_cents'}],'chart':'pivot','pivot':{'dimension':'model'}}
        self.p={'dataset':'products','definition':self.d,'scope':{},'path':[]}
        for i,f in enumerate(['YE3','YE3','YE4']):self.record('products',{'id':f'P{i}','family':f,'model':'M'+str(i%2),'price_cents':100+i*100})
    def result(self):
        response=self.post('/api/analyze',self.p);self.assertEqual(response.status_code,200,response.content);return response.json()
    def ev(self,r,selection=None,**extras):return self.post('/api/analyze/pivot/evidence',{**self.p,'revision':r['pivot']['revision'],'selection':selection or {'row':None,'column':None},**extras})
    def export(self,r,**extras):return self.post('/api/analyze/pivot/export',{**self.p,'revision':r['pivot']['revision'],'kind':'result',**extras})
    def test_evidence_selection_and_excel_provenance(self):
        r=self.result();cell=next(c for c in r['pivot']['cells'] if c['row_count']==1);data=self.ev(r,{k:cell[k] for k in ['row','column']});self.assertEqual(data.status_code,200,data.content);self.assertEqual(data.json()['total'],1);self.assertEqual(data.json()['rows'][0]['source']['file'],'unit-test.xlsx');self.assertEqual(data['Cache-Control'],'no-store')
    def test_empty_intersection_does_not_return_all(self):
        r=self.result();cell=next(c for c in r['pivot']['cells'] if c['empty']);self.assertEqual(self.ev(r,{k:cell[k] for k in ['row','column']}).json()['total'],0)
    def test_requires_revision_and_rejects_changed_facts(self):
        r=self.result();self.assertEqual(self.ev(r,revision=None).status_code,400);self.record('products',{'id':'P9','family':'YE3','model':'M0'});self.assertEqual(self.ev(r).status_code,409);self.assertEqual(self.export(r).status_code,409)
    def test_scope_definition_and_code_revision_guard(self):
        r=self.result();self.assertEqual(self.ev(r,scope={'family':'YE3'}).status_code,409);self.assertEqual(self.ev(r,definition={**self.d,'sort':'desc'}).status_code,409)
        with patch('app.metric_registry.calculation_hash',return_value='new'):self.assertEqual(self.ev(r).status_code,409)
    def test_unknown_payload_selection_path_page(self):
        r=self.result()
        for extra in [{'sql':'x'},{'page':True},{'page':0},{'path':['YE3']},{'selection':{'row':'no','column':None}}]:
            with self.subTest(extra=extra):self.assertEqual(self.ev(r,**extra).status_code,400)
    def test_legacy_exports_and_sources_cannot_misrepresent_pivot(self):
        r=self.result();self.assertEqual(self.post('/api/analyze/explore/export',{**self.p,'revision':r['pivot']['revision']}).status_code,400);self.assertEqual(self.post('/api/analyze/evidence',self.p).status_code,400)
    def test_auth_csrf_and_field_permissions(self):
        r=self.result();secure=Client(enforce_csrf_checks=True);secure.force_login(self.admin);self.assertEqual(secure.post('/api/analyze/pivot/evidence',json.dumps(self.p),content_type='application/json').status_code,403)
        self.client.force_login(self.quality);self.assertEqual(self.post('/api/analyze',self.p).status_code,400);self.d['metrics']=[{'agg':'count'}];self.d['pivot']={'dimension':'price_cents'};self.assertEqual(self.post('/api/analyze',self.p).status_code,400)
        self.client.logout();self.assertEqual(self.ev(r).status_code,401)
    def test_export_complete_matrix_and_no_fact_mutation(self):
        r=self.result();before=list(Record.objects.values());out=self.export(r);self.assertEqual(out.status_code,200,out.content);d=out.json();self.assertEqual(d['rows'],9);f=self.client.get(d['download_url']);rows=list(csv.reader(io.StringIO(f.content.decode('utf-8-sig'))));self.assertEqual(sum(x[0]=='总计' for x in rows),1);self.assertEqual(before,list(Record.objects.values()));self.assertEqual(AuditEvent.objects.filter(action='analysis.pivot_export').count(),1);self.assertIn('analysis-pivot-result.csv',f['Content-Disposition'])
    def test_export_selected_source_and_receipt(self):
        r=self.result();a=r['pivot']['rows'][0]['key'];out=self.export(r,kind='evidence',selection={'row':a,'column':None}).json();self.assertEqual(out['rows'],2);text=self.client.get(out['download_url']).content.decode('utf-8-sig');self.assertIn('计算依据',text);self.assertIn('P0',text);self.assertNotIn('P2',text)
    def test_download_account_role_and_expiry(self):
        r=self.result();out=self.export(r).json();self.client.force_login(self.quality);self.assertEqual(self.client.get(out['download_url']).status_code,400);self.client.force_login(self.admin)
        with patch('app.analysis_explore_views.access.role',return_value='viewer'):self.assertEqual(self.client.get(out['download_url']).status_code,400)
        cache.delete('analysis-export:'+out['download_url'].split('/')[-1]);self.assertEqual(self.client.get(out['download_url']).status_code,400)
    def test_export_formula_escaping(self):
        self.record('products',{'id':'P9','family':'=1+1','model':'+run','price_cents':1});r=self.result();out=self.export(r).json();text=self.client.get(out['download_url']).content.decode('utf-8-sig');self.assertIn("'=1+1",text);self.assertIn("'+run",text)
    def test_audit_failure_does_not_publish_download(self):
        r=self.result()
        with patch('app.analysis_pivot_views.AuditEvent.objects.create',side_effect=ValueError('failed')),patch('app.analysis_pivot_views.cache.set') as setter:
            self.assertEqual(self.export(r).status_code,400);setter.assert_not_called()
    def topic(self):
        model=AnalysisModel.objects.create(name='透视',dataset='products',definition=self.d,owner='admin');topic=Topic.objects.create(name='透视专题',owner='admin',layout=[{'model_id':model.pk,'span':2}]);ctx=ws.context(self.admin,topic.pk);conf={'scope':{},'reference_scope':{},'primary_label':'A','reference_label':'B'};r=ws.run(self.admin,topic.pk,{'context_token':ctx['context_token'],'config':conf});return topic,ctx,conf,r
    def test_model_topic_persists_full_matrices_and_exports_comparison(self):
        topic,ctx,conf,r=self.topic();self.assertEqual(r['cards'][0]['primary']['pivot']['grand_total']['m0'],3);self.assertTrue(r['cards'][0]['comparison']['pivot']);rows,_=ws.export_rows(self.admin,topic.pk,{'context_token':ctx['context_token'],'facts_token':r['facts_token'],'config':conf,'slot':0});self.assertEqual(len(rows),19)
        self.assertIn('相对变化(%)',rows[0]);self.assertIn('行身份',rows[0]);self.assertEqual(rows[-1][rows[0].index('差值')],0)
    def test_range_export_has_independent_averages_and_missing_axes(self):
        topic,ctx,conf,_=self.topic();conf.update(scope={'family':'YE4'},reference_scope={'family':'YE3'})
        r=ws.run(self.admin,topic.pk,{'context_token':ctx['context_token'],'config':conf})
        v=r['cards'][0]['comparison']['matrix']['grand_total']['values'][1]
        self.assertEqual((v['primary'],v['reference'],v['delta'],v['relative_pct']),(300,150,150,100))
        self.assertTrue(all(x['values'][0]['delta'] is None for x in r['cards'][0]['comparison']['matrix']['cells']))
        rows,_=ws.export_rows(self.admin,topic.pk,{'context_token':ctx['context_token'],'facts_token':r['facts_token'],'config':conf,'slot':0})
        self.assertEqual(rows[-1][rows[0].index('差值')],150)
    def test_comparison_export_preserves_csv_injection_protection(self):
        self.record('products',{'id':'PX','family':'=1+1','model':'+run','price_cents':1});topic,ctx,conf,r=self.topic()
        response=self.client.get(f'/api/topics/{topic.pk}/export',{'context_token':ctx['context_token'],'facts_token':r['facts_token'],'config':json.dumps(conf),'slot':'0'})
        self.assertEqual(response.status_code,200,response.content);text=response.content.decode('utf-8-sig');self.assertIn("'=1+1",text);self.assertIn("'+run",text)
    def snapshot(self):
        topic,ctx,conf,r=self.topic();s=ss.create(self.admin,topic.pk,{'request_id':str(uuid.uuid4()),'context_token':ctx['context_token'],'facts_token':r['facts_token'],'config':conf,'name':'透视保存','note':'保存模拟透视矩阵与来源'});return topic,s
    def test_snapshot_cell_evidence_immutable_and_source_provenance(self):
        topic,s=self.snapshot();before=copy.deepcopy(s.payload);r=s.payload['result']['cards'][0]['primary'];cell=next(c for c in r['pivot']['cells'] if c['row_count']==1);rec=Record.objects.get(business_key='P0');rec.values['price_cents']=999;rec.revision+=1;rec.save()
        d=ss.evidence(self.admin,topic.pk,s.pk,{'slot':0,'side':'primary','group':None,'page':1,'selection':{k:cell[k] for k in ['row','column']}});self.assertEqual(d['total'],1);self.assertNotEqual(d['rows'][0]['values']['price_cents'],999);s.refresh_from_db();self.assertEqual(s.payload,before);self.assertEqual(len(ss.export_rows(s)),37)
    def test_snapshot_unknown_cell_rejected_comparison_reports_boundary(self):
        topic,s=self.snapshot()
        with self.assertRaises(ValidationError):ss.evidence(self.admin,topic.pk,s.pk,{'slot':0,'side':'primary','group':None,'page':1,'selection':{'row':'bad','column':None}})
        result=ss.compare_current(self.admin,topic.pk,s.pk);self.assertFalse(result['blocked']);self.assertTrue(result['cards'][0]['comparison']['pivot'])
    def test_snapshot_current_difference_and_current_evidence_receipt(self):
        topic,s=self.snapshot();before=copy.deepcopy(s.payload);old_hash=s.payload_hash
        rec=Record.objects.get(business_key='P0');rec.values['price_cents']=400;rec.revision+=1;rec.save()
        result=ss.compare_current(self.admin,topic.pk,s.pk);card=result['cards'][0];v=card['comparison']['matrix']['grand_total']['values'][1]
        self.assertEqual((v['primary'],v['reference'],v['delta']),(300,200,100));self.assertEqual(card['changed_objects'],1)
        current=card['current_result'];cell=next(c for c in current['pivot']['cells'] if c['row_count']==1 and c['m1']==400)
        self.assertEqual(self.ev(current,{k:cell[k] for k in ['row','column']}).status_code,200)
        s.refresh_from_db();self.assertEqual(s.payload,before);self.assertEqual(s.payload_hash,old_hash)
    def test_fixed_grouping_rows_and_frozen_missing_identity(self):
        from app import business_groups as bg
        from .test_business_groups import enumeration
        saved=bg.save(self.admin,{'code':'PIVOT.FAMILY','payload':enumeration()});self.d['grouping_ref']=saved['versions'][0]['ref'];self.d['pivot']={'dimension':'family'}
        r=self.result();self.assertEqual(len(r['pivot']['rows']),1);self.assertEqual(r['pivot']['rows'][0]['label'],'标准电机');self.assertEqual(len(r['pivot']['columns']),2)
        cell=r['pivot']['cells'][0];self.assertEqual(self.ev(r,{k:cell[k] for k in ['row','column']}).json()['total'],2)
        topic,s=self.snapshot();self.assertEqual(len(ss.export_rows(s)),25)
    def test_missing_literal_axis_provenance_stays_separate(self):
        self.record('products',{'id':'P9','family':None,'model':'M0','price_cents':1});self.record('products',{'id':'P10','family':'未填写','model':'M0','price_cents':2});r=self.result()
        for label,key in [('未填写','P9'),('未填写（原文）','P10')]:
            axis=next(a for a in r['pivot']['rows'] if a['label']==label);d=self.ev(r,{'row':axis['key'],'column':None}).json();self.assertEqual(d['total'],1);self.assertEqual(d['rows'][0]['values']['id'],key)
    def test_calculation_revision_changes_mid_run_rejected(self):
        with patch('app.analysis_pivot.receipt',side_effect=[{'data':'before'},{'data':'after'}]):self.assertEqual(self.post('/api/analyze',self.p).status_code,409)
