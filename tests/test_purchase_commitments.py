import copy,csv,io
from django.test import SimpleTestCase
from app import purchase_commitments as eng,purchase_commitment_views as views,analytics,supply
from app.models import AuditEvent,Record
from .test_supply import fixture as supply_fixture
from .test_platform import PlatformCase

def fixture():
 d=supply_fixture()
 for i,p in enumerate(d['purchase_lines'],1):
  v=dict(id='C'+str(i),purchase_line_id=p['id'],version=1,previous_id=None,status='模拟确认',confirmed='2026-09-01T10:00:00',effective='2026-09-01T11:00:00',registered='2026-09-01T12:00:00',total_qty=p['qty'],line_count=1,owner_id='E1',reference='模拟确认依据',reason='首版')
  d['purchase_commitment_versions'].append(v);d['purchase_commitment_lines'].append(dict(id=v['id']+'D1',version_id=v['id'],sequence=1,due=p['due'],qty=p['qty'],reference='模拟分段依据',note='分析假设'))
 return d
def second(d,**extra):
 v=d['purchase_commitment_versions'][0]|dict(id='C3',version=2,previous_id='C1',confirmed='2026-09-04T10:00:00',effective='2026-09-04T11:00:00',registered='2026-09-04T12:00:00',line_count=2)|extra
 d['purchase_commitment_versions'].append(v)
 for i,(qty,due) in enumerate([(4,'2026-09-05'),(6,'2026-09-08')],1):d['purchase_commitment_lines'].append(dict(id='C3D'+str(i),version_id='C3',sequence=i,due=due,qty=qty,reference='模拟分段依据',note='分析假设'))
 return v

