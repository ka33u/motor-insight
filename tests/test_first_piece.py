import copy
import csv
import io
from unittest.mock import patch
from django.test import SimpleTestCase
from django.contrib.auth.models import User, Group
from django.db import IntegrityError
from app import first_piece as engine, analytics
from app.models import Record, AuditEvent, AccountAccessState
from app.ingestion import fingerprint
from .test_platform import PlatformCase
from .test_process_quality import fixture as quality_fixture


def fixture():
    d = quality_fixture()
    clock = '2026-09-21T08:11:00'
    common = dict(version=1, previous_id=None, status='已登记', registered='2026-09-01T08:01:00')
    d['metrology_instruments'] = [dict(id='I1', stage='process', parameter='BURR', unit='mm', active_from='2026-01-01T00:00:00', retired=None)]
    d['metrology_rules'] = [dict(common, id='MR1', series='RULE1', stage='process', parameter='BURR', unit='mm', required=True, effective='2026-01-01T00:00:00', expires=None)]
    d['metrology_uses'] = [dict(common, id='MU1', series='USE1', stage='process', measurement_id=None, incoming_reading_id=None, process_reading_id='V1', instrument_id='I1', measured=clock, registered='2026-09-21T08:12:00')]
    d['metrology_calibrations'] = [dict(common, id='MC1', series='CAL1', instrument_id='I1', performed='2026-09-01T08:00:00', valid_from='2026-09-01T08:00:00', valid_until='2026-10-01T00:00:00', result='符合登记范围', parameter='BURR', unit='mm', certificate_no='SIM1', reference='合成登记')]
    return d


