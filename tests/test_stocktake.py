import copy,csv,io
from django.test import SimpleTestCase
from django.contrib.auth.models import User,Group
from app import stocktake as eng,stocktake_views as views,analytics
from app.schema import SCHEMAS
from app.models import Record,AuditEvent
from .test_platform import PlatformCase

def fixture():
 d={k:[] for k in SCHEMAS}
 d['materials']=[{'id':'0001','name':'轴承','unit':'件','category':'外购件','safety_qty':2,'spec':'6202'}]
 d['employees']=[{'id':str(i),'name':'模拟人员'+str(i)} for i in range(1,4)]
 d['inventory_opening']=[{'id':'OPEN1','material_id':'0001','lot':'LOT1','location':'CK01-A01','as_of':'2026-09-01','qty':10,'unit_cost_cents':918273,'status':'可用'}]
 d['stocktake_runs']=[{'id':'PD001','kind':'范围全盘','location_prefix':'CK01','book_at':'2026-09-23T07:00:00','freeze_start':'2026-09-23T07:00:00','freeze_end':'2026-09-23T12:00:00','line_count':1,'owner_id':'1','status':'已登记','freeze_evidence':'模拟封库登记'}]
 d['stocktake_lines']=[{'id':'PD001-01','run_id':'PD001','material_id':'0001','lot':'LOT1','location':'CK01-A01','unit':'件','initial_qty':8,'counted':'2026-09-23T08:00:00','counter_id':'2','note':'合成盘点'}]
 return d
def recount(d,**extra):
 r={'id':'FP01','line_id':'PD001-01','attempt':1,'qty':10,'counted':'2026-09-23T09:00:00','counter_id':'3','voided':False,'reason':'独立复核计数'}|extra;d['stocktake_recounts'].append(r);return r
def disposition(d,**extra):
 r={'id':'CZ01','line_id':'PD001-01','recount_id':None,'confirmed_qty':8,'recorded':'2026-09-23T10:00:00','owner_id':'1','status':'已确认','method':'核对领退料登记','evidence':'模拟核查记录，不调整库存'}|extra;d['stocktake_dispositions'].append(r);return r

