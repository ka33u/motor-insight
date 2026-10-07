import json,csv,io,copy
from unittest.mock import patch
from django.test import SimpleTestCase,Client
from django.contrib.auth.models import Group,User
from app import workforce as w,analytics
from app.models import Record,IssueDisposition,AuditEvent
from tests.test_platform import PlatformCase

def fixture():
    d={k:[] for k in w.TABLES}
    d['departments']=[{'id':'D1','name':'生产'}]
    d['employees']=[dict(id='E1',name='模拟甲',department_id='D1',role='操作员',skill_level='高级',active=True,hourly_cents=99999),dict(id='E2',name='模拟乙',department_id='D1',role='支持岗',skill_level='初级',active=True,hourly_cents=88888)]
    d['attendance']=[dict(id='A1',employee_id='E1',date='2026-09-21',shift='白班',productive_hours=2,setup_hours=1,wait_hours=4,rework_hours=1,support_hours=0,overtime_hours=1,scheduled_hours=8)]
    d['skills']=[dict(id='S1',employee_id='E1',process='绕线',level='高级',approved='2026-01-01',expires='2026-10-01',status='有效')]
    d['production_resources']=[dict(id='R1',employee_id='E1',process='绕线',station='1号工位',effective='2026-01-01')]
    d['resource_calendars']=[dict(id='C1',employee_id='E1',resource_id='R1',started='2026-09-21T08:00:00',finished='2026-09-21T16:00:00',shift='白班')]
    d['operations']=[dict(id='O1',employee_id='E1',work_order_id='W1',process='绕线',started='2026-09-21T08:00:00',finished='2026-09-21T12:00:00')]
    d['labor_entries']=[dict(id='L'+str(i),employee_id='E1',operation_id='O1',work_order_id='W1',started=f'2026-09-21T{a}:00:00',finished=f'2026-09-21T{b}:00:00',activity=kind,minutes=minutes,hourly_cents=99999,amount_cents=123456) for i,a,b,kind,minutes in [(1,'08','09','换型',60),(2,'09','11','生产',120),(3,'11','12','返工',60)]]
    return d

