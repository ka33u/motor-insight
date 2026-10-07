import csv,io,json
from copy import deepcopy
from unittest.mock import patch
from django.test import SimpleTestCase,Client
from django.contrib.auth.models import User
from app import supply,analytics
from app.schema import SCHEMAS
from app.models import Record,IssueDisposition,AuditEvent
from tests.test_platform import PlatformCase

def fixture():
    d={k:[] for k in SCHEMAS}
    d['employees']=[{'id':'E1'}];d['work_orders']=[{'id':'W1'}];d['suppliers']=[{'id':'S1','name':'模拟供方'}]
    d['materials']=[dict(id='M1',name='线材',spec='1.0',category='铜线',unit='kg',safety_qty=5,unit_cost_cents=500,supplier_id='S1'),dict(id='M2',name='轴承',spec='6205',category='轴承',unit='件',safety_qty=2,unit_cost_cents=900,supplier_id='S1')]
    d['inventory_opening']=[dict(id='O1',material_id='M1',lot='L1',location='A1',as_of='2026-09-01',qty=10,unit_cost_cents=500,status='冻结')]
    d['inventory_status_events']=[dict(id='E1',material_id='M1',lot='L1',location='A1',occurred='2026-09-02T08:00:00',from_status='冻结',to_status='可用',approver_id='E1',reason='复核')]
    d['inventory_movements']=[dict(id='V1',material_id='M1',lot='L1',location='A1',occurred='2026-09-03T08:00:00',movement='生产领料',qty_signed=-3.2,work_order_id='W1',reference='W1'),dict(id='V2',material_id='M1',lot='L2',location='A2',occurred='2026-09-05T14:00:00',movement='采购入库',qty_signed=4,work_order_id=None,reference='R1')]
    d['purchase_lines']=[dict(id='P1',material_id='M1',supplier_id='S1',ordered='2026-09-01',due='2026-09-05',qty=10,unit_price_cents=500,status='部分到货'),dict(id='P2',material_id='M2',supplier_id='S1',ordered='2026-09-01',due='2026-10-01',qty=2,unit_price_cents=900,status='未到货')]
    d['receipts']=[dict(id='R1',purchase_line_id='P1',material_id='M1',lot='L2',qty=4,received='2026-09-05T09:00:00',certificate='CZ1',status='检验合格'),dict(id='R2',purchase_line_id='P1',material_id='M1',lot='L3',qty=2,received='2026-09-06T09:00:00',certificate='CZ2',status='隔离')]
    d['incoming_inspections']=[dict(id='I1',receipt_id='R1',sample_size=2,defect_count=0,inspected='2026-09-05T12:00:00',result='合格',inspector_id='E1',disposition='批准入库'),dict(id='I2',receipt_id='R2',sample_size=2,defect_count=1,inspected='2026-09-06T12:00:00',result='不合格',inspector_id='E1',disposition='隔离待退货')]
    return d

