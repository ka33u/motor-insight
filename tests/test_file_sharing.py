import copy,json,tempfile,uuid
from pathlib import Path
from datetime import timedelta
from unittest.mock import patch
from django.test import Client,override_settings
from django.contrib.auth.models import User,Group
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.exceptions import ValidationError,PermissionDenied
from django.db import transaction,IntegrityError
from django.utils import timezone
from app import file_sharing as share,device_files as df,material_certificates as cert,analytics
from app.models import FileReadGrant,DeviceFile,AuditEvent,Record,AccountAccessState
from app.import_review import ReviewConflict
from tests.test_platform import PlatformCase
from tests.test_material_certificates import fixture,raw

class SharingCase(PlatformCase):
    def setUp(self):
        super().setUp();self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.override=override_settings(DEVICE_FILE_ROOT=Path(self.temp.name));self.override.enable();self.addCleanup(self.override.disable)
        self.viewer=User.objects.create_user('reader',password='test-password');self.viewer.groups.add(Group.objects.create(name='viewer'))
        self.file=df.upload(self.admin,SimpleUploadedFile('模拟私有证明.txt',b'synthetic original'),uuid.uuid4(),'模拟设备原件，仅用于授权测试')
        self.record('departments',dict(id='D1',name='质量',owner='模拟人员'));self.before=list(Record.objects.values());self.client.force_login(self.admin)
    def data(self,user=None,action='grant',expires=''):
        return dict(recipient_id=(user or self.quality).pk,action=action,reason='模拟原件协作核对依据',expires_at=expires)
    def payload(self,user=None,action='grant',expires=''):
        d=self.data(user,action,expires);p=share.preview(self.admin,self.file.pk,d);return d|dict(token=p['token'],request_id=str(uuid.uuid4()))
    def grant(self,user=None,action='grant',expires=''):
        return share.commit(self.admin,self.file.pk,self.payload(user,action,expires))
    def post(self,url,data,client=None):return (client or self.client).post(url,json.dumps(data),content_type='application/json')
    def api(self,suffix=''):return '/api/file-sharing/'+str(self.file.pk)+suffix
    def read_api(self,suffix=''):return '/api/shared-originals/'+str(self.file.pk)+suffix

