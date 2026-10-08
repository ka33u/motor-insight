from copy import deepcopy
import json
from unittest.mock import patch
from django.test import SimpleTestCase
from app import joint_schedule, crew_schedule, finite_schedule, joint_batch_material as evidence
from app.models import Record, AuditEvent
from .test_joint_schedule import fixture, declare
from .test_crew_schedule import declare as declare_crew
from .test_platform import PlatformCase


def two_batches():
    args = list(fixture())
    parent = args[2]
    base, ct = parent['base'], parent['tables']
    bt = base['tables']
    bt['schedule_jobs'][0]['priority'] = 2
    bt['schedule_jobs'].append({**bt['schedule_jobs'][0], 'id': 'J2', 'priority': 1, 'due': '2026-10-02T11:00:00'})
    for ds in ('schedule_tasks', 'schedule_edges', 'schedule_options'):
        for old in list(bt[ds]):
            row = {**old, 'id': old['id']+'-2'}
            if ds == 'schedule_tasks': row['job_id'] = 'J2'
            if ds == 'schedule_edges': row['from_task_id'] += '-2'; row['to_task_id'] += '-2'
            if ds == 'schedule_options': row['task_id'] += '-2'
            bt[ds].append(row)
    ct['crew_candidates'].extend([{**c, 'id': c['id']+'-2', 'task_id': c['task_id']+'-2'} for c in list(ct['crew_candidates'])])
    args[1]['joint_demands'].extend([{**d, 'id': d['id']+'-2', 'job_id': 'J2'} for d in list(args[1]['joint_demands'])])
    args[1]['joint_supplies'][1]['qty'] = 4
    for field, ds in [('job_count', 'schedule_jobs'), ('task_count', 'schedule_tasks'), ('edge_count', 'schedule_edges'), ('option_count', 'schedule_options')]:
        base['study'][field] = len(bt[ds])
    declare_crew(parent['result']['study'], ct)
    declare(*args[:2])
    return args


def boards(args):
    outputs = []
    for policy in ('due', 'priority'):
        parent, refs = args[2:]
        base = parent['base']
        base['result'] = finite_schedule.analyze(base['study'], base['tables'], refs, policy)
        parent['result'] = crew_schedule.analyze(parent['result']['study'], parent['tables'], base, refs)
        outputs.append(joint_schedule.analyze(*args))
    return outputs


