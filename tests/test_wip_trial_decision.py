from copy import deepcopy
from unittest.mock import patch
from django.test import SimpleTestCase
from app import wip_trial, wip_trial_decision as decision, finite_schedule, crew_schedule, joint_schedule
from app.wip_trial_contract import REFERENCE_FIELDS
from .test_wip_trial import fixture,running,seal,second_job
from .test_crew_schedule import declare as declare_crew
from .test_joint_schedule import declare as declare_joint


def context(args):
    study,tables,joint,refs=args;parent=joint['parent'];base=parent['base'];rs=base['result']['study']
    for f,ds in [('job_count','schedule_jobs'),('task_count','schedule_tasks'),('edge_count','schedule_edges'),('option_count','schedule_options'),('window_count','schedule_windows'),('block_count','schedule_blocks')]:rs[f]=len(base['tables'][ds])
    base['result']=finite_schedule.analyze(rs,base['tables'],refs)
    cs=parent['result']['study'];declare_crew(cs,parent['tables']);parent['result']=crew_schedule.analyze(cs,parent['tables'],base,refs)
    js=joint['result']['study'];declare_joint(js,joint['tables']);joint['result']=joint_schedule.analyze(js,joint['tables'],parent,refs)
    seal(*args)
    return dict(result=wip_trial.analyze(*args,study['cutoff']),tables=tables,joint_context=joint,
        references={ds:[{f:r.get(f) for f in fields} for r in refs.get(ds,{}).values()] for ds,fields in REFERENCE_FIELDS.items()},
        version_history=list(refs.get('wip_trial_studies',{}).values()))