class CommitmentLogicTests(SimpleTestCase):
 def setUp(self):self.d=fixture()
 def row(self,cutoff=None):return eng.Commitments(self.d,cutoff).index['P1']
 def test_original_and_current_are_distinct_grains(self):
  second(self.d);s=eng.summary(eng.Commitments(self.d).rows);self.assertEqual((s['original_on_time'],s['original_due']),(0,1));self.assertEqual((s['segment_on_time'],s['segment_due']),(1,2))
 def test_receipt_allocation_is_conserved(self):
  second(self.d);r=self.row();self.assertEqual([s['arrived_qty'] for s in r['segments']],[4,2]);self.assertEqual([s['remaining_qty'] for s in r['segments']],[0,4]);slices=[x for s in r['segments'] for x in s['slices']];self.assertEqual(sum(x['qty'] for x in slices),6);self.assertEqual({x['receipt_id'] for x in slices},{'R1','R2'});self.assertEqual((r['received_qty'],r['approved_qty'],r['putaway_qty']),(6,4,4))
 def test_one_receipt_spans_segments_once(self):
  second(self.d);self.d['receipts'][0]['qty']=5;r=self.row();self.assertEqual([s['arrived_qty'] for s in r['segments']],[4,3]);xs=[x for s in r['segments'] for x in s['slices'] if x['receipt_id']=='R1'];self.assertEqual([x['qty'] for x in xs],[4,1]);self.assertEqual(xs[0]['receipt_after'],xs[1]['receipt_before'])
 def test_reordering_sources_preserves_allocation(self):
  second(self.d);a=self.row();self.d['receipts'].reverse();self.d['purchase_commitment_lines'].reverse();self.assertEqual(self.row()['segments'],a['segments'])
 def test_time_ties_use_receipt_id(self):
  second(self.d);self.d['receipts'][1]['received']=self.d['receipts'][0]['received'];r=self.row();self.assertEqual(r['segments'][0]['slices'][0]['receipt_id'],'R1')
 def test_latest_missing_confirmation_blocks_no_fallback(self):
  second(self.d,confirmed=None);r=self.row();self.assertEqual(r['version_id'],'C3');self.assertFalse(r['valid']);self.assertEqual(r['segments'],[]);self.assertIsNone(r['last_due']);self.assertIsNone(r['overdue_unreceived'])
 def test_invalid_latest_quantities_and_line_counts(self):
  for change in [{'total_qty':11},{'line_count':3}]:
   self.d=fixture();second(self.d,**change);self.assertFalse(self.row()['valid'])
 def test_segment_gap_duplicate_negative_or_mismatch(self):
  for change in [{'sequence':1},{'qty':-1},{'qty':7},{'due':'2026-08-31'}]:
   self.d=fixture();second(self.d);self.d['purchase_commitment_lines'][-1].update(change);self.assertFalse(self.row()['valid'])
 def test_predecessor_corruption_blocks(self):
  second(self.d);self.d['purchase_commitment_lines'][0]['qty']=9;self.assertTrue(any('前序C1' in x for x in self.row()['issues']))
 def test_previous_cross_purchase_missing_and_skipped(self):
  for change in [{'previous_id':'C2'},{'previous_id':'absent'},{'version':3}]:
   self.d=fixture();second(self.d,**change);self.assertFalse(self.row()['valid'])
 def test_cycle_is_reported(self):
  second(self.d);self.d['purchase_commitment_versions'][0].update(version=3,previous_id='C3');r=self.row();self.assertTrue(any('循环' in x for x in r['issues']))
 def test_duplicate_version_conflict(self):
  second(self.d);self.d['purchase_commitment_versions'].append(self.d['purchase_commitment_versions'][0]|{'id':'DUP'});self.assertFalse(self.row()['valid'])
 def test_future_draft_void_not_applied_but_retained(self):
  for change in [{'registered':'2026-10-02T12:00:00'},{'effective':'2026-10-02T11:00:00','registered':'2026-10-02T12:00:00'},{'status':'草稿'},{'status':'作废'}]:
   self.d=fixture();second(self.d,**change);r=self.row();self.assertTrue(r['valid']);self.assertEqual(r['version_id'],'C1');self.assertEqual(len(r['versions']),2)
 def test_invalid_clock_sequence_blocks(self):
  second(self.d,effective='2026-09-03T10:00:00');self.assertFalse(self.row()['valid'])
 def test_change_after_original_due_flag(self):
  second(self.d,confirmed='2026-09-06T10:00:00',effective='2026-09-06T11:00:00',registered='2026-09-06T12:00:00');r=self.row();self.assertTrue(r['late_change']);self.assertEqual(r['original_due'],'2026-09-05');self.assertEqual(r['original_on_time_full'],0)
 def test_due_today_is_not_mature(self):
  second(self.d);self.d['purchase_commitment_lines'][-1]['due']='2026-10-01';r=self.row();self.assertFalse(r['segments'][-1]['due_sample']);self.assertEqual(r['segments'][-1]['overdue_unreceived'],0)
 def test_early_cutoff_filters_receipts_and_versions(self):
  second(self.d);r=self.row('2026-09-05T10:00:00');self.assertEqual(r['received_qty'],4);self.assertEqual(sum(s['arrived_qty'] for s in r['segments']),4);self.assertEqual(r['approved_qty'],0)
 def test_missing_version_does_not_erase_original_rate(self):
  self.d['purchase_commitment_versions']=[];self.d['purchase_commitment_lines']=[];s=eng.summary(eng.Commitments(self.d).rows);self.assertEqual(s['original_rate'],0);self.assertIsNone(s['segment_rate']);self.assertEqual(s['segment_excluded_rows'],2)
 def test_cancelled_not_remaining_or_denominator(self):
  self.d['purchase_lines'][1].update(status='已取消',due='2026-09-02');r=eng.Commitments(self.d).index['P2'];self.assertTrue(r['cancelled']);self.assertFalse(r['valid']);self.assertEqual(r['remaining_qty'],0);self.assertEqual(r['original_due_sample'],0)
 def test_pieces_fractional_blocks(self):
  self.d['materials'][0]['unit']='件';second(self.d);self.d['purchase_commitment_lines'][-2]['qty']=3.5;self.d['purchase_commitment_lines'][-1]['qty']=6.5;self.assertTrue(any('整数' in x for x in self.row()['issues']))
 def test_unknown_owner_and_missing_evidence_blocks(self):
  for change in [{'owner_id':'absent'},{'reference':''},{'reason':''}]:
   self.d=fixture();second(self.d,**change);self.assertFalse(self.row()['valid'])
 def test_scope_and_sources_preserved(self):
  second(self.d);old=copy.deepcopy(self.d);r=self.row();self.assertEqual(self.d,old);refs={(x['dataset'],x['key']) for x in r['sources']};self.assertIn(('purchase_commitment_versions','C1'),refs);self.assertIn(('purchase_commitment_lines','C3D2'),refs);self.assertIn(('incoming_inspections','I1'),refs)
 def test_raw_source_issues_suspend_rates_and_quantities(self):
  self.d['receipts'][0]['qty']=11;d=eng.Commitments(self.d);self.assertIsNone(eng.summary(d.rows)['original_rate']);self.assertIsNone(next(u for u in eng.unit_totals(d.rows) if u['unit']=='kg')['received_qty'])

