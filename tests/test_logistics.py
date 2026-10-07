import copy,csv,io,json
from django.test import SimpleTestCase,Client
from django.contrib.auth.models import User,Group
from app import logistics as lg
from app.models import Record,IssueDisposition,AuditEvent
from tests.test_platform import PlatformCase

def fixture():
    return {'customers':[dict(id='C',name='模拟客户')],'products':[dict(id='P',family='F')],'orders':[dict(id='O',customer_id='C')],'order_lines':[dict(id='OL',order_id='O',product_id='P')],
      'units':[dict(id='U1',product_id='P'),dict(id='U2',product_id='P')],
      'shipments':[dict(id='S',order_line_id='OL',qty=2,shipped='2026-09-20T08:00:00',signed='2026-09-22T12:00:00',carrier='物流',tracking='T')],
      'shipment_units':[dict(id='PK1',shipment_id='S',unit_id='U1',package='B'),dict(id='PK2',shipment_id='S',unit_id='U2',package='B')],
      'transport_dispatches':[dict(id='D',shipment_id='S',handed='2026-09-20T09:00:00',promised='2026-09-22T12:00:00',route='线路',reference='JJ')],
      'transport_events':[dict(id='E',dispatch_id='D',occurred='2026-09-22T10:00:00',kind='物流到达',location='客户',note='物流到达',voided=False)],
      'customer_receipts':[dict(id='R',dispatch_id='D',received='2026-09-22T12:00:00',document='DOC',receiver='收货岗位',voided=False)],
      'customer_receipt_units':[dict(id='RU1',receipt_id='R',unit_id='U1',outcome='接收',reason='模拟接收'),dict(id='RU2',receipt_id='R',unit_id='U2',outcome='接收',reason='模拟接收')]}

