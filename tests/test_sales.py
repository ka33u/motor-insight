import copy,csv,io,json
from unittest.mock import patch
from django.test import SimpleTestCase,Client
from django.contrib.auth.models import User,Group
from tests.test_platform import PlatformCase
from app import sales as s,analytics
from app.models import Record,IssueDisposition

def fixture():
    d={k:[] for k in s.TABLES}
    d['customers']=[dict(id='C1',name='模拟客户一',region='华东',industry='水泵'),dict(id='C2',name='模拟客户二')]
    d['products']=[dict(id='P1',model='模拟配置',family='YE3',price_cents=88888888)]
    d['employees']=[dict(id='E1',name='模拟销售一',hourly_cents=55555555),dict(id='E2',name='模拟销售二')]
    d['quotes']=[dict(id='Q1',customer_id='C1',product_id='P1',qty=10,unit_price_cents=10000,quote_date='2026-09-01',valid_until='2026-10-01',status='已转订单',reason='模拟转单'),dict(id='Q2',customer_id='C2',product_id='P1',qty=5,unit_price_cents=20000,quote_date='2026-09-20',valid_until='2026-09-30',status='待技术确认',reason='核对安装')]
    d['quote_details']=[dict(id='M1',quote_id='Q1',owner_id='E1',inquiry_date='2026-08-30',inquiry_no='XJ1',channel='设备配套',currency='CNY',tax_basis='未税',version='V1',outcome_date='2026-09-05',requirement='核对配置'),dict(id='M2',quote_id='Q2',owner_id='E2',inquiry_date='2026-09-19',inquiry_no='XJ2',channel='网站',currency='CNY',tax_basis='待确认',version='V1',outcome_date=None,requirement='核对安装')]
    d['orders']=[dict(id='O1',customer_id='C1',order_date='2026-09-05',currency='CNY',status='待生产')]
    d['order_lines']=[dict(id='L1',order_id='O1',product_id='P1',qty=10,unit_price_cents=9000)]
    d['quote_order_links']=[dict(id='A1',quote_id='Q1',order_line_id='L1',qty=10,confirmed='2026-09-05',status='有效',reference='客户采购单模拟索引')]
    d['quote_tasks']=[dict(id='T1',quote_id='Q1',owner_id='E1',created='2026-09-01',kind='商务',due='2026-09-04',completed='2026-09-05',status='已完成',description='核对订单',result='已登记'),dict(id='T2',quote_id='Q2',owner_id='E1',created='2026-09-20',kind='技术',due='2026-09-30',completed=None,status='待反馈',description='安装核对',result=None),dict(id='T3',quote_id='Q2',owner_id='E2',created='2026-09-20',kind='商务',due='2026-10-01',completed=None,status='待反馈',description='商务回访',result=None)]
    return d