class CommitmentApiTests(PlatformCase):
 def setUp(self):
  super().setUp();self.d=fixture();second(self.d)
  for ds,rows in self.d.items():
   for r in rows:self.record(ds,r)
  analytics._tables.cache_clear();self.addCleanup(analytics._tables.cache_clear);self.client.force_login(self.quality)
 def board(self,q=''):
  r=self.client.get('/api/purchase-commitments'+q);self.assertEqual(r.status_code,200,r.content);return r.json()
 def detail_url(self,d=None):return '/api/purchase-commitments/rows/P1?receipt='+(d or self.board())['receipt']
 def test_auth_and_method(self):
  self.client.logout();self.assertEqual(self.client.get('/api/purchase-commitments').status_code,401);self.client.force_login(self.quality);self.assertEqual(self.client.post('/api/purchase-commitments').status_code,405)
 def test_filters_strict(self):
  for q in ['?stage=bad','?unknown=x','?page=0','?q=a&q=b','?supplier_id=absent']:
   self.assertEqual(self.client.get('/api/purchase-commitments'+q).status_code,400,q)
 def test_receipt_required_bound_to_scope_and_actor(self):
  url=self.detail_url();self.assertEqual(self.client.get(url.split('?')[0]).status_code,400);self.assertEqual(self.client.get(url+'&stage=changed').status_code,409);self.client.force_login(self.admin);self.assertEqual(self.client.get(url).status_code,409)
 def test_revision_invalidates(self):
  url=self.detail_url();self.record('employees',{'id':'NEW'});self.assertEqual(self.client.get(url).status_code,409)
 def test_stage_filters_queue_not_summary(self):
  d=self.board('?stage=changed');self.assertEqual((d['total'],d['summary']['objects']),(1,2));self.assertEqual(d['facets']['changed'],1)
 def test_detail_honors_stage_and_search(self):
  d=self.board('?q=absent');self.assertEqual(self.client.get(self.detail_url(d)+'&q=absent').status_code,404)
  d=self.board('?stage=attention');self.assertEqual(self.client.get(self.detail_url(d)+'&stage=attention').status_code,404)
 def test_sources_do_not_expose_money(self):
  d=self.board();r=self.client.get(self.detail_url(d));self.assertEqual(r.status_code,200);self.assertNotIn('cents',r.content.decode());e=self.client.get(self.detail_url(d).replace('?','/evidence?'));self.assertEqual(e.status_code,200);self.assertTrue(all(x['filename']=='unit-test.xlsx' for x in e.json()['rows']));self.assertFalse(e.json()['can_download_original'])
 def test_csv_full_scope_not_page_and_audit(self):
  d=self.board('?page=100');r=self.client.get('/api/purchase-commitments/export?page=100&receipt='+d['receipt']);self.assertEqual(r.status_code,200);rows=list(csv.reader(io.StringIO(r.content.decode('utf-8-sig'))));self.assertEqual(len(rows),7);self.assertEqual(AuditEvent.objects.filter(action='purchase_commitments.export').count(),1)
 def test_segment_export_and_unknown_blank(self):
  Record.objects.filter(dataset='purchase_commitment_versions',business_key='C3').update(values=self.d['purchase_commitment_versions'][-1]|{'confirmed':None});analytics._tables.cache_clear();d=self.board();r=self.client.get('/api/purchase-commitments/segments-export?receipt='+d['receipt']);rows=list(csv.reader(io.StringIO(r.content.decode('utf-8-sig'))));x=next(x for x in rows[5:] if x[0]=='P1');self.assertEqual(x[3],'False');self.assertTrue(all(v=='' for v in x[4:-1]))
 def test_stale_export_no_write(self):
  before=Record.objects.count();self.assertEqual(self.client.get('/api/purchase-commitments/export?receipt=bad').status_code,409);self.assertFalse(AuditEvent.objects.filter(action='purchase_commitments.export').exists());self.assertEqual(Record.objects.count(),before)
