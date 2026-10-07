import csv,io,json
from copy import deepcopy
from datetime import date,timedelta
from unittest.mock import patch
from django.test import SimpleTestCase,Client
from django.contrib.auth.models import User,Group
from app import receivables as ar,analytics
from app.schema import SCHEMAS
from app.models import Record,IssueDisposition,AuditEvent
from tests.test_platform import PlatformCase

def fixture():
    d={k:[] for k in SCHEMAS}
    d['customers']=[dict(id='C1',name='客户一（模拟）',region='华东'),dict(id='C2',name='客户二（模拟）',region='华北')]
    d['orders']=[dict(id='O1',customer_id='C1',currency='CNY')]
    d['order_lines']=[dict(id='L1',order_id='O1')]
    d['shipments']=[dict(id='S1',order_line_id='L1',shipped='2026-09-21T09:00:00')]
    d['invoices']=[dict(id='F1',customer_id='C1',shipment_id='S1',issued='2026-09-21',due='2026-10-21',net_cents=9000,tax_cents=1000,status='部分收款')]
    d['payments']=[dict(id='P1',invoice_id='F1',paid='2026-09-25',amount_cents=2000,method='模拟转账')]
    d['ar_opening']=[dict(id='A1',customer_id='C1',document_no='OLD1',issued='2026-06-01',due='2026-08-15',as_of='2026-09-01',currency='CNY',original_gross_cents=20000,opening_balance_cents=10000,note='模拟')]
    d['ar_events']=[dict(id='E1',opening_id='A1',occurred='2026-09-05',kind='收款核销',delta_cents=-3000,status='已过账',document_no='V1',reverses_id=None),
                    dict(id='E2',opening_id='A1',occurred='2026-09-10',kind='贷项冲减',delta_cents=-1000,status='已过账',document_no='V2',reverses_id=None)]
    return d

