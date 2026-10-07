import csv,io,json,os,tempfile,uuid
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch
from django.contrib.auth.models import Group,User
from django.core import signing
from django.core.exceptions import PermissionDenied,ValidationError
from django.test import Client
from django.utils import timezone
from app import device_collector as dc,device_files as files
from app.models import AuditEvent,DeviceCollectionRun,DeviceCollectionEvent,DeviceFile,DeviceFileReview,FileReadGrant,Record
from app.import_review import ReviewConflict
from tests.test_platform import PlatformCase

class DeviceCollectorTests(PlatformCase):
 def setUp(self):
  super().setUp();self.client.force_login(self.admin)
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)/'inbox';self.root.mkdir();self.leaf=self.root/'SRC-0001';self.leaf.mkdir();self.archive=Path(self.temp.name)/'archives'
  self.override=self.settings(DEVICE_COLLECTION_ENABLED=True,DEVICE_COLLECTION_ROOT=self.root,DEVICE_COLLECTION_SOURCES={'SRC-0001'},DEVICE_COLLECTION_STABLE_SECONDS=2,DEVICE_FILE_ROOT=self.archive);self.override.enable();self.addCleanup(self.override.disable)
  self.source=self.record('device_sources',dict(id='SRC-0001',equipment_id='SB-08-01',host_label='SIM-PC',directory='Z:\\NEVER-READ',format='csv',scan_interval_hours=24,registered='2026-09-20T08:00:00',owner_id='E00001',active=True,note='Excel模拟'))
  self.at=timezone.now();self.write('a.txt',b'local synthetic sample')
 def write(self,name,raw):
  p=self.leaf/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(raw);os.utime(p,(self.at.timestamp()-10,self.at.timestamp()-10));return p
 def sample(self,prior=None,at=None,user=None):
  with patch.object(dc.timezone,'now',return_value=at or self.at):return dc.sampling(user or self.admin,dict(source_id='SRC-0001',prior_receipt=prior))
 def stable(self,user=None):
  first=self.sample(user=user);return self.sample(first['receipt'],self.at+timedelta(seconds=3),user)
 def new(self,selected=None,user=None):
  s=self.stable(user);body=dict(source_id='SRC-0001',request_id=str(uuid.uuid4()),receipt=s['receipt'],keys=selected or [r['key'] for r in s['items'] if r['eligible']])
  with patch.object(dc.timezone,'now',return_value=self.at+timedelta(seconds=3)):return dc.create(user or self.admin,body),body
 def take(self,d,body=None,user=None):return dc.collect(user or self.admin,d['id'],body or dict(request_id=str(uuid.uuid4()),versions={r['item']['key']:r['version'] for r in d['rows']}))
 def test_two_observations_actual_hash_and_no_writes(self):
  first=self.sample();self.assertFalse(first['items'][0]['eligible']);second=self.sample(first['receipt'],self.at+timedelta(seconds=3));self.assertTrue(second['items'][0]['eligible']);self.assertEqual(second['items'][0]['sha256'],files.hashlib.sha256((self.leaf/'a.txt').read_bytes()).hexdigest());self.assertFalse(DeviceCollectionRun.objects.exists());self.assertFalse(AuditEvent.objects.exists())
 def test_too_soon_not_stable(self):self.assertFalse(self.sample(self.sample()['receipt'],self.at+timedelta(seconds=1))['items'][0]['eligible'])
 def test_same_size_content_and_preserved_mtime_not_stable(self):
  first=self.sample();p=self.leaf/'a.txt';st=p.stat();p.write_bytes(b'x'*st.st_size);os.utime(p,ns=(st.st_atime_ns,st.st_mtime_ns));self.assertFalse(self.sample(first['receipt'],self.at+timedelta(seconds=3))['items'][0]['eligible'])
 def test_future_modified_time_not_stable(self):
  p=self.leaf/'a.txt';os.utime(p,(self.at.timestamp()+10,self.at.timestamp()+10));self.assertFalse(self.stable()['items'][0]['eligible'])
 def test_role_and_current_disabled_checked(self):
  other=User.objects.create_user('viewer');other.groups.add(Group.objects.create(name='viewer'))
  with self.assertRaises(PermissionDenied):dc.board(other)
  self.admin.is_active=False;self.admin.save()
  with self.assertRaises(PermissionDenied):dc.board(self.admin)
 def test_unconfigured_source_denied(self):
  with self.assertRaises(PermissionDenied):dc.sampling(self.admin,dict(source_id='UNKNOWN',prior_receipt=None))
 def test_disabled_configuration_denied(self):
  with self.settings(DEVICE_COLLECTION_ENABLED=False),self.assertRaises(PermissionDenied):self.sample()
 def test_unknown_api_query_and_csrf(self):
  self.assertEqual(self.client.get('/api/device-collection?extra=x').status_code,400);self.assertEqual(self.client.get('/api/device-collection?x=1&x=2').status_code,400)
  c=Client(enforce_csrf_checks=True);c.force_login(self.admin);self.assertEqual(c.post('/api/device-collection/preview','{}',content_type='application/json').status_code,403)
 def test_path_traversal_rejected(self):
  for p in ['../x','/x','C:\\x','a/../../x','a\\b']:
   with self.subTest(p=p),self.assertRaises(ValidationError):dc.read(self.root,'SRC-0001',p)
 def test_file_and_directory_symlinks_blocked(self):
  outside=Path(self.temp.name)/'outside';outside.mkdir();(outside/'secret.txt').write_bytes(b'not collected');(self.leaf/'outside').symlink_to(outside,target_is_directory=True);(self.leaf/'link.txt').symlink_to(outside/'secret.txt')
  d=self.stable();self.assertEqual([r['state'] for r in d['items'] if r['path']!='a.txt'],['blocked','blocked'])
  with self.assertRaises(OSError):dc.read(self.root,'SRC-0001','outside/secret.txt')
 def test_root_symlink_rejected(self):
  link=Path(self.temp.name)/'linked';link.symlink_to(self.root,target_is_directory=True)
  with self.settings(DEVICE_COLLECTION_ROOT=link),self.assertRaises(ValidationError):self.sample()
 def test_source_symlink_rejected(self):
  other=self.root/'OTHER';other.mkdir();self.leaf.rename(self.root/'saved');self.leaf.symlink_to(other,target_is_directory=True)
  with self.assertRaises(ValidationError):self.sample()
 def test_fifo_not_read(self):
  os.mkfifo(self.leaf/'pipe.txt');self.assertEqual(next(r for r in self.sample()['items'] if r['path']=='pipe.txt')['state'],'blocked')
 def test_hidden_temporary_unsupported_empty_and_oversize(self):
  for p in ['.hidden.txt','file.csv.part','a.exe']:self.write(p,b'x')
  self.write('empty.txt',b'');p=self.leaf/'large.csv'
  with p.open('wb') as f:f.truncate(files.MAX_BYTES+1)
  states={r['path']:r['state'] for r in self.sample()['items']};self.assertEqual([states[k] for k in ['.hidden.txt','file.csv.part','a.exe','empty.txt','large.csv']],['skipped','skipped','skipped','empty','too_big'])
 def test_depth_limit_fails_whole_observation(self):
  self.write('1/2/3/4/5/6/deep.txt',b'x')
  with self.assertRaises(ValidationError):self.sample()
 def test_file_count_limit_fails_whole_observation(self):
  for n in range(100):self.write(str(n)+'.txt',b'x')
  with self.assertRaises(ValidationError):self.sample()
 def test_read_budget_discloses_skipped_files(self):
  for n in range(6):self.write(f'b{n}.txt',b'x'*(8*1024*1024))
  d=self.sample();self.assertLessEqual(d['read_bytes'],40*1024*1024);self.assertIn('budget',d['summary'])
 def test_changed_during_read_not_eligible(self):
  with patch.object(dc,'read',side_effect=ReviewConflict('changed')):self.assertEqual(self.sample()['items'][0]['state'],'read_failed')
 def test_receipt_tamper_expiry_and_malformed(self):
  s=self.sample()
  for token in [s['receipt']+'x',signing.dumps(dict(revision=dc.REVISION,sampled_at='x',items=[]),salt=dc.SALT)]:
   with self.assertRaises(ReviewConflict):self.sample(token)
  with patch.object(dc.signing,'loads',side_effect=signing.SignatureExpired('old')),self.assertRaises(ReviewConflict):self.sample(s['receipt'])
 def test_other_account_receipt_rejected(self):
  with self.assertRaises(ReviewConflict):self.sample(self.sample()['receipt'],self.at+timedelta(seconds=3),self.quality)
 def test_source_values_change_invalidates_observation(self):
  s=self.sample();self.source.values={**self.source.values,'note':'changed'};self.source.save()
  with self.assertRaises(ReviewConflict):self.sample(s['receipt'],self.at+timedelta(seconds=3))
 def test_first_sample_not_selectable(self):
  s=self.sample()
  with self.assertRaises(ValidationError):dc.create(self.admin,dict(source_id='SRC-0001',request_id=str(uuid.uuid4()),receipt=s['receipt'],keys=[s['items'][0]['key']]))
 def test_duplicate_or_unknown_selection_rejected(self):
  s=self.stable();k=s['items'][0]['key']
  for keys in [[k,k],['unknown'],[]]:
   with patch.object(dc.timezone,'now',return_value=self.at+timedelta(seconds=3)),self.assertRaises(ValidationError):dc.create(self.admin,dict(source_id='SRC-0001',request_id=str(uuid.uuid4()),receipt=s['receipt'],keys=keys))
 def test_new_run_idempotent_and_request_conflict(self):
  d,b=self.new();self.assertEqual(dc.create(self.admin,b)['id'],d['id']);self.assertEqual(DeviceCollectionRun.objects.count(),1)
  with self.assertRaises(ReviewConflict):dc.create(self.admin,{**b,'source_id':'OTHER'})
 def test_file_changed_before_freeze_no_run(self):
  s=self.stable();self.write('a.txt',b'new value')
  with self.assertRaises(ReviewConflict):dc.create(self.admin,dict(source_id='SRC-0001',request_id=str(uuid.uuid4()),receipt=s['receipt'],keys=[s['items'][0]['key']]))
  self.assertFalse(DeviceCollectionRun.objects.exists())
 def test_run_private_and_manifest_tamper_blocked(self):
  d,_=self.new()
  with self.assertRaises(DeviceCollectionRun.DoesNotExist):dc.detail(self.quality,d['id'])
  DeviceCollectionRun.objects.filter(pk=d['id']).update(manifest_hash='x')
  with self.assertRaises(ReviewConflict):dc.detail(self.admin,d['id'])
  with self.assertRaises(ReviewConflict):dc.board(self.admin)
 def test_duplicate_contents_reuse_one_private_original(self):
  self.write('copy.txt',(self.leaf/'a.txt').read_bytes());d,_=self.new();result=self.take(d);self.assertEqual(result['summary'],{'archived':1,'reused':1});self.assertEqual(DeviceFile.objects.count(),1);self.assertEqual(len(result['history']),2);self.assertFalse(DeviceFileReview.objects.exists());self.assertFalse(FileReadGrant.objects.exists());self.assertEqual(Record.objects.count(),1)
 def test_archive_bytes_exact(self):
  d,_=self.new();r=self.take(d)['rows'][0];self.assertEqual(files.contents(DeviceFile.objects.get(pk=r['archive']['id'])),(self.leaf/'a.txt').read_bytes());self.assertEqual(r['archive']['current_integrity'],'ok')
 def test_collect_request_replay_no_duplicate_events(self):
  d,_=self.new();b=dict(request_id=str(uuid.uuid4()),versions={d['rows'][0]['item']['key']:0});first=self.take(d,b);self.assertEqual(self.take(d,b)['receipt'],first['receipt']);self.assertEqual(DeviceCollectionEvent.objects.count(),1)
  with self.assertRaises(ReviewConflict):self.take(d,{**b,'versions':{d['rows'][0]['item']['key']:1}})
 def test_failed_archive_retry_and_stale_version(self):
  d,_=self.new()
  with patch.object(files,'upload',side_effect=ValidationError('capacity')):fail=self.take(d)
  self.assertEqual(fail['summary'],{'archive_failed':1})
  with self.assertRaises(ReviewConflict):self.take(d)
  ok=self.take(fail);self.assertEqual(ok['summary'],{'archived':1});self.assertEqual([r['version'] for r in ok['history']],[1,2])
 def test_interrupt_after_archive_retry_recovers_one_original(self):
  d,_=self.new();b=dict(request_id=str(uuid.uuid4()),versions={d['rows'][0]['item']['key']:0})
  with patch.object(DeviceCollectionEvent.objects,'create',side_effect=RuntimeError('interrupted')),self.assertRaises(RuntimeError):self.take(d,b)
  self.assertEqual(DeviceFile.objects.count(),1);self.assertEqual(DeviceCollectionEvent.objects.count(),0);self.assertEqual(self.take(d,b)['summary'],{'reused':1});self.assertEqual(DeviceFile.objects.count(),1)
 def test_success_cannot_recollect_new_request(self):
  d,_=self.new();r=self.take(d)
  with self.assertRaises(ValidationError):self.take(r)
 def test_source_stopped_after_freeze_has_source_changed_receipt(self):
  d,_=self.new();self.source.values={**self.source.values,'active':False};self.source.save();self.assertEqual(self.take(d)['summary'],{'source_changed':1});self.assertFalse(DeviceFile.objects.exists())
 def test_file_changed_after_freeze_no_archive(self):
  d,_=self.new();self.write('a.txt',b'changed');self.assertEqual(self.take(d)['summary'],{'source_changed':1});self.assertFalse(DeviceFile.objects.exists())
 def test_missing_file_receipt_and_retry(self):
  d,_=self.new();p=self.leaf/'a.txt';moved=self.leaf/'holding';p.rename(moved);fail=self.take(d);self.assertEqual(fail['summary'],{'read_failed':1});moved.rename(p)
  # Moving a file changes ctime; a fresh observation is required even if bytes agree.
  self.assertEqual(self.take(fail)['summary'],{'source_changed':1})
 def test_event_payload_tamper_rejected(self):
  d,_=self.new();self.take(d);DeviceCollectionEvent.objects.update(payload_hash='x')
  with self.assertRaises(ReviewConflict):dc.detail(self.admin,d['id'])
 def test_event_sequence_gap_rejected_even_hash_updated(self):
  d,_=self.new();self.take(d);e=DeviceCollectionEvent.objects.get();p={**e.payload,'version':2};DeviceCollectionEvent.objects.filter(pk=e.pk).update(version=2,payload=p,payload_hash=dc.digest(p))
  with self.assertRaises(ReviewConflict):dc.detail(self.admin,d['id'])
 def test_append_only_models(self):
  d,_=self.new();self.take(d)
  for obj in [DeviceCollectionRun.objects.get(),DeviceCollectionEvent.objects.get()]:
   with self.assertRaises(ValidationError):obj.save()
 def test_current_corrupt_archive_separate_from_historical_success(self):
  d,_=self.new();done=self.take(d);f=DeviceFile.objects.get();files.path(f).write_bytes(b'corrupt');current=dc.detail(self.admin,d['id']);self.assertEqual(current['rows'][0]['state'],'archived');self.assertEqual(current['rows'][0]['archive']['current_integrity'],'failed');self.assertNotEqual(done['receipt'],current['receipt']);self.assertEqual(done['history'],current['history'])
 def test_invalid_csv_archived_without_association(self):
  self.write('bad.csv',b'session_id,unit_id,measurement_id\nS,U,M\n');d,_=self.new();r=self.take(d);self.assertEqual(r['summary']['archived_invalid'],1);self.assertFalse(DeviceFileReview.objects.exists())
 def test_csv_export_same_scope_receipt_and_formula_escape(self):
  self.write('=SUM(1).txt',b'formula filename');d,_=self.new();r=self.take(d);url=f'/api/device-collection/runs/{d["id"]}/export';self.assertEqual(self.client.get(url,{'receipt':'stale'}).status_code,400);response=self.client.get(url,{'receipt':r['receipt']});self.assertEqual(response.status_code,200);rows=list(csv.reader(io.StringIO(response.content.decode('utf-8-sig'))));self.assertEqual(len(rows)-4,len(r['rows']));self.assertTrue(any(row[0]=="'=SUM(1).txt" for row in rows[4:]));self.assertEqual(AuditEvent.objects.filter(action='device_collection.export').count(),1)
 def test_api_private_and_bad_parameter_status(self):
  d,_=self.new();self.client.force_login(self.quality);self.assertEqual(self.client.get(f'/api/device-collection/runs/{d["id"]}').status_code,404);self.client.force_login(self.admin);self.assertEqual(self.post('/api/device-collection/preview',dict(source_id='SRC-0001',prior_receipt=None,path='/secret')).status_code,400);self.assertEqual(self.client.get('/api/device-collection').headers['Cache-Control'],'no-store')
