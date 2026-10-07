import csv,io,json
from unittest.mock import patch
from django.contrib.auth.models import User,Group
from django.db import IntegrityError
from app.models import Record,AuditEvent,AccountAccessState
from app.ingestion import fingerprint
from .test_platform import PlatformCase
from .test_crew_schedule import fixture,declare

class CrewScheduleAPITests(PlatformCase):
 def setUp(self):
  super().setUp();study,tables,base,refs=fixture();declare(study,tables);self.record('crew_studies',study);self.record('schedule_studies',base['study'])
  for ds,rows in {**tables,**base['tables']}.items():
   for r in rows:self.record(ds,r)
  # All reference records must also remain exact sources for the resource loader.
  from .test_finite_schedule import fixture as rf
  original=rf()[2]
  for ds,rows in {**original,**refs}.items():
   for r in rows.values():self.record(ds,r)
  self.client.force_login(self.admin)
 def board(self):return self.client.get('/api/crew-schedule/CR1')
 def d(self):return self.board().json()
 def export(self,d=None,fmt='json',**extra):return self.client.get('/api/crew-schedule/CR1/export',dict(receipt=(d or self.d())['receipt'],format=fmt,**extra))
 def change(self,ds,key,**fields):
  r=Record.objects.get(dataset=ds,business_key=key);r.values.update(fields);r.record_hash=fingerprint(r.values);r.revision+=1;r.save();row=r.source_row;row.normalized=r.values;row.record_hash=r.record_hash;row.save()
 def test_auth_and_method(self):
  self.client.logout();self.assertEqual(self.board().status_code,401);self.client.force_login(self.admin);self.assertEqual(self.client.post('/api/crew-schedule/CR1').status_code,405)
 def test_three_allowed_three_denied_and_no_facts_changed(self):
  before=(Record.objects.count(),AuditEvent.objects.count())
  for role in ['admin','analyst','operations','quality','finance','viewer']:
   user=User.objects.filter(username=role).first() or User.objects.create_user(role);group,_=Group.objects.get_or_create(name=role);user.groups.add(group);self.client.force_login(user);allowed=role in ['admin','analyst','operations']
   self.assertEqual(self.board().status_code,200 if allowed else 403)
   self.assertEqual(self.client.get('/api/crew-schedule').status_code,200 if allowed else 403)
   self.assertEqual(self.client.get('/api/records/crew_credentials').status_code,200 if allowed else 403)
  self.assertEqual(before,(Record.objects.count(),AuditEvent.objects.count()))
 def test_unknown_repeated_and_bad_ranges(self):
  for q in ['?policy=due&policy=priority','?page=2','?filter=E1','?policy=nope']:self.assertEqual(self.client.get('/api/crew-schedule/CR1'+q).status_code,400)
 def test_expired_stale_role_and_other_account(self):
  self.assertEqual(self.client.get('/api/crew-schedule/CR1/export').status_code,400)
  with patch('django.core.signing.time.time',return_value=0):old=self.d()
  self.assertEqual(self.export(old).status_code,409);d=self.d();self.assertEqual(self.export(d,policy='priority').status_code,409)
  AccountAccessState.objects.create(user=self.admin,revision=2);self.assertEqual(self.export(d).status_code,409)
  d=self.d();user=User.objects.create_user('crew_analyst');user.groups.add(Group.objects.get_or_create(name='analyst')[0]);self.client.force_login(user);self.assertEqual(self.export(d).status_code,409)
 def test_skill_source_rules_and_metadata_invalidate(self):
  d=self.d();self.change('skills','S1',status='暂停');self.assertEqual(self.export(d).status_code,409);d=self.d()
  self.batch.filename='new.xlsx';self.batch.save();self.assertEqual(self.export(d).status_code,409);d=self.d()
  with patch('app.crew_schedule.rule_hash',return_value='changed'):self.assertEqual(self.export(d).status_code,409)
 def test_direct_evidence_both_calendars_credential_and_pred(self):
  d=self.d();r=self.client.get('/api/crew-schedule/CR1/tasks/TC1',dict(receipt=d['receipt']));self.assertEqual(r.status_code,200);keys={(s['dataset'],s['key']) for s in r.json()['sources']}
  for pair in [('crew_candidates','HTC1'),('crew_credentials','CS3'),('skills','S3'),('employees','E3'),('crew_windows','WE3'),('schedule_windows','WR3'),('schedule_tasks','TA')]:self.assertIn(pair,keys)
 def test_bad_pages_and_foreign_tasks(self):
  d=self.d()
  for page in ['0','1.2','１００','-1']:self.assertEqual(self.client.get('/api/crew-schedule/CR1/sources',dict(receipt=d['receipt'],page=page)).status_code,400)
  self.assertEqual(self.client.get('/api/crew-schedule/CR1/tasks/FOREIGN',dict(receipt=d['receipt'])).status_code,404)
 def test_full_json_all_assumptions_no_active_receipt_one_audit(self):
  r=self.export();self.assertEqual(r.status_code,200);d=r.json();self.assertEqual(len(d['result']['tasks']),4);self.assertEqual(len(d['resource_inputs']['schedule_tasks']),4);self.assertEqual(len(d['crew_inputs']['crew_candidates']),4);self.assertNotIn('receipt',d);self.assertEqual(r['Cache-Control'],'no-store');self.assertEqual(AuditEvent.objects.get(action='crew_schedule.export').detail['input_tasks'],4)
 def test_full_csv_and_formula_shaped_source_name(self):
  self.change('crew_studies','CR1',name='  =SIM()');r=self.export(fmt='csv');rows=list(csv.reader(io.StringIO(r.content.decode('utf-8-sig'))));self.assertIn("'  =SIM()",rows[0]);self.assertEqual(len(rows[6:-1]),4)
 def test_paused_csv_preserves_every_input_not_healthy_zero(self):
  self.record('crew_windows',dict(id='Bad',study_id='CR1',employee_id='E1',started='2026-10-02T09:00:00',finished='2026-10-02T10:00:00',basis='SIM'));d=self.d();self.assertEqual(d['state'],'paused');self.assertIsNone(d['summary']);doc=self.export(d).json();self.assertTrue(doc['result']['issues']);self.assertEqual(len(doc['resource_inputs']['schedule_tasks']),4)
  raw=self.export(d,'csv').content.decode('utf-8-sig');self.assertIn('排程、人员、完成和等待未计算',raw);rows=list(csv.reader(io.StringIO(raw)));self.assertEqual([r[0] for r in rows if r and r[0] in {'TA','TB','TC1','TC2'}],['TA','TB','TC1','TC2'])
 def test_atomic_audit_failure_and_invalid_export_no_file(self):
  before=(Record.objects.count(),AuditEvent.objects.count())
  with patch('app.crew_schedule_views.AuditEvent.objects.create',side_effect=IntegrityError('SIM')):self.assertEqual(self.export().status_code,409)
  self.assertEqual(self.export(fmt='xlsx').status_code,400);self.assertEqual(before,(Record.objects.count(),AuditEvent.objects.count()))
 def test_corrupt_source_rejected(self):
  r=Record.objects.get(dataset='skills',business_key='S1');r.values['status']='暂停';r.save();self.assertEqual(self.board().status_code,400)
