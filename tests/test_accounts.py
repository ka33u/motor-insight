import json
from unittest.mock import patch
from django.contrib.auth.models import User,Group,AnonymousUser
from django.core.exceptions import ValidationError,PermissionDenied
from django.test import TestCase,Client
from app import accounts,access
from app.models import AccountAccessState,AuditEvent,AnalysisModel,Topic,ImportBatch,ImportRow,Record
from app.ingestion import fingerprint

class AccountTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.users={}
        for role in access.ROLES:
            u=User.objects.create_user('test_'+role,password='S7!fixture-strong-secret',first_name=role)
            u.groups.add(Group.objects.create(name=role));cls.users[role]=u
        cls.admin=cls.users['admin'];cls.target=cls.users['quality']
        cls.model=AnalysisModel.objects.create(name='本人质量数量',dataset='units',definition={'dimension':'id','metrics':[{'agg':'count'}],'chart':'bar'},owner=cls.target.username)
        cls.topic=Topic.objects.create(name='本人质量专题',owner=cls.target.username,layout=[{'model_id':cls.model.pk,'span':1}])
        cls.batch=ImportBatch.objects.create(filename='permissions.xlsx',file_hash='x',file_path='/not-used',status='committed')
        for ds,values in [('products',{'id':'CP.00001.A','family':'YE3','price_cents':123456}),('costs',{'id':'C01','amount_cents':12345}),('attendance',{'id':'A01','employee_id':'E01','date':'2026-10-01','productive_hours':8})]:
            r=ImportRow.objects.create(batch=cls.batch,sheet=ds,row_number=2,dataset=ds,business_key=values['id'],raw=values,normalized=values,record_hash=fingerprint(values),status='committed')
            Record.objects.create(dataset=ds,business_key=values['id'],values=values,record_hash=r.record_hash,source_row=r)
    def setUp(self):self.client.force_login(self.admin)
    def post(self,path,payload,client=None):return (client or self.client).post(path,json.dumps(payload),content_type='application/json')
    def proposal(self,user=None,**changes):
        u=user or self.target
        return {'display_name':u.first_name,'role':access.role(u),'is_active':u.is_active,**changes}
    def preview(self,user=None,**changes):
        u=user or self.target;r=self.post(f'/api/accounts/{u.pk}/preview',self.proposal(u,**changes));self.assertEqual(r.status_code,200,r.content);return r.json()
    def commit(self,preview,user=None,client=None):return self.post(f'/api/accounts/{(user or self.target).pk}/update',{'preview_token':preview['preview_token'],'reason':'模拟岗位调整验收'},client)
    def create_payload(self,**kwargs):return {'username':'new_quality','display_name':'模拟质量新账号','role':'quality','is_active':True,'password':'Fixture-90!unrelated-secret','reason':'模拟新岗位访问验收',**kwargs}
    def test_admin_list_and_detail_no_password_or_contact_fields(self):
        r=self.client.get('/api/accounts');self.assertEqual(r.status_code,200);self.assertEqual(r.json()['summary']['total'],6);self.assertEqual(r['Cache-Control'],'no-store')
        d=self.client.get(f'/api/accounts/{self.target.pk}').json();self.assertEqual(d['user']['role'],'quality')
        for text in [self.target.password,'S7!fixture-strong-secret','email','user_permissions']:
            self.assertNotIn(text,json.dumps(d))
    def test_all_non_admin_roles_blocked_on_all_admin_endpoints(self):
        for role,u in self.users.items():
            if role=='admin':continue
            self.client.force_login(u)
            self.assertEqual(self.client.get('/api/accounts').status_code,403)
            self.assertEqual(self.client.get(f'/api/accounts/{self.target.pk}').status_code,403)
            for action,payload in [('preview',self.proposal()),('update',{}),('revoke',{})]:
                self.assertEqual(self.post(f'/api/accounts/{self.target.pk}/{action}',payload).status_code,403)
            self.assertEqual(self.post('/api/accounts',self.create_payload()).status_code,403)
        self.assertFalse(AuditEvent.objects.filter(object_type='UserAccess').exists())
    def test_anonymous_is_401_and_methods_rejected(self):
        self.client.logout();self.assertEqual(self.client.get('/api/accounts').status_code,401)
        self.client.force_login(self.admin);self.assertEqual(self.client.delete('/api/accounts').status_code,405)
    def test_filter_role_status_search_paging_validation(self):
        self.target.is_active=False;self.target.save()
        r=self.client.get('/api/accounts?q=quality&status=inactive&role=quality').json();self.assertEqual(r['total'],1);self.assertEqual(r['rows'][0]['id'],self.target.pk)
        self.assertEqual(self.client.get('/api/accounts?page=2').json()['rows'],[])
        for q in ['status=x','role=unknown','q='+'x'*151,'page=bad']:self.assertEqual(self.client.get('/api/accounts?'+q).status_code,400)
    def test_permission_matrix_uses_record_and_export_rules(self):
        for role,u in self.users.items():
            profile=accounts.permission_profile(u);self.client.force_login(u)
            for ds in ['products','costs','attendance']:
                expected=next(x for x in profile['datasets'] if x['id']==ds)
                self.assertEqual(self.client.get('/api/records/'+ds).status_code,200 if expected['allowed'] else 403)
                export=self.client.get('/api/records/'+ds+'/export');self.assertEqual(export.status_code,200 if expected['allowed'] else 403)
                if ds=='products' and not profile['capabilities']['money']:
                    self.assertNotIn('123456',export.content.decode())
                    self.assertNotIn('price_cents',self.client.get('/api/records/products').json()['rows'][0]['values'])
    def test_no_group_fallback_and_unknown_groups_preserved(self):
        self.target.groups.clear();self.target.groups.add(Group.objects.create(name='external'))
        self.assertEqual(access.role(self.target),'viewer');self.assertTrue(accounts.profile(self.target)['role_fallback'])
        out=self.commit(self.preview(role='quality'));self.assertEqual(out.status_code,200)
        self.assertEqual(set(self.target.groups.values_list('name',flat=True)),{'external','quality'})
    def test_conflicting_roles_fail_closed_and_are_repairable(self):
        self.target.groups.add(Group.objects.get(name='finance'));self.assertIsNone(access.role(self.target));self.assertFalse(access.allowed(self.target,'products'))
        c=Client();c.force_login(self.target);self.assertEqual(c.get('/api/overview').status_code,401)
        self.assertEqual(self.post('/api/auth',{'username':self.target.username,'password':'S7!fixture-strong-secret'},c).status_code,401)
        self.assertEqual(self.client.get('/api/accounts?status=conflict').json()['total'],1)
        self.assertEqual(self.commit(self.preview(role='quality')).status_code,200)
        self.target.refresh_from_db();self.assertEqual(access.role(self.target),'quality')
    def test_inactive_and_anonymous_have_no_role(self):
        self.target.is_active=False;self.assertIsNone(access.role(self.target));self.assertIsNone(access.role(AnonymousUser()))
    def test_preview_has_no_mutation_and_names_existing_impact(self):
        prior=list(User.objects.values());out=self.preview(role='viewer')
        self.assertEqual(prior,list(User.objects.values()));self.assertFalse(AuditEvent.objects.exists());self.assertFalse(AccountAccessState.objects.exists())
        self.assertEqual(out['impact']['owned_models'],1);self.assertEqual(out['impact']['owned_topics'],1);self.assertEqual(out['impact']['affected_model_count'],1)
    def test_role_change_preserves_business_owners_and_audits(self):
        before=list(Record.objects.values());r=self.commit(self.preview(role='operations'));self.assertEqual(r.status_code,200,r.content)
        self.assertEqual(r.json()['user']['revision'],1);self.assertEqual(r.json()['user']['session_epoch'],1)
        self.target.refresh_from_db();self.assertEqual(access.role(self.target),'operations')
        self.model.refresh_from_db();self.topic.refresh_from_db();self.assertEqual(self.model.owner,self.target.username);self.assertEqual(self.topic.owner,self.target.username)
        self.assertEqual(before,list(Record.objects.values()));self.assertEqual(AuditEvent.objects.get().detail['reason'],'模拟岗位调整验收')
    def test_stale_or_replayed_preview_rejected(self):
        p=self.preview(role='operations');self.assertEqual(self.commit(p).status_code,200);self.assertEqual(self.commit(p).status_code,409)
        self.assertEqual(AuditEvent.objects.filter(action='account.update').count(),1)
    def test_preview_detects_external_groups_or_credentials_change(self):
        p=self.preview(role='viewer');self.target.groups.add(Group.objects.create(name='unmanaged'))
        self.assertEqual(self.commit(p).status_code,409)
        p=self.preview(role='viewer');self.target.set_password('Different-8!fixture-password');self.target.save()
        self.assertEqual(self.commit(p).status_code,409)
    def test_preview_bound_to_actor_target_and_signature(self):
        p=self.preview(role='viewer');other=self.users['operations']
        self.assertEqual(self.commit(p,other).status_code,409)
        p['preview_token']+='bad';self.assertEqual(self.commit(p).status_code,409)
        p=self.preview(role='viewer');new=User.objects.create_user('admin2',password='test-password');new.groups.add(Group.objects.get(name='admin'));c=Client();c.force_login(new)
        self.assertEqual(self.commit(p,client=c).status_code,409)
    def test_preview_expiration(self):
        with patch('django.core.signing.time.time',return_value=1000):p=self.preview(role='viewer')
        with patch('django.core.signing.time.time',return_value=1601):self.assertEqual(self.commit(p).status_code,409)
    def test_no_change_does_not_write_audit_or_revision(self):
        r=self.commit(self.preview());self.assertFalse(r.json()['changed']);self.assertFalse(AuditEvent.objects.exists());self.assertFalse(AccountAccessState.objects.exists())
    def test_display_only_does_not_revoke_sessions(self):
        c=Client();c.force_login(self.target);self.assertEqual(c.get('/api/auth').status_code,200)
        r=self.commit(self.preview(display_name='质量岗位显示名称'));self.assertEqual(r.json()['user']['session_epoch'],0)
        self.assertTrue(c.get('/api/auth').json()['authenticated'])
    def test_downgrade_revokes_two_sessions_and_new_login_rechecks_exports(self):
        u=self.users['finance'];clients=[Client(),Client()]
        for c in clients:c.force_login(u);self.assertEqual(c.get('/api/records/costs').status_code,200)
        self.assertEqual(self.commit(self.preview(u,role='viewer'),u).status_code,200)
        for c in clients:
            self.assertEqual(c.get('/api/records/costs/export').status_code,401)
            self.assertEqual(self.post('/api/auth',{'username':u.username,'password':'S7!fixture-strong-secret'},c).status_code,200)
            self.assertEqual(c.get('/api/records/costs/export').status_code,403)
    def test_upgrade_also_revokes_old_session(self):
        c=Client();c.force_login(self.target);c.get('/api/auth')
        self.assertEqual(self.commit(self.preview(role='finance')).status_code,200)
        self.assertEqual(c.get('/api/records/costs').status_code,401)
        self.assertEqual(self.post('/api/auth',{'username':self.target.username,'password':'S7!fixture-strong-secret'},c).status_code,200)
        self.assertEqual(c.get('/api/records/costs').status_code,200)
    def test_disable_reenable_does_not_restore_old_sessions(self):
        c=Client();c.force_login(self.target);c.get('/api/auth');self.assertEqual(self.commit(self.preview(is_active=False)).status_code,200)
        self.target.refresh_from_db();self.assertEqual(self.commit(self.preview(role='quality',is_active=True)).status_code,200)
        self.assertFalse(c.get('/api/auth').json()['authenticated'])
    def test_disable_prevents_login_and_does_not_delete(self):
        self.assertEqual(self.commit(self.preview(is_active=False)).status_code,200)
        c=Client();self.assertEqual(self.post('/api/auth',{'username':self.target.username,'password':'S7!fixture-strong-secret'},c).status_code,401)
        self.assertTrue(User.objects.filter(pk=self.target.pk).exists());self.assertTrue(AnalysisModel.objects.filter(pk=self.model.pk).exists())
    def test_explicit_revoke_blocks_old_sessions_but_allows_relogin(self):
        c=Client();c.force_login(self.target);c.get('/api/auth');d=self.client.get(f'/api/accounts/{self.target.pk}').json()
        p={'receipt':d['receipt'],'reason':'模拟异常登录处置'};r=self.post(f'/api/accounts/{self.target.pk}/revoke',p);self.assertEqual(r.status_code,200)
        self.assertFalse(c.get('/api/auth').json()['authenticated']);self.assertEqual(self.post(f'/api/accounts/{self.target.pk}/revoke',p).status_code,409)
        self.assertEqual(self.post('/api/auth',{'username':self.target.username,'password':'S7!fixture-strong-secret'},c).status_code,200)
    def test_external_role_edit_revokes_bound_session(self):
        c=Client();c.force_login(self.target);c.get('/api/auth');self.target.groups.set([Group.objects.get(name='viewer')]);self.assertFalse(c.get('/api/auth').json()['authenticated'])
    def test_self_lockout_and_last_admin_guard(self):
        for p in [self.proposal(self.admin,role='viewer'),self.proposal(self.admin,is_active=False)]:self.assertEqual(self.post(f'/api/accounts/{self.admin.pk}/preview',p).status_code,400)
        second=self.users['analyst']
        with self.assertRaises(ValidationError):accounts.guard(second,self.admin,self.proposal(self.admin,role='viewer'))
    def test_superuser_is_readonly_even_for_admin(self):
        root=User.objects.create_superuser('root',password='S7!fixture-strong-secret')
        self.assertEqual(self.post(f'/api/accounts/{root.pk}/preview',{'display_name':'root','role':'viewer','is_active':True}).status_code,403)
        self.assertEqual(self.post(f'/api/accounts/{root.pk}/revoke',{'receipt':accounts.current_receipt(root),'reason':'不应允许普通管理员操作'}).status_code,403)
    def test_recheck_actor_authority_inside_transaction(self):
        p=self.preview(role='viewer');self.admin.groups.set([Group.objects.get(name='viewer')])
        with self.assertRaises(PermissionDenied):accounts.update(self.admin,self.target.pk,{'preview_token':p['preview_token'],'reason':'旧权限不得继续写入'})
    def test_audit_failure_rolls_back_role_and_epoch(self):
        p=self.preview(role='viewer')
        with patch('app.accounts.AuditEvent.objects.create',side_effect=RuntimeError('audit offline')):
            with self.assertRaises(RuntimeError):self.commit(p)
        self.target.refresh_from_db();self.assertEqual(access.role(self.target),'quality');self.assertFalse(AccountAccessState.objects.exists())
    def test_invalid_payloads_and_reason(self):
        for change in [{'is_active':1},{'role':['admin']},{'role':'unknown'},{'display_name':'  '},{'username':'rename'},{'is_superuser':True}]:
            self.assertEqual(self.post(f'/api/accounts/{self.target.pk}/preview',self.proposal(**change)).status_code,400)
        p=self.preview(role='viewer');self.assertEqual(self.post(f'/api/accounts/{self.target.pk}/update',{'preview_token':p['preview_token'],'reason':'短'}).status_code,400)
    def test_create_hashes_password_with_no_privileged_flags_or_secret_in_audit(self):
        payload=self.create_payload();r=self.post('/api/accounts',payload);self.assertEqual(r.status_code,201,r.content);u=User.objects.get(username=payload['username'])
        self.assertTrue(u.check_password(payload['password']));self.assertFalse(u.is_staff);self.assertFalse(u.is_superuser);self.assertEqual(access.role(u),'quality')
        event=json.dumps(AuditEvent.objects.get().detail);self.assertNotIn(payload['password'],event);self.assertNotIn(u.password,event)
    def test_create_inactive_and_reject_weak_duplicate_invalid_or_privileged(self):
        self.assertEqual(self.post('/api/accounts',self.create_payload(is_active=False)).status_code,201)
        self.assertEqual(self.post('/api/accounts',self.create_payload()).status_code,400)
        for p in [{'username':'NEW_USER'},{'username':'bad space'},{'password':'short'},{'password':'1234567890123456'},{'password':'password123456'},{'password':['invalid']},{'is_superuser':True},{'groups':['admin']}]:
            self.assertEqual(self.post('/api/accounts',self.create_payload(username='other_user')|p).status_code,400)
    def test_create_case_insensitive_uniqueness(self):
        User.objects.create_user('NEW_QUALITY')
        self.assertEqual(self.post('/api/accounts',self.create_payload()).status_code,400)
    def test_create_failure_rolls_back_user_and_audit(self):
        with patch('app.accounts.AuditEvent.objects.create',side_effect=RuntimeError('audit unavailable')):
            with self.assertRaises(RuntimeError):self.post('/api/accounts',self.create_payload())
        self.assertFalse(User.objects.filter(username='new_quality').exists())
    def test_csrf_required_for_create_preview_update_and_revoke(self):
        c=Client(enforce_csrf_checks=True);c.force_login(self.admin)
        for url in ['/api/accounts',*[f'/api/accounts/{self.target.pk}/{a}' for a in ['preview','update','revoke']]]:self.assertEqual(self.post(url,{},c).status_code,403)
    def test_deleted_target_returns_404(self):self.assertEqual(self.client.get('/api/accounts/99999').status_code,404)
