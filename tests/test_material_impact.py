import copy,csv,io,json
from unittest.mock import patch
from django.test import SimpleTestCase,Client
from django.contrib.auth.models import User,Group
from app import material_impact as mi,material_planning as mp,analytics
from app.models import Record,IssueDisposition,AuditEvent
from .test_platform import PlatformCase
from .test_material_planning import fixture

def source():
 d=fixture();d['customers']=[{'id':'C1','name':'模拟客户'}];d['orders']=[{'id':'O1','customer_id':'C1','order_date':'2026-09-01','status':'待生产','currency':'CNY','secret':'hidden'}]
 d['order_lines']=[{'id':'L1','order_id':'O1','product_id':'P1','qty':7,'due':'2026-10-02','unit_price_cents':987654},{'id':'L2','order_id':'O1','product_id':'P2','qty':2,'due':'2026-09-29','unit_price_cents':123456}]
 d['allocations']=[{'id':k,'work_order_id':w,'order_line_id':l,'qty':q,'effective':'2026-09-01'} for k,w,l,q in [('A1','W1','L1',4),('A2','W2','L1',3),('A3','W3','L2',2)]]
 return d

class OrderImpactTests(SimpleTestCase):
 def setUp(self):self.d=source()
 def build(self,**scope):return mi.OrderImpact(mp.MaterialPlanning(self.d,mp.filters({'stock_policy':'all_usable',**scope})))
 def test_order_line_has_two_work_orders_without_multiplying_demand(self):
  x=self.build();r=x.index['L1'];self.assertEqual((r['qty'],r['selected_allocated_qty'],r['covered_link_qty'],r['short_link_qty']),(7,7,4,3));self.assertEqual(x.summary()['short_lines'],1);self.assertEqual(x.summary()['short_link_qty'],3)
 def test_shared_work_order_keeps_plan_links_not_sn_inference(self):
  self.d['order_lines'].append({**self.d['order_lines'][0],'id':'L3','qty':2});self.d['order_lines'][0]['qty']=5;self.d['allocations'][0]['qty']=2;self.d['allocations'].append({**self.d['allocations'][0],'id':'A4','order_line_id':'L3'})
  x=self.build();self.assertTrue(x.index['L1']['links'][0]['shared']);self.assertEqual(x.index['L3']['covered_link_qty'],2);self.assertNotIn('produced_qty',x.index['L3'])
 def test_partial_queue_does_not_reuse_outside_work_order_verdict(self):
  r=self.build(work_order='W2').index['L1'];self.assertEqual(r['outside_work_orders'],['W1']);self.assertEqual((r['outside_link_qty'],r['selected_allocated_qty'],r['covered_link_qty']),(4,3,3));self.assertEqual(r['links'][0]['state'],'outside');self.assertEqual(r['links'][0]['short_materials'],[])
 def test_unassigned_work_order_never_guessed_from_same_product(self):
  self.d['allocations'].pop(1);x=self.build();self.assertEqual(x.summary()['unlinked_work_orders'],1);self.assertEqual(x.unlinked[0]['id'],'W2');self.assertEqual(x.index['L1']['unallocated_qty'],3)
 def test_missing_order_line_is_visible_as_work_order_problem(self):
  self.d['allocations'][1]['order_line_id']='MISSING';x=self.build();self.assertIn('W2',[r['id'] for r in x.unlinked]);self.assertNotIn('MISSING',x.index)
 def test_order_line_overallocation_blocks_complete_plan_quantities(self):
  self.d['order_lines'][0]['qty']=6;r=self.build().index['L1'];self.assertIn('attention',r['flags']);self.assertIsNone(r['short_link_qty']);self.assertNotIn('short',r['flags'])
 def test_global_work_order_overallocation_checked_across_other_orders(self):
  self.d['order_lines'].append({**self.d['order_lines'][0],'id':'L3','qty':1});self.d['allocations'].append({**self.d['allocations'][0],'id':'A4','order_line_id':'L3','qty':1});x=self.build();self.assertIsNone(x.index['L1']['covered_link_qty']);self.assertIsNone(x.index['L3']['covered_link_qty']);self.assertTrue(any(s['dataset']=='allocations' and s['key']=='A4' for s in x.detail('L1')['sources']))
 def test_duplicate_pair_same_day_is_not_added_twice(self):
  self.d['allocations'].append({**self.d['allocations'][0],'id':'DUP'});self.assertTrue(any('重复分配' in i for i in self.build().index['L1']['issues']))
 def test_allocation_quantities_must_be_positive_integer(self):
  for q in [0,-1,1.5,True,None,'3']:
   with self.subTest(q=q):self.d=source();self.d['allocations'][1]['qty']=q;self.assertIsNone(self.build().index['L1']['short_link_qty'])
 def test_configuration_mismatch_is_not_valid_link(self):
  self.d['order_lines'][0]['product_id']='P2';r=self.build().index['L1'];self.assertIn('attention',r['flags']);self.assertIsNone(r['selected_allocated_qty'])
 def test_future_allocation_ignored_and_missing_link_reported(self):
  self.d['allocations'][1]['effective']='2026-10-05';x=self.build();self.assertEqual(x.index['L1']['selected_allocated_qty'],4);self.assertIn('W2',[r['id'] for r in x.unlinked])
 def test_bad_allocation_date_not_silently_discarded(self):
  self.d['allocations'][1]['effective']='wrong';self.assertIn('attention',self.build().index['L1']['flags'])
 def test_missing_work_order_in_other_allocation_blocks_order(self):
  self.d['allocations'][0]['work_order_id']='MISSING';self.assertIn('attention',self.build().index['L1']['flags'])
 def test_missing_order_customer_product_and_cancelled_status(self):
  for ds in ['orders','customers','products']:
   with self.subTest(ds=ds):self.d=source();self.d[ds]=[];self.assertIn('attention',self.build().index['L1']['flags'])
  self.d=source();self.d['orders'][0]['status']='已取消';self.assertIn('attention',self.build().index['L1']['flags'])
 def test_future_order_unknown_due_and_bad_quantity(self):
  for ds,key,value in [('orders','order_date','2026-10-05'),('order_lines','due','wrong'),('order_lines','qty',-1)]:
   with self.subTest(key=key):self.d=source();self.d[ds][0][key]=value;self.assertIn('attention',self.build().index['L1']['flags'])
 def test_shipments_reconcile_once_per_line_not_per_work_order(self):
  self.d['shipments']=[{'id':'S1','order_line_id':'L1','qty':2,'shipped':'2026-09-29T08:00:00'}];r=self.build().index['L1'];self.assertEqual((r['qty'],r['shipped_qty'],r['remaining_qty'],r['short_link_qty']),(7,2,5,3))
 def test_future_shipments_excluded(self):
  self.d['shipments']=[{'id':'S1','order_line_id':'L1','qty':2,'shipped':'2026-10-05T08:00:00'}];self.assertEqual(self.build().index['L1']['remaining_qty'],7)
 def test_invalid_shipments_do_not_become_zero(self):
  for q,t in [(-1,'2026-09-29T08:00:00'),(8,'2026-09-29T08:00:00'),(1,'bad'),(1,'2026-08-01T08:00:00')]:
   with self.subTest(q=q,t=t):self.d=source();self.d['shipments']=[{'id':'S1','order_line_id':'L1','qty':q,'shipped':t}];r=self.build().index['L1'];self.assertIsNone(r['remaining_qty']);self.assertIn('attention',r['flags'])
 def test_already_shipped_line_not_counted_as_open_material_risk(self):
  self.d['shipments']=[{'id':'S1','order_line_id':'L1','qty':7,'shipped':'2026-09-29T08:00:00'}];r=self.build().index['L1'];self.assertEqual(r['short_link_qty'],3);self.assertNotIn('short',r['flags']);self.assertEqual(self.build().summary()['short_link_qty'],0)
 def test_due_today_not_overdue_and_past_due_independent_of_materials(self):
  self.d['order_lines'][0]['due']='2026-10-01';x=self.build();self.assertEqual(x.index['L1']['overdue_remaining_qty'],0);self.assertEqual(x.index['L2']['overdue_remaining_qty'],2)
 def test_plan_finish_later_than_commitment_is_a_date_comparison(self):
  self.d['work_orders'][0]['planned_end']='2026-10-04';self.d['work_orders'][1]['planned_end']='2026-10-02';self.assertEqual(self.build().index['L1']['plan_after_due_count'],1)
 def test_unknown_material_data_not_given_covered_plan_quantity(self):
  self.d['inventory_opening'].pop();r=self.build().index['L1'];self.assertIn('attention',r['flags']);self.assertIsNone(r['covered_link_qty'])
 def test_sources_cover_explicit_relation_and_bom_stock(self):
  ds={r['dataset'] for r in self.build().detail('L1')['sources']};self.assertTrue({'allocations','order_lines','orders','customers','products','work_orders','bom','inventory_opening'}<=ds)
 def test_no_money_and_input_immutability(self):
  before=copy.deepcopy(self.d);r=self.build();s=json.dumps(mp.clean({'rows':r.rows,'summary':r.summary()}));self.assertNotIn('987654',s);self.assertNotIn('unit_price_cents',s);self.assertNotIn('secret',s);self.assertEqual(self.d,before)
 def test_empty_scope_has_no_fallback_orders(self):
  x=self.build(work_order='NONE');self.assertEqual(x.rows,[]);self.assertEqual(x.unlinked,[])
 def test_display_stage_never_changes_pool(self):
  a=self.build();b=self.build(tab='impact',stage='short');self.assertEqual(a.planning.pool,b.planning.pool);self.assertEqual(a.rows,b.rows)

