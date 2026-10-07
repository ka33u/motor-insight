import csv
import io
import json
from unittest.mock import patch
from django.contrib.auth.models import User, Group
from django.db import IntegrityError
from app.models import Record, AuditEvent, AccountAccessState
from app.ingestion import fingerprint
from .test_platform import PlatformCase
from .test_joint_schedule import fixture


class JointScheduleAPITests(PlatformCase):
    def setUp(self):
        super().setUp()
        study, tables, parent, refs = fixture()
        self.record('joint_studies', study)
        self.record('crew_studies', parent['result']['study'])
        self.record('schedule_studies', parent['base']['study'])
        for ds, rows in {**tables, **parent['tables'], **parent['base']['tables']}.items():
            for row in rows:
                self.record(ds, row)
        for ds, rows in refs.items():
            for row in rows.values():
                self.record(ds, row)
        self.client.force_login(self.admin)

    def board(self):
        return self.client.get('/api/joint-schedule/MP1')

    def export(self, d=None, fmt='json', **extra):
        return self.client.get('/api/joint-schedule/MP1/export', dict(receipt=(d or self.board().json())['receipt'], format=fmt, **extra))

    def change(self, ds, key, **fields):
        row = Record.objects.get(dataset=ds, business_key=key)
        row.values.update(fields)
        row.record_hash = fingerprint(row.values)
        row.revision += 1
        row.save()
        source = row.source_row
        source.normalized, source.record_hash = row.values, row.record_hash
        source.save()

    def test_auth_method_roles_and_raw_route(self):
        before = (Record.objects.count(), AuditEvent.objects.count())
        self.client.logout()
        self.assertEqual(self.board().status_code, 401)
        for role in ['admin', 'analyst', 'operations', 'quality', 'finance', 'viewer']:
            user = User.objects.filter(username=role).first() or User.objects.create_user(role)
            user.groups.add(Group.objects.get_or_create(name=role)[0])
            self.client.force_login(user)
            expected = 200 if role in ['admin', 'analyst', 'operations'] else 403
            self.assertEqual(self.board().status_code, expected)
            self.assertEqual(self.client.get('/api/joint-schedule').status_code, expected)
            for ds in ('joint_studies', 'joint_bindings', 'joint_demands', 'joint_supplies'):
                self.assertEqual(self.client.get('/api/records/'+ds).status_code, expected)
        self.assertEqual(before, (Record.objects.count(), AuditEvent.objects.count()))
        self.client.force_login(self.admin)
        self.assertEqual(self.client.post('/api/joint-schedule/MP1').status_code, 405)

    def test_strict_query_and_pages(self):
        for query in ('?policy=due&policy=priority', '?policy=bad', '?filter=M1', '?page=1'):
            self.assertEqual(self.client.get('/api/joint-schedule/MP1'+query).status_code, 400)
        receipt = self.board().json()['receipt']
        for page in ('0', '2.1', '-1', '１００'):
            self.assertEqual(self.client.get('/api/joint-schedule/MP1/sources', dict(receipt=receipt, page=page)).status_code, 400)
        self.assertEqual(self.client.get('/api/joint-schedule/MP1/tasks/OTHER', dict(receipt=receipt)).status_code, 404)

    def test_receipt_expiry_policy_account_and_epoch(self):
        self.assertEqual(self.client.get('/api/joint-schedule/MP1/export').status_code, 400)
        with patch('django.core.signing.time.time', return_value=0):
            old = self.board().json()
        self.assertEqual(self.export(old).status_code, 409)
        current = self.board().json()
        self.assertEqual(self.export(current, policy='priority').status_code, 409)
        AccountAccessState.objects.create(user=self.admin, revision=2)
        self.assertEqual(self.export(current).status_code, 409)
        current = self.board().json()
        user = User.objects.create_user('joint-analyst')
        user.groups.add(Group.objects.get_or_create(name='analyst')[0])
        self.client.force_login(user)
        self.assertEqual(self.export(current).status_code, 409)

    def test_bom_material_skill_and_supply_changes_invalidate(self):
        for ds, key, fields in [('bom', 'B1', {'qty': 1.6}), ('materials', 'M1', {'name': '新名'}), ('skills', 'S1', {'status': '暂停'}), ('joint_supplies', 'L1', {'qty': 4})]:
            before = self.board().json()
            self.change(ds, key, **fields)
            self.assertEqual(self.export(before).status_code, 409)
        before = self.board().json()
        self.batch.filename = 'renamed.xlsx'
        self.batch.save()
        self.assertEqual(self.export(before).status_code, 409)
        before = self.board().json()
        with patch('app.joint_schedule.rule_hash', return_value='new'):
            self.assertEqual(self.export(before).status_code, 409)

    def test_all_current_bom_lines_checked_not_just_bound_lines(self):
        self.record('bom', dict(id='UNBOUND', product_id='P1', material_id='M1', version='B1', qty=1, scrap_allowance=0, effective='2026-01-01', assembly_level='定子'))
        result = self.board().json()
        self.assertEqual(result['state'], 'paused')
        self.assertTrue(any('未完整绑定' in s for s in result['issues']))
        self.assertIsNone(result['summary'])

    def test_full_export_preserves_all_inputs_and_avoids_prices_and_receipts(self):
        self.change('products', 'P1', price_cents=9876543)
        self.change('materials', 'M1', unit_cost_cents=7654321)
        response = self.export()
        self.assertEqual(response.status_code, 200)
        doc = response.json()
        self.assertEqual(len(doc['result']['tasks']), 4)
        self.assertEqual(len(doc['material_inputs']['joint_demands']), 3)
        self.assertEqual(len(doc['crew_inputs']['crew_candidates']), 4)
        self.assertEqual(len(doc['resource_inputs']['schedule_tasks']), 4)
        self.assertNotIn('receipt', doc)
        raw = response.content.decode()
        for forbidden in ('price_cents', 'unit_cost_cents', '9876543', '7654321'):
            self.assertNotIn(forbidden, raw)
        self.assertEqual(response['Cache-Control'], 'no-store')
        self.assertEqual(AuditEvent.objects.get(action='joint_schedule.export').detail['input_tasks'], 4)

    def test_detail_has_whole_batch_ledger_and_shared_supply(self):
        current = self.board().json()
        response = self.client.get('/api/joint-schedule/MP1/tasks/TC2', dict(receipt=current['receipt']))
        self.assertEqual(response.status_code, 200)
        doc = response.json()
        self.assertEqual(doc['reservations'][0]['task_id'], 'TC1')
        self.assertEqual(doc['demands'][0]['required_qty'], '2')
        keys = {(s['dataset'], s['key']) for s in doc['sources']}
        for key in [('joint_demands', 'D3'), ('joint_bindings', 'K3'), ('bom', 'B3'), ('joint_supplies', 'L2'), ('crew_windows', 'WE3')]:
            self.assertIn(key, keys)

    def test_paused_csv_keeps_inputs_and_formula_safe_text(self):
        self.change('joint_studies', 'MP1', name='  =SIM()', demand_count=99)
        d = self.board().json()
        self.assertEqual(d['state'], 'paused')
        doc = self.export(d).json()
        self.assertEqual(len(doc['resource_inputs']['schedule_tasks']), 4)
        self.assertEqual(len(doc['material_inputs']['joint_demands']), 3)
        rows = list(csv.reader(io.StringIO(self.export(d, 'csv').content.decode('utf-8-sig'))))
        self.assertIn("'  =SIM()", rows[0])
        self.assertIn(['material_inputs/joint_demands'], rows)
        self.assertIn(['crew_inputs/crew_windows'], rows)
        self.assertEqual(sum(bool(r) and r[0] in {'TA', 'TB', 'TC1', 'TC2'} for r in rows), 4)

    def test_corrupt_source_and_audit_failure_do_not_export(self):
        before = (Record.objects.count(), AuditEvent.objects.count())
        with patch('app.joint_schedule_views.AuditEvent.objects.create', side_effect=IntegrityError('SIM')):
            self.assertEqual(self.export().status_code, 409)
        self.assertEqual(self.export(fmt='xlsx').status_code, 400)
        self.assertEqual(before, (Record.objects.count(), AuditEvent.objects.count()))
        row = Record.objects.get(dataset='joint_supplies', business_key='L1')
        row.values['qty'] = 999
        row.save()
        self.assertEqual(self.board().status_code, 400)
