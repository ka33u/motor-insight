import copy,csv,io,json,uuid
from unittest.mock import patch
from django.contrib.auth.models import User,Group
from django.test import Client
from django.core.exceptions import PermissionDenied,ValidationError
from app import action_tasks as tasks
from app.models import ActionTask,ActionTaskEvent,AuditEvent,Record
from app.import_review import ReviewConflict
from .test_platform import PlatformCase


class ActionTaskTests(PlatformCase):
    def setUp(self):
        super().setUp()
        for role in ['operations','analyst','finance','viewer']:
            u=User.objects.create(username=role,password='!');u.groups.add(Group.objects.get_or_create(name=role)[0]);setattr(self,role,u)
        self.product=self.record('products',{'id':'P1','family':'YE3','model':'M1','price_cents':123456})
        self.invoice=self.record('invoices',{'id':'INV1','net_cents':10000})
        self.labor=self.record('labor_entries',{'id':'LE1','employee_id':'E1','minutes':60})
        self.initial=list(Record.objects.values());self.client.force_login(self.admin)

    def data(self,**changes):
        d=dict(request_id=str(uuid.uuid4()),dataset='products',key='P1',rule='QUALITY',classification='business',title='核对该配置质量资料',description='模拟问题，请根据已导入来源核对资料')
        d.update(changes);d['source_receipt']=tasks.preview(self.admin,d['dataset'],d['key'],d['classification'])['source']['receipt'];return d
    def make(self,**changes):return tasks.create(self.admin,self.data(**changes))['task']
    def act(self,t,action,user=None,**changes):
        p=dict(request_id=str(uuid.uuid4()),version=t['version'],action=action,note='模拟核查依据与处理记录');p.update(changes)
        return tasks.transition(user or self.admin,t['id'],p)['task']
    def assigned(self,**changes):
        t=self.act(self.make(**changes),'confirm');return self.act(t,'assign',assignee=self.quality.pk,reviewer=self.operations.pk,due_date='2026-10-10')
    def working(self):return self.act(self.assigned(),'start',self.quality)
    def submitted(self):return self.act(self.working(),'submit',self.quality,evidence=[{'dataset':'products','key':'P1'}])

    def test_full_cycle_evidence_and_business_facts_unchanged(self):
        t=self.submitted();t=self.act(t,'close',self.operations);self.assertEqual(t['state'],'closed');self.assertIsNotNone(t['closed_at'])
        detail=tasks.detail(self.admin,t['id']);self.assertEqual(detail['history_total'],6)
        evidence=detail['submission']['evidence'][0];self.assertEqual(evidence['file'],'unit-test.xlsx');self.assertEqual(evidence['row'],2);self.assertNotIn('price_cents',evidence['values'])
        self.assertEqual(self.initial,list(Record.objects.values()));self.assertEqual(AuditEvent.objects.filter(action__startswith='action_task.').count(),6)

    def test_duplicate_identity_even_after_close(self):
        t=self.act(self.submitted(),'close',self.operations)
        with self.assertRaises(ReviewConflict):self.make(title='不同标题也不能重复登记')
        self.assertEqual(ActionTask.objects.count(),1);self.assertEqual(ActionTask.objects.get().state,'closed')

    def test_create_replay_and_request_collision(self):
        d=self.data();a=tasks.create(self.admin,d);b=tasks.create(self.admin,d);self.assertEqual(a['task']['id'],b['task']['id']);self.assertTrue(b['replayed']);self.assertEqual(ActionTaskEvent.objects.count(),1)
        with self.assertRaises(ReviewConflict):tasks.create(self.admin,{**d,'title':'不同请求内容'})

    def test_transition_replay_after_subsequent_transition(self):
        t=self.make();p=dict(request_id=str(uuid.uuid4()),version=1,action='confirm',note='模拟确认确有资料问题')
        first=tasks.transition(self.admin,t['id'],p);current=self.act(first['task'],'comment')
        again=tasks.transition(self.admin,t['id'],p);self.assertTrue(again['replayed']);self.assertEqual(again['task']['version'],current['version']);self.assertEqual(ActionTaskEvent.objects.count(),3)

    def test_request_cannot_move_to_another_task(self):
        a=self.make();b=self.make(rule='DATA_MISSING');p=dict(request_id=str(uuid.uuid4()),version=1,action='confirm',note='模拟问题确认登记依据')
        tasks.transition(self.admin,a['id'],p)
        with self.assertRaises(ReviewConflict):tasks.transition(self.admin,b['id'],p)

    def test_stale_version_cannot_write(self):
        t=self.make();self.act(t,'confirm')
        with self.assertRaises(ReviewConflict):self.act(t,'confirm')
        with self.assertRaises(ReviewConflict):tasks.transition(self.admin,t['id'],dict(request_id=str(uuid.uuid4()),version=True,action='comment',note='布尔值不作为版本'))
        self.assertEqual(ActionTaskEvent.objects.count(),2)

    def test_source_changes_between_preview_and_create(self):
        d=self.data();self.product.values['model']='M2';self.product.save()
        with self.assertRaises(ReviewConflict):tasks.create(self.admin,d)
        self.assertEqual(ActionTask.objects.count(),0)

    def test_snapshot_retained_and_source_change_visible(self):
        t=self.make();old=copy.deepcopy(tasks.detail(self.admin,t['id'])['source_snapshot']);self.product.values['model']='M2';self.product.revision+=1;self.product.save()
        detail=tasks.detail(self.admin,t['id']);self.assertTrue(detail['source_changed']);self.assertEqual(detail['source_snapshot'],old);self.assertEqual(detail['current_source']['values']['model'],'M2')

    def test_self_review_and_skipped_states_rejected(self):
        t=self.make()
        for action,user,extras in [('close',self.admin,{}),('start',self.admin,{}),('submit',self.admin,{'evidence':[{'dataset':'products','key':'P1'}]})]:
            with self.subTest(action=action),self.assertRaises(PermissionDenied):self.act(t,action,user,**extras)
        t=self.act(t,'confirm')
        with self.assertRaises(ValidationError):self.act(t,'assign',assignee=self.admin.pk,reviewer=self.admin.pk,due_date='2026-10-10')

    def test_only_assignee_can_start_and_submit(self):
        t=self.assigned()
        with self.assertRaises(PermissionDenied):self.act(t,'start',self.admin)
        t=self.act(t,'start',self.quality)
        with self.assertRaises(PermissionDenied):self.act(t,'submit',self.operations,evidence=[{'dataset':'products','key':'P1'}])

    def test_independent_reviewer_and_admin_cannot_bypass(self):
        t=self.submitted()
        for user in [self.quality,self.admin,self.analyst]:
            with self.subTest(user=user.username),self.assertRaises(PermissionDenied):self.act(t,'close',user)
        self.assertEqual(self.act(t,'close',self.operations)['state'],'closed')

    def test_return_retains_history_and_requires_new_submission(self):
        t=self.submitted();t=self.act(t,'return',self.operations)
        with self.assertRaises(PermissionDenied):self.act(t,'close',self.operations)
        t=self.act(t,'submit',self.quality,note='根据退回说明补充新的核查结论',evidence=[{'dataset':'products','key':'P1'}]);t=self.act(t,'close',self.operations)
        events=ActionTask.objects.get(pk=t['id']).events.filter(action='submit');self.assertEqual(events.count(),2);self.assertNotEqual(events[0].note,events[1].note)

    def test_evidence_revision_changed_blocks_close(self):
        t=self.submitted();self.product.values['model']='M2';self.product.revision+=1;self.product.save()
        with self.assertRaises(ReviewConflict):self.act(t,'close',self.operations)
        t=self.act(t,'return',self.operations);t=self.act(t,'submit',self.quality,evidence=[{'dataset':'products','key':'P1'}]);self.assertEqual(self.act(t,'close',self.operations)['state'],'closed')

    def test_evidence_content_changed_without_revision_also_blocks(self):
        t=self.submitted();Record.objects.filter(pk=self.product.pk).update(values={**self.product.values,'model':'M2'})
        with self.assertRaises(ReviewConflict):self.act(t,'close',self.operations)

    def test_origin_change_blocks_even_when_supporting_evidence_unchanged(self):
        self.record('products',{'id':'P2','family':'YE4','model':'M2'})
        t=self.act(self.working(),'submit',self.quality,evidence=[{'dataset':'products','key':'P2'}])
        self.product.values['model']='M3';self.product.save()
        with self.assertRaises(ReviewConflict):self.act(t,'close',self.operations)

    def test_viewer_can_read_business_task_but_not_participant_actions(self):
        t=self.make();self.assertEqual(tasks.detail(self.viewer,t['id'])['task']['actions'],[])
        with self.assertRaises(PermissionDenied):self.act(t,'comment',self.viewer)
        with self.assertRaises(PermissionDenied):self.act(t,'comment',self.analyst)

    def test_missing_source_fails_closed_and_preserves_submission(self):
        t=self.submitted();old=copy.deepcopy(tasks.detail(self.admin,t['id'])['submission']);self.product.delete()
        with self.assertRaises(Record.DoesNotExist):self.act(t,'close',self.operations)
        d=tasks.detail(self.admin,t['id']);self.assertIsNone(d['current_source']);self.assertEqual(d['submission'],old);self.assertTrue(d['source_changed'])

    def test_evidence_bounds_duplicate_and_classification(self):
        t=self.working()
        for refs in [[],[{'dataset':'products','key':'P1'}]*11,[{'dataset':'products','key':'P1'}]*2,[{'dataset':'invoices','key':'INV1'}],[{'dataset':'products','key':'P1','x':1}]]:
            with self.subTest(refs=refs),self.assertRaises((ValidationError,PermissionDenied)):self.act(t,'submit',self.quality,evidence=refs)
        self.assertEqual(ActionTask.objects.get(pk=t['id']).state,'working')

    def test_transfer_requires_new_owner_acceptance(self):
        t=self.working();t=self.act(t,'transfer',assignee=self.analyst.pk,due_date='2026-10-11')
        self.assertEqual(t['state'],'assigned');self.assertEqual(t['reviewer_id'],self.operations.pk)
        with self.assertRaises(PermissionDenied):self.act(t,'start',self.quality)
        self.assertEqual(self.act(t,'start',self.analyst)['state'],'working')

    def test_transfer_cannot_use_original_owner_or_reviewer(self):
        t=self.assigned()
        for user in [self.quality,self.operations]:
            with self.assertRaises(ValidationError):self.act(t,'transfer',assignee=user.pk,due_date='2026-10-11')
        with self.assertRaises(PermissionDenied):self.act(t,'transfer',self.quality,assignee=self.analyst.pk,due_date='2026-10-11')

    def test_inactive_and_readonly_people_not_assignable(self):
        t=self.act(self.make(),'confirm');self.quality.is_active=False;self.quality.save()
        for who in [self.quality,self.viewer]:
            with self.assertRaises(ValidationError):self.act(t,'assign',assignee=who.pk,reviewer=self.operations.pk,due_date='2026-10-11')

    def test_inactive_reviewer_requires_manager_replacement(self):
        t=self.working();self.operations.is_active=False;self.operations.save()
        with self.assertRaises(ValidationError):self.act(t,'submit',self.quality,evidence=[{'dataset':'products','key':'P1'}])
        t=self.act(t,'reviewer',reviewer=self.analyst.pk);t=self.act(t,'submit',self.quality,evidence=[{'dataset':'products','key':'P1'}]);self.assertEqual(self.act(t,'close',self.analyst)['state'],'closed')

    def test_reviewer_change_cannot_be_assignee(self):
        t=self.submitted()
        with self.assertRaises(ValidationError):self.act(t,'reviewer',reviewer=self.quality.pk)
        self.assertEqual(self.act(t,'reviewer',reviewer=self.analyst.pk)['reviewer_id'],self.analyst.pk)

    def test_reopen_preserves_old_cycle_and_needs_reassignment(self):
        t=self.act(self.submitted(),'close',self.operations);original=copy.deepcopy(tasks.detail(self.admin,t['id'])['history']);t=self.act(t,'reopen',self.quality)
        self.assertEqual((t['cycle'],t['state'],t['assignee_id'],t['due_date']),(2,'confirmed',None,None));self.assertIsNone(t['closed_at'])
        self.assertEqual(tasks.detail(self.admin,t['id'])['history'][1:],original)

    def test_deadline_change_audited_and_overdue_uses_task_clock(self):
        t=self.assigned();t=self.act(t,'deadline',due_date='2020-01-01')
        self.assertTrue(t['overdue']);self.assertEqual(tasks.board(self.admin,{'bucket':'overdue'})['total'],1)
        with self.assertRaises(ValidationError):self.act(t,'deadline',due_date='2020-01-01')
        e=ActionTaskEvent.objects.latest('pk');self.assertEqual(e.before['due_date'],'2026-10-10');self.assertEqual(e.after['due_date'],'2020-01-01')

    def test_finance_task_visibility_and_export_permissions(self):
        t=self.make(dataset='invoices',key='INV1',classification='money',rule='FINANCE')
        for user in [self.quality,self.operations,self.viewer]:
            self.client.force_login(user);self.assertEqual(self.client.get('/api/action-tasks/'+t['id']).status_code,403);self.assertEqual(self.client.get('/api/action-tasks/'+t['id']+'/export').status_code,403);self.assertEqual(tasks.board(user,{})['total'],0)
        self.assertEqual(tasks.board(self.finance,{})['total'],1);self.assertIn('net_cents',tasks.detail(self.finance,t['id'])['source_snapshot']['values'])

    def test_personnel_and_combined_classifications(self):
        a=self.make(dataset='labor_entries',key='LE1',classification='personnel',rule='PERSONNEL')
        b=self.make(dataset='labor_entries',key='LE1',classification='restricted',rule='OTHER')
        self.assertEqual(tasks.board(self.operations,{})['total'],1);self.assertEqual(tasks.board(self.finance,{})['total'],0);self.assertEqual(tasks.board(self.analyst,{})['total'],2)
        with self.assertRaises(ValidationError):tasks.preview(self.admin,'labor_entries','LE1','business')

    def test_business_snapshot_strips_money_for_every_actor(self):
        t=self.make();s=tasks.detail(self.admin,t['id'])['source_snapshot'];self.assertNotIn('price_cents',s['values']);self.assertNotIn('price_cents',{f['name'] for f in s['fields']});self.assertEqual(tasks.detail(self.viewer,t['id'])['source_snapshot'],s)

    def test_role_changes_restrict_old_task_and_replay(self):
        d=self.data(classification='money');t=tasks.create(self.admin,d)['task'];self.admin.groups.set([Group.objects.get(name='quality')])
        with self.assertRaises(PermissionDenied):tasks.detail(self.admin,t['id'])
        with self.assertRaises(PermissionDenied):tasks.create(self.admin,d)

    def test_actor_reloaded_before_write_not_stale_user_instance(self):
        t=self.make();User.objects.filter(pk=self.admin.pk).update(is_active=False)
        with self.assertRaises(PermissionDenied):self.act(t,'confirm')
        self.assertEqual(ActionTaskEvent.objects.count(),1)

    def test_mutations_rollback_if_audit_fails(self):
        d=self.data()
        with patch('app.action_tasks.AuditEvent.objects.create',side_effect=ValueError('audit unavailable')):
            with self.assertRaises(ValueError):tasks.create(self.admin,d)
        self.assertEqual(ActionTask.objects.count(),0);self.assertEqual(ActionTaskEvent.objects.count(),0)
        t=self.make()
        with patch('app.action_tasks.AuditEvent.objects.create',side_effect=ValueError('audit unavailable')):
            with self.assertRaises(ValueError):self.act(t,'confirm')
        self.assertEqual(ActionTask.objects.get().version,1);self.assertEqual(ActionTaskEvent.objects.count(),1)

    def test_filters_counts_search_and_history_pagination(self):
        t=self.assigned();self.make(rule='OTHER',title='另一个模拟核查事项')
        b=tasks.board(self.quality,{'bucket':'mine','state':'assigned','q':'配置'});self.assertEqual(b['total'],1);self.assertEqual(b['counts']['assigned'],1)
        for i in range(30):t=self.act(t,'comment',note=f'第{i}次模拟补充核查记录')
        self.assertEqual(len(tasks.detail(self.admin,t['id'])['history']),30);self.assertEqual(len(tasks.detail(self.admin,t['id'],2)['history']),3)

    def test_api_create_preview_and_csrf(self):
        p=self.client.get('/api/action-tasks/preview',{'dataset':'products','key':'P1','classification':'business'});self.assertEqual(p.status_code,200)
        response=self.post('/api/action-tasks',self.data());self.assertEqual(response.status_code,200,response.content);self.assertEqual(response['Cache-Control'],'no-store')
        self.client.force_login(self.viewer);self.assertEqual(self.post('/api/action-tasks',self.data(rule='OTHER')).status_code,403)
        secure=Client(enforce_csrf_checks=True);secure.force_login(self.admin);self.assertEqual(secure.post('/api/action-tasks','{}',content_type='application/json').status_code,403)
        self.client.logout();self.assertEqual(self.client.get('/api/action-tasks').status_code,401)

    def test_api_export_full_history_and_csv_formula_escape(self):
        t=self.make(title='=1+1',description='=模拟公式不应执行');self.act(t,'confirm',note='@模拟确认问题依据')
        response=self.client.get('/api/action-tasks/'+t['id']+'/export');self.assertEqual(response.status_code,200,response.content)
        content=response.content.decode('utf-8-sig');self.assertIn("'=1+1",content);self.assertIn("'@模拟确认问题依据",content);rows=list(csv.reader(io.StringIO(content)));self.assertEqual(len(rows),5)

    def test_invalid_payload_filters_dates_and_raw_dataset_only(self):
        t=self.act(self.make(),'confirm')
        for when in ['2026-13-01','2026-1-1',None,True]:
            with self.assertRaises(ValidationError):self.act(t,'assign',assignee=self.quality.pk,reviewer=self.operations.pk,due_date=when)
        for params in [{'sql':'x'},{'state':'wrong'},{'page':'0'},{'bucket':'wrong'}]:self.assertEqual(self.client.get('/api/action-tasks',params).status_code,400)
        self.assertEqual(self.client.get('/api/action-tasks/preview',{'dataset':'bi_work_orders','key':'W1','classification':'business'}).status_code,403)
        p=self.data(rule='OTHER');p['request_id']='bad';self.assertEqual(self.post('/api/action-tasks',p).status_code,400)
