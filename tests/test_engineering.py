import copy,csv,io,json
from unittest.mock import patch
from django.test import SimpleTestCase,Client
from django.contrib.auth.models import User,Group
from tests.test_platform import PlatformCase
from app import engineering as e,analytics
from app.models import Record,IssueDisposition

def fixture():
    d={k:[] for k in e.TABLES}
    d['products']=[dict(id='P1',model='模拟定制电机',family='YE3',bom_version='B',route_version='R1',price_cents=12345678)]
    d['materials']=[dict(id='M1',name='模拟硅钢',unit='kg',unit_cost_cents=321),dict(id='M2',name='模拟轴承',unit='件',unit_cost_cents=888)]
    d['employees']=[dict(id='E1',name='模拟研发人',hourly_cents=456789)]
    d['bom']=[dict(id='B1',product_id='P1',material_id='M1',version='B',qty=1.2,scrap_allowance=.03,effective='2026-09-01',assembly_level='定子'),dict(id='B2',product_id='P1',material_id='M2',version='B',qty=1,scrap_allowance=0,effective='2026-09-01',assembly_level='转子')]
    d['routes']=[dict(id=key,product_id='P1',version='R1',sequence=10,process=name,branch=branch,minutes=minutes,mandatory=True,workshop='模拟车间') for key,name,branch,minutes in [('R1','冲片','定子',2),('R2','机加工','转子',3),('R3','装配','整机',1)]]
    d['route_dependencies']=[dict(id='D1',product_id='P1',from_route_id='R1',to_route_id='R3',lag_minutes=0,basis='模拟依赖'),dict(id='D2',product_id='P1',from_route_id='R2',to_route_id='R3',lag_minutes=2,basis='模拟依赖')]
    d['work_orders']=[dict(id='W1',product_id='P1',bom_version='B',route_version='R1',planned_start='2026-09-20',planned_qty=10)]
    d['projects']=[dict(id='PJ1',name='模拟验证项目',product_id='P1',owner_id='E1',planned_end='2026-09-30',actual_end=None,status='验证中',budget_cents=99998765),dict(id='PJ2',name='模拟转产项目',product_id='P1',owner_id='E1',planned_end='2026-09-29',actual_end='2026-10-01',status='已转产',budget_cents=0)]
    d['project_milestones']=[dict(id='MS1',project_id='PJ1',sequence=10,name='验证资料',planned_start='2026-09-28',planned_end='2026-09-30',actual_start='2026-09-28',actual_end=None,status='进行中',owner_id='E1',outcome='待反馈',record_no=None),dict(id='MS2',project_id='PJ2',sequence=10,name='转产记录',planned_start='2026-09-28',planned_end='2026-09-29',actual_start='2026-09-28',actual_end='2026-10-01',status='已完成',owner_id='E1',outcome='模拟记录完成',record_no='JL2')]
    d['engineering_changes']=[dict(id='EC1',product_id='P1',from_version='A',to_version='B',reason='模拟安装变更',effective='2026-09-01',approved_by='E1',status='已批准')]
    d['change_actions']=[dict(id='CA1',change_id='EC1',kind='文件回收',owner_id='E1',created='2026-09-28',due='2026-10-01',completed=None,status='待反馈',description='模拟回收范围',result=None,record_no=None),dict(id='CA2',change_id='EC1',kind='版本核对',owner_id='E1',created='2026-09-28',due='2026-09-30',completed='2026-10-01',status='已完成',description='模拟版本范围',result='有记录，附件未核对',record_no='CJ2')]
    return d

