import copy,json,csv,io
from unittest.mock import patch
from django.test import SimpleTestCase,Client
from django.contrib.auth.models import User,Group
from tests.test_platform import PlatformCase
from app.models import Record,IssueDisposition,AuditEvent
from app import payables as ap

def fixture():
    return {'suppliers':[{'id':'S','name':'供应商'}],'materials':[{'id':'M','name':'轴承','unit':'件'}],
      'purchase_lines':[dict(id='PO',supplier_id='S',material_id='M',ordered='2026-09-01',unit_price_cents=100)],
      'receipts':[dict(id='R',purchase_line_id='PO',material_id='M',received='2026-09-03T08:00:00',qty=100,status='检验合格')],
      'purchase_terms':[dict(id='T',purchase_line_id='PO',currency='CNY',price_basis='未税',tax_bps=1300,confirmed='2026-09-01')],
      'ap_invoices':[dict(id='I',supplier_id='S',invoice_no='VAT1',currency='CNY',issued='2026-09-04',posted='2026-09-05',due='2026-09-30',net_cents=10000,tax_cents=1300,status='已确认')],
      'ap_invoice_lines':[dict(id='L',invoice_id='I',receipt_id='R',qty=100,unit_price_cents=100,tax_bps=1300,net_cents=10000,tax_cents=1300)],
      'ap_payments':[dict(id='P',supplier_id='S',currency='CNY',paid='2026-09-06',amount_cents=6000,status='已付款',document_no='PV1')],
      'ap_allocations':[dict(id='A',payment_id='P',invoice_id='I',occurred='2026-09-07',amount_cents=5000,status='已核销',plan_id='PL')],
      'ap_adjustments':[dict(id='C',invoice_id='I',occurred='2026-09-10',kind='贷项冲减',delta_cents=-1300,allocation_id=None,status='已过账'),dict(id='REV',invoice_id='I',occurred='2026-09-11',kind='核销冲回',delta_cents=1000,allocation_id='A',status='已过账')],
      'ap_payment_plans':[dict(id='PL',invoice_id='I',created='2026-09-05',approved='2026-09-05',planned='2026-09-30',amount_cents=10000,status='已批准',owner_id='E')]}

