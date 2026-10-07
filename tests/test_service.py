import copy,csv,io,json
from unittest.mock import patch
from django.test import SimpleTestCase,Client
from django.contrib.auth.models import User,Group
from tests.test_platform import PlatformCase
from app import service_board as s,analytics
from app.models import Record,IssueDisposition

def fixture():
    d={k:[] for k in s.TABLES}
    d['customers']=[dict(id='C1',name='模拟客户')];d['products']=[dict(id='P1',family='YE3',model='定制型')]
    d['units']=[dict(id='SN1',product_id='P1',work_order_id='W1',assembly_at='2026-09-20T08:00:00')];d['work_orders']=[dict(id='W1')]
    d['orders']=[dict(id='O1',customer_id='C1')];d['order_lines']=[dict(id='L1',order_id='O1',product_id='P1')]
    d['shipments']=[dict(id='S1',order_line_id='L1',shipped='2026-09-21T08:00:00')];d['shipment_units']=[dict(id='PK1',shipment_id='S1',unit_id='SN1')]
    d['employees']=[dict(id='E1',name='模拟服务员',hourly_cents=998877)]
    d['service']=[dict(id='SH1',unit_id='SN1',customer_id='C1',reported='2026-09-25T08:00:00',response='2026-09-25T08:45:00',closed=None,failure='运行噪声',environment='风机',status='跟进中',cost_cents=5000),dict(id='SH2',unit_id='SN1',customer_id='C1',reported='2026-09-26T08:00:00',response='2026-09-26T09:00:00',closed='2026-09-26T16:00:00',failure='接线咨询',environment='输送',status='已关闭',cost_cents=0)]
    d['service_events']=[dict(id='EV1',service_id='SH1',occurred='2026-09-25T08:00:00',kind='客户报修',owner_id='E1',description='模拟报修',channel='电话',source_kind='合成记录'),dict(id='EV2',service_id='SH1',occurred='2026-09-25T08:45:00',kind='首次响应',owner_id='E1',description='模拟响应',channel='电话',source_kind='合成记录')]
    d['service_tasks']=[dict(id='T1',service_id='SH1',created='2026-09-25T09:00:00',due='2026-09-26T09:00:00',completed=None,status='待资料',kind='补充资料',owner_id='E1',description='模拟待补充资料',result=None),dict(id='T2',service_id='SH2',created='2026-09-26T09:00:00',due='2026-09-26T12:00:00',completed='2026-09-26T13:00:00',status='已完成',kind='核对记录',owner_id='E1',description='模拟核对',result='模拟完成')]
    d['service_conditions']=[dict(id='G1',service_id='SH1',recorded='2026-09-25T10:00:00',item='供电',value=0,unit='V',description='客户自报待核实',source_kind='客户自报（模拟）',status='待核实',owner_id='E1')]
    return d

