import json
from copy import deepcopy
from unittest.mock import patch
from django.test import SimpleTestCase
from django.contrib.auth.models import User, Group
from app import joint_schedule, joint_candidate_evidence as evidence
from app.models import Record, AuditEvent
from app.ingestion import fingerprint
from .test_joint_schedule import fixture
from .test_platform import PlatformCase

def context():
    study, tables, parent, refs = fixture()
    return dict(result=joint_schedule.analyze(study,tables,parent,refs),parent=parent,
                references={'production_resources':list(refs['production_resources'].values())})

class CandidateEvidenceTests(SimpleTestCase):
    def setUp(self):
        self.context = context()
        self.task = next(t for t in self.context['result']['tasks'] if t['id']=='TA')

    def build(self): return evidence.build(self.context,self.task)

    def test_keeps_original_candidate_identity_and_selection(self):
        d, refs = self.build()
        self.assertEqual(d['task_id'],'TA')
        self.assertTrue(d['resource_options'])
        self.assertEqual([r['id'] for r in d['resource_options'] if r['selected']],[self.task['option_id']])
        self.assertEqual([r['id'] for r in d['people_candidates'] if r['selected']],[self.task['candidate_id']])
        self.assertTrue(all(r['task_id']=='TA' for r in d['resource_options']+d['people_candidates']))
        self.assertIn(('schedule_tasks','TA'),refs)

    def test_capacity_gate_is_not_a_free_slot_claim(self):
        resource_id = self.task['resource_id']
        next(r for r in self.context['references']['production_resources'] if r['id']==resource_id)['max_batch_qty'] = 1
        d,_ = self.build()
        row = next(r for r in d['resource_options'] if r['resource_id']==resource_id)
        self.assertEqual(row['task_qty'],2); self.assertFalse(row['batch_fits'])
        self.assertIn('不代表当前剩余容量',d['notice'])
        self.assertNotIn('earliest_start',json.dumps(d))

    def test_ineligible_original_qualification_is_retained(self):
        q = next(q for q in self.context['result']['credentials'] if q['id']==self.task['credential_id'])
        q.update(eligible=False,effective_from=None,effective_until=None,reason='SIM expired')
        d,_ = self.build(); row = next(r for r in d['people_candidates'] if r['credential_id']==q['id'])
        self.assertFalse(row['eligible']);self.assertIsNone(row['effective_from']);self.assertEqual(row['reason'],'SIM expired')
        self.assertTrue(any(w['employee_id']==row['employee_id'] for w in d['crew_windows']))

    def test_no_windows_remains_empty_without_inferred_availability(self):
        self.context['parent']['tables']['crew_windows']=[]
        d,_=self.build();self.assertEqual(d['crew_windows'],[]);self.assertTrue(d['people_candidates'])

    def test_unrelated_task_candidates_do_not_leak(self):
        p=self.context['parent'];p['base']['tables']['schedule_options'].append(dict(id='OTHER',task_id='OTHER',resource_id='SECRET'))
        p['tables']['crew_candidates'].append(dict(id='OTHER',task_id='OTHER',credential_id='SECRET'))
        d,refs=self.build();self.assertNotIn('SECRET',json.dumps(d));self.assertNotIn(('schedule_options','OTHER'),refs)

    def test_windows_and_unavailability_are_separate_and_source_backed(self):
        p=self.context['parent'];resource=self.task['resource_id'];employee=self.task['employee_id']
        for ds,rows,key,identity in [('schedule_blocks',p['base']['tables']['schedule_blocks'],'resource_id',resource),('crew_blocks',p['tables']['crew_blocks'],'employee_id',employee)]:
            rows.append(dict(id=ds+'-SIM',**{key:identity},started='2026-10-02T08:00:00',finished='2026-10-02T08:10:00',reason='SIM block',basis='SIM'))
        d,refs=self.build()
        for ds in ('schedule_windows','schedule_blocks','crew_windows','crew_blocks'):
            self.assertTrue(d[ds]);self.assertTrue(all((ds,r['id']) in refs for r in d[ds]))
        self.assertEqual(d['schedule_blocks'][0]['reason'],'SIM block')

    def test_current_predecessor_and_first_blocker_objects_are_exact(self):
        d=self.context;self.task=next(t for t in d['result']['tasks'] if t['id']=='TC2')
        self.task['root_tasks']=['TA']
        v,refs=self.build();self.assertEqual([r['id'] for r in v['root_tasks']],['TA'])
        self.assertEqual({r['id'] for r in v['predecessors']},set(self.task['predecessors']))
        self.assertIn(('schedule_tasks','TA'),refs)

    def test_projection_is_detached_and_does_not_change_calculation(self):
        before=deepcopy(self.context);d,_=self.build();d['resource_options'][0]['resource_id']='CHANGED'
        d['crew_windows'][0]['basis']='CHANGED';self.assertEqual(self.context,before)

    def test_allowlist_excludes_extra_personnel_price_and_raw_fields(self):
        p=self.context['parent']
        for rows in [p['base']['tables']['schedule_options'],p['tables']['crew_candidates'],self.context['result']['credentials'],self.context['references']['production_resources']]:
            for row in rows:row.update(hourly_cents=987654321,phone='PRIVATE-SIM',arbitrary_payload={'secret':'PRIVATE-SIM'})
        d,_=self.build();raw=json.dumps(d)
        for forbidden in ('hourly_cents','987654321','PRIVATE-SIM','arbitrary_payload'):self.assertNotIn(forbidden,raw)

    def test_paused_or_foreign_task_is_rejected(self):
        with self.assertRaises(ValueError): evidence.build(self.context,{**self.task,'id':'OTHER'})
        self.context['result']['state']='paused'
        with self.assertRaises(ValueError):self.build()