class EngineeringCalculations(SimpleTestCase):
    def setUp(self):self.d=fixture()
    def board(self,cutoff=None,**q):return e.Engineering(self.d,e.filters(q),cutoff)
    def test_product_grain_no_child_multiplication(self):
        b=self.board();s=b.summary(b.selected());self.assertEqual((s['objects'],s['bom_rows'],s['route_rows'],s['work_orders']),(1,2,3,1));self.assertEqual(s['attention'],0)
    def test_branch_sequence_and_merge_graph(self):
        graph=self.board().products['P1']['graph'];self.assertTrue(graph['valid']);self.assertEqual({n['id']:n['rank'] for n in graph['nodes']},{'R1':0,'R2':0,'R3':1});self.assertEqual(len(graph['edges']),2)
    def test_cycle_blocks_graph(self):
        self.d['route_dependencies'].append(dict(id='D3',product_id='P1',from_route_id='R3',to_route_id='R1',lag_minutes=0));g=self.board().products['P1']['graph'];self.assertFalse(g['valid']);self.assertEqual(g['nodes'],[]);self.assertTrue(any('环' in x for x in g['issues']))
    def test_missing_cross_product_and_version_dependencies(self):
        for change in [dict(to_route_id='missing'),dict(lag_minutes=-1)]:
            self.d=fixture();self.d['route_dependencies'][0].update(change);self.assertFalse(self.board().products['P1']['graph']['valid'])
        self.d=fixture();self.d['routes'][2]['product_id']='P2';self.assertTrue(self.board().global_issues);self.assertFalse(self.board().products['P1']['graph']['valid'])
        self.d=fixture();self.d['routes'][2]['version']='R2';self.assertFalse(self.board().products['P1']['graph']['valid'])
    def test_no_dependencies_and_duplicate_edge_not_healthy(self):
        self.d['route_dependencies']=[];self.assertFalse(self.board().products['P1']['graph']['valid'])
        self.d=fixture();self.d['route_dependencies'].append({**self.d['route_dependencies'][0],'id':'D3'});self.assertFalse(self.board().products['P1']['graph']['valid'])
    def test_route_invalid_minutes_and_sequence(self):
        for change in [dict(minutes=False),dict(minutes=0),dict(minutes=float('nan')),dict(sequence=True),dict(mandatory='是'),dict(branch='定子')]:
            self.d=fixture();self.d['routes'][1].update(change);self.assertFalse(self.board().products['P1']['graph']['valid'])
    def test_bom_effective_and_version_scope(self):
        self.d['bom'].append({**self.d['bom'][0],'id':'B3','version':'A'});self.d['bom'][1]['effective']='2026-10-02';p=self.board().products['P1'];self.assertEqual(len(p['bom']),1);self.assertEqual(len(p['other_bom']),2)
    def test_missing_bom_route_and_material_are_visible(self):
        for ds in ['bom','routes','materials']:
            self.d=fixture();self.d[ds]=[];self.assertTrue(self.board().products['P1']['row']['issues'])
    def test_bom_quantity_unit_and_scrap_checks(self):
        for change in [dict(qty=0),dict(qty=True),dict(qty=.5),dict(scrap_allowance=1),dict(scrap_allowance=-.1),dict(effective='bad')]:
            self.d=fixture();self.d['bom'][1].update(change);self.assertTrue(self.board().products['P1']['row']['issues'])
    def test_old_version_is_difference_not_automatic_invalidity(self):
        self.d['bom'] += [{**x,'id':x['id']+'A','version':'A'} for x in self.d['bom']]
        self.d['work_orders'][0]['bom_version']='A';p=self.board().products['P1'];self.assertIn('version_difference',p['row']['flags']);self.assertTrue(p['work_orders'][0]['version_rows_present']);self.assertFalse(p['row']['issues'])
    def test_uncovered_work_order_version_flagged(self):
        self.d['work_orders'][0]['bom_version']='Z';p=self.board().products['P1'];self.assertIn('attention',p['row']['flags']);self.assertFalse(p['work_orders'][0]['version_rows_present'])
    def test_project_grain_and_budget_zero(self):
        b=self.board(tab='projects');s=b.summary(b.selected());self.assertEqual((s['objects'],s['closed'],s['open'],s['overdue'],s['late']),(2,1,1,1,1));self.assertEqual((s['milestones'],s['completed_milestones'],s['overdue_milestones']),(2,1,1));self.assertEqual(s['budget_cents'],99998765)
    def test_empty_unknown_filters_no_fallback(self):
        for f in [dict(product='missing'),dict(family='unknown'),dict(tab='projects',owner='missing')]:self.assertEqual(self.board(**f).selected(),[])
        b=self.board(tab='projects',product='missing');self.assertIsNone(b.summary(b.selected())['budget_cents'])
    def test_project_period_is_planned_end_cohort(self):
        b=self.board(tab='projects',**{'from':'2026-09-30'});self.assertEqual([x['id'] for x in b.selected()],['PJ1'])
        self.assertEqual(self.board(tab='changes',**{'from':'2026-09-02'}).selected(),[])
    def test_date_deadline_boundary(self):
        p=self.board(tab='projects',cutoff='2026-09-30T23:00:00').projects['PJ1']['row'];self.assertNotIn('overdue',p['flags'])
        p=self.board(tab='projects',cutoff='2026-10-01T00:00:00').projects['PJ1']['row'];self.assertEqual(p['days_overdue'],1)
        self.assertFalse(self.board().changes['EC1']['actions'][0]['overdue'])
        self.assertTrue(self.board(cutoff='2026-10-02T00:00:00').changes['EC1']['actions'][0]['overdue'])
    def test_future_project_and_task_completion_not_counted(self):
        self.d['projects'][1]['actual_end']='2026-10-02';self.d['project_milestones'][1]['actual_end']='2026-10-02';p=self.board(tab='projects').projects['PJ2'];self.assertIn('open',p['row']['flags']);self.assertIsNone(p['row']['closed_as_of']);self.assertFalse(p['milestones'][0]['done'])
    def test_future_created_actions_separate(self):
        self.d['change_actions'][0].update(created='2026-10-02',due='2026-10-03');c=self.board().changes['EC1'];self.assertEqual(c['row']['actions'],1);self.assertEqual(c['future_actions'],1)
    def test_bad_project_state_has_unknown_lifecycle(self):
        for change in [dict(planned_end='bad'),dict(status='已转产'),dict(owner_id='missing')]:
            self.d=fixture();self.d['projects'][0].update(change);r=self.board(tab='projects').projects['PJ1']['row'];self.assertIn('attention',r['flags']);self.assertNotIn('open',r['flags']);self.assertNotIn('closed',r['flags'])
    def test_milestone_missing_invalid_dates_and_status(self):
        for change in [dict(actual_start=None),dict(actual_end='2026-09-27',status='已完成'),dict(planned_end='2026-09-27'),dict(status='未开始'),dict(sequence=True)]:
            self.d=fixture();self.d['project_milestones'][0].update(change);r=self.board(tab='projects').projects['PJ1'];self.assertTrue(r['row']['issues']);self.assertFalse(r['milestones'][0]['done'])
    def test_closed_project_with_open_child_not_implicitly_complete(self):
        self.d['project_milestones'][1].update(actual_end=None,status='进行中');r=self.board(tab='projects').projects['PJ2'];self.assertIn('attention',r['row']['flags']);self.assertEqual(r['row']['completed_milestones'],0)
    def test_missing_children_and_duplicate_sequence(self):
        self.d['project_milestones']=[];self.assertIn('attention',self.board().projects['PJ1']['row']['flags'])
        self.d=fixture();self.d['project_milestones'].append({**self.d['project_milestones'][0],'id':'MS3'});self.assertTrue(any('序号重复' in x for x in self.board().projects['PJ1']['row']['issues']))
    def test_change_approval_and_execution_and_baseline_separate(self):
        c=self.board().changes['EC1'];self.assertEqual(c['row']['status'],'已批准');self.assertEqual((c['row']['actions'],c['row']['completed_actions'],c['row']['pending_actions']),(2,1,1));self.assertIn('missing_baseline',c['row']['flags']);self.assertEqual(c['row']['before_bom_rows'],0);self.assertTrue(c['actions'][1]['late'])
    def test_orphans_reported(self):
        self.d['project_milestones'][0]['project_id']='missing';self.d['change_actions'][0]['change_id']='missing';self.assertEqual(len(self.board().global_issues),2)
    def test_sensitive_nested_values_removed(self):
        p=e.safe(self.board().products['P1'],False);self.assertNotIn('cents',json.dumps(p));self.assertNotIn('99998765',json.dumps(p))
    def test_invalid_filters_rejected(self):
        for q in [dict(tab='unknown'),dict(stage='closed'),dict(owner='E1'),{'from':'2026-10-01'},dict(tab='projects',**{'from':'2026-10-02','to':'2026-10-01'}),dict(q='x'*151),dict(unexpected='x')]:
            with self.assertRaises(ValueError):e.filters(q)

