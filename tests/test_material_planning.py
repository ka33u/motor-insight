import copy,csv,io,json
from unittest.mock import patch
from decimal import Decimal
from django.test import SimpleTestCase,Client
from django.contrib.auth.models import User,Group
from app import material_planning as mp,analytics,supply
from app.schema import SCHEMAS
from app.models import Record,IssueDisposition,AuditEvent
from .test_platform import PlatformCase

def fixture():
 d={k:[] for k in SCHEMAS};d['suppliers']=[{'id':'S1','name':'模拟供应商'}];d['employees']=[{'id':'E1'}]
 d['materials']=[{'id':'M1','name':'铜线','spec':'A','category':'铜线','unit':'kg','safety_qty':2,'unit_cost_cents':12345,'supplier_id':'S1'},{'id':'M2','name':'轴承','spec':'A','category':'轴承','unit':'件','safety_qty':1,'unit_cost_cents':54321,'supplier_id':'S1'}]
 d['products']=[{'id':'P1','family':'A','model':'模拟A','bom_version':'A'},{'id':'P2','family':'B','model':'模拟B','bom_version':'A'}]
 d['bom']=[{'id':'B1','product_id':'P1','material_id':'M1','version':'A','qty':1,'scrap_allowance':0,'effective':'2026-09-01','assembly_level':'定子'},{'id':'B2','product_id':'P1','material_id':'M2','version':'A','qty':1,'scrap_allowance':0.25,'effective':'2026-09-01','assembly_level':'装配件包'},{'id':'B3','product_id':'P2','material_id':'M1','version':'A','qty':1,'scrap_allowance':0,'effective':'2026-09-01','assembly_level':'定子'}]
 d['work_orders']=[{'id':k,'product_id':p,'planned_qty':qty,'planned_start':start,'planned_end':'2026-10-10','priority':'普通','status':'未开工','bom_version':'A','route_version':'R'} for k,p,qty,start in [('W1','P1',4,'2026-09-20'),('W2','P1',3,'2026-09-21'),('W3','P2',2,'2026-09-22')]]
 d['inventory_opening']=[{'id':'O1','material_id':'M1','lot':'L1','location':'A1','as_of':'2026-09-01','qty':10,'status':'可用','unit_cost_cents':12345},{'id':'O2','material_id':'M2','lot':'L2','location':'A2','as_of':'2026-09-01','qty':5,'status':'可用','unit_cost_cents':54321}]
 return d

def issue(mid='M1',qty=-2,key='I1',wo='W1',stamp='2026-09-20T08:00:00'):
 return {'id':key,'material_id':mid,'lot':'L1' if mid=='M1' else 'L2','location':'A1' if mid=='M1' else 'A2','occurred':stamp,'qty_signed':qty,'movement':'生产领料','work_order_id':wo,'reference':wo}