class SupplyFactsTests(SimpleTestCase):
    def setUp(self):self.d=fixture()
    def data(self):return supply.SupplyData(self.d)
    def test_receipt_approval_and_posting_never_double_count_stock(self):
        d=self.data();r=d.stock_index['M1'];p=d.po_index['P1']
        self.assertEqual((r['balance_qty'],r['usable_state_qty']),(10.8,10.8));self.assertEqual((p['received_qty'],p['approved_qty'],p['putaway_qty'],p['remaining_qty']),(6,4,4,4));self.assertEqual(p['quality_pending_receipts'],1)
    def test_missing_inventory_is_unknown_not_zero(self):
        r=self.data().stock_index['M2'];self.assertIsNone(r['balance_qty']);self.assertIsNone(r['safety_gap']);self.assertIn('attention',r['flags']);self.assertNotIn('low',r['flags'])
    def test_due_today_not_overdue_or_in_denominator(self):
        d=self.data();self.assertEqual(d.po_index['P2']['due_count'],0);self.assertNotIn('overdue',d.po_index['P2']['flags']);self.assertEqual(supply.summary(d.po_rows,'purchase')['due'],1)
    def test_duplicate_opening_does_not_sum_snapshots(self):
        self.d['inventory_opening'].append({**self.d['inventory_opening'][0],'id':'O2'})
        r=self.data().stock_index['M1'];self.assertIsNone(r['balance_qty']);self.assertIsNone(r['usable_state_qty'])
    def test_before_opening_movement_invalidates_balance(self):
        self.d['inventory_movements'][0]['occurred']='2026-08-31T10:00:00';r=self.data().stock_index['M1'];self.assertIsNone(r['balance_qty'])
    def test_state_chain_and_approval_identity_guard_available_stock(self):
        self.d['inventory_status_events'][0]['from_status']='可用';r=self.data().stock_index['M1'];self.assertIsNone(r['usable_state_qty']);self.assertTrue(any('状态链' in x for x in r['issues']))
        self.d=fixture();self.d['inventory_status_events'][0]['approver_id']='UNKNOWN';self.assertIsNone(self.data().stock_index['M1']['usable_state_qty'])
    def test_frozen_consumption_and_same_time_unlock_are_flagged(self):
        for timestamp in ['2026-09-01T09:00:00','2026-09-02T08:00:00']:
            self.d=fixture();self.d['inventory_movements'][0]['occurred']=timestamp;self.assertIsNone(self.data().stock_index['M1']['usable_state_qty'])
    def test_future_events_do_not_change_current_stock_or_receipts(self):
        self.d['inventory_movements'].append({**self.d['inventory_movements'][0],'id':'F','occurred':'2026-10-03T08:00:00','qty_signed':-99})
        self.d['receipts'].append({**self.d['receipts'][0],'id':'RF','received':'2026-10-03T08:00:00','qty':100})
        self.assertEqual(self.data().stock_index['M1']['balance_qty'],10.8);self.assertEqual(self.data().po_index['P1']['received_qty'],6)
    def test_latest_iqc_not_sum_and_posting_at_time_requires_approval(self):
        self.d['incoming_inspections'].append({**self.d['incoming_inspections'][0],'id':'I3','inspected':'2026-09-05T13:00:00'})
        self.assertEqual(self.data().po_index['P1']['approved_qty'],4)
        self.d['inventory_movements'][1]['occurred']='2026-09-05T10:00:00';d=self.data();self.assertIn('attention',d.po_index['P1']['flags']);self.assertIsNone(d.stock_index['M1']['usable_state_qty'])
    def test_wrong_lot_and_excess_putaway_not_accepted_silently(self):
        for changed in [{'lot':'BAD'},{'qty_signed':8}]:
            self.d=fixture();self.d['inventory_movements'][1].update(changed);self.assertIn('attention',self.data().po_index['P1']['flags'])
    def test_one_receipt_split_across_two_locations_is_counted_once(self):
        self.d['inventory_movements'][1]['qty_signed']=1.5;self.d['inventory_movements'].append({**self.d['inventory_movements'][1],'id':'V3','location':'A3','qty_signed':2.5})
        d=self.data();self.assertEqual(d.po_index['P1']['putaway_qty'],4);self.assertEqual(d.stock_index['M1']['balance_qty'],10.8)
    def test_negative_running_and_fractional_pieces_block_available(self):
        self.d['inventory_movements'][0]['qty_signed']=-20;self.assertIsNone(self.data().stock_index['M1']['usable_state_qty'])
        self.d=fixture();self.d['materials'][0]['unit']='件';self.assertIsNone(self.data().stock_index['M1']['usable_state_qty'])
    def test_cancelled_open_purchase_has_no_remaining_or_due(self):
        self.d['purchase_lines'][1].update(status='已取消',due='2026-09-02');r=self.data().po_index['P2'];self.assertEqual((r['remaining_qty'],r['due_count']),(0,0))
    def test_empty_scopes_and_mismatched_supplier_filters(self):
        d=self.data();self.assertEqual(supply.cohort(d,supply.filters({'q':'absent'})),[]);self.assertIsNone(supply.summary([],'purchase')['ontime_rate'])
        for query in [{'supplier_id':'S1'},{'tab':'fake'},{'date':'2026-09-02'},{'stage':'bad'}]:
            with self.assertRaises(ValueError):supply.filters(query)
    def test_sources_include_required_receipt_and_inspection(self):
        d=self.data().detail('material','M1');sources={(r['dataset'],r['key']) for r in d['sources']};self.assertIn(('incoming_inspections','I2'),sources);self.assertIn(('receipts','R2'),sources);self.assertEqual(len(d['sources']),len(sources))

