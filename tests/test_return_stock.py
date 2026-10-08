from copy import deepcopy
import csv,hashlib,io,json
from unittest.mock import patch
from django.test import SimpleTestCase
from django.contrib.auth.models import User,Group
from app import analytics,supply,return_stock as engine
from app.models import Record,AuditEvent
from .test_platform import PlatformCase
from .test_material_returns import data,returned
from .test_material_planning import issue


def fixture():
    value=data();value['inventory_movements'][1]['location']='QC'
    value['inventory_opening'].append(dict(value['inventory_opening'][0],id='O3',location='QC',qty=0,status='待检'))
    return value


def event(key='E1',when='2026-09-22T09:00:00',old='待检',new='可用',location='QC'):
    return dict(id=key,material_id='M1',lot='L1',location=location,occurred=when,from_status=old,to_status=new,reason='模拟状态登记',approver_id='E1')


class ReturnStockRules(SimpleTestCase):
    def calc(self,value=None):return engine.ReturnStock(supply.SupplyData(fixture() if value is None else value))
    def test_pending_return_and_release_are_separate_axes(self):
        value=fixture();pending=self.calc(value);r=pending.index['T1']
        self.assertTrue(r['document_verified']);self.assertEqual((r['arrival_state'],r['current_state']),('待检','待检'))
        self.assertEqual(pending.units(pending.rows)[0]['target_usable_qty'],0)
        value['inventory_status_events']=[event()];released=self.calc(value);r=released.index['T1']
        self.assertEqual((r['arrival_state'],r['current_state']),('待检','可用'));self.assertEqual(released.units(released.rows)[0]['target_usable_qty'],1)
    def test_isolation_frozen_and_return_to_supplier_remain_restricted(self):
        for state in ('隔离','冻结','待退货'):
            value=fixture();value['inventory_status_events']=[event(new=state)];d=self.calc(value)
            self.assertIn('restricted',d.rows[0]['flags']);self.assertEqual(d.units(d.rows)[0]['target_usable_qty'],0)
    def test_shared_destination_deduplicated_but_returns_not_lost(self):
        value=fixture();value['inventory_movements']+=[returned('T2',1,location='QC')];value['inventory_status_events']=[event()]
        d=self.calc(value);s=d.summary(d.rows);u=d.units(d.rows)[0]
        self.assertEqual((s['returns'],s['target_lots']),(2,1));self.assertEqual((u['returned_qty'],u['target_balance_qty'],u['target_usable_qty']),(2,2,2))
    def test_later_issue_changes_lot_balance_not_return_quantity(self):
        value=fixture();value['inventory_status_events']=[event()]
        value['inventory_movements']+=[dict(issue(key='I2',qty=-0.4,stamp='2026-09-23T08:00:00'),location='QC')]
        d=self.calc(value);u=d.units(d.rows)[0]
        self.assertEqual((u['returned_qty'],u['target_balance_qty'],u['target_usable_qty']),(1,0.6,0.6))
    def test_preexisting_destination_stock_not_assigned_to_return(self):
        value=fixture();value['inventory_opening'][-1]['qty']=4;d=self.calc(value);u=d.units(d.rows)[0]
        self.assertEqual((u['returned_qty'],u['target_balance_qty']),(1,5))
    def test_bad_status_chain_is_unknown_not_zero_or_released(self):
        value=fixture();value['inventory_status_events']=[event(old='冻结')];d=self.calc(value);r=d.rows[0]
        self.assertTrue(r['document_verified']);self.assertIsNone(r['current_state']);self.assertEqual(r['recorded_state'],'可用')
        self.assertEqual(r['arrival_state'],'待检');self.assertIsNone(d.units(d.rows)[0]['target_usable_qty']);self.assertEqual(d.units(d.rows)[0]['unknown_lots'],1)
    def test_same_instant_arrival_unknown_but_current_state_can_be_known(self):
        value=fixture();value['inventory_status_events']=[event(when=value['inventory_movements'][1]['occurred'])];r=self.calc(value).rows[0]
        self.assertIsNone(r['arrival_state']);self.assertEqual(r['current_state'],'可用');self.assertIn('attention',r['flags']);self.assertIn('available',r['flags'])
    def test_multiple_same_instant_statuses_do_not_guess_by_id(self):
        value=fixture();value['inventory_status_events']=[event('S1'),event('S2',old='可用',new='冻结')];d=self.calc(value)
        self.assertIsNone(d.rows[0]['current_state']);self.assertTrue(any('同刻' in e for e in d.rows[0]['current_issues']))
        value['inventory_status_events'].reverse();self.assertEqual(self.calc(value).rows,d.rows)
    def test_origin_state_ambiguity_taints_every_return_to_shared_target(self):
        value=fixture();value['inventory_status_events']=[event('S1',old='可用',new='冻结',location='A1'),event('S2',old='冻结',new='可用',location='A1')]
        d=self.calc(value);r=d.rows[0];self.assertIsNone(r['current_state']);self.assertFalse(d.details['T1']['target_lot']['verified']);self.assertIsNone(d.units(d.rows)[0]['target_usable_qty'])
    def test_future_event_and_future_return_do_not_leak(self):
        value=fixture();value['inventory_status_events']=[event(when='2026-10-02T09:00:00')]
        value['inventory_movements']+=[returned('FUTURE',1,occurred='2026-10-02T08:00:00',location='QC')]
        d=self.calc(value);self.assertEqual(len(d.rows),1);self.assertEqual(d.rows[0]['current_state'],'待检');self.assertFalse(d.details['T1']['target_lot']['status_events'])
    def test_unknown_document_suspends_return_total_preserves_raw_rows(self):
        value=fixture();value['inventory_movements']+=[returned('T2',2,location='QC')];d=self.calc(value)
        self.assertEqual([r['qty_signed'] for r in d.rows],[2,1]);self.assertIsNone(d.units(d.rows)[0]['returned_qty']);self.assertTrue(all(not r['document_verified'] for r in d.rows))
    def test_units_never_combined_and_wrong_material_keeps_original_unit(self):
        value=fixture();value['inventory_movements'] += [issue(mid='M2',key='I2'),returned('T2',1,material_id='M2',lot='L2',location='A2',reference='I2')]
        d=self.calc(value);self.assertEqual({u['unit'] for u in d.units(d.rows)},{'件','kg'})
        value['inventory_movements'][1]['material_id']='M2';d=self.calc(value);self.assertEqual(d.details['T1']['original_unit'],'kg');self.assertEqual(d.details['T1']['row']['unit'],'件')
    def test_scope_exact_ids_search_original_work_and_stage_cohort(self):
        value=fixture();value['inventory_movements'][1]['work_order_id']='W2';d=self.calc(value)
        self.assertEqual(len(d.cohort(engine.filters({'work_order_id':'W1'}))),1)
        self.assertEqual(len(d.cohort(engine.filters({'q':'i1'}))),1)
        self.assertFalse(d.cohort(engine.filters({'material_id':'M'})))
        f=engine.filters({'stage':'available'});self.assertEqual(len(d.cohort(f)),1);self.assertFalse(d.selected(f))
    def test_sources_include_both_lots_events_and_registered_people(self):
        value=fixture();value['inventory_status_events']=[event()];d=self.calc(value)
        refs={(r['dataset'],r['key']) for r in d.details['T1']['sources']}
        self.assertTrue({('inventory_opening','O1'),('inventory_opening','O3'),('inventory_movements','I1'),('inventory_movements','T1'),('inventory_status_events','E1'),('employees','E1')}<=refs)
        self.assertNotIn('cents',json.dumps(d.details));self.assertNotIn('12345',json.dumps(d.details))
    def test_empty_pure_and_existing_inventory_unmodified(self):
        value=fixture();stock=supply.SupplyData(value);before=deepcopy(stock.__dict__);d=engine.ReturnStock(stock)
        self.assertEqual(stock.__dict__,before);self.assertTrue(d.rows)
        value['inventory_movements']=[];d=self.calc(value);self.assertFalse(d.rows);self.assertFalse(d.units([]));self.assertEqual(d.summary([])['returns'],0)
    def test_purchase_in_origin_lot_retains_receipt_and_inspection_sources(self):
        value=fixture()
        value['purchase_lines']=[dict(id='PO',material_id='M1',supplier_id='S1',ordered='2026-09-01',due='2026-09-15',qty=2,status='已到货')]
        value['receipts']=[dict(id='R',purchase_line_id='PO',material_id='M1',lot='L1',qty=2,received='2026-09-15T08:00:00',certificate='X',status='检验合格')]
        value['incoming_inspections']=[dict(id='Q',receipt_id='R',sample_size=1,defect_count=0,inspected='2026-09-15T09:00:00',result='合格',disposition='批准入库',inspector_id='E1')]
        value['inventory_movements'] += [dict(issue(key='IN',qty=2,stamp='2026-09-15T10:00:00'),movement='采购入库',reference='R',work_order_id=None)]
        d=self.calc(value);refs={(r['dataset'],r['key']) for r in d.details['T1']['sources']}
        self.assertTrue({('receipts','R'),('purchase_lines','PO'),('incoming_inspections','Q'),('suppliers','S1'),('employees','E1')}<=refs)
        self.assertTrue(d.rows[0]['current_verified'])
    def test_receipt_covers_stage_and_code_but_not_page(self):
        f=engine.filters({});a=engine.receipt(f,[1]);self.assertEqual(a,engine.receipt(engine.filters({'page':'2'}),[1]))
        self.assertNotEqual(a,engine.receipt(engine.filters({'stage':'restricted'}),[1]));self.assertNotEqual(a,engine.receipt(f,[2]))
        for query in ({'stage':'bad'},{'q':'x'*151},{'unsupported':'x'}):
            with self.assertRaises(ValueError):engine.filters(query)