class SupplierLedgerTests(SimpleTestCase):
    def setUp(self):self.d=fixture()
    def data(self):return ap.PayableData(self.d)
    def test_unknown_receipt_date_is_visible_but_not_valued(self):
        self.d['receipts'][0]['received']='invalid'
        d=self.data();self.assertIn('R',d.receipts);self.assertTrue(d.receipts['R']['issues']);self.assertIsNone(d.receipts['R']['reference_net_cents'])
        self.assertFalse(ap.summary(list(d.receipts.values()),'receipts')['complete'])
    def test_receipt_material_mismatch_cannot_value_wrong_purchase_price(self):
        self.d['materials'].append(dict(id='M2',name='不同材料',unit='kg'));self.d['receipts'][0]['material_id']='M2'
        r=self.data().receipts['R'];self.assertIn('到货物料与采购行不一致',r['issues']);self.assertIsNone(r['reference_net_cents'])
    def test_receipt_missing_supplier_cannot_be_confirmed(self):
        self.d['suppliers']=[];r=self.data().receipts['R'];self.assertIsNone(r['reference_net_cents']);self.assertIn('采购供应商档案缺失',r['issues'])
    def test_unknown_receipt_units_are_not_false_zero_or_sum(self):
        self.d['materials'][0]['unit']=None;d=self.data();r=d.receipts['R'];self.assertIsNone(r['reference_net_cents'])
        self.assertEqual(ap.summary([r],'receipts')['units'],[dict(unit='未登记',received_qty=None,unbilled_qty=None)])
    def test_balance_payment_and_plan_are_three_distinct_measures(self):
        d=self.data();i=d.invoices['I'];p=d.payments['P'];plan=d.plans['PL']
        self.assertEqual((i['gross_cents'],i['allocated_cents'],i['reversal_cents'],i['credit_cents'],i['balance_cents']),(11300,5000,1000,1300,6000))
        self.assertEqual((p['amount_cents'],p['net_allocation_cents'],p['unallocated_cents']),(6000,4000,2000))
        self.assertEqual((plan['executed_cents'],plan['remaining_cents'],plan['late']),(4000,6000,True));self.assertEqual(i['stage'],'overdue')
    def test_matching_variance_preserves_booked_liability(self):
        self.d['ap_invoice_lines'][0]['unit_price_cents']=101
        r=self.data().invoices['I'];self.assertEqual(r['balance_cents'],6000);self.assertTrue(r['match_issues']);self.assertFalse(r['issues'])
    def test_header_detail_difference_does_not_erase_liability(self):
        self.d['ap_invoices'][0]['net_cents']=11000;r=self.data().invoices['I'];self.assertEqual(r['balance_cents'],7000);self.assertIn('发票头与明细金额不一致',r['match_issues'])
    def test_no_lines_does_not_erase_booked_invoice(self):
        self.d['ap_invoice_lines']=[];r=self.data().invoices['I'];self.assertEqual(r['balance_cents'],6000);self.assertTrue(r['match_issues'])
    def test_cross_invoice_payment_allocations_share_one_limit(self):
        self.d['ap_invoices'].append({**self.d['ap_invoices'][0],'id':'I2','invoice_no':'VAT2'})
        self.d['ap_allocations'].append({**self.d['ap_allocations'][0],'id':'A2','invoice_id':'I2','amount_cents':2000,'plan_id':None})
        d=self.data();self.assertIsNone(d.payments['P']['unallocated_cents']);self.assertTrue(all(r['balance_cents'] is None for r in d.invoices.values()))
    def test_later_reversal_cannot_hide_earlier_overallocation(self):
        self.d['ap_allocations'][0]['amount_cents']=7000;self.d['ap_adjustments'][1]['delta_cents']=2000
        self.assertIsNone(self.data().payments['P']['unallocated_cents'])
    def test_same_day_netting_does_not_invent_intraday_order(self):
        self.d['ap_allocations'][0]['amount_cents']=7000;self.d['ap_adjustments'][1].update(delta_cents=2000,occurred='2026-09-07')
        self.assertEqual(self.data().payments['P']['unallocated_cents'],1000)
    def test_aggregate_reversal_limit(self):
        self.d['ap_adjustments']+=[{**self.d['ap_adjustments'][1],'id':'REV2','delta_cents':4500}]
        d=self.data();self.assertIsNone(d.invoices['I']['balance_cents']);self.assertIsNone(d.payments['P']['unallocated_cents'])
    def test_cross_invoice_reversal_rejected(self):
        self.d['ap_adjustments'][1]['invoice_id']='MISSING';d=self.data();self.assertTrue(d.global_issues);self.assertIsNone(d.payments['P']['unallocated_cents'])
    def test_supplier_currency_and_allocation_dates_checked(self):
        for changes in [{'supplier_id':'OTHER'},{'currency':'USD'},{'paid':'2026-09-09'}]:
            self.d=fixture();self.d['ap_payments'][0].update(changes);self.assertIsNone(self.data().invoices['I']['balance_cents'])
    def test_future_draft_void_events_not_applied(self):
        for changes in [{'occurred':'2026-10-02'},{'status':'草稿'},{'status':'已撤销'}]:
            self.d=fixture();self.d['ap_adjustments'][0].update(changes);self.assertEqual(self.data().invoices['I']['balance_cents'],7300)
    def test_future_allocation_and_payment_are_not_current(self):
        self.d['ap_payments'][0]['paid']='2026-10-02';self.d['ap_allocations'][0]['occurred']='2026-10-02';self.d['ap_adjustments']=[]
        d=self.data();self.assertEqual(d.invoices['I']['balance_cents'],11300);self.assertIsNone(d.payments['P']['unallocated_cents'])
    def test_draft_and_future_invoices_are_excluded(self):
        self.d['ap_allocations']=[];self.d['ap_adjustments']=[]
        for changes in [{'posted':'2026-10-02'},{'status':'草稿'},{'status':'已作废'}]:
            self.d['ap_invoices'][0].update(changes);r=self.data().invoices['I'];self.assertIsNone(r['balance_cents']);self.assertEqual(r['stage'],'excluded')
    def test_duplicate_supplier_invoice_number_halts_balances(self):
        self.d['ap_invoices'].append({**self.d['ap_invoices'][0],'id':'I2'})
        self.assertTrue(all(r['balance_cents'] is None for r in self.data().invoices.values()))
    def test_negative_daily_balance_not_hidden_by_later_adjustment(self):
        self.d['ap_adjustments'][0]['delta_cents']=-7000;self.assertIsNone(self.data().invoices['I']['balance_cents'])
    def test_unapproved_plan_does_not_reduce_balance(self):
        self.d['ap_allocations'][0]['plan_id']=None;self.d['ap_payment_plans'][0].update(status='待审批',approved=None)
        d=self.data();self.assertEqual(d.invoices['I']['balance_cents'],6000);self.assertIsNone(d.plans['PL']['remaining_cents'])
    def test_two_plans_cannot_allocate_same_balance_twice(self):
        self.d['ap_payment_plans'].append({**self.d['ap_payment_plans'][0],'id':'PL2','amount_cents':1})
        d=self.data();self.assertEqual(d.invoices['I']['balance_cents'],6000);self.assertTrue(all(r['remaining_cents'] is None for r in d.plans.values()))
    def test_plan_execution_cannot_cross_invoice_or_precede_approval(self):
        for changes in [{'invoice_id':'MISSING'},{'approved':'2026-09-08'}]:
            self.d=fixture();self.d['ap_payment_plans'][0].update(changes);self.assertIsNone(self.data().plans['PL']['remaining_cents'])
    def test_unapproved_plan_with_execution_is_visible_issue(self):
        self.d['ap_payment_plans'][0].update(status='待审批',approved=None);self.assertTrue(self.data().plans['PL']['issues'])
    def test_invoice_lines_compete_for_receipt_quantity_across_invoices(self):
        self.d['ap_invoices'].append({**self.d['ap_invoices'][0],'id':'I2','invoice_no':'VAT2'})
        self.d['ap_invoice_lines'].append({**self.d['ap_invoice_lines'][0],'id':'L2','invoice_id':'I2'})
        d=self.data();self.assertEqual(d.receipts['R']['unbilled_qty'],-100);self.assertTrue(d.receipts['R']['issues']);self.assertTrue(d.invoices['I']['match_issues']);self.assertEqual(d.invoices['I']['balance_cents'],6000)
    def test_partial_billing_reference_uses_decimal_rounding(self):
        self.d['ap_invoice_lines'][0].update(qty=33.3333,net_cents=3333,tax_cents=433)
        d=self.data();self.assertEqual(d.receipts['R']['reference_net_cents'],6667)
    def test_missing_tax_terms_or_unit_mismatch_not_guessed(self):
        self.d['purchase_terms']=[];d=self.data();self.assertIsNone(d.receipts['R']['reference_net_cents']);self.assertTrue(d.invoices['I']['match_issues'])
    def test_receipt_quarantine_does_not_cancel_invoice(self):
        self.d['receipts'][0]['status']='隔离';d=self.data();self.assertTrue(d.invoices['I']['match_issues']);self.assertEqual(d.invoices['I']['balance_cents'],6000)
    def test_due_day_not_overdue_and_settled_not_in_aging(self):
        self.d['ap_invoices'][0]['due']='2026-10-01';self.assertEqual(self.data().invoices['I']['stage'],'due_today')
        self.d['ap_adjustments'][0].update(delta_cents=-7300,occurred='2026-09-12');d=self.data();self.assertEqual(d.invoices['I']['stage'],'settled');self.assertEqual(d.invoices['I']['overdue_days'],0)
    def test_summary_selection_uses_same_scope_and_no_false_zero(self):
        d=self.data();f=ap.params({'supplier_id':'S'});self.assertEqual(ap.summary(d.selected(f),'invoices')['balance_cents'],6000)
        f['supplier_id']='missing';s=ap.summary(d.selected(f),'invoices');self.assertEqual(s['rows'],0);self.assertIsNone(s['balance_cents'])
    def test_invalid_query_is_explicit(self):
        for p in [{'tab':'bad'},{'stage':'bad'},{'bucket':'bad'},{'match':'bad'},{'q':'x'*201}]:
            with self.assertRaises(ValueError):ap.params(p)
    def test_source_inputs_not_mutated(self):
        before=copy.deepcopy(self.d);self.data();self.assertEqual(before,self.d)
    def test_allocation_order_does_not_change_other_payment_values(self):
        self.d['ap_payments'].append({**self.d['ap_payments'][0],'id':'P2','document_no':'PV2'})
        self.d['ap_allocations'].append({**self.d['ap_allocations'][0],'id':'BAD','payment_id':'P2','amount_cents':-100,'plan_id':None})
        before=self.data();self.d['ap_allocations'].reverse();after=self.data()
        self.assertEqual(before.payments['P']['unallocated_cents'],after.payments['P']['unallocated_cents']);self.assertEqual(before.invoices['I']['balance_cents'],after.invoices['I']['balance_cents'])
    def test_duplicate_payment_voucher_is_not_double_counted(self):
        self.d['ap_payments'].append({**self.d['ap_payments'][0],'id':'P2'});d=self.data();self.assertTrue(all(r['unallocated_cents'] is None for r in d.payments.values()))
    def test_date_unit_and_amount_errors_are_explicit(self):
        for changes in [{'net_cents':True},{'tax_cents':-1},{'due':'bad'},{'issued':'2026-09-06'},{'currency':'USD'},{'status':'无法识别'}]:
            self.d=fixture();self.d['ap_invoices'][0].update(changes);self.assertIsNone(self.data().invoices['I']['balance_cents'])
    def test_invalid_or_future_plan_not_silently_counted(self):
        for changes in [{'amount_cents':1000},{'approved':'bad'},{'planned':'2026-09-03'},{'approved':'2026-10-02'},{'status':'未知'}]:
            self.d=fixture();self.d['ap_payment_plans'][0].update(changes);self.assertIsNone(self.data().plans['PL']['remaining_cents'])
    def test_missing_receipt_or_invalid_line_remains_matching_issue(self):
        for changes in [{'receipt_id':'missing'},{'qty':None},{'tax_bps':10001},{'net_cents':None}]:
            self.d=fixture();self.d['ap_invoice_lines'][0].update(changes);d=self.data();self.assertEqual(d.invoices['I']['balance_cents'],6000);self.assertTrue(d.invoices['I']['match_issues'])
    def test_receipt_matching_filter_includes_price_and_quality(self):
        self.d['receipts'][0]['status']='隔离';d=self.data();self.assertEqual(len(d.selected(ap.params({'tab':'receipts','match':'issues'}))),1)

