from copy import deepcopy
import json
from unittest.mock import patch
from django.test import SimpleTestCase
from app import joint_setup as setup
from .test_joint_batch_material import two_batches, boards
from .test_joint_schedule import declare
from .test_crew_schedule import declare as declare_crew
from .test_platform import PlatformCase


def three_batches():
    args = two_batches()
    parent = args[2]
    bt = parent['base']['tables']
    original_tasks = {t['id'] for t in bt['schedule_tasks'] if t['job_id'] == 'J1'}
    bt['schedule_jobs'].append({**bt['schedule_jobs'][0], 'id': 'J3'})
    for job, family, priority, due in zip(bt['schedule_jobs'], ('A', 'B', 'A'), (1, 3, 2), (10, 11, 12)):
        job.update(family=family, priority=priority, due=f'2026-10-02T{due}:00:00')
    for ds in ('schedule_tasks', 'schedule_edges', 'schedule_options'):
        for source in list(bt[ds]):
            field = 'id' if ds == 'schedule_tasks' else 'from_task_id' if ds == 'schedule_edges' else 'task_id'
            if source[field] not in original_tasks:
                continue
            row = {**source, 'id': source['id']+'-3'}
            if ds == 'schedule_tasks': row['job_id'] = 'J3'
            elif ds == 'schedule_edges': row['from_task_id'] += '-3'; row['to_task_id'] += '-3'
            else: row['task_id'] += '-3'
            bt[ds].append(row)
    for option in bt['schedule_options']:
        option['setup_minutes'] = 12
    ct = parent['tables']
    ct['crew_candidates'].extend({**r, 'id': r['id']+'-3', 'task_id': r['task_id']+'-3'} for r in list(ct['crew_candidates']) if r['task_id'] in original_tasks)
    args[1]['joint_demands'].extend({**r, 'id': r['id']+'-3', 'job_id': 'J3'} for r in list(args[1]['joint_demands']) if r['job_id'] == 'J1')
    for supply in args[1]['joint_supplies']:
        supply['qty'] = 15 if supply['material_id'] == 'M1' else 6
    for field, ds in [('job_count', 'schedule_jobs'), ('task_count', 'schedule_tasks'), ('edge_count', 'schedule_edges'), ('option_count', 'schedule_options')]:
        parent['base']['study'][field] = len(bt[ds])
    declare_crew(parent['result']['study'], ct)
    declare(*args[:2])
    return args