class ServiceCalculations(SimpleTestCase):
    def setUp(self):self.d=fixture()
    def board(self,cutoff=None,**q):return s.ServiceBoard(self.d,s.filters(q),cutoff)
    def test_case_grain_response_closed_open_and_repeated_sn(self):
        b=self.board();v=b.summary(b.selected());self.assertEqual((v['objects'],v['units'],v['repeat_units'],v['open'],v['closed']),(2,1,1,1,1));self.assertEqual(v['response_hours'],.875);self.assertEqual(v['closed_hours'],8);self.assertEqual(v['cost_cents'],5000);self.assertFalse(b.cases['SH1']['row']['issues'])
    def test_tasks_not_joined_into_case_counts_and_overdue(self):
        b=self.board(tab='tasks');v=b.summary(b.selected());self.assertEqual((v['objects'],v['open'],v['done'],v['overdue'],v['late']),(2,1,1,1,1))
    def test_filters_are_case_reported_cohort_for_both_tabs(self):
        b=self.board(tab='tasks',**{'from':'2026-09-26','customer':'C1'});self.assertEqual([r['id'] for r in b.selected()],['T2'])
        self.assertEqual(self.board(customer='unknown').selected(),[]);self.assertEqual(self.board(failure='接线咨询').selected()[0]['id'],'SH2')
    def test_empty_measures_remain_null(self):
        b=self.board(product='missing');v=b.summary(b.selected());self.assertEqual(v['objects'],0);self.assertIsNone(v['response_hours']);self.assertIsNone(v['closed_hours']);self.assertIsNone(v['cost_cents'])
    def test_future_case_and_future_child_excluded(self):
        self.d['service'][1]['reported']='2026-10-02T08:00:00';self.d['service_events'][0]['occurred']='2026-10-02T08:00:00';self.d['service_conditions'][0]['recorded']='2026-10-02T08:00:00';b=self.board();self.assertEqual(len(b.selected()),1);self.assertEqual(b.cases['SH1']['row']['event_count'],1);self.assertEqual(b.cases['SH1']['conditions'],[])
    def test_future_close_and_response_use_asof(self):
        self.d['service'][0].update(response='2026-10-02T08:00:00',closed='2026-10-02T09:00:00',status='已关闭');r=self.board().cases['SH1']['row'];self.assertIn('open',r['flags']);self.assertIn('no_response',r['flags']);self.assertIsNone(r['response_hours']);self.assertIsNone(r['closed_hours'])
    def test_time_order_and_missing_close_unknown(self):
        for change in [dict(response='2026-09-24T08:00:00'),dict(closed='2026-09-25T08:30:00',status='已关闭'),dict(status='已关闭'),dict(response='bad'),dict(response='2026-09-25T08:45:00+08:00')]:
            self.d=fixture();self.d['service'][0].update(change);r=self.board().cases['SH1']['row'];self.assertTrue(r['time_issues']);self.assertNotIn('open',r['flags']);self.assertNotIn('closed',r['flags'])
    def test_missing_response_not_zero(self):
        self.d['service'][0]['response']=None;r=self.board().cases['SH1']['row'];self.assertIsNone(r['response_hours']);self.assertIn('no_response',r['flags'])
    def test_bad_reported_goes_global_not_silent_zero(self):
        self.d['service'][0]['reported']='invalid';b=self.board();self.assertTrue(b.global_issues);self.assertEqual(len(b.selected()),1)
    def test_customer_mismatch_does_not_hide_service_elapsed(self):
        self.d['orders'][0]['customer_id']='C2';r=self.board().cases['SH1']['row'];self.assertTrue(r['link_issues']);self.assertEqual(r['response_hours'],.75)
    def test_missing_packing_does_not_allocate_by_work_order(self):
        self.d['shipment_units']=[];r=self.board().cases['SH1']['row'];self.assertFalse(r['shipment_customer_match']);self.assertTrue(r['link_issues'])
    def test_future_shipment_not_customer_evidence(self):
        self.d['shipments'][0]['shipped']='2026-09-27T08:00:00';r=self.board().cases['SH1'];self.assertFalse(r['row']['shipment_customer_match']);self.assertEqual(r['shipments'],[])
    def test_duplicate_packing_and_wrong_product_flag(self):
        self.d['shipment_units'].append({**self.d['shipment_units'][0],'id':'PK2'});self.assertFalse(self.board().cases['SH1']['row']['shipment_customer_match']);self.d=fixture();self.d['order_lines'][0]['product_id']='P2';self.assertTrue(self.board().cases['SH1']['row']['link_issues'])
    def test_task_future_completion_remains_open_asof(self):
        self.d['service_tasks'][0].update(status='已完成',completed='2026-10-02T09:00:00');r=self.board(tab='tasks').selected()[0];self.assertIn('overdue',r['flags']);self.assertIsNone(r['completed_as_of'])
    def test_task_invalid_chronology_status_owner_block(self):
        for change in [dict(due='2026-09-24T08:00:00'),dict(completed='2026-09-24T08:00:00',status='已完成'),dict(owner_id='missing'),dict(status='已完成'),dict(created='bad')]:
            self.d=fixture();self.d['service_tasks'][0].update(change);r=self.board().cases['SH1']['tasks'][0];self.assertIn('attention',r['flags']);self.assertNotIn('overdue',r['flags'])
    def test_task_due_exactly_cutoff_not_overdue(self):
        self.d['service_tasks'][0]['due']=analytics.AS_OF;self.assertNotIn('overdue',self.board().cases['SH1']['tasks'][0]['flags'])
    def test_zero_customer_value_and_missing_are_distinct(self):
        r=self.board().cases['SH1']['conditions'][0];self.assertEqual(r['value'],0);self.assertFalse(r['issues']);self.assertEqual(self.board().cases['SH1']['row']['unverified_conditions'],1)
        self.d['service_conditions'][0].update(value=None,unit='V',status='未提供');self.assertEqual(self.board().cases['SH1']['row']['missing_conditions'],1);self.assertFalse(self.board().cases['SH1']['conditions'][0]['issues'])
    def test_condition_nonfinite_unit_mismatch_or_unknown_status_flag(self):
        for change in [dict(value=float('nan')),dict(unit=None),dict(status='未提供'),dict(status='现场通过')]:
            self.d=fixture();self.d['service_conditions'][0].update(change);self.assertTrue(self.board().cases['SH1']['conditions'][0]['issues'])
    def test_duplicate_anchor_wrong_time_and_orphan_visible(self):
        self.d['service_events'].append({**self.d['service_events'][0],'id':'EV3'});self.assertTrue(self.board().cases['SH1']['row']['issues']);self.d['service_events'][0]['service_id']='missing';self.assertTrue(self.board().global_issues)
    def test_negative_money_is_unknown_not_zero(self):
        self.d['service'][0]['cost_cents']=-1;b=self.board();self.assertIsNone(b.summary(b.selected())['cost_cents']);self.assertEqual(b.summary(b.selected())['cost_coverage'],1)
    def test_evidence_refs_unique_and_salary_not_returned(self):
        o=self.board().detail('SH1');refs=o['sources'];self.assertEqual(len(refs),len({(x['dataset'],x['key']) for x in refs}));self.assertNotIn('hourly_cents',json.dumps(o));self.assertNotIn('cents',json.dumps(s.safe(o,False)))
    def test_bad_filters_and_scope(self):
        for q in [dict(tab='unknown'),dict(stage='overdue'),dict(q='x'*151),{'from':'2026-10-03'},dict(injected='x'),{'from':'2026-09-26','to':'2026-09-25'}]:
            with self.assertRaises(ValueError):s.filters(q)
        with self.assertRaises(Record.DoesNotExist):self.board(customer='missing').detail('SH1')

