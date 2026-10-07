import copy,csv,io
from django.test import SimpleTestCase
from app import incoming_quality as eng,analytics,supply
from app.models import AuditEvent,Record
from tests.test_supply import fixture as source_fixture
from tests.test_platform import PlatformCase

def fixture():
    d=source_fixture();d['incoming_specs']=[dict(id='A',material_id='M1',version='V1',parameter='WIDTH',name='宽度',unit='mm',lsl=9,usl=11,mandatory=True,effective='2026-08-01',expires=None,basis='模拟范围'),dict(id='B',material_id='M1',version='V1',parameter='VALUE',name='辅助量',unit='演示单位',lsl=2,usl=None,mandatory=True,effective='2026-08-01',expires=None,basis='模拟范围')]
    d['incoming_check_plans']=[dict(id='P',inspection_id='I1',spec_version='V1',sample_count=2,created='2026-09-05T09:15:00',due='2026-09-05T11:00:00',owner_id='E1',reference='依据',note='模拟计划')]
    d['incoming_checks']=[dict(id='C1',plan_id='P',checked='2026-09-05T11:45:00',registered='2026-09-05T11:46:00',inspector_id='E1',voided=False,reference='原记录',reason='模拟采集')]
    d['incoming_readings']=[dict(id=f'R{n}{s}',check_id='C1',sample_no=n,spec_id=s,value=10 if s=='A' else 2,unit='mm' if s=='A' else '演示单位',instrument='演示采集点',file_reference='模拟外部编号') for n in [1,2] for s in ['A','B']]
    return d