class FileSharingTests(SharingCase):
    def test_default_private_and_no_admin_override(self):
        self.assertRaises(DeviceFile.DoesNotExist,share.readable,self.quality,self.file.pk)
        other=User.objects.create_user('another-admin');other.groups.add(Group.objects.get(name='admin'))
        self.assertRaises(DeviceFile.DoesNotExist,share.readable,other,self.file.pk)
        self.assertEqual(share.listing(self.viewer)['rows'],[])
    def test_preview_is_read_only_and_names_scope(self):
        old=AuditEvent.objects.count();p=share.preview(self.admin,self.file.pk,self.data(self.viewer))
        self.assertEqual(p['recipient']['id'],self.viewer.pk);self.assertEqual(p['file']['file_hash'],self.file.file_hash)
        self.assertEqual(FileReadGrant.objects.count(),0);self.assertEqual(AuditEvent.objects.count(),old)
    def test_owner_only_grants_even_for_platform_admin(self):
        self.assertRaises(DeviceFile.DoesNotExist,share.preview,self.quality,self.file.pk,self.data(self.viewer))
        self.assertRaises(PermissionDenied,share.preview,self.viewer,self.file.pk,self.data())
        self.assertRaises(ValidationError,share.preview,self.admin,self.file.pk,self.data(self.admin))
    def test_grant_allows_exact_recipient_and_no_association_or_reshare(self):
        e=self.grant(self.viewer);f,receipt=share.readable(self.viewer,self.file.pk)
        self.assertEqual(f.pk,self.file.pk);self.assertIn(e.payload_hash,receipt)
        self.assertRaises(DeviceFile.DoesNotExist,share.readable,self.quality,self.file.pk)
        self.assertRaises(PermissionDenied,df.get,self.viewer,self.file.pk)
        self.assertRaises(PermissionDenied,share.preview,self.viewer,self.file.pk,self.data())
        self.assertFalse(share.detail(self.viewer,self.file.pk)['grant']['payload']['association_rights'])
    def test_quality_recipient_can_read_but_cannot_confirm_owner_link(self):
        self.grant();share.readable(self.quality,self.file.pk)
        self.assertRaises(DeviceFile.DoesNotExist,df.get,self.quality,self.file.pk)
        self.assertRaises(DeviceFile.DoesNotExist,df.preview,self.quality,self.file.pk,'T1')
        self.assertRaises(DeviceFile.DoesNotExist,share.context,self.quality,self.file.pk)
    def test_revoke_stops_next_read_and_regrant_is_new_version(self):
        a=self.grant();b=self.grant(action='revoke')
        self.assertEqual([a.version,b.version],[1,2]);self.assertRaises(DeviceFile.DoesNotExist,share.readable,self.quality,self.file.pk)
        self.assertEqual(share.listing(self.quality)['rows'],[]);c=self.grant();self.assertEqual(c.version,3);share.readable(self.quality,self.file.pk)
    def test_exact_expiry_boundary_and_owner_access_survives(self):
        t=(timezone.now()+timedelta(hours=1)).replace(microsecond=0);stamp=t.strftime('%Y-%m-%dT%H:%M:%SZ');e=self.grant(expires=stamp)
        self.assertEqual(share.grant_state(e,self.quality,t-timedelta(microseconds=1)),'active')
        self.assertEqual(share.grant_state(e,self.quality,t),'expired')
        with patch('app.file_sharing.timezone.now',return_value=t):self.assertRaises(DeviceFile.DoesNotExist,share.readable,self.quality,self.file.pk)
        share.readable(self.admin,self.file.pk)
    def test_role_change_and_account_revision_need_new_grant(self):
        self.grant();self.quality.groups.clear();self.quality.groups.add(Group.objects.get(name='viewer'))
        self.assertRaises(DeviceFile.DoesNotExist,share.readable,self.quality,self.file.pk)
        self.quality.groups.clear();self.quality.groups.add(Group.objects.get(name='quality'))
        AccountAccessState.objects.create(user=self.quality,revision=1)
        self.assertRaises(DeviceFile.DoesNotExist,share.readable,self.quality,self.file.pk)
        self.grant();share.readable(self.quality,self.file.pk)
    def test_inactive_and_conflicting_accounts_cannot_receive_or_read(self):
        self.grant();self.quality.is_active=False;self.quality.save()
        self.assertRaises(PermissionDenied,share.readable,self.quality,self.file.pk)
        self.assertRaises(ValidationError,share.preview,self.admin,self.file.pk,self.data())
        self.quality.is_active=True;self.quality.save();self.quality.groups.add(Group.objects.get(name='viewer'))
        self.assertRaises(ValidationError,share.preview,self.admin,self.file.pk,self.data())
    def test_owner_role_revocation_blocks_grant_management(self):
        self.admin.groups.clear();self.assertRaises(PermissionDenied,share.context,self.admin,self.file.pk)
        self.assertRaises(PermissionDenied,share.commit,self.admin,self.file.pk,{})
    def test_missing_corrupt_original_stops_grants_and_read_but_allows_revoke(self):
        self.grant();df.path(self.file).unlink()
        self.assertRaises(ReviewConflict,share.preview,self.admin,self.file.pk,self.data(self.viewer))
        self.assertRaises(ReviewConflict,share.readable,self.quality,self.file.pk)
        self.assertFalse(share.context(self.admin,self.file.pk)['original_valid'])
        self.grant(action='revoke');self.assertRaises(DeviceFile.DoesNotExist,share.readable,self.quality,self.file.pk)
    def test_metadata_and_history_tampering_fail_closed(self):
        e=self.grant();FileReadGrant.objects.filter(pk=e.pk).update(payload_hash='0'*64)
        self.assertRaises(share.GrantConflict,share.readable,self.quality,self.file.pk)
        self.assertEqual(share.listing(self.quality)['rows'],[]);df.get(self.admin,self.file.pk)
        self.assertRaises(share.GrantConflict,share.context,self.admin,self.file.pk)
    def test_history_header_chain_and_missing_version_rejected(self):
        e=self.grant();p=copy.deepcopy(e.payload);p['recipient_id']=self.viewer.pk
        FileReadGrant.objects.filter(pk=e.pk).update(payload=p,payload_hash=share.digest(p))
        self.assertRaises(share.GrantConflict,share.readable,self.quality,self.file.pk)
    def test_global_file_chain_is_independent_of_recipient(self):
        a=self.grant();b=self.grant(self.viewer);c=self.grant(action='revoke')
        self.assertEqual(b.payload['previous_id'],a.pk);self.assertEqual(c.payload['previous_id'],b.pk)
        share.readable(self.viewer,self.file.pk);self.assertRaises(DeviceFile.DoesNotExist,share.readable,self.quality,self.file.pk)
    def test_history_is_immutable_and_version_unique(self):
        e=self.grant();self.assertRaises(ValidationError,e.save)
        with self.assertRaises(IntegrityError),transaction.atomic():
            FileReadGrant.objects.create(file=self.file,recipient=self.quality,actor=self.admin,version=1,action='grant',request_id=uuid.uuid4(),request_hash='x',payload={},payload_hash='x')
    def test_stale_preview_detects_other_grant_account_and_bytes_changes(self):
        p=self.payload();self.grant(self.viewer);self.assertRaises(ReviewConflict,share.commit,self.admin,self.file.pk,p)
        p=self.payload();self.quality.first_name='新身份';self.quality.save();AccountAccessState.objects.create(user=self.quality,revision=1)
        self.assertRaises(ReviewConflict,share.commit,self.admin,self.file.pk,p)
        p=self.payload();df.path(self.file).write_bytes(b'changed');self.assertRaises(ReviewConflict,share.commit,self.admin,self.file.pk,p)
    def test_preview_bound_to_file_recipient_action_reason_and_expiry(self):
        for key,value in [('recipient_id',self.viewer.pk),('action','revoke'),('reason','另外的模拟核对依据'),('expires_at',(timezone.now()+timedelta(days=1)).strftime('%Y-%m-%dT%H:%M:%SZ'))]:
            p=self.payload();p[key]=value
            with self.assertRaises((ReviewConflict,ValidationError)):share.commit(self.admin,self.file.pk,p)
    def test_retries_do_not_reactivate_revoked_permission(self):
        p=self.payload();a=share.commit(self.admin,self.file.pk,p);self.grant(action='revoke')
        before=FileReadGrant.objects.count();self.assertEqual(share.commit(self.admin,self.file.pk,p).pk,a.pk)
        self.assertEqual(FileReadGrant.objects.count(),before);self.assertRaises(DeviceFile.DoesNotExist,share.readable,self.quality,self.file.pk)
        p['reason']='修改原申请内容';self.assertRaises(ReviewConflict,share.commit,self.admin,self.file.pk,p)
    def test_audit_failure_rolls_back_permission(self):
        p=self.payload()
        with patch.object(AuditEvent.objects,'create',side_effect=RuntimeError('audit failure')):self.assertRaises(RuntimeError,share.commit,self.admin,self.file.pk,p)
        self.assertEqual(FileReadGrant.objects.count(),0);self.assertRaises(DeviceFile.DoesNotExist,share.readable,self.quality,self.file.pk)
    def test_invalid_fields_dates_and_unknown_recipient(self):
        for change in [dict(recipient_id=True),dict(recipient_id='2'),dict(action='approve'),dict(reason='短'),dict(expires_at=None),dict(expires_at='2026-99-01T00:00:00Z'),dict(expires_at='2026-12-01T00:00:00+00:00'),dict(expires_at='2020-01-01T00:00:00Z'),dict(extra='x')]:
            with self.assertRaises(ValidationError):share.preview(self.admin,self.file.pk,self.data()|change)
        self.assertRaises(User.DoesNotExist,share.preview,self.admin,self.file.pk,self.data()|dict(recipient_id=999999))
        self.assertRaises(ValidationError,share.preview,self.admin,self.file.pk,self.data(action='revoke'))
    def test_recipient_detail_reveals_no_other_grant_or_association_history(self):
        self.grant();self.grant(self.viewer);d=share.detail(self.viewer,self.file.pk)
        self.assertEqual(d['grant']['payload']['recipient_id'],self.viewer.pk);self.assertNotIn('history',d);self.assertNotIn('checks',d)
        self.assertEqual(len(share.listing(self.viewer)['rows']),1);self.assertEqual(len(share.context(self.admin,self.file.pk)['history']),2)
    def test_business_facts_bytes_and_metadata_unchanged(self):
        before=df.file_meta(self.file);bytes_before=df.contents(self.file);self.grant();self.grant(action='revoke')
        self.file.refresh_from_db();self.assertEqual(df.file_meta(self.file),before);self.assertEqual(df.contents(self.file),bytes_before);self.assertEqual(list(Record.objects.values()),self.before)
    def test_api_auth_methods_owner_and_csrf(self):
        c=Client(enforce_csrf_checks=True);self.assertEqual(c.get('/api/shared-originals').status_code,401)
        c.force_login(self.admin);self.assertEqual(self.post(self.api('/preview'),self.data(),c).status_code,403)
        self.assertEqual(self.client.get(self.api('/commit')).status_code,405);self.assertEqual(self.client.get(self.api()+'?x=a').status_code,400)
        self.client.force_login(self.quality);self.assertEqual(self.client.get(self.api()).status_code,404)
    def test_api_download_headers_audit_and_immediate_revoke(self):
        self.grant(self.viewer);self.client.force_login(self.viewer)
        r=self.client.get(self.read_api('/original'));self.assertEqual(r.status_code,200);self.assertEqual(r.content,b'synthetic original')
        for key,value in [('Cache-Control','no-store'),('X-Content-Type-Options','nosniff')]:self.assertEqual(r[key],value)
        self.assertIn('sandbox',r['Content-Security-Policy']);self.assertTrue(r['Content-Disposition'].startswith('attachment'))
        self.assertEqual(AuditEvent.objects.filter(action='file_read.download',actor=self.viewer.username).count(),1)
        self.grant(self.viewer,action='revoke');self.assertEqual(self.client.get(self.read_api('/original')).status_code,404)
    def test_api_commit_preview_and_recipient_directory(self):
        c=self.client.get(self.api()).json();self.assertTrue(c['original_valid']);self.assertNotIn('password',str(c));self.assertNotIn('session_epoch',str(c))
        p=self.post(self.api('/preview'),self.data(self.viewer)).json();payload=p['change']|dict(token=p['token'],request_id=str(uuid.uuid4()))
        r=self.post(self.api('/commit'),payload);self.assertEqual(r.status_code,200);self.assertEqual(self.post(self.api('/commit'),payload).json()['id'],r.json()['id'])
        self.client.force_login(self.viewer);self.assertEqual(self.client.get('/api/shared-originals').json()['rows'][0]['file']['id'],str(self.file.pk))
        self.assertEqual(self.client.get(self.read_api()).status_code,200)