class OrderImpactApiTests(PlatformCase):
 def setUp(self):
  super().setUp()
  for ds,rows in source().items():
   for row in rows:self.record(ds,row)
  self.client.force_login(self.admin)
 def board(self,extra=''):
  r=self.client.get('/api/material-planning?tab=impact&stock_policy=all_usable'+extra);self.assertEqual(r.status_code,200,r.content);return r.json()
 def url(self,path='',extra=''):
  return '/api/material-planning'+path+'?tab=impact&stock_policy=all_usable&receipt='+self.board()['receipt']+extra
 def payload(self,version=0):return {'status':'待计划协调','owner':'模拟计划岗位','note':'核对订单分配和当前完整队列，未更改交期或预留。','due_date':'2026-10-08','version':version}
 def test_board_stages_and_brief_have_correct_grain(self):
  d=self.board('&stage=short');self.assertEqual(d['total'],1);self.assertEqual(d['impact_summary']['lines'],2);self.assertEqual(d['rows'][0]['id'],'L1');self.assertNotIn('links',d['rows'][0]);self.assertIn('计划关系',d['impact_note'])
 def test_detail_and_bidirectional_work_order_links(self):
  r=self.client.get(self.url('/impact/L1'));self.assertEqual(r.status_code,200);self.assertEqual(len(r.json()['row']['links']),2);r=self.client.get(self.url('/orders/W2'));self.assertEqual(r.json()['order_links'][0]['id'],'L1')
 def test_out_of_scope_detail_is_not_accessible(self):
  b=self.board('&work_order=W3');r=self.client.get('/api/material-planning/impact/L1?tab=impact&stock_policy=all_usable&work_order=W3&receipt='+b['receipt']);self.assertEqual(r.status_code,404)
 def test_export_matches_stage_and_has_boundary_and_units(self):
  r=self.client.get(self.url('/export','&stage=short'));self.assertEqual(r.status_code,200);rows=list(csv.reader(io.StringIO(r.content.decode('utf-8-sig'))));self.assertEqual(len(rows),6);self.assertEqual(rows[5][0],'L1');self.assertIn('缺料工单关联计划台数',rows[4]);self.assertIn('不是已产出',rows[1][1])
 def test_compare_preserves_queue_and_lists_order_changes(self):
  r=self.client.get(self.url('/compare')).json();self.assertEqual(r['primary_impact']['short_link_qty'],3);self.assertEqual(r['reference_impact']['short_link_qty'],4);self.assertEqual(r['order_changes'][0]['id'],'L1');self.assertEqual(r['order_changes'][0]['remaining_qty'],7)
 def test_source_manifest_includes_allocation(self):
  r=self.client.get(self.url('/impact/L1/evidence')).json();self.assertTrue(any(x['dataset']=='allocations' and x['key']=='A2' for x in r['rows']))
 def test_missing_line_relation_still_has_allocation_evidence_on_work_order(self):
  r=Record.objects.get(dataset='allocations',business_key='A2');r.values['order_line_id']='MISSING';r.save();response=self.client.get(self.url('/orders/W2/evidence')).json();self.assertTrue(any(x['dataset']=='allocations' and x['key']=='A2' for x in response['rows']))
 def test_viewer_can_read_but_not_write(self):
  u=User.objects.create_user('viewer',password='test');u.groups.add(Group.objects.create(name='viewer'));self.client.force_login(u);self.assertFalse(self.client.get(self.url('/impact/L1')).json()['can_follow']);self.assertEqual(self.post(self.url('/impact/L1/follow-up'),self.payload()).status_code,403)
 def test_quality_can_read_without_financial_fields(self):
  self.client.force_login(self.quality);r=self.client.get(self.url('/impact/L1'));self.assertEqual(r.status_code,200);self.assertNotIn('unit_price_cents',r.content.decode());self.assertNotIn('987654',r.content.decode())
 def test_follow_up_version_and_no_business_fact_changes(self):
  before=list(Record.objects.order_by('id').values_list('id','values','revision'));url=self.url('/impact/L1/follow-up');self.assertEqual(self.post(url,self.payload()).status_code,200);self.assertEqual(self.post(url,self.payload()).status_code,409);self.assertEqual(list(Record.objects.order_by('id').values_list('id','values','revision')),before);self.assertEqual(IssueDisposition.objects.get().key,'material_planning:impact:L1');self.assertEqual(self.client.get(self.url('/impact/L1/history')).json()['rows'][0]['detail']['after']['version'],1)
 def test_stale_receipt_after_allocation_change(self):
  url=self.url('/impact/L1');r=Record.objects.get(dataset='allocations',business_key='A1');r.values['qty']=1;r.save();self.assertEqual(self.client.get(url).status_code,409)
 def test_audit_failure_rolls_back_follow_up(self):
  url=self.url('/impact/L1/follow-up')
  with patch('app.material_planning_views.AuditEvent.objects.create',side_effect=RuntimeError('audit')):
   with self.assertRaises(RuntimeError):self.post(url,self.payload())
  self.assertFalse(IssueDisposition.objects.exists())
 def test_csrf_and_anonymous(self):
  c=Client(enforce_csrf_checks=True);c.force_login(self.admin);self.assertEqual(c.post(self.url('/impact/L1/follow-up'),json.dumps(self.payload()),content_type='application/json').status_code,403);self.client.logout();self.assertEqual(self.client.get('/api/material-planning?tab=impact').status_code,401)
