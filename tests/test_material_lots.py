import copy,csv,io
from decimal import Decimal
from django.test import SimpleTestCase
from django.contrib.auth.models import User,Group
from app import material_planning as mp,material_planning_views as views,analytics,supply
from app.models import Record,AuditEvent,IssueDisposition
from .test_material_planning import fixture as planning_fixture,issue
from .test_platform import PlatformCase

def date_profile(mid,lot,key,**extra):return {'id':key,'material_id':mid,'lot':lot,'version':1,'supersedes_id':None,'registered':'2026-09-26T09:00:00','manufactured':'2026-07-01','first_stock_date':'2026-08-01','expires':'2026-10-15' if mid=='M1' else None,'expiry_mode':'固定日期' if mid=='M1' else '不适用','document_no':'模拟登记-'+key,'owner_id':'E1','voided':False,'note':'合成日期资料'}|extra
def fixture():
 d=planning_fixture();d['inventory_lot_dates']=[date_profile('M1','L1','D1'),date_profile('M2','L2','D2')]
 d['inventory_age_policies']=[{'id':'R'+m['id'],'material_id':m['id'],'version':1,'supersedes_id':None,'effective_from':'2026-09-01','registered':'2026-09-25T09:00:00','age_limit_days':60,'warning_days':14,'expiry_required':m['id']=='M1','owner_id':'E1','status':'模拟确认','reason':'合成规则'} for m in d['materials']]
 return d
def another_lot(d,**extra):
 d['inventory_opening'].append(d['inventory_opening'][0]|{'id':'O3','lot':'L3','location':'A3','qty':5});r=date_profile('M1','L3','D3',first_stock_date='2026-08-15',expires='2026-10-05')|extra;d['inventory_lot_dates'].append(r);return r
def plans(d,mid):return [p for w in d.ordered for item in w['items'] if item['material_id']==mid for p in item.get('lot_allocations',[])]