class PlanningCalculationTests(SimpleTestCase):
 def setUp(self):self.d=fixture()
 def calc(self,**f):return mp.MaterialPlanning(self.d,mp.filters({'stock_policy':'all_usable',**f}))
 def test_shared_pool_not_counted_for_every_order(self):
  d=self.calc();self.assertEqual([w['state'] for w in d.ordered],['covered','short','covered']);self.assertEqual(d.pool['M1'],4);self.assertEqual(d.pool['M2'],0)
 def test_short_order_uses_nothing_and_later_order_can_fit(self):
  d=self.calc();self.assertEqual([i['simulated_allocated'] for i in d.orders['W2']['items']],[0,0]);self.assertEqual(d.orders['W3']['state'],'covered')
 def test_piece_rounding_after_same_material_branches_merge(self):
  self.d['work_orders'][0]['planned_qty']=3;self.d['bom'][1]['scrap_allowance']=0.1;self.d['bom'].append({**self.d['bom'][1],'id':'B4','assembly_level':'转子'})
  item=next(x for x in self.calc().orders['W1']['items'] if x['material_id']=='M2');self.assertEqual(item['gross_unrounded'],Decimal('6.6'));self.assertEqual(item['gross_required'],7)
 def test_actual_issues_only_subtracted_once(self):
  self.d['inventory_movements']=[issue()];d=self.calc();item=d.orders['W1']['items'][0];self.assertEqual((item['gross_required'],item['issued_qty'],item['remaining_required']),(4,2,2));self.assertEqual(d.material_rows['M1']['initial_pool'],8);self.assertEqual(d.pool['M1'],4)
 def test_assembly_count_not_used_as_imagined_material_credit(self):
  self.d['work_orders'][0]['status']='生产中';self.d['units']=[{'id':'U1','work_order_id':'W1','product_id':'P1','assembly_at':'2026-09-21T08:00:00'}];d=self.calc();self.assertEqual(d.orders['W1']['items'][0]['remaining_required'],4)
 def test_excess_issues_do_not_return_stock_to_pool(self):
  self.d['inventory_movements']=[issue(qty=-5)];d=self.calc();item=d.orders['W1']['items'][0];self.assertEqual(item['remaining_required'],0);self.assertTrue(item['warnings']);self.assertEqual(d.material_rows['M1']['initial_pool'],5)
 def test_missing_inventory_is_unknown_not_zero(self):
  self.d['inventory_opening'].pop();d=self.calc();self.assertIsNone(d.material_rows['M2']['initial_pool']);self.assertEqual(d.orders['W1']['state'],'attention');self.assertEqual(d.orders['W3']['state'],'covered');self.assertIsNone(d.material_rows['M2']['known_gap'])
 def test_frozen_and_pending_stock_excluded(self):
  for state in ['冻结','待检','隔离']:
   with self.subTest(state=state):self.d=fixture();self.d['inventory_opening'][1]['status']=state;d=self.calc();self.assertEqual(d.material_rows['M2']['initial_pool'],0);self.assertEqual(d.orders['W1']['state'],'short')
 def test_in_transit_and_approved_unposted_not_available(self):
  self.d['purchase_lines']=[{'id':'PO','material_id':'M2','supplier_id':'S1','ordered':'2026-09-01','due':'2026-09-15','qty':100,'status':'部分到货'}];self.d['receipts']=[{'id':'R','purchase_line_id':'PO','material_id':'M2','lot':'NEW','qty':50,'received':'2026-09-15T08:00:00','certificate':'X','status':'检验合格'}];self.d['incoming_inspections']=[{'id':'Q','receipt_id':'R','sample_size':1,'defect_count':0,'inspected':'2026-09-15T09:00:00','result':'合格','disposition':'批准入库','inspector_id':'E1'}]
  d=self.calc();self.assertEqual(d.material_rows['M2']['initial_pool'],5);self.assertEqual(d.material_rows['M2']['open_purchase_qty'],50)
 def test_safety_policy_changes_queue_not_inventory(self):
  before=copy.deepcopy(self.d);a=self.calc(stock_policy='protect_safety');b=self.calc();self.assertEqual(a.orders['W1']['state'],'short');self.assertEqual(a.orders['W2']['state'],'covered');self.assertEqual(b.orders['W1']['state'],'covered');self.assertEqual(self.d,before)
 def test_priority_order_can_change_who_is_covered(self):
  self.d['work_orders'][1]['priority']='紧急';a=self.calc(order='start');b=self.calc(order='priority');self.assertEqual(a.orders['W1']['state'],'covered');self.assertEqual(b.orders['W1']['state'],'short');self.assertEqual(b.ordered[0]['id'],'W2')
 def test_filter_rebuilds_selected_competition_and_never_falls_back(self):
  self.assertEqual(self.calc(work_order='W2').orders['W2']['state'],'covered');self.assertEqual(self.calc(work_order='NONE').summary()['orders'],0);self.assertEqual(self.calc(family='NONE').material_rows,{})
 def test_stage_and_tab_do_not_change_allocations(self):
  before=self.calc();after=self.calc(tab='materials',stage='short');self.assertEqual(before.pool,after.pool);self.assertEqual([w['state'] for w in before.ordered],[w['state'] for w in after.ordered])
 def test_dates_select_work_orders_not_stock_history(self):
  d=self.calc(**{'from':'2026-09-21','to':'2026-09-21'});self.assertEqual(set(d.orders),{'W2'});self.assertEqual(d.material_rows['M2']['initial_pool'],5)
 def test_declared_bom_version_not_current_product_fallback(self):
  self.d['products'][0]['bom_version']='B';d=self.calc();self.assertEqual(d.orders['W1']['state'],'covered');self.assertTrue(d.orders['W1']['warnings']);self.d['work_orders'][0]['bom_version']='NONE';d=self.calc();self.assertEqual(d.orders['W1']['state'],'attention');self.assertFalse(d.orders['W1']['items'])
 def test_bom_future_at_cutoff_or_after_start_blocks_complete_demand(self):
  for effective in ['2026-09-21','2026-10-03']:
   self.d=fixture();self.d['bom'][0]['effective']=effective;d=self.calc();self.assertEqual(d.orders['W1']['state'],'attention');self.assertEqual(d.material_rows['M1']['net_demand'],5 if effective=='2026-09-21' else 2)
 def test_duplicate_same_material_branch_blocks_not_double_counted(self):
  self.d['bom'].append({**self.d['bom'][0],'id':'DUP'});d=self.calc();self.assertEqual(d.orders['W1']['state'],'attention');self.assertEqual(d.material_rows['M1']['net_demand'],2)
 def test_invalid_loss_or_quantity_or_branch(self):
  for changed in [{'qty':0},{'qty':float('nan')},{'scrap_allowance':1},{'scrap_allowance':-1},{'assembly_level':''}]:
   with self.subTest(changed=changed):self.d=fixture();self.d['bom'][0].update(changed);self.assertEqual(self.calc().orders['W1']['state'],'attention')
 def test_piece_fractional_bom_use_and_issue_block(self):
  self.d['bom'][1]['qty']=0.5;self.assertEqual(self.calc().orders['W1']['state'],'attention');self.d=fixture();self.d['inventory_movements']=[issue('M2',-0.5)];self.assertEqual(self.calc().orders['W1']['state'],'attention')
 def test_bad_inventory_history_blocks_material_pool(self):
  self.d['inventory_opening'].append({**self.d['inventory_opening'][0],'id':'DUP'});d=self.calc();self.assertIsNone(d.material_rows['M1']['initial_pool']);self.assertEqual(d.summary()['attention'],3)
 def test_bad_issue_reference_and_direction_not_credited(self):
  for changed in [{'reference':'OTHER'},{'qty_signed':2},{'movement':'生产退料'}]:
   with self.subTest(changed=changed):self.d=fixture();self.d['inventory_movements']=[{**issue(),**changed}];self.assertEqual(self.calc().orders['W1']['state'],'attention')
 def test_issue_outside_bom_is_not_silent_credit(self):
  self.d['inventory_movements']=[issue('M2',-1,wo='W3')];self.assertEqual(self.calc().orders['W3']['state'],'attention')
 def test_future_issue_and_assembly_ignored(self):
  self.d['inventory_movements']=[issue(stamp='2026-10-02T08:00:00')];self.d['units']=[{'id':'U','work_order_id':'W1','product_id':'P1','assembly_at':'2026-10-02T08:00:00'}];d=self.calc();self.assertEqual(d.material_rows['M1']['initial_pool'],10);self.assertEqual(d.orders['W1']['assembled_qty'],0)
 def test_completed_orders_do_not_demand_material_twice(self):
  self.d['work_orders'][0]['status']='完工待清尾';self.d['units']=[{'id':f'U{i}','work_order_id':'W1','product_id':'P1','assembly_at':'2026-09-21T08:00:00'} for i in range(4)];d=self.calc();self.assertEqual(d.orders['W1']['state'],'excluded');self.assertEqual(d.orders['W2']['state'],'covered');self.assertEqual(d.material_rows['M2']['net_demand'],4)
 def test_closed_without_assembly_evidence_is_attention(self):
  self.d['work_orders'][0]['status']='完工待清尾';self.assertEqual(self.calc().orders['W1']['state'],'attention')
 def test_cancelled_excluded_even_without_completed_units(self):
  self.d['work_orders'][0]['status']='已取消';self.assertEqual(self.calc().orders['W1']['state'],'excluded')
 def test_unknown_status_priority_and_invalid_dates_flagged(self):
  for changed in [{'status':'未知'},{'priority':'VIP'},{'planned_start':'2026-10-12'},{'planned_qty':True}]:
   with self.subTest(changed=changed):self.d=fixture();self.d['work_orders'][0].update(changed);self.assertEqual(self.calc().orders['W1']['state'],'attention')
 def test_invalid_date_scope_reports_excluded_unknown_membership(self):
  self.d['work_orders'][0]['planned_start']=None;d=self.calc(**{'from':'2026-09-01'});self.assertNotIn('W1',d.orders);self.assertTrue(d.global_issues)
 def test_material_balance_gap_not_sum_of_failed_order_gaps(self):
  d=self.calc();m=d.material_rows['M2'];self.assertEqual(m['net_demand'],9);self.assertEqual(m['known_gap'],4);self.assertEqual(m['simulated_allocated'],5);self.assertEqual(m['remaining_pool'],0)
 def test_sources_and_inputs_preserved(self):
  before=copy.deepcopy(self.d);d=self.calc();obj=d.detail('orders','W1');refs={(r['dataset'],r['key']) for r in obj['sources']};self.assertIn(('bom','B1'),refs);self.assertIn(('inventory_opening','O1'),refs);self.assertEqual(self.d,before)
 def test_invalid_scope_rejected(self):
  for q in [{'order':'fake'},{'stock_policy':'zero'},{'from':'2026-10-01','to':'2026-09-01'},{'from':'20260101'},{'sql':'x'},{'tab':'none'},{'stage':'invalid'}]:
   with self.subTest(q=q),self.assertRaises(ValueError):mp.filters(q)

