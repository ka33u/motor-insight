from collections import defaultdict
from copy import deepcopy
from django.test import SimpleTestCase
from app import launch as engine, order_baseline
from app.launch_contract import COUNTS, KINDS, bundle_hash, issues
from .test_order_baseline import fixture as baseline_fixture


def seal(study, tables):
    study.update({field: len(tables[ds]) for ds, field in COUNTS.items()})
    study['content_hash'] = bundle_hash(study, tables)


def fixture():
    bs, bt, joint, refs, cutoff = baseline_fixture()
    parent = dict(result=order_baseline.analyze(bs, bt, joint, refs, cutoff), tables=bt, parent=joint)
    s = dict(id='LR1', name='投产核对', baseline_id='OB1', assessed_at=cutoff, owner_id='E1', basis='SIM')
    t = {ds: [] for ds in COUNTS}
    common = dict(study_id='LR1', registered=cutoff, valid_from='2026-10-02T08:00:00', valid_until='2026-10-03T18:00:00', owner_id='E1', reference='SIM', note='合成登记')
    refs['tools'] = {}
    for i, route in enumerate(('A', 'B', 'C'), 1):
        tool = dict(id='TOOL'+str(i), name='工装'+str(i), kind='工装夹具', equipment_id='EQ'+str(i), uses=90, maintenance_limit=100, calibrated='2026-01-01', next_due='2027-01-01', status='有效')
        refs['tools'][tool['id']] = tool
        refs['production_resources']['R'+str(i)]['equipment_id'] = tool['equipment_id']
        t['launch_tool_fits'].append(dict(common, id='FIT'+route, group='FG'+route, tool_id=tool['id'], product_id='P1', route_id=route, version='V1', status='配套有效'))
        t['launch_documents'].append(dict(common, id='DOC'+route, document_no='WI-'+route, product_id='P1', route_id=route, version='V1', status='已发布'))
        t['launch_clearances'].append(dict(common, id='QC'+route, work_order_id='WO1', route_id=route, version='V1', status='具备登记条件'))
        for kind, prefix in zip(KINDS, ('FG', 'DOC', 'QC')):
            t['launch_requirements'].append(dict(id=kind+route, study_id='LR1', job_id='J1', route_id=route, kind=kind, applicable=True, subject=prefix+route, version='V1', uses_per_unit=1 if kind=='工装' else 0, reason='SIM'))
    seal(s, t)
    return [s, t, parent, refs, cutoff]