class ReturnStockAPI(PlatformCase):
    def setUp(self):
        super().setUp();value=fixture();value['inventory_status_events']=[event()]
        value['inventory_movements'] += [returned('T2',1,location='QC')]
        for ds,rows in value.items():
            for r in rows:self.record(ds,r)
        analytics._tables.cache_clear();supply.cached.cache_clear();self.addCleanup(analytics._tables.cache_clear);self.addCleanup(supply.cached.cache_clear);self.client.force_login(self.admin)
    def board(self,query=''):
        r=self.client.get('/api/return-stock'+query);self.assertEqual(r.status_code,200,r.content);return r.json()
    def test_board_detail_and_exact_source_line(self):
        d=self.board();self.assertEqual((d['summary']['returns'],d['summary']['target_lots']),(2,1))
        q='?receipt='+d['receipt'];r=self.client.get('/api/return-stock/rows/T1'+q);self.assertEqual(r.status_code,200);self.assertEqual(r['Cache-Control'],'no-store')
        sources=self.client.get('/api/return-stock/rows/T1/evidence'+q).json()['rows'];raw=Record.objects.get(dataset='inventory_movements',business_key='T1').source_row
        self.assertTrue(any(x['key']=='T1' and x['row']==raw.row_number and x['sheet']==raw.sheet for x in sources))
    def test_complete_export_deduplicates_lots_has_exact_audit_hash(self):
        before=list(Record.objects.values());d=self.board();r=self.client.get('/api/return-stock/export?receipt='+d['receipt']+'&page=2')
        self.assertEqual(r.status_code,200,r.content);self.assertTrue(r.content.startswith(b'\xef\xbb\xbf'))
        parsed=list(csv.reader(io.StringIO(r.content.decode('utf-8-sig'))));self.assertEqual(sum(row and row[0]=='T1' for row in parsed if row),1)
        event=AuditEvent.objects.latest('id');self.assertEqual((event.detail['returns'],event.detail['target_lots']),(2,1));self.assertEqual(event.detail['file_sha256'],hashlib.sha256(r.content).hexdigest());self.assertEqual(list(Record.objects.values()),before)
    def test_stage_scope_export_and_outside_detail(self):
        d=self.board('?stage=restricted');self.assertEqual(d['summary']['returns'],2);self.assertEqual(d['total'],0)
        q='?stage=restricted&receipt='+d['receipt'];self.assertEqual(self.client.get('/api/return-stock/rows/T1'+q).status_code,404)
        r=self.client.get('/api/return-stock/export'+q);self.assertEqual(r.status_code,200);self.assertEqual(AuditEvent.objects.latest('id').detail['returns'],0)
    def test_six_roles_no_money_or_raw_personnel_and_anonymous_denied(self):
        for role in ('admin','analyst','quality','operations','finance','viewer'):
            user=User.objects.create_user('return_stock_'+role);user.groups.add(Group.objects.get_or_create(name=role)[0]);self.client.force_login(user);d=self.board()
            for path in ('/api/return-stock/rows/T1','/api/return-stock/export'):
                r=self.client.get(path+'?receipt='+d['receipt']);self.assertEqual(r.status_code,200,r.content);self.assertNotIn('cents',r.content.decode());self.assertNotIn('12345',r.content.decode())
        # Account middleware revokes the session when its role assignment changes.
        user.groups.add(Group.objects.get(name='quality'));self.assertEqual(self.client.get('/api/return-stock').status_code,401)
        self.client.logout();self.assertEqual(self.client.get('/api/return-stock').status_code,401)
    def test_missing_stale_scope_data_and_bad_pagination(self):
        self.assertEqual(self.client.get('/api/return-stock/export').status_code,400);d=self.board();q='?receipt='+d['receipt']
        self.assertEqual(self.client.get('/api/return-stock/export'+q+'&q=T1').status_code,409)
        r=Record.objects.get(dataset='inventory_movements',business_key='T1');r.revision+=1;r.save()
        self.assertEqual(self.client.get('/api/return-stock/export'+q).status_code,409)
        self.assertEqual(self.client.get('/api/return-stock?page=0').status_code,400)
    def test_mid_read_revision_or_audit_error_does_not_commit_export(self):
        d=self.board();before=AuditEvent.objects.count();q='?receipt='+d['receipt']
        revision=analytics.revision()
        with patch('app.return_stock_views.analytics.revision',side_effect=[revision,tuple(revision)+('changed',)]):
            self.assertEqual(self.client.get('/api/return-stock/export'+q).status_code,409)
        with patch('app.return_stock_views.AuditEvent.objects.create',side_effect=ValueError('unavailable')):self.assertEqual(self.client.get('/api/return-stock/export'+q).status_code,400)
        self.assertEqual(AuditEvent.objects.count(),before)