class LogisticsMathTests(SimpleTestCase):
    def setUp(self):self.d=fixture()
    def row(self):return lg.Logistics(self.d).detail('S')
    def test_exact_promise_counts_and_quantity_conservation(self):
        r=self.row();self.assertEqual((r['accepted'],r['refused'],r['pending']),(2,0,0));self.assertTrue(r['on_time']);self.assertEqual(r['legacy_check'],'原签收与全量SN接收时间一致')
    def test_no_receipt_does_not_infer_acceptance_from_legacy_or_arrival(self):
        self.d['customer_receipts']=[];self.d['customer_receipt_units']=[];r=self.row();self.assertEqual((r['accepted'],r['pending']),(0,2));self.assertFalse(r['on_time']);self.assertTrue(r['issues'])
    def test_partial_refused_and_pending_are_distinct(self):
        self.d['customer_receipt_units'].pop();r=self.row();self.assertEqual((r['stage'],r['accepted'],r['pending']),('partial',1,1))
        self.d['customer_receipt_units'][0]['outcome']='拒收';r=self.row();self.assertEqual((r['stage'],r['refused'],r['pending']),('refused',1,1))
    def test_full_receipt_is_latest_split_time(self):
        self.d['customer_receipts'].append({**self.d['customer_receipts'][0],'id':'R2','received':'2026-09-23T12:00:00'});self.d['customer_receipt_units'][1]['receipt_id']='R2'
        r=self.row();self.assertEqual(r['full_received'],'2026-09-23T12:00:00');self.assertFalse(r['on_time']);self.assertTrue(r['late'])
    def test_void_and_future_receipts_excluded(self):
        for changed in [{'voided':True},{'received':'2026-10-02T08:00:00'}]:
            self.d=fixture();self.d['customer_receipts'][0].update(changed);r=self.row();self.assertEqual((r['accepted'],r['pending'],r['excluded_units']),(0,2,2))
    def test_void_then_corrected_receipt_valid(self):
        self.d['customer_receipts'].append({**self.d['customer_receipts'][0],'id':'OLD','voided':True});self.d['customer_receipt_units'].append({**self.d['customer_receipt_units'][0],'id':'OLDLINE','receipt_id':'OLD','outcome':'拒收'});self.assertEqual(self.row()['accepted'],2)
    def test_duplicate_active_decisions_unknown_even_same_outcome(self):
        self.d['customer_receipt_units'].append({**self.d['customer_receipt_units'][0],'id':'DUP'});r=self.row();self.assertIsNone(r['accepted']);self.assertIsNone(r['on_time']);self.assertEqual(lg.summary([r])['unknown_due_rows'],1)
    def test_wrong_shipment_sn_never_counted(self):
        self.d['customer_receipt_units'][0]['unit_id']='OTHER';self.assertIsNone(self.row()['accepted'])
    def test_quantity_and_packing_disagreements_unknown(self):
        for qty in [3,True,-1,0,'2']:
            self.d['shipments'][0]['qty']=qty;self.assertIsNone(self.row()['accepted'])
    def test_duplicate_packing_across_shipments_unknown(self):
        self.d['shipment_units'].append(dict(id='P3',shipment_id='S2',unit_id='U1',package='B2'));self.assertIsNone(self.row()['accepted']);self.assertTrue(lg.Logistics(self.d).global_issues)
    def test_wrong_product_and_missing_order_cannot_be_accepted(self):
        for ds in ['orders','customers','products','units']:
            self.d=fixture();self.d[ds]=[];self.assertIsNone(self.row()['accepted'])
    def test_missing_receipt_document_receiver_and_date_unknown(self):
        for changed in [{'document':None},{'receiver':None},{'received':'bad'},{'received':'2026-09-20T08:30:00'},{'voided':'False'}]:
            self.d=fixture();self.d['customer_receipts'][0].update(changed);self.assertIsNone(self.row()['accepted'])
    def test_empty_receipt_unknown_not_pending(self):
        self.d['customer_receipt_units']=[];self.assertIsNone(self.row()['accepted'])
    def test_no_valid_promise_keeps_quantity_but_excludes_timeliness(self):
        for changed in [{'handed':None},{'reference':None},{'promised':None},{'promised':'2026-09-20T07:00:00'}]:
            self.d=fixture();self.d['transport_dispatches'][0].update(changed);r=self.row();self.assertEqual(r['accepted'],2);self.assertFalse(r['due']);self.assertIsNone(r['on_time'])
    def test_unexpired_promise_is_not_in_denominator(self):
        self.d['transport_dispatches'][0]['promised']='2026-10-10T10:00:00';r=self.row();self.assertIsNone(r['on_time']);self.assertEqual(lg.summary([r])['rated_due_rows'],0)
    def test_multiple_dispatches_require_explicit_split_reconciliation(self):
        self.d['transport_dispatches'].append({**self.d['transport_dispatches'][0],'id':'D2'});self.assertIsNone(self.row()['accepted'])
    def test_future_shipment_excluded_from_current_quantities(self):
        self.d['shipments'][0]['shipped']='2026-10-05T08:00:00';self.d['customer_receipts']=[];self.d['customer_receipt_units']=[];r=self.row();self.assertEqual(r['stage'],'future');self.assertIsNone(r['accepted']);self.assertFalse(r['due'])
    def test_transport_events_do_not_inflate_or_override_receipt(self):
        self.d['transport_events']*=3;r=self.row();self.assertEqual(r['accepted'],2)
        for changed in [{'occurred':'2026-10-03T12:00:00'},{'voided':True},{'kind':'不支持'}]:
            self.d=fixture();self.d['transport_events'][0].update(changed);r=self.row();self.assertFalse(r['timeline'][0]['included']);self.assertEqual(r['accepted'],2)
    def test_filters_empty_sn_and_date_scope(self):
        d=lg.Logistics(self.d)
        for f in [{'q':'U1'},{'from':'2026-09-20','to':'2026-09-20'},{'customer_id':'C'},{'carrier':'物流'}]:self.assertEqual(len(d.selected(lg.params(f))),1)
        self.assertEqual(d.selected(lg.params({'customer_id':'missing'})),[]);self.assertIsNone(lg.summary([])['accepted']);self.assertIsNone(lg.summary([])['due_rate'])
    def test_invalid_params_rejected(self):
        for p in [{'from':'bad'},{'stage':'invalid'},{'attention':'invalid'},{'from':'2026-10-01','to':'2026-09-30'}]:
            with self.assertRaises(ValueError):lg.params(p)
    def test_sources_preserve_excluded_lines_and_unit_identity(self):
        self.d['customer_receipts'][0]['voided']=True;r=self.row();refs={(s['dataset'],s['key']) for s in r['sources']};self.assertIn(('customer_receipt_units','RU1'),refs);self.assertIn(('units','U1'),refs)
    def test_calculation_does_not_mutate_facts(self):
        before=copy.deepcopy(self.d);self.row();self.assertEqual(self.d,before)