class SupplierAPITests(PlatformCase):
    def setUp(self):
        super().setUp();self.finance=User.objects.create_user('finance',password='test-password');g=Group.objects.create(name='finance');self.finance.groups.add(g)
        for ds,rows in fixture().items():
            for r in rows:self.record(ds,r)
        self.client.force_login(self.finance)
    def payload(self):
        receipt=self.client.get('/api/payables/invoices/I').json()['receipt']
        return dict(version=0,status='供应商对账中',owner='模拟财务岗位',due_date='2026-10-08',note='核对模拟发票和核销关系',receipt=receipt)
    def test_board_all_four_scopes(self):
        for tab,total in [('invoices',1),('payments',1),('plans',1),('receipts',1)]:
            r=self.client.get('/api/payables',{'tab':tab});self.assertEqual(r.status_code,200);self.assertEqual(r.json()['total'],total);self.assertEqual(r['Cache-Control'],'no-store')
        r=self.client.get('/api/payables').json();self.assertEqual(r['summary']['balance_cents'],6000);self.assertEqual(r['suppliers'][0]['balance_cents'],6000);self.assertEqual(r['facets']['all'],1)
    def test_filters_and_zero_results_not_fabricated(self):
        r=self.client.get('/api/payables?supplier_id=missing').json();self.assertEqual(r['total'],0);self.assertIsNone(r['summary']['balance_cents'])
        r=self.client.get('/api/payables?stage=settled').json();self.assertEqual(r['total'],0)
    def test_aging_uses_entire_filtered_population_not_page(self):
        for i in range(30):
            row={**fixture()['ap_invoices'][0],'id':f'I{i}','invoice_no':f'VAT-{i}','due':'2026-10-10'}
            self.record('ap_invoices',row)
        first=self.client.get('/api/payables').json();second=self.client.get('/api/payables?page=2').json()
        self.assertEqual(first['aging'],second['aging']);self.assertEqual(sum(x['rows'] for x in first['aging']),31)
        self.assertEqual(sum(x['balance_cents'] or 0 for x in first['aging']),first['summary']['balance_cents'])
        filtered=self.client.get('/api/payables?bucket=d1_30').json()
        self.assertEqual(filtered['total'],1);self.assertEqual(sum(x['balance_cents'] or 0 for x in filtered['aging']),6000)
        empty=self.client.get('/api/payables?supplier_id=missing').json()
        self.assertTrue(all(x['balance_cents'] is None for x in empty['aging']))
    def test_excluded_draft_is_not_mislabeled_as_future(self):
        row={**fixture()['ap_invoices'][0],'id':'D','invoice_no':'DRAFT','status':'草稿'};self.record('ap_invoices',row)
        r=self.client.get('/api/payables?bucket=future').json()
        self.assertEqual(r['total'],1);self.assertEqual(r['rows'][0]['bucket_label'],'未计入应付')
        bucket=next(x for x in r['aging'] if x['key']=='future');self.assertEqual(bucket['rows'],1);self.assertIsNone(bucket['balance_cents'])
    def test_all_detail_types_and_relationships(self):
        for kind,key in [('invoices','I'),('payments','P'),('plans','PL'),('receipts','R')]:
            r=self.client.get(f'/api/payables/{kind}/{key}');self.assertEqual(r.status_code,200);self.assertEqual(r.json()['row']['id'],key)
        r=self.client.get('/api/payables/invoices/I').json()['row'];self.assertEqual(len(r['ledger']),3);self.assertEqual(r['plans'],['PL'])
    def test_permissions_on_board_details_exports_and_raw_datasets(self):
        self.client.force_login(self.quality)
        for url in ['/api/payables','/api/payables/export','/api/payables/invoices/I','/api/payables/invoices/I/evidence','/api/payables/invoices/I/history',*['/api/records/'+ds for ds in ap.DATASETS]]:self.assertEqual(self.client.get(url).status_code,403,url)
        self.assertEqual(self.post('/api/payables/invoices/I/follow-up',{}).status_code,403)
        self.client.logout();self.assertEqual(self.client.get('/api/payables').status_code,401)
    def test_viewer_operations_and_inactive_roles_cannot_access(self):
        for role in ['viewer','operations']:
            u=User.objects.create_user(role,password='test-password');u.groups.add(Group.objects.create(name=role));self.client.force_login(u);self.assertEqual(self.client.get('/api/payables').status_code,403)
    def test_sources_are_receipt_guarded_and_include_original_rows(self):
        receipt=self.client.get('/api/payables/invoices/I').json()['receipt'];r=self.client.get('/api/payables/invoices/I/evidence',{'receipt':receipt});self.assertEqual(r.status_code,200)
        v=r.json();self.assertEqual({x['filename'] for x in v['rows']},{'unit-test.xlsx'});self.assertFalse(v['can_download_original']);self.assertGreater(v['total'],5)
        self.assertEqual(self.client.get('/api/payables/invoices/I/evidence?receipt=stale').status_code,409)
    def test_export_exact_values_filters_and_formula_escaping(self):
        obj=Record.objects.get(dataset='suppliers');obj.values['name']='=1+1';obj.save();r=self.client.get('/api/payables').json()
        res=self.client.get('/api/payables/export',{'receipt':r['receipt']});self.assertEqual(res.status_code,200)
        rows=list(csv.reader(io.StringIO(res.content.decode('utf-8-sig'))));self.assertEqual(len(rows),5);self.assertEqual(rows[4][3],"'=1+1");self.assertEqual(rows[4][12],'6000');self.assertTrue(AuditEvent.objects.filter(action='payable.export').exists())
    def test_old_receipt_rejected_when_records_or_calculation_change(self):
        receipt=self.client.get('/api/payables').json()['receipt'];Record.objects.filter(dataset='suppliers').update(updated_at='2027-01-01T00:00:00Z')
        self.assertEqual(self.client.get('/api/payables/export',{'receipt':receipt}).status_code,409)
        with patch('app.payable_views.receipt',return_value='new-code'):self.assertEqual(self.client.get('/api/payables/export',{'receipt':receipt}).status_code,409)
    def test_followup_version_preserves_facts_and_history(self):
        before=list(Record.objects.order_by('id').values_list('values',flat=True));p=self.payload();r=self.post('/api/payables/invoices/I/follow-up',p);self.assertEqual(r.status_code,200);self.assertEqual(r.json()['follow_up']['version'],1)
        self.assertEqual(self.post('/api/payables/invoices/I/follow-up',p).status_code,409);p.update(version=1,receipt='stale');self.assertEqual(self.post('/api/payables/invoices/I/follow-up',p).status_code,409)
        self.assertEqual(before,list(Record.objects.order_by('id').values_list('values',flat=True)));self.assertEqual(self.client.get('/api/payables/invoices/I/history').json()['rows'][0]['actor'],'finance')
    def test_invalid_followup_and_csrf_rejected(self):
        p=self.payload()
        for changes in [{'version':True},{'status':'paid'},{'owner':''},{'note':'x'},{'due_date':'bad'}]:
            self.assertEqual(self.post('/api/payables/invoices/I/follow-up',{**p,**changes}).status_code,400)
        c=Client(enforce_csrf_checks=True);c.force_login(self.finance);self.assertEqual(c.post('/api/payables/invoices/I/follow-up',json.dumps(p),content_type='application/json').status_code,403)
    def test_audit_failure_rolls_back_followup_and_blocks_export(self):
        p=self.payload()
        with patch('app.payable_views.AuditEvent.objects.create',side_effect=RuntimeError('audit failed')):
            with self.assertRaises(RuntimeError):self.post('/api/payables/invoices/I/follow-up',p)
            with self.assertRaises(RuntimeError):self.client.get('/api/payables/export',{'receipt':p['receipt']})
        self.assertFalse(IssueDisposition.objects.filter(key='ap:invoices:I').exists())
    def test_malformed_queries_are_explicit(self):
        for query in ['tab=unknown','stage=unknown','match=unknown','page=0','page=-2','page=abc','page=100001']:
            self.assertEqual(self.client.get('/api/payables?'+query).status_code,400)
        self.assertEqual(self.client.get('/api/payables/invoices/MISSING').status_code,400)
