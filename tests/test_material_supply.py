import copy,csv,io
from unittest.mock import patch
from django.test import SimpleTestCase
from django.contrib.auth.models import User,Group
from app import material_planning as mp,material_supply as flow,analytics,supply
from app.models import Record,AuditEvent
from .test_platform import PlatformCase
from .test_material_planning import fixture


def supply_fixture():
 d=fixture()
 d['purchase_lines']=[{'id':'PO1','material_id':'M2','supplier_id':'S1','ordered':'2026-09-01','due':'2026-09-25','qty':20,'status':'部分到货','unit_price_cents':91827}]
 d['receipts']=[{'id':i,'purchase_line_id':'PO1','material_id':'M2','lot':i,'qty':q,'received':'2026-09-24T08:00:00','certificate':'C','status':status} for i,q,status in [('R1',8,'检验合格'),('R2',5,'待检'),('R3',2,'隔离')]]
 d['incoming_inspections']=[{'id':'Q1','receipt_id':'R1','sample_size':1,'defect_count':0,'inspected':'2026-09-24T09:00:00','result':'合格','disposition':'批准入库','inspector_id':'E1'}, {'id':'Q3','receipt_id':'R3','sample_size':1,'defect_count':1,'inspected':'2026-09-24T09:00:00','result':'不合格','disposition':'隔离待退货','inspector_id':'E1'}]
 d['inventory_movements']=[{'id':'IN1','material_id':'M2','lot':'R1','location':'B1','occurred':'2026-09-24T10:00:00','qty_signed':3,'movement':'采购入库','work_order_id':'','reference':'R1','value_cents':88281}]
 return d

