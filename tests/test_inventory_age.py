import copy,csv,io
from django.test import SimpleTestCase
from django.contrib.auth.models import User,Group
from app import inventory_age as eng,inventory_age_views as views,supply
from app.schema import SCHEMAS
from app.models import Record,AuditEvent
from .test_platform import PlatformCase

def fixture():
 d={k:[] for k in SCHEMAS}
 d['materials']=[{'id':'0001','name':'漆料','unit':'kg','category':'漆料','safety_qty':2,'spec':'模拟'}]
 d['employees']=[{'id':'1','name':'模拟登记人'}]
 d['inventory_opening']=[{'id':'OPEN1','material_id':'0001','lot':'LOT1','location':'CK01-A01','as_of':'2026-09-01','qty':10,'unit_cost_cents':918273,'status':'可用'}]
 d['inventory_lot_dates']=[{'id':'DATE1','material_id':'0001','lot':'LOT1','version':1,'supersedes_id':None,'registered':'2026-09-26T09:00:00','manufactured':'2026-07-01','first_stock_date':'2026-08-01','expires':'2026-10-10','expiry_mode':'固定日期','document_no':'模拟依据001','owner_id':'1','voided':False,'note':'合成日期'}]
 d['inventory_age_policies']=[{'id':'RULE1','material_id':'0001','version':1,'supersedes_id':None,'effective_from':'2026-09-01','registered':'2026-09-25T09:00:00','age_limit_days':60,'warning_days':14,'expiry_required':True,'owner_id':'1','status':'模拟确认','reason':'合成规则，非正式制度'}]
 return d
def second(d,ds='inventory_lot_dates',**extra):
 r=d[ds][0]|{'id':'DATE2' if ds=='inventory_lot_dates' else 'RULE2','version':2,'supersedes_id':d[ds][0]['id'],'registered':'2026-09-28T09:00:00'}|extra;d[ds].append(r);return r