class IncomingQualityTests(SimpleTestCase):
    def setUp(self):self.d=fixture()
    def data(self,cutoff=None):return eng.IncomingQuality(self.d,cutoff)
    def row(self):return self.data().index['I1']
    def second(self,**change):
        c=self.d['incoming_checks'][0]|dict(id='C2',checked='2026-09-05T11:55:00',registered='2026-09-05T11:56:00')|change;self.d['incoming_checks'].append(c)
        rr=[v|dict(id=v['id']+'C2',check_id='C2') for v in self.d['incoming_readings'] if v['check_id']=='C1'];self.d['incoming_readings']+=rr;return c,rr
    def test_samples_and_original_conclusion_are_different_grains(self):
        r=self.row();self.assertEqual((r['state'],r['latest_defect_count'],r['raw_defect_count']),('pass',0,0));self.assertEqual(r['executions'][0]['known_samples'],2);self.assertEqual(len(r['executions'][0]['values']),4)
        self.d['incoming_readings'][0]['value']=12;r=self.row();self.assertEqual((r['state'],r['latest_defect_count'],r['raw_result'],r['raw_disposition']),('out',1,'合格','批准入库'));self.assertTrue(r['disagreement'])
    def test_multiple_out_items_count_one_defective_sample(self):
        self.d['incoming_readings'][0]['value']=12;self.d['incoming_readings'][1]['value']=1;self.assertEqual(self.row()['latest_defect_count'],1)
    def test_missing_mandatory_not_zero_or_complete(self):
        self.d['incoming_readings'].pop();r=self.row();self.assertEqual(r['state'],'missing');self.assertIsNone(r['latest_defect_count']);self.assertEqual(r['executions'][0]['missing_samples'],1)
    def test_missing_optional_is_allowed(self):
        self.d['incoming_specs'].append(self.d['incoming_specs'][0]|dict(id='C',parameter='OPTIONAL',mandatory=False));self.assertEqual(self.row()['state'],'pass')
    def test_optional_out_and_bad_optional_are_not_hidden(self):
        self.d['incoming_specs'].append(self.d['incoming_specs'][0]|dict(id='C',parameter='OPTIONAL',mandatory=False));self.d['incoming_readings'].append(self.d['incoming_readings'][0]|dict(id='OPT',spec_id='C',value=12));self.assertEqual(self.row()['latest_defect_count'],1)
        self.d['incoming_readings'][-1]['unit']='bad';self.assertEqual(self.row()['state'],'attention')
    def test_limits_inclusive_and_one_sided(self):
        self.d['incoming_readings'][0]['value']=9;self.d['incoming_readings'][2]['value']=11;self.assertEqual(self.row()['state'],'pass')
        self.d['incoming_readings'][1]['value']=1.99;self.assertEqual(self.row()['latest_defect_count'],1)
    def test_invalid_latest_never_falls_back_to_clean_first(self):
        c,rr=self.second();rr[0]['unit']='bad';r=self.row();self.assertEqual(r['first_id'],'C1');self.assertEqual((r['latest_id'],r['state']),('C2','attention'));self.assertIsNone(r['latest_defect_count'])
    def test_empty_latest_never_falls_back(self):
        self.second();self.d['incoming_readings']=[v for v in self.d['incoming_readings'] if v['check_id']=='C1'];r=self.row();self.assertEqual((r['latest_id'],r['state']),('C2','missing'))
    def test_void_and_future_registration_keep_history_without_adoption(self):
        for change in [dict(voided=True),dict(registered='2026-10-02T09:00:00'),dict(checked='2026-10-02T09:00:00',registered='2026-10-02T09:01:00')]:
            self.d=fixture();self.second(**change);r=self.row();self.assertEqual(r['latest_id'],'C1');self.assertEqual(r['excluded_count'],1);self.assertEqual(len(r['executions']),2)
    def test_same_time_pauses_first_latest_but_all_mode_is_explicit(self):
        self.second(checked='2026-09-05T11:45:00');d=self.data();r=d.index['I1'];self.assertIsNone(r['latest_id']);self.assertIsNone(r['first_id']);self.assertEqual(r['state'],'attention')
        self.assertEqual(d.distribution([r],'A','latest')['n'],0);all_values=d.distribution([r],'A','all');self.assertEqual((all_values['n'],all_values['inspection_count'],all_values['check_count']),(4,1,2))
    def test_invalid_timestamp_does_not_guess_sequence(self):
        self.second(checked='bad');r=self.row();self.assertIsNone(r['latest_id']);self.assertTrue(r['ordering_issues'])
    def test_plan_counts_must_match_original_sample_count(self):
        for v in [0,-1,True,1,10001]:
            self.d=fixture();self.d['incoming_check_plans'][0]['sample_count']=v;self.assertEqual(self.row()['state'],'attention')
    def test_duplicate_plan_not_double_counted(self):
        self.d['incoming_check_plans'].append(self.d['incoming_check_plans'][0]|dict(id='P2'));r=self.row();self.assertEqual(r['state'],'attention');self.assertIsNone(r['plan_id']);self.assertEqual(eng.summary(self.data().rows)['objects'],2)
        self.assertTrue(any(x['dataset']=='incoming_checks' and x['key']=='C1' for x in r['sources']))
        self.assertEqual(sum(x['dataset']=='incoming_readings' for x in r['sources']),4)
    def test_no_plan_and_no_execution_are_distinct(self):
        self.assertEqual(self.data().index['I2']['state'],'no_plan');self.d['incoming_checks']=[];self.assertEqual(self.row()['state'],'pending')
    def test_duplicate_reading_and_out_of_range_sample_block(self):
        self.d['incoming_readings'].append(self.d['incoming_readings'][0]|dict(id='DUP'));self.assertEqual(self.row()['state'],'attention')
        for n in [0,3,True]:
            self.d=fixture();self.d['incoming_readings'][0]['sample_no']=n;self.assertEqual(self.row()['state'],'attention')
    def test_invalid_units_values_and_missing_instrument_block(self):
        for change in [dict(unit='cm'),dict(value=float('nan')),dict(value=float('inf')),dict(value=True),dict(instrument=''),dict(file_reference=''),dict(spec_id='absent')]:
            self.d=fixture();self.d['incoming_readings'][0].update(change);self.assertEqual(self.row()['state'],'attention',change)
    def test_wrong_material_version_and_overlapping_norms_block(self):
        for change in [dict(material_id='M2'),dict(version='V2')]:
            self.d=fixture();self.d['incoming_specs'][0].update(change);self.assertEqual(self.row()['state'],'attention')
        self.d=fixture();self.d['incoming_specs'].append(self.d['incoming_specs'][0]|dict(id='ADUP'));self.assertEqual(self.row()['state'],'attention')
    def test_norm_effective_and_exclusive_expiry_are_preserved(self):
        self.d['incoming_specs'][0]['expires']='2026-09-05';self.assertEqual(self.row()['state'],'attention')
        self.d=fixture();self.d['incoming_specs'][0]['effective']='2026-09-06';self.assertEqual(self.row()['state'],'attention')
    def test_invalid_norm_range_or_no_required_items_not_healthy(self):
        for change in [dict(lsl=12,usl=11),dict(lsl=None,usl=None),dict(lsl=float('inf')),dict(basis='')]:
            self.d=fixture();self.d['incoming_specs'][0].update(change);self.assertEqual(self.row()['state'],'attention')
        self.d=fixture()
        for s in self.d['incoming_specs']:s['mandatory']=False
        self.assertEqual(self.row()['state'],'attention')
    def test_temporal_owner_and_original_physical_errors_stay_visible(self):
        for ds,change in [('incoming_check_plans',dict(created='2026-09-05T08:00:00')),('incoming_check_plans',dict(due='2026-09-05T13:00:00')),('incoming_checks',dict(registered='2026-09-05T11:40:00')),('incoming_checks',dict(inspector_id='unknown'))]:
            self.d=fixture();self.d[ds][0].update(change);self.assertEqual(self.row()['state'],'attention')
        self.d=fixture();self.d['inventory_movements'][1]['lot']='wrong';self.assertEqual(self.row()['state'],'attention')
    def test_cutoff_and_future_plan_do_not_create_current_coverage(self):
        d=self.data('2026-09-05T12:00:00');self.assertEqual(len(d.rows),1);self.assertEqual(d.index['I1']['state'],'pass')
        self.d['incoming_check_plans'][0]['created']='2026-10-02T09:00:00';self.assertEqual(self.row()['state'],'no_plan')
    def test_distribution_single_spec_equal_values_and_missing_other_feature(self):
        self.d['incoming_readings'].pop();d=self.data();x=d.distribution(d.rows,'A');self.assertEqual((x['n'],x['mean'],x['inspection_count'],len(x['bins'])),(2,10,1,1));self.assertEqual(sum(b['count'] for b in x['bins']),2)
        with self.assertRaises(ValueError):d.distribution(d.rows,'absent')
    def test_histogram_conservation_including_maximum(self):
        self.d['incoming_readings'][0]['value']=9;self.d['incoming_readings'][2]['value']=11;x=self.data().distribution(self.data().rows,'A');self.assertEqual(sum(b['count'] for b in x['bins']),2);self.assertEqual((x['bins'][0]['count'],x['bins'][-1]['count']),(1,1))
    def test_distribution_first_latest_all_scopes_and_exclusions(self):
        c,rr=self.second();rr[0]['value']=12;d=self.data();self.assertEqual(d.distribution(d.rows,'A','first')['out'],0);self.assertEqual(d.distribution(d.rows,'A','latest')['out'],1);self.assertEqual(d.distribution(d.rows,'A','all')['n'],4)
        rr[0]['unit']='bad';d=self.data();x=d.distribution(d.rows,'A');self.assertEqual((x['n'],len(x['exclusions'])),(0,2))
    def test_one_spec_id_never_pools_new_version(self):
        self.d['incoming_specs'].append(self.d['incoming_specs'][0]|dict(id='A2',version='V2'));x=self.data().distribution(self.data().rows,'A2');self.assertEqual(x['n'],0);self.assertIsNone(x['mean'])
    def test_search_dates_and_empty_cohort(self):
        d=self.data();self.assertEqual(len(d.cohort(dict(inspection_from='2026-09-06'))),1);self.assertEqual(d.cohort(dict(q='absent')),[]);self.assertEqual(eng.summary([])['objects'],0)
    def test_global_orphans_visible_and_input_immutable(self):
        self.d['incoming_checks'].append(self.d['incoming_checks'][0]|dict(id='ORPHAN',plan_id='absent'));self.d['incoming_readings'].append(self.d['incoming_readings'][0]|dict(id='ORPHAN',check_id='absent'));before=copy.deepcopy(self.d);d=self.data();self.assertEqual(len(d.global_issues),2);self.assertEqual(self.d,before)
    def test_raw_supply_unchanged_by_recheck(self):
        old=supply.SupplyData(self.d);c,rr=self.second();rr[0]['value']=12;self.data();new=supply.SupplyData(self.d);self.assertEqual([supply.clean(r) for r in old.po_rows],[supply.clean(r) for r in new.po_rows])