class SupplyProgressCalculationTests(SimpleTestCase):
 def setUp(self):self.data=supply_fixture()
 def build(self,key='M2',**scope):
  self.plan=mp.MaterialPlanning(self.data,mp.filters({'stock_policy':'all_usable',**scope}));return flow.build(self.plan,key)
 def test_disjoint_stages_reconcile_partial_and_split_arrivals(self):
  s=self.build()['summary'];self.assertEqual([s[k] for k in flow.STAGES],[5,7,5,3]);self.assertEqual(sum(s[k] for k in flow.STAGES),s['ordered']);self.assertEqual(s['overdue_unreceived'],5)
 def test_no_inventory_credit_and_inputs_unchanged(self):
  before=copy.deepcopy(self.data);out=self.build();self.assertEqual(out['material']['initial_pool'],8);self.assertEqual(self.data,before);self.assertEqual(self.plan.pool['M2'],3)
 def test_scope_filters_demand_only(self):
  a=self.build();b=self.build(work_order='W2');self.assertEqual(a['summary'],b['summary']);self.assertNotEqual(a['material']['net_demand'],b['material']['net_demand']);self.assertEqual(b['demand_start_range'],{'first':'2026-09-21','last':'2026-09-21'})
 def test_absent_material_from_demand_rejected(self):
  with self.assertRaises(Record.DoesNotExist):self.build(work_order='W3')
 def test_today_not_overdue_future_grouped(self):
  self.data['purchase_lines'][0]['due']='2026-10-01';d=self.build();self.assertEqual(d['summary']['overdue_unreceived'],0);self.assertFalse(d['promises'][0]['overdue'])
 def test_cancelled_empty_po_excluded(self):
  self.data['purchase_lines'].append({**self.data['purchase_lines'][0],'id':'PO2','qty':100,'status':'已取消'});d=self.build();self.assertEqual(d['summary']['cancelled_lines'],1);self.assertEqual(d['summary']['ordered'],20);self.assertIsNone(d['purchases'][-1]['unreceived'])
 def test_cancelled_with_receipt_is_attention(self):
  self.data['purchase_lines'][0]['status']='已取消';s=self.build()['summary'];self.assertEqual(s['attention_lines'],1);self.assertEqual(s['ordered'],0);self.assertEqual(s['cancelled_lines'],0)
 def test_oversupply_not_clamped_into_valid_total(self):
  self.data['purchase_lines'][0]['qty']=10;d=self.build();self.assertEqual(d['summary']['valid_lines'],0);self.assertIsNone(d['purchases'][0]['unreceived'])
 def test_fractional_piece_amount_invalid(self):
  for target,field in [('purchase_lines','qty'),('receipts','qty'),('inventory_movements','qty_signed')]:
   self.data=supply_fixture();self.data[target][0][field]+=.5;self.assertEqual(self.build()['summary']['attention_lines'],1)
 def test_unmapped_and_contradictory_statuses(self):
  for status in ['奇怪状态','已到货','未到货']:
   self.data=supply_fixture();self.data['purchase_lines'][0]['status']=status;self.assertEqual(self.build()['summary']['attention_lines'],1)
 def test_approved_without_inspection_not_credited(self):
  self.data['incoming_inspections']=[];d=self.build();self.assertEqual(d['summary']['valid_lines'],0)
 def test_putaway_before_quality_not_credited(self):
  self.data['inventory_movements'][0]['occurred']='2026-09-24T08:30:00';self.assertEqual(self.build()['summary']['valid_lines'],0)
 def test_conflicting_simultaneous_inspection_not_arbitrarily_chosen(self):
  self.data['incoming_inspections'].append({**self.data['incoming_inspections'][0],'id':'Q0','result':'不合格','disposition':'隔离'});d=self.build();self.assertEqual(d['summary']['valid_lines'],0);self.assertIn('同一时刻',str(d['purchases'][0]['issues']))
 def test_missing_supplier_or_unit_blocks(self):
  self.data['suppliers']=[];self.assertEqual(self.build()['summary']['valid_lines'],0);self.data=supply_fixture();self.data['materials'][1]['unit']='';self.assertEqual(self.build()['summary']['valid_lines'],0)
 def test_wrong_material_receipt_does_not_become_available(self):
  self.data['receipts'][0]['material_id']='M1';self.assertEqual(self.build()['summary']['valid_lines'],0)
 def test_orphan_receipt_visible_with_sources_not_added(self):
  self.data['receipts'].append({**self.data['receipts'][1],'id':'ORPHAN','purchase_line_id':'MISSING'});d=self.build();self.assertEqual(d['summary']['ordered'],20);self.assertEqual(d['unmatched_receipts'][0]['id'],'ORPHAN');self.assertIn({'dataset':'receipts','key':'ORPHAN'},d['sources'])
 def test_future_po_and_receipts_excluded_at_business_cutoff(self):
  self.data['purchase_lines'].append({**self.data['purchase_lines'][0],'id':'FUTURE','ordered':'2026-10-02','due':'2026-10-03','status':'未到货'});self.data['receipts'].append({**self.data['receipts'][1],'id':'FUTURE','received':'2026-10-02T08:00:00'});self.assertEqual(self.build()['summary']['ordered'],20)
 def test_sources_include_demand_and_procurement_without_duplication(self):
  d=self.build();refs={(r['dataset'],r['key']) for r in d['sources']};self.assertEqual(len(refs),len(d['sources']))
  for r in [('purchase_lines','PO1'),('receipts','R3'),('incoming_inspections','Q1'),('inventory_movements','IN1'),('bom','B2'),('work_orders','W2')]:self.assertIn(r,refs)
 def test_empty_procurement_is_observed_empty_not_guessed_order(self):
  d=self.build('M1');self.assertEqual(d['purchases'],[]);self.assertEqual(d['summary']['ordered'],0)
 def test_valid_and_invalid_po_subtotals_not_mixed(self):
  self.data['purchase_lines'].append({**self.data['purchase_lines'][0],'id':'BAD','status':'已到货','qty':100});d=self.build();self.assertEqual(d['summary']['ordered'],20);self.assertEqual((d['summary']['valid_lines'],d['summary']['attention_lines']),(1,1))