class StocktakeLogicTests(SimpleTestCase):
 def setUp(self):self.data=fixture()
 def row(self):return eng.Stocktakes(self.data).rows[0]
 def test_count_does_not_change_ledger(self):
  before=copy.deepcopy(self.data);r=self.row();self.assertEqual(r['variance'],-2);self.assertEqual(r['book_qty'],10);self.assertEqual(self.data,before)
 def test_zero_count_is_real_loss(self):
  self.data['stocktake_lines'][0]['initial_qty']=0;self.assertEqual(self.row()['variance'],-10)
 def test_uncounted_is_not_zero(self):
  self.data['stocktake_lines'][0].update(initial_qty=None,counted=None,counter_id=None);r=self.row();self.assertIsNone(r['variance']);self.assertIn('uncounted',r['flags']);self.assertNotIn('unknown',r['flags'])
 def test_uncounted_inconsistent_time_blocks(self):
  self.data['stocktake_lines'][0]['initial_qty']=None;self.assertIn('unknown',self.row()['flags'])
 def test_missing_book_never_assumed_zero(self):
  self.data['inventory_opening']=[];r=self.row();self.assertIsNone(r['book_qty']);self.assertIsNone(r['variance'])
 def test_piece_fraction_and_negative_count_invalid(self):
  for qty in [2.5,-1,float('inf'),True]:
   self.data['stocktake_lines'][0]['initial_qty']=qty;self.assertIsNone(self.row()['variance'])
 def test_unit_mismatch_does_not_compare(self):
  self.data['stocktake_lines'][0]['unit']='kg';self.assertIsNone(self.row()['variance'])
 def test_duplicate_lot_location_plan_not_double_counted(self):
  self.data['stocktake_lines'].append(self.data['stocktake_lines'][0]|{'id':'PD001-02'});self.data['stocktake_runs'][0]['line_count']=2
  self.assertTrue(all(not r['eligible'] for r in eng.Stocktakes(self.data).rows))
 def test_unplanned_ledger_lots_visible(self):
  self.data['inventory_opening'].append(self.data['inventory_opening'][0]|{'id':'OPEN2','lot':'LOT2'});self.assertEqual(len(eng.Stocktakes(self.data).runs[0]['unplanned_lots']),1)
 def test_sample_does_not_claim_full_coverage(self):
  self.data['stocktake_runs'][0]['kind']='指定抽盘';self.data['inventory_opening'].append(self.data['inventory_opening'][0]|{'id':'OPEN2','lot':'LOT2'});self.assertEqual(eng.Stocktakes(self.data).runs[0]['unplanned_lots'],[])
 def test_header_count_or_freeze_inconsistency_blocks(self):
  for extra in [{'line_count':2},{'freeze_evidence':''},{'book_at':'2026-09-23T06:00:00'},{'kind':'未映射'},{'freeze_end':'2026-09-23T06:00:00'}]:
   self.data=fixture();self.data['stocktake_runs'][0].update(extra);self.assertFalse(self.row()['eligible'])
 def test_count_outside_freeze_or_future_blocks(self):
  for stamp in ['2026-09-23T06:00:00','2026-09-23T13:00:00','2026-10-03T08:00:00']:
   self.data['stocktake_lines'][0]['counted']=stamp;self.assertFalse(self.row()['eligible'])
 def test_historical_ledger_ignores_later_movement(self):
  self.data['inventory_movements']=[{'id':'MV1','material_id':'0001','lot':'LOT1','location':'CK01-A01','occurred':'2026-09-24T08:00:00','movement':'生产领料','qty_signed':-2,'work_order_id':'WO1','reference':'REF1'}]
  self.assertEqual(self.row()['book_qty'],10);self.assertEqual(self.row()['variance'],-2)
 def test_move_between_book_and_count_blocks(self):
  self.data['inventory_movements']=[{'id':'MV1','material_id':'0001','lot':'LOT1','location':'CK01-A01','occurred':'2026-09-23T07:30:00','movement':'生产领料','qty_signed':-2,'work_order_id':'WO1','reference':'REF1'}]
  r=self.row();self.assertIsNone(r['variance']);self.assertIn({'dataset':'inventory_movements','key':'MV1'},r['sources'])
 def test_recount_fix_preserves_first_difference(self):
  recount(self.data);r=self.row();self.assertEqual((r['initial_delta'],r['variance']),(-2,0));self.assertIn('resolved',r['flags'])
 def test_last_recount_wins_and_void_does_not(self):
  recount(self.data);recount(self.data,id='FP02',attempt=2,qty=9,counted='2026-09-23T09:30:00');recount(self.data,id='FP03',attempt=3,qty=7,counted='2026-09-23T10:00:00',voided=True);self.assertEqual(self.row()['variance'],-1)
 def test_future_recount_excluded(self):
  recount(self.data,counted='2026-10-03T08:00:00');self.assertEqual(self.row()['variance'],-2)
 def test_invalid_active_recount_does_not_fallback(self):
  for extra in [{'qty':-1},{'qty':2.5},{'counter_id':'2'},{'counter_id':'4'},{'counted':'2026-09-23T07:30:00'},{'reason':''}]:
   self.data=fixture();recount(self.data,**extra);self.assertIsNone(self.row()['variance'])
 def test_conflicting_attempts_not_arbitrarily_selected(self):
  recount(self.data);recount(self.data,id='FP02',qty=7);self.assertIsNone(self.row()['variance'])
 def test_attempt_time_order_must_match(self):
  recount(self.data,counted='2026-09-23T10:00:00');recount(self.data,id='FP02',attempt=2,counted='2026-09-23T09:00:00');self.assertIsNone(self.row()['variance'])
 def test_disposition_does_not_change_variance(self):
  disposition(self.data);r=self.row();self.assertEqual(r['variance'],-2);self.assertTrue(r['confirmed'])
 def test_stale_disposition_does_not_confirm_new_recount(self):
  disposition(self.data);recount(self.data);r=self.row();self.assertFalse(r['confirmed']);self.assertEqual(r['variance'],0);self.assertTrue(r['disposition_issues'])
 def test_disposition_exact_quantity_and_basis(self):
  recount(self.data);disposition(self.data,recount_id='FP01',confirmed_qty=10,status='复核无差异');self.assertTrue(self.row()['confirmed'])
 def test_disposition_claim_no_difference_when_loss_invalid(self):
  disposition(self.data,status='复核无差异');self.assertFalse(self.row()['confirmed']);self.assertEqual(self.row()['variance'],-2)
 def test_conflicting_dispositions_not_arbitrarily_confirmed(self):
  disposition(self.data);disposition(self.data,id='CZ02');self.assertFalse(self.row()['confirmed'])
 def test_orphans_reported(self):
  recount(self.data,line_id='missing');self.assertTrue(eng.Stocktakes(self.data).global_issues)
 def test_future_run_not_shown(self):
  self.data['stocktake_runs'][0]['book_at']='2026-10-03T07:00:00';self.assertEqual(eng.Stocktakes(self.data).rows,[])
 def test_quantities_split_by_run_and_unit(self):
  r=self.row();rows=[r,r|{'run_id':'PD002'},r|{'unit':'kg'}];s=eng.summary(rows);self.assertEqual(len(s['units']),3);self.assertTrue(all(x['loss']==2 for x in s['units']))

