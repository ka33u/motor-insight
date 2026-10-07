from copy import deepcopy
from decimal import Decimal
from django.test import SimpleTestCase
from app import joint_schedule as engine, crew_schedule, finite_schedule
from app.joint_schedule_contract import issues
from .test_crew_schedule import fixture as crew_fixture, declare as declare_crew


def fixture():
    cs, ct, base, refs = crew_fixture()
    declare_crew(cs, ct)
    refs['products']['P1']['bom_version'] = 'B1'
    refs['materials'] = {'M1': dict(id='M1', name='硅钢', unit='kg'), 'M2': dict(id='M2', name='轴承', unit='件')}
    refs['bom'] = {k: dict(id=k, product_id='P1', material_id=m, version='B1', qty=q, scrap_allowance=0, effective='2026-01-01', assembly_level=branch)
                   for k, m, q, branch in [('B1', 'M1', 1.5, '定子'), ('B2', 'M1', 1, '转子'), ('B3', 'M2', 1, '装配件包')]}
    parent = dict(result=crew_schedule.analyze(cs, ct, base, refs), tables=ct, base=base)
    s = dict(id='MP1', name='物料联立', crew_study_id='CR1', version='V1', owner_id='E1', scope='SIM', assumptions='合成整批预留', reference='SIM')
    t = dict(joint_bindings=[dict(id='K'+str(i), study_id='MP1', bom_id=b, route_id=r, quantum=q, basis='SIM') for i, b, r, q in [(1, 'B1', 'A', .001), (2, 'B2', 'B', .001), (3, 'B3', 'C', 1)]],
             joint_demands=[dict(id='D'+str(i), study_id='MP1', job_id='J1', binding_id='K'+str(i), required_qty=q, unit=u, basis='SIM') for i, q, u in [(1, 3, 'kg'), (2, 2, 'kg'), (3, 2, '件')]],
             joint_supplies=[dict(id=k, study_id='MP1', material_id=m, lot='SIM-'+k, unit=u, qty=q, unavailable_qty=0, available_from='2026-10-02T08:00:00', status='可预留', kind='期初假设', reference='SIM', basis='SIM') for k, m, u, q in [('L1', 'M1', 'kg', 5), ('L2', 'M2', '件', 2)]])
    declare(s, t)
    return s, t, parent, refs


def declare(s, t):
    for field, ds in [('binding_count', 'joint_bindings'), ('demand_count', 'joint_demands'), ('supply_count', 'joint_supplies')]:
        s[field] = len(t[ds])