class SetupRules(SimpleTestCase):
    def setUp(self): self.args = three_batches()
    def result(self): return setup.build(*boards(self.args), self.args[2]['base']['tables'])
    def test_hand_counted_initial_cross_and_same_family_events(self):
        d = self.result()
        self.assertEqual(d['state'], 'ready')
        self.assertEqual(len(d['resources']), 3)
        self.assertEqual((d['columns']['due']['initial_tasks'], d['columns']['due']['change_tasks']), (3, 6))
        self.assertEqual((d['columns']['priority']['initial_tasks'], d['columns']['priority']['change_tasks']), (3, 3))
        self.assertEqual((d['columns']['due']['setup_minutes'], d['columns']['priority']['setup_minutes']), (108, 72))
        self.assertEqual(d['summary']['setup_delta_minutes'], -36)
    def test_all_events_include_predecessor_original_family_and_candidate(self):
        d = self.result()
        for event in d['events']:
            self.assertTrue(event['option_id'])
            if event['kind'] == 'initial': self.assertIsNone(event['previous_task_id'])
            else:
                self.assertIsNotNone(event['previous_task_id'])
                self.assertEqual(event['family'] == event['previous_family'], event['kind'] == 'same')
    def test_zero_minute_first_and_cross_events_are_retained(self):
        for option in self.args[2]['base']['tables']['schedule_options']: option['setup_minutes'] = 0
        d = self.result()
        self.assertEqual(d['columns']['due']['change_tasks'], 6)
        self.assertEqual(d['columns']['due']['initial_tasks'], 3)
        self.assertEqual(d['columns']['due']['setup_minutes'], 0)
        self.assertEqual(d['summary']['setup_delta_minutes'], 0)
    def test_fractional_declared_minutes_use_whole_second_ceiling(self):
        for option in self.args[2]['base']['tables']['schedule_options']: option['setup_minutes'] = .001
        d = self.result()
        self.assertEqual({r['setup_seconds'] for r in d['events'] if r['kind'] != 'same'}, {1})
        self.assertEqual(d['columns']['due']['setup_minutes'], 9/60)
    def test_partial_equal_scope_can_compare_preparation_but_not_finish(self):
        self.args[1]['joint_supplies'][1]['qty'] = 0
        d = self.result()
        self.assertTrue(d['summary']['same_scheduled_scope'])
        self.assertIsNotNone(d['summary']['setup_delta_minutes'])
        self.assertIsNone(d['summary']['finish_delta_minutes'])
        self.assertIsNone(d['summary']['late_jobs_delta'])
        self.assertIsNone(d['columns']['due']['finished'])
    def test_different_recipients_same_count_is_not_setup_saving(self):
        args = two_batches()
        d = setup.build(*boards(args), args[2]['base']['tables'])
        self.assertEqual(d['columns']['due']['scheduled_tasks'], d['columns']['priority']['scheduled_tasks'])
        self.assertFalse(d['summary']['same_scheduled_scope'])
        self.assertIsNone(d['summary']['setup_delta_minutes'])
    def test_all_blocked_is_zero_observed_preparation_not_zero_delta(self):
        self.args[1]['joint_supplies'][0]['qty'] = 0
        d = self.result()
        self.assertEqual(d['columns']['due']['setup_minutes'], 0)
        self.assertEqual(d['events'], [])
        self.assertIsNone(d['summary']['setup_delta_minutes'])
        self.assertIsNone(d['columns']['due']['finished'])
    def test_paused_is_unavailable_without_fabricated_zero(self):
        left, right = boards(self.args); right.update(state='paused', summary=None)
        d = setup.build(left, right, {})
        self.assertEqual(d['state'], 'paused'); self.assertEqual(d['columns'], {}); self.assertIsNone(d['summary'])
    def test_job_finish_and_lateness_are_independently_reconciled(self):
        for change in (lambda r: r['jobs'][0].update(finished='2026-10-02T09:00:00'), lambda r: r['jobs'][0].update(lateness_minutes=99), lambda r: r['jobs'][0].update(state='blocked')):
            pair = boards(self.args); change(pair[1])
            with self.assertRaises(ValueError): setup.build(*pair, self.args[2]['base']['tables'])
    def test_invalid_time_setup_number_and_option_fail_closed(self):
        for change in (lambda t: t.update(started=None), lambda t: t.update(setup_minutes=float('nan')), lambda t: t.update(option_id='OTHER'), lambda t: t.update(process_minutes=-1), lambda t: t.update(process_started=t['started'])):
            pair = boards(self.args); change(pair[1]['tasks'][0])
            with self.assertRaises(ValueError): setup.build(*pair, self.args[2]['base']['tables'])
    def test_missing_duplicate_and_unrelated_source_rows_are_rejected(self):
        pair = boards(self.args)
        for edit in (lambda t: t['schedule_tasks'].pop(), lambda t: t['schedule_options'].append(deepcopy(t['schedule_options'][0])), lambda t: t['schedule_jobs'][0].update(family=''), lambda t: t['schedule_options'][0].update(resource_id='OTHER')):
            bt = deepcopy(self.args[2]['base']['tables']); edit(bt)
            with self.assertRaises(ValueError): setup.build(*pair, bt)
    def test_summary_does_not_hide_incomplete_scope(self):
        pair = boards(self.args); pair[1]['summary']['scheduled_tasks'] -= 1
        with self.assertRaises(ValueError): setup.build(*pair, self.args[2]['base']['tables'])
    def test_identity_or_policy_mismatch_is_rejected(self):
        for edit in (lambda r: r.update(policy='due'), lambda r: r['resource_study'].update(version='OTHER'), lambda r: r['tasks'][0].update(route_id='OTHER')):
            pair = [deepcopy(r) for r in boards(self.args)]; edit(pair[1])
            with self.assertRaises(ValueError): setup.build(*pair, self.args[2]['base']['tables'])
    def test_projection_is_pure_order_independent_and_allowlisted(self):
        pair = boards(self.args); bt = deepcopy(self.args[2]['base']['tables']); expected = setup.build(*pair, bt)
        before = deepcopy((pair, bt)); setup.build(*pair, bt); self.assertEqual((pair, bt), before)
        for r in pair:
            for key in ('jobs', 'tasks'): r[key].reverse()
        for rows in bt.values():
            rows.reverse()
            for row in rows: row['private_cost'] = 999
        self.assertEqual(setup.build(*pair, bt), expected)
        self.assertNotIn('private_cost', json.dumps(expected))


class SetupAPI(PlatformCase):
    def setUp(self):
        super().setUp(); study, tables, parent, refs = two_batches()
        self.record('joint_studies', study); self.record('crew_studies', parent['result']['study']); self.record('schedule_studies', parent['base']['study'])
        for ds, rows in {**tables, **parent['tables'], **parent['base']['tables']}.items():
            for row in rows: self.record(ds, row)
        for ds, rows in refs.items():
            for row in rows.values(): self.record(ds, row)
        self.client.force_login(self.admin)
    def call(self, suffix='', body=None, status=200):
        r=self.client.post('/api/joint-comparison/MP1'+suffix,json.dumps(body or {}),content_type='application/json')
        self.assertEqual(r.status_code,status,r.content[:100]);return r.json()
    def test_existing_comparison_exposes_preparation_and_partial_scope(self):
        d = self.call(); self.assertEqual(d['setup_reading']['state'], 'ready')
        self.assertIsNone(d['setup_reading']['summary']['setup_delta_minutes'])
    def test_definition_change_rejects_old_receipt(self):
        d = self.call()
        with patch('app.joint_setup.definition_hash', return_value='NEW'): self.call('/sources', dict(receipt=d['receipt']), 409)
    def test_task_detail_exposes_original_setup_event_or_null(self):
        d = self.call(); key=d['tasks'][0]['id']
        detail = self.call('/tasks/'+key, dict(receipt=d['receipt']))
        for side, policy in [('left', 'due'), ('right', 'priority')]:
            self.assertEqual(detail['setup_reading'][side], next((e for e in d['setup_reading']['events'] if e['policy'] == policy and e['task_id'] == key), None))
    def test_full_exports_rebuild_without_queries_and_keep_csv_sections(self):
        d=self.call(); doc=json.loads(self.call('/export', dict(receipt=d['receipt'],format='json'))['text'])
        with self.assertNumQueries(0): rebuilt=setup.build(doc['left']['result'],doc['right']['result'],doc['left']['resource_inputs'])
        self.assertEqual(rebuilt,d['setup_reading']);self.assertEqual(doc['comparison']['setup_reading'],rebuilt)
        csv=self.call('/export',dict(receipt=d['receipt'],format='csv'))['text']
        self.assertIn('换型准备/events',csv);self.assertIn('换型准备/策略',csv);self.assertIn('两列共同来源',csv)
