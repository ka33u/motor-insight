import csv,io,json
from copy import deepcopy
from unittest.mock import patch
from django.test import SimpleTestCase,Client
from app import quality_comparison as qc,quality_board as qb,analytics
from app.models import Record,AuditEvent
from .test_platform import PlatformCase
from .test_quality_board import fixture


def observations(values):
    return [{'id':str(i),'unit_id':'U'+str(i),'value':v,'result':'符合'} for i,v in enumerate(values)]

class BoxStatisticsTests(SimpleTestCase):
    def test_linear_quantiles_sample_standard_deviation_and_fences(self):
        s,ids=qc.stats(observations([0,1,2,3,100]));self.assertEqual((s['q1'],s['median'],s['q3'],s['iqr']),(1,2,3,2))
        self.assertEqual((s['lower_fence'],s['upper_fence'],s['lower_whisker'],s['upper_whisker']),(-2,6,0,3));self.assertEqual(ids,{'4'});self.assertEqual(s['outliers'],1)
        self.assertAlmostEqual(s['sample_stddev'],44.064725122412005)
    def test_even_sample_interpolates(self):
        s,_=qc.stats(observations([0,10,20,30]));self.assertEqual((s['q1'],s['median'],s['q3']),(7.5,15,22.5))
    def test_fence_equality_is_inside(self):
        s,ids=qc.stats(observations([-2,1,2,3,6]));self.assertEqual(ids,set());self.assertEqual((s['lower_whisker'],s['upper_whisker']),(-2,6))
    def test_spec_failure_and_outlier_are_independent(self):
        rows=observations([0,1,2,3,100]);rows[2]['result']='超限';s,ids=qc.stats(rows)
        self.assertEqual(s['outside'],1);self.assertEqual(ids,{'4'});self.assertNotIn('2',ids)
    def test_empty_single_constant_and_negative(self):
        s,_=qc.stats([]);self.assertEqual(s['n'],0);self.assertIsNone(s['median']);self.assertIsNone(s['outliers'])
        s,ids=qc.stats(observations([-4]));self.assertEqual(s['median'],-4);self.assertEqual(s['iqr'],0);self.assertIsNone(s['sample_stddev']);self.assertTrue(s['small_sample']);self.assertEqual(ids,set())
        s,_=qc.stats(observations([3]*6));self.assertEqual(s['sample_stddev'],0);self.assertEqual(s['outliers'],0)
    def test_iqr_zero_does_not_erase_extreme_observation(self):
        s,ids=qc.stats(observations([1,1,1,1,9]));self.assertEqual(s['iqr'],0);self.assertEqual(ids,{'4'})
    def test_unordered_inputs_not_modified_and_repeated_sn_not_deduped(self):
        rows=observations([4,0,2,1]);rows[1]['unit_id']=rows[0]['unit_id'];before=deepcopy(rows);s,_=qc.stats(rows)
        self.assertEqual(rows,before);self.assertEqual((s['n'],s['unique_units']),(4,3));self.assertEqual(s['median'],1.5)
    def test_invalid_values_and_duplicate_ids_rejected(self):
        for v in [None,True,'1',float('nan'),float('inf')]:
            with self.subTest(v=v),self.assertRaises(ValueError):qc.stats(observations([v]))
        rows=observations([1,2]);rows[1]['id']=rows[0]['id']
        with self.assertRaises(ValueError):qc.stats(rows)
    def test_binary_counts_no_continuous_statistics(self):
        s,ids=qc.stats(observations([0,1,1]),True);self.assertEqual(s['binary_counts'],[{'value':0,'count':1},{'value':1,'count':2}]);self.assertIsNone(s['median']);self.assertIsNone(s['sample_stddev']);self.assertIsNone(s['outliers']);self.assertEqual(ids,set())
        with self.assertRaises(ValueError):qc.stats(observations([2]),True)
    def test_marker_limit_does_not_truncate_statistics_or_membership(self):
        rows=observations([0]*1000+list(range(1,150)));s,ids=qc.stats(rows);self.assertEqual(s['outliers'],149);self.assertEqual(len(ids),149);self.assertEqual(len(s['outlier_points']),100);self.assertEqual(s['omitted_outlier_values'],49)
    def test_group_identity_keeps_missing_literal_and_empty_separate(self):
        pairs=[qc.group_value({'stator_batch':v},'stator_batch') for v in [None,'','未填写','空文本','全部范围']]
        self.assertEqual(len({x[0] for x in pairs}),5);self.assertEqual(len({x[1] for x in pairs}),5)
    def test_decimal_border_and_large_values_stay_finite(self):
        s,_=qc.stats(observations([.1,.2,.3,.4,.5]));self.assertEqual(s['median'],.3)
        s,_=qc.stats(observations([1e100,1e100]));self.assertEqual(s['sample_stddev'],0)