class WipDecisionTests(SimpleTestCase):
    def setUp(self):self.args=fixture()
    def build(self,task='TC2'):
        c=context(self.args);self.assertEqual(c['result']['state'],'trial',c['result']['issues']);before=deepcopy(c)
        d=decision.build(c,task,self.args[0]['cutoff']);self.assertEqual(c,before)
        self.assertIn(d['state'],('explained','historical'),d['issues']);return d
    def test_hand_calculated_tail_and_same_family_setup(self):
        d=self.build();p=d['pairs'][0]
        self.assertTrue(p['selected']);self.assertEqual(p['resource_tail_tasks'],['TC1']);self.assertEqual(p['worker_tail_tasks'],['TC1'])
        self.assertEqual((p['setup_minutes'],p['started'],p['finished']),(0,'2026-10-02T08:40:00','2026-10-02T08:50:00'))
        self.assertEqual(p['previous_family'],p['task_family']);self.assertEqual(d['lots'][0]['remaining_before_task'],'1')
    def test_historical_completion_has_no_hypothetical_future_matrix(self):
        d=self.build('TA');self.assertEqual(d['state'],'historical');self.assertFalse(d['pairs']);self.assertFalse(d['lots'])
    def test_running_lock_uses_original_qty_no_setup(self):
        running(self.args);p=self.build('TA')['pairs'][0]
        self.assertEqual((p['checked_qty'],p['setup_minutes'],p['finished']),(2,0,'2026-10-02T08:12:00'))
        self.assertEqual(p['capacity_basis'],'原处理批量')
    def test_paused_recovery_added_to_first_family_setup(self):
        running(self.args);self.args[1]['wip_trial_tasks'][0].update(state='中断待续',resource_id=None,employee_id=None,recovery_minutes=3)
        self.args[3]['operations']['OP1'].update(status='中断',finished='2026-10-02T07:50:00')
        p=self.build('TA')['pairs'][0];self.assertEqual((p['checked_qty'],p['setup_minutes'],p['finished']),(1,8,'2026-10-02T08:20:00'))
    def test_shared_worker_tail_from_different_resource(self):
        running(self.args);self.args[3]['skills']['S2']['employee_id']='E1'
        p=self.build('TB')['pairs'][0];self.assertEqual(p['resource_tail_tasks'],[]);self.assertEqual(p['worker_tail_tasks'],['TA']);self.assertEqual(p['started'],'2026-10-02T08:12:00')
    def test_missing_material_does_not_claim_no_capacity(self):
        self.args[1]['wip_trial_supplies'][0]['qty']=0
        p=self.build('TB')['pairs'][0];self.assertIsNone(p['started']);self.assertIsNone(p['earliest']);self.assertIn('剩余物料不足，未计算连续窗口',p['reasons']);self.assertTrue(p['windows'])
    def test_failed_predecessors_have_root_links_not_fabricated_shortage(self):
        self.args[1]['wip_trial_supplies'][0]['qty']=0
        d=self.build('TC2');self.assertEqual(d['failed_predecessors'],['TB']);self.assertTrue(any(t['id']=='TB' for t in d['related_tasks']));self.assertIsNone(d['pairs'][0]['earliest'])
    def test_future_stock_moves_earliest_and_is_not_final_balance(self):
        self.args[1]['wip_trial_supplies'][0].update(kind='未来到料',available_from='2026-10-02T09:00:00')
        d=self.build('TB');self.assertEqual(d['pairs'][0]['started'],'2026-10-02T09:00:00');self.assertEqual(d['lots'][0]['remaining_before_task'],'5')
    def test_dedicated_other_job_stock_is_excluded(self):
        second_job(self.args);self.args[1]['wip_trial_supplies'][0].update(kind='线边盘点',owner_job_id='J2')
        d=self.build('TB');self.assertFalse(d['lots'][0]['eligible']);self.assertIn('其他批次专属',d['lots'][0]['reasons'])
    def test_invalid_credential_and_capacity_reasons_remain_distinct(self):
        self.args[3]['skills']['S2']['status']='撤销';p=self.build('TB')['pairs'][0]
        self.assertFalse(p['credential']['eligible']);self.assertFalse(p['windows']);self.assertIn('资格无效',p['reasons'][0])
        self.args=fixture();self.args[3]['production_resources']['R2']['max_batch_qty']=1
        p=self.build('TB')['pairs'][0];self.assertIn('批量超过资源上限',p['reasons']);self.assertTrue(p['credential']['eligible'])
    def test_qualification_end_boundary_covers_entire_interval(self):
        cred=self.args[2]['parent']['tables']['crew_credentials'][1];cred['valid_until']='2026-10-02T08:15:00'
        p=self.build('TB')['pairs'][0];self.assertTrue(p['selected']);self.assertEqual(p['windows'][0]['finished'],cred['valid_until'])
        cred['valid_until']='2026-10-02T08:14:59';p=self.build('TB')['pairs'][0];self.assertFalse(p['selected']);self.assertIn('尾部之后没有共同连续窗口',p['reasons'])
    def test_unavailability_moves_whole_contiguous_operation(self):
        self.args[2]['parent']['tables']['crew_blocks'].append(dict(id='X',study_id='CR1',employee_id='E2',started='2026-10-02T08:05:00',finished='2026-10-02T09:00:00',reason='SIM',basis='SIM'))
        p=self.build('TB')['pairs'][0];self.assertEqual(p['started'],'2026-10-02T09:00:00');self.assertEqual(p['blocks'][0]['id'],'X')
    def test_all_combinations_and_lexical_tie_are_preserved(self):
        bt=self.args[2]['parent']['base']['tables'];ct=self.args[2]['parent']['tables']
        refs=self.args[3];refs['production_resources']['R4']=dict(refs['production_resources']['R2'],id='R4',equipment_id='EQ-R4')
        bt['schedule_windows'].append(dict(bt['schedule_windows'][1],id='WR4',resource_id='R4'))
        bt['schedule_options'].append(dict(bt['schedule_options'][1],id='Z-OPTION',resource_id='R4'))
        refs['employees']['E4']=dict(id='E4',name='E4',active=True)
        refs['skills']['S4']=dict(refs['skills']['S2'],id='S4',employee_id='E4')
        ct['crew_credentials'].append(dict(ct['crew_credentials'][1],id='CS4',skill_id='S4'))
        ct['crew_windows'].append(dict(ct['crew_windows'][1],id='WE4',employee_id='E4'))
        ct['crew_candidates'].append(dict(ct['crew_candidates'][1],id='Z-CANDIDATE',credential_id='CS4'))
        d=self.build('TB');self.assertEqual(d['pair_count'],4);self.assertEqual(len(d['pairs']),4);self.assertEqual(sum(p['selected'] for p in d['pairs']),1)
        self.assertEqual(sum(p['status']=='feasible' for p in d['pairs']),3);self.assertEqual(next(p for p in d['pairs'] if p['selected'])['option_id'],'OTB')
    def test_observation_copies_cannot_mutate_pools_or_result(self):
        c=context(self.args);obs={'TC2':None};r=wip_trial.analyze(*self.args,self.args[0]['cutoff'],observations=obs)
        obs['TC2']['assigned']['TC1']['finished']='BAD';obs['TC2']['lots'].clear();obs['TC2']['choices'].clear()
        self.assertEqual(r,c['result']);self.assertEqual(wip_trial.analyze(*self.args,self.args[0]['cutoff']),r)
    def test_overflow_is_explicit_without_plausible_subset(self):
        c=context(self.args)
        for constant in ('MAX_PAIRS','MAX_WINDOW_WORK'):
            with patch('app.wip_trial_decision.'+constant,0):d=decision.build(c,'TC2',self.args[0]['cutoff'])
            self.assertEqual(d['state'],'unavailable');self.assertEqual(d['pairs'],[]);self.assertTrue(d['issues'])
    def test_changed_replay_never_claims_selection_verified(self):
        c=context(self.args);c['result']['tasks'][-1]['finished']='2026-10-02T11:11:11'
        d=decision.build(c,'TC2',self.args[0]['cutoff']);self.assertEqual(d['state'],'unavailable');self.assertFalse(d['pairs'])
    def test_unknown_task_and_paused_trial_rejected(self):
        c=context(self.args)
        with self.assertRaises(ValueError):decision.build(c,'unknown',self.args[0]['cutoff'])
        c['result']['state']='paused'
        with self.assertRaises(ValueError):decision.build(c,'TC2',self.args[0]['cutoff'])
    def test_mismatched_observed_choices_stop_explanation(self):
        c=context(self.args);original=wip_trial.analyze
        def tampered(*args,**kwargs):
            result=original(*args,**kwargs);kwargs['observations']['TC2']['choices']=[];return result
        with patch('app.wip_trial_decision.wip_trial.analyze',side_effect=tampered):d=decision.build(c,'TC2',self.args[0]['cutoff'])
        self.assertEqual(d['state'],'unavailable');self.assertFalse(d['pairs']);self.assertIn('可行组合不一致',d['issues'][0])