class LaunchTests(SimpleTestCase):
    def setUp(self): self.args = fixture()
    def result(self, reseal=True):
        if reseal: seal(*self.args[:2])
        return engine.analyze(*self.args)
    def task(self, result, key): return next(t for t in result['tasks'] if t['id'] == key)
    def gate(self, result, key, kind): return next(g for g in self.task(result, key)['gates'] if g['kind'] == kind)

    def test_fixed_trial_and_unit_portions_conserve_usage(self):
        r = self.result()
        self.assertEqual(r['state'], 'review', r['issues'])
        self.assertEqual(r['summary'], dict(tasks=4,satisfied=4,blocked=0,unknown=0,jobs=1,satisfied_jobs=1,plan_qty=2,conditions=9,not_required=0,proposed_tool_uses=6,uncovered_qty=8))
        self.assertEqual([t['proposed_uses'] for t in r['tools']], [2,2,2])
        self.assertEqual(self.task(r,'TC2')['started'], '2026-10-02T08:45:00')

    def test_missing_matrix_row_cannot_be_inferred_not_required(self):
        self.args[1]['launch_requirements'].pop()
        r=self.result(); self.assertEqual(r['state'],'paused'); self.assertIsNone(r['summary'])

    def test_duplicate_and_foreign_matrix_pairs_pause(self):
        self.args[1]['launch_requirements'][-1].update(job_id='OTHER')
        self.assertEqual(self.result()['state'],'paused')

    def test_hash_and_declared_count_detect_removed_evidence(self):
        self.args[1]['launch_documents'].pop()
        self.assertEqual(self.result(False)['state'],'paused')

    def test_explicit_not_required_keeps_its_reason(self):
        self.args[1]['launch_requirements'][1].update(applicable=False,subject=None,version=None,reason='本工序使用上位文件；仅模拟豁免')
        r=self.result(); self.assertEqual(self.gate(r,'TA','工艺文件')['state'],'not_required')
        self.assertEqual(r['summary']['not_required'],1)

    def test_missing_evidence_is_unknown(self):
        self.args[1]['launch_requirements'][1]['subject']='MISSING'
        r=self.result(); self.assertEqual(self.gate(r,'TA','工艺文件')['state'],'unknown')
        self.assertEqual(self.task(r,'TC1')['upstream'],['TA'])

    def test_document_version_and_product_scope(self):
        self.args[1]['launch_documents'][0].update(version='V2',product_id='OTHER')
        g=self.gate(self.result(),'TA','工艺文件')
        self.assertEqual(g['state'],'blocked'); self.assertIn('登记版本与要求不符',g['reasons']); self.assertIn('文件适用配置不符',g['reasons'])

    def test_quality_restriction_propagates_without_moving_reference_times(self):
        self.args[1]['launch_clearances'][0]['status']='限制开工'
        r=self.result(); self.assertEqual(self.task(r,'TC2')['state'],'blocked')
        self.assertEqual(self.task(r,'TC2')['finished'],'2026-10-02T08:55:00')
        self.assertEqual(r['summary']['satisfied'],1)

    def test_future_registration_is_unknown_and_work_order_mismatch_blocked(self):
        self.args[1]['launch_clearances'][0].update(registered='2026-10-01T18:00:01',work_order_id='OTHER')
        g=self.gate(self.result(),'TA','质量条件')
        self.assertEqual(g['state'],'unknown'); self.assertIn('质量条件对应工单不符',g['reasons'])

    def test_whole_setup_interval_and_exact_end_boundary(self):
        self.args[1]['launch_documents'][0]['valid_until']='2026-10-02T08:25:00'
        self.assertEqual(self.gate(self.result(),'TA','工艺文件')['state'],'satisfied')
        self.args[1]['launch_documents'][0]['valid_from']='2026-10-02T08:00:01'
        self.assertEqual(self.gate(self.result(),'TA','工艺文件')['state'],'blocked')

    def test_shared_physical_tool_overlaps_across_resource_slots(self):
        self.args[3]['production_resources']['R2']['equipment_id']='EQ1'
        self.args[1]['launch_tool_fits'][1]['tool_id']='TOOL1'
        g=self.gate(self.result(),'TB','工装')
        self.assertEqual(g['state'],'blocked'); self.assertTrue(any('重叠' in x for x in g['reasons']))

    def test_adjacent_reservations_and_cumulative_lifetime_boundary(self):
        self.args[3]['tools']['TOOL3']['uses']=98
        self.assertEqual(self.gate(self.result(),'TC2','工装')['state'],'satisfied')
        self.args[3]['tools']['TOOL3']['uses']=99
        self.assertEqual(self.gate(self.result(),'TC1','工装')['state'],'satisfied')
        self.assertEqual(self.gate(self.result(),'TC2','工装')['state'],'blocked')

    def test_prior_external_booking_and_exact_adjacency(self):
        row=dict(id='BL1',study_id='LR1',tool_id='TOOL1',started='2026-10-02T07:00:00',ended='2026-10-02T08:00:00',registered=self.args[-1],owner_id='E1',reason='借用')
        self.args[1]['launch_tool_blocks'].append(row)
        self.assertEqual(self.gate(self.result(),'TA','工装')['state'],'satisfied')
        row['ended']='2026-10-02T08:00:01'
        self.assertEqual(self.gate(self.result(),'TA','工装')['state'],'blocked')

    def test_tool_expiry_malformed_counts_and_equipment(self):
        tool=self.args[3]['tools']['TOOL1'];tool.update(next_due='2026-10-02',equipment_id='OTHER')
        g=self.gate(self.result(),'TA','工装');self.assertEqual(g['state'],'blocked');self.assertEqual(len(g['reasons']),2)
        tool['uses']=True
        self.assertEqual(self.gate(self.result(),'TA','工装')['state'],'unknown')

    def test_other_gates_blocked_does_not_silently_free_proposed_tool_budget(self):
        self.args[1]['launch_clearances'][0]['status']='限制开工'
        self.assertEqual(self.result()['summary']['proposed_tool_uses'],6)

    def test_alternative_tool_must_be_valid_in_its_own_right(self):
        self.args[3]['tools']['TOOL1']['uses']=100
        self.args[3]['tools']['TOOL4']=dict(self.args[3]['tools']['TOOL1'],id='TOOL4',uses=0)
        self.args[1]['launch_tool_fits'].append(dict(self.args[1]['launch_tool_fits'][0],id='FIT4',tool_id='TOOL4'))
        self.assertEqual(self.gate(self.result(),'TA','工装')['tool_id'],'TOOL4')

    def test_parent_review_and_unplanned_task_never_mark_ready(self):
        self.args[2]['result']['state']='review'
        self.assertEqual(self.result()['summary']['satisfied'],0)
        self.args[2]['result']['state']='aligned'
        self.args[2]['parent']['result']['tasks'][0].update(state='blocked',started=None,finished=None,reason='缺料')
        self.assertEqual(self.task(self.result(),'TA')['state'],'unknown')

    def test_paused_parent_future_cutoff_and_missing_owner_pause(self):
        self.args[0]['assessed_at']='2026-10-01T18:00:01'
        self.assertEqual(self.result()['state'],'paused')
        self.args[0]['assessed_at']=self.args[-1];self.args[2]['result']['state']='paused'
        self.assertEqual(self.result()['state'],'paused')

    def test_contract_rejects_incoherent_exemption_and_time(self):
        r=deepcopy(self.args[1]['launch_requirements'][0]);r['applicable']=False
        self.assertTrue(issues('launch_requirements',r))
        r=deepcopy(self.args[1]['launch_documents'][0]);r['valid_until']=r['valid_from']
        self.assertTrue(issues('launch_documents',r))

    def test_read_only_repeatable(self):
        old=deepcopy(self.args);a=self.result();b=self.result()
        self.assertEqual(a,b);self.assertEqual(old,self.args)