class WorkforceCalculationTests(SimpleTestCase):
    def setUp(self):self.d=fixture()
    def data(self,**q):return w.Workforce(self.d,w.filters(q))
    def test_overtime_subset_and_support_not_added_twice(self):
        d=self.data();r=d.people['E1']['row'];self.assertEqual(r['total_hours'],8);self.assertEqual(r['overtime_hours'],1);self.assertEqual(r['labor_hours'],4);self.assertEqual(r['calendar_hours'],8);self.assertEqual(r['issues'],[])
        s=d.summary(d.selected());self.assertEqual((s['objects'],s['verified'],s['missing']),(2,1,1));self.assertEqual(s['total_hours'],8)
    def test_missing_records_stay_null(self):
        r=self.data().people['E2']['row'];self.assertIsNone(r['total_hours']);self.assertIsNone(r['labor_hours']);self.assertIn('missing',r['flags']);self.assertEqual(r['issues'],[])
    def test_duplicate_attendance_or_negative_and_missing_classification_block(self):
        for mode in ['duplicate','negative','missing','overtime','schedule']:
            self.d=fixture()
            if mode=='duplicate':self.d['attendance'].append({**self.d['attendance'][0],'id':'A2'})
            if mode=='negative':self.d['attendance'][0]['wait_hours']=-1
            if mode=='missing':self.d['attendance'][0]['support_hours']=None
            if mode=='overtime':self.d['attendance'][0]['overtime_hours']=9
            if mode=='schedule':self.d['attendance'][0]['scheduled_hours']=7
            with self.subTest(mode=mode):
                r=self.data().people['E1']['row'];self.assertIsNone(r['total_hours']);self.assertIn('attention',r['flags'])
    def test_multiple_shifts_cannot_exceed_24_hours(self):
        self.d['attendance']=[{**self.d['attendance'][0],'id':str(i),'shift':str(i),'productive_hours':0,'setup_hours':0,'rework_hours':0,'wait_hours':13,'scheduled_hours':13} for i in [1,2]]
        self.assertIn('attention',self.data().people['E1']['row']['flags'])
    def test_overlapping_task_and_calendar_spans_block(self):
        for ds in ['labor_entries','resource_calendars']:
            self.d=fixture();self.d[ds].append({**self.d[ds][0],'id':'duplicate'})
            r=self.data().people['E1']['row'];self.assertIn('attention',r['flags']);self.assertIsNone(r['labor_hours'])
    def test_cross_midnight_clipping_conserves_hours(self):
        self.d['operations'][0].update(started='2026-09-20T23:00:00',finished='2026-09-21T01:00:00')
        self.d['labor_entries']=[{**self.d['labor_entries'][1],'started':'2026-09-20T23:00:00','finished':'2026-09-21T01:00:00'}]
        self.d['resource_calendars'][0].update(started='2026-09-20T22:00:00',finished='2026-09-21T02:00:00')
        self.d['attendance'][0].update(productive_hours=1,setup_hours=0,rework_hours=0,wait_hours=0,scheduled_hours=1,overtime_hours=0)
        r=self.data(**{'from':'2026-09-21','to':'2026-09-21'}).people['E1']['row'];self.assertEqual(r['labor_hours'],1);self.assertEqual(r['calendar_hours'],2);self.assertEqual(r['issues'],[])
    def test_future_sources_and_period_are_excluded(self):
        self.d['attendance'].append({**self.d['attendance'][0],'id':'AF','date':'2026-10-02'})
        self.assertEqual(self.data().people['E1']['row']['attendance_rows'],1)
        self.assertEqual(self.data(**{'from':'2026-09-22'}).people['E1']['row']['attendance_rows'],0)
    def test_wrong_operation_person_or_work_order_and_unknown_activity_block(self):
        for field,value in [('work_order_id','OTHER'),('operation_id','NONE'),('minutes',5),('activity','未知')]:
            self.d=fixture();self.d['labor_entries'][0][field]=value
            self.assertIn('attention',self.data().people['E1']['row']['flags'])
    def test_outside_resource_calendar_is_explicit(self):
        self.d['resource_calendars'][0]['started']='2026-09-21T10:00:00'
        r=self.data().people['E1']['row'];self.assertEqual(r['outside_hours'],2);self.assertIsNone(r['labor_hours'])
    def test_absent_calendar_is_unknown_not_zero_capacity(self):
        self.d['resource_calendars']=[];r=self.data().people['E1']['row'];self.assertIsNone(r['calendar_hours']);self.assertIsNone(r['outside_hours']);self.assertEqual(r['labor_hours'],4)
    def test_daily_discrepancies_do_not_cancel(self):
        self.d['attendance'][0].update(productive_hours=1,wait_hours=5)
        self.d['attendance'].append({**self.d['attendance'][0],'id':'A2','date':'2026-09-22','productive_hours':1,'setup_hours':0,'rework_hours':0,'wait_hours':7})
        r=self.data().people['E1']['row'];self.assertEqual(r['reconciliation_delta'],0);self.assertIsNone(r['total_hours']);self.assertEqual(len([x for x in r['issues'] if '合计不符' in x]),2)
    def test_trend_missing_day_and_requested_end_are_null(self):
        self.d['attendance'].append({**self.d['attendance'][0],'id':'A3','date':'2026-09-23','productive_hours':0,'setup_hours':0,'rework_hours':0,'wait_hours':8})
        d=self.data(**{'to':'2026-09-24'});trend=d.breakdown(d.selected())['daily'];self.assertEqual([r['hours'] for r in trend],[8,None,8,None])
    def test_skill_inclusive_dates_current_status_and_expiry(self):
        for expires,flag in [('2026-09-30','expired'),('2026-10-01','today'),('2026-10-31','soon'),('2026-11-01','effective')]:
            self.d['skills'][0]['expires']=expires;r=self.data(tab='skills').grants['S1'];self.assertIn(flag,r['flags'])
        self.d['skills'][0]['status']='撤销';self.assertFalse(self.data(tab='skills').grants['S1']['effective'])
    def test_future_inactive_and_bad_grants(self):
        for change,flag in [(dict(approved='2026-11-01',expires='2027-01-01'),'future'),(dict(approved='2027-01-01'),'attention'),(dict(status='神秘状态'),'attention')]:
            self.d=fixture();self.d['skills'][0].update(change);self.assertIn(flag,self.data(tab='skills').grants['S1']['flags'])
        self.d=fixture();self.d['employees'][0]['active']=False;self.assertIn('inactive',self.data(tab='skills').grants['S1']['flags'])
    def test_duplicate_grants_do_not_multiply_people_or_pairs(self):
        self.d['skills'].append({**self.d['skills'][0],'id':'S2'});d=self.data(tab='skills');s=d.summary(d.selected());self.assertEqual((s['objects'],s['effective_people'],s['effective_pairs']),(2,1,1))
        self.assertEqual(d.breakdown(d.selected())['processes'][0]['effective_people'],1)
    def test_missing_authorization_has_assignment_gap_even_without_grants(self):
        self.d['skills']=[];d=self.data(tab='skills');b=d.breakdown(d.selected());self.assertEqual(b['processes'][0]['unmatched_assigned'],1);self.assertEqual(b['assignment_gaps'][0]['employee_id'],'E1')
    def test_orphan_records_report_global_issue(self):
        self.d['skills'][0]['employee_id']='MISSING';d=self.data(tab='skills');self.assertTrue(d.global_issues);self.assertFalse(d.grants['S1']['effective'])
    def test_scope_unknown_department_and_no_search_matches_are_empty(self):
        for args in [dict(department='NO'),dict(q='NO')]:
            d=self.data(**args);self.assertEqual(d.selected(),[]);self.assertIsNone(d.summary([])['total_hours']);self.assertEqual(d.breakdown([])['daily'],[])
        for args in [{'tab':'skills','from':'2026-09-01'},{'process':'绕线'},{'tab':'bad'},{'from':'2026-10-02'},{'from':'2026-09-22','to':'2026-09-21'},{'family':'YE3'},{'from':'2020-01-01'}]:
            with self.assertRaises(ValueError):w.filters(args)
    def test_source_provenance_unique_and_financial_fields_absent(self):
        d=self.data().detail('E1');self.assertEqual(len(d['sources']),len({(r['dataset'],r['key']) for r in d['sources']}));self.assertNotIn('cents',json.dumps(d));self.assertNotIn('99999',json.dumps(d))
    def test_skill_id_search_keeps_assignment_context_and_bad_resource_is_explicit(self):
        d=self.data(tab='skills',q='S1');self.assertEqual(d.breakdown(d.selected())['processes'][0]['assigned_people'],1)
        self.d['production_resources'][0]['effective']='not-a-date';d=self.data(tab='skills');self.assertTrue(d.global_issues)