class MaterialLotLogicTests(SimpleTestCase):
 def setUp(self):self.d=fixture()
 def calc(self,**f):return mp.MaterialPlanning(self.d,mp.filters({'stock_policy':'all_usable','lot_policy':'fefo',**f}))
 def test_legacy_policy_exact_original_quantities(self):
  a=self.calc(lot_policy='ledger');b=self.calc();self.assertEqual(a.pool,b.pool);self.assertEqual([w['state'] for w in a.ordered],[w['state'] for w in b.ordered]);self.assertIsNone(a.lot_pool)
 def test_read_does_not_change_original_stock_or_data(self):
  before=copy.deepcopy(self.d);stock=copy.deepcopy(supply.SupplyData(self.d).lots);self.calc();self.assertEqual(self.d,before);self.assertEqual(supply.SupplyData(self.d).lots,stock)
 def test_one_shared_batch_not_reused(self):
  d=self.calc();self.assertEqual(sum(p['qty'] for p in plans(d,'M1')),6);self.assertEqual([p['before'] for p in plans(d,'M1')],[10,6]);self.assertEqual(d.lot_pool.slices['M1'][0]['remaining'],4)
 def test_short_whole_order_allocates_no_batches(self):
  self.d['inventory_opening'][1]['qty']=3;d=self.calc();self.assertEqual(d.orders['W1']['state'],'short');self.assertTrue(all(i['lot_allocations']==[] for i in d.orders['W1']['items']));self.assertEqual(d.pool['M1'],8)
 def test_rounded_piece_demand_has_exact_batch_quantity(self):
  d=self.calc();p=d.orders['W1']['items'][1]['lot_allocations'][0];self.assertEqual(p['qty'],5);self.assertEqual(p['after'],0)
 def test_already_issued_only_subtracted_once(self):
  self.d['inventory_movements']=[issue()];d=self.calc();item=d.orders['W1']['items'][0];self.assertEqual(item['lot_allocations'][0]['qty'],2);self.assertEqual(d.material_rows['M1']['initial_pool'],8);self.assertEqual(d.pool['M1'],4)
 def test_overage_still_valid_not_automatic_exclusion(self):
  d=self.calc();self.assertTrue(d.lot_pool.date_data.rows[0]['overage']);self.assertEqual(d.material_rows['M1']['date_candidate_qty'],10);self.assertEqual(d.orders['W1']['state'],'covered')
 def test_expired_stock_quantity_retained_in_ledger(self):
  self.d['inventory_lot_dates'][0]['expires']='2026-09-30';d=self.calc();m=d.material_rows['M1'];self.assertEqual((m['usable_state_qty'],m['date_candidate_qty'],m['date_excluded_usable_qty']),(10,0,10));self.assertEqual(d.orders['W1']['state'],'short');self.assertEqual(d.lot_pool.details('M1')[0]['selection_reason'],'截止日已过期')
 def test_unknown_first_date_excluded_not_actual_zero(self):
  self.d['inventory_lot_dates'][0]['first_stock_date']=None;d=self.calc();m=d.material_rows['M1'];self.assertEqual(m['usable_state_qty'],10);self.assertEqual(m['date_excluded_usable_qty'],10);self.assertIn('日期',d.lot_pool.details('M1')[0]['selection_reason'])
 def test_unknown_policy_excludes_date_candidate(self):
  self.d['inventory_age_policies'].pop(0);d=self.calc();self.assertEqual(d.material_rows['M1']['date_candidate_qty'],0);self.assertEqual(d.lot_pool.details('M1')[0]['selection_reason'],'规则待核对')
 def test_future_or_void_correction_does_not_replace(self):
  for extra in [{'registered':'2026-10-02T09:00:00'},{'voided':True}]:
   self.d=fixture();self.d['inventory_lot_dates'].append(self.d['inventory_lot_dates'][0]|{'id':'D4','version':2,'supersedes_id':'D1','registered':'2026-09-28T09:00:00','expires':'2026-09-30'}|extra);self.assertEqual(self.calc().orders['W1']['state'],'covered')
 def test_current_correction_adopted_and_sources_preserved(self):
  self.d['inventory_lot_dates'].append(self.d['inventory_lot_dates'][0]|{'id':'D4','version':2,'supersedes_id':'D1','registered':'2026-09-28T09:00:00','expires':'2026-09-30'});d=self.calc();self.assertEqual(d.orders['W1']['state'],'short');sources=d.detail('orders','W1')['sources'];self.assertIn({'dataset':'inventory_lot_dates','key':'D1'},sources);self.assertIn({'dataset':'inventory_lot_dates','key':'D4'},sources)
 def test_invalid_ledger_cannot_cherry_pick_good_lots(self):
  another_lot(self.d);self.d['inventory_opening'].append(self.d['inventory_opening'][0]|{'id':'DUP'});d=self.calc();self.assertIsNone(d.material_rows['M1']['initial_pool']);self.assertEqual(d.orders['W1']['state'],'attention');self.assertEqual(plans(d,'M1'),[])
 def test_restricted_state_excluded(self):
  self.d['inventory_opening'][0]['status']='冻结';d=self.calc();self.assertEqual(d.material_rows['M1']['date_candidate_qty'],0);self.assertEqual(d.lot_pool.details('M1')[0]['selection_reason'],'状态受限')
 def test_fifo_fefo_choose_different_first_lot(self):
  another_lot(self.d);a=self.calc(lot_policy='fifo');b=self.calc(lot_policy='fefo');self.assertEqual(a.orders['W1']['items'][0]['lot_allocations'][0]['lot'],'L1');self.assertEqual(b.orders['W1']['items'][0]['lot_allocations'][0]['lot'],'L3')
 def test_fefo_can_split_one_material_across_batches(self):
  another_lot(self.d);d=self.calc();parts=d.orders['W3']['items'][0]['lot_allocations'];self.assertEqual([(p['lot'],p['qty']) for p in parts],[('L3',1),('L1',1)])
 def test_safety_buffer_retained_once_from_sequence_end(self):
  another_lot(self.d);d=self.calc(stock_policy='protect_safety');rows=d.lot_pool.slices['M1'];self.assertEqual([(r['lot'],r['retained']) for r in rows],[('L3',0),('L1',2)]);self.assertEqual(d.material_rows['M1']['initial_pool'],13)
 def test_fifo_buffer_stays_at_end_of_fifo_sequence(self):
  another_lot(self.d);d=self.calc(stock_policy='protect_safety',lot_policy='fifo');self.assertEqual([(r['lot'],r['retained']) for r in d.lot_pool.slices['M1']],[('L1',0),('L3',2)])
 def test_buffer_larger_than_candidates_keeps_whole_pool(self):
  self.d['materials'][0]['safety_qty']=100;d=self.calc(stock_policy='protect_safety');self.assertEqual(d.material_rows['M1']['initial_pool'],0);self.assertEqual(d.lot_pool.slices['M1'][0]['retained'],10)
 def test_use_date_skips_lot_expiring_before_start(self):
  another_lot(self.d);self.d['work_orders'][0].update(planned_start='2026-10-10',planned_end='2026-10-11');d=self.calc(work_order='W1');i=d.orders['W1']['items'][0];self.assertEqual((i['use_day'],i['before_pool'],i['date_available_pool'],i['date_excluded_at_use']),('2026-10-10',15,10,5));self.assertEqual(i['lot_allocations'][0]['lot'],'L1')
 def test_valid_until_use_day_itself(self):
  another_lot(self.d,expires='2026-10-10');self.d['work_orders'][0].update(planned_start='2026-10-10',planned_end='2026-10-11');d=self.calc(work_order='W1');self.assertEqual(d.orders['W1']['items'][0]['lot_allocations'][0]['lot'],'L3')
 def test_old_plan_date_cannot_restore_expired_lot(self):
  self.d['inventory_lot_dates'][0]['expires']='2026-09-30';d=self.calc();self.assertEqual(d.orders['W1']['items'][0]['use_day'],'2026-10-01');self.assertEqual(d.orders['W1']['items'][0]['lot_allocations'],[])
 def test_future_shortage_does_not_deplete_earlier_order_pool(self):
  self.d['work_orders'][0].update(priority='紧急',planned_start='2026-10-20',planned_end='2026-10-21');d=self.calc(order='priority');self.assertEqual(d.ordered[0]['id'],'W1');self.assertEqual(d.orders['W1']['state'],'short');self.assertEqual(d.orders['W2']['state'],'covered');self.assertEqual(d.orders['W2']['items'][0]['lot_allocations'][0]['before'],10)
 def test_stage_tab_do_not_rebuild_shared_batch_pool(self):
  a=self.calc();b=self.calc(tab='materials',stage='short');self.assertEqual(a.lot_pool.slices,b.lot_pool.slices)
 def test_candidate_and_slice_quantities_reconcile(self):
  another_lot(self.d);d=self.calc(stock_policy='protect_safety')
  for mid,rs in d.lot_pool.slices.items():
   self.assertEqual(sum(r['initial'] for r in rs),d.material_rows[mid]['initial_pool']);self.assertEqual(sum(r['remaining'] for r in rs),d.pool[mid]);self.assertEqual(sum(r['balance_qty'] for r in rs),sum(r['retained']+r['initial'] for r in rs));self.assertEqual(sum(p['qty'] for p in plans(d,mid)),sum(r['initial']-r['remaining'] for r in rs))
 def test_empty_scope_does_not_allocate_unselected_orders(self):
  self.assertEqual(self.calc(work_order='missing').material_rows,{});self.assertEqual(self.calc(work_order='missing').lot_pool.slices,{})
 def test_bad_policy_rejected(self):
  with self.assertRaises(ValueError):mp.filters({'lot_policy':'execute'})