class FirstPieceTests(SimpleTestCase):
    def setUp(self):
        self.d = fixture()

    def result(self):
        return engine.analyze(self.d, analytics.AS_OF)

    def row(self):
        return self.result()['rows'][0]

    def test_read_only_evidence_ready_is_not_approval(self):
        before = copy.deepcopy(self.d)
        r = self.row()
        self.assertEqual((r['evidence_state'], r['measured_items']), ('ready', 1))
        self.assertIn('未提供', r['approval'])
        self.assertEqual(self.d, before)

    def test_patrol_does_not_count_as_first_piece(self):
        self.d['process_check_plans'][0]['stage'] = '巡检'
        self.assertEqual(self.result()['summary']['plans'], 0)

    def test_all_voided_is_pending(self):
        self.d['process_checks'][0]['voided'] = True
        self.assertEqual(self.row()['evidence_state'], 'waiting')

    def test_future_only_is_pending_without_future_measurements(self):
        self.d['process_checks'][0]['checked'] = '2026-10-02T08:00:00'
        r = self.row()
        self.assertEqual((r['evidence_state'], r['measured_items'], r['future_checks']), ('waiting', 0, 1))

    def test_future_due_remains_future(self):
        self.d['process_checks'] = []
        self.d['process_check_plans'][0]['due'] = '2026-10-02T08:00:00'
        self.assertEqual(self.row()['evidence_state'], 'future')

    def test_latest_incomplete_never_reuses_prior_pass(self):
        self.d['process_checks'].append(dict(self.d['process_checks'][0], id='C2', checked='2026-09-21T08:20:00'))
        r = self.row()
        self.assertEqual((r['evidence_state'], r['latest_id'], r['latest_missing']), ('missing', 'C2', 1))

    def test_outside_limits_has_priority_over_meter_problem(self):
        self.d['process_readings'][0]['value'] = .06
        self.d['metrology_uses'] = []
        r = self.row()
        self.assertEqual((r['evidence_state'], r['latest_out'], r['meter_attention']), ('out', 1, 1))

    def test_tied_execution_invalid_even_if_numerically_good(self):
        self.d['process_checks'].append(dict(self.d['process_checks'][0], id='C2'))
        self.assertEqual(self.row()['evidence_state'], 'attention')

    def test_wrong_spec_unit_and_work_order_each_block(self):
        for ds, field, value in [('process_readings', 'unit', 'cm'), ('batches', 'work_order_id', 'OTHER'), ('work_orders', 'route_version', 'R2')]:
            self.d = fixture()
            self.d[ds][0][field] = value
            self.assertEqual(self.row()['evidence_state'], 'attention')

    def test_missing_usage_and_expired_calibration(self):
        self.d['metrology_uses'] = []
        self.assertEqual(self.row()['evidence_state'], 'metrology')
        self.d = fixture()
        self.d['metrology_calibrations'][0]['valid_until'] = '2026-09-21T08:11:00'
        r = self.result()['details']['PQC1']['measures'][0]
        self.assertEqual(r['metrology']['calibration_state'], 'expired')

    def test_latest_withdrawn_calibration_never_falls_back(self):
        old = self.d['metrology_calibrations'][0]
        self.d['metrology_calibrations'].append(dict(old, id='MC2', previous_id='MC1', version=2, status='撤销', registered='2026-09-25T00:00:00'))
        self.assertEqual(self.row()['evidence_state'], 'metrology')

    def test_known_impact_blocks_even_with_valid_calibration(self):
        self.d['metrology_notices'] = [dict(id='N1', series='N1', version=1, previous_id=None, status='已登记', instrument_id='I1', calibration_id='MC1', discovered='2026-09-24T08:00:00', lower_mode='明确起点', impact_from='2026-09-21T08:00:00', impact_until='2026-09-22T08:00:00', registered='2026-09-24T09:00:00')]
        self.assertEqual(self.row()['evidence_state'], 'metrology')

    def test_candidates_require_same_work_order_route_and_branch(self):
        study = dict(id='L1', name='模拟')
        self.d['launch_clearances'] = [dict(id='LC1', study_id='L1', work_order_id='W1', route_id='R01', status='具备登记条件')]
        def target():
            return engine.targets(self.d, self.result(), study, analytics.AS_OF)['rows'][0]
        self.assertEqual(target()['state'], 'candidates')
        self.assertIn('未确认覆盖或批准', target()['reason'])
        self.d['work_orders'].append(dict(id='W2', product_id='P1', route_version='R1'))
        self.d['launch_clearances'][0]['work_order_id'] = 'W2'
        self.assertEqual(target()['state'], 'missing')
        self.d['work_orders'][-1]['route_version'] = 'R2'
        self.assertEqual(target()['state'], 'attention')

    def test_summary_is_exclusive_but_keeps_overlapping_problems(self):
        r = self.result()
        self.assertEqual(sum(r['summary'][s] for s in engine.STATES), r['summary']['plans'])


