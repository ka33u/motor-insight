import csv,hashlib,io,json,tempfile,uuid
from pathlib import Path
from unittest.mock import patch
from django.contrib.auth.models import User,Group
from django.core.exceptions import ValidationError,PermissionDenied
from django.core.files.uploadedfile import SimpleUploadedFile
from app import device_intake as di,access,device_files as files
from app.models import Record,AuditEvent,DeviceFileReview
from tests.test_platform import PlatformCase

class DeviceIntakeTests(PlatformCase):
 def setUp(self):
  super().setUp();self.client.force_login(self.admin)
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.override=self.settings(DEVICE_FILE_ROOT=Path(self.temp.name));self.override.enable();self.addCleanup(self.override.disable)
  self.source=dict(id='SRC-0001',equipment_id='SB-08-01',host_label='SIM-PC',directory='D:\\Sim\\Export',format='csv',scan_interval_hours=24,registered='2026-09-20T08:00:00',owner_id='E00001',active=True,note='模拟目录')
  self.run=dict(id='SCAN-0001',source_id='SRC-0001',started='2026-10-01T09:00:00',finished='2026-10-01T09:20:00',status='完成',reported_count=1,operator_id='E00001',note='模拟扫描')
  self.observation=dict(id='OBS-0001',scan_id='SCAN-0001',relative_path='20261001\\a.csv',filename='a.csv',size_bytes=10,sha256='a'*64,modified='2026-10-01T08:55:00',discovered='2026-10-01T09:10:00',read_state='可读',format='csv',session_hint=None,unit_hint=None,note='模拟发现')
 def corpus(self,source=None,run=None,observation=None):
  self.record('device_sources',{**self.source,**(source or {})})
  if run is not False:self.record('device_scan_runs',{**self.run,**(run or {})})
  if observation is not False:self.record('device_file_observations',{**self.observation,**(observation or {})})
 def update(self,ds,key,**changes):
  r=Record.objects.get(dataset=ds,business_key=key);r.values={**r.values,**changes};r.record_hash=di.digest(r.values);r.revision+=1;r.save();return r
 def workspace(self,**conf):return di.Workspace(self.admin,conf)
 def export(self,d):return self.client.get('/api/device-intake/export',{**d.filters,'receipt':d.receipt})
 def archive(self,raw=b'synthetic report',kind='txt',owner=None):
  return files.upload(owner or self.admin,SimpleUploadedFile('report.'+kind,raw),str(uuid.uuid4()),'合成原件供测试')
 def test_absent_scan_is_unknown_not_empty(self):
  self.corpus(run=False,observation=False);d=self.workspace().board();self.assertEqual(d['sources'][0]['state'],'not_scanned');self.assertIsNone(d['sources'][0]['visible_count']);self.assertEqual(d['total'],0)
 def test_complete_empty_scan_is_explicit(self):
  self.corpus(run={'reported_count':0},observation=False);self.assertEqual(self.workspace().board()['sources'][0]['state'],'empty')
 def test_failure_is_not_healthy_empty(self):
  self.corpus(run={'status':'失败','reported_count':0,'finished':None},observation=False);self.assertEqual(self.workspace().board()['sources'][0]['state'],'failed')
 def test_not_executed_is_separate(self):
  self.corpus(run={'status':'未执行','reported_count':None,'finished':None},observation=False);self.assertEqual(self.workspace().board()['sources'][0]['state'],'not_executed')
 def test_partial_uses_visible_rows_without_completeness_claim(self):
  self.corpus(run={'status':'部分完成','reported_count':4,'finished':None});d=self.workspace().board();self.assertEqual(d['total'],1);self.assertEqual(d['sources'][0]['state'],'partial')
 def test_declared_count_mismatch_is_invalid(self):
  self.corpus(run={'reported_count':2});d=self.workspace().board();self.assertEqual(d['sources'][0]['state'],'invalid');self.assertEqual(d['rows'][0]['state'],'declaration_invalid')
 def test_missing_scan_count_is_not_assumed_zero(self):
  self.corpus(run={'reported_count':None});self.assertEqual(self.workspace().board()['sources'][0]['state'],'invalid')
 def test_invalid_scan_end_is_exposed(self):
  self.corpus(run={'finished':'2026-10-01T08:00:00'});self.assertEqual(self.workspace().board()['sources'][0]['state'],'invalid')
 def test_scan_not_yet_finished_is_partial_at_cutoff(self):
  self.corpus(run={'finished':'2026-10-02T09:00:00'});self.assertEqual(self.workspace().board()['sources'][0]['state'],'partial')
 def test_future_scans_do_not_replace_past_at_cutoff(self):
  self.corpus();self.record('device_scan_runs',{**self.run,'id':'SCAN-FUTURE','started':'2026-10-02T09:00:00','finished':'2026-10-02T09:20:00','reported_count':0});self.assertEqual(self.workspace().board()['sources'][0]['latest_scan'],'SCAN-0001')
 def test_future_observations_are_not_backdated(self):
  self.corpus(observation={'discovered':'2026-10-02T09:10:00'});d=self.workspace().board();self.assertEqual(d['total'],0);self.assertEqual(d['sources'][0]['state'],'invalid')
 def test_history_is_not_mixed_into_current(self):
  self.corpus();self.record('device_scan_runs',{**self.run,'id':'SCAN-OLD','started':'2026-09-30T09:00:00','finished':'2026-09-30T09:20:00'});self.record('device_file_observations',{**self.observation,'id':'OBS-OLD','scan_id':'SCAN-OLD','discovered':'2026-09-30T09:10:00','modified':'2026-09-30T08:55:00'});self.assertEqual(self.workspace().board()['total'],1);self.assertEqual(self.workspace(mode='all').board()['total'],2)
 def test_same_latest_time_is_ambiguous_not_silently_chosen(self):
  self.corpus();self.record('device_scan_runs',{**self.run,'id':'SCAN-TIE','reported_count':0});d=self.workspace().board();self.assertEqual(d['sources'][0]['state'],'invalid');self.assertEqual(d['rows'][0]['state'],'declaration_invalid');self.assertEqual(self.workspace(source='SRC-0001',scan='SCAN-0001').board()['rows'][0]['state'],'uncollected')
 def test_unknown_source_and_scan_mismatch_are_rejected(self):
  self.corpus()
  for conf in [{'source':'unknown'},{'scan':'SCAN-0001'},{'source':'SRC-0001','scan':'unknown'}]:
   with self.subTest(conf=conf),self.assertRaises(ValidationError):self.workspace(**conf)
 def test_missing_and_invalid_fingerprints_do_not_deduplicate(self):
  self.corpus(observation={'sha256':None});self.record('device_file_observations',{**self.observation,'id':'OBS-2','sha256':'not-sha256'});self.update('device_scan_runs','SCAN-0001',reported_count=2);s=self.workspace().board()['summary'];self.assertEqual(s['unknown_fingerprints'],2);self.assertEqual(s['known_contents'],0);self.assertEqual(s['duplicate_observations'],0)
 def test_known_content_deduplication_preserves_observation_rows(self):
  self.corpus();self.record('device_file_observations',{**self.observation,'id':'OBS-2','filename':'copy.csv','relative_path':'copy.csv'});self.update('device_scan_runs','SCAN-0001',reported_count=2);s=self.workspace().board()['summary'];self.assertEqual((s['observations'],s['known_contents'],s['duplicate_observations'],s['known_content_bytes']),(2,1,1,10))
 def test_sha_is_case_normalized(self):
  self.assertEqual(di.fingerprint({'sha256':'A'*64,'size_bytes':0}),('a'*64,0))
 def test_zero_bytes_valid_and_negative_bytes_unknown(self):
  self.assertEqual(di.fingerprint({'sha256':'a'*64,'size_bytes':0}),('a'*64,0));self.assertIsNone(di.fingerprint({'sha256':'a'*64,'size_bytes':-1}));self.assertIsNone(di.fingerprint({'sha256':'a'*64,'size_bytes':True}))
 def test_read_problem_is_not_uncollected(self):
  self.corpus()
  for state in ('正在写入','无权限','损坏','待核查'):
   self.update('device_file_observations','OBS-0001',read_state=state)
   with self.subTest(state=state):self.assertEqual(self.workspace().board()['rows'][0]['state'],'read_blocked')
 def test_disabled_account_cannot_read_with_cached_user_object(self):
  self.corpus();User.objects.filter(pk=self.admin.pk).update(is_active=False)
  with self.assertRaises(PermissionDenied):self.workspace()
 def test_unknown_read_state_is_declaration_problem(self):
  self.corpus(observation={'read_state':'???'});self.assertEqual(self.workspace().board()['rows'][0]['state'],'declaration_invalid')
 def test_paths_are_declarations_and_are_never_opened(self):
  self.corpus(source={'directory':'\\\\NOT-A-REAL-PC\\SHARE'})
  with patch('pathlib.Path.read_bytes',side_effect=AssertionError('No declared source may be opened')):self.assertEqual(self.workspace().board()['total'],1)
 def test_escaping_or_absolute_relative_paths_are_invalid(self):
  self.corpus()
  for path in ('../a.csv','C:\\a.csv','C:a.csv','/etc/a.csv','\\\\pc\\share\\a.csv'):
   self.update('device_file_observations','OBS-0001',relative_path=path)
   with self.subTest(path=path):self.assertEqual(self.workspace().board()['rows'][0]['state'],'declaration_invalid')
 def test_extension_mismatch_is_not_auto_converted(self):
  self.corpus(observation={'format':'pdf'});self.assertEqual(self.workspace().board()['rows'][0]['state'],'declaration_invalid')
 def test_modified_after_discovery_is_exposed(self):
  self.corpus(observation={'modified':'2026-10-01T09:15:00'});self.assertEqual(self.workspace().board()['rows'][0]['state'],'declaration_invalid')
 def test_staleness_boundary_and_unknown_policy(self):
  self.corpus();self.assertFalse(self.workspace(as_of='2026-10-02T09:00:00').board()['sources'][0]['stale']);self.assertTrue(self.workspace(as_of='2026-10-02T09:00:01').board()['sources'][0]['stale']);self.update('device_sources','SRC-0001',scan_interval_hours=0);self.assertIsNone(self.workspace().board()['sources'][0]['stale'])
 def test_disabled_source_remains_visible_for_audit(self):
  self.corpus(source={'active':False});self.assertFalse(self.workspace().board()['sources'][0]['active'])
 def test_roles_and_raw_data_endpoints_enforce_new_scope(self):
  self.corpus()
  for role in ('analyst','operations','finance','viewer'):
   u=User.objects.create_user(role);g,_=Group.objects.get_or_create(name=role);u.groups.add(g);self.client.force_login(u)
   self.assertEqual(self.client.get('/api/device-intake').status_code,403)
   for ds in di.DATASETS:self.assertFalse(access.allowed(u,ds));self.assertEqual(self.client.get('/api/records/'+ds).status_code,403)
 def test_quality_and_admin_can_read_empty_and_populated(self):
  self.corpus()
  for user in (self.admin,self.quality):self.assertEqual(di.Workspace(user).board()['total'],1)
 def test_other_owner_archive_existence_is_not_disclosed(self):
  raw=b'synthetic private evidence';f=self.archive(raw,owner=self.quality);self.corpus(observation={'sha256':f.file_hash,'size_bytes':len(raw),'format':'txt','filename':'report.txt','relative_path':'report.txt'});r=self.workspace().board()['rows'][0];self.assertEqual(r['archives'],[]);self.assertEqual(r['state'],'uncollected');q=di.Workspace(self.quality).board()['rows'][0];self.assertEqual(q['state'],'archived_manual')
 def test_same_filename_with_different_content_does_not_match(self):
  self.archive();self.corpus(observation={'filename':'report.txt','relative_path':'report.txt','format':'txt'});self.assertEqual(self.workspace().board()['rows'][0]['archives'],[])
 def test_same_sha_wrong_size_does_not_match(self):
  f=self.archive();self.corpus(observation={'sha256':f.file_hash,'size_bytes':f.size+1});self.assertEqual(self.workspace().board()['rows'][0]['archives'],[])
 def test_tampered_original_is_exposed_and_receipt_changes(self):
  f=self.archive();self.corpus(observation={'sha256':f.file_hash,'size_bytes':f.size,'filename':'report.txt','relative_path':'report.txt','format':'txt'});d=self.workspace();files.path(f).write_bytes(b'changed');fresh=self.workspace();self.assertEqual(fresh.rows[0]['state'],'archive_invalid');self.assertNotEqual(d.receipt,fresh.receipt)
 def test_source_change_invalidates_receipt(self):
  self.corpus();d=self.workspace();self.update('device_file_observations','OBS-0001',note='后来登记')
  with self.assertRaises(ValidationError):self.workspace().check(d.receipt)
 def test_role_change_invalidates_cached_permission(self):
  self.corpus();d=self.workspace();self.admin.groups.clear();self.admin.groups.add(Group.objects.create(name='viewer'))
  with self.assertRaises(PermissionDenied):self.workspace().check(d.receipt)
 def test_detail_requires_scope_and_current_receipt(self):
  self.corpus();d=self.workspace();self.assertEqual(self.client.get('/api/device-intake/rows/OBS-0001',{**d.filters,'receipt':d.receipt}).status_code,200);self.assertEqual(self.client.get('/api/device-intake/rows/OBS-0001',{'receipt':'stale'}).status_code,400)
  with self.assertRaises(ValidationError):self.workspace(q='not-here').detail('OBS-0001')
 def test_all_page_and_csv_records_match(self):
  self.corpus()
  for n in range(2,63):self.record('device_file_observations',{**self.observation,'id':f'OBS-{n:04}','filename':f'f{n}.csv','relative_path':f'f{n}.csv','sha256':hashlib.sha256(str(n).encode()).hexdigest()})
  self.update('device_scan_runs','SCAN-0001',reported_count=62);d=self.workspace();keys=[]
  for page in (1,2,3):keys.extend(r['key'] for r in d.board(page)['rows'])
  r=self.export(d);self.assertEqual(r.status_code,200);rows=list(csv.reader(io.StringIO(r.content.decode('utf-8-sig'))));self.assertEqual(keys,[r[0] for r in rows[4:]]);self.assertEqual(len(set(keys)),62)
 def test_csv_formula_injection_is_escaped(self):
  self.corpus(observation={'filename':' +cmd.csv','relative_path':' +cmd.csv','unit_hint':'=SUM(1,2)'});r=self.export(self.workspace());rows=list(csv.reader(io.StringIO(r.content.decode('utf-8-sig'))));self.assertTrue(rows[4][5].startswith("'"));self.assertTrue(rows[4][15].startswith("'"))
 def test_unsupported_or_duplicate_parameters_are_rejected(self):
  for query in ('source=x&source=y','secret=x','mode=bad','page=0','page=1.5','as_of=2026-10-01T18:00:00Z'):
   self.assertEqual(self.client.get('/api/device-intake?'+query).status_code,400)
 def test_read_only_board_and_detail_never_add_review_or_fact(self):
  self.corpus();before=Record.objects.count();audits=AuditEvent.objects.count();reviews=DeviceFileReview.objects.count();d=self.workspace();d.board();d.detail('OBS-0001');self.assertEqual((Record.objects.count(),AuditEvent.objects.count(),DeviceFileReview.objects.count()),(before,audits,reviews))
 def test_only_export_adds_non_business_audit(self):
  self.corpus();self.export(self.workspace());a=AuditEvent.objects.get(action='device_intake.export');self.assertFalse(a.detail['business_facts_changed']);self.assertFalse(a.detail['live_collection'])
