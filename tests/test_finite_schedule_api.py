import csv,io
from unittest.mock import patch
from django.contrib.auth.models import User,Group
from django.db import IntegrityError
from app.models import Record,AuditEvent,AccountAccessState
from app.ingestion import fingerprint
from .test_platform import PlatformCase
from .test_finite_schedule import fixture
class FiniteScheduleAPITests(PlatformCase):
 def setUp(self):
  super().setUp();s,tables,refs=fixture();self.record('schedule_studies',s)
  for ds,rows in tables.items():
   for r in rows:self.record(ds,r)
  for ds,rows in refs.items():
   for r in rows.values():self.record(ds,r)
  self.client.force_login(self.quality)
 def board(self,fields=None):return self.client.get('/api/finite-schedule/SP1',fields or {})
 def d(self):return self.board().json()
 def change(self,ds,key,**fields):
  r=Record.objects.get(dataset=ds,business_key=key);r.values.update(fields);r.record_hash=fingerprint(r.values);r.revision+=1;r.save();row=r.source_row;row.normalized=r.values;row.record_hash=r.record_hash;row.save()
 def export(self,d=None,fmt='json',**extra):return self.client.get('/api/finite-schedule/SP1/export',dict(receipt=(d or self.d())['receipt'],format=fmt,**extra))
 def test_auth_method_directory_and_trial(self):
  self.client.logout();self.assertEqual(self.board().status_code,401);self.client.force_login(self.quality);self.assertEqual(self.client.post('/api/finite-schedule/SP1').status_code,405);self.assertEqual(len(self.client.get('/api/finite-schedule').json()['rows']),1);self.assertEqual(self.d()['summary']['qty'],2)
 def test_six_roles_and_no_business_write(self):
  before=(Record.objects.count(),AuditEvent.objects.count(),AccountAccessState.objects.count())
  for role in ['admin','analyst','quality','operations','finance','viewer']:
   user=User.objects.filter(username=role).first() or User.objects.create_user(role);group,_=Group.objects.get_or_create(name=role);user.groups.add(group);self.client.force_login(user);d=self.d();self.assertEqual(d['summary']['tasks'],4);self.assertNotIn('price_cents',str(d));self.assertEqual(self.client.get('/api/finite-schedule/SP1/sources',dict(receipt=d['receipt'])).status_code,200)
  self.assertEqual(before,(Record.objects.count(),AuditEvent.objects.count(),AccountAccessState.objects.count()))
 def test_bad_and_repeated_or_unknown_range(self):
  for q in ['?policy=due&policy=priority','?filter=product','?page=2','?policy=unbounded']:
   self.assertEqual(self.client.get('/api/finite-schedule/SP1'+q).status_code,400)
 def test_receipt_required_invalid_expired_and_other_account(self):
  self.assertEqual(self.client.get('/api/finite-schedule/SP1/export').status_code,400);d=self.d();self.assertEqual(self.export({'receipt':d['receipt']+'bad'}).status_code,409)
  with patch('django.core.signing.time.time',return_value=0):expired=self.d()
  self.assertEqual(self.export(expired).status_code,409);self.client.force_login(self.admin);self.assertEqual(self.export(d).status_code,409)
 def test_strategy_source_and_rule_staleness(self):
  d=self.d();self.assertEqual(self.export(d,policy='priority').status_code,409);self.change('schedule_tasks','TA',unit_minutes=11);self.assertEqual(self.export(d).status_code,409);d=self.d()
  with patch('app.finite_schedule.rule_hash',return_value='changed'):self.assertEqual(self.export(d).status_code,409)
 def test_source_file_and_revision_changes_invalidate(self):
  d=self.d();self.batch.filename='new.xlsx';self.batch.save();self.assertEqual(self.export(d).status_code,409);d=self.d();AccountAccessState.objects.create(user=self.quality,revision=2);self.assertEqual(self.export(d).status_code,409)
 def test_point_sources_and_original_privilege(self):
  d=self.d();r=self.client.get('/api/finite-schedule/SP1/tasks/TC1',dict(receipt=d['receipt']));self.assertEqual(r.status_code,200);keys={(s['dataset'],s['key']) for s in r.json()['sources']}
  for pair in [('schedule_tasks','TC1'),('schedule_tasks','TA'),('schedule_options','OTC1'),('schedule_windows','WR3'),('production_resources','R3'),('route_dependencies','AC')]:self.assertIn(pair,keys)
  self.assertFalse(r.json()['can_download_original']);self.client.force_login(self.admin);d=self.d();self.assertTrue(self.client.get('/api/finite-schedule/SP1/sources',dict(receipt=d['receipt'])).json()['can_download_original'])
 def test_unknown_task_404_and_invalid_page(self):
  d=self.d();self.assertEqual(self.client.get('/api/finite-schedule/SP1/tasks/FOREIGN',dict(receipt=d['receipt'])).status_code,404)
  for page in ['0','1.2','１００','-1']:self.assertEqual(self.client.get('/api/finite-schedule/SP1/sources',dict(receipt=d['receipt'],page=page)).status_code,400)
 def test_complete_json_no_active_receipt_and_one_audit(self):
  r=self.export();self.assertEqual(r.status_code,200);d=r.json();self.assertEqual(len(d['result']['tasks']),4);self.assertNotIn('receipt',d);self.assertEqual(r['Cache-Control'],'no-store');self.assertEqual(AuditEvent.objects.get(action='finite_schedule.export').detail['tasks'],4)
 def test_full_csv_formula_shape_and_missing_zero(self):
  self.change('schedule_studies','SP1',name='  =SIM()');r=self.export(fmt='csv');rows=list(csv.reader(io.StringIO(r.content.decode('utf-8-sig'))));self.assertIn("'  =SIM()",rows[0]);self.assertEqual(len(rows[6:-1]),4);self.assertIn('0.0',rows[9])
 def test_failed_export_no_audit_and_unsupported_format(self):
  d=self.d();self.change('schedule_tasks','TA',unit_minutes=12);before=AuditEvent.objects.count();self.assertEqual(self.export(d).status_code,409);self.assertEqual(self.export(fmt='xlsx').status_code,400);self.assertEqual(before,AuditEvent.objects.count())
 def test_audit_failure_atomic_no_file_or_fact_changes(self):
  before=(Record.objects.count(),AuditEvent.objects.count())
  with patch('app.finite_schedule_views.AuditEvent.objects.create',side_effect=IntegrityError('simulated')):self.assertEqual(self.export().status_code,409)
  self.assertEqual(before,(Record.objects.count(),AuditEvent.objects.count()))
 def test_source_hash_corruption_rejected(self):
  r=Record.objects.get(dataset='schedule_tasks',business_key='TA');r.values['unit_minutes']=99;r.save();self.assertEqual(self.board().status_code,400)
 def test_paused_trial_export_preserves_reason_not_empty_success(self):
  self.record('schedule_windows',dict(id='Wbad',study_id='SP1',resource_id='R1',started='2026-10-02T09:00:00',finished='2026-10-02T10:00:00',basis='SIM'));d=self.d();self.assertEqual(d['state'],'paused');self.assertIsNone(d['summary']);doc=self.export(d).json();self.assertTrue(doc['result']['issues']);self.assertEqual(len(doc['inputs']['schedule_tasks']),4)
  raw=self.export(d,'csv').content.decode('utf-8-sig');self.assertIn('排程、完成、等待与负载未计算',raw);rows=list(csv.reader(io.StringIO(raw)));self.assertEqual([r[0] for r in rows if r and r[0] in {'TA','TB','TC1','TC2'}],['TA','TB','TC1','TC2'])
