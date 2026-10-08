import csv
import hashlib
import io
import json
from collections import defaultdict
from unittest.mock import patch

from django.contrib.auth.models import Group, User
from django.db import IntegrityError
from django.test import Client

from app import baseline_trial, crew_schedule, finite_schedule, joint_schedule, order_baseline
from app.ingestion import fingerprint
from app.models import AccountAccessState, AuditEvent, ImportBatch, ImportRow, Record
from app.order_baseline_contract import bundle_hash
from .test_order_baseline import fixture
from .test_platform import PlatformCase


class BaselineTrialAPITests(PlatformCase):
    def setUp(self):
        super().setUp()
        study, tables, joint, refs, _ = fixture()
        crew, base = joint['parent'], joint['parent']['base']
        for dataset, row in [('order_baselines', study), ('joint_studies', joint['result']['study']),
                             ('crew_studies', crew['result']['study']), ('schedule_studies', base['study'])]:
            self.record(dataset, row)
        for dataset, rows in {**tables, **joint['tables'], **crew['tables'], **base['tables']}.items():
            for row in rows:
                self.record(dataset, row)
        for dataset, rows in refs.items():
            if dataset != 'order_baselines':
                for row in rows.values():
                    self.record(dataset, row)
        self.client.force_login(self.admin)

    def call(self, suffix='', value=None, status=200, key='OB1'):
        response = self.client.post('/api/baseline-trial/'+key+suffix,
                                    json.dumps({} if value is None else value), content_type='application/json')
        self.assertEqual(response.status_code, status, response.content[:600])
        if status == 200:
            self.assertEqual(response['Cache-Control'], 'no-store')
        return response

    def board(self, policy='due'):
        return self.call(value={'policy': policy}).json()

    def bound(self, board, **extra):
        return dict(receipt=board['receipt'], policy=board['policy'], **extra)

    def export(self, board, fmt='json', status=200):
        return self.call('/export', self.bound(board, format=fmt), status)

    def csv_rows(self, text):
        return list(csv.reader(io.StringIO(text.removeprefix('\ufeff'))))

    def sources(self, board):
        first = self.call('/sources', self.bound(board)).json()
        self.assertEqual(first['total'], board['source_count'])
        self.assertEqual(first['size'], 40)
        rows = first['rows']
        for page in range(2, (first['total']+39)//40+1):
            rows.extend(self.call('/sources', self.bound(board, page=page)).json()['rows'])
        self.assertEqual(len(rows), first['total'])
        return rows

    def change(self, dataset, key, **fields):
        row = Record.objects.get(dataset=dataset, business_key=key)
        row.values.update(fields)
        row.record_hash = fingerprint(row.values)
        row.revision += 1
        row.save()
        source = row.source_row
        source.normalized, source.record_hash = row.values, row.record_hash
        source.save()

    def reseal(self):
        row = Record.objects.get(dataset='order_baselines', business_key='OB1')
        tables = {dataset: list(Record.objects.filter(dataset=dataset).values_list('values', flat=True))
                  for dataset in ('order_baseline_links', 'order_baseline_bom')}
        self.change('order_baselines', 'OB1', content_hash=bundle_hash(row.values, tables))

    def movement(self, key='IM1', **fields):
        values = dict(id=key, material_id='M1', lot='SIM-ISSUE', location='SIM-WH',
                      occurred='2026-10-01T18:00:00', movement='生产领料', qty_signed=-1,
                      work_order_id='WO1', reference='WO1')
        values.update(fields)
        return self.record('inventory_movements', values)

    def business_snapshot(self):
        return {model.__name__: list(model.objects.order_by('pk').values())
                for model in (Record, ImportRow, ImportBatch)}

    def assert_paused(self, board, code):
        self.assertEqual(board['state'], 'paused')
        self.assertIsNone(board['trial'])
        self.assertFalse(board['comparison']['available'])
        self.assertIn(code, {row['code'] for row in board['issues']})

    def test_six_roles_and_anonymous_for_all_endpoints(self):
        self.client.logout()
        for suffix in ('', '/sources', '/tasks/TA', '/export'):
            self.call(suffix, {'receipt': 'not-a-receipt'}, 401)
        for role in ('admin', 'analyst', 'operations', 'quality', 'finance', 'viewer'):
            with self.subTest(role=role):
                user = User.objects.filter(username=role).first() or User.objects.create_user(role)
                user.groups.add(Group.objects.get_or_create(name=role)[0])
                self.client.force_login(user)
                if role in ('admin', 'analyst', 'operations'):
                    board = self.board()
                    for suffix in ('/sources', '/tasks/TA', '/export'):
                        self.call(suffix, self.bound(board))
                else:
                    for suffix in ('', '/sources', '/tasks/TA', '/export'):
                        self.call(suffix, {'receipt': 'not-a-receipt'}, 403)

    def test_frozen_demands_use_snapshot_ids_and_whole_batch_quantities(self):
        board = self.board()
        self.assertEqual(board['state'], 'trial', board['issues'])
        self.assertFalse(board['history_verified'])
        trial = board['trial']
        self.assertEqual(trial['summary']['scheduled_tasks'], 4)
        self.assertEqual(trial['summary']['qty'], 2)
        self.assertEqual(trial['summary']['reserved_demands'], 3)
        self.assertEqual(trial['jobs'][0]['finished'], '2026-10-02T08:55:00')
        self.assertEqual({row['id']: row['required_qty'] for row in trial['demands']},
                         {'OBS1': '3', 'OBS2': '2', 'OBS3': '2'})
        self.assertEqual({row['demand_id'] for row in trial['reservations']}, {'OBS1', 'OBS2', 'OBS3'})
        self.assertEqual({row['material_id']: row['required_qty'] for row in trial['balances']},
                         {'M1': '5', 'M2': '2'})
        self.assertTrue(board['comparison']['available'])
        self.assertEqual(board['comparison']['jobs'][0]['delta_minutes'], 0)
        self.assertEqual(board['coverage'][0]['uncovered_qty'], 8)
        self.assertIsNone(board['coverage'][0]['order_finish'])

    def test_current_bom_difference_pauses_current_trial_but_frozen_still_calculates(self):
        old = self.board()
        self.change('bom', 'B1', qty=999)
        for suffix in ('', '/sources', '/tasks/TA', '/export'):
            self.call(suffix, self.bound(old), 409)
        board = self.board()
        self.assertEqual(board['state'], 'trial', board['issues'])
        self.assertFalse(board['comparison']['available'])
        self.assertEqual(board['trial']['demands'][0]['required_qty'], '3')
        self.assertEqual(board['trial']['jobs'][0]['finished'], old['trial']['jobs'][0]['finished'])
        doc = json.loads(self.export(board).json()['text'])
        self.assertEqual(doc['current_trial']['result']['state'], 'paused')
        self.assertEqual(doc['baseline_review']['state'], 'review')
        self.assertEqual(doc['baseline_inputs']['order_baseline_bom'][0]['unit_qty'], 1.5)
        self.assertEqual(next(row for row in doc['baseline_references']['bom'] if row['id'] == 'B1')['qty'], 999)

    def test_all_related_work_order_movements_invalidate_receipt_and_pause_at_cutoff(self):
        old = self.board()
        # This material is outside the frozen demand set; work-order history still matters.
        movement = self.movement(material_id='UNMODELED-MATERIAL')
        self.call('/sources', self.bound(old), 409)
        board = self.board()
        self.assert_paused(board, 'MATERIAL_ALREADY_ISSUED')
        self.assertNotEqual(board['source_hash'], old['source_hash'])
        source = next(row for row in self.sources(board) if row['dataset'] == 'inventory_movements')
        self.assertEqual((source['key'], source['source_row_id']), ('IM1', movement.source_row_id))
        doc = json.loads(self.export(board).json()['text'])
        self.assertEqual(doc['registered_issue_history'][0]['material_id'], 'UNMODELED-MATERIAL')
        self.assertEqual(doc['registered_issue_history'][0]['occurred'], board['cutoff'])
        self.call('/tasks/TA', self.bound(board), 404)

    def test_future_movements_remain_in_sources_without_blocking_or_deducting_supply(self):
        old = self.board()
        self.movement(occurred='2026-10-01T18:00:01', qty_signed=-999)
        self.export(old, status=409)
        board = self.board()
        self.assertEqual(board['state'], 'trial', board['issues'])
        self.assertEqual(board['trial']['balances'], old['trial']['balances'])
        self.assertEqual(board['trial']['reservations'], old['trial']['reservations'])
        self.assertIn(('inventory_movements', 'IM1'), {(row['dataset'], row['key']) for row in self.sources(board)})
        doc = json.loads(self.export(board).json()['text'])
        self.assertEqual(len(doc['registered_issue_history']), 1)
        self.assertEqual(doc['registered_issue_history'][0]['qty_signed'], -999)

    def test_unrelated_work_order_history_does_not_change_trial_scope(self):
        old = self.board()
        self.movement(work_order_id='UNRELATED-WO', reference='UNRELATED-WO')
        board = self.call(value=self.bound(old)).json()
        self.assertEqual(board['source_hash'], old['source_hash'])
        self.assertNotIn(('inventory_movements', 'IM1'), {(row['dataset'], row['key']) for row in self.sources(board)})

    def test_return_or_ambiguous_history_cannot_net_away_an_issue(self):
        self.movement()
        self.movement('RETURN', movement='生产退料', qty_signed=1)
        board = self.board()
        self.assert_paused(board, 'MATERIAL_ALREADY_ISSUED')
        self.assertIn('ISSUE_HISTORY_UNRESOLVED', {row['code'] for row in board['issues']})
        doc = json.loads(self.export(board).json()['text'])
        self.assertEqual({row['id'] for row in doc['registered_issue_history']}, {'IM1', 'RETURN'})

    def test_units_must_match_without_implicit_conversion(self):
        self.change('materials', 'M1', unit='g')
        self.change('joint_supplies', 'L1', unit='g', qty=5000)
        self.assert_paused(self.board(), 'UNIT_MISMATCH')

    def test_supply_in_another_unit_is_not_accepted_as_equivalent(self):
        self.change('joint_supplies', 'L1', unit='g', qty=5000)
        self.assert_paused(self.board(), 'SUPPLY_INVALID')

    def test_source_pages_and_task_detail_are_complete_and_resolve_real_import_rows(self):
        board = self.board()
        rows = self.sources(board)
        self.assertEqual(len({(row['dataset'], row['key']) for row in rows}), len(rows))
        self.assertFalse(self.call('/sources', self.bound(board, page=10000)).json()['rows'])
        for source in rows:
            if source.get('missing'):
                continue
            row = Record.objects.get(dataset=source['dataset'], business_key=source['key'])
            self.assertEqual(source['source_row_id'], row.source_row_id)
            self.assertEqual(source['record_hash'], fingerprint(row.values))
            self.assertEqual(source['batch_id'], str(row.source_row.batch_id))
            self.assertEqual(source['sheet'], row.source_row.sheet)
            self.assertEqual(source['row'], row.source_row.row_number)
        detail = self.call('/tasks/TA', self.bound(board)).json()
        self.assertEqual(detail['task'], next(row for row in board['trial']['tasks'] if row['id'] == 'TA'))
        self.assertEqual([row['snapshot_row_id'] for row in detail['demands']], ['OBS1'])
        self.assertEqual([row['demand_id'] for row in detail['reservations']], ['OBS1'])
        self.assertEqual(detail['sources'], rows)
        self.call('/tasks/OTHER', self.bound(board), 404)

    def test_repointed_source_row_invalidates_existing_receipt(self):
        board = self.board()
        row = Record.objects.get(dataset='schedule_tasks', business_key='TA')
        row.source_row = self.row(row.dataset, row.values, 'committed')
        row.save(update_fields=['source_row'])
        self.call('/sources', self.bound(board), 409)
        source = next(row for row in self.sources(self.board()) if (row['dataset'], row['key']) == ('schedule_tasks', 'TA'))
        self.assertEqual(source['source_row_id'], row.source_row_id)

    def test_corrupt_current_fact_and_history_import_row_are_rejected(self):
        row = Record.objects.get(dataset='bom', business_key='B1')
        row.values['qty'] = 99
        row.save(update_fields=['values'])
        self.call(status=400)
        self.change('bom', 'B1', qty=1.5)
        movement = self.movement(occurred='2026-10-01T18:00:01')
        source = movement.source_row
        source.normalized = {**source.normalized, 'qty_signed': -2}
        source.save(update_fields=['normalized'])
        self.call(status=400)

    def test_receipt_binds_account_policy_rule_and_expiry(self):
        board = self.board()
        self.call('/sources', dict(receipt=board['receipt'], policy='priority'), 409)
        priority = self.board('priority')
        self.call('/sources', self.bound(priority))
        with patch('app.baseline_trial.rule_hash', return_value='changed'):
            self.export(board, status=409)
        with patch('django.core.signing.time.time', return_value=0):
            expired = self.board()
        self.export(expired, status=409)
        AccountAccessState.objects.create(user=self.admin, revision=2)
        self.export(board, status=409)
        board = self.board()
        user = User.objects.create_user('another-planner')
        user.groups.add(Group.objects.get_or_create(name='analyst')[0])
        self.client.force_login(user)
        self.export(board, status=409)

    def test_mid_request_rule_change_prevents_receipt_and_export(self):
        rule_hash = baseline_trial.rule_hash()
        with patch('app.baseline_trial.rule_hash', side_effect=[rule_hash, 'changed']):
            self.call(status=409)
        board = self.board()
        with patch('app.baseline_trial.rule_hash', side_effect=[rule_hash, 'changed']):
            self.export(board, status=409)
        self.assertFalse(AuditEvent.objects.exists())

    def test_strict_json_fields_methods_and_csrf(self):
        for suffix in ('', '/sources', '/tasks/TA', '/export'):
            with self.subTest(suffix=suffix):
                self.assertEqual(self.client.get('/api/baseline-trial/OB1'+suffix).status_code, 405)
        for raw in ('{"policy":"due","policy":"priority"}', '{"receipt":"x","receipt":"y"}',
                    '{"policy":"due","unknown":{"x":1,"x":2}}', '[]', 'null', '1', 'bad-json'):
            response = self.client.post('/api/baseline-trial/OB1', raw, content_type='application/json')
            self.assertEqual(response.status_code, 400, response.content[:200])
        for value in ({'policy': 'bad'}, {'policy': None}, {'policy': []}, {'filter': 'TA'}, {'page': 1},
                      {'receipt': None}, {'receipt': ''}, {'receipt': 123}, {'receipt': 'a'*4097}):
            self.call(value=value, status=400)
        self.call(value={'receipt': 'tampered'}, status=409)
        for suffix in ('/sources', '/tasks/TA', '/export'):
            self.call(suffix, status=400)
        board = self.board()
        for page in (0, -1, 1.5, True, '1', '１００', 10001, None):
            self.call('/sources', self.bound(board, page=page), 400)
        self.call('/tasks/TA', self.bound(board, page=1), 400)
        self.export(board, 'xlsx', 400)
        self.call('?policy=due', status=400)
        self.call('/sources?page=1', self.bound(board), 400)
        self.call(key='OTHER', status=404)
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.admin)
        self.assertEqual(client.post('/api/baseline-trial/OB1', '{}', content_type='application/json').status_code, 403)

    def test_json_and_csv_exports_preserve_full_inputs_without_money_or_receipts(self):
        self.change('order_lines', 'OL1', unit_price_cents=9876543)
        self.change('materials', 'M1', unit_cost_cents=7654321)
        self.change('products', 'P1', price_cents=6543219)
        self.change('employees', 'E1', hourly_cents=5432198, phone='PRIVATE-EMPLOYEE-PHONE',
                    id_card='PRIVATE-EMPLOYEE-ID-CARD', private_note='PRIVATE-EMPLOYEE-NOTE')
        board = self.board()
        for fmt in ('json', 'csv'):
            with self.subTest(format=fmt):
                output = self.export(board, fmt).json()
                self.assertTrue(output['filename'].endswith('.'+fmt))
                self.assertEqual(output['mime'], 'application/json' if fmt == 'json' else 'text/csv')
                for forbidden in ('unit_price_cents', 'unit_cost_cents', 'price_cents', 'hourly_cents',
                                  '9876543', '7654321', '6543219', '5432198', 'PRIVATE-EMPLOYEE-PHONE',
                                  'PRIVATE-EMPLOYEE-ID-CARD', 'PRIVATE-EMPLOYEE-NOTE', '"receipt"', board['receipt']):
                    self.assertNotIn(forbidden, output['text'])
                if fmt == 'json':
                    doc = json.loads(output['text'])
                    self.assertEqual(len(doc['baseline_inputs']['order_baseline_links']), 1)
                    self.assertEqual(len(doc['baseline_inputs']['order_baseline_bom']), 3)
                    self.assertEqual(len(doc['current_trial']['material_inputs']['joint_demands']), 3)
                    self.assertEqual(len(doc['current_trial']['material_inputs']['joint_supplies']), 2)
                    self.assertEqual(len(doc['current_trial']['crew_inputs']['crew_candidates']), 4)
                    self.assertEqual(len(doc['current_trial']['resource_inputs']['schedule_tasks']), 4)
                    self.assertEqual(doc['sources'], self.sources(board))
                    self.assertEqual(doc['registered_issue_history'], [])
                else:
                    rows = self.csv_rows(output['text'])
                    for section in ('baseline_inputs/order_baseline_links', 'baseline_inputs/order_baseline_bom',
                                    'current_trial/material_inputs/joint_demands', 'current_trial/material_inputs/joint_supplies',
                                    'current_trial/crew_inputs/crew_candidates', 'current_trial/resource_inputs/schedule_tasks',
                                    'registered_issue_history', 'sources'):
                        self.assertIn([section], rows)

    def test_json_and_csv_export_complete_original_planning_references(self):
        fields = dict(employees=('id', 'active', 'name'),
                      skills=('id', 'employee_id', 'process', 'approved', 'expires', 'status'),
                      routes=('id', 'product_id', 'version', 'process', 'branch', 'mandatory'),
                      route_dependencies=('id', 'product_id', 'from_route_id', 'to_route_id'),
                      production_resources=('id', 'process', 'capacity', 'max_batch_qty', 'effective', 'station'))
        expected = {}
        for dataset, names in fields.items():
            records = Record.objects.filter(dataset=dataset).order_by('business_key')
            expected[dataset] = [{name: record.values.get(name) for name in names} for record in records]
            self.assertTrue(expected[dataset], dataset)
            for record in records:
                self.change(dataset, record.business_key, confidential_note='PRIVATE-PLANNING-'+dataset)
        board = self.board()
        output = self.export(board).json()
        doc = json.loads(output['text'])
        self.assertEqual(doc['planning_references'], expected)
        self.assertEqual(doc['planning_references']['employees'][0], {'id': 'E1', 'active': True, 'name': 'E1'})
        self.assertEqual(doc['planning_references']['skills'][0]['expires'], '2027-01-01')
        self.assertTrue(doc['planning_references']['routes'][0]['mandatory'])
        self.assertEqual(len(doc['planning_references']['route_dependencies']), 2)
        self.assertEqual(doc['planning_references']['production_resources'][0]['effective'], '2026-01-01')
        self.assertEqual(doc['planning_references']['production_resources'][0]['station'], 'R1')
        self.assertNotIn('PRIVATE-PLANNING-', output['text'])
        output = self.export(board, 'csv').json()
        self.assertNotIn('PRIVATE-PLANNING-', output['text'])
        rows = self.csv_rows(output['text'])
        for dataset, names in fields.items():
            with self.subTest(dataset=dataset):
                at = rows.index(['planning_references/'+dataset])
                self.assertEqual(rows[at+1], list(names))
                actual = [dict(zip(rows[at+1], row)) for row in rows[at+2:at+2+len(expected[dataset])]]
                self.assertEqual(actual, [{name: '' if row[name] is None else str(row[name]) for name in names}
                                          for row in expected[dataset]])

    def test_export_alone_reproduces_full_calculation_for_both_policies_and_bom_drift(self):
        self.movement(occurred='2026-10-01T18:00:01')
        for bom_qty in (1.5, 999):
            self.change('bom', 'B1', qty=bom_qty)
            for policy in ('due', 'priority'):
                with self.subTest(policy=policy, current_bom_qty=bom_qty):
                    doc = json.loads(self.export(self.board(policy)).json()['text'])
                    self.assertEqual(doc['result']['state'], 'trial')
                    self.assertEqual(doc['current_trial']['result']['state'], 'trial' if bom_qty == 1.5 else 'paused')
                    self.assertEqual(len(doc['registered_issue_history']), 1)
                    # From here the export is the sole source, with no ORM reads or saved intermediate results.
                    with self.assertNumQueries(0):
                        refs = defaultdict(dict)
                        for projection in (doc['baseline_references'], doc['current_trial']['references'], doc['planning_references']):
                            for dataset, rows in projection.items():
                                for row in rows:
                                    refs[dataset].setdefault(row['id'], {}).update(row)
                        for row in [*doc['baseline_review']['versions'], doc['baseline_inputs']['study']]:
                            refs['order_baselines'][row['id']] = row
                        refs['inventory_movements'] = {row['id']: row for row in doc['registered_issue_history']}

                        def inputs(value):
                            return value['study'], {key: rows for key, rows in value.items() if key != 'study'}

                        resource_study, resource_tables = inputs(doc['current_trial']['resource_inputs'])
                        base = dict(study=resource_study, tables=resource_tables,
                                    result=finite_schedule.analyze(resource_study, resource_tables, refs, doc['result']['policy']))
                        crew_study, crew_tables = inputs(doc['current_trial']['crew_inputs'])
                        crew = dict(tables=crew_tables, base=base,
                                    result=crew_schedule.analyze(crew_study, crew_tables, base, refs))
                        joint_study, joint_tables = inputs(doc['current_trial']['material_inputs'])
                        joint = dict(tables=joint_tables, parent=crew,
                                     result=joint_schedule.analyze(joint_study, joint_tables, crew, refs))
                        study, tables = inputs(doc['baseline_inputs'])
                        cutoff = doc['result']['cutoff']
                        review = order_baseline.analyze(study, tables, joint, refs, cutoff)
                        result = baseline_trial.analyze(review, tables, joint, refs, cutoff)
                        self.assertEqual(joint['result'], doc['current_trial']['result'])
                        self.assertEqual(review, doc['baseline_review'])
                        self.assertEqual(result, doc['result'])

    def test_csv_returned_text_has_one_utf8_bom_and_audit_hash_covers_it(self):
        output = self.export(self.board(), 'csv').json()
        text = output['text']
        self.assertTrue(text.startswith('\ufeff'))
        self.assertFalse(text.startswith('\ufeff\ufeff'))
        encoded = text.encode('utf-8')
        self.assertTrue(encoded.startswith(b'\xef\xbb\xbf'))
        self.assertEqual(self.csv_rows(text)[0], ['基线假设试排'])
        audit = AuditEvent.objects.get(action='baseline_trial.export')
        self.assertEqual(audit.detail['file_sha256'], hashlib.sha256(encoded).hexdigest())
        self.assertNotEqual(audit.detail['file_sha256'], hashlib.sha256(text.removeprefix('\ufeff').encode('utf-8')).hexdigest())

    def test_paused_export_preserves_original_inputs_and_csv_formula_guard(self):
        self.change('order_baselines', 'OB1', name='  =SIM()')
        self.reseal()
        board = self.board()
        rows = self.csv_rows(self.export(board, 'csv').json()['text'])
        self.assertIn("'  =SIM()", rows[2])
        self.change('order_baseline_bom', 'OBS1', unit_qty=777)
        board = self.board()
        self.assert_paused(board, 'BASELINE_INVALID')
        doc = json.loads(self.export(board).json()['text'])
        self.assertEqual(doc['result']['study']['name'], '  =SIM()')
        self.assertEqual(len(doc['baseline_inputs']['order_baseline_bom']), 3)
        self.assertEqual(doc['baseline_inputs']['order_baseline_bom'][0]['unit_qty'], 777)
        self.assertEqual(len(doc['current_trial']['resource_inputs']['schedule_tasks']), 4)

    def test_reads_and_exports_do_not_write_business_facts_and_audit_hash_matches_text(self):
        before = self.business_snapshot()
        board = self.board()
        self.sources(board)
        self.call('/tasks/TA', self.bound(board))
        self.assertFalse(AuditEvent.objects.exists())
        for fmt in ('json', 'csv'):
            output = self.export(board, fmt).json()
            audit = AuditEvent.objects.order_by('-pk').first()
            self.assertEqual(audit.action, 'baseline_trial.export')
            self.assertFalse(audit.detail['business_facts_changed'])
            self.assertEqual(audit.detail['policy'], board['policy'])
            self.assertEqual(audit.detail['source_hash'], board['source_hash'])
            self.assertEqual(audit.detail['file_sha256'], hashlib.sha256(output['text'].encode('utf-8')).hexdigest())
        self.assertEqual(AuditEvent.objects.count(), 2)
        self.assertEqual(self.business_snapshot(), before)

    def test_audit_failure_rolls_back_event_and_returns_no_export(self):
        before = self.business_snapshot()
        board = self.board()
        create = AuditEvent.objects.create

        def failed_audit(**values):
            create(**values)
            raise IntegrityError('SIM audit failure after insert')

        with patch('app.baseline_trial_views.AuditEvent.objects.create', side_effect=failed_audit):
            response = self.export(board, status=409)
        self.assertNotIn('text', response.json())
        self.assertFalse(AuditEvent.objects.exists())
        self.assertEqual(self.business_snapshot(), before)
