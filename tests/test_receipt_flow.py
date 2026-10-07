import copy,csv,io
from django.test import SimpleTestCase
from app import receipt_flow as eng,analytics,supply
from app.models import Record,AuditEvent
from tests.test_supply import fixture as supply_fixture
from tests.test_platform import PlatformCase

def fixture():
    d=supply_fixture()
    d['receipt_jobs']=[dict(id='JQ1',receipt_id='R1',stage='来料检验',created='2026-09-05T09:00:00',reference='任务Q1',note='模拟工位窗口'),dict(id='JP1',receipt_id='R1',stage='入库上架',created='2026-09-05T09:00:00',reference='任务P1',note='模拟工位窗口')]
    common=dict(version=1,previous_id=None,status='模拟确认',owner_id='E1',station='A1',reference='登记依据',reason='模拟登记')
    d['receipt_job_versions']=[common|dict(id='LQ1',job_id='JQ1',assigned='2026-09-05T09:30:00',started='2026-09-05T10:00:00',finished='2026-09-05T12:00:00',inspection_id='I1',movement_id=None,registered='2026-09-05T12:10:00'),common|dict(id='LP1',job_id='JP1',assigned='2026-09-05T12:15:00',started='2026-09-05T13:00:00',finished='2026-09-05T14:00:00',inspection_id=None,movement_id='V2',registered='2026-09-05T14:10:00')]
    return d

