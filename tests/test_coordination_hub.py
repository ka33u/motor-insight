import csv,io,json,uuid
from datetime import date,timedelta
from unittest.mock import patch
from urllib.parse import parse_qs
from django.contrib.auth.models import User,Group
from django.core.exceptions import ObjectDoesNotExist,ValidationError
from django.test import Client
from django.http import QueryDict
from app import coordination_hub as hub
from app.models import IssueDisposition,ActionTask,ActionTaskEvent,AuditEvent,Record
from app.import_review import ReviewConflict
from .test_platform import PlatformCase


class CoordinationHubTests(PlatformCase):
    def setUp(self):
        super().setUp();self.today=date(2026,10,5)
        for role in ['analyst','operations','finance','viewer']:
            u=User.objects.create_user(role,password='!');u.groups.add(Group.objects.get_or_create(name=role)[0]);setattr(self,role,u)
        self.unit=self.record('units',{'id':'SN1','work_order_id':'WO1','product_id':'P1','status':'待检'})
        self.line=self.record('order_lines',{'id':'LINE1','net_cents':12345})
        self.invoice=self.record('invoices',{'id':'INV1','net_cents':987654})
        self.employee=self.record('employees',{'id':'E1','name':'模拟甲'})
        self.target=self.record('kpi_targets',{'id':'T1'})
        self.note('quality:SN1',due_date='2026-10-04')
        self.note('delivery:LINE1',status='处理中',due_date='2026-10-05')
        self.note('ar:invoice:INV1',status='对账中',due_date='2026-10-06',note='财务保密演练')
        self.note('workforce:E1',status='待授权复核',due_date=None,note='人员保密演练')
        self.note('target:T1',status='责任岗位分析中',due_date='2026-10-12',note='经营目标保密演练')
        self.client.force_login(self.admin)
        self.clock=patch('app.coordination_hub.timezone.localdate',return_value=self.today);self.clock.start();self.addCleanup(self.clock.stop)

    def note(self,key,**kwargs):
        return IssueDisposition.objects.create(key=key,**dict({'status':'待处理','owner':'模拟岗位','note':'模拟核查依据','updated_by':'admin','version':1},**kwargs))
    def task(self,**kwargs):
        return ActionTask.objects.create(**dict({'dataset':'units','business_key':'SN1','rule':'QUALITY','classification':'business',
            'title':'模拟质量任务','description':'任务核查说明','creator':self.admin,'state':'working','source_snapshot':{},'assignee':self.quality,'reviewer':self.operations,'due_date':self.today},**kwargs))
    def current(self,user=None):return hub.Hub(user or self.admin,self.today)
    def hub_row(self,key,user=None):return next(r for r in self.current(user).rows if r['key']==key)
    def get(self,params=None):return self.client.get('/api/coordination-hub',params or {})
    def info(self,row,user=None,**params):
        self.client.force_login(user or self.admin);h=self.current(user)
        return self.client.get('/api/coordination-hub/rows/'+row['id'],{'receipt':h.receipt,**params})

    def test_open_summary_and_dates_use_operation_day(self):
        s=self.get().json()['summary'];self.assertEqual((s['total'],s['open'],s['overdue'],s['today'],s['next7'],s['no_due']),(5,5,1,1,2,1))
        self.assertEqual(self.hub_row('quality:SN1')['overdue_days'],1)
        self.assertEqual(self.get().json()['today'],'2026-10-05')

    def test_today_is_not_overdue(self):
        r=self.hub_row('delivery:LINE1');self.assertEqual(r['bucket'],'today');self.assertIsNone(r['overdue_days'])

    def test_future_seven_day_boundary(self):
        self.assertEqual(self.hub_row('target:T1')['bucket'],'next7')
        IssueDisposition.objects.filter(key='target:T1').update(due_date=self.today+timedelta(days=8))
        self.assertEqual(self.hub_row('target:T1')['bucket'],'later')

    def test_closed_note_and_closed_task_do_not_count_overdue(self):
        IssueDisposition.objects.filter(key='quality:SN1').update(status='演练已核验')
        self.task(state='closed',due_date=self.today-timedelta(days=20))
        s=self.get().json()['summary'];self.assertEqual((s['note_reviewed'],s['task_closed'],s['done'],s['overdue']),(1,1,2,0))

    def test_unknown_status_is_not_assumed_open_or_closed(self):
        IssueDisposition.objects.filter(key='quality:SN1').update(status='新状态待解释')
        r=self.hub_row('quality:SN1');self.assertEqual(r['phase'],'unknown');self.assertEqual(r['bucket'],'unknown')
        self.assertEqual(self.get().json()['summary']['overdue'],0)

    def test_missing_object_keeps_note_without_claiming_resolution(self):
        self.note('quality:SN-MISSING');r=self.hub_row('quality:SN-MISSING')
        self.assertEqual((r['source_state'],r['phase']),('missing','open'))
        self.assertIsNone(self.info(r).json()['source'])

    def test_missing_mapping_only_visible_to_admin(self):
        n=self.note('future-system:PRIVATE',note='不能进入普通角色的搜索选项')
        self.assertEqual(self.hub_row(n.key)['source_state'],'unmapped')
        h=self.current(self.viewer);self.assertNotIn('note:'+str(n.pk),h.objects)
        with self.assertRaises(ObjectDoesNotExist):h.get('note:'+str(n.pk))

    def test_invalid_financial_key_fails_closed(self):
        self.note('ar:unsupported:SECRET',note='测试金融说明')
        self.assertFalse(any('SECRET' in r['key'] for r in self.current(self.finance).rows))

    def test_financial_metadata_notes_and_options_are_filtered(self):
        self.client.force_login(self.quality);raw=self.get({'q':'财务保密演练'}).json()
        self.assertEqual(raw['total'],0);self.assertNotIn('ar',[d['id'] for d in raw['domains']])
        self.assertNotIn('INV1',json.dumps(raw))

    def test_personnel_and_target_permissions_differ(self):
        ops={r['key'] for r in self.current(self.operations).rows};fin={r['key'] for r in self.current(self.finance).rows}
        self.assertIn('workforce:E1',ops);self.assertNotIn('target:T1',ops);self.assertNotIn('ar:invoice:INV1',ops)
        self.assertIn('ar:invoice:INV1',fin);self.assertNotIn('workforce:E1',fin);self.assertNotIn('target:T1',fin)

    def test_forbidden_detail_does_not_leak_existence(self):
        r=self.hub_row('ar:invoice:INV1');self.assertEqual(self.info(r,self.viewer).status_code,404)

    def test_task_classification_restricts_board_and_detail(self):
        t=self.task(classification='restricted')
        for u in [self.viewer,self.quality,self.finance,self.operations]:self.assertNotIn('task:'+str(t.pk),self.current(u).objects)
        self.assertIn('task:'+str(t.pk),self.current(self.analyst).objects)

    def test_free_text_username_does_not_create_assignment(self):
        IssueDisposition.objects.filter(key='quality:SN1').update(owner=self.quality.username)
        t=self.task();h=self.current(self.quality);rows=h.selected(hub.params({'relation':'assigned'}))
        self.assertEqual([r['id'] for r in rows],['task:'+str(t.pk)])

    def test_review_me_only_pending_account_tasks(self):
        t=self.task(state='review');h=self.current(self.operations)
        self.assertEqual([r['id'] for r in h.selected(hub.params({'relation':'review'}))],['task:'+str(t.pk)])
        t.state='closed';t.save();self.assertEqual(self.current(self.operations).selected(hub.params({'relation':'review'})),[])

    def test_recent_actor_not_same_as_assignee(self):
        t=self.task();ActionTaskEvent.objects.create(task=t,sequence=1,action='comment',actor=self.operations,request_id=uuid.uuid4(),payload_hash='x',note='测试补充',before={},after={})
        r=self.current(self.operations).get('task:'+str(t.pk));self.assertTrue(r['updated_by_me']);self.assertFalse(r['assigned_to_me'])

    def test_filter_intersection_and_all_owner_literal(self):
        IssueDisposition.objects.filter(key='quality:SN1').update(owner='all')
        d=self.get({'owner':'all','bucket':'overdue','domain':'quality','q':'SN1','type':'note'}).json()
        self.assertEqual(d['total'],1);self.assertEqual(d['summary']['total'],1);self.assertEqual(len(d['groups']),1)

    def test_read_only_board_and_detail_do_not_change_state(self):
        before=list(IssueDisposition.objects.values());facts=list(Record.objects.values());audits=AuditEvent.objects.count()
        d=self.get().json();self.info(d['rows'][0]);self.assertEqual(before,list(IssueDisposition.objects.values()));self.assertEqual(facts,list(Record.objects.values()));self.assertEqual(audits,AuditEvent.objects.count())

    def test_source_fields_respect_money_access(self):
        r=self.hub_row('delivery:LINE1');d=self.info(r,self.viewer).json()
        self.assertNotIn('net_cents',d['source']['values']);self.assertEqual(d['source']['file'],'unit-test.xlsx');self.assertFalse(d['can_download_original'])

    def test_history_uses_exact_namespace_and_whitelisted_fields(self):
        for oid in ['SN1','SN2']:
            AuditEvent.objects.create(action='quality.followup',actor='admin',object_type='QualityUnit',object_id=oid,
                detail={'after':{'status':'待处理','note':oid,'net_cents':999},'source_issues':['不要泄露额外内容']})
        d=self.info(self.hub_row('quality:SN1')).json();self.assertEqual(d['history_total'],1);self.assertEqual(d['history'][0]['after'],{'status':'待处理','note':'SN1'})

    def test_history_paginates_without_truncating_total(self):
        AuditEvent.objects.bulk_create([AuditEvent(action='quality.followup',actor='admin',object_type='QualityUnit',object_id='SN1',detail={'after':{'version':i}}) for i in range(23)])
        d=self.info(self.hub_row('quality:SN1'),page=2).json();self.assertEqual(d['history_total'],23);self.assertEqual(len(d['history']),3)

    def test_related_records_are_exact_primary_object_links(self):
        t=self.task();d=self.info(self.hub_row('quality:SN1')).json()
        self.assertEqual([r['id'] for r in d['related']],['task:'+str(t.pk)])

    def test_history_not_cross_matched_by_key_suffix(self):
        AuditEvent.objects.create(action='delivery.followup',actor='admin',object_type='OrderLine',object_id='SN1',detail={})
        self.assertEqual(self.info(self.hub_row('quality:SN1')).json()['history_total'],0)

    def test_receipt_expires_when_note_changes(self):
        h=self.current();IssueDisposition.objects.filter(key='quality:SN1').update(note='新的跟进说明')
        with self.assertRaises(ReviewConflict):self.current().check(h.receipt)

    def test_receipt_expires_on_source_value_change_even_without_new_hash(self):
        h=self.current();self.unit.values['status']='已检';self.unit.save()
        with self.assertRaises(ReviewConflict):self.current().check(h.receipt)

    def test_receipt_is_bound_to_identity_role_and_day(self):
        h=self.current()
        for newer in [self.current(self.analyst),hub.Hub(self.admin,self.today+timedelta(days=1))]:
            with self.assertRaises(ReviewConflict):newer.check(h.receipt)

    def test_lost_permission_refuses_previous_detail_receipt(self):
        r=self.hub_row('ar:invoice:INV1');h=self.current(self.analyst);self.analyst.groups.clear();self.analyst.groups.add(Group.objects.get(name='viewer'));self.client.force_login(self.analyst)
        self.assertEqual(self.client.get('/api/coordination-hub/rows/'+r['id'],{'receipt':h.receipt}).status_code,404)

    def test_pagination_does_not_change_summary_export_or_receipt(self):
        for i in range(31):self.note('quality:EXTRA'+str(i),due_date='2026-10-04')
        a=self.get().json();b=self.get({'page':2}).json()
        self.assertEqual((a['total'],len(a['rows']),len(b['rows'])),(36,25,11));self.assertEqual(a['summary'],b['summary']);self.assertEqual(a['receipt'],b['receipt'])
        out=self.client.get('/api/coordination-hub/export',{'receipt':a['receipt'],'page':2})
        self.assertEqual(len(list(csv.reader(io.StringIO(out.content.decode('utf-8-sig')))))-4,36)

    def test_csv_matches_filter_and_escapes_formulas(self):
        IssueDisposition.objects.filter(key='quality:SN1').update(owner='=HYPERLINK("x")',note='+123')
        d=self.get({'domain':'quality'}).json();out=self.client.get('/api/coordination-hub/export',{'receipt':d['receipt'],'domain':'quality'})
        rows=list(csv.reader(io.StringIO(out.content.decode('utf-8-sig'))));self.assertEqual(len(rows)-4,1);self.assertEqual(rows[4][6],'\'=HYPERLINK("x")');self.assertEqual(rows[4][13],"'+123")
        event=AuditEvent.objects.get(action='coordination_hub.export');self.assertEqual(event.detail['rows'],1)

    def test_export_requires_receipt_and_retains_permission_filter(self):
        self.assertEqual(self.client.get('/api/coordination-hub/export').status_code,409)
        self.client.force_login(self.viewer);d=self.get().json();out=self.client.get('/api/coordination-hub/export',{'receipt':d['receipt']})
        self.assertNotIn('财务保密演练',out.content.decode('utf-8-sig'));self.assertEqual(out['Cache-Control'],'no-store')

    def test_invalid_filters_and_pages_rejected(self):
        for p in [{'page':'0'},{'page':'1.5'},{'page':'100001'},{'type':'other'},{'relation':'owner-fuzzy'},{'bucket':'late'},{'extra':'x'},{'domain':'other'},{'q':'a'*201}]:
            with self.subTest(p=p):self.assertEqual(self.get(p).status_code,400)
        with self.assertRaises(ValidationError):hub.params(QueryDict('q=a&q=b'))

    def test_anonymous_and_role_conflict_rejected(self):
        self.client.logout();self.assertEqual(self.get().status_code,401)
        self.viewer.groups.add(Group.objects.get(name='finance'));self.client.force_login(self.viewer);self.assertEqual(self.get().status_code,401)

    def test_endpoints_are_read_only(self):
        r=self.hub_row('quality:SN1')
        for path in ['/api/coordination-hub','/api/coordination-hub/export','/api/coordination-hub/rows/'+r['id']]:self.assertEqual(self.client.post(path,{}).status_code,405)

    def test_plan_composite_identifier_keeps_date_and_work_order(self):
        r=hub.resolve('assembly-plan:2026-09-22~WO001');p=parse_qs(r['route'].split('?',1)[1]);self.assertEqual((r['dataset'],r['anchor']),('work_orders','WO001'));self.assertEqual(p['from'],['2026-09-22']);self.assertEqual(p['q'],['WO001'])
        self.assertIsNone(hub.resolve('assembly-plan:2026-09-99~WO001'))

    def test_url_encodes_object_identifiers(self):
        r=hub.resolve('sales:ID&A#B');self.assertEqual(parse_qs(r['route'].split('?',1)[1])['q'],['ID&A#B'])

    def test_material_link_preserves_shared_queue_instead_of_filtering_one_order(self):
        n=self.note('material_planning:orders:WO1',status='待核对')
        saved={'tab':'orders','order':'priority','stock_policy':'all_usable','family':'YE3','q':''}
        AuditEvent.objects.create(action='material_planning.followup',actor='admin',object_type='MaterialPlanningCoordination',object_id=n.key,detail={'filters':saved})
        r=self.hub_row(n.key);p=parse_qs(r['href'].split('?',1)[1]);self.assertEqual(p['order'],['priority']);self.assertEqual(p['stock_policy'],['all_usable']);self.assertEqual(p['family'],['YE3']);self.assertNotIn('q',p);self.assertEqual(p['focus'],['orders:WO1'])

    def test_invalid_saved_material_scope_is_explicit(self):
        n=self.note('material_planning:impact:LINE1',status='待核对')
        AuditEvent.objects.create(action='material_planning.followup',actor='admin',object_type='MaterialPlanningCoordination',object_id=n.key,detail={'filters':{'order':'invalid'}})
        r=self.hub_row(n.key);self.assertIn('无法恢复',r['source_context']);self.assertNotIn('q=',r['href'])

    def test_registry_states_and_sources_exist(self):
        import importlib
        for key,(_,_,module,terminal,_,kinds) in hub.REGISTRY.items():
            self.assertIn(terminal,importlib.import_module('app.'+module+'_views').STATUSES,key)
            for ds in kinds.values():
                if ds:self.assertIn(ds,hub.SCHEMAS)

    def test_empty_result_has_honest_zero_counts(self):
        d=self.get({'q':'NOT-EXISTING'}).json();self.assertEqual(d['rows'],[]);self.assertEqual(d['groups'],[]);self.assertEqual(d['summary']['total'],0);self.assertEqual(d['summary']['open'],0)