class ServiceAPI(PlatformCase):
    def setUp(self):
        super().setUp()
        for ds,rows in fixture().items():
            for row in rows:self.record(ds,row)
        self.client.force_login(self.admin)
        q=patch('app.service_views.quality_board.current');self.mockq=q.start();self.addCleanup(q.stop);self.mockq.return_value.detail.return_value={'unit':{'id':'SN1'},'product':{},'sessions':[],'releases':[],'shipments':[],'nonconformities':[],'sources':[],'as_of':analytics.AS_OF,'notice':'模拟检测'}
    def payload(self):return {'status':'待资料核对','owner':'模拟负责人','due_date':'2026-10-05','note':'仅演练核对，不批准服务结案','version':0,'data_revision':list(analytics.revision())}
    def test_board_sources_money_and_auth(self):
        for user in [self.admin,self.quality]:
            self.client.force_login(user)
            for url in ['/api/service','/api/service?tab=tasks','/api/service/SH1','/api/service/SH1/evidence','/api/service/export']:
                r=self.client.get(url);self.assertEqual(r.status_code,200);self.assertEqual(r.headers['Cache-Control'],'no-store')
                if user==self.quality:self.assertNotIn('cents',r.content.decode());self.assertNotIn('台账服务费用分',r.content.decode())
        self.assertEqual(Client().get('/api/service').status_code,401)
    def test_stage_only_filters_list_and_export(self):
        d=self.client.get('/api/service?tab=tasks&stage=overdue').json();self.assertEqual(d['total'],1);self.assertEqual(d['summary']['objects'],2)
        rows=list(csv.reader(io.StringIO(self.client.get('/api/service/export?tab=tasks&stage=overdue').content.decode('utf-8-sig'))));self.assertEqual(len(rows),4);self.assertEqual(rows[3][0],'T1')
    def test_versions_and_stale_facts_cannot_overwrite(self):
        before=list(Record.objects.values_list('values',flat=True));p=self.payload();url='/api/service/SH1/follow-up';self.assertEqual(self.post(url,p).status_code,200);self.assertEqual(self.post(url,p).status_code,409);p.update(version=1,data_revision=[0,'stale']);self.assertEqual(self.post(url,p).status_code,409);self.assertEqual(before,list(Record.objects.values_list('values',flat=True)));self.assertEqual(len(self.client.get('/api/service/SH1/history').json()['rows']),1)
    def test_viewer_finance_cannot_follow_and_csrf(self):
        for role in ['viewer','finance']:
            u=User.objects.create_user(role);u.groups.add(Group.objects.create(name=role));self.client.force_login(u);self.assertEqual(self.client.get('/api/service').status_code,200);self.assertEqual(self.post('/api/service/SH1/follow-up',self.payload()).status_code,403)
        c=Client(enforce_csrf_checks=True);c.force_login(self.admin);self.assertEqual(c.post('/api/service/SH1/follow-up',json.dumps(self.payload()),content_type='application/json').status_code,403)
    def test_invalid_update_and_scope(self):
        for change in [dict(status='批准责任'),dict(version=True),dict(note='短'),dict(due_date='bad')]:self.assertEqual(self.post('/api/service/SH1/follow-up',{**self.payload(),**change}).status_code,400)
        self.assertEqual(self.client.get('/api/service/SH1?customer=missing').status_code,404)
        self.assertEqual(self.client.get('/api/service/missing').status_code,404)
    def test_audit_failure_rolls_back(self):
        with patch('app.service_views.AuditEvent.objects.create',side_effect=RuntimeError('audit unavailable')):
            with self.assertRaises(RuntimeError):self.post('/api/service/SH1/follow-up',self.payload())
        self.assertFalse(IssueDisposition.objects.filter(key='service:SH1').exists())
    def test_csv_formula_escape_and_source_permission(self):
        r=Record.objects.get(dataset='service_tasks',business_key='T1');r.values['description']='=1+1';r.save();self.assertIn("'=1+1",self.client.get('/api/service/export?tab=tasks').content.decode('utf-8-sig'));self.client.force_login(self.quality);self.assertFalse(self.client.get('/api/service/SH1/evidence').json()['can_download_original'])

    def test_missing_quality_snapshot_does_not_hide_service_case(self):
        self.mockq.return_value.detail.side_effect=Record.DoesNotExist()
        r=self.client.get('/api/service/SH1');self.assertEqual(r.status_code,200);self.assertIsNone(r.json()['quality']);self.assertEqual(r.json()['row']['id'],'SH1')