class ReceiptFlowTests(SimpleTestCase):
    def setUp(self):self.d=fixture()
    def data(self,cutoff=None):return eng.ReceiptFlow(self.d,cutoff)
    def row(self,key='R1',cutoff=None):return self.data(cutoff).index[key]
    def revised(self,**change):
        v=self.d['receipt_job_versions'][0]|dict(id='LQ2',version=2,previous_id='LQ1',registered='2026-09-05T12:20:00')|change
        self.d['receipt_job_versions'].append(v);return v
    def test_closed_and_open_samples_have_separate_origins(self):
        d=self.data();s=eng.summary(d.rows)
        self.assertEqual((s['objects'],s['completed'],s['disposition']),(2,1,1))
        self.assertEqual((s['inspection_elapsed']['n'],s['inspection_elapsed']['median'],s['stock_elapsed']['n'],s['stock_elapsed']['median']),(2,3,1,5))
        self.assertEqual(d.index['R2']['open_observation_hours'],606)
        self.assertIsNone(d.index['R2']['stock_hours']);self.assertEqual(s['open_states'][1]['n'],1)
    def test_parts_conserve_original_elapsed_and_unit_quantities(self):
        r=self.row()
        for key,expected in [('inspection_decomposition',(3,1,2,0)),('putaway_decomposition',(2,1,1,0))]:
            p=r[key];self.assertTrue(p['known']);self.assertEqual(tuple(p[k] for k in ['total_hours','before_start_hours','work_hours','gap_hours']),expected)
        s=eng.summary(self.data().rows);u=s['units'][0];self.assertEqual(u['unit'],'kg');self.assertEqual(sum(x['qty'] for x in u['states']),6)
    def test_partial_posting_is_open_not_complete(self):
        self.d['inventory_movements'][1]['qty_signed']=2;r=self.row()
        self.assertEqual((r['state'],r['putaway_qty'],r['unposted_qty']),('putaway',2,2));self.assertIsNone(r['stock_hours']);self.assertIsNone(r['full_stock_at'])
        self.assertEqual(r['observation_from'],'2026-09-05T12:00:00');self.assertFalse(r['putaway_decomposition']['known'])
    def test_cumulative_split_posting_finishes_at_last_needed_move(self):
        self.d['inventory_movements'][1]['qty_signed']=2
        self.d['inventory_movements'].append(self.d['inventory_movements'][1]|dict(id='V3',qty_signed=2,location='A3',occurred='2026-09-06T14:00:00'))
        r=self.row();self.assertEqual((r['state'],r['stock_hours'],r['putaway_qty']),('complete',29,4));self.assertFalse(r['putaway_decomposition']['known'])
    def test_no_inspection_remains_waiting_without_fake_zero(self):
        self.d['incoming_inspections']=[self.d['incoming_inspections'][1]];self.d['inventory_movements']=[self.d['inventory_movements'][0]];self.d['receipts'][0]['status']='待检';r=self.row()
        self.assertEqual(r['state'],'waiting_inspection');self.assertEqual(r['open_observation_hours'],633);self.assertIsNone(r['inspection_hours'])
    def test_reinspection_does_not_replace_first_node_or_historic_approval(self):
        self.d['incoming_inspections'].append(self.d['incoming_inspections'][0]|dict(id='I3',inspected='2026-09-06T12:00:00'))
        r=self.row();self.assertEqual((r['first_inspection_id'],r['inspection_hours'],r['approval_before_first_stock']),('I1',3,'2026-09-05T12:00:00'));self.assertTrue(r['putaway_decomposition']['known'])
    def test_new_rejection_blocks_physical_statistics(self):
        self.d['incoming_inspections'].append(self.d['incoming_inspections'][1]|dict(id='I3',receipt_id='R1',inspected='2026-09-06T12:00:00'));r=self.row()
        self.assertEqual(r['state'],'attention');self.assertIsNone(r['stock_hours']);self.assertIsNone(r['approval_before_first_stock']);self.assertFalse(r['inspection_decomposition']['known'])
    def test_registration_gap_is_separate_from_work(self):
        self.d['receipt_job_versions'][0]['finished']='2026-09-05T11:30:00';p=self.row()['inspection_decomposition']
        self.assertTrue(p['known']);self.assertEqual((p['total_hours'],p['before_start_hours'],p['work_hours'],p['gap_hours']),(3,1,1.5,.5))
    def test_parallel_windows_are_union_not_duration_sum(self):
        self.d['receipt_job_versions'][0]['finished']='2026-09-05T11:30:00'
        self.d['receipt_jobs'].append(self.d['receipt_jobs'][0]|dict(id='JQ3'))
        self.d['receipt_job_versions'].append(self.d['receipt_job_versions'][0]|dict(id='LQ3',job_id='JQ3',started='2026-09-05T11:00:00',finished='2026-09-05T12:00:00'))
        p=self.row()['inspection_decomposition'];self.assertTrue(p['known']);self.assertEqual(p['work_hours'],2);self.assertEqual(p['gap_hours'],0)
    def test_disjoint_windows_keep_uncovered_interval(self):
        self.d['receipt_job_versions'][0]['finished']='2026-09-05T10:30:00';self.d['receipt_jobs'].append(self.d['receipt_jobs'][0]|dict(id='JQ3'))
        self.d['receipt_job_versions'].append(self.d['receipt_job_versions'][0]|dict(id='LQ3',job_id='JQ3',started='2026-09-05T11:00:00',finished='2026-09-05T11:30:00'))
        p=self.row()['inspection_decomposition'];self.assertEqual((p['work_hours'],p['gap_hours']),(1,1))
    def test_zero_duration_is_known_zero(self):
        self.d['receipt_job_versions'][0]['started']='2026-09-05T12:00:00';p=self.row()['inspection_decomposition'];self.assertTrue(p['known']);self.assertEqual(p['work_hours'],0)
    def test_latest_error_does_not_fallback_or_erase_raw_nodes(self):
        self.revised(assigned=None);r=self.row();self.assertEqual(r['jobs'][0]['selected']['id'],'LQ2');self.assertFalse(r['inspection_decomposition']['known']);self.assertIsNone(r['jobs'][0]['work_hours']);self.assertEqual((r['state'],r['inspection_hours'],r['stock_hours']),('complete',3,5))
    def test_future_draft_void_revisions_do_not_replace_confirmed(self):
        for change in [dict(registered='2026-10-02T09:00:00'),dict(status='草稿'),dict(status='作废')]:
            self.d=fixture();self.revised(**change);r=self.row();self.assertTrue(r['jobs'][0]['valid']);self.assertEqual(r['jobs'][0]['selected']['id'],'LQ1');self.assertEqual(len(r['jobs'][0]['versions']),2)
    def test_missing_or_noncontinuous_predecessor_blocks(self):
        for change in [dict(previous_id=None),dict(previous_id='absent'),dict(version=3),dict(previous_id='LP1')]:
            self.d=fixture();self.revised(**change);self.assertFalse(self.row()['jobs'][0]['valid'])
    def test_duplicate_confirmed_version_blocks(self):
        self.d['receipt_job_versions'].append(self.d['receipt_job_versions'][0]|dict(id='LQ1B'));self.assertFalse(self.row()['jobs'][0]['valid'])
    def test_invalid_predecessor_cannot_be_hidden_by_clean_revision(self):
        self.revised();self.d['receipt_job_versions'][0]['assigned']=None;self.assertTrue(any('前序' in x for x in self.row()['jobs'][0]['issues']))
    def test_cycle_and_registration_reversal_block(self):
        v=self.revised();self.d['receipt_job_versions'][0].update(version=2,previous_id='LQ2');self.assertFalse(self.row()['jobs'][0]['valid'])
        self.d=fixture();self.revised(registered='2026-09-05T12:05:00');self.assertFalse(self.row()['jobs'][0]['valid'])
    def test_source_owner_and_timestamp_errors_do_not_decompose(self):
        for change in [dict(owner_id='absent'),dict(reference=''),dict(station=''),dict(inspection_id='I2'),dict(movement_id='V2'),dict(started='2026-09-05T12:05:00'),dict(finished='2026-09-05T12:05:00'),dict(assigned='2026-09-05T08:00:00')]:
            self.d=fixture();self.d['receipt_job_versions'][0].update(change);self.assertFalse(self.row()['inspection_decomposition']['known'],change)
    def test_stock_work_requires_approval_at_start(self):
        self.d['receipt_job_versions'][1].update(assigned='2026-09-05T11:00:00',started='2026-09-05T11:30:00');self.assertFalse(self.row()['jobs'][1]['valid'])
    def test_missing_job_is_unknown_not_zero(self):
        self.d['receipt_jobs']=[];self.d['receipt_job_versions']=[];s=eng.summary(self.data().rows)
        self.assertEqual(s['decompositions'][0]['n'],0);self.assertEqual(s['decompositions'][0]['unknown'],2);self.assertIsNone(s['decompositions'][0]['means']['work_hours']);self.assertEqual(s['inspection_elapsed']['n'],2)
    def test_open_work_window_stays_out_of_completed_sample(self):
        self.d['receipt_job_versions'][0].update(finished=None,inspection_id=None,registered='2026-09-05T10:10:00')
        r=self.row(cutoff='2026-09-05T11:00:00');j=r['jobs'][0];self.assertTrue(j['valid']);self.assertEqual(j['open_work_hours'],1);self.assertIsNone(j['work_hours']);self.assertEqual(r['state'],'waiting_inspection');self.assertIsNone(r['inspection_hours'])
    def test_cutoff_excludes_future_physical_nodes_and_versions(self):
        d=self.data('2026-09-05T12:05:00');self.assertEqual(len(d.rows),1);r=d.index['R1'];self.assertEqual(r['state'],'putaway');self.assertIsNone(r['jobs'][0]['selected']);self.assertEqual(r['putaway_qty'],0)
    def test_future_task_header_not_counted_as_coverage(self):
        self.d['receipt_jobs'][0]['created']='2026-10-02T09:00:00';r=self.row();self.assertFalse(r['inspection_decomposition']['known']);self.assertFalse(r['jobs'][0]['issues'])
    def test_global_orphans_are_visible(self):
        self.d['receipt_jobs'].append(self.d['receipt_jobs'][0]|dict(id='ORPHAN',receipt_id='absent'));self.d['receipt_job_versions'].append(self.d['receipt_job_versions'][0]|dict(id='ORPHAN',job_id='absent'));self.assertEqual(len(self.data().global_issues),2)
    def test_scope_dates_are_receipt_dates_and_units_not_mixed(self):
        f=dict(received_from='2026-09-06',received_to='2026-09-06');self.assertEqual([r['id'] for r in self.data().cohort(f)],['R2'])
        self.d['receipts'].append(self.d['receipts'][0]|dict(id='R3',purchase_line_id='P2',material_id='M2',qty=2,status='待检'));s=eng.summary(self.data().rows);self.assertEqual({u['unit'] for u in s['units']},{'kg','件'})
    def test_quantiles_empty_single_and_linear_interpolation(self):
        self.assertIsNone(eng.stats([])['p90']);self.assertEqual(eng.stats([None,3])['p90'],3);self.assertAlmostEqual(eng.stats([1,3,5,7])['p90'],6.4)
    def test_no_source_mutation_and_existing_supply_unchanged(self):
        before=copy.deepcopy(self.d);old=supply.SupplyData(self.d);self.data();self.assertEqual(self.d,before);now=supply.SupplyData(self.d)
        self.assertEqual([supply.clean(r) for r in old.po_rows],[supply.clean(r) for r in now.po_rows]);self.assertEqual([supply.clean(r) for r in old.lots],[supply.clean(r) for r in now.lots])

