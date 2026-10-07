from collections import defaultdict
from copy import deepcopy
from django.test import SimpleTestCase
from app import order_baseline as engine, joint_schedule
from app.order_baseline_contract import bundle_hash, source_hash, signature, issues
from .test_joint_schedule import fixture as joint_fixture


def fixture():
    js, jt, crew, references = joint_fixture()
    parent = dict(result=joint_schedule.analyze(js, jt, crew, references), tables=jt, parent=crew)
    refs = defaultdict(dict, references)
    refs['order_lines'] = {'OL1': dict(id='OL1', order_id='SO1', product_id='P1', qty=10, original_due='2026-09-29', due='2026-09-30')}
    refs['orders'] = {'SO1': dict(id='SO1', order_date='2026-09-20', customer_id='CU1', status='执行中')}
    refs['work_orders'] = {'WO1': dict(id='WO1', product_id='P1', planned_qty=10, bom_version='B1', route_version='V1', status='未开工')}
    refs['allocations'] = {'AL1': dict(id='AL1', work_order_id='WO1', order_line_id='OL1', qty=10, effective='2026-09-21')}
    refs['products']['P1'].update(route_version='V1')
    s = dict(id='OB1', name='订单基线', series='OB-S1', version=1, supersedes_id=None, joint_study_id='MP1', baseline_at='2026-10-01T18:00:00',
             link_count=1, bom_count=3, content_hash='0'*64, owner_id='E1', basis='模拟快照，不是历史批准')
    link = dict(id='OLK1', baseline_id='OB1', job_id='J1', allocation_id='AL1', order_line_id='OL1', order_id='SO1', work_order_id='WO1', product_id='P1', plan_qty=2,
                order_qty=10, allocation_qty=10, work_order_qty=10, original_due='2026-09-29', due='2026-09-30', bom_version='B1', route_version='V1', work_status='未开工',
                allocation_effective='2026-09-21', product_bom_version='B1', product_route_version='V1', bom_count=3, note='SIM')
    for ds, field, key in [('order_lines', 'order_hash', 'OL1'), ('work_orders', 'work_hash', 'WO1'), ('allocations', 'allocation_hash', 'AL1'), ('products', 'product_hash', 'P1')]:
        link[field] = source_hash(ds, refs[ds][key])
    rows = []
    for i, binding in enumerate(jt['joint_bindings'], 1):
        bom = refs['bom'][binding['bom_id']]
        material, route = refs['materials'][bom['material_id']], refs['routes'][binding['route_id']]
        rows.append(dict(id='OBS'+str(i), baseline_id='OB1', link_id='OLK1', source_bom_id=bom['id'], material_id=material['id'], unit=material['unit'], version=bom['version'],
                         branch=bom['assembly_level'], unit_qty=float(bom['qty']), scrap_allowance=float(bom['scrap_allowance']), effective=bom['effective'], quantum=float(binding['quantum']),
                         route_id=route['id'], process=route['process'], route_mandatory=route['mandatory'], bom_hash=source_hash('bom', bom),
                         route_hash=source_hash('routes', route), material_hash=source_hash('materials', material), note='SIM'))
    link['bom_set_hash'] = signature(sorted([engine.frozen_bom(r, link) for r in rows], key=lambda r: r['id']))
    t = dict(order_baseline_links=[link], order_baseline_bom=rows)
    s['content_hash'] = bundle_hash(s, t)
    refs['order_baselines']['OB1'] = s
    return s, t, parent, refs, '2026-10-01T18:00:00'