class FirstPieceAPITests(PlatformCase):
    def setUp(self):
        super().setUp()
        for ds, rows in fixture().items():
            for row in rows:
                self.record(ds, row)
        self.record('launch_studies', dict(id='L1', name='模拟'))
        self.record('launch_clearances', dict(id='LC1', study_id='L1', work_order_id='W1', route_id='R01', status='具备登记条件'))
        self.client.force_login(self.admin)

    def board(self, **kw):
        return self.client.get('/api/first-piece', kw)

    def export(self, d=None, **kw):
        return self.client.get('/api/first-piece/export', dict(receipt=(d or self.board().json())['receipt'], format='json', **kw))

    def change(self, ds, key, **changes):
        r = Record.objects.get(dataset=ds, business_key=key)
        r.values.update(changes)
        r.record_hash = fingerprint(r.values)
        r.revision += 1
        r.save()
        row = r.source_row
        row.normalized = r.values
        row.record_hash = r.record_hash
        row.save()

    def test_six_roles_and_target_separation(self):
        self.client.logout()
        self.assertEqual(self.board().status_code, 401)
        for role in ('admin', 'analyst', 'operations', 'quality', 'finance', 'viewer'):
            user = User.objects.filter(username=role).first() or User.objects.create_user(role)
            user.groups.add(Group.objects.get_or_create(name=role)[0])
            self.client.force_login(user)
            r = self.board()
            self.assertEqual(r.status_code, 200)
            self.assertEqual(self.board(study='L1').status_code, 200 if role in ('admin', 'analyst', 'operations') else 403)
            self.assertNotIn('cents', self.export(r.json()).content.decode())

    def test_detail_and_export_match_without_business_mutation(self):
        before = list(Record.objects.order_by('dataset', 'business_key').values_list('record_hash', flat=True))
        d = self.board().json()
        self.assertEqual(d['summary']['ready'], 1)
        r = self.client.get('/api/first-piece/PQC1', dict(receipt=d['receipt']))
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()['sources'])
        self.assertEqual(self.export(d).json()['summary'], d['summary'])
        self.assertEqual(self.export(d)['Cache-Control'], 'no-store')
        self.assertEqual(AuditEvent.objects.latest('id').action, 'first_piece.export')
        self.assertEqual(before, list(Record.objects.order_by('dataset', 'business_key').values_list('record_hash', flat=True)))

    def test_changed_data_invalidates_receipt(self):
        d = self.board().json()
        self.change('process_readings', 'V1', value=.06)
        self.assertEqual(self.export(d).status_code, 409)
        self.assertEqual(self.board().json()['summary']['out'], 1)

    def test_changed_filter_account_rule_or_expiry_invalidates(self):
        d = self.board().json()
        self.assertEqual(self.export(d, state='ready').status_code, 409)
        AccountAccessState.objects.create(user=self.admin, revision=1)
        self.assertEqual(self.export(d).status_code, 409)
        d = self.board().json()
        with patch('app.first_piece.rule_hash', return_value='changed'):
            self.assertEqual(self.export(d).status_code, 409)
        with patch('django.core.signing.time.time', return_value=0):
            old = self.board().json()
        self.assertEqual(self.export(old).status_code, 409)

    def test_use_series_changed_identity_is_not_hidden_by_scope(self):
        row = fixture()['metrology_uses'][0]
        self.record('metrology_uses', dict(row, id='MU2', version=2, previous_id='MU1', process_reading_id=None, measurement_id='OTHER', stage='test', registered='2026-09-25T00:00:00'))
        self.assertEqual(self.board().json()['summary']['metrology'], 1)

    def test_corrupt_provenance_is_rejected(self):
        source = Record.objects.get(dataset='process_readings', business_key='V1').source_row
        source.normalized = dict(id='OTHER')
        source.save()
        self.assertEqual(self.board().status_code, 400)

    def test_strict_queries_no_unbound_export_or_out_of_scope_detail(self):
        self.assertEqual(self.client.post('/api/first-piece').status_code, 405)
        self.assertEqual(self.client.get('/api/first-piece/export').status_code, 400)
        for q in ('?page=0', '?page=１００', '?state=bad', '?q=a&q=b', '?unknown=1'):
            self.assertEqual(self.client.get('/api/first-piece'+q).status_code, 400)
        d = self.board(state='waiting').json()
        self.assertEqual(self.client.get('/api/first-piece/PQC1', dict(state='waiting', receipt=d['receipt'])).status_code, 404)

    def test_csv_escaping_and_export_audit_atomicity(self):
        for ds, key in [('operations', 'OP1'), ('routes', 'R01'), ('equipment', 'EQ1'), ('process_specs', 'S1')]:
            self.change(ds, key, process='=1+1')
        d = self.board().json()
        r = self.client.get('/api/first-piece/export', dict(format='csv', receipt=d['receipt']))
        self.assertEqual(r.status_code, 200)
        self.assertIn('首件证据工作台', r.content.decode('utf-8-sig'))
        rows = list(csv.reader(io.StringIO(r.content.decode('utf-8-sig'))))
        self.assertIn("'=1+1", rows[-1])
        before = AuditEvent.objects.count()
        with patch('app.first_piece_views.AuditEvent.objects.create', side_effect=IntegrityError):
            self.assertEqual(self.export().status_code, 409)
        self.assertEqual(AuditEvent.objects.count(), before)