class SupplyApiTests(PlatformCase):
    def setUp(self):
        super().setUp();self.d=fixture()
        for ds,rows in self.d.items():
            for r in rows:self.record(ds,r)
        analytics._tables.cache_clear();supply.cached.cache_clear();self.addCleanup(analytics._tables.cache_clear);self.addCleanup(supply.cached.cache_clear);self.client.force_login(self.quality)
    def payload(self):return dict(status='催交中',owner='模拟采购岗位',note='核对采购承诺与未到货明细',due_date='2026-10-06',version=0,data_revision=list(analytics.revision()))
    def test_summary_separate_from_list_and_units_never_merge(self):
        d=self.client.get('/api/supply?stage=attention').json();self.assertEqual(d['summary']['objects'],2);self.assertEqual(d['total'],1);self.assertEqual({r['unit'] for r in d['unit_totals']},{'kg','件'})
        self.assertIsNone(next(r for r in d['unit_totals'] if r['unit']=='件')['balance_qty'])
    def test_empty_unknown_material_and_supplier_never_fall_back(self):
        for q in ['material_id=NONE','tab=purchase&supplier_id=NONE','q=MISSING']:
            d=self.client.get('/api/supply?'+q).json();self.assertEqual(d['total'],0);self.assertEqual(d['summary']['objects'],0)
    def test_safety_multiple_excludes_unknown_inventory_and_zero_denominator(self):
        d=self.client.get('/api/supply').json();by={r['category']:r for r in d['categories']};self.assertAlmostEqual(by['铜线']['minimum_multiple'],2.16);self.assertIsNone(by['轴承']['minimum_multiple'])
        r=Record.objects.get(dataset='materials',business_key='M1');r.values['safety_qty']=0;r.save();d=self.client.get('/api/supply').json();self.assertIsNone(next(r for r in d['categories'] if r['category']=='铜线')['median_multiple'])
    def test_export_uses_filtered_objects_not_page(self):
        q='tab=purchase&stage=quality&page=9';d=list(csv.reader(io.StringIO(self.client.get('/api/supply/export?'+q).content.decode('utf-8-sig'))));self.assertEqual(len(d)-3,1);self.assertEqual(d[3][0],'P1')
    def test_detail_and_evidence_do_not_leak_prices(self):
        for url in ['/api/supply','/api/supply/material/M1','/api/supply/purchase/P1']:
            r=self.client.get(url);self.assertEqual(r.status_code,200);self.assertNotIn('cents',r.content.decode())
        r=self.client.get('/api/supply/material/M1/evidence').json();self.assertFalse(r['can_download_original']);self.assertTrue(r['total']>0)
        self.assertEqual(Client().get('/api/supply').status_code,401);self.assertEqual(self.client.get('/api/supply/material/UNKNOWN').status_code,404)
    def test_ledger_keeps_running_balance_across_pages(self):
        r=supply.current().stock_index['M1']['_lots'][0];d=self.client.get('/api/supply/ledger/'+r['id']).json();self.assertEqual([x['running_qty'] for x in d['rows']],[10,6.8]);self.assertEqual(d['rows'][0]['qty_signed'],0)
        self.assertEqual(self.client.get('/api/supply/ledger/'+r['id']+'?page=99').json()['rows'],[])
    def test_followup_version_source_guard_and_no_mutated_business_facts(self):
        before=list(Record.objects.values_list('values',flat=True));p=self.payload();r=self.post('/api/supply/purchase/P1/follow-up',p);self.assertEqual(r.status_code,200);self.assertEqual(r.json()['follow_up']['version'],1)
        self.assertEqual(self.post('/api/supply/purchase/P1/follow-up',p).status_code,409);p.update(version=1,data_revision=[0,'stale']);self.assertEqual(self.post('/api/supply/purchase/P1/follow-up',p).status_code,409)
        self.assertEqual(list(Record.objects.values_list('values',flat=True)),before);self.assertEqual(len(self.client.get('/api/supply/purchase/P1/history').json()['rows']),1)
    def test_role_csrf_and_audit_rollback(self):
        user=User.objects.create_user('readonly');self.client.force_login(user);self.assertEqual(self.post('/api/supply/purchase/P1/follow-up',self.payload()).status_code,403)
        c=Client(enforce_csrf_checks=True);c.force_login(self.quality);self.assertEqual(c.post('/api/supply/purchase/P1/follow-up','{}',content_type='application/json').status_code,403)
        self.client.force_login(self.quality)
        with patch('app.supply_views.AuditEvent.objects.create',side_effect=RuntimeError('audit failed')):
            with self.assertRaises(RuntimeError):self.post('/api/supply/purchase/P1/follow-up',self.payload())
        self.assertEqual(IssueDisposition.objects.count(),0)
    def test_formula_escaping_on_export(self):
        r=Record.objects.get(dataset='materials',business_key='M1');r.values['name']='=CMD()';r.save();result=list(csv.reader(io.StringIO(self.client.get('/api/supply/export').content.decode('utf-8-sig'))));self.assertEqual(result[3][1],"'=CMD()")
