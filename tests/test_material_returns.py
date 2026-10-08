from copy import deepcopy
from decimal import Decimal
import hashlib
from unittest.mock import patch
from django.test import SimpleTestCase
from django.contrib.auth.models import User,Group
from app import material_returns as engine,material_planning as planning,supply,analytics
from app.models import Record,AuditEvent
from .test_material_planning import fixture,issue
from .test_platform import PlatformCase

def returned(key='T1',qty=1,**changes):
    return dict(issue(qty=qty,key=key,stamp='2026-09-21T09:00:00'),movement='生产退料',reference='I1') | changes

def data():
    value=fixture();value['inventory_movements']=[issue(),returned()];return value

class ReturnRules(SimpleTestCase):
    def calc(self,value=None):return planning.MaterialPlanning(value or data(),planning.filters({'stock_policy':'all_usable'}))
    def report(self,value):return engine.reconcile(value,analytics.AS_OF)
    def test_netting_and_stock_each_once(self):
        result=self.calc();item=result.orders['W1']['items'][0]
        self.assertEqual([item[k] for k in ('gross_issued_qty','returned_qty','issued_qty','remaining_required')],[2,1,1,3])
        self.assertEqual(result.material_rows['M1']['initial_pool'],9)
        self.assertEqual(result.pool['M1'],4)
    def test_pending_destination_not_usable(self):
        value=data();value['inventory_movements'][1]['location']='QC'
        value['inventory_opening'].append(dict(value['inventory_opening'][0],id='O3',location='QC',qty=0,status='待检'))
        result=self.calc(value);item=result.orders['W1']['items'][0]
        self.assertEqual((item['issued_qty'],item['remaining_required']),(1,3))
        self.assertEqual(result.material_rows['M1']['initial_pool'],8)
        lot=result.stock.lot_index[supply.lot_id(('M1','L1','QC'))]
        self.assertEqual((lot['balance_qty'],lot['usable_state_qty']),(1,0))
    def test_multiple_returns_and_exact_cap(self):
        value=data();value['inventory_movements']+=[returned('T2',Decimal('0.7')),returned('T3',Decimal('0.3'))]
        report=self.report(value);self.assertEqual(report['by_issue']['I1']['net_issued_qty'],'0')
        self.assertTrue(all(r['verified'] for r in report['returns'].values()))
    def test_overreturn_pauses_whole_group_without_clipping(self):
        value=data();value['inventory_movements']+=[returned('T2',1.001)]
        report=self.report(value);self.assertFalse(report['by_issue']['I1']['verified'])
        self.assertTrue(all(r['issues'] for r in report['returns'].values()))
        result=self.calc(value);item=result.orders['W1']['items'][0]
        self.assertEqual(result.orders['W1']['state'],'attention');self.assertIsNone(item['issued_qty']);self.assertIsNone(item['remaining_required']);self.assertIsNone(item['gross_issued_qty'])
    def test_one_bad_sibling_does_not_leave_partial_credit(self):
        value=data();value['inventory_movements']+=[returned('T2',-1)]
        report=self.report(value);self.assertFalse(report['returns']['T1']['verified']);self.assertIn('未部分抵扣',report['returns']['T1']['issues'][0])
    def test_identity_mismatch_blocks_origin_and_declared_work(self):
        for changes in ({'work_order_id':'W2'},{'material_id':'M2'},{'lot':'OTHER'}):
            with self.subTest(changes=changes):
                value=data();value['inventory_movements'][1].update(changes)
                self.assertFalse(self.report(value)['returns']['T1']['verified'])
                result=self.calc(value);self.assertEqual(result.orders['W1']['state'],'attention')
                self.assertTrue(result.detail('orders','W1')['return_reconciliation']['rows'])
    def test_different_location_allowed_with_same_lot(self):
        value=data();value['inventory_movements'][1]['location']='OTHER'
        self.assertTrue(self.report(value)['returns']['T1']['verified'])
        self.assertEqual(self.calc(value).orders['W1']['state'],'attention')
    def test_missing_or_nonissue_reference(self):
        for reference in ('UNKNOWN','W1','T1'):
            value=data();value['inventory_movements'][1]['reference']=reference
            self.assertFalse(self.report(value)['returns']['T1']['verified'])
            self.assertEqual(self.calc(value).orders['W1']['state'],'attention')
    def test_strict_time_and_cutoff(self):
        value=data()
        for when in ('2026-09-19T08:00:00','2026-09-20T08:00:00'):
            value['inventory_movements'][1]['occurred']=when;self.assertFalse(self.report(value)['returns']['T1']['verified'])
        value['inventory_movements'][1]['occurred']='2026-10-02T08:00:00'
        self.assertFalse(self.report(value)['returns']);self.assertEqual(self.calc(value).orders['W1']['items'][0]['issued_qty'],2)
    def test_invalid_time_and_quantity_not_zero(self):
        for changes in ({'occurred':'bad'},{'occurred':'2026-09-21T09:00:00+00:00'},{'qty_signed':0},{'qty_signed':True},{'qty_signed':float('nan')},{'qty_signed':float('inf')}):
            with self.subTest(changes=changes):
                value=data();value['inventory_movements'][1].update(changes)
                self.assertFalse(self.report(value)['returns']['T1']['verified'])
    def test_original_direction_reference_and_work_must_match(self):
        for changes in ({'qty_signed':2},{'reference':'OTHER'},{'work_order_id':'UNKNOWN'}):
            value=data();value['inventory_movements'][0].update(changes)
            self.assertFalse(self.report(value)['returns']['T1']['verified'])
    def test_piece_quantity_and_decimal_no_hidden_rounding(self):
        value=data();value['materials'][0]['unit']='件';value['inventory_movements'][1]['qty_signed']=0.5
        self.assertFalse(self.report(value)['returns']['T1']['verified'])
        value=data();value['inventory_movements'][0]['qty_signed']=-0.3;value['inventory_movements'][1]['qty_signed']=0.1;value['inventory_movements']+=[returned('T2',0.2)]
        self.assertEqual(self.report(value)['by_issue']['I1']['net_issued_qty'],'0')
    def test_original_stock_uncertainty_propagates_to_return_location(self):
        value=data();value['inventory_opening'][0]['status']='冻结';value['inventory_movements'][1]['location']='NEW'
        value['inventory_opening'].append(dict(value['inventory_opening'][0],id='O3',location='NEW',qty=0,status='可用'))
        result=self.calc(value);lot=result.stock.lot_index[supply.lot_id(('M1','L1','NEW'))]
        self.assertIsNone(lot['usable_state_qty']);self.assertEqual(result.orders['W1']['state'],'attention')
    def test_source_indices_include_both_sides_of_wrong_material(self):
        value=data();value['inventory_movements'][1]['material_id']='M2';result=self.calc(value)
        for kind,key in [('orders','W1'),('materials','M1')]:
            refs={(r['dataset'],r['key']) for r in result.detail(kind,key)['sources']}
            self.assertIn(('inventory_movements','T1'),refs);self.assertIn(('inventory_movements','I1'),refs)
    def test_closed_order_keeps_return_evidence_without_new_demand(self):
        value=data();value['work_orders'][0]['status']='已取消';result=self.calc(value)
        self.assertTrue(result.orders['W1']['excluded']);self.assertFalse(result.orders['W1']['items'])
        self.assertEqual(len(result.detail('orders','W1')['return_reconciliation']['rows']),1)
    def test_no_returns_preserves_old_net_definition(self):
        value=data();value['inventory_movements'].pop();result=self.calc(value);item=result.orders['W1']['items'][0]
        self.assertEqual((item['gross_issued_qty'],item['returned_qty'],item['issued_qty']),(2,0,2))
    def test_pure_stable_order_and_duplicate_identity(self):
        value=data();before=deepcopy(value);expected=self.report(value);self.assertEqual(value,before)
        value['inventory_movements'].reverse();self.assertEqual(self.report(value),expected)
        value['inventory_movements'].append(deepcopy(value['inventory_movements'][0]))
        with self.assertRaises(ValueError):self.report(value)