class SupplyProgressAPITests(PlatformCase):
 def setUp(self):
  super().setUp();self.data=supply_fixture()
  for ds,rows in self.data.items():
   for r in rows:self.record(ds,r)
  analytics._tables.cache_clear();supply.cached.cache_clear();self.addCleanup(analytics._tables.cache_clear);self.addCleanup(supply.cached.cache_clear);self.client.force_login(self.admin)
 def prep_receipt(self):return self.client.get('/api/material-planning?stock_policy=all_usable').json()['receipt']
 def url(self,key='M2',path='',receipt=None,flow_receipt=None):return '/api/material-supply/'+key+path+'?stock_policy=all_usable&receipt='+(receipt or self.prep_receipt())+('&flow_receipt='+flow_receipt if flow_receipt else '')
 def board(self):
  r=self.client.get(self.url());self.assertEqual(r.status_code,200,r.content);return r.json()
 def test_read_only_and_no_prices_exposed(self):
  before=list(Record.objects.values());d=self.board();self.assertEqual(d['summary']['held'],7);self.assertEqual(list(Record.objects.values()),before);self.assertNotIn('cents',str(d));self.assertNotIn('91827',str(d))
 def test_authentication_and_read_only_methods(self):
  url=self.url();self.assertEqual(self.post(url,{}).status_code,405);self.client.logout();self.assertEqual(self.client.get(url).status_code,401)
 def test_existing_roles_can_inspect_without_financial_leak(self):
  users=[self.admin,self.quality]
  for role in ['analyst','finance','operations','viewer']:
   u=User.objects.create_user(role,password='test-password');u.groups.add(Group.objects.create(name=role));users.append(u)
  for u in users:
   self.client.force_login(u);r=self.client.get(self.url());self.assertEqual(r.status_code,200);self.assertNotIn('cents',r.content.decode())
 def test_parent_receipt_and_scope_protected(self):
  receipt=self.prep_receipt();self.assertEqual(self.client.get('/api/material-supply/M2').status_code,400);self.assertEqual(self.client.get(self.url(receipt=receipt)+'&work_order=W1').status_code,409)
 def test_flow_required_for_export_and_bound_to_material(self):
  d=self.board();self.assertEqual(self.client.get(self.url(path='/export')).status_code,400);self.assertEqual(self.client.get(self.url(key='M1',path='/export',flow_receipt=d['flow_receipt'])).status_code,409)
 def test_user_bound_flow_rejects_reuse(self):
  d=self.board();self.client.force_login(self.quality);self.assertEqual(self.client.get(self.url(path='/export',flow_receipt=d['flow_receipt'])).status_code,409)
 def test_data_and_code_drift_rejects_old_receipt(self):
  d=self.board();r=Record.objects.get(dataset='purchase_lines',business_key='PO1');r.values['qty']=21;r.revision+=1;r.save();self.assertEqual(self.client.get(self.url(receipt=d['receipt'],flow_receipt=d['flow_receipt'])).status_code,409)
  fresh=self.board()
  with patch('app.material_supply_views.eng.digest',return_value='changed'):self.assertEqual(self.client.get(self.url(path='/export',flow_receipt=fresh['flow_receipt'])).status_code,409)
 def test_invalid_duplicate_unknown_query_rejected(self):
  for extra in ['&receipt=x','&stock_policy=all_usable','&bogus=x']:
   self.assertEqual(self.client.get(self.url()+extra).status_code,400)
 def test_current_material_and_missing_material(self):
  self.assertEqual(self.client.get(self.url(key='MISSING')).status_code,404)
 def test_csv_matches_stages_and_appends_audit_only(self):
  d=self.board();before=list(Record.objects.values());r=self.client.get(self.url(path='/export',flow_receipt=d['flow_receipt']));self.assertEqual(r.status_code,200,r.content);rows=list(csv.reader(io.StringIO(r.content.decode('utf-8-sig'))));self.assertEqual(rows[4][7:11],['5','7','5','3']);self.assertEqual(list(Record.objects.values()),before);self.assertEqual(AuditEvent.objects.filter(action='material_supply.export').count(),1);self.assertEqual(r['Cache-Control'],'no-store')
 def test_source_rows_include_original_sheet_and_line(self):
  d=self.board();r=self.client.get(self.url(path='/evidence',flow_receipt=d['flow_receipt']));self.assertEqual(r.status_code,200,r.content);rows=r.json()['rows'];self.assertTrue(any(r['dataset']=='receipts' and r['sheet']=='receipts' and r['row']==2 for r in rows));self.assertNotIn('cents',r.content.decode())
 def test_csv_formula_protection(self):
  r=Record.objects.get(dataset='suppliers',business_key='S1');r.values['name']='=1+1';r.save();d=self.board();r=self.client.get(self.url(path='/export',flow_receipt=d['flow_receipt']));self.assertIn("'=1+1",r.content.decode('utf-8-sig'))