class SalesCalculations(SimpleTestCase):
    def setUp(self):self.d=fixture()
    def board(self,cutoff=None,**f):return s.Sales(self.d,s.filters(f),cutoff)
    def test_quote_grain_and_exact_price_bridge(self):
        b=self.board();r=b.summary(b.selected());self.assertEqual((r['quotes'],r['linked_quotes'],r['valid_links'],r['order_lines']),(2,1,1,1));self.assertEqual((r['order_value_cents'],r['quote_reference_cents'],r['price_difference_cents']),(90000,100000,-10000));self.assertEqual(r['quote_days_median'],1.5)
    def test_partial_order_quantity_not_full_quote_value(self):
        self.d['quotes'][0].update(qty=15,status='部分转单');r=self.board().quotes['Q1']['row'];self.assertEqual((r['linked_qty'],r['unlinked_qty'],r['order_value_cents']),(10,5,90000));self.assertFalse(r['unproven'])
    def test_no_guessed_customer_product_join(self):
        self.d['quote_order_links']=[];r=self.board().quotes['Q1']['row'];self.assertTrue(r['unproven']);self.assertEqual(r['valid_links'],0);self.assertIsNone(r['order_value_cents'])
    def test_duplicate_link_pair_rejected(self):
        self.d['quote_order_links'].append({**self.d['quote_order_links'][0],'id':'A2','qty':1});r=self.board().quotes['Q1']['row'];self.assertEqual(r['valid_links'],0);self.assertIsNone(r['linked_qty'])
    def test_order_overallocation_checked_before_customer_filter(self):
        self.d['quotes'].append({**self.d['quotes'][0],'id':'Q3'});self.d['quote_details'].append({**self.d['quote_details'][0],'id':'M3','quote_id':'Q3','owner_id':'E2'});self.d['quote_order_links'].append({**self.d['quote_order_links'][0],'id':'A3','quote_id':'Q3','qty':1})
        b=self.board(owner='E1');self.assertEqual(b.selected()[0]['valid_links'],0);self.assertTrue(any('超额' in x for x in b.quotes['Q1']['links'][0]['issues']))
    def test_quote_overallocation_across_order_lines(self):
        self.d['order_lines'].append({**self.d['order_lines'][0],'id':'L2'});self.d['quote_order_links'].append({**self.d['quote_order_links'][0],'id':'A2','order_line_id':'L2','qty':1});self.assertEqual(self.board().quotes['Q1']['row']['valid_links'],0)
    def test_different_customer_product_or_missing_order_rejected(self):
        for ds,field,value in [('orders','customer_id','C2'),('order_lines','product_id','P2'),('order_lines','order_id','missing'),('orders','status','已取消')]:
            self.d=fixture();self.d[ds][0][field]=value;self.assertEqual(self.board().quotes['Q1']['row']['valid_links'],0)
    def test_bad_link_quantity_and_date_never_summed(self):
        for change in [dict(qty=True),dict(qty=0),dict(qty=-1),dict(qty=1.5),dict(confirmed='bad'),dict(confirmed='2026-08-31'),dict(status='待核对')]:
            self.d=fixture();self.d['quote_order_links'][0].update(change);r=self.board().quotes['Q1']['row'];self.assertEqual(r['valid_links'],0);self.assertIsNone(r['linked_qty'])
    def test_future_link_excluded(self):
        self.d['quote_order_links'][0]['confirmed']='2026-10-02';r=self.board().quotes['Q1'];self.assertEqual(r['links'],[]);self.assertTrue(r['row']['unproven'])
    def test_future_order_excluded(self):
        self.d['orders'][0]['order_date']='2026-10-02';self.assertEqual(self.board().quotes['Q1']['row']['valid_links'],0)
    def test_order_before_quote_or_confirm_before_order_rejected(self):
        for stamp in ['2026-08-31','2026-09-06']:
            self.d=fixture();self.d['orders'][0]['order_date']=stamp;self.assertEqual(self.board().quotes['Q1']['row']['valid_links'],0)
    def test_unknown_tax_or_currency_keeps_quantity_hides_compare(self):
        for change in [dict(tax_basis='含税'),dict(tax_basis='待确认'),dict(currency='USD')]:
            self.d=fixture();self.d['quote_details'][0].update(change);r=self.board().quotes['Q1']['row'];self.assertEqual(r['linked_qty'],10);self.assertEqual(r['comparable_links'],0);self.assertIsNone(r['order_value_cents'])
    def test_price_zero_retained_bad_values_not_compared(self):
        self.d['quotes'][0]['unit_price_cents']=0;self.assertEqual(self.board().quotes['Q1']['row']['quote_reference_cents'],0)
        for value in [True,-1,1.5,None]:
            self.d=fixture();self.d['quotes'][0]['unit_price_cents']=value;self.assertIsNone(self.board().quotes['Q1']['row']['order_value_cents'])
    def test_status_marker_is_not_conversion_proof(self):
        self.d['quote_order_links'][0]['qty']=5;r=self.board().quotes['Q1']['row'];self.assertTrue(r['unproven']);self.assertEqual(r['linked_qty'],5)
    def test_pending_quote_with_link_is_inconsistent(self):
        self.d['quotes'][0]['status']='跟进中';self.d['quote_details'][0]['outcome_date']=None;self.assertEqual(self.board().quotes['Q1']['row']['valid_links'],0)
    def test_expiry_day_boundary_and_closed_quotes_not_expired(self):
        self.assertFalse(self.board(cutoff='2026-09-30T23:59:59').quotes['Q2']['row']['expired']);b=self.board();self.assertTrue(b.quotes['Q2']['row']['expired']);self.assertFalse(b.quotes['Q1']['row']['expired'])
    def test_bad_or_future_quote_dates_visible_in_scope(self):
        self.d['quotes'][0]['quote_date']='bad';b=self.board();self.assertEqual(len(b.quotes),1);self.assertTrue(b.global_issues)
        self.d=fixture();self.d['quotes'][0]['quote_date']='2026-10-02';self.assertEqual(len(self.board().quotes),1)
    def test_missing_duplicate_metadata_prevents_price_assumptions(self):
        for rows in [[],[fixture()['quote_details'][0],{**fixture()['quote_details'][0],'id':'M3'}]]:
            self.d=fixture();self.d['quote_details']=rows;r=self.board().quotes['Q1']['row'];self.assertTrue(r['issues']);self.assertIsNone(r['order_value_cents'])
    def test_inquiry_date_and_outcome_errors_not_used(self):
        self.d['quote_details'][0]['inquiry_date']='2026-09-02';self.assertIsNone(self.board().quotes['Q1']['row']['quote_days'])
        for change in [dict(outcome_date=None),dict(outcome_date='2026-10-02'),dict(outcome_date='2026-08-31')]:
            self.d=fixture();self.d['quote_details'][0].update(change);self.assertFalse(self.board().quotes['Q1']['row']['state_known'])
    def test_tasks_summary_no_quote_multiplication(self):
        b=self.board(tab='tasks');r=b.summary(b.selected());self.assertEqual((r['tasks'],r['completed_tasks'],r['open_tasks'],r['overdue_tasks'],r['late_tasks']),(3,1,2,1,1))
    def test_task_date_boundary_and_future_completion(self):
        self.assertFalse(self.board(cutoff='2026-09-30T23:00:00').tasks['T2']['overdue']);self.assertFalse(self.board().tasks['T3']['overdue'])
        self.d['quote_tasks'][0]['completed']='2026-10-02';self.assertFalse(self.board().tasks['T1']['done']);self.assertTrue(self.board().tasks['T1']['open'])
    def test_future_tasks_excluded(self):
        self.d['quote_tasks'][1].update(created='2026-10-02',due='2026-10-03');b=self.board();self.assertNotIn('T2',b.tasks);self.assertEqual(b.quotes['Q2']['future_tasks'],1)
    def test_bad_task_dates_status_owner_unknown_not_zero_done(self):
        for change in [dict(due='bad'),dict(owner_id='missing'),dict(created='2026-08-01'),dict(due='2026-08-31'),dict(status='未知'),dict(completed=None),dict(completed='2026-08-31')]:
            self.d=fixture();self.d['quote_tasks'][0].update(change);t=self.board().tasks['T1'];self.assertTrue(t['issues']);self.assertFalse(t['done']);self.assertFalse(t['open'])
    def test_scope_intersects_customer_owner_family_quote_date(self):
        self.assertEqual([r['id'] for r in self.board(customer='C1',owner='E1',family='YE3',**{'to':'2026-09-10'}).selected()],['Q1'])
        self.assertEqual(self.board(customer='missing').selected(),[]);self.assertEqual(self.board(owner='E2',customer='C1').selected(),[])
    def test_task_owner_scope_is_distinct_from_quote_owner(self):
        b=self.board(tab='tasks',owner='E2',task_owner='E1');self.assertEqual([r['id'] for r in b.task_rows(b.selected())],['T2']);self.assertEqual(b.summary(b.selected())['quotes'],1)
    def test_empty_range_has_no_rate_or_money(self):
        b=self.board(product='missing');r=b.summary(b.selected());self.assertIsNone(r['quote_days_median']);self.assertIsNone(r['order_value_cents'])
    def test_orphan_children_and_sensitive_nested_values(self):
        for ds in ['quote_details','quote_order_links','quote_tasks']:self.d[ds][0]['quote_id']='missing'
        self.assertEqual(len(self.board().global_issues),3);self.assertNotIn('cents',json.dumps(s.safe(self.board().quotes,False)))
    def test_invalid_filter_rejected(self):
        for f in [dict(tab='bad'),dict(stage='done'),dict(task_owner='E1'),dict(quote_status='bad'),dict(unknown='x'),{'from':'2026-10-03'},{'from':'2026-09-02','to':'2026-09-01'}]:
            with self.assertRaises(ValueError):s.filters(f)

