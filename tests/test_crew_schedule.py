from copy import deepcopy
from django.test import SimpleTestCase
from app import crew_schedule as engine,finite_schedule
from .test_finite_schedule import fixture as resource_fixture

def fixture():
 s,rt,refs=resource_fixture()
 refs['employees']={k:dict(id=k,name=k,active=True) for k in ['E1','E2','E3']}
 refs['skills']={r:dict(id=r,employee_id=e,process=p,approved='2026-01-01',expires='2027-01-01',status='有效') for r,e,p in [('S1','E1','冲片'),('S2','E2','转子铸铝'),('S3','E3','装配')]}
 study=dict(id='CR1',name='联立模拟',resource_study_id='SP1',version='V1',owner_id='E1',assumptions='一人全过程',reference='SIM')
 tables=dict(crew_credentials=[dict(id='C'+r,study_id='CR1',skill_id=r,valid_from=s['baseline'],valid_until=s['horizon_end'],basis='SIM') for r in refs['skills']],crew_candidates=[dict(id='H'+t['id'],study_id='CR1',task_id=t['id'],credential_id={'A':'CS1','B':'CS2','C':'CS3'}[t['route_id']],basis='SIM') for t in rt['schedule_tasks']],crew_windows=[dict(id='W'+e,study_id='CR1',employee_id=e,started=s['baseline'],finished=s['horizon_end'],basis='SIM') for e in refs['employees']],crew_blocks=[])
 return study,tables,dict(result=finite_schedule.analyze(s,rt,refs),tables=rt,study=s),refs

def declare(study,tables):
 for key,ds in [('credential_count','crew_credentials'),('candidate_count','crew_candidates'),('window_count','crew_windows'),('block_count','crew_blocks')]:study[key]=len(tables[ds])