class ReceiptFlowApiTests(PlatformCase):
    def setUp(self):
        super().setUp();self.d=fixture()
        for ds,rows in self.d.items():
            for r in rows:self.record(ds,r)
        analytics._tables.cache_clear();self.addCleanup(analytics._tables.cache_clear);self.client.force_login(self.quality)
    def board(self,q=''):
        r=self.client.get('/api/receipt-flow'+q);self.assertEqual(r.status_code,200,r.content);return r.json()
    def detail_url(self,d=None):return '/api/receipt-flow/rows/R1?receipt='+(d or self.board())['receipt']
    def test_auth_method_and_no_store(self):
        self.assertEqual(self.client.get('/api/receipt-flow')['Cache-Control'],'no-store');self.client.logout();self.assertEqual(self.client.get('/api/receipt-flow').status_code,401);self.client.force_login(self.quality);self.assertEqual(self.client.post('/api/receipt-flow').status_code,405)
    def test_invalid_filter_date_duplicate_and_page_are_rejected(self):
        for q in ['?stage=bad','?unknown=x','?page=0','?q=a&q=b','?supplier_id=absent','?received_from=20260905','?received_to=2026-10-02','?received_from=2026-09-06&received_to=2026-09-05']:
            self.assertEqual(self.client.get('/api/receipt-flow'+q).status_code,400,q)
    def test_scope_actor_and_revision_bind_detail_receipt(self):
        url=self.detail_url();self.assertEqual(self.client.get(url.split('?')[0]).status_code,400);self.assertEqual(self.client.get(url+'&stage=complete').status_code,409);self.client.force_login(self.admin);self.assertEqual(self.client.get(url).status_code,409)
        self.client.force_login(self.quality);self.record('employees',dict(id='NEW'));self.assertEqual(self.client.get(url).status_code,409)
    def test_stage_filters_queue_not_summary_and_date_filters_both(self):
        d=self.board('?stage=complete');self.assertEqual((d['total'],d['summary']['objects']),(1,2));d=self.board('?received_from=2026-09-06');self.assertEqual((d['total'],d['summary']['objects']),(1,1));self.assertEqual(d['summary']['completed'],0)
    def test_detail_honors_stage_and_search(self):
        for q in ['q=absent','stage=disposition']:
            d=self.board('?'+q);self.assertEqual(self.client.get(self.detail_url(d)+'&'+q).status_code,404)
    def test_private_money_fields_hidden_and_source_metadata_preserved(self):
        r=self.client.get(self.detail_url());self.assertEqual(r.status_code,200);self.assertNotIn('cents',r.content.decode());e=self.client.get(self.detail_url().replace('?','/evidence?')).json();self.assertFalse(e['can_download_original']);self.assertTrue(e['rows']);self.assertTrue(all(x['filename']=='unit-test.xlsx' for x in e['rows']))
    def test_exports_full_scope_not_page_and_unknown_parts_blank(self):
        d=self.board('?page=100');r=self.client.get('/api/receipt-flow/export?page=100&receipt='+d['receipt']);rows=list(csv.reader(io.StringIO(r.content.decode('utf-8-sig'))));self.assertEqual(len(rows),7);unknown=next(r for r in rows[5:] if r[0]=='R2');self.assertTrue(all(x=='' for x in unknown[17:25]));self.assertEqual(AuditEvent.objects.filter(action='receipt_flow.export').count(),1)
    def test_job_export_selects_current_invalid_candidate_with_blank_hours(self):
        v=self.d['receipt_job_versions'][0]|dict(id='LQ2',version=2,previous_id='LQ1',assigned=None,registered='2026-09-05T12:20:00');self.record('receipt_job_versions',v);analytics._tables.cache_clear();d=self.board();r=self.client.get('/api/receipt-flow/jobs-export?receipt='+d['receipt']);rows=list(csv.reader(io.StringIO(r.content.decode('utf-8-sig'))));x=next(r for r in rows[5:] if r[1]=='JQ1');self.assertEqual((x[3],x[4]),('False','LQ2'));self.assertEqual(x[-3:-1],['','']);self.assertEqual(AuditEvent.objects.filter(action='receipt_flow.jobs_export').count(),1)
    def test_stale_export_does_not_write_audit_or_facts(self):
        n=Record.objects.count();self.assertEqual(self.client.get('/api/receipt-flow/export?receipt=bad').status_code,409);self.assertFalse(AuditEvent.objects.filter(action='receipt_flow.export').exists());self.assertEqual(Record.objects.count(),n)