class InventoryAgeLogicTests(SimpleTestCase):
 def setUp(self):self.data=fixture()
 def row(self,order='fifo'):return eng.InventoryAge(self.data,order=order).rows[0]
 def test_age_and_expiry_are_separate(self):
  r=self.row();self.assertEqual((r['age_days'],r['expiry_days'],r['expiry_state']),(61,9,'临期'));self.assertTrue(r['overage'])
 def test_read_does_not_change_stock_or_source(self):
  before=copy.deepcopy(self.data);stock=supply.SupplyData(self.data).lots;self.row();self.assertEqual(self.data,before);self.assertEqual(supply.SupplyData(self.data).lots,stock)
 def test_missing_date_never_uses_opening_date(self):
  self.data['inventory_lot_dates']=[];r=self.row();self.assertIsNone(r['age_days']);self.assertEqual(r['observed_from'],'2026-09-01');self.assertFalse(r['rank_eligible']);self.assertEqual(r['balance_qty'],10)
 def test_missing_first_age_unknown_expiry_remains_known(self):
  self.data['inventory_lot_dates'][0]['first_stock_date']=None;r=self.row();self.assertIsNone(r['age_days']);self.assertEqual(r['expiry_state'],'临期')
 def test_unknown_expiry_keeps_age(self):
  self.data['inventory_lot_dates'][0].update(expires=None,expiry_mode='待核实');r=self.row();self.assertEqual(r['age_days'],61);self.assertEqual(r['expiry_state'],'未知')
 def test_not_applicable_when_rule_allows(self):
  self.data['inventory_lot_dates'][0].update(expires=None,expiry_mode='不适用');self.data['inventory_age_policies'][0]['expiry_required']=False;self.assertEqual(self.row()['expiry_state'],'不适用');self.assertTrue(self.row()['rank_eligible'])
 def test_rule_requires_expiry_contradiction(self):
  self.data['inventory_lot_dates'][0].update(expires=None,expiry_mode='不适用');self.assertTrue(self.row()['date_issues']);self.assertFalse(self.row()['rank_eligible'])
 def test_expiry_day_valid_next_day_expired(self):
  self.data['inventory_lot_dates'][0]['expires']='2026-10-01';self.assertEqual(self.row()['expiry_state'],'临期');self.data['inventory_lot_dates'][0]['expires']='2026-09-30';r=self.row();self.assertEqual(r['expiry_state'],'过期');self.assertFalse(r['rank_eligible']);self.assertEqual(r['usable_state_qty'],10)
 def test_age_threshold_equality_not_overage(self):
  self.data['inventory_age_policies'][0]['age_limit_days']=61;self.assertFalse(self.row()['overage'])
 def test_warning_threshold_equality_included(self):
  self.data['inventory_lot_dates'][0]['expires']='2026-10-15';self.assertEqual(self.row()['expiry_state'],'临期');self.data['inventory_lot_dates'][0]['expires']='2026-10-16';self.assertEqual(self.row()['expiry_state'],'有效')
 def test_no_policy_does_not_invent_thresholds(self):
  self.data['inventory_age_policies']=[];r=self.row();self.assertEqual(r['age_days'],61);self.assertEqual(r['expiry_state'],'有效');self.assertFalse(r['overage']);self.assertFalse(r['rank_eligible'])
 def test_invalid_or_unconfirmed_rules_not_used(self):
  for extra in [{'status':'作废'},{'age_limit_days':0},{'warning_days':-1},{'reason':''},{'owner_id':'missing'}]:
   self.data=fixture();self.data['inventory_age_policies'][0].update(extra);self.assertTrue(self.row()['policy_issues']);self.assertFalse(self.row()['rank_eligible'])
 def test_future_draft_and_void_preserve_current(self):
  for ds,extra in [('inventory_lot_dates',{'registered':'2026-10-02T09:00:00'}),('inventory_lot_dates',{'voided':True}),('inventory_age_policies',{'status':'草稿'}),('inventory_age_policies',{'effective_from':'2026-10-02'})]:
   self.data=fixture();second(self.data,ds,**extra);r=self.row();self.assertEqual(r['date_profile_id'],'DATE1');self.assertEqual(r['policy_id'],'RULE1')
 def test_correction_keeps_history(self):
  second(self.data,first_stock_date='2026-08-08');r=self.row();self.assertEqual(r['age_days'],54);self.assertEqual(len(r['date_history']),2);self.assertEqual(self.data['inventory_lot_dates'][0]['first_stock_date'],'2026-08-01')
 def test_bad_date_chain_blocks_no_fallback(self):
  for extra in [{'supersedes_id':'missing'},{'version':3},{'lot':'LOT2'},{'registered':'2026-09-24T09:00:00'}]:
   self.data=fixture();second(self.data,**extra)
   if extra.get('lot'):self.data['inventory_lot_dates'][0]['lot']='LOT2'
   self.assertTrue(self.row()['date_issues']);self.assertIsNone(self.row()['age_days'])
 def test_duplicate_predecessor_version_blocks(self):
  self.data['inventory_lot_dates'].append(self.data['inventory_lot_dates'][0]|{'id':'DUP'});second(self.data);self.assertTrue(self.row()['date_issues'])
 def test_same_current_version_conflict_blocks(self):
  second(self.data);second(self.data,id='DATE3');self.assertIsNone(self.row()['age_days'])
 def test_late_lower_version_blocks(self):
  second(self.data);self.data['inventory_lot_dates'][0]['registered']='2026-09-29T09:00:00';self.assertIsNone(self.row()['age_days'])
 def test_effective_rule_dates_monotonic(self):
  self.data['inventory_age_policies'][0]['effective_from']='2026-09-27';second(self.data,'inventory_age_policies',effective_from='2026-09-20');self.assertTrue(self.row()['policy_issues'])
 def test_date_contradictions_block(self):
  for extra in [{'manufactured':'2026-08-02'},{'first_stock_date':'2026-09-02'},{'first_stock_date':'2026-10-02'},{'expires':'2026-06-30'},{'expiry_mode':'未映射'},{'document_no':''},{'owner_id':'missing'}]:
   self.data=fixture();self.data['inventory_lot_dates'][0].update(extra);self.assertTrue(self.row()['date_issues']);self.assertFalse(self.row()['rank_eligible'])
 def test_zero_and_negative_ledger_not_risk_amount(self):
  self.data['inventory_opening'][0]['qty']=0;self.assertEqual(eng.summary([self.row()])['positive'],0);self.assertFalse(self.row()['overage']);self.data['inventory_opening'][0]['qty']=-1;self.assertFalse(self.row()['quantity_valid']);self.assertIsNone(eng.summary([self.row()])['units'][0]['known_balance'])
 def test_restricted_state_does_not_rank(self):
  self.data['inventory_opening'][0]['status']='冻结';self.assertFalse(self.row()['rank_eligible']);self.assertEqual(self.row()['balance_qty'],10)
 def test_same_batch_two_locations_date_reused_quantity_not_duplicated(self):
  self.data['inventory_opening'].append(self.data['inventory_opening'][0]|{'id':'OPEN2','location':'CK01-A02','qty':7});rs=eng.InventoryAge(self.data).rows;self.assertEqual(len(rs),2);self.assertEqual([r['date_profile_id'] for r in rs],['DATE1','DATE1']);self.assertEqual(eng.summary(rs)['units'][0]['known_balance'],17)
 def test_fifo_fefo_orders_differ_and_filter_does_not_renumber(self):
  self.data['inventory_opening'].append(self.data['inventory_opening'][0]|{'id':'OPEN2','lot':'LOT2'});self.data['inventory_lot_dates'].append(self.data['inventory_lot_dates'][0]|{'id':'DATE3','lot':'LOT2','first_stock_date':'2026-08-10','expires':'2026-10-05'});
  fifo=eng.InventoryAge(self.data);fefo=eng.InventoryAge(self.data,order='fefo');self.assertEqual(fifo.rows[0]['lot'],'LOT1');self.assertEqual(fefo.rows[0]['lot'],'LOT2');f=views.filters({'q':'LOT1','order':'fefo'});self.assertEqual(fefo.selected(f)[0]['reference_rank'],2)
 def test_unit_partition_reconciles_known_positive(self):
  r=self.row();s=eng.summary([r,r|{'unit':'件'},r|{'age_bucket':'日期未知','expiry_state':'未知'}]);self.assertEqual(len(s['units']),2)
  for u in s['units']:self.assertEqual(sum(b['qty'] for b in u['buckets']),u['known_balance']);self.assertEqual(sum(b['qty'] for b in u['expiry']),u['known_balance'])
 def test_orphan_date_visible_not_stock(self):
  self.data['inventory_lot_dates'].append(self.data['inventory_lot_dates'][0]|{'id':'ORPHAN','lot':'MISSING'});d=eng.InventoryAge(self.data);self.assertEqual(len(d.rows),1);self.assertTrue(d.global_issues)
 def test_source_contains_versions_and_no_money(self):
  second(self.data);r=self.row();self.assertIn({'dataset':'inventory_lot_dates','key':'DATE1'},r['sources']);self.assertNotIn('cents',str(r));self.assertNotIn('918273',str(r))

