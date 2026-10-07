import copy,csv,io,json
from unittest.mock import patch
from django.test import SimpleTestCase,Client
from django.core.exceptions import ValidationError
from app import analysis_drill as drill,business_groups as bg,metric_registry as registry,access
from app.analysis_engine import run_analysis,validate_definition
from app.models import Record,AuditEvent,AnalysisModel,GovernedMetric,MetricVersion
from .test_platform import PlatformCase
from .test_derived import ADMIN,ROWS,definition,source_tables
from .test_business_groups import enumeration

def model():
    d=definition();d['drilldown']=[{'dimension':'product_id','grain':'value'},{'dimension':'id','grain':'value'}];return d

class DrillCalculationTests(SimpleTestCase):
    def calc(self,d=None,rows=None,path=None,scope=None):
        with patch('app.analysis_engine.semantic.rows',return_value=ROWS if rows is None else rows),patch('app.bi_scope.analytics.tables',return_value=source_tables()):
            return run_analysis(ADMIN,'bi_work_orders',d or model(),scope,path)
    def test_root_unchanged_and_inputs_immutable(self):
        d=model();before=copy.deepcopy(d);r=self.calc(d,path=[]);self.assertEqual(r['rows'],self.calc(d)['rows']);self.assertEqual(d,before)
    def test_family_configuration_work_order_recomputed(self):
        r=self.calc(path=['A']);self.assertEqual((r['matched'],r['rows'][0]['dimension'],r['rows'][0]['d0']),(2,'P1',40))
        leaf=self.calc(path=['A','P1']);self.assertEqual({r['dimension'] for r in leaf['rows']},{'W1','W2'});self.assertAlmostEqual(next(r for r in leaf['rows'] if r['dimension']=='W2')['d0'],300/9)
    def test_return_root_has_full_original_population(self):
        self.calc(path=['A','P1']);self.assertEqual(self.calc(path=[])['matched'],3)
    def test_cannot_cross_parent_scope(self):
        with self.assertRaises(ValidationError):self.calc(path=['B','P1'])
    def test_unknown_group_never_falls_back(self):
        with self.assertRaises(ValidationError):self.calc(path=['NOPE'])
    def test_path_too_deep_or_wrong_type_rejected(self):
        for p in [['A','P1','W1'],'A',[None],[{}]]:
            with self.subTest(p=p),self.assertRaises(ValidationError):self.calc(path=p)
    def test_missing_group_retains_missing_rows(self):
        rows=copy.deepcopy(ROWS);rows[0]['family']=None
        self.assertEqual(self.calc(rows=rows,path=['未填写'])['matched'],1)
    def test_literal_missing_label_keeps_same_membership_as_root(self):
        rows=copy.deepcopy(ROWS);rows[0]['family']=None;rows[1]['family']='未填写'
        root=self.calc(rows=rows,path=[]);child=self.calc(rows=rows,path=['未填写'])
        self.assertEqual(child['matched'],next(r for r in root['rows'] if r['dimension']=='未填写')['row_count'])
    def test_numeric_zero_group_is_not_empty(self):
        d=model();d['dimension']='produced_qty';self.assertEqual(self.calc(d,path=['0'])['matched'],1)
    def test_ratio_recomputed_from_child_numerators(self):
        d=model();d.update(metrics=[{'agg':'ratio','field':'released_qty','denominator':'produced_qty'}],derived=[],display_metric='m0')
        rows=[{**ROWS[0],'released_qty':1},{**ROWS[1],'released_qty':0}, {**ROWS[2],'released_qty':0}]
        self.assertEqual(self.calc(d,rows,path=['A'])['rows'][0]['m0'],10)
        self.assertIsNone(self.calc(d,rows,path=['B'])['rows'][0]['m0'])
    def test_average_and_distinct_are_not_sums_of_groups(self):
        d=model();d.update(metrics=[{'agg':'avg','field':'produced_qty'},{'agg':'distinct','field':'product_id'}],derived=[],display_metric='m0')
        root=self.calc(d,path=[]);self.assertEqual(root['rows'][0]['m0'],5);self.assertEqual(root['rows'][0]['m1'],1)
        self.assertEqual(sum(r['m1'] for r in self.calc(d,path=['A','P1'])['rows']),2)
    def test_initial_filter_preserved(self):
        d=model();d['filters']=[{'field':'produced_qty','op':'gte','value':2}];self.assertEqual(self.calc(d,path=['A'])['matched'],1)
    def test_scope_intersects_path(self):
        self.assertEqual(self.calc(path=['A'],scope={'family':'A'})['matched'],2)
        with self.assertRaises(ValidationError):self.calc(path=['A'],scope={'family':'B'})
    def test_month_day_and_missing_dates(self):
        d=model();d.update(dimension='planned_end',grain='month',drilldown=[{'dimension':'planned_end','grain':'day'},{'dimension':'id','grain':'value'}])
        rows=[{**r,'planned_end':v} for r,v in zip(ROWS,['2026-09-01','2026-09-02',None])]
        self.assertEqual({r['dimension'] for r in self.calc(d,rows,path=['2026-09'])['rows']},{'2026-09-01','2026-09-02'})
        self.assertEqual(self.calc(d,rows,path=['2026-09','2026-09-02'])['rows'][0]['dimension'],'W2')
        self.assertEqual(self.calc(d,rows,path=['未填写'])['matched'],1)
    def test_non_date_grain_duplicate_empty_root_and_unknown_fields(self):
        for changes in [dict(dimension=''),dict(drilldown=[{'dimension':'family','grain':'value'}]),dict(drilldown=[{'dimension':'product_id','grain':'day'}]),dict(drilldown=[{'dimension':'sql','grain':'value'}]),dict(drilldown=[{'dimension':'id','grain':'value','sql':'x'}]),dict(drilldown=[{'dimension':'id','grain':'value'}]*4),dict(drilldown=None)]:
            with self.subTest(changes=changes),self.assertRaises(ValidationError):self.calc({**model(),**changes})
    def test_all_null_measure_keeps_group_and_null(self):
        rows=[{**ROWS[0],'total_cost_cents':None}];r=self.calc(rows=rows,path=['A']);self.assertIsNone(r['rows'][0]['m0']);self.assertIsNone(r['rows'][0]['d0'])
    def test_negative_measure_values_preserved(self):
        rows=[{**ROWS[0],'total_cost_cents':-10000}];self.assertEqual(self.calc(rows=rows,path=['A'])['rows'][0]['d0'],-100)
    def test_empty_root_is_empty_not_zero_group(self):self.assertEqual(self.calc(rows=[],path=[])['rows'],[])
    def test_invalid_field_type_is_validation_error(self):
        for field in [[],{},None,True]:
            with self.subTest(field=field),self.assertRaises(ValidationError):self.calc({**model(),'drilldown':[{'dimension':field,'grain':'value'}]})
    def test_child_still_checks_mixed_units(self):
        d={'dimension':'category','metrics':[{'agg':'sum','field':'balance_qty'}],'drilldown':[{'dimension':'material_id','grain':'value'}]}
        rows=[{'id':'I1','category':'材料','material_id':'M1','unit':'kg','balance_qty':2},{'id':'I2','category':'材料','material_id':'M1','unit':'件','balance_qty':1}]
        with patch('app.analysis_engine.semantic.rows',return_value=rows),patch('app.bi_scope.analytics.tables',return_value=source_tables()),self.assertRaises(ValidationError):
            run_analysis(ADMIN,'bi_inventory',d,{},['材料'])