class IncomingQualityApiTests(PlatformCase):
    def setUp(self):
        super().setUp();self.d=fixture()
        for ds,rows in self.d.items():
            for r in rows:self.record(ds,r)
        analytics._tables.cache_clear();self.addCleanup(analytics._tables.cache_clear);self.client.force_login(self.quality)
    def board(self,q=''):
        r=self.client.get('/api/incoming-quality'+q);self.assertEqual(r.status_code,200,r.content);return r.json()
    def url(self,d=None):return '/api/incoming-quality/rows/I1?receipt='+(d or self.board())['receipt']
    def test_auth_methods_and_no_store(self):
        self.assertEqual(self.client.get('/api/incoming-quality')['Cache-Control'],'no-store');self.client.logout();self.assertEqual(self.client.get('/api/incoming-quality').status_code,401);self.client.force_login(self.quality);self.assertEqual(self.client.post('/api/incoming-quality').status_code,405)
    def test_strict_filters_dates_duplicates_and_norm(self):
        for q in ['?mode=bad','?stage=bad','?unknown=x','?page=0','?q=a&q=b','?material_id=absent','?spec_id=absent','?inspection_from=20260905','?inspection_to=2026-10-02','?inspection_from=2026-09-06&inspection_to=2026-09-05']:
            self.assertEqual(self.client.get('/api/incoming-quality'+q).status_code,400,q)
    def test_receipt_required_and_bound_to_scope_actor_and_revision(self):
        url=self.url();self.assertEqual(self.client.get(url.split('?')[0]).status_code,400);self.assertEqual(self.client.get(url+'&mode=first').status_code,409);self.client.force_login(self.admin);self.assertEqual(self.client.get(url).status_code,409)
        self.client.force_login(self.quality);self.record('employees',dict(id='NEW'));self.assertEqual(self.client.get(url).status_code,409)
    def test_queue_scope_and_analysis_scope_are_explicit(self):
        d=self.board('?stage=no_plan&spec_id=A');self.assertEqual((d['summary']['objects'],d['total'],d['distribution']['n']),(2,1,0));d=self.board('?inspection_from=2026-09-06');self.assertEqual(d['summary']['objects'],1)
    def test_detail_stage_and_empty_search_do_not_fallback(self):
        for q in ['q=absent','stage=no_plan']:
            d=self.board('?'+q);self.assertEqual(self.client.get(self.url(d)+'&'+q).status_code,404)
    def test_sources_and_detail_hide_prices(self):
        d=self.board();r=self.client.get(self.url(d));self.assertEqual(r.status_code,200);self.assertNotIn('cents',r.content.decode());e=self.client.get(self.url(d).replace('?','/evidence?')).json();self.assertTrue(e['rows']);self.assertFalse(e['can_download_original']);self.assertTrue(all(r['filename']=='unit-test.xlsx' for r in e['rows']))
    def test_full_queue_export_not_page_and_unknown_blank(self):
        d=self.board('?page=100');r=self.client.get('/api/incoming-quality/export?page=100&receipt='+d['receipt']);rows=list(csv.reader(io.StringIO(r.content.decode('utf-8-sig'))));self.assertEqual(len(rows),7);unknown=next(r for r in rows[5:] if r[0]=='I2');self.assertEqual(unknown[16],'');self.assertEqual(AuditEvent.objects.filter(action='incoming_quality.export').count(),1)
    def test_measurement_export_spec_selection_and_full_rows(self):
        d=self.board();self.assertEqual(self.client.get('/api/incoming-quality/measurements-export?receipt='+d['receipt']).status_code,400)
        d=self.board('?spec_id=A&page=100');r=self.client.get('/api/incoming-quality/measurements-export?spec_id=A&page=100&receipt='+d['receipt']);rows=list(csv.reader(io.StringIO(r.content.decode('utf-8-sig'))));self.assertEqual(len(rows),7);self.assertTrue(all(r[5]=='A' for r in rows[5:]));self.assertEqual(AuditEvent.objects.filter(action='incoming_quality.measurement_export').count(),1)
    def test_stale_export_does_not_write(self):
        n=Record.objects.count();self.assertEqual(self.client.get('/api/incoming-quality/export?receipt=bad').status_code,409);self.assertFalse(AuditEvent.objects.filter(action='incoming_quality.export').exists());self.assertEqual(Record.objects.count(),n)