class ComparisonCohortTests(SimpleTestCase):
    def setUp(self):self.raw=fixture()
    def calculate(self,sample='first_complete',equipment='',by='equipment_id'):
        data=qb.QualityData(self.raw);d=qb.distribution(data,data.rows,'P1','R',sample,equipment);return qc.calculate(d,data.rows,by)
    def test_group_totals_reconcile_to_selected_observations(self):
        d=self.calculate();self.assertEqual(sum(g['n'] for g in d['groups']),3);self.assertEqual(d['overall']['n'],3);self.assertEqual(d['group_count'],2)
        self.assertEqual({r['id'] for r in d['observations']},{'T11-R','T22-R','T51-R'})
    def test_first_selection_precedes_equipment_filter(self):
        d=self.calculate(equipment='D2');self.assertEqual([r['session_id'] for r in d['observations']],['T22'])
    def test_all_sessions_preserve_repeated_sn_and_no_voided_future(self):
        d=self.calculate('all_valid');self.assertEqual(d['overall']['n'],6);self.assertEqual(d['overall']['unique_units'],3)
        self.assertNotIn('T31-R',{r['id'] for r in d['observations']});self.assertNotIn('FUT-R',{r['id'] for r in d['observations']})
    def test_dimensions_have_known_sources(self):
        for by in qc.GROUPS:
            d=self.calculate(by=by);self.assertEqual(sum(g['n'] for g in d['groups']),3);self.assertTrue(all(by in r for r in d['observations']))
    def test_unknown_dimension_and_excess_groups_rejected(self):
        with self.assertRaises(ValueError):self.calculate(by='operator_id')
        units=[{'id':str(i),'assembly_at':'2026-09-21','work_order_id':'W'+str(i)} for i in range(501)]
        rows=[{**r,'unit_id':str(i),'tested':'2026-09-21','equipment_id':'D'} for i,r in enumerate(observations(range(501)))]
        with self.assertRaises(ValueError):qc.calculate({'observations':rows,'binary':False},units,'work_order_id')
    def test_issue_or_wrong_unit_never_enters_comparison(self):
        self.raw['measurements'][0]['unit']='V';d=self.calculate('all_valid');self.assertNotIn('T11-R',{r['id'] for r in d['observations']})
    def test_overall_recomputed_not_average_group_median(self):
        data=qb.QualityData(self.raw);d=qb.distribution(data,data.rows,'P1','R','all_valid');d['observations'][0]['value']=100
        result=qc.calculate(d,data.rows,'equipment_id');self.assertEqual(result['overall']['median'],1)
        self.assertEqual(result['overall']['n'],len(d['observations']))

