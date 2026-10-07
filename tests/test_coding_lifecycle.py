import copy,importlib,json,uuid
from datetime import timedelta
from unittest.mock import patch
from django.apps import apps
from django.core.exceptions import ValidationError,PermissionDenied
from django.test import Client,TransactionTestCase
from django.db import close_old_connections,OperationalError
from django.utils import timezone
from app import coding,coding_lifecycle as life
from app.import_review import ReviewConflict
from app.models import CodingRule,CodingRuleVersion,CodeAllocation,CodeCounter,CodeIssueRequest,AuditEvent
from tests.test_platform import PlatformCase

PAYLOAD={'name':'试制检测单','prefix':'TR','date_format':'%Y%m%d','width':4,'separator':'-','reset_period':'day'}
WHY='模拟核对已完成，可以启用'

class CodingLifecycleTests(PlatformCase):
    def setUp(self):
        super().setUp();self.today=timezone.localdate();self.rule=CodingRule.objects.create(key='trial',**PAYLOAD)
        self.client.force_login(self.admin)
    def preview(self,at=None,count=2):return coding.preview(self.rule.pk,at or self.today,count,self.admin.username)
    def request(self,p=None,**changes):
        p=p or self.preview();return {'date':str(p['business_date']),'count':p['count'],'preview':False,'preview_token':p['preview_token'],'request_id':str(uuid.uuid4()),'purpose':'模拟试制检测发号',**changes}
    def draft(self,payload=None):
        self.rule.refresh_from_db();return life.save_draft(self.admin,self.rule.pk,{'revision':self.rule.revision,'payload':payload or {**PAYLOAD,'prefix':'TR2'},'reason':WHY})
    def action(self,action,**values):
        self.rule.refresh_from_db();return life.transition(self.admin,self.rule.pk,{'revision':self.rule.revision,'action':action,'reason':WHY,**values})
    def issue(self,req=None):return coding.issue(self.rule.pk,req or self.request(),self.admin.username)
    def test_new_rule_stays_draft_until_dated_activation(self):
        r=life.create(self.admin,{'key':'new_rule','payload':PAYLOAD,'reason':WHY});self.assertIsNone(r['current']);self.assertEqual(r['draft']['version'],1)
        with self.assertRaises(ValidationError):coding.preview(r['id'],self.today,1,'admin')
        active=life.transition(self.admin,r['id'],{'revision':r['revision'],'action':'activate','version':1,'effective_from':str(self.today),'reason':WHY})
        self.assertEqual(active['current']['version'],1)
        with self.assertRaises(ValidationError):coding.preview(r['id'],self.today-timedelta(days=1),1,'admin')
    def test_preview_and_gets_are_read_only(self):
        before=(AuditEvent.objects.count(),CodingRuleVersion.objects.count(),CodeCounter.objects.count(),CodeAllocation.objects.count(),CodeIssueRequest.objects.count())
        self.preview();life.info(self.rule,True)
        for path in ['/api/coding',f'/api/coding/{self.rule.pk}',f'/api/coding/{self.rule.pk}/allocations']:
            self.assertEqual(self.client.get(path).status_code,200)
        self.assertEqual(before,(AuditEvent.objects.count(),CodingRuleVersion.objects.count(),CodeCounter.objects.count(),CodeAllocation.objects.count(),CodeIssueRequest.objects.count()))
    def test_draft_does_not_change_current_definition_or_old_allocation(self):
        old=self.issue();a=CodeAllocation.objects.first();snapshot=copy.deepcopy(a.definition)
        result=self.draft();self.assertEqual(result['current']['payload'],PAYLOAD);self.assertEqual(result['draft']['version'],2)
        self.assertEqual(CodingRuleVersion.objects.get(version=1).payload,PAYLOAD)
        a.refresh_from_db();self.assertEqual(a.definition,snapshot);self.assertEqual(a.code,old['codes'][0]);self.assertEqual(self.preview()['definition']['version'],1)
    def test_scheduled_boundary_and_history_resolve(self):
        self.draft();tomorrow=self.today+timedelta(days=1);self.action('activate',version=2,effective_from=str(tomorrow))
        self.assertEqual(self.preview()['definition']['version'],1);self.assertEqual(self.preview(tomorrow)['definition']['version'],2)
        self.assertTrue(self.preview(tomorrow)['codes'][0].startswith('TR2-'))
        self.rule.refresh_from_db();self.assertEqual(life.info(self.rule)['current']['version'],1)
    def test_no_retroactive_activation_or_overlap_or_reedit(self):
        self.draft()
        with self.assertRaises(ValidationError):self.action('activate',version=2,effective_from=str(self.today-timedelta(days=1)))
        self.action('activate',version=2,effective_from=str(self.today))
        with self.assertRaises(ValidationError):self.action('activate',version=2,effective_from=str(self.today+timedelta(days=1)))
        self.draft({**PAYLOAD,'prefix':'TR3'})
        with self.assertRaises(ValidationError):self.action('activate',version=3,effective_from=str(self.today))
    def test_existing_future_issue_protects_date_range(self):
        future=self.today+timedelta(days=3);self.issue(self.request(self.preview(future)));self.draft()
        with self.assertRaises(ValidationError):self.action('activate',version=2,effective_from=str(self.today+timedelta(days=1)))
        self.action('activate',version=2,effective_from=str(future+timedelta(days=1)))
    def test_scheduled_unused_cancel_and_used_cancel_protection(self):
        day=self.today+timedelta(days=1);self.draft();self.action('activate',version=2,effective_from=str(day));self.action('cancel',version=2)
        self.assertEqual(self.preview(day)['definition']['version'],1);self.draft();self.action('activate',version=3,effective_from=str(day))
        self.issue(self.request(self.preview(day)))
        with self.assertRaises(ValidationError):self.action('cancel',version=3)
        with self.assertRaises(ValidationError):self.action('cancel',version=1)
    def test_disabled_stops_new_issue_but_preserves_completed_retry(self):
        req=self.request();result=self.issue(req);self.action('enabled',enabled=False)
        self.assertFalse(self.preview()['valid']);self.assertEqual(self.issue(req)['codes'],result['codes']);self.assertTrue(self.issue(req)['replayed'])
        self.assertEqual(CodeAllocation.objects.count(),2)
        with self.assertRaises(ValidationError):self.issue(self.request())
        self.action('enabled',enabled=True);self.assertTrue(self.preview()['valid'])
    def test_idempotent_request_and_parameter_or_actor_mismatch(self):
        req=self.request();first=self.issue(req);again=self.issue(req)
        self.assertEqual(first['codes'],again['codes']);self.assertEqual(first['allocation_count'],2);self.assertEqual(again['allocation_count'],2);self.assertTrue(again['replayed']);self.assertEqual(CodeCounter.objects.get().value,2)
        for changed in [{**req,'purpose':'另外一个模拟业务'},{**req,'count':3}]:
            with self.assertRaises(ReviewConflict):self.issue(changed)
        with self.assertRaises(ReviewConflict):coding.issue(self.rule.pk,req,'someone_else')
        self.assertEqual(CodeIssueRequest.objects.count(),1);self.assertEqual(AuditEvent.objects.filter(action='coding.allocate').count(),1)
    def test_rule_or_counter_change_invalidates_preview(self):
        req=self.request();self.draft()
        with self.assertRaises(ReviewConflict):self.issue(req)
        req=self.request();self.issue()
        with self.assertRaises(ReviewConflict):self.issue(req)
        self.assertEqual(CodeAllocation.objects.count(),2)
    def test_api_identifies_expired_uncommitted_preview(self):
        req=self.request();self.draft()
        response=self.post(f'/api/coding/{self.rule.pk}/allocate',req)
        self.assertEqual(response.status_code,409);self.assertEqual(response.json()['code'],'coding_preview_expired')
        self.assertFalse(response.json()['committed']);self.assertFalse(CodeIssueRequest.objects.exists())
    def test_preview_is_actor_specific(self):
        with self.assertRaises(ReviewConflict):coding.issue(self.rule.pk,self.request(),'other_admin')
        self.assertFalse(CodeAllocation.objects.exists())
    def test_imported_high_sequence_blocks_until_explicit_forward_continuation(self):
        historical=coding.render_code(self.rule,self.today,77);record=self.record('departments',{'id':historical,'name':'模拟遗留档案','owner':'档案员'})
        p=self.preview();self.assertFalse(p['valid']);self.assertEqual(p['history']['max_sequence'],77)
        values={'revision':self.rule.revision,'date':str(self.today),'expected_counter':0,'value':77,'reason':WHY}
        with self.assertRaises(ValidationError):life.advance(self.admin,self.rule.pk,{**values,'value':76})
        life.advance(self.admin,self.rule.pk,values);nextp=self.preview();self.assertTrue(nextp['valid']);self.assertTrue(nextp['codes'][0].endswith('0078'))
        record.refresh_from_db();self.assertEqual(record.business_key,historical);self.assertEqual(CodeAllocation.objects.count(),0)
        self.assertEqual(AuditEvent.objects.get(action='coding.advance').detail['to'],77)
    def test_continuation_rejects_stale_revision_counter_and_regression(self):
        self.issue();self.rule.refresh_from_db();payload={'revision':self.rule.revision,'date':str(self.today),'expected_counter':2,'value':10,'reason':WHY}
        for changes,error in [({'revision':0},ReviewConflict),({'expected_counter':0},ReviewConflict),({'value':1},ValidationError),({'value':2},ValidationError),({'value':10000},ValidationError),({'value':True},ValidationError)]:
            with self.assertRaises(error):life.advance(self.admin,self.rule.pk,{**payload,**changes})
        self.assertEqual(CodeCounter.objects.get().value,2)
    def test_shared_month_counter_continues_across_version_prefix_change(self):
        self.rule.reset_period='month';self.rule.date_format='%Y%m';self.rule.save();self.issue()
        self.draft({**PAYLOAD,'prefix':'REV','reset_period':'month','date_format':'%Y%m'});tomorrow=self.today+timedelta(days=1)
        # Use a date within the same month, independent of the test runtime date.
        with patch('app.coding_lifecycle.timezone.localdate',return_value=self.today.replace(day=1)):
            at=self.today.replace(day=2)
            # Existing issue could be later in the month; a new version may not rewrite its date.
            CodeAllocation.objects.update(business_date=self.today.replace(day=1))
            self.action('activate',version=2,effective_from=str(at))
        p=self.preview(at);self.assertEqual(p['counter'],2);self.assertTrue(p['codes'][0].endswith('0003'))
    def test_capacity_never_rolls_over_and_twelve_digit_counter_supported(self):
        self.rule.width=1;self.rule.save();CodeCounter.objects.create(rule=self.rule,period=self.today.strftime('%Y%m%d'),value=9)
        p=self.preview();self.assertFalse(p['valid']);self.assertEqual(p['remaining'],0);self.assertEqual(p['codes'],[])
        self.rule.width=12;self.rule.save();c=CodeCounter.objects.get();c.value=999999999998;c.save()
        req=self.request(self.preview(count=1));self.issue(req);c.refresh_from_db();self.assertEqual(c.value,999999999999)
        self.assertFalse(self.preview(count=1)['valid'])
    def test_audit_failure_rolls_back_counter_allocation_and_request(self):
        req=self.request()
        with patch('app.coding.AuditEvent.objects.create',side_effect=RuntimeError('disk failure')):
            with self.assertRaises(RuntimeError):self.issue(req)
        self.assertEqual(CodeAllocation.objects.count(),0);self.assertEqual(CodeCounter.objects.count(),0);self.assertEqual(CodeIssueRequest.objects.count(),0);self.assertEqual(CodingRuleVersion.objects.count(),0)
    def test_lifecycle_audit_failure_rolls_back_draft(self):
        with patch('app.coding_lifecycle.AuditEvent.objects.create',side_effect=RuntimeError('disk failure')):
            with self.assertRaises(RuntimeError):self.draft()
        self.rule.refresh_from_db();self.assertEqual(self.rule.revision,1);self.assertFalse(CodingRuleVersion.objects.exists())
    def test_validation_rejects_malformed_requests_and_unknown_fields(self):
        for changes in [{'date':'20261003'},{'date':'2026-02-30'},{'count':True},{'count':0},{'count':101}]:
            response=self.post(f'/api/coding/{self.rule.pk}/allocate',{'date':str(self.today),'count':1,'preview':True,**changes});self.assertEqual(response.status_code,400)
        for changes in [{'purpose':'短'},{'request_id':'invalid'},{'extra':1},{'preview':True},{'preview_token':'bad'}]:
            self.assertEqual(self.post(f'/api/coding/{self.rule.pk}/allocate',{**self.request(),**changes}).status_code,400)
        self.assertFalse(CodeAllocation.objects.exists())
    def test_permissions_csrf_and_authenticated_read(self):
        self.client.force_login(self.quality)
        self.assertEqual(self.client.get(f'/api/coding/{self.rule.pk}').status_code,200)
        for suffix,body in [('allocate',{'date':str(self.today),'count':1,'preview':True}),('draft',{'revision':1,'payload':PAYLOAD,'reason':WHY}),('lifecycle',{'revision':1,'action':'enabled','enabled':False,'reason':WHY}),('advance',{})]:
            self.assertEqual(self.post(f'/api/coding/{self.rule.pk}/{suffix}',body).status_code,403)
        self.assertEqual(self.post('/api/coding',{'key':'try_new','payload':PAYLOAD,'reason':WHY}).status_code,403)
        secure=Client(enforce_csrf_checks=True);secure.force_login(self.admin)
        self.assertEqual(secure.post(f'/api/coding/{self.rule.pk}/allocate',json.dumps(self.request()),content_type='application/json').status_code,403)
        self.client.logout();self.assertEqual(self.client.get('/api/coding').status_code,401)
    def test_ledger_search_date_version_pagination_and_snapshot(self):
        self.issue(self.request(self.preview(count=30)))
        url=f'/api/coding/{self.rule.pk}/allocations';data=self.client.get(url).json()
        self.assertEqual(data['total'],30);self.assertEqual(len(data['rows']),25);self.assertEqual(len(self.client.get(url+'?page=2').json()['rows']),5)
        row=self.client.get(url+'?q=0001&version=1&from='+str(self.today)+'&to='+str(self.today)).json()['rows'][0]
        self.assertEqual(row['definition']['payload'],PAYLOAD);self.assertEqual(row['purpose'],'模拟试制检测发号');self.assertTrue(row['request_id'])
        self.assertEqual(self.client.get(url+'?version=2').json()['total'],0)
        self.assertEqual(self.client.get(url+'?from=2026-10-05&to=2026-10-01').status_code,400)
    def test_migration_only_recovers_proven_current_version_daily_dates(self):
        code=coding.render_code(self.rule,self.today,7)
        a=CodeAllocation.objects.create(rule=self.rule,rule_version=1,code=code,allocated_by='admin')
        unknown=CodeAllocation.objects.create(rule=self.rule,rule_version=0,code='OLD-0008',allocated_by='admin')
        event=AuditEvent.objects.create(action='coding.allocate',actor='admin',object_type='CodingRule',object_id=str(self.rule.pk),detail={'version':1,'period':self.today.strftime('%Y%m%d'),'codes':[code,'OLD-0008']})
        importlib.import_module('app.migrations.0006_coding_version_lifecycle').preserve_current_rules(apps,None)
        a.refresh_from_db();unknown.refresh_from_db();self.assertEqual(a.business_date,self.today);self.assertEqual(a.sequence,7);self.assertEqual(a.definition['audit_event_id'],event.pk)
        self.assertEqual(a.code,code);self.assertIsNone(unknown.business_date);self.assertEqual(unknown.definition,{})
        self.assertIsNone(CodingRuleVersion.objects.get().effective_from)
    def test_migration_monthly_audit_does_not_invent_exact_business_day(self):
        self.rule.reset_period='month';self.rule.date_format='%Y%m';self.rule.save();code=coding.render_code(self.rule,self.today,3)
        a=CodeAllocation.objects.create(rule=self.rule,rule_version=1,code=code,allocated_by='admin')
        AuditEvent.objects.create(action='coding.allocate',actor='admin',object_type='CodingRule',object_id=str(self.rule.pk),detail={'version':1,'period':self.today.strftime('%Y%m'),'codes':[code]})
        importlib.import_module('app.migrations.0006_coding_version_lifecycle').preserve_current_rules(apps,None)
        a.refresh_from_db();self.assertIsNone(a.business_date);self.assertEqual(a.sequence,3);self.assertEqual(a.period,self.today.strftime('%Y%m'))

class CodingConcurrencyTests(TransactionTestCase):
    def test_same_preview_parallel_requests_cannot_both_consume(self):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Barrier
        rule=CodingRule.objects.create(key='parallel',**PAYLOAD);day=timezone.localdate();p=coding.preview(rule.pk,day,1,'admin')
        barrier=Barrier(2);original=coding.plan
        def synchronized(*args,**kwargs):
            result=original(*args,**kwargs);barrier.wait(timeout=10);return result
        def worker():
            close_old_connections()
            try:
                req={'date':str(day),'count':1,'preview':False,'preview_token':p['preview_token'],'request_id':str(uuid.uuid4()),'purpose':'并发申请防重复测试'}
                return coding.issue(rule.pk,req,'admin')
            except (OperationalError,ReviewConflict):return None
            finally:close_old_connections()
        with patch('app.coding.plan',side_effect=synchronized),ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(lambda _:worker(),range(2)))
        self.assertLessEqual(sum(r is not None for r in results),1)
        # SQLite may reject both lock upgrades; a normal retry must issue at most one code.
        if not any(results):coding.allocate(rule.pk,day,1,'admin')
        self.assertEqual(CodeAllocation.objects.count(),1);self.assertEqual(CodeCounter.objects.get().value,1)
