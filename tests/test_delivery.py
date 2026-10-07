import csv,io,json
from copy import deepcopy
from unittest.mock import patch
from django.test import SimpleTestCase,Client
from app import analytics,delivery,semantic
from app.models import AuditEvent,IssueDisposition,Record
from tests.test_platform import PlatformCase
from tests.test_semantic import fixture as semantic_fixture

def fixture():
    d=semantic_fixture()
    d['orders'][0].update(customer_po='客户PO-00001',status='部分交付')
    d['work_orders'][0].update(planned_start='2026-09-20',bom_version='A',route_version='A')
    for p in d['delivery_plans']:p['version']=1
    for s in d['shipments']:s.update(signed=None,tracking='物流-'+s['id'])
    return d

class DeliveryFactsTests(SimpleTestCase):
    def setUp(self):self.d=fixture()
    def row(self):return delivery.build(self.d)[0]
    def test_quantity_does_not_multiply_through_multiple_plans_and_retests(self):
        r=self.row();self.assertEqual((r['qty'],r['shipped_qty'],r['remaining_qty'],r['produced_qty']),(10,2,8,2))
        self.assertEqual(r['stages']['shipped'],2);self.assertEqual(sum(r['stages'].values()),2);self.assertFalse(r['issues'])
    def test_shared_work_order_is_unknown_not_zero_or_proportional(self):
        self.d['order_lines'].append({**self.d['order_lines'][0],'id':'L2'})
        self.d['allocations'][0]['qty']=5
        self.d['allocations'].append(dict(id='A2',work_order_id='W1',order_line_id='L2',qty=5,effective='2026-09-01'))
        for r in delivery.build(self.d):
            self.assertIsNone(r['produced_qty']);self.assertIsNone(r['quality_wait_qty']);self.assertIsNone(r['stages']['ready']);self.assertEqual(r['_units'],[]);self.assertIn('unknown',r['flags'])
    def test_future_shipping_and_its_packs_do_not_mark_a_unit_shipped(self):
        self.d['shipments'][1]['shipped']='2026-10-05T08:00:00'
        r=self.row();self.assertEqual(r['shipped_qty'],1);self.assertEqual(r['stages']['ready'],1);self.assertEqual(r['stages']['shipped'],1)
    def test_latest_test_invalidates_older_release(self):
        self.d['shipments']=[];self.d['shipment_units']=[]
        self.d['test_sessions'].append({**self.d['test_sessions'][-1],'id':'T4','tested':'2026-09-22T15:00:00','attempt':2})
        self.d['measurements'].append({**self.d['measurements'][-1],'id':'MS4','session_id':'T4'})
        r=self.row();self.assertEqual(r['stages']['waiting_release'],1);self.assertEqual(r['stages']['ready'],1)
        self.d['releases'].append(dict(id='R3',unit_id='U2',session_id='T4',released='2026-09-22T16:00:00',status='批准放行'))
        self.assertEqual(self.row()['stages']['ready'],2)
    def test_voided_test_does_not_change_current_state(self):
        self.d['test_sessions'].append({**self.d['test_sessions'][-1],'id':'VOID','tested':'2026-09-22T15:00:00','voided':True})
        r=self.row();self.assertEqual(r['post_shipment_attention'],0);self.assertEqual(r['_units'][1]['session_count'],1)
    def test_new_failure_after_shipping_is_visible_without_unshipping(self):
        self.d['test_sessions'].append({**self.d['test_sessions'][-1],'id':'T4','tested':'2026-09-28T15:00:00','attempt':2,'result':'不合格'})
        self.d['measurements'].append({**self.d['measurements'][-1],'id':'MS4','session_id':'T4','value':3,'result':'不合格'})
        r=self.row();self.assertEqual(r['shipped_qty'],2);self.assertEqual(r['post_shipment_attention'],1);self.assertIn('quality',r['flags'])
    def test_latest_withdrawal_does_not_leave_a_unit_ready(self):
        self.d['shipments']=[];self.d['shipment_units']=[]
        self.d['releases'].append(dict(id='R3',unit_id='U2',session_id='T3',released='2026-09-25T16:00:00',status='撤销放行'))
        self.assertEqual(self.row()['stages']['ready'],1)
        self.assertEqual(self.row()['stages']['waiting_release'],1)
    def test_due_today_is_neither_overdue_nor_a_closed_otif_sample(self):
        for p in self.d['delivery_plans']:p['due']='2026-10-01'
        r=self.row();self.assertEqual((r['overdue_qty'],r['due_plan_count']),(0,0))
        self.assertEqual(semantic.build(self.d)['bi_order_lines'][0]['due_plan_count'],0)
        with patch.object(analytics,'AS_OF','2026-10-02T08:00:00'):
            r=self.row();self.assertEqual((r['overdue_qty'],r['due_plan_count']),(8,2))
    def test_packing_quantity_mismatch_is_not_hidden(self):
        self.d['shipment_units'].append({**self.d['shipment_units'][0],'id':'DUP'})
        r=self.row();self.assertIn('unknown',r['flags']);self.assertTrue(any('装箱SN' in x for x in r['issues']));self.assertEqual(r['shipped_qty'],2)
    def test_multiple_allocations_to_same_line_do_not_duplicate_units(self):
        self.d['allocations'][0]['qty']=5
        self.d['allocations'].append({**self.d['allocations'][0],'id':'A2','qty':5})
        r=self.row();self.assertEqual((r['allocated_qty'],r['produced_qty']),(10,2));self.assertFalse(r['issues'])
    def test_packing_from_an_unallocated_work_order_is_flagged(self):
        self.d['units'][0]['work_order_id']='ANOTHER-WO'
        self.assertTrue(any('工单分配' in x for x in self.row()['issues']))
    def test_shipping_before_assembly_is_flagged(self):
        self.d['shipments'][0]['shipped']='2026-09-20T12:00:00'
        self.assertTrue(any('发货前装配' in x for x in self.row()['issues']))
    def test_future_allocations_are_excluded(self):
        self.d['allocations'][0]['effective']='2026-10-05'
        r=self.row();self.assertEqual(r['allocated_qty'],0);self.assertEqual(r['produced_qty'],0)
    def test_nullable_operation_end_is_supported_and_not_complete(self):
        self.d['operations']=[dict(id='OP1',work_order_id='W1',process='装配',started='2026-09-25T08:00:00',finished=None)]
        p=self.row()['_work_orders'][0]['processes'][0]
        self.assertEqual((p['event_count'],p['active_events'],p['completed_events']),(1,1,0))
    def test_invalid_filters_fail_and_unknown_customer_never_returns_everyone(self):
        for query in [{'bad':'x'},{'stage':'garbage'},{'due_from':'2026-13-40'},{'due_from':'2026-10-02','due_to':'2026-10-01'}]:
            with self.assertRaises(ValueError):delivery.filters(query)
        rows,facets=delivery.select(delivery.build(self.d),delivery.filters({'customer_id':'NO-SUCH-ID'}))
        self.assertEqual(rows,[]);self.assertEqual(facets['all'],0);self.assertIsNone(delivery.summary(rows)['otif_pct'])