class BatchMaterialRules(SimpleTestCase):
    def setUp(self): self.args = two_batches()
    def result(self): return evidence.build(*boards(self.args))
    def test_same_total_different_recipients_has_exact_balancing_gains_losses(self):
        d = self.result(); m = d['materials'][0]
        self.assertEqual((m['left_reserved_qty'], m['right_reserved_qty'], m['reserved_delta_qty']), ('5', '5', '0'))
        self.assertEqual((m['increased_qty'], m['decreased_qty'], m['more_jobs'], m['less_jobs']), ('5', '5', 1, 1))
        rows = [r for r in d['rows'] if r['material_id'] == 'M1']
        self.assertEqual([(r['job_id'], r['quantity_change']) for r in rows], [('J1', 'less'), ('J2', 'more')])
    def test_changed_job_counts_deduplicate_across_materials(self):
        d = self.result(); self.assertEqual(d['summary']['quantity_changed_pairs'], 4)
        self.assertEqual(d['summary']['unique_quantity_changed_jobs'], 2)
        self.assertNotIn('qty', d['summary'])
    def test_full_pool_changes_flow_without_changing_quantities(self):
        self.args[1]['joint_supplies'][0]['qty'] = 10
        d = self.result(); self.assertEqual(d['summary']['quantity_changed_pairs'], 0)
        self.assertGreater(d['summary']['allocation_only_changed_pairs'], 0)
        self.assertTrue(all(r['reserved_delta_qty'] == '0' for r in d['rows']))
    def test_partial_batch_preserves_whole_demand_and_unfinished_job(self):
        self.args[1]['joint_supplies'][0]['qty'] = 4
        r = self.result()['rows'][0]
        self.assertEqual((r['required_qty'], r['left']['reserved_qty'], r['left']['unreserved_qty']), ('5', '3', '2'))
        self.assertEqual(r['left']['job_state'], 'blocked'); self.assertIsNone(r['left']['job_finished'])
        self.assertEqual(r['demand_ids'], ['D1', 'D2'])
    def test_all_portions_link_but_demand_is_counted_once(self):
        r = next(r for r in self.result()['rows'] if r['material_id'] == 'M2' and r['job_id'] == 'J1')
        self.assertEqual(r['required_qty'], '2'); self.assertEqual(r['task_ids'], ['TC1', 'TC2'])
    def test_common_quantity_scale_uses_all_jobs(self):
        d = self.result(); self.assertEqual(d['materials'][0]['chart_max_qty'], '5')
        for r in d['rows']:
            self.assertEqual(r['required_percent'], 100)
            for side in ('left', 'right'):
                self.assertEqual(r[side]['reserved_percent']+r[side]['unreserved_percent'], 100)
    def test_people_blocked_does_not_claim_shortage(self):
        self.args[2]['tables']['crew_windows'] = []; self.args[2]['result']['study']['window_count'] = 0
        d = self.result(); self.assertEqual(d['materials'][0]['left_reserved_qty'], '0')
        self.assertTrue(all(r['left']['job_state'] == 'blocked' for r in d['rows']))
        self.assertFalse(any('shortage' in k for r in d['rows'] for k in r))
    def test_unequal_declared_demands_use_same_absolute_scale(self):
        # Hand ledger for the projection's scale: one 5 kg job and one 10 kg job.
        # No scheduling claim is derived from this isolated output fixture.
        left = boards(self.args)[0]
        for need in left['demands']:
            if need['job_id'] == 'J2' and need['material_id'] == 'M1':
                need['required_qty'] = str(int(need['required_qty'])*2)
        left['balances'][0].update(required_qty='15', initial_supply_gap_qty='10')
        right = deepcopy(left); right['policy'] = 'priority'
        d = evidence.build(left, right); rows = [r for r in d['rows'] if r['material_id'] == 'M1']
        self.assertEqual(d['materials'][0]['chart_max_qty'], '10')
        self.assertEqual([r['required_percent'] for r in rows], [50, 100])
        self.assertEqual(rows[0]['left']['reserved_percent'], 50)
    def test_supply_only_material_has_no_fabricated_recipient(self):
        self.args[3]['materials']['M3'] = dict(id='M3', name='备件', unit='件')
        self.args[1]['joint_supplies'].append({**self.args[1]['joint_supplies'][1], 'id': 'L3', 'material_id': 'M3', 'qty': 10})
        declare(*self.args[:2]); d = self.result(); m = d['materials'][-1]
        self.assertEqual((m['material_id'], m['jobs'], m['chart_max_qty']), ('M3', 0, '0'))
        self.assertFalse(any(r['material_id'] == 'M3' for r in d['rows']))
    def test_units_and_negative_decimal_deltas_are_retained(self):
        d = self.result(); self.assertEqual({r['unit'] for r in d['materials']}, {'kg', '件'})
        self.assertEqual(d['rows'][0]['reserved_delta_qty'], '-5')
    def test_paused_is_not_zero_recipient_change(self):
        left, right = boards(self.args); right.update(state='paused', summary=None)
        d = evidence.build(left, right); self.assertEqual(d['state'], 'paused')
        self.assertIsNone(d['summary']); self.assertEqual(d['rows'], [])
    def test_different_input_or_missing_scope_fails_closed(self):
        for change in (lambda r: r['jobs'].pop(), lambda r: r['demands'].pop(), lambda r: r['demands'][0].update(required_qty='9'), lambda r: r['lots'][0].update(qty=99), lambda r: r['tasks'][0].update(route_id='OTHER')):
            left, right = boards(self.args); change(right)
            with self.assertRaises(ValueError): evidence.build(left, right)
    def test_invalid_ledger_fails_without_trusting_precomputed_totals(self):
        for change in (lambda r: r['balances'][0].update(reserved_qty='0'), lambda r: r['reservations'][0].update(qty='-1'), lambda r: r['demands'][0].update(reserved_qty='NaN')):
            left, right = boards(self.args); change(right)
            with self.assertRaises(ValueError): evidence.build(left, right)
    def test_identity_and_policy_order_rejected(self):
        for change in (lambda r: r.update(policy='due'), lambda r: r['study'].update(version='NEW')):
            left, right = [deepcopy(board) for board in boards(self.args)]; change(right)
            with self.assertRaises(ValueError): evidence.build(left, right)
    def test_global_flow_sequence_only_does_not_fake_recipient_change(self):
        left = boards(self.args)[0]; right = deepcopy(left); right.update(policy='priority'); right['reservations'].reverse()
        d = evidence.build(left, right)
        self.assertEqual(d['summary']['quantity_changed_pairs'], 0); self.assertEqual(d['summary']['allocation_only_changed_pairs'], 0)
    def test_allowlist_does_not_expand_private_reference_fields(self):
        pair = boards(self.args)
        for board in pair:
            for key in ('jobs', 'demands', 'lots'):
                for r in board[key]: r['hourly_cents'] = 999
        self.assertNotIn('hourly_cents', json.dumps(evidence.build(*pair)))
    def test_no_mutation_and_reordered_rows_keep_same_result(self):
        pair = boards(self.args); before = deepcopy(pair); d = evidence.build(*pair); self.assertEqual(pair, before)
        for board in pair:
            for key in ('jobs', 'tasks', 'demands', 'balances', 'lots'): board[key].reverse()
        self.assertEqual(d, evidence.build(*pair))