class ReturnAPI(PlatformCase):
    def setUp(self):
        super().setUp()
        for dataset,rows in data().items():
            for row in rows:self.record(dataset,row)
        analytics._tables.cache_clear();supply.cached.cache_clear()
        self.addCleanup(analytics._tables.cache_clear);self.addCleanup(supply.cached.cache_clear);self.client.force_login(self.admin)
    def receipt(self):
        response=self.client.get('/api/material-planning?stock_policy=all_usable');self.assertEqual(response.status_code,200,response.content);return response.json()['receipt']
    def url(self,suffix='',receipt=None):return '/api/material-planning/orders/W1'+suffix+'?stock_policy=all_usable&receipt='+(receipt or self.receipt())
    def test_detail_netting_and_excel_sources(self):
        response=self.client.get(self.url());self.assertEqual(response.status_code,200,response.content)
        result=response.json();self.assertEqual(result['row']['items'][0]['issued_qty'],1);self.assertEqual(result['return_reconciliation']['rows'][0]['issue']['id'],'I1')
        sources=self.client.get(self.url('/evidence')).json()['rows'];source=Record.objects.get(dataset='inventory_movements',business_key='T1').source_row
        self.assertTrue(any(r['key']=='T1' and r['row']==source.row_number and r['sheet']==source.sheet for r in sources))
    def test_full_order_csv_audit_and_fact_preservation(self):
        before=list(Record.objects.values());response=self.client.get(self.url('/issue-returns.csv')+'&stage=short')
        self.assertEqual(response.status_code,200,response.content);self.assertIn('T1',response.content.decode('utf-8-sig'));self.assertIn('累计领料',response.content.decode('utf-8-sig'))
        self.assertEqual(AuditEvent.objects.latest('id').detail['file_sha256'],hashlib.sha256(response.content).hexdigest());self.assertEqual(list(Record.objects.values()),before)
    def test_auth_permissions_no_money_and_stale_receipt(self):
        for name in ('admin','analyst','quality','operations','finance','viewer'):
            user=User.objects.create_user('return_'+name);user.groups.add(Group.objects.get_or_create(name=name)[0]);self.client.force_login(user)
            response=self.client.get(self.url('/issue-returns.csv'));self.assertEqual(response.status_code,200,response.content);self.assertNotIn('cents',response.content.decode());self.assertNotIn('12345',response.content.decode())
        receipt=self.receipt();row=Record.objects.get(dataset='inventory_movements',business_key='T1');row.revision+=1;row.save()
        self.assertEqual(self.client.get(self.url('/issue-returns.csv',receipt)).status_code,409)
        self.client.logout();self.assertEqual(self.client.get(self.url('/issue-returns.csv',receipt)).status_code,401)
    def test_export_requires_receipt_and_rolls_back_audit_failure(self):
        self.assertEqual(self.client.get('/api/material-planning/orders/W1/issue-returns.csv').status_code,400)
        url=self.url('/issue-returns.csv');before=AuditEvent.objects.count()
        with patch('app.material_planning_views.AuditEvent.objects.create',side_effect=ValueError('Unavailable')):
            self.assertEqual(self.client.get(url).status_code,400)
        self.assertEqual(AuditEvent.objects.count(),before)