class ReceivableCalculationTests(SimpleTestCase):
    def setUp(self):self.d=fixture()
    def current(self):return ar.ReceivableData(self.d)
    def opening(self):return self.current().index['opening:A1']
    def event(self,**kw):
        r=dict(self.d['ar_events'][0],id='E3',**kw);self.d['ar_events'].append(r);return r
    def test_opening_uses_unsettled_not_original_gross(self):
        r=self.opening();self.assertEqual((r['original_gross_cents'],r['basis_cents'],r['balance_cents']),(20000,10000,6000));self.assertEqual(r['overdue_days'],47)
        s=ar.summary(self.current().rows);self.assertEqual(s['balance_cents'],14000);self.assertEqual(s['basis_cents'],20000)
    def test_credit_is_not_cash_and_bridge_reconciles(self):
        s=ar.summary(self.current().rows);self.assertEqual(s['net_receipt_cents'],5000);self.assertEqual(s['credit_cents'],1000);self.assertEqual(s['balance_cents'],s['basis_cents']-s['net_receipt_cents']-s['credit_cents'])
    def test_future_draft_revoked_excluded_but_retained(self):
        self.event(occurred='2026-10-05',delta_cents=-6000)
        self.d['ar_events'] += [dict(self.d['ar_events'][0],id='DRAFT',status='草稿',delta_cents=None),dict(self.d['ar_events'][0],id='VOID',status='已撤销')]
        r=self.opening();self.assertEqual(r['balance_cents'],6000);self.assertEqual((r['future_events'],r['excluded_events'],len(r['ledger'])),(1,2,5))
    def test_partial_reversal_restores_balance_and_net_receipts(self):
        self.event(kind='核销冲回',delta_cents=1000,reverses_id='E1',occurred='2026-09-18')
        r=self.opening();self.assertEqual((r['balance_cents'],r['receipt_cents'],r['reversal_cents'],r['net_receipt_cents']),(7000,3000,1000,2000))
    def test_cross_receivable_or_credit_reversal_is_invalid(self):
        for key in ['OTHER_RECEIPT','E2']:
            self.d=fixture();self.event(kind='核销冲回',delta_cents=500,reverses_id=key);self.assertIsNone(self.opening()['balance_cents'])
    def test_cumulative_reversal_cannot_exceed_original(self):
        self.event(kind='核销冲回',delta_cents=2000,reverses_id='E1',occurred='2026-09-12')
        self.d['ar_events'].append(dict(self.d['ar_events'][-1],id='E4',occurred='2026-09-15'))
        self.assertIsNone(self.opening()['balance_cents']);self.assertIn('累计冲回',str(self.opening()['issues']))
    def test_reversal_before_receipt_and_pre_cutover_receipt_rejected(self):
        for occurred in ['2026-09-04','2026-08-30']:
            self.d=fixture();self.event(kind='核销冲回',delta_cents=1000,reverses_id='E1',occurred=occurred);self.assertEqual(self.opening()['stage'],'review')
    def test_same_day_order_is_not_inferred_and_daily_balance_shared(self):
        self.event(kind='核销冲回',delta_cents=3000,reverses_id='E1',occurred='2026-09-05')
        r=self.opening();today=[e for e in r['ledger'] if e['occurred']=='2026-09-05'];self.assertEqual([e['day_balance_cents'] for e in today],[10000,10000]);self.assertEqual(r['balance_cents'],9000)
    def test_overpayment_not_clamped_even_when_later_reversed(self):
        self.d['ar_events'][0]['delta_cents']=-11000
        self.event(kind='核销冲回',delta_cents=11000,reverses_id='E1',occurred='2026-09-25')
        r=self.opening();self.assertIsNone(r['balance_cents']);self.assertTrue(all(e['day_balance_cents'] is None for e in r['ledger']))
    def test_aging_boundaries_and_today_not_overdue(self):
        self.d['ar_events']=[]
        for offset,key in [(-1,'not_due'),(0,'due_today'),(1,'d1_30'),(30,'d1_30'),(31,'d31_60'),(60,'d31_60'),(61,'d61_90'),(90,'d61_90'),(91,'d91_180'),(180,'d91_180'),(181,'d181_plus')]:
            self.d['ar_opening'][0].update(issued='2025-01-01',due=(date(2026,10,1)-timedelta(days=offset)).isoformat());r=self.opening();self.assertEqual(r['bucket'],key)
    def test_settled_is_not_overdue_and_no_ratio_when_all_zero(self):
        self.d['ar_events'][0]['delta_cents']=-9000;r=self.opening();self.assertEqual((r['stage'],r['balance_cents'],r['overdue_days']),('settled',0,0));self.assertIsNone(ar.summary([r])['overdue_ratio'])
    def test_future_invoice_payment_does_not_settle_by_raw_status(self):
        self.d['payments'][0].update(paid='2026-10-05',amount_cents=10000);self.d['invoices'][0]['status']='已收款'
        r=self.current().index['invoice:F1'];self.assertEqual(r['balance_cents'],10000);self.assertEqual(r['future_events'],1)
    def test_payment_before_invoice_date_is_review(self):
        self.d['payments'][0]['paid']='2026-09-20';self.assertIsNone(self.current().index['invoice:F1']['balance_cents'])
    def test_currency_customer_and_order_links_must_match(self):
        for change in ['currency','customer_id']:
            self.d=fixture();self.d['orders'][0][change]='BAD';self.assertEqual(self.current().index['invoice:F1']['stage'],'review')
        self.d=fixture();self.d['order_lines']=[];self.assertEqual(self.current().index['invoice:F1']['stage'],'review')
    def test_exact_original_document_duplicates_pause_both(self):
        self.d['ar_opening'][0]['document_no']='F1';d=self.current();self.assertTrue(all(r['balance_cents'] is None for r in d.rows));self.assertEqual(ar.summary(d.rows)['review_rows'],2)
    def test_bad_integer_dates_balance_and_unsupported_status(self):
        for key,value in [('opening_balance_cents',True),('opening_balance_cents',20001),('opening_balance_cents',-1),('original_gross_cents',None),('due','2026-02-30'),('issued','2026-09-01'),('currency','USD')]:
            self.d=fixture();self.d['ar_opening'][0][key]=value;self.assertEqual(self.opening()['stage'],'review',(key,value))
        self.d=fixture();self.d['ar_events'][0]['status']='未知';self.assertIsNone(self.opening()['balance_cents'])
    def test_invalid_sign_type_reference_does_not_silently_count(self):
        for changes in [dict(delta_cents=100),dict(delta_cents=0),dict(delta_cents='-100'),dict(kind='无法识别'),dict(reverses_id='E2')]:
            self.d=fixture();self.d['ar_events'][0].update(changes);self.assertEqual(self.opening()['stage'],'review')
    def test_orphan_records_visible_and_future_basis_separate(self):
        self.d['payments'][0]['invoice_id']='MISSING';self.d['ar_opening'][0]['as_of']='2026-10-05';self.d['ar_events']=[]
        d=self.current();self.assertEqual(len(d.global_issues),1);self.assertEqual(d.index['opening:A1']['stage'],'future');self.assertEqual(ar.summary(d.rows)['balance_cents'],10000)
    def test_weighted_ratio_and_customer_kind_partition(self):
        d=self.current();s=ar.summary(d.rows);b=ar.breakdown(d.rows);self.assertAlmostEqual(s['overdue_ratio'],6000/14000*100);self.assertEqual(sum(x['balance_cents'] for x in b['by_kind']),s['balance_cents']);self.assertEqual(sum(x['value'] for x in b['aging']),s['balance_cents'])
    def test_combined_filters_and_unknown_customer_empty(self):
        d=self.current();f=ar.filters(dict(customer_id='C1',kind='opening',bucket='d31_60',stage='overdue',q='OLD1'));self.assertEqual([r['id'] for r in d.selected(f)],['A1']);self.assertEqual(d.selected(ar.filters(dict(customer_id='missing'))),[])
        for args in [dict(kind='wrong'),dict(bucket='wrong'),dict(stage='wrong')]:
            with self.assertRaises(ValueError):ar.filters(args)