class StocktakeApiTests(PlatformCase):
 def setUp(self):
  super().setUp();self.data=fixture()
  for ds,rows in self.data.items():
   for r in rows:self.record(ds,r)
  self.client.force_login(self.admin)
 def board(self,query=''):
  r=self.client.get('/api/stocktake'+query);self.assertEqual(r.status_code,200,r.content);return r.json()
 def query(self,d=None):
  d=d or self.board();return views.filters({}),d['receipt']
 def detail_url(self,d=None):return '/api/stocktake/rows/PD001-01?receipt='+(d or self.board())['receipt']
 def test_read_only_and_financial_data_hidden(self):
  before=list(Record.objects.values());d=self.board();r=self.client.get(self.detail_url(d));self.assertEqual(r.status_code,200);self.assertNotIn('918273',r.content.decode());self.assertNotIn('cents',r.content.decode());self.assertEqual(list(Record.objects.values()),before)
 def test_auth_and_post_rejected(self):
  self.assertEqual(self.post('/api/stocktake',{}).status_code,405);self.client.logout();self.assertEqual(self.client.get('/api/stocktake').status_code,401)
 def test_existing_roles_can_read(self):
  for role in ['analyst','finance','operations','viewer']:
   u=User.objects.create_user(role,password='test-password');u.groups.add(Group.objects.create(name=role));self.client.force_login(u);self.board()
  self.client.force_login(self.quality);self.board()
 def test_conflicting_role_denied(self):
  self.admin.groups.add(Group.objects.get(name='quality'));self.assertEqual(self.client.get('/api/stocktake').status_code,401)
 def test_invalid_filters_and_pages_rejected(self):
  for query in ['?bogus=1','?run=missing','?unit=吨','?stage=missing','?page=0','?page=1.5','?q=a&q=b']:
   self.assertEqual(self.client.get('/api/stocktake'+query).status_code,400,query)
 def test_receipt_required_and_user_bound(self):
  d=self.board();self.assertEqual(self.client.get('/api/stocktake/rows/PD001-01').status_code,400);self.client.force_login(self.quality);self.assertEqual(self.client.get(self.detail_url(d)).status_code,409)
 def test_receipt_bound_to_filters(self):
  d=self.board();self.assertEqual(self.client.get(self.detail_url(d)+'&stage=variance').status_code,409)
 def test_changed_data_requires_new_receipt(self):
  d=self.board();self.record('stocktake_dispositions',{'id':'ORPHAN','line_id':'missing','recorded':'2026-09-23T10:00:00'});self.assertEqual(self.client.get(self.detail_url(d)).status_code,409)
 def test_object_outside_current_filters_hidden(self):
  d=self.board('?q=other');url=self.detail_url(d)+'&q=other';self.assertEqual(self.client.get(url).status_code,404)
 def test_evidence_contains_original_row_provenance(self):
  d=self.board();r=self.client.get('/api/stocktake/rows/PD001-01/evidence?receipt='+d['receipt']);self.assertEqual(r.status_code,200);rows=r.json()['rows'];self.assertTrue(all(x['filename']=='unit-test.xlsx' and x['row']==2 for x in rows));self.assertEqual(len(rows),4)
 def test_filtered_csv_and_one_audit(self):
  d=self.board('?stage=variance');r=self.client.get('/api/stocktake/export?stage=variance&receipt='+d['receipt']);self.assertEqual(r.status_code,200);rows=list(csv.reader(io.StringIO(r.content.decode('utf-8-sig'))));self.assertEqual(rows[5][0],'PD001');self.assertEqual(len(rows),6);self.assertEqual(AuditEvent.objects.filter(action='stocktake.export').count(),1)
 def test_stale_export_has_no_audit(self):
  r=self.client.get('/api/stocktake/export?receipt=bad');self.assertEqual(r.status_code,409);self.assertEqual(AuditEvent.objects.filter(action='stocktake.export').count(),0)