class LogisticsApiTests(PlatformCase):
    def setUp(self):
        super().setUp()
        for ds,rows in fixture().items():
            for r in rows:self.record(ds,r)
        self.client.force_login(self.admin)
    def detail(self):return self.client.get('/api/logistics/S').json()
    def test_read_auth_and_role_conflict(self):
        self.client.logout();self.assertEqual(self.client.get('/api/logistics').status_code,401)
        self.admin.groups.add(Group.objects.get(name='quality'));self.client.force_login(self.admin);self.assertEqual(self.client.get('/api/logistics').status_code,401)
    def test_read_nonfinancial_for_quality(self):
        self.client.force_login(self.quality);self.assertEqual(self.client.get('/api/logistics').status_code,200);self.assertFalse(self.detail()['can_follow'])
    def test_invalid_filter_and_missing_object(self):
        self.assertEqual(self.client.get('/api/logistics?from=bad').status_code,400);self.assertEqual(self.client.get('/api/logistics/MISSING').status_code,404)
    def test_summary_not_limited_to_page(self):
        for i in range(26):self.record('shipments',{**fixture()['shipments'][0],'id':'OTHER'+str(i)})
        d=self.client.get('/api/logistics').json();self.assertEqual((d['total'],len(d['rows']),d['summary']['quantity_unknown_rows']),(27,25,26))
    def test_export_uses_whole_same_filter_and_guards_stale_receipt(self):
        d=self.client.get('/api/logistics?customer_id=C').json();r=self.client.get('/api/logistics/export',{'customer_id':'C','receipt':d['receipt']});self.assertEqual(r.status_code,200);rows=list(csv.reader(io.StringIO(r.content.decode('utf-8-sig'))));self.assertEqual(rows[5][0],'S');self.assertEqual(len(rows),6)
        self.assertEqual(self.client.get('/api/logistics/export?receipt=old').status_code,409)
        empty=self.client.get('/api/logistics/export',{'customer_id':'missing','receipt':d['receipt']});self.assertEqual(len(list(csv.reader(io.StringIO(empty.content.decode('utf-8-sig'))))),5)
    def test_evidence_has_xlsx_line_and_revision(self):
        d=self.detail();r=self.client.get('/api/logistics/S/evidence',{'receipt':d['receipt']}).json();self.assertTrue(all(x['row']==2 and x['filename']=='unit-test.xlsx' for x in r['rows']));self.assertEqual(self.client.get('/api/logistics/S/evidence?receipt=stale').status_code,409)
    def payload(self):return dict(version=0,status='客户签收核对中',owner='模拟业务岗位',due_date='2026-10-05',note='逐台核对模拟签收依据',receipt=self.detail()['receipt'])
    def test_followup_preserves_business_and_audits_versions(self):
        before=list(Record.objects.values_list('values',flat=True));p=self.payload();r=self.post('/api/logistics/S/follow-up',p);self.assertEqual(r.status_code,200);self.assertEqual(r.json()['follow_up']['version'],1);self.assertEqual(before,list(Record.objects.values_list('values',flat=True)));self.assertEqual(self.post('/api/logistics/S/follow-up',p).status_code,409);self.assertEqual(len(self.client.get('/api/logistics/S/history').json()['rows']),1)
    def test_only_admin_analyst_operations_may_follow(self):
        p=self.payload()
        for role in ['quality','finance','viewer']:
            u=User.objects.create_user('reader-'+role);u.groups.add(Group.objects.get_or_create(name=role)[0]);self.client.force_login(u);self.assertEqual(self.post('/api/logistics/S/follow-up',p).status_code,403)
        for role in ['analyst','operations']:
            u=User.objects.create_user('writer-'+role);u.groups.add(Group.objects.get_or_create(name=role)[0]);self.client.force_login(u);p['version']=IssueDisposition.objects.first().version if IssueDisposition.objects.exists() else 0;self.assertEqual(self.post('/api/logistics/S/follow-up',p).status_code,200)
    def test_followup_validation_and_csrf(self):
        p=self.payload()
        for update in [{'version':True},{'status':'业务已签收'},{'owner':''},{'note':'短'},{'due_date':'bad'}]:self.assertEqual(self.post('/api/logistics/S/follow-up',{**p,**update}).status_code,400)
        self.assertEqual(self.post('/api/logistics/S/follow-up',{**p,'receipt':'old'}).status_code,409)
        c=Client(enforce_csrf_checks=True);c.force_login(self.admin);self.assertEqual(c.post('/api/logistics/S/follow-up',json.dumps(p),content_type='application/json').status_code,403)
    def test_record_change_invalidates_export_and_coordination(self):
        p=self.payload();self.record('transport_events',dict(id='E2',dispatch_id='D',occurred='2026-09-23T08:00:00',kind='运输中',location='A',note='模拟记录',voided=False));self.assertEqual(self.post('/api/logistics/S/follow-up',p).status_code,409)