class ReceivableAPITests(PlatformCase):
    def setUp(self):
        super().setUp();self.finance=User.objects.create_user('finance',password='test-password');g=Group.objects.create(name='finance');self.finance.groups.add(g)
        for ds,rows in fixture().items():
            for r in rows:self.record(ds,r)
        analytics._tables.cache_clear();self.client.force_login(self.finance)
    def payload(self):return dict(version=0,status='对账中',owner='财务岗位（模拟）',due_date='2026-10-06',note='核对期初与核销原件',data_revision=list(analytics.revision()))
    def test_all_endpoints_and_raw_datasets_require_money_permission(self):
        urls=['/api/receivables','/api/receivables/export','/api/receivables/opening/A1','/api/receivables/opening/A1/evidence','/api/receivables/opening/A1/history','/api/records/ar_opening','/api/records/ar_events']
        self.client.force_login(self.quality)
        for url in urls:self.assertEqual(self.client.get(url).status_code,403,url)
        self.assertEqual(self.post('/api/receivables/opening/A1/follow-up',self.payload()).status_code,403)
        self.client.logout();self.assertEqual(self.client.get('/api/receivables').status_code,401)
    def test_board_scoping_source_evidence_and_empty_range(self):
        r=self.client.get('/api/receivables?kind=opening&stage=overdue').json();self.assertEqual((r['total'],r['summary']['balance_cents']),(1,6000));self.assertEqual(r['facets']['all'],1)
        self.assertEqual(r['customers'][0]['balance_cents'],6000);self.assertEqual(len(r['customer_options']),2)
        e=self.client.get('/api/receivables/opening/A1/evidence').json();self.assertEqual(e['total'],4);self.assertFalse(e['can_download_original']);self.assertEqual({x['filename'] for x in e['rows']},{'unit-test.xlsx'})
        self.assertEqual(self.client.get('/api/receivables?customer_id=missing').json()['total'],0)
    def test_followup_version_source_guard_and_facts_preserved(self):
        before=list(Record.objects.values_list('values',flat=True));p=self.payload();r=self.post('/api/receivables/opening/A1/follow-up',p);self.assertEqual(r.status_code,200);self.assertEqual(r.json()['follow_up']['version'],1)
        self.assertEqual(self.post('/api/receivables/opening/A1/follow-up',p).status_code,409)
        p.update(version=1,data_revision=[0,'stale']);self.assertEqual(self.post('/api/receivables/opening/A1/follow-up',p).status_code,409)
        self.assertEqual(list(Record.objects.values_list('values',flat=True)),before);self.assertEqual(self.client.get('/api/receivables/opening/A1/history').json()['rows'][0]['actor'],'finance')
    def test_audit_failure_rolls_back_followup(self):
        with patch('app.receivable_views.AuditEvent.objects.create',side_effect=RuntimeError('audit failed')):
            with self.assertRaises(RuntimeError):self.post('/api/receivables/opening/A1/follow-up',self.payload())
        self.assertFalse(IssueDisposition.objects.exists())
    def test_csrf_and_unknown_fields_rejected(self):
        c=Client(enforce_csrf_checks=True);c.force_login(self.finance);self.assertEqual(c.post('/api/receivables/opening/A1/follow-up',json.dumps(self.payload()),content_type='application/json').status_code,403)
        self.assertEqual(self.post('/api/receivables/opening/A1/follow-up',{**self.payload(),'balance_cents':0}).status_code,400)
    def test_export_is_full_filtered_population_and_formula_safe(self):
        r=Record.objects.get(dataset='customers',business_key='C1');r.values['name']='=BAD()';r.save();analytics._tables.cache_clear()
        res=self.client.get('/api/receivables/export?kind=opening&stage=overdue');self.assertEqual(res.status_code,200)
        data=list(csv.reader(io.StringIO(res.content.decode('utf-8-sig'))));self.assertEqual(len(data[4:]),1);self.assertEqual(data[4][0],'A1');self.assertTrue(data[4][4].startswith("'="));self.assertEqual(data[4][14],'6000');self.assertEqual(res['Cache-Control'],'no-store')
    def test_orphan_warning_prevents_complete_summary(self):
        self.record('ar_events',dict(fixture()['ar_events'][0],id='ORPHAN',opening_id='missing'));analytics._tables.cache_clear()
        d=self.client.get('/api/receivables').json();self.assertFalse(d['summary']['complete']);self.assertEqual(len(d['global_issues']),1)