class OrderBaselineTests(SimpleTestCase):
    def setUp(self):
        self.args = list(fixture())

    def result(self, reseal=True):
        if reseal:
            self.args[0]['content_hash'] = bundle_hash(*self.args[:2])
        return engine.analyze(*self.args)

    def test_complete_trial_does_not_mean_order_covered_or_on_time(self):
        r = self.result()
        self.assertEqual(r['state'], 'aligned', (r['issues'], r['warnings']))
        self.assertEqual(r['summary']['scheduled_jobs'], 1)
        self.assertEqual(r['summary']['planned_qty'], 2)
        self.assertEqual(r['summary']['order_qty'], 10)
        self.assertEqual(r['summary']['uncovered_qty'], 8)
        self.assertEqual(r['summary']['fully_covered_lines'], 0)
        self.assertEqual(r['summary']['customer_late_jobs'], 1)
        self.assertIsNone(r['orders'][0]['order_finish'])
        self.assertEqual(r['orders'][0]['mapped_jobs_finish'], '2026-10-02T08:55:00')

    def test_current_bom_edits_do_not_recalculate_frozen_need(self):
        before = self.result()
        self.args[3]['bom']['B1']['qty'] = 999
        after = self.result()
        self.assertEqual(after['state'], 'review')
        self.assertEqual(after['bom'][0]['required_qty'], before['bom'][0]['required_qty'])
        self.assertEqual(after['bom'][0]['required_qty'], '3')
        self.assertTrue(any(c['dataset'] == 'bom' for c in after['changes']))

    def test_current_product_new_version_does_not_replace_workorder_baseline(self):
        self.args[3]['products']['P1']['bom_version'] = 'B2'
        r = self.result()
        self.assertEqual(r['state'], 'review')
        self.assertEqual(r['links'][0]['bom_version'], 'B1')
        self.assertEqual(r['bom'][0]['required_qty'], '3')

    def test_changed_snapshot_without_new_hash_pauses(self):
        self.args[1]['order_baseline_bom'][0]['unit_qty'] = 2
        r = self.result(False)
        self.assertEqual(r['state'], 'paused')
        self.assertIsNone(r['summary'])
        self.assertIn('基线内容摘要不符；不能把局部变更视为原冻结版本', r['issues'])

    def test_resealed_but_internally_inconsistent_source_hash_pauses(self):
        self.args[1]['order_baseline_links'][0]['order_qty'] = 20
        r = self.result()
        self.assertEqual(r['state'], 'paused')
        self.assertTrue(any('快照字段与声明来源摘要不符' in i for i in r['issues']))

    def test_missing_and_extra_bom_lines_are_detected(self):
        self.args[1]['order_baseline_bom'].pop()
        self.assertEqual(self.result()['state'], 'paused')
        self.args = list(fixture())
        self.args[3]['bom']['B4'] = {**self.args[3]['bom']['B1'], 'id': 'B4'}
        r = self.result()
        self.assertEqual(r['state'], 'review')
        self.assertTrue(any('BOM集合' in w for w in r['warnings']))
        self.assertEqual(len(r['bom']), 3)

    def test_job_quantity_or_missing_mapping_pauses(self):
        self.args[1]['order_baseline_links'][0]['plan_qty'] = 3
        self.assertEqual(self.result()['state'], 'paused')
        self.args = list(fixture())
        self.args[1]['order_baseline_links'].clear()
        self.assertEqual(self.result()['state'], 'paused')

    def test_trial_demand_and_snapshot_are_separate(self):
        self.args[2]['tables']['joint_demands'][0]['required_qty'] = 4
        r = self.result()
        self.assertEqual(r['state'], 'review')
        self.assertEqual(r['summary']['mismatched_bom_rows'], 1)
        self.assertEqual(r['bom'][0]['required_qty'], '3')
        self.assertEqual(r['bom'][0]['trial_demands'][0]['qty'], 4)

    def test_parent_pause_keeps_frozen_requirements_without_delivery_claim(self):
        self.args[2]['result'].update(state='paused', issues=['缺工序'], jobs=[], summary=None)
        r = self.result()
        self.assertEqual(r['state'], 'review')
        self.assertEqual(len(r['bom']), 3)
        self.assertIsNone(r['orders'][0]['mapped_jobs_finish'])
        self.assertEqual(r['summary']['customer_late_jobs'], 0)

    def test_orders_deduplicated_across_jobs_and_total_not_overbooked(self):
        s, t, parent, refs, _ = self.args
        raw = parent['parent']['base']['tables']
        raw['schedule_jobs'].append({**raw['schedule_jobs'][0], 'id': 'J2'})
        raw['schedule_tasks'].extend([{**r, 'id': r['id']+'-2', 'job_id': 'J2'} for r in list(raw['schedule_tasks'])])
        t['order_baseline_links'].append({**t['order_baseline_links'][0], 'id': 'OLK2', 'job_id': 'J2'})
        t['order_baseline_bom'].extend([{**r, 'id': r['id']+'-2', 'link_id': 'OLK2'} for r in list(t['order_baseline_bom'])])
        s.update(link_count=2, bom_count=6)
        r = self.result()
        self.assertEqual(r['summary']['order_qty'], 10)
        self.assertEqual(r['summary']['planned_qty'], 4)
        self.assertEqual(r['summary']['uncovered_qty'], 6)
        raw['schedule_jobs'][1]['qty'] = 10
        t['order_baseline_links'][1]['plan_qty'] = 10
        r = self.result()
        self.assertEqual(r['state'], 'paused')
        self.assertTrue(any('累计超过' in v for v in r['issues']))

    def test_registered_shipments_count_once_at_baseline_including_boundary(self):
        self.args[3]['shipments'] = {'SH1': dict(id='SH1', order_line_id='OL1', qty=8, shipped='2026-10-01T18:00:00'), 'SH2': dict(id='SH2', order_line_id='OL1', qty=99, shipped='2026-10-01T18:00:01')}
        r = self.result()
        self.assertEqual(r['orders'][0]['registered_shipped_qty'], 8)
        self.assertEqual(r['orders'][0]['baseline_open_qty'], 2)
        self.assertTrue(r['orders'][0]['fully_covered'])
        self.assertEqual(r['orders'][0]['order_finish'], '2026-10-02T08:55:00')

    def test_overplanned_shipped_order_is_not_healthy_coverage(self):
        self.args[3]['shipments']['SH1'] = dict(id='SH1', order_line_id='OL1', qty=10, shipped='2026-10-01T17:00:00')
        r = self.result()
        self.assertEqual(r['state'], 'review')
        self.assertEqual(r['orders'][0]['overplanned_qty'], 2)
        self.assertIsNone(r['orders'][0]['coverage_percent'])
        self.assertFalse(r['orders'][0]['fully_covered'])

    def test_wip_or_other_allocation_requires_review(self):
        self.args[3]['operations']['OP1'] = dict(id='OP1', work_order_id='WO1', started='2026-09-30T08:00:00')
        self.assertEqual(self.result()['state'], 'review')
        self.args = list(fixture())
        self.args[3]['allocations']['AL2'] = dict(id='AL2', work_order_id='WO1', order_line_id='OTHER', qty=1, effective='2026-09-21')
        self.assertEqual(self.result()['state'], 'review')

    def test_bad_history_time_does_not_disappear_as_zero(self):
        self.args[3]['shipments']['SH1'] = dict(id='SH1', order_line_id='OL1', qty=2, shipped='not-a-time')
        r = self.result()
        self.assertEqual(r['state'], 'paused')
        self.assertIsNone(r['summary'])

    def test_cancelled_order_requires_review_without_erasing_baseline(self):
        self.args[3]['orders']['SO1']['status'] = '已取消'
        r = self.result()
        self.assertEqual(r['state'], 'review')
        self.assertEqual(r['summary']['order_qty'], 10)
        self.assertTrue(any('取消' in w for w in r['warnings']))

    def test_full_quantity_with_changed_basis_does_not_claim_order_completion(self):
        self.args[3]['shipments']['SH1'] = dict(id='SH1', order_line_id='OL1', qty=8, shipped='2026-10-01T17:00:00')
        self.args[3]['bom']['B1']['qty'] = 999
        r = self.result()
        self.assertTrue(r['orders'][0]['fully_covered'])
        self.assertEqual(r['orders'][0]['mapped_jobs_finish'], '2026-10-02T08:55:00')
        self.assertEqual(r['state'], 'review')
        self.assertIsNone(r['orders'][0]['order_finish'])

    def test_revision_chain_valid_missing_and_duplicate(self):
        s, _, _, refs, _ = self.args
        refs['order_baselines']['OB0'] = {**s, 'id': 'OB0'}
        s.update(version=2, supersedes_id='OB0')
        self.assertEqual(self.result()['state'], 'aligned')
        refs['order_baselines']['OB0']['version'] = 2
        self.assertEqual(self.result()['state'], 'paused')
        refs['order_baselines'].pop('OB0')
        self.assertEqual(self.result()['state'], 'paused')

    def test_future_baseline_and_effective_dates_pause(self):
        self.args[0]['baseline_at'] = '2026-10-02T08:00:00'
        self.assertEqual(self.result()['state'], 'paused')
        self.args = list(fixture())
        self.args[1]['order_baseline_bom'][0]['effective'] = '2026-10-02'
        self.assertEqual(self.result()['state'], 'paused')

    def test_contract_numbers_and_canonical_excel_float(self):
        self.assertTrue(issues('order_baselines', dict(version=0)))
        self.assertTrue(issues('order_baseline_links', dict(plan_qty=True)))
        self.assertTrue(issues('order_baseline_bom', dict(unit_qty=float('nan'))))
        self.assertTrue(issues('order_baseline_links', dict(order_hash='bad')))
        self.assertEqual(signature(dict(qty=1)), signature(dict(qty=1.0)))

    def test_readonly_deterministic_no_financial_values(self):
        before = deepcopy(self.args)
        self.assertEqual(self.result(), self.result())
        self.assertEqual(self.args, before)
        self.args[3]['order_lines']['OL1']['unit_price_cents'] = 999
        self.args[3]['materials']['M1']['unit_cost_cents'] = 888
        self.assertEqual(self.result()['state'], 'aligned')