class EngineeringAPI(PlatformCase):
    def setUp(self):
        super().setUp()
        for ds,rows in fixture().items():
            for r in rows:self.record(ds,r)
        self.client.force_login(self.admin)
    def payload(self):return dict(status='待资料补齐',owner='研发责任岗位（模拟）',due_date='2026-10-05',note='核对阶段记录和原始签核附件',version=0,data_revision=list(analytics.revision()))
    def test_board_detail_evidence_and_money_permissions(self):
        for user in [self.admin,self.quality]:
            self.client.force_login(user)
            for kind,key in [('products','P1'),('projects','PJ1'),('changes','EC1')]:
                for url in [f'/api/engineering?tab={kind}',f'/api/engineering/{kind}/{key}?tab={kind}',f'/api/engineering/{kind}/{key}/evidence?tab={kind}',f'/api/engineering/export?tab={kind}']:
                    r=self.client.get(url);self.assertEqual(r.status_code,200,url);self.assertEqual(r.headers['Cache-Control'],'no-store')
                    if user==self.quality:
                        self.assertNotIn('cents',r.content.decode());self.assertNotIn('99998765',r.content.decode());self.assertNotIn('项目台账预算分',r.content.decode())
        self.assertEqual(Client().get('/api/engineering').status_code,401)
    def test_stage_list_export_and_summary_ranges(self):
        d=self.client.get('/api/engineering?tab=projects&stage=overdue').json();self.assertEqual(d['summary']['objects'],2);self.assertEqual(d['total'],1)
        raw=self.client.get('/api/engineering/export?tab=projects&stage=overdue').content.decode('utf-8-sig');rows=list(csv.reader(io.StringIO(raw)));self.assertEqual(len(rows),4);self.assertEqual(rows[3][0],'PJ1')
    def test_scope_and_kind_are_checked(self):
        for path in ['/api/engineering/projects/PJ1?tab=changes','/api/engineering/products/P1?product=unknown','/api/engineering/projects/missing?tab=projects']:
            self.assertEqual(self.client.get(path).status_code,404)
        self.assertEqual(self.client.get('/api/engineering?tab=products&owner=E1').status_code,400)
    def test_saved_note_preserves_facts_and_versions(self):
        values=list(Record.objects.values_list('values',flat=True));p=self.payload();url='/api/engineering/projects/PJ1/follow-up?tab=projects';self.assertEqual(self.post(url,p).status_code,200);self.assertEqual(self.post(url,p).status_code,409);p.update(version=1,data_revision=[0,'old']);self.assertEqual(self.post(url,p).status_code,409);self.assertEqual(values,list(Record.objects.values_list('values',flat=True)));self.assertEqual(len(self.client.get('/api/engineering/projects/PJ1/history?tab=projects').json()['rows']),1)
    def test_role_and_csrf_write_checks(self):
        for role in ['viewer','finance']:
            u=User.objects.create_user(role);u.groups.add(Group.objects.create(name=role));self.client.force_login(u);self.assertEqual(self.post('/api/engineering/projects/PJ1/follow-up?tab=projects',self.payload()).status_code,403)
        c=Client(enforce_csrf_checks=True);c.force_login(self.admin);self.assertEqual(c.post('/api/engineering/projects/PJ1/follow-up?tab=projects',json.dumps(self.payload()),content_type='application/json').status_code,403)
    def test_invalid_note_and_review_authority(self):
        self.client.force_login(self.admin)
        for change in [dict(status='批准投产'),dict(version=True),dict(note='短'),dict(due_date='bad'),dict(extra='unexpected')]:self.assertEqual(self.post('/api/engineering/projects/PJ1/follow-up?tab=projects',{**self.payload(),**change}).status_code,400)
        u=User.objects.create_user('ops');u.groups.add(Group.objects.create(name='operations'));self.client.force_login(u);self.assertEqual(self.post('/api/engineering/projects/PJ1/follow-up?tab=projects',{**self.payload(),'status':'演练已核对'}).status_code,403)
    def test_audit_failure_rolls_back_coordination(self):
        with patch('app.engineering_views.AuditEvent.objects.create',side_effect=RuntimeError('audit unavailable')):
            with self.assertRaises(RuntimeError):self.post('/api/engineering/projects/PJ1/follow-up?tab=projects',self.payload())
        self.assertFalse(IssueDisposition.objects.filter(key='engineering:projects:PJ1').exists())
    def test_csv_injection_and_source_download_permission(self):
        r=Record.objects.get(dataset='projects',business_key='PJ1');r.values['name']='=1+1';r.save();self.assertIn("'=1+1",self.client.get('/api/engineering/export?tab=projects').content.decode('utf-8-sig'))
        self.client.force_login(self.quality);self.assertFalse(self.client.get('/api/engineering/projects/PJ1/evidence?tab=projects').json()['can_download_original'])