class WorkforceApiTests(PlatformCase):
    def setUp(self):
        super().setUp()
        for ds,rows in fixture().items():
            for r in rows:self.record(ds,r)
        self.client.force_login(self.admin)
    def payload(self):return dict(version=0,status='待授权复核',owner='模拟人事岗位',due_date='2026-10-06',note='核对来源授权与固定岗位，仅作演练跟进',data_revision=list(analytics.revision()))
    def test_auth_roles_all_routes_and_no_money_leak(self):
        urls=['/api/workforce','/api/workforce?tab=skills','/api/workforce/E1','/api/workforce/E1/evidence','/api/workforce/E1/history','/api/workforce/export']
        for url in urls:
            r=self.client.get(url);self.assertEqual(r.status_code,200);self.assertEqual(r.headers['Cache-Control'],'no-store');self.assertNotIn('cents',r.content.decode());self.assertNotIn('99999',r.content.decode())
        self.client.force_login(self.quality)
        for url in urls:self.assertEqual(self.client.get(url).status_code,403)
        self.assertEqual(self.post('/api/workforce/E1/follow-up',self.payload()).status_code,403)
        self.assertEqual(Client().get('/api/workforce').status_code,401)
    def test_operations_allowed_but_cannot_download_original(self):
        user=User.objects.create_user('operations');user.groups.add(Group.objects.create(name='operations'));self.client.force_login(user)
        self.assertEqual(self.client.get('/api/workforce').status_code,200);self.assertFalse(self.client.get('/api/workforce/E1/evidence').json()['can_download_original'])
    def test_stage_only_changes_list_export_matches_and_empty_filters(self):
        r=self.client.get('/api/workforce?stage=missing').json();self.assertEqual(r['summary']['objects'],2);self.assertEqual(r['total'],1);self.assertEqual(r['rows'][0]['id'],'E2')
        exported=list(csv.reader(io.StringIO(self.client.get('/api/workforce/export?stage=missing').content.decode('utf-8-sig'))));self.assertEqual(exported[3][0],'E2');self.assertEqual(len(exported),4)
        self.assertEqual(self.client.get('/api/workforce?department=NONE').json()['total'],0)
    def test_followup_versions_source_revision_and_facts_unchanged(self):
        before=list(Record.objects.values_list('values',flat=True));p=self.payload();r=self.post('/api/workforce/E1/follow-up',p);self.assertEqual(r.status_code,200);self.assertEqual(r.json()['follow_up']['version'],1)
        self.assertEqual(self.post('/api/workforce/E1/follow-up',p).status_code,409)
        p.update(version=1,data_revision=[0,'stale']);self.assertEqual(self.post('/api/workforce/E1/follow-up',p).status_code,409)
        self.assertEqual(before,list(Record.objects.values_list('values',flat=True)));self.assertEqual(len(self.client.get('/api/workforce/E1/history').json()['rows']),1)
    def test_invalid_followup_and_csrf_rejected(self):
        for change in [dict(status='批准上岗'),dict(version=True),dict(note='短'),dict(due_date='tomorrow')]:
            self.assertEqual(self.post('/api/workforce/E1/follow-up',{**self.payload(),**change}).status_code,400)
        c=Client(enforce_csrf_checks=True);c.force_login(self.admin);self.assertEqual(c.post('/api/workforce/E1/follow-up',json.dumps(self.payload()),content_type='application/json').status_code,403)
        self.assertEqual(self.client.get('/api/workforce/MISSING').status_code,404)
    def test_audit_failure_rolls_back_followup(self):
        with patch('app.workforce_views.AuditEvent.objects.create',side_effect=RuntimeError('audit unavailable')):
            with self.assertRaises(RuntimeError):self.post('/api/workforce/E1/follow-up',self.payload())
        self.assertFalse(IssueDisposition.objects.filter(key='workforce:E1').exists())
    def test_csv_formula_guard(self):
        row=Record.objects.get(dataset='employees',business_key='E1');row.values['name']='=1+1';row.save()
        out=self.client.get('/api/workforce/export').content.decode('utf-8-sig');self.assertIn("'=1+1",out)