class PlanningAPITests(PlatformCase):
 def setUp(self):
  super().setUp();self.d=fixture()
  for ds,rows in self.d.items():
   for r in rows:self.record(ds,r)
  analytics._tables.cache_clear();supply.cached.cache_clear();self.addCleanup(analytics._tables.cache_clear);self.addCleanup(supply.cached.cache_clear);self.client.force_login(self.admin)
 def board(self,extra=''):
  r=self.client.get('/api/material-planning?stock_policy=all_usable'+extra);self.assertEqual(r.status_code,200,r.content);return r.json()
 def url(self,path='',extra='',receipt=None):
  receipt=receipt or self.board()['receipt'];return '/api/material-planning'+path+'?stock_policy=all_usable&receipt='+receipt+extra
 def payload(self):return {'status':'待采购核对','owner':'模拟采购岗位','note':'核对缺口物料和来料时间，不形成采购指令','due_date':'2026-10-07','version':0}
 def test_summary_state_counts_and_list_pagination(self):
  d=self.board('&stage=short');self.assertEqual(d['summary']['orders'],3);self.assertEqual(d['total'],1);self.assertEqual(d['rows'][0]['id'],'W2');self.assertEqual(d['summary']['covered'],2)
 def test_missing_object_or_outside_scope_is_not_returned(self):
  self.assertEqual(self.client.get(self.url('/orders/NONE')).status_code,404);b=self.board('&work_order=W1');self.assertEqual(self.client.get(self.url('/orders/W2','&work_order=W1',b['receipt'])).status_code,404)
 def test_receipt_required_and_data_change_blocks(self):
  receipt=self.board()['receipt'];self.assertEqual(self.client.get('/api/material-planning/orders/W1').status_code,400);r=Record.objects.get(dataset='work_orders',business_key='W1');r.values['planned_qty']=9;r.revision+=1;r.save();self.assertEqual(self.client.get(self.url('/orders/W1',receipt=receipt)).status_code,409)
 def test_rules_and_scope_changes_invalidate_receipt(self):
  receipt=self.board()['receipt'];self.assertEqual(self.client.get(self.url('/orders/W1','&family=A',receipt)).status_code,409)
  with patch('app.material_planning_views.eng.receipt',return_value='changed'):self.assertEqual(self.client.get(self.url('/orders/W1',receipt=receipt)).status_code,409)
 def test_stock_detail_and_excel_evidence_same_scope(self):
  d=self.client.get(self.url('/orders/W1')).json();self.assertEqual(d['row']['state'],'covered');r=self.client.get(self.url('/orders/W1/evidence')).json();self.assertTrue(any(x['sheet']=='bom' and x['row']==2 for x in r['rows']));self.assertEqual(self.client.get(self.url('/materials/M2')).json()['row']['known_gap'],4)
 def test_quality_and_viewer_do_not_see_financial_values(self):
  self.client.force_login(self.quality)
  for path in ['', '/orders/W1','/materials/M1','/orders/W1/evidence']:
   r=self.client.get(self.url(path));self.assertEqual(r.status_code,200,r.content);self.assertNotIn('cents',r.content.decode());self.assertNotIn('12345',r.content.decode());self.assertEqual(r['Cache-Control'],'no-store')
 def test_strategy_comparison_reports_gains_and_losses(self):
  r=self.client.get(self.url('/compare')).json();self.assertEqual(r['primary']['covered'],2);self.assertEqual(r['reference']['covered'],2);self.assertEqual({x['id'] for x in r['rows']},{'W1','W2'});self.assertEqual(r['reference_policy'],'protect_safety')
 def test_exports_current_full_list_without_fact_mutation(self):
  before=list(Record.objects.values());r=self.client.get(self.url('/export','&stage=short'));rows=list(csv.reader(io.StringIO(r.content.decode('utf-8-sig'))));self.assertEqual(len(rows),6);self.assertEqual(rows[-1][1],'W2');self.assertEqual(list(Record.objects.values()),before);self.assertEqual(AuditEvent.objects.filter(action='material_planning.export').count(),1)
 def test_material_export_contains_units_and_known_gaps(self):
  r=self.client.get(self.url('/export','&tab=materials&stage=all'));rows=list(csv.reader(io.StringIO(r.content.decode('utf-8-sig'))));self.assertEqual({x[2] for x in rows[5:]},{'kg','件'});self.assertEqual(len(rows),7)
 def test_export_formula_injection_protected(self):
  r=Record.objects.get(dataset='materials',business_key='M1');r.values['name']='=1+1';r.save();out=self.client.get(self.url('/export','&tab=materials&stage=all'));self.assertIn("'=1+1",out.content.decode('utf-8-sig'))
 def test_follow_up_optimistic_lock_and_fact_preservation(self):
  before=list(Record.objects.values());url=self.url('/orders/W2/follow-up');r=self.post(url,self.payload());self.assertEqual(r.status_code,200,r.content);self.assertEqual(r.json()['follow_up']['version'],1);self.assertEqual(self.post(url,self.payload()).status_code,409);self.assertEqual(list(Record.objects.values()),before);self.assertEqual(len(self.client.get(self.url('/orders/W2/history')).json()['rows']),1)
 def test_follow_up_audit_failure_rolls_back(self):
  with patch('app.material_planning_views.AuditEvent.objects.create',side_effect=ValueError('audit unavailable')):
   self.assertEqual(self.post(self.url('/orders/W2/follow-up'),self.payload()).status_code,400)
  self.assertFalse(IssueDisposition.objects.exists())
 def test_permission_auth_and_csrf(self):
  viewer=User.objects.create_user('viewer');viewer.groups.add(Group.objects.create(name='viewer'));self.client.force_login(viewer);self.assertEqual(self.post(self.url('/orders/W2/follow-up'),self.payload()).status_code,403)
  secure=Client(enforce_csrf_checks=True);secure.force_login(self.admin);self.assertEqual(secure.post(self.url('/orders/W2/follow-up'),json.dumps(self.payload()),content_type='application/json').status_code,403);self.client.logout();self.assertEqual(self.client.get('/api/material-planning').status_code,401)
 def test_parameters_page_and_post_validation(self):
  for suffix in ['&page=0','&page=true','&unknown=x']:
   self.assertEqual(self.client.get('/api/material-planning?stock_policy=all_usable'+suffix).status_code,400)
  for p in [{**self.payload(),'version':True},{**self.payload(),'note':'短'},{**self.payload(),'due_date':'bad'},{**self.payload(),'stock_reserved':1}]:self.assertEqual(self.post(self.url('/orders/W2/follow-up'),p).status_code,400)
 def test_mid_run_data_change_rejected(self):
  with patch('app.material_planning_views.verify',side_effect=__import__('app.import_review',fromlist=['ReviewConflict']).ReviewConflict('changed')):self.assertEqual(self.client.get('/api/material-planning').status_code,409)
 def test_unknown_demand_count_carried_to_material_export(self):
  r=Record.objects.get(dataset='bom',business_key='B1');r.values['effective']='2026-10-09';r.save();data=self.board('&tab=materials&stage=attention');self.assertTrue(any(r['unknown_order_count']==2 for r in data['rows']));out=self.client.get(self.url('/export','&tab=materials&stage=all'));self.assertIn('需求待核对工单数',out.content.decode('utf-8-sig'))
 def test_wrong_receipt_cannot_save_coordination(self):
  url=self.url('/orders/W2/follow-up',receipt='wrong');self.assertEqual(self.post(url,self.payload()).status_code,409);self.assertFalse(IssueDisposition.objects.exists())
