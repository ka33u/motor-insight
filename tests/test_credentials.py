import json
import tempfile
import uuid
from pathlib import Path
from unittest.mock import patch

from django.contrib.auth.models import User, Group
from django.core import signing
from django.core.exceptions import PermissionDenied
from django.test import Client, TestCase, override_settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import OperationalError

from app import access, accounts, credentials, device_files, file_sharing
from app.models import AccountAccessState, AccountChangeLock, AnalysisModel, AuditEvent, Topic, FileReadGrant


class CredentialTests(TestCase):
    OLD = 'Fixture-61!old-secret-value'
    NEW = 'Fixture-83!new-unrelated-value'

    @classmethod
    def setUpTestData(cls):
        cls.users = {}
        for role in access.ROLES:
            u = User.objects.create_user('credential_' + role, password=cls.OLD, first_name='岗位' + role)
            u.groups.add(Group.objects.create(name=role))
            cls.users[role] = u
        cls.admin = cls.users['admin']
        cls.target = cls.users['quality']
        cls.model = AnalysisModel.objects.create(name='保留本人模型', owner=cls.target.username,
            dataset='units', definition={'dimension': 'id', 'metrics': [{'agg': 'count'}], 'chart': 'bar'})
        cls.topic = Topic.objects.create(name='保留本人专题', owner=cls.target.username,
            layout=[{'model_id': cls.model.pk, 'span': 1}])

    def setUp(self):
        self.client.force_login(self.admin)

    def post(self, path, data, client=None):
        return (client or self.client).post(path, json.dumps(data), content_type='application/json')

    def reset_preview(self, user=None, client=None):
        u = user or self.target
        return self.post(f'/api/accounts/{u.pk}/password/preview',
            {'receipt': accounts.current_receipt(u)}, client)

    def reset_body(self, preview=None, **changes):
        p = preview if preview is not None else self.reset_preview().json()
        return {'preview_token': p['preview_token'], 'password': self.NEW,
                'confirmation': self.NEW, 'reason': '模拟账号身份核对及口令恢复', **changes}

    def commit(self, data=None, user=None, client=None):
        return self.post(f'/api/accounts/{(user or self.target).pk}/password/reset',
            data if data is not None else self.reset_body(), client)

    def self_body(self, client, **changes):
        context = client.get('/api/credentials').json()
        return {'context_token': context['context_token'], 'current_password': self.OLD,
                'password': self.NEW, 'confirmation': self.NEW, **changes}

    def login(self, client, user, password):
        return self.post('/api/auth', {'username': user.username, 'password': password}, client)

    def test_preview_is_read_only_and_contains_no_credential_material(self):
        before = list(User.objects.values())
        out = self.reset_preview()
        self.assertEqual(out.status_code, 200, out.content)
        self.assertEqual(before, list(User.objects.values()))
        self.assertFalse(AuditEvent.objects.exists())
        self.assertFalse(AccountChangeLock.objects.exists())
        self.assertFalse(AccountAccessState.objects.exists())
        self.assertEqual(out.json()['owned_models'], 1)
        self.assertEqual(out.json()['owned_topics'], 1)
        decoded = signing.loads(out.json()['preview_token'], salt=credentials.SALT)
        for value in [self.OLD, self.NEW, self.target.password]:
            self.assertNotIn(value, json.dumps(decoded))
            self.assertNotIn(value, out.content.decode())
        self.assertEqual(out['Cache-Control'], 'no-store')

    def test_every_role_can_obtain_only_own_context(self):
        for u in self.users.values():
            self.client.force_login(u)
            r = self.client.get('/api/credentials')
            self.assertEqual(r.status_code, 200)
            self.assertEqual(r.json()['username'], u.username)
            self.assertNotIn('target', r.json())
        self.assertFalse(AuditEvent.objects.exists())

    def test_each_builtin_role_can_change_own_credential_without_new_permissions(self):
        for u in self.users.values():
            c = Client(); c.force_login(u)
            before = accounts.permission_profile(u)
            r = self.post('/api/credentials/change', self.self_body(c), c)
            self.assertEqual(r.status_code, 200, r.content)
            u.refresh_from_db()
            self.assertEqual(before, accounts.permission_profile(u))
            self.assertFalse(c.get('/api/auth').json()['authenticated'])
        self.assertEqual(AuditEvent.objects.filter(action='account.password_change').count(), 6)

    def test_non_admin_cannot_preview_or_reset_other_accounts(self):
        for role, u in self.users.items():
            if role == 'admin':
                continue
            self.client.force_login(u)
            self.assertEqual(self.reset_preview().status_code, 403)
            self.assertEqual(self.commit({}).status_code, 403)
        self.assertFalse(AuditEvent.objects.exists())
        self.assertFalse(AccountChangeLock.objects.exists())

    def test_admin_reset_has_no_role_active_or_ownership_changes(self):
        groups = list(self.target.groups.values_list('name', flat=True))
        before = accounts.permission_profile(self.target)
        models = list(AnalysisModel.objects.values())
        topics = list(Topic.objects.values())
        r = self.commit()
        self.assertEqual(r.status_code, 200, r.content)
        self.target.refresh_from_db()
        self.assertTrue(self.target.check_password(self.NEW))
        self.assertFalse(self.target.check_password(self.OLD))
        self.assertTrue(self.target.is_active)
        self.assertEqual(groups, list(self.target.groups.values_list('name', flat=True)))
        self.assertEqual(before, accounts.permission_profile(self.target))
        self.assertEqual(models, list(AnalysisModel.objects.values()))
        self.assertEqual(topics, list(Topic.objects.values()))
        state = AccountAccessState.objects.get(user=self.target)
        self.assertEqual((state.revision, state.session_epoch), (0, 1))
        self.assertTrue(self.client.get('/api/auth').json()['authenticated'])

    def test_self_change_invalidates_current_and_second_session(self):
        clients = [Client(), Client()]
        for c in clients:
            c.force_login(self.target)
            c.get('/api/auth')
        r = self.post('/api/credentials/change', self.self_body(clients[0]), clients[0])
        self.assertEqual(r.status_code, 200, r.content)
        self.assertTrue(r.json()['signed_out'])
        for c in clients:
            self.assertFalse(c.get('/api/auth').json()['authenticated'])
            self.assertEqual(self.login(c, self.target, self.OLD).status_code, 401)
            self.assertEqual(self.login(c, self.target, self.NEW).status_code, 200)
        self.assertTrue(self.client.get('/api/auth').json()['authenticated'])

    def test_reset_invalidates_two_old_sessions_and_old_exports(self):
        clients = [Client(), Client()]
        for c in clients:
            c.force_login(self.target)
            c.get('/api/auth')
        self.assertEqual(self.commit().status_code, 200)
        for c in clients:
            self.assertEqual(c.get('/api/records/units/export').status_code, 401)
            self.assertEqual(self.login(c, self.target, self.OLD).status_code, 401)
            self.assertEqual(self.login(c, self.target, self.NEW).status_code, 200)
            self.assertEqual(c.get('/api/records/costs/export').status_code, 403)

    def test_reset_inactive_account_does_not_enable_login(self):
        self.target.is_active = False
        self.target.save()
        self.assertEqual(self.commit().status_code, 200)
        self.target.refresh_from_db()
        self.assertFalse(self.target.is_active)
        self.assertTrue(self.target.check_password(self.NEW))
        self.assertEqual(self.login(Client(), self.target, self.NEW).status_code, 401)

    def test_reset_unusable_credential_and_conflict_preserves_role_conflict(self):
        self.target.set_unusable_password()
        self.target.save()
        self.target.groups.add(Group.objects.get(name='finance'))
        self.assertEqual(self.commit().status_code, 200)
        self.target.refresh_from_db()
        self.assertTrue(self.target.check_password(self.NEW))
        self.assertIsNone(access.role(self.target))
        self.assertEqual(self.login(Client(), self.target, self.NEW).status_code, 401)

    def test_self_wrong_current_password_has_no_write_or_audit(self):
        c = Client(); c.force_login(self.target)
        before = self.target.password
        r = self.post('/api/credentials/change', self.self_body(c, current_password='wrong'), c)
        self.assertEqual(r.status_code, 400)
        self.target.refresh_from_db()
        self.assertEqual(self.target.password, before)
        self.assertFalse(AuditEvent.objects.exists())
        self.assertFalse(AccountAccessState.objects.exists())
        self.assertFalse(AccountChangeLock.objects.exists())

    def test_wrong_current_password_even_with_valid_new_password_cannot_reset(self):
        c = Client(); c.force_login(self.target)
        for old in [None, [], 12, '', 'x' * 129]:
            r = self.post('/api/credentials/change', self.self_body(c, current_password=old), c)
            self.assertEqual(r.status_code, 400)
        self.assertFalse(AuditEvent.objects.exists())

    def test_new_password_contract_rejects_weak_same_or_mismatched(self):
        for value, confirmation in [('short', 'short'), ('1' * 129, '1' * 129),
                ('1234567890123456', '1234567890123456'), ('password123456', 'password123456'),
                (self.OLD, self.OLD), (self.NEW, 'different'), (None, None), ([], []),
                ('credential_quality', 'credential_quality')]:
            with self.subTest(value_type=type(value).__name__):
                r = self.commit(self.reset_body(password=value, confirmation=confirmation))
                self.assertEqual(r.status_code, 400, r.content)
        self.assertFalse(AuditEvent.objects.exists())
        self.assertFalse(AccountAccessState.objects.exists())

    def test_password_is_not_trimmed_and_unicode_is_supported(self):
        value = ' 新演示口令-91!多语言验证 '
        r = self.commit(self.reset_body(password=value, confirmation=value))
        self.assertEqual(r.status_code, 200, r.content)
        self.target.refresh_from_db()
        self.assertTrue(self.target.check_password(value))
        self.assertFalse(self.target.check_password(value.strip()))

    def test_admin_cannot_reset_self_without_current_password(self):
        self.assertEqual(self.reset_preview(self.admin).status_code, 400)
        self.assertEqual(self.commit({}, self.admin).status_code, 400)
        # A correctly shaped payload still cannot take the administrator path.
        self.assertEqual(self.commit(self.reset_body(), self.admin).status_code, 400)

    def test_admin_can_change_self_with_current_password(self):
        r = self.post('/api/credentials/change', self.self_body(self.client), self.client)
        self.assertEqual(r.status_code, 200, r.content)
        self.admin.refresh_from_db()
        self.assertEqual(access.role(self.admin), 'admin')
        self.assertEqual(self.login(self.client, self.admin, self.NEW).status_code, 200)

    def test_deployment_superuser_cannot_use_business_credential_workflows(self):
        root = User.objects.create_superuser('deployment_root', password=self.OLD)
        self.assertEqual(self.reset_preview(root).status_code, 403)
        self.assertEqual(self.commit(self.reset_body(), root).status_code, 403)
        c = Client(); c.force_login(root)
        self.assertEqual(c.get('/api/credentials').status_code, 403)
        self.assertEqual(self.post('/api/credentials/change', {}, c).status_code, 400)
        data = {'context_token': credentials.token(root, root, 'self'), 'current_password': self.OLD,
                'password': self.NEW, 'confirmation': self.NEW}
        self.assertEqual(self.post('/api/credentials/change', data, c).status_code, 403)

    def test_preview_requires_current_detail_receipt(self):
        for data in [{}, {'receipt': 'old'}, {'receipt': []}, {'receipt': 'old', 'password': self.NEW}]:
            self.assertIn(self.post(f'/api/accounts/{self.target.pk}/password/preview', data).status_code, [400, 409])
        p = accounts.current_receipt(self.target)
        self.target.first_name = '外部修改显示名称'; self.target.save()
        self.assertEqual(self.post(f'/api/accounts/{self.target.pk}/password/preview', {'receipt': p}).status_code, 409)

    def test_preview_token_bound_to_actor_target_and_action(self):
        body = self.reset_body()
        other = self.users['operations']
        self.assertEqual(self.commit(body, other).status_code, 409)
        admin2 = User.objects.create_user('other_admin', password=self.OLD)
        admin2.groups.add(Group.objects.get(name='admin'))
        c = Client(); c.force_login(admin2)
        self.assertEqual(self.commit(body, client=c).status_code, 409)
        c = Client(); c.force_login(self.target)
        data = self.self_body(c, context_token=body['preview_token'])
        self.assertEqual(self.post('/api/credentials/change', data, c).status_code, 409)

    def test_modified_expired_or_invalid_tokens_are_rejected(self):
        for value in [None, [], 'invalid', 'x' * 16001]:
            self.assertEqual(self.commit(self.reset_body(preview_token=value)).status_code, 409)
        with patch('django.core.signing.time.time', return_value=1000):
            body = self.reset_body()
        with patch('django.core.signing.time.time', return_value=1601):
            self.assertEqual(self.commit(body).status_code, 409)
        self.assertFalse(AuditEvent.objects.exists())

    def test_signed_wrong_shape_token_is_rejected_without_disclosing_content(self):
        for data in [[], {}, {'unexpected': self.NEW}]:
            value = signing.dumps(data, salt=credentials.SALT)
            r = self.commit(self.reset_body(preview_token=value))
            self.assertEqual(r.status_code, 409)
            self.assertNotIn(self.NEW, r.content.decode())

    def test_external_account_changes_invalidate_reset_preview(self):
        for kind in ['role', 'active', 'credential', 'display', 'state']:
            with self.subTest(kind=kind):
                body = self.reset_body()
                if kind == 'role': self.target.groups.set([Group.objects.get(name='operations')])
                elif kind == 'active': self.target.is_active = False; self.target.save()
                elif kind == 'credential': self.target.set_password('Another-90!external-secret'); self.target.save()
                elif kind == 'display': self.target.first_name = '外部维护'; self.target.save()
                else: AccountAccessState.objects.create(user=self.target, revision=1)
                self.assertEqual(self.commit(body).status_code, 409)
        self.assertFalse(AuditEvent.objects.filter(action='account.password_reset').exists())

    def test_replayed_success_does_not_write_second_change(self):
        data = self.reset_body()
        self.assertEqual(self.commit(data).status_code, 200)
        self.assertEqual(self.commit(data).status_code, 409)
        self.assertEqual(AuditEvent.objects.filter(action='account.password_reset').count(), 1)
        self.assertEqual(AccountAccessState.objects.get(user=self.target).session_epoch, 1)

    def test_competing_admin_previews_cannot_overwrite_first_success(self):
        data = self.reset_body()
        other = User.objects.create_user('second_credential_admin', password=self.OLD)
        other.groups.add(Group.objects.get(name='admin'))
        c = Client(); c.force_login(other)
        preview = self.reset_preview(client=c).json()
        second = self.reset_body(preview, password='Other-94!competing-secret', confirmation='Other-94!competing-secret')
        self.assertEqual(self.commit(data).status_code, 200)
        self.assertEqual(self.commit(second, client=c).status_code, 409)
        self.target.refresh_from_db()
        self.assertTrue(self.target.check_password(self.NEW))
        self.assertEqual(AuditEvent.objects.filter(action='account.password_reset').count(), 1)

    def test_credential_change_invalidates_old_role_and_revoke_receipts(self):
        p = accounts.preview(self.admin, self.target,
            {'display_name': self.target.first_name, 'role': 'viewer', 'is_active': True})
        receipt = accounts.current_receipt(self.target)
        self.assertEqual(self.commit().status_code, 200)
        self.assertEqual(self.post(f'/api/accounts/{self.target.pk}/update',
            {'preview_token': p['preview_token'], 'reason': '旧岗位核对不得覆盖口令维护'}).status_code, 409)
        self.assertEqual(self.post(f'/api/accounts/{self.target.pk}/revoke',
            {'receipt': receipt, 'reason': '旧账号凭据不得重复操作'}).status_code, 409)

    def test_authority_rechecked_even_with_old_actor_object(self):
        data = self.reset_body()
        self.admin.groups.set([Group.objects.get(name='viewer')])
        with self.assertRaises(PermissionDenied):
            credentials.reset(self.admin, self.target.pk, data)
        self.assertFalse(AuditEvent.objects.exists())

    def test_secret_never_in_success_audit_context_or_account_history(self):
        self.assertEqual(self.commit().status_code, 200)
        self.target.refresh_from_db()
        out = self.client.get(f'/api/accounts/{self.target.pk}')
        events = json.dumps(list(AuditEvent.objects.values()), default=str)
        for value in [self.OLD, self.NEW, self.target.password]:
            self.assertNotIn(value, out.content.decode())
            self.assertNotIn(value, events)
        e = AuditEvent.objects.get(action='account.password_reset')
        self.assertTrue(e.detail['credential_changed'])
        self.assertFalse(e.detail['permissions_changed'])

    def test_reason_cannot_contain_new_password(self):
        r = self.commit(self.reset_body(reason='重设口令为' + self.NEW))
        self.assertEqual(r.status_code, 400)
        self.assertFalse(AuditEvent.objects.exists())

    def test_missing_short_or_non_text_reason_has_no_write(self):
        for value in ['', '短', None, [], 'x' * 1001]:
            self.assertEqual(self.commit(self.reset_body(reason=value)).status_code, 400)
        self.assertFalse(AuditEvent.objects.exists())

    def test_audit_failure_rolls_back_password_epoch_revision_and_lock(self):
        data = self.reset_body(); before = self.target.password
        with patch('app.credentials.AuditEvent.objects.create', side_effect=RuntimeError('audit unavailable')):
            self.assertEqual(self.commit(data).status_code, 500)
        self.target.refresh_from_db()
        self.assertEqual(self.target.password, before)
        self.assertFalse(AccountAccessState.objects.exists())
        self.assertFalse(AccountChangeLock.objects.exists())
        self.assertFalse(AuditEvent.objects.exists())

    def test_self_audit_failure_preserves_existing_login(self):
        c = Client(); c.force_login(self.target)
        data = self.self_body(c)
        with patch('app.credentials.AuditEvent.objects.create', side_effect=RuntimeError('audit unavailable')):
            self.assertEqual(self.post('/api/credentials/change', data, c).status_code, 500)
        self.assertTrue(c.get('/api/auth').json()['authenticated'])
        self.target.refresh_from_db()
        self.assertTrue(self.target.check_password(self.OLD))
        self.assertFalse(AccountAccessState.objects.exists())

    @override_settings(DEBUG=True)
    def test_unexpected_failure_never_returns_debug_traceback_with_submitted_secrets(self):
        data = self.reset_body()
        for kind in [RuntimeError, ValueError, TypeError, OperationalError]:
            with patch('app.credentials.AuditEvent.objects.create', side_effect=kind('unexpected '+self.NEW)):
                r = self.commit(data)
            self.assertIn(r.status_code, [400, 500])
            self.assertEqual(r['Content-Type'], 'application/json')
            self.assertEqual(r['Cache-Control'], 'no-store')
            self.assertNotIn(self.NEW, r.content.decode())
            self.assertNotIn(self.OLD, r.content.decode())
            self.assertNotIn('Traceback', r.content.decode())
        self.assertFalse(AccountAccessState.objects.exists())

    def test_existing_epoch_advances_instead_of_resetting(self):
        AccountAccessState.objects.create(user=self.target, revision=7, session_epoch=12)
        self.assertEqual(self.commit().status_code, 200)
        state = AccountAccessState.objects.get(user=self.target)
        self.assertEqual((state.revision, state.session_epoch), (7, 13))

    def test_existing_original_read_grant_survives_reset_and_self_change(self):
        with tempfile.TemporaryDirectory() as directory, override_settings(DEVICE_FILE_ROOT=Path(directory)):
            f = device_files.upload(self.admin, SimpleUploadedFile('模拟协作原件.txt', b'synthetic shared original'),
                uuid.uuid4(), '模拟原件只读授权用于口令维护验证')
            change = {'recipient_id': self.target.pk, 'action': 'grant',
                      'reason': '模拟原件协作核对依据', 'expires_at': ''}
            preview = file_sharing.preview(self.admin, f.pk, change)
            file_sharing.commit(self.admin, f.pk, {**change, 'token': preview['token'], 'request_id': str(uuid.uuid4())})
            before = list(FileReadGrant.objects.values())
            receipt = file_sharing.account_receipt(self.target)
            self.assertEqual(self.commit().status_code, 200)
            self.target.refresh_from_db()
            self.assertEqual(file_sharing.account_receipt(self.target), receipt)
            self.assertEqual(file_sharing.readable(self.target, f.pk)[0].pk, f.pk)
            c = Client(); self.assertEqual(self.login(c, self.target, self.NEW).status_code, 200)
            data = self.self_body(c, current_password=self.NEW,
                                  password='Further-65!self-change-value', confirmation='Further-65!self-change-value')
            self.assertEqual(self.post('/api/credentials/change', data, c).status_code, 200)
            self.target.refresh_from_db()
            self.assertEqual(file_sharing.account_receipt(self.target), receipt)
            self.assertEqual(file_sharing.readable(self.target, f.pk)[0].pk, f.pk)
            self.assertEqual(before, list(FileReadGrant.objects.values()))

    def test_extra_privileged_or_wrong_user_fields_rejected(self):
        for extra in [{'is_active': True}, {'role': 'admin'}, {'username': 'rename'}, {'target': self.admin.pk}, {'is_superuser': True}]:
            self.assertEqual(self.commit(self.reset_body(**extra)).status_code, 400)
        c = Client(); c.force_login(self.target)
        self.assertEqual(self.post('/api/credentials/change', self.self_body(c, target=self.admin.pk), c).status_code, 400)

    def test_anonymous_methods_and_deleted_target(self):
        c = Client()
        self.assertEqual(c.get('/api/credentials').status_code, 401)
        self.assertEqual(self.post('/api/credentials/change', {}, c).status_code, 401)
        self.assertEqual(self.reset_preview(client=c).status_code, 401)
        self.assertEqual(self.commit({}, client=c).status_code, 401)
        self.assertEqual(self.client.post('/api/credentials', '{}', content_type='application/json').status_code, 405)
        self.assertEqual(self.client.get('/api/credentials/change').status_code, 405)
        self.assertEqual(self.client.get(f'/api/accounts/{self.target.pk}/password/reset').status_code, 405)
        self.assertEqual(self.post('/api/accounts/99999/password/preview', {'receipt': 'x'}).status_code, 404)

    def test_csrf_required_for_every_mutation(self):
        c = Client(enforce_csrf_checks=True); c.force_login(self.admin)
        for path in ['/api/credentials/change', f'/api/accounts/{self.target.pk}/password/preview', f'/api/accounts/{self.target.pk}/password/reset']:
            self.assertEqual(self.post(path, {}, c).status_code, 403)

    def test_self_inactive_or_conflicting_account_cannot_change(self):
        for kind in ['inactive', 'conflict']:
            self.target.is_active = True; self.target.save()
            c = Client(); c.force_login(self.target)
            data = self.self_body(c)
            if kind == 'inactive': self.target.is_active = False; self.target.save()
            else: self.target.is_active = True; self.target.save(); self.target.groups.add(Group.objects.get(name='finance'))
            self.assertEqual(self.post('/api/credentials/change', data, c).status_code, 401)
        self.assertFalse(AuditEvent.objects.exists())