class InventoryAgeApiTests(PlatformCase):
 def setUp(self):
  super().setUp();self.data=fixture()
  for ds,rows in self.data.items():
   for r in rows:self.record(ds,r)
  self.client.force_login(self.admin)
 def board(self,q=''):
  r=self.client.get('/api/inventory-age'+q);self.assertEqual(r.status_code,200,r.content);return r.json()
 def detail_url(self,d=None):return '/api/inventory-age/rows/'+self.board()['rows'][0]['id']+'?receipt='+(d or self.board())['receipt']
 def test_read_only_finance_hidden(self):
  before=list(Record.objects.values());r=self.client.get(self.detail_url());self.assertEqual(r.status_code,200);self.assertNotIn('cents',r.content.decode());self.assertEqual(before,list(Record.objects.values()))
 def test_auth_post_denied(self):
  self.assertEqual(self.post('/api/inventory-age',{}).status_code,405);self.client.logout();self.assertEqual(self.client.get('/api/inventory-age').status_code,401)
 def test_roles_read_and_conflicting_role_denied(self):
  for role in ['analyst','finance','operations','viewer']:
   u=User.objects.create_user(role,password='test-password');u.groups.add(Group.objects.create(name=role));self.client.force_login(u);self.board()
  self.client.force_login(self.quality);self.board();self.client.force_login(self.admin);self.admin.groups.add(Group.objects.get(name='quality'));self.assertEqual(self.client.get('/api/inventory-age').status_code,401)
 def test_invalid_filters(self):
  for q in ['?bogus=1','?material_id=missing','?category=未知','?unit=吨','?stage=missing','?order=bad','?page=0','?page=1.5','?q=a&q=b']:
   self.assertEqual(self.client.get('/api/inventory-age'+q).status_code,400,q)
 def test_receipt_required_and_role_bound(self):
  d=self.board();url=self.detail_url(d);self.assertEqual(self.client.get(url.split('?')[0]).status_code,400);self.client.force_login(self.quality);self.assertEqual(self.client.get(url).status_code,409)
 def test_receipt_scope_and_order_bound(self):
  for q in ['&stage=near','&order=fefo','&unit=kg']:
   self.assertEqual(self.client.get(self.detail_url()+q).status_code,409)
 def test_data_revision_invalidates(self):
  url=self.detail_url();self.record('inventory_lot_dates',self.data['inventory_lot_dates'][0]|{'id':'ORPHAN','lot':'missing'});self.assertEqual(self.client.get(url).status_code,409)
 def test_scope_outside_and_empty_no_leak(self):
  d=self.board('?q=other');self.assertEqual(d['total'],0);self.assertEqual(self.client.get(self.detail_url(d)+'&q=other').status_code,404)
 def test_evidence_actual_row_provenance(self):
  d=self.board();url=self.detail_url(d).replace('?','/evidence?');r=self.client.get(url);self.assertEqual(r.status_code,200);rows=r.json()['rows'];self.assertEqual(len(rows),4);self.assertTrue(all(r['filename']=='unit-test.xlsx' and r['row']==2 for r in rows))
 def test_csv_same_scope_and_one_audit(self):
  d=self.board('?stage=near');r=self.client.get('/api/inventory-age/export?stage=near&receipt='+d['receipt']);self.assertEqual(r.status_code,200);rows=list(csv.reader(io.StringIO(r.content.decode('utf-8-sig'))));self.assertEqual(rows[5][0],'0001');self.assertEqual(len(rows),6);self.assertEqual(AuditEvent.objects.filter(action='inventory_age.export').count(),1)
 def test_stale_export_no_audit(self):
  self.assertEqual(self.client.get('/api/inventory-age/export?receipt=bad').status_code,409);self.assertEqual(AuditEvent.objects.filter(action='inventory_age.export').count(),0)