class BatchMaterialAPI(PlatformCase):
    def setUp(self):
        super().setUp(); study, tables, parent, refs = two_batches()
        self.record('joint_studies', study); self.record('crew_studies', parent['result']['study']); self.record('schedule_studies', parent['base']['study'])
        for ds, rows in {**tables, **parent['tables'], **parent['base']['tables']}.items():
            for row in rows: self.record(ds, row)
        for ds, rows in refs.items():
            for row in rows.values(): self.record(ds, row)
        self.client.force_login(self.admin)
    def call(self, suffix='', body=None, status=200):
        r = self.client.post('/api/joint-comparison/MP1'+suffix, json.dumps(body or {}), content_type='application/json')
        self.assertEqual(r.status_code, status, r.content[:100]); return r.json()
    def test_same_total_recipient_change_is_returned_by_existing_board(self):
        d = self.call(); self.assertEqual(d['batch_materials']['materials'][0]['reserved_delta_qty'], '0')
        self.assertEqual(d['batch_materials']['materials'][0]['more_jobs'], 1)
    def test_projection_and_upstream_definition_changes_invalidate_receipt(self):
        for module in ('app.joint_batch_material.definition_hash', 'app.joint_material_evidence.definition_hash'):
            d = self.call()
            with patch(module, return_value='changed'): self.call('/sources', dict(receipt=d['receipt']), 409)
    def test_complete_exports_keep_projection_and_can_rebuild_without_queries(self):
        d = self.call(); doc = json.loads(self.call('/export', dict(receipt=d['receipt'], format='json'))['text'])
        self.assertEqual(doc['comparison']['batch_materials'], d['batch_materials'])
        with self.assertNumQueries(0): rebuilt = evidence.build(doc['left']['result'], doc['right']['result'])
        self.assertEqual(rebuilt, d['batch_materials'])
        csv = self.call('/export', dict(receipt=d['receipt'], format='csv'))['text']
        self.assertIn('批次获料/materials', csv); self.assertIn('批次获料/rows', csv); self.assertIn('两列共同来源', csv)
    def test_projection_does_not_write_or_change_original_heuristic_fields(self):
        before = list(Record.objects.values()); audits = AuditEvent.objects.count(); d = self.call()
        self.assertEqual(before, list(Record.objects.values())); self.assertEqual(audits, AuditEvent.objects.count())
        for policy, side in [('due', 'left'), ('priority', 'right')]:
            original = self.client.get('/api/joint-schedule/MP1', dict(policy=policy, receipt=d['policy_receipts'][policy])).json()
            self.assertEqual({r['id']: r[side] for r in d['jobs']}, {r['id']: r for r in original['jobs']})