class ComparisonAPITests(PlatformCase):
    def setUp(self):
        super().setUp()
        for ds,rows in fixture().items():
            for row in rows:self.record(ds,row)
        analytics._tables.cache_clear();qb.cached.cache_clear();self.addCleanup(analytics._tables.cache_clear);self.addCleanup(qb.cached.cache_clear);self.client.force_login(self.quality)
        self.params={'product_id':'P1','spec_id':'R','sample':'first_complete','compare_by':'equipment_id'}
    def board(self,**kwargs):
        r=self.client.get('/api/quality/comparison',{**self.params,**kwargs});self.assertEqual(r.status_code,200,r.content);return r.json()
    def sample(self,d,**kwargs):return self.client.get('/api/quality/comparison/samples',{**self.params,'revision':d['revision'],**kwargs})
    def export(self,d,**kwargs):return self.client.get('/api/quality/comparison/export',{**self.params,'revision':d['revision'],**kwargs})
    def test_group_samples_and_export_share_scope(self):
        d=self.board();g=next(g for g in d['groups'] if g['label']=='D1');r=self.sample(d,group=g['key']);self.assertEqual(r.status_code,200);self.assertEqual(r.json()['total'],g['n']);self.assertEqual(r['Cache-Control'],'no-store')
        r=self.export(d,group=g['key'],mode='samples');rows=list(csv.reader(io.StringIO(r.content.decode('utf-8-sig'))));self.assertEqual(len(rows)-9,g['n']);self.assertEqual({x[5] for x in rows[9:]},{'B1'})
    def test_spec_subset_does_not_include_compliant_rows(self):
        d=self.board();r=self.sample(d,kind='outside');self.assertEqual(r.json()['total'],1);self.assertEqual(r.json()['rows'][0]['id'],'T11-R')
    def test_empty_subset_and_unknown_group_no_fallback(self):
        d=self.board();self.assertEqual(self.sample(d,kind='iqr').json()['total'],0)
        self.assertEqual(self.sample(d,group='missing').status_code,400)
    def test_revised_scope_or_missing_receipt_denied(self):
        d=self.board();self.assertEqual(self.sample(d,revision='').status_code,409);self.assertEqual(self.sample(d,compare_by='stator_batch').status_code,409);self.assertEqual(self.export(d,revision='old').status_code,409)
    def test_data_change_and_code_change_rejected(self):
        d=self.board();self.record('units',{'id':'U9','product_id':'P1','work_order_id':'W1','assembly_at':'2026-09-21T08:00:00'})
        self.assertEqual(self.sample(d).status_code,409)
        d=self.board()
        with patch('app.quality_comparison.Path.read_bytes',return_value=b'new calculation'):self.assertEqual(self.export(d).status_code,409)
    def test_no_data_stays_empty_and_binary_outliers_not_applicable(self):
        d=self.board(q='NO');self.assertEqual(d['overall']['n'],0);self.assertIsNone(d['overall']['median'])
        r=Record.objects.get(dataset='test_specs',business_key='V');r.values.update(unit='bool',lsl=1,usl=1);r.save()
        for r in Record.objects.filter(dataset='measurements'):
            if r.values['spec_id']=='V':r.values['unit']='bool';r.save()
        self.params['spec_id']='V';d=self.board();self.assertTrue(d['binary']);self.assertEqual(self.sample(d,kind='iqr').status_code,400)
    def test_invalid_params_rejected(self):
        for params in [{'spec_id':'OTHER'},{'product_id':''},{'compare_by':'bad'},{'sample':'first'},{'stage':'failed'},{'sql':'query'}]:
            self.assertEqual(self.client.get('/api/quality/comparison',{**self.params,**params}).status_code,400)
        self.assertEqual(self.client.get('/api/quality/comparison?product_id=P1&product_id=P2&spec_id=R').status_code,400)
        d=self.board()
        for params in [{'page':'no'},{'page':0},{'kind':'bad'}]:self.assertEqual(self.sample(d,**params).status_code,400)
    def test_summary_export_complete_has_units_and_no_view_pagination(self):
        d=self.board();rows=list(csv.reader(io.StringIO(self.export(d).content.decode('utf-8-sig'))));self.assertEqual(len(rows)-8,3);self.assertEqual(rows[8][0],'全范围重算');self.assertEqual(rows[8][-1],'A')
        self.assertEqual(self.export(d,group=d['groups'][0]['key']).status_code,400)
    def test_auth_and_sensitive_fields(self):
        self.assertEqual(Client().get('/api/quality/comparison',self.params).status_code,401)
        d=self.board();r=self.sample(d);self.assertNotIn('price_cents',r.content.decode());self.assertNotIn('operator_id',r.content.decode())
    def test_export_audit_rolls_back_on_failure_and_facts_unchanged(self):
        before=list(Record.objects.values_list('values',flat=True));d=self.board()
        with patch('app.quality_comparison_views.AuditEvent.objects.create',side_effect=RuntimeError('audit failure')):
            with self.assertRaises(RuntimeError):self.export(d)
        self.assertEqual(list(Record.objects.values_list('values',flat=True)),before)
        self.assertEqual(AuditEvent.objects.filter(action='quality.comparison_export').count(),0)
    def test_formula_escape_and_all_sample_pages(self):
        r=Record.objects.get(dataset='units',business_key='U1');r.values['work_order_id']='=EVIL()';r.save();d=self.board();r=self.export(d,mode='samples');rows=list(csv.reader(io.StringIO(r.content.decode('utf-8-sig'))));self.assertEqual(rows[9][4],"'=EVIL()")
        self.assertEqual(self.sample(d,page=2).json()['rows'],[])