class DeliveryApiTests(PlatformCase):
    def setUp(self):
        super().setUp();self.rows=delivery.build(fixture());self.patcher=patch('app.delivery.rows',return_value=self.rows);self.patcher.start();self.addCleanup(self.patcher.stop);self.client.force_login(self.admin)
    def payload(self,version=0):return dict(status='处理中',owner='模拟计划责任人',note='测试模拟协调记录，不改动业务原件。',due_date='2026-10-05',version=version)
    def test_auth_and_read_only_identity_cannot_write(self):
        self.assertEqual(Client().get('/api/delivery').status_code,401)
        self.quality.groups.clear();self.client.force_login(self.quality)
        self.assertEqual(self.client.get('/api/delivery').status_code,200)
        self.assertEqual(self.post('/api/delivery/L1/follow-up',self.payload()).status_code,403)
    def test_quality_role_gets_no_financial_fields_and_sources_are_visible(self):
        self.client.force_login(self.quality);r=self.client.get('/api/delivery/L1');self.assertEqual(r.status_code,200)
        self.assertNotIn('cents',r.content.decode());self.assertIn('order_lines',[x['dataset'] for x in r.json()['sources']])
        self.assertEqual(r.json()['unit_total'],2)
    def test_filtered_export_matches_table_population_and_quotes_formula_cells(self):
        self.rows[0]['customer']='=UNTRUSTED()'
        body=self.client.get('/api/delivery?customer_id=C1&stage=all').json()
        response=self.client.get('/api/delivery/export?customer_id=C1&stage=all')
        parsed=list(csv.reader(io.StringIO(response.content.decode('utf-8-sig'))));self.assertEqual(len(parsed)-4,body['total'])
        self.assertEqual(parsed[4][2],"'=UNTRUSTED()")
        empty=self.client.get('/api/delivery/export?customer_id=UNKNOWN').content.decode('utf-8-sig');self.assertNotIn('L1',empty)
    def test_followup_is_audited_versioned_and_does_not_change_facts(self):
        count=Record.objects.count();r=self.post('/api/delivery/L1/follow-up',self.payload());self.assertEqual(r.status_code,200);self.assertEqual(r.json()['follow_up']['version'],1)
        self.assertEqual(self.post('/api/delivery/L1/follow-up',self.payload()).status_code,409)
        r=self.post('/api/delivery/L1/follow-up',self.payload(1));self.assertEqual(r.json()['follow_up']['version'],2)
        self.assertEqual(Record.objects.count(),count);self.assertEqual(AuditEvent.objects.filter(action='delivery.followup').count(),2)
        self.assertEqual(self.client.get('/api/delivery/L1').json()['follow_up']['owner'],'模拟计划责任人')
    def test_followup_rejects_bad_payload_and_requires_csrf(self):
        for edits in [{'version':True},{'due_date':'bad'},{'owner':''},{'note':'短'},{'status':'直接放行'}]:
            self.assertEqual(self.post('/api/delivery/L1/follow-up',{**self.payload(),**edits}).status_code,400)
        c=Client(enforce_csrf_checks=True);c.force_login(self.admin)
        self.assertEqual(c.post('/api/delivery/L1/follow-up',json.dumps(self.payload()),content_type='application/json').status_code,403)
    def test_audit_failure_rolls_back_note(self):
        with patch('app.delivery_views.AuditEvent.objects.create',side_effect=RuntimeError('audit failed')):
            with self.assertRaises(RuntimeError):self.post('/api/delivery/L1/follow-up',self.payload())
        self.assertFalse(IssueDisposition.objects.filter(key='delivery:L1').exists())
    def test_unit_filter_pagination_and_missing_order(self):
        r=self.client.get('/api/delivery/L1?unit_stage=ready').json();self.assertEqual(r['unit_total'],0);self.assertEqual(r['unit_rows'],[])
        self.assertEqual(self.client.get('/api/delivery/NONE').status_code,404)
        self.assertEqual(self.client.get('/api/delivery/L1?unit_stage=bad').status_code,400)
        r=self.client.get('/api/delivery/L1?unit_page=2').json();self.assertEqual(r['unit_total'],2);self.assertEqual(r['unit_rows'],[])