class CertificateSharingTests(SharingCase):
    def setUp(self):
        super().setUp();self.d=fixture()
        self.file=df.upload(self.admin,SimpleUploadedFile('模拟材质证明.csv',raw(self.d)),uuid.uuid4(),'模拟证明，用于跨账号核对')
        self.d['material_certificates'][0].update(file_id=str(self.file.pk),file_sha256=self.file.file_hash)
        for ds,rows in self.d.items():
            for r in rows:self.record(ds,r)
        analytics._tables.cache_clear();self.addCleanup(analytics._tables.cache_clear)
    def board(self):return self.client.get('/api/material-certificates').json()
    def test_grant_and_revoke_change_access_state_not_iqc_or_facts(self):
        self.client.force_login(self.quality);before=list(Record.objects.values());old=self.board();self.assertEqual(old['summary']['no_access'],1)
        self.grant();d=self.board();self.assertEqual(d['summary']['consistent'],1);self.assertNotEqual(d['receipt'],old['receipt'])
        self.assertEqual(self.client.get('/api/material-certificates/rows/R1?receipt='+old['receipt']).status_code,409)
        self.assertEqual(self.client.get(self.read_api('/original')).status_code,200);self.assertEqual(self.client.get('/api/device-files/'+str(self.file.pk)+'/original').status_code,404)
        self.grant(action='revoke');self.assertEqual(self.board()['summary']['no_access'],1);self.assertEqual(list(Record.objects.values()),before)
    def test_regrant_same_bytes_invalidates_old_recipient_receipt(self):
        self.grant();self.client.force_login(self.quality);old=self.board()['receipt'];self.grant(action='revoke');self.grant()
        self.assertNotEqual(self.board()['receipt'],old);self.assertEqual(self.client.get('/api/material-certificates/export?receipt='+old).status_code,409)
    def test_damaged_grant_is_access_issue_not_material_content_failure(self):
        e=self.grant();FileReadGrant.objects.filter(pk=e.pk).update(payload_hash='f'*64);self.client.force_login(self.quality)
        d=self.board();self.assertEqual(d['summary']['no_access'],1);self.assertEqual(d['summary']['file_attention'],0);self.assertIsNone(next(r for r in d['rows'] if r['id']=='R1')['file'])