class MaterialLotApiTests(PlatformCase):
 def setUp(self):
  super().setUp();self.d=fixture();another_lot(self.d)
  for ds,rows in self.d.items():
   for r in rows:self.record(ds,r)
  self.client.force_login(self.admin)
 def board(self,q=''):
  r=self.client.get('/api/material-planning?stock_policy=all_usable&lot_policy=fefo'+q);self.assertEqual(r.status_code,200,r.content);return r.json()
 def url(self,path='material-planning/orders/W1',q='',d=None):return '/api/'+path+'?stock_policy=all_usable&lot_policy=fefo&receipt='+(d or self.board(q))['receipt']+q
 def test_detail_batch_plans_and_sources(self):
  d=self.client.get(self.url()).json();self.assertEqual(d['row']['items'][0]['lot_allocations'][0]['lot'],'L3');s=self.client.get(self.url('material-planning/orders/W1/evidence')).json();self.assertTrue(any(r['dataset']=='inventory_lot_dates' and r['row']==2 for r in s['rows']))
 def test_new_date_strategy_receipt_bound(self):
  url=self.url();self.assertEqual(self.client.get(url.replace('lot_policy=fefo','lot_policy=fifo')).status_code,409)
 def test_date_change_invalidates_old_plan(self):
  url=self.url();r=Record.objects.get(dataset='inventory_lot_dates',business_key='D3');r.values['expires']='2026-09-30';r.revision+=1;r.save();self.assertEqual(self.client.get(url).status_code,409)
 def test_csv_selected_covered_orders_only(self):
  before=list(Record.objects.values());r=self.client.get(self.url('material-lots/export','&stage=covered'));self.assertEqual(r.status_code,200,r.content);rows=list(csv.reader(io.StringIO(r.content.decode('utf-8-sig'))));self.assertEqual({r[1] for r in rows[5:]},{'W1','W3'});self.assertEqual(len(rows)-5,4);self.assertEqual(list(Record.objects.values()),before);self.assertEqual(AuditEvent.objects.filter(action='material_lots.export').count(),1)
 def test_csv_short_orders_have_no_batch_occupancy(self):
  r=self.client.get(self.url('material-lots/export','&stage=short'));rows=list(csv.reader(io.StringIO(r.content.decode('utf-8-sig'))));self.assertEqual(len(rows),5)
 def test_material_csv_respects_material_list_stage(self):
  r=self.client.get(self.url('material-lots/export','&tab=materials&stage=short'));rows=list(csv.reader(io.StringIO(r.content.decode('utf-8-sig'))));self.assertEqual({r[3] for r in rows[5:]},{'M2'})
 def test_impact_export_deduplicates_work_order_shared_by_two_lines(self):
  from .test_material_impact import source
  source_data=source();source_data['order_lines'][0]['qty']=5;source_data['allocations'][0]['qty']=2
  source_data['order_lines'].append(source_data['order_lines'][0]|{'id':'L3','qty':2})
  source_data['allocations'].append(source_data['allocations'][0]|{'id':'A4','order_line_id':'L3'})
  for ds in ['customers','orders','order_lines','allocations']:
   for row in source_data[ds]:self.record(ds,row)
  d=self.board('&tab=impact');r=self.client.get(self.url('material-lots/export','&tab=impact',d));rows=list(csv.reader(io.StringIO(r.content.decode('utf-8-sig'))));self.assertEqual(len(rows)-5,4)
  self.assertEqual(sum(Decimal(row[8]) for row in rows[5:] if row[1]=='W1' and row[3]=='M1'),4)
  self.assertIn('按工单去重',rows[2][1]);self.assertNotIn('cents',r.content.decode())
 def test_legacy_csv_batch_plan_unavailable(self):
  d=self.client.get('/api/material-planning?lot_policy=ledger').json();r=self.client.get('/api/material-lots/export?lot_policy=ledger&receipt='+d['receipt']);self.assertEqual(r.status_code,400)
 def test_comparison_same_queue_safety_and_three_options(self):
  r=self.client.get(self.url('material-planning/lot-compare'));self.assertEqual(r.status_code,200);d=r.json();self.assertEqual({x['key'] for x in d['results']},{'ledger','fifo','fefo'});self.assertTrue(all(x['summary']['orders']==3 for x in d['results']));self.assertEqual(d['filters']['stock_policy'],'all_usable')
 def test_duplicate_filters_rejected(self):
  for q in ['&lot_policy=fifo','&q=a&q=b']:
   self.assertEqual(self.client.get('/api/material-planning?lot_policy=fefo'+q).status_code,400)
 def test_auth_method_and_stale_export_no_audit(self):
  self.assertEqual(self.post('/api/material-lots/export',{}).status_code,405);self.assertEqual(self.client.get('/api/material-lots/export?lot_policy=fefo&receipt=bad').status_code,409);self.assertFalse(AuditEvent.objects.filter(action='material_lots.export').exists());self.client.logout();self.assertEqual(self.client.get('/api/material-lots/export').status_code,401)
 def test_existing_roles_have_no_financial_field_leak(self):
  self.client.force_login(self.quality)
  for path in ['material-planning/orders/W1','material-planning/materials/M1','material-planning/lot-compare','material-lots/export']:
   r=self.client.get(self.url(path));self.assertEqual(r.status_code,200,r.content);self.assertNotIn('cents',r.content.decode());self.assertNotIn('unit_cost',r.content.decode())
 def test_saved_coordination_returns_same_date_strategy(self):
  f={'status':'待计划协调','owner':'模拟计划岗位','note':'核对到期批次，未生成领料指令','due_date':'2026-10-08','version':0};r=self.post(self.url('material-planning/orders/W1/follow-up'),f);self.assertEqual(r.status_code,200,r.content)
  hub=self.client.get('/api/coordination-hub').json();row=next(r for r in hub['rows'] if r['key']=='material_planning:orders:W1');self.assertIn('lot_policy=fefo',row['href']);self.assertNotIn('work_order=W1',row['href']);self.assertIn('focus=orders',row['href'])