class CrewScheduleTests(SimpleTestCase):
 def setUp(self):self.args=list(fixture())
 def result(self):declare(*self.args[:2]);return engine.analyze(*self.args)
 def test_hand_oracle_without_staff_constraint_matches_resource(self):
  r=self.result();self.assertEqual(r['summary']['scheduled_tasks'],4)
  self.assertEqual(r['jobs'][0]['finished'],'2026-10-02T08:55:00')
  self.assertEqual(r['jobs'][0]['completion_delta_minutes'],0)
  self.assertEqual(r['summary']['qty'],2);self.assertEqual(r['summary']['staff_delayed_tasks'],0)
 def test_shared_person_across_processes_has_one_capacity(self):
  self.args[3]['skills']['S2']['employee_id']='E1';r=self.result();rows={t['id']:t for t in r['tasks']}
  self.assertEqual(rows['TA']['finished'],'2026-10-02T08:25:00')
  self.assertEqual(rows['TB']['started'],'2026-10-02T08:25:00')
  self.assertEqual(rows['TB']['staff_additional_wait_minutes'],25)
  self.assertEqual(rows['TC1']['started'],'2026-10-02T08:50:00')
  self.assertEqual(r['jobs'][0]['finished'],'2026-10-02T09:15:00');self.assertEqual(r['jobs'][0]['completion_delta_minutes'],20)
 def test_qualification_covers_setup_and_process_not_start_only(self):
  self.args[1]['crew_credentials'][0]['valid_until']='2026-10-02T08:24:59';r=self.result()
  self.assertEqual(r['summary']['blocked_tasks'],3);self.assertIsNone(r['jobs'][0]['finished']);self.assertEqual(r['tasks'][-1]['root_tasks'],['TA'])
 def test_qualification_end_touching_is_valid(self):
  self.args[1]['crew_credentials'][0]['valid_until']='2026-10-02T08:25:00';self.assertEqual(self.result()['tasks'][0]['state'],'scheduled')
 def test_registration_expiry_date_included(self):
  self.args[3]['skills']['S1']['expires']='2026-10-02';self.assertEqual(self.result()['tasks'][0]['state'],'scheduled')
  self.args[3]['skills']['S1']['expires']='2026-10-01';self.assertEqual(self.result()['tasks'][0]['state'],'blocked')
 def test_assumed_window_clipped_to_registration(self):
  self.args[3]['skills']['S1']['approved']='2026-10-03';r=self.result();self.assertFalse(r['credentials'][0]['eligible']);self.assertEqual(r['summary']['blocked_tasks'],3)
 def test_future_window_missing_is_business_block_not_paused(self):
  self.args[1]['crew_windows'].pop(0);r=self.result();self.assertEqual(r['state'],'trial');self.assertEqual(r['summary']['blocked_tasks'],3)
 def test_person_training_interrupt_moves_whole_task(self):
  self.args[1]['crew_blocks']=[dict(id='B1',study_id='CR1',employee_id='E1',started='2026-10-02T08:20:00',finished='2026-10-02T09:00:00',reason='模拟培训',basis='SIM')]
  r=self.result();self.assertEqual(r['tasks'][0]['started'],'2026-10-02T09:00:00');self.assertEqual(r['workers'][0]['available_minutes'],200)
 def test_touching_training_boundary_does_not_delay(self):
  self.args[1]['crew_blocks']=[dict(id='B1',study_id='CR1',employee_id='E1',started='2026-10-02T08:25:00',finished='2026-10-02T09:00:00',reason='SIM',basis='SIM')]
  self.assertEqual(self.result()['tasks'][0]['started'],'2026-10-02T08:00:00')
 def test_worker_overlapping_calendar_pauses_whole_trial(self):
  self.args[1]['crew_windows'].append({**self.args[1]['crew_windows'][0],'id':'BAD'});r=self.result();self.assertEqual(r['state'],'paused');self.assertIsNone(r['summary']);self.assertEqual(r['tasks'],[])
 def test_wrong_process_credential_pauses_not_ignores(self):
  self.args[1]['crew_candidates'][0]['credential_id']='CS2';self.assertEqual(self.result()['state'],'paused')
 def test_inactive_or_revoked_is_blocked_known_constraint(self):
  for status in ['暂停','撤销','待审批']:
   self.args=list(fixture());self.args[3]['skills']['S1']['status']=status;r=self.result();self.assertEqual(r['state'],'trial');self.assertEqual(r['summary']['blocked_tasks'],3)
  self.args=list(fixture());self.args[3]['employees']['E1']['active']=False;self.assertEqual(self.result()['summary']['blocked_tasks'],3)
 def test_unknown_state_or_missing_person_pauses(self):
  self.args[3]['skills']['S1']['status']='未定义';self.assertEqual(self.result()['state'],'paused')
  self.args=list(fixture());self.args[3]['employees'].pop('E1');self.assertEqual(self.result()['state'],'paused')
 def test_declared_input_cannot_silently_shrink(self):
  declare(*self.args[:2]);self.args[1]['crew_windows'].pop();self.assertEqual(engine.analyze(*self.args)['state'],'paused')
 def test_deterministic_readonly_and_parent_unchanged(self):
  declare(*self.args[:2]);before=deepcopy(self.args);self.assertEqual(engine.analyze(*self.args),engine.analyze(*self.args));self.assertEqual(before,self.args)
 def test_slot_union_of_resource_and_person_blocks(self):
  time=finite_schedule.time
  slot=engine.fit(time('2026-10-02T08:00:00'),__import__('datetime').timedelta(minutes=25),[(time('2026-10-02T08:00:00'),time('2026-10-02T12:00:00'),'W')],[(time('2026-10-02T08:10:00'),time('2026-10-02T08:30:00'),'R'),(time('2026-10-02T08:20:00'),time('2026-10-02T09:00:00'),'P')])
  self.assertEqual(finite_schedule.stamp(slot[0]),'2026-10-02T09:00:00')
 def test_busy_minutes_exact_seconds_and_capacity_not_causal(self):
  r=self.result();self.assertEqual(r['workers'][0]['busy_minutes'],25);self.assertAlmostEqual(r['workers'][0]['load_percent'],25/240*100)
  self.assertIn('不是人员效率因果估计',r['resource_reference']['notice'])