class DrillAPITests(PlatformCase):
    def setUp(self):
        super().setUp();self.client.force_login(self.admin)
        self.d={'dimension':'family','grain':'value','metrics':[{'agg':'count'}],'chart':'bar','drilldown':[{'dimension':'id','grain':'value'}]}
        self.p={'dataset':'products','definition':self.d,'scope':{},'path':[]}
        for i,fam in enumerate(['YE3','YE3','YE4']):self.record('products',{'id':f'P{i}','family':fam,'price_cents':100,'model':'演示型号'})
    def call(self,suffix='',**extra):return self.post('/api/analyze/explore'+suffix,{**self.p,**extra})
    def opened(self):
        r=self.call();self.assertEqual(r.status_code,200,r.content);return r.json()
    def test_requires_login_and_post(self):
        self.assertEqual(self.client.get('/api/analyze/explore').status_code,405);self.client.logout();self.assertEqual(self.call().status_code,401)
    def test_no_store_root_path_and_metadata(self):
        r=self.call();self.assertEqual(r['Cache-Control'],'no-store');self.assertEqual(r.json()['levels'][1]['dimension'],'id');self.assertEqual(r.json()['result']['matched'],3)
    def test_revision_required_after_root(self):self.assertEqual(self.call(path=['YE3']).status_code,400)
    def test_data_changed_blocks_following_path(self):
        r=self.opened();self.record('products',{'id':'P4','family':'YE3'})
        self.assertEqual(self.call(path=['YE3'],revision=r['revision']).status_code,409)
    def test_definition_scope_and_code_changes_block(self):
        r=self.opened()
        self.assertEqual(self.call(revision=r['revision'],definition={**self.d,'sort':'desc'}).status_code,409)
        self.assertEqual(self.call(revision=r['revision'],scope={'family':'YE3'}).status_code,409)
        with patch('app.analysis_explore_views.metric_registry.calculation_hash',return_value='changed'):
            self.assertEqual(self.call(revision=r['revision']).status_code,409)
    def test_evidence_matches_path_group_and_provenance(self):
        r=self.opened();data=self.call('/evidence',path=['YE3'],revision=r['revision'],group='P1').json()
        self.assertEqual(data['total'],1);self.assertEqual(data['rows'][0]['values']['id'],'P1');self.assertEqual(data['rows'][0]['source']['row'],2)
        self.assertEqual(self.call('/evidence',path=['YE3'],revision=r['revision'],group='P2').json()['total'],0)
    def test_hidden_field_and_dataset_rejected(self):
        self.client.force_login(self.quality)
        self.assertEqual(self.call(definition={**self.d,'drilldown':[{'dimension':'price_cents','grain':'value'}]}).status_code,400)
        self.assertEqual(self.call(dataset='costs').status_code,400)
        r=self.opened();data=self.call('/evidence',revision=r['revision']).json();self.assertNotIn('price_cents',json.dumps(data));self.assertFalse(data['can_download_original'])
    def test_exports_scope_and_no_fact_changes(self):
        r=self.opened();before=list(Record.objects.values());out=self.call('/export',path=['YE3'],revision=r['revision'],kind='result').json()
        csvrows=list(csv.reader(io.StringIO(out['csv'])));self.assertEqual(out['rows'],2);self.assertEqual({x[0] for x in csvrows[5:-1]},{'P0','P1'})
        raw=self.call('/export',path=['YE3'],revision=r['revision'],kind='evidence',group='P0').json();self.assertEqual(raw['rows'],1)
        self.assertEqual(before,list(Record.objects.values()));self.assertEqual(AuditEvent.objects.filter(action='analysis.explore_export').count(),2)
    def test_export_formula_escaping_and_hidden_fields(self):
        self.record('products',{'id':'P9','family':'=1+1','model':'+cmd','price_cents':999})
        self.client.force_login(self.quality);r=self.opened();out=self.call('/export',revision=r['revision'],kind='result').json();self.assertIn("'=1+1",out['csv'])
        out=self.call('/export',revision=r['revision'],kind='evidence').json();parsed=list(csv.reader(io.StringIO(out['csv'])))
        # The metadata timestamp/hash can incidentally contain "999". Inspect
        # actual field columns and business cells, rather than opaque receipts.
        self.assertEqual(parsed[4],[f['label'] for f in access.permitted_fields(self.quality,'products')])
        self.assertNotIn('参考售价分',parsed[4]);self.assertEqual(len(parsed[5:-1]),out['rows'])
        self.assertTrue(all('999' not in row for row in parsed[5:-1]));self.assertIn("'+cmd",next(row for row in parsed[5:-1] if row[0]=='P9'))
    def test_export_requires_receipt_and_stale_prevents_audit(self):
        self.assertEqual(self.call('/export',kind='result').status_code,400)
        r=self.opened();r['revision']['definition']='bad';self.assertEqual(self.call('/export',revision=r['revision']).status_code,409);self.assertFalse(AuditEvent.objects.exists())
    def test_export_audit_failure_returns_no_export(self):
        r=self.opened()
        with patch('app.analysis_explore_views.AuditEvent.objects.create',side_effect=ValueError('audit failed')):
            self.assertEqual(self.call('/export',revision=r['revision']).status_code,400)
    def test_download_matches_prepared_csv_and_requires_same_account(self):
        r=self.opened();out=self.call('/export',revision=r['revision']).json();file=self.client.get(out['download_url'])
        self.assertEqual(file.content.decode('utf-8-sig'),out['csv']);self.assertEqual(file['Cache-Control'],'no-store');self.assertIn('attachment',file['Content-Disposition'])
        self.client.force_login(self.quality);self.assertEqual(self.client.get(out['download_url']).status_code,400)
        self.client.logout();self.assertEqual(self.client.get(out['download_url']).status_code,401)
    def test_download_expiry_and_permission_change(self):
        r=self.opened();out=self.call('/export',revision=r['revision']).json()
        with patch('app.analysis_explore_views.access.role',return_value='viewer'):self.assertEqual(self.client.get(out['download_url']).status_code,400)
        from django.core.cache import cache
        cache.delete('analysis-export:'+out['download_url'].split('/')[-1]);self.assertEqual(self.client.get(out['download_url']).status_code,400)
    def test_unknown_arguments_pages_and_groups(self):
        r=self.opened()
        self.assertEqual(self.call(sql='x').status_code,400)
        for p in [0,True,'1']:
            self.assertEqual(self.call('/evidence',page=p,revision=r['revision']).status_code,400)
        self.assertEqual(self.call('/evidence',group=[],revision=r['revision']).status_code,400)
    def test_csrf_enforced(self):
        c=Client(enforce_csrf_checks=True);c.force_login(self.admin);self.assertEqual(c.post('/api/analyze/explore',json.dumps(self.p),content_type='application/json').status_code,403)
    def test_many_groups_are_explicitly_truncated_in_export(self):
        self.p.update(dataset='bi_work_orders',definition={'dimension':'id','metrics':[{'agg':'count'}]})
        with patch('app.analysis_engine.semantic.rows',return_value=[{'id':f'W{i:05}'} for i in range(1001)]),patch('app.bi_scope.analytics.tables',return_value=source_tables()):
            r=self.opened();self.assertEqual(r['result']['groups'],1001);self.assertTrue(r['result']['truncated'])
            out=self.call('/export',revision=r['revision']).json();self.assertEqual(out['rows'],1000)
            self.assertEqual(list(csv.reader(io.StringIO(out['csv'])))[3],['返回分组','1000','全部分组','1001','截断','True'])
    def test_evidence_paging_and_large_export_refusal(self):
        self.p.update(dataset='bi_work_orders',definition={'dimension':'family','metrics':[{'agg':'count'}]})
        with patch('app.analysis_engine.semantic.rows',return_value=[{'id':f'W{i:05}','family':'A'} for i in range(10001)]),patch('app.bi_scope.analytics.tables',return_value=source_tables()):
            r=self.opened();first=self.call('/evidence',revision=r['revision']).json();second=self.call('/evidence',revision=r['revision'],page=2).json()
            self.assertEqual(first['total'],10001);self.assertEqual(len(first['rows']),30)
            self.assertFalse({x['values']['id'] for x in first['rows']}&{x['values']['id'] for x in second['rows']})
            rejected=self.call('/export',revision=r['revision'],kind='evidence');self.assertEqual(rejected.status_code,400);self.assertIn('10,000',rejected.json()['error']);self.assertFalse(AuditEvent.objects.exists())
    def test_save_and_reopen_hierarchy(self):
        r=self.post('/api/models',{'name':'分层演练','dataset':'products','definition':self.d,'is_public':False});self.assertEqual(r.status_code,200,r.content)
        m=AnalysisModel.objects.get(pk=r.json()['id']);self.assertEqual(m.definition['drilldown'],self.d['drilldown'])
        self.assertEqual(self.call(path=['YE3'],revision=self.opened()['revision']).json()['result']['matched'],2)
    def test_custom_group_drills_to_original_field_values(self):
        saved=bg.save(self.admin,{'code':'DRILL.GROUP','payload':enumeration()});d={**self.d,'grouping_ref':saved['versions'][0]['ref'],'drilldown':[{'dimension':'family','grain':'value'},{'dimension':'id','grain':'value'}]}
        root=self.call(definition=d).json();child=self.call(definition=d,path=['标准电机'],revision=root['revision']).json()
        self.assertEqual({r['dimension'] for r in child['result']['rows']},{'YE3','YE4'});self.assertIsNone(child['result']['grouping_receipt'])
        self.assertEqual(root['levels'][0]['label'],'产品族归类')
    def test_governed_metric_stays_pinned_and_fixed_filter_remains(self):
        payload={'name':'产品记录数','business_definition':'产品来源记录数','purpose':'演练下钻','business_owner':'工艺','clock':'当前来源','unit':'条','exclusions':'无','comparison':'同一范围','change_reason':'模拟新建','review_role':'operations','measure':{'agg':'count'},'filters':[{'field':'family','op':'eq','value':'YE3'}]}
        m=GovernedMetric.objects.create(key='DRILL_COUNT',dataset='products',owner=self.admin.username)
        v=MetricVersion.objects.create(metric=m,version=1,status='published',payload=payload,calculation_hash=registry.calculation_hash('products'))
        d={**self.d,'metrics':[],'metric_ref':{'key':'DRILL_COUNT','version':1}};root=self.call(definition=d).json()
        self.assertEqual(root['result']['matched'],2);child=self.call(definition=d,path=['YE3'],revision=root['revision']).json();self.assertEqual(child['result']['metric_receipt']['version'],1)
        v.status='retired';v.save();self.assertEqual(self.call(definition=d,path=['YE3'],revision=root['revision']).status_code,400)