class JointScheduleTests(SimpleTestCase):
    def setUp(self):
        self.args = list(fixture())

    def result(self):
        declare(*self.args[:2])
        return engine.analyze(*self.args)

    def test_hand_oracle_and_whole_batch_reserved_once(self):
        r = self.result()
        self.assertEqual(r['state'], 'trial', r['issues'])
        self.assertEqual(r['jobs'][0]['finished'], '2026-10-02T08:55:00')
        self.assertEqual(r['summary']['qty'], 2)
        self.assertEqual(r['summary']['reserved_demands'], 3)
        self.assertEqual(len(r['reservations']), 3)
        self.assertEqual(r['tasks'][-1]['new_reservation_ids'], [])
        self.assertEqual(r['lots'][0]['remaining_qty'], '0')

    def test_shared_material_cannot_be_reserved_twice_and_propagates(self):
        self.args[1]['joint_supplies'][0]['qty'] = 4
        r = self.result()
        self.assertEqual(r['summary']['scheduled_tasks'], 1)
        self.assertEqual(r['summary']['blocked_tasks'], 3)
        self.assertEqual(r['tasks'][1]['shortages'][0]['shortage_qty'], '1')
        self.assertEqual(r['tasks'][-1]['root_tasks'], ['TB'])
        self.assertIsNone(r['jobs'][0]['finished'])
        self.assertEqual(r['lots'][0]['reserved_qty'], '3')

    def test_future_arrival_recomputes_dependencies_workers_and_setup(self):
        self.args[1]['joint_supplies'][0].update(kind='未来到料假设', available_from='2026-10-02T09:00:00')
        r = self.result()
        self.assertEqual(r['tasks'][0]['started'], '2026-10-02T09:00:00')
        self.assertEqual(r['jobs'][0]['finished'], '2026-10-02T09:55:00')
        self.assertEqual(r['jobs'][0]['completion_delta_minutes'], 60)
        self.assertEqual(r['tasks'][0]['material_readiness_delay_minutes'], 60)
        self.assertEqual(r['reservations'][0]['reserved_at'], '2026-10-02T09:00:00')

    def test_fifo_split_and_conservation(self):
        lots = self.args[1]['joint_supplies']
        lots[0]['qty'] = 1
        lots.append({**lots[0], 'id': 'L0', 'qty': 2})
        lots.append({**lots[0], 'id': 'L3', 'qty': 2, 'kind': '未来到料假设', 'available_from': '2026-10-02T09:00:00'})
        r = self.result()
        self.assertEqual([a['supply_id'] for a in r['reservations'][:2]], ['L0', 'L1'])
        for lot in r['lots']:
            self.assertEqual(Decimal(lot['usable_qty']), Decimal(lot['reserved_qty'])+Decimal(lot['remaining_qty']))
        self.assertEqual(r['tasks'][1]['started'], '2026-10-02T09:00:00')

    def test_isolated_and_unavailable_not_usable(self):
        self.args[1]['joint_supplies'][0].update(status='隔离', unavailable_qty=1)
        r = self.result()
        self.assertEqual(r['lots'][0]['excluded_qty'], '5')
        self.assertEqual(r['lots'][0]['usable_qty'], '0')
        self.assertEqual(r['summary']['scheduled_tasks'], 0)
        self.args[1]['joint_supplies'][0].update(status='可预留', unavailable_qty=1)
        self.assertEqual(self.result()['summary']['scheduled_tasks'], 1)

    def test_no_joint_window_does_not_consume_material(self):
        self.args[2]['tables']['crew_windows'] = []
        # Parent reference is retained as a comparison; the new schedule reads windows.
        r = self.result()
        self.assertEqual(r['summary']['scheduled_tasks'], 0)
        self.assertEqual(r['reservations'], [])
        self.assertEqual(r['lots'][0]['remaining_qty'], '5')

    def test_late_supply_beyond_horizon_not_available(self):
        self.args[1]['joint_supplies'][0].update(kind='未来到料假设', available_from='2026-10-02T12:00:00')
        r = self.result()
        self.assertEqual(r['summary']['scheduled_tasks'], 0)
        self.assertEqual(r['balances'][0]['horizon_usable_qty'], '0')
        self.assertEqual(r['balances'][0]['total_remaining_qty'], '5')

    def test_partial_job_reservations_are_kept_and_not_claimed_complete(self):
        self.args[1]['joint_supplies'][1]['qty'] = 1
        r = self.result()
        self.assertEqual(r['summary']['scheduled_tasks'], 2)
        self.assertEqual(r['summary']['blocked_jobs'], 1)
        self.assertEqual(r['summary']['reserved_demands'], 2)
        self.assertEqual(r['lots'][0]['reserved_qty'], '5')

    def test_missing_binding_or_demand_pauses_whole_trial(self):
        for ds in ('joint_bindings', 'joint_demands'):
            self.args = list(fixture())
            self.args[1][ds].pop()
            r = self.result()
            self.assertEqual(r['state'], 'paused')
            self.assertIsNone(r['summary'])
            self.assertEqual(r['tasks'], [])

    def test_declared_inputs_cannot_shrink(self):
        self.args[1]['joint_supplies'].pop()
        self.assertEqual(engine.analyze(*self.args)['state'], 'paused')

    def test_units_wrong_qty_and_cross_scope_pause(self):
        for ds, field, value in [('joint_demands', 'unit', '件'), ('joint_supplies', 'unit', '件'), ('joint_demands', 'required_qty', 2.999), ('joint_bindings', 'route_id', 'B'), ('joint_supplies', 'study_id', 'OTHER')]:
            self.args = list(fixture())
            self.args[1][ds][0][field] = value
            self.assertEqual(self.result()['state'], 'paused', (ds, field))

    def test_decimal_ceiling_not_binary_rounding(self):
        self.assertEqual(engine.requirement(6, 1, .015, 1), Decimal(7))
        self.assertEqual(engine.requirement(10, .1, 0, .001), Decimal(1))
        self.assertEqual(engine.requirement(6, 8.97, .035, .001), Decimal('55.704'))
        self.args[3]['bom']['B3']['scrap_allowance'] = .015
        self.args[1]['joint_demands'][2]['required_qty'] = 3
        self.assertEqual(self.result()['demands'][2]['calculated_qty'], '3')

    def test_current_bom_version_and_effective_date(self):
        self.args[3]['bom']['B1']['effective'] = '2026-10-03'
        self.assertEqual(self.result()['state'], 'paused')
        self.args = list(fixture())
        self.args[3]['products']['P1']['bom_version'] = 'ABSENT'
        self.assertEqual(self.result()['state'], 'paused')

    def test_duplicate_binding_or_need_does_not_double_count(self):
        for ds in ('joint_bindings', 'joint_demands'):
            self.args = list(fixture())
            self.args[1][ds].append({**self.args[1][ds][0], 'id': 'DUP'})
            self.assertEqual(self.result()['state'], 'paused')

    def test_mixed_unit_balances_are_separate(self):
        self.assertEqual([(v['unit'], v['required_qty']) for v in self.result()['balances']], [('kg', '5'), ('件', '2')])

    def test_deterministic_and_no_source_mutation(self):
        before = deepcopy(self.args)
        self.assertEqual(self.result(), self.result())
        self.assertEqual(before, self.args)

    def test_invalid_source_quantities_and_timestamps(self):
        for v in (True, float('nan'), float('inf'), -1):
            self.assertTrue(issues('joint_supplies', dict(qty=v)))
        self.assertTrue(issues('joint_demands', dict(required_qty=0)))
        self.assertTrue(issues('joint_bindings', dict(quantum=0)))
        self.assertTrue(issues('joint_supplies', dict(qty=1, unavailable_qty=2)))
        self.assertTrue(issues('joint_supplies', dict(available_from='2026-10-02T08:00:00Z')))

    def test_parent_pause_preserves_no_fabricated_zero(self):
        self.args[2]['result'].update(state='paused', issues=['资格缺失'], summary=None)
        r = self.result()
        self.assertEqual(r['state'], 'paused')
        self.assertIn('人员资源方案：资格缺失', r['issues'])
        self.assertIsNone(r['summary'])

    def test_other_portion_cannot_start_before_existing_batch_reservation(self):
        parent, refs = self.args[2:]
        base, ct = parent['base'], parent['tables']
        bt = base['tables']
        refs['production_resources']['R4'] = {**refs['production_resources']['R3'], 'id': 'R4', 'station': 'R4'}
        bt['schedule_windows'].append({**bt['schedule_windows'][-1], 'id': 'WR4', 'resource_id': 'R4'})
        next(w for w in bt['schedule_windows'] if w['resource_id'] == 'R3')['started'] = '2026-10-02T09:00:00'
        next(o for o in bt['schedule_options'] if o['task_id'] == 'TC2')['resource_id'] = 'R4'
        refs['employees']['E4'] = dict(id='E4', name='E4', active=True)
        refs['skills']['S4'] = {**refs['skills']['S3'], 'id': 'S4', 'employee_id': 'E4'}
        ct['crew_credentials'].append({**ct['crew_credentials'][-1], 'id': 'CS4', 'skill_id': 'S4'})
        ct['crew_windows'].append({**ct['crew_windows'][-1], 'id': 'WE4', 'employee_id': 'E4'})
        next(c for c in ct['crew_candidates'] if c['task_id'] == 'TC2')['credential_id'] = 'CS4'
        base['study']['window_count'] += 1
        base['result'] = finite_schedule.analyze(base['study'], bt, refs)
        cs = parent['result']['study']
        declare_crew(cs, ct)
        parent['result'] = crew_schedule.analyze(cs, ct, base, refs)
        original = {t['id']: t for t in parent['result']['tasks']}
        self.assertEqual(original['TC2']['started'], '2026-10-02T08:30:00')
        r = self.result()
        rows = {t['id']: t for t in r['tasks']}
        self.assertEqual(rows['TC1']['started'], '2026-10-02T09:00:00')
        self.assertEqual(rows['TC2']['started'], '2026-10-02T09:00:00')
        self.assertEqual(rows['TC2']['new_reservation_ids'], [])
        self.assertEqual(len([a for a in r['reservations'] if a['demand_id'] == 'D3']), 1)

    def test_two_jobs_compete_for_same_pool_and_priority_changes_recipient(self):
        parent, refs = self.args[2:]
        base, ct = parent['base'], parent['tables']
        bt = base['tables']
        bt['schedule_jobs'][0]['priority'] = 2
        bt['schedule_jobs'].append({**bt['schedule_jobs'][0], 'id': 'J2', 'priority': 1, 'due': '2026-10-02T11:00:00'})
        for ds in ('schedule_tasks', 'schedule_edges', 'schedule_options'):
            added = []
            for old in bt[ds]:
                row = {**old, 'id': old['id']+'-2'}
                if ds == 'schedule_tasks':
                    row['job_id'] = 'J2'
                if ds == 'schedule_edges':
                    row['from_task_id'] += '-2'
                    row['to_task_id'] += '-2'
                if ds == 'schedule_options':
                    row['task_id'] += '-2'
                added.append(row)
            bt[ds].extend(added)
        ct['crew_candidates'].extend([{**c, 'id': c['id']+'-2', 'task_id': c['task_id']+'-2'} for c in list(ct['crew_candidates'])])
        self.args[1]['joint_demands'].extend([{**d, 'id': d['id']+'-2', 'job_id': 'J2'} for d in list(self.args[1]['joint_demands'])])
        for field, ds in [('job_count', 'schedule_jobs'), ('task_count', 'schedule_tasks'), ('edge_count', 'schedule_edges'), ('option_count', 'schedule_options')]:
            base['study'][field] = len(bt[ds])
        cs = parent['result']['study']
        declare_crew(cs, ct)
        for policy, winner in [('due', 'J1'), ('priority', 'J2')]:
            base['result'] = finite_schedule.analyze(base['study'], bt, refs, policy)
            parent['result'] = crew_schedule.analyze(cs, ct, base, refs)
            r = self.result()
            self.assertEqual(r['state'], 'trial', r['issues'])
            self.assertEqual(r['summary']['jobs'], 2)
            self.assertEqual(r['summary']['qty'], 4)
            self.assertEqual(r['summary']['complete_jobs'], 1)
            self.assertEqual({a['job_id'] for a in r['reservations']}, {winner})