class SalesAPI(PlatformCase):
    def setUp(self):
        super().setUp()
        for ds,rows in fixture().items():
            for r in rows:self.record(ds,r)
        self.client.force_login(self.admin)
    def payload(self):return dict(status='待客户反馈',owner='销售岗位（模拟）',due_date='2026-10-05',note='核对安装条件及客户确认记录',version=0,data_revision=list(analytics.revision()))
    def test_auth_money_and_cache_policy(self):
        for user in [self.admin,self.quality]:
            self.client.force_login(user)
            for url in ['/api/sales','/api/sales?tab=tasks','/api/sales/Q1','/api/sales/Q1/evidence','/api/sales/export']:
                r=self.client.get(url);self.assertEqual(r.status_code,200,url);self.assertEqual(r.headers['Cache-Control'],'no-store')
                if user==self.quality:self.assertNotIn('cents',r.content.decode());self.assertNotIn('报价单价分',r.content.decode())
        self.assertEqual(Client().get('/api/sales').status_code,401)
    def test_scope_stage_and_export_agree(self):
        d=self.client.get('/api/sales?stage=expired').json();self.assertEqual(d['total'],1);self.assertEqual(d['summary']['quotes'],2)
        rows=list(csv.reader(io.StringIO(self.client.get('/api/sales/export?stage=expired').content.decode('utf-8-sig'))));self.assertEqual(len(rows),4);self.assertEqual(rows[3][0],'Q2')
        d=self.client.get('/api/sales?tab=tasks&stage=overdue').json();self.assertEqual(d['total'],1);self.assertEqual(d['summary']['tasks'],3)
    def test_detail_outside_scope_rejected(self):
        for url in ['/api/sales/Q1?customer=C2','/api/sales/missing','/api/sales/Q1/evidence?owner=E2']:self.assertEqual(self.client.get(url).status_code,404)
    def test_followup_preserves_facts_and_detects_versions(self):
        before=list(Record.objects.values_list('id','values','revision'));p=self.payload();url='/api/sales/Q2/follow-up'
        self.assertEqual(self.post(url,p).status_code,200);self.assertEqual(self.post(url,p).status_code,409);self.assertEqual(list(Record.objects.values_list('id','values','revision')),before)
        self.assertEqual(self.client.get('/api/sales/Q2/history').json()['rows'][0]['detail']['after']['version'],1)
        p.update(version=1,data_revision=['old']);self.assertEqual(self.post(url,p).status_code,409)
    def test_role_csrf_and_review_authority(self):
        self.client.force_login(self.quality);self.assertEqual(self.post('/api/sales/Q1/follow-up',self.payload()).status_code,403)
        c=Client(enforce_csrf_checks=True);c.force_login(self.admin);self.assertEqual(c.post('/api/sales/Q1/follow-up',json.dumps(self.payload()),content_type='application/json').status_code,403)
        u=User.objects.create_user('ops');u.groups.add(Group.objects.create(name='operations'));self.client.force_login(u);self.assertEqual(self.post('/api/sales/Q1/follow-up',{**self.payload(),'status':'演练已核对'}).status_code,403)
    def test_validation_and_audit_atomicity(self):
        for delta in [dict(status='批准报价'),dict(version=True),dict(note='短'),dict(due_date='bad'),dict(extra=1)]:self.assertEqual(self.post('/api/sales/Q1/follow-up',{**self.payload(),**delta}).status_code,400)
        with patch('app.sales_views.AuditEvent.objects.create',side_effect=RuntimeError('audit unavailable')):
            with self.assertRaises(RuntimeError):self.post('/api/sales/Q1/follow-up',self.payload())
        self.assertFalse(IssueDisposition.objects.filter(key='sales:Q1').exists())
    def test_formula_escape_and_original_download_guard(self):
        r=Record.objects.get(dataset='customers',business_key='C1');r.values['name']='=1+1';r.save();self.assertIn("'=1+1",self.client.get('/api/sales/export').content.decode('utf-8-sig'))
        self.client.force_login(self.quality);self.assertFalse(self.client.get('/api/sales/Q1/evidence').json()['can_download_original'])