class CandidateEvidenceAPITests(PlatformCase):
    def setUp(self):
        super().setUp()
        study,tables,parent,refs=fixture()
        self.record('joint_studies',study);self.record('crew_studies',parent['result']['study']);self.record('schedule_studies',parent['base']['study'])
        for ds,rows in {**tables,**parent['tables'],**parent['base']['tables']}.items():
            for row in rows:self.record(ds,row)
        for ds,rows in refs.items():
            for row in rows.values():self.record(ds,row)
        self.client.force_login(self.admin)

    def board(self):return self.client.get('/api/joint-schedule/MP1').json()
    def detail(self,receipt=None,task='TA'):
        return self.client.get('/api/joint-schedule/MP1/tasks/'+task,{'receipt':receipt or self.board()['receipt']})

    def test_detail_reads_candidates_without_mutating_records_or_audit(self):
        before=list(Record.objects.order_by('id').values());audit=AuditEvent.objects.count()
        r=self.detail();self.assertEqual(r.status_code,200);d=r.json()
        self.assertEqual(d['candidate_evidence']['task_id'],'TA');self.assertEqual(r['Cache-Control'],'no-store')
        self.assertEqual(list(Record.objects.order_by('id').values()),before);self.assertEqual(AuditEvent.objects.count(),audit)

    def test_expanded_sources_include_unused_options_qualifications_and_windows(self):
        d=self.detail().json();e=d['candidate_evidence'];keys={(s['dataset'],s['key']) for s in d['sources']}
        for r in e['resource_options']:
            self.assertIn(('schedule_options',r['id']),keys);self.assertIn(('production_resources',r['resource_id']),keys)
        for r in e['people_candidates']:
            for ds,key in [('crew_candidates',r['id']),('crew_credentials',r['credential_id']),('skills',r['skill_id']),('employees',r['employee_id'])]:self.assertIn((ds,key),keys)
        for ds in ('schedule_windows','schedule_blocks','crew_windows','crew_blocks'):
            for r in e[ds]:self.assertIn((ds,r['id']),keys)
        self.assertEqual(len(keys),len(d['sources']))

    def test_no_people_window_keeps_candidates_visible_on_blocked_task(self):
        Record.objects.filter(dataset='crew_windows').delete()
        r=Record.objects.get(dataset='crew_studies');r.values['window_count']=0;r.record_hash=fingerprint(r.values);r.save()
        r.source_row.normalized=r.values;r.source_row.record_hash=r.record_hash;r.source_row.save()
        d=self.detail().json();self.assertEqual(d['row']['state'],'blocked');self.assertTrue(d['candidate_evidence']['people_candidates'])
        self.assertEqual(d['candidate_evidence']['crew_windows'],[])
        self.assertFalse(any(r['selected'] for r in d['candidate_evidence']['resource_options']))

    def test_projection_definition_changes_expire_old_receipt(self):
        receipt=self.board()['receipt']
        with patch('app.joint_candidate_evidence.definition_hash',return_value='new-projection'):
            self.assertEqual(self.detail(receipt).status_code,409)

    def test_projection_definition_changes_during_read_reject_response(self):
        receipt=self.board()['receipt'];old=evidence.definition_hash()
        with patch('app.joint_candidate_evidence.definition_hash',side_effect=[old,'changed-during-read']):
            self.assertEqual(self.detail(receipt).status_code,409)

    def test_roles_and_original_permissions_stay_separate(self):
        for role in ('analyst','operations','quality','finance','viewer'):
            u=User.objects.create_user('candidate-'+role);u.groups.add(Group.objects.get_or_create(name=role)[0]);self.client.force_login(u)
            expected=200 if role in ('analyst','operations') else 403
            if expected==200:
                d=self.detail();self.assertEqual(d.status_code,200);self.assertFalse(d.json()['can_download_original'])
            else:self.assertEqual(self.client.get('/api/joint-schedule/MP1/tasks/TA',{'receipt':'not-authorized'}).status_code,403)

    def test_full_exports_keep_original_trial_and_inputs(self):
        board=self.board();self.detail(board['receipt'])
        file=self.client.get('/api/joint-schedule/MP1/export',{'receipt':board['receipt'],'format':'json'}).json()
        self.assertEqual(file['result']['tasks'],board['tasks']);self.assertEqual(len(file['resource_inputs']['schedule_options']),4)
        self.assertNotIn('candidate_evidence',file['result'])

    def test_candidate_evidence_rebuilds_from_full_export_without_database(self):
        board=self.board();detail=self.detail(board['receipt']).json()
        file=self.client.get('/api/joint-schedule/MP1/export',{'receipt':board['receipt'],'format':'json'}).json()
        context=dict(result=file['result'],references=file['references'],parent=dict(tables=file['crew_inputs'],base=dict(tables=file['resource_inputs'])))
        with self.assertNumQueries(0):
            rebuilt,_=evidence.build(context,detail['row'])
        self.assertEqual(rebuilt,detail['candidate_evidence'])

    def test_missing_receipt_and_foreign_task_remain_rejected(self):
        self.assertEqual(self.client.get('/api/joint-schedule/MP1/tasks/TA').status_code,400)
        self.assertEqual(self.detail(task='OTHER').status_code,404)
