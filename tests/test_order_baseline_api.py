import csv
import io
from unittest.mock import patch
from django.contrib.auth.models import User, Group
from django.db import IntegrityError
from app.models import Record, AuditEvent, AccountAccessState
from app.ingestion import fingerprint
from app.order_baseline_contract import bundle_hash
from .test_platform import PlatformCase
from .test_order_baseline import fixture


class OrderBaselineAPITests(PlatformCase):
    def setUp(self):
        super().setUp()
        study, tables, joint, refs, _ = fixture()
        crew, base = joint['parent'], joint['parent']['base']
        for ds, row in [('order_baselines', study), ('joint_studies', joint['result']['study']), ('crew_studies', crew['result']['study']), ('schedule_studies', base['study'])]:
            self.record(ds, row)
        for ds, rows in {**tables, **joint['tables'], **crew['tables'], **base['tables']}.items():
            for row in rows:
                self.record(ds, row)
        for ds, rows in refs.items():
            if ds != 'order_baselines':
                for row in rows.values():
                    self.record(ds, row)
        self.client.force_login(self.admin)

    def board(self):
        return self.client.get('/api/order-baselines/OB1')

    def export(self, d=None, fmt='json', **extra):
        return self.client.get('/api/order-baselines/OB1/export', dict(receipt=(d or self.board().json())['receipt'], format=fmt, **extra))

    def change(self, ds, key, **fields):
        row = Record.objects.get(dataset=ds, business_key=key)
        row.values.update(fields)
        row.record_hash = fingerprint(row.values)
        row.revision += 1
        row.save()
        source = row.source_row
        source.normalized, source.record_hash = row.values, row.record_hash
        source.save()

    def reseal(self):
        row = Record.objects.get(dataset='order_baselines', business_key='OB1')
        tables = {ds: list(Record.objects.filter(dataset=ds).values_list('values', flat=True)) for ds in ('order_baseline_links', 'order_baseline_bom')}
        self.change('order_baselines', 'OB1', content_hash=bundle_hash(row.values, tables))

    def test_roles_raw_access_and_methods(self):
        before = (Record.objects.count(), AuditEvent.objects.count())
        self.client.logout()
        self.assertEqual(self.board().status_code, 401)
        for role in ('admin', 'analyst', 'operations', 'quality', 'finance', 'viewer'):
            user = User.objects.filter(username=role).first() or User.objects.create_user(role)
            user.groups.add(Group.objects.get_or_create(name=role)[0])
            self.client.force_login(user)
            expected = 200 if role in ('admin', 'analyst', 'operations') else 403
            self.assertEqual(self.board().status_code, expected)
            self.assertEqual(self.client.get('/api/order-baselines').status_code, expected)
            for ds in ('order_baselines', 'order_baseline_links', 'order_baseline_bom'):
                self.assertEqual(self.client.get('/api/records/'+ds).status_code, expected)
                self.assertEqual(self.client.get('/api/bi-field-catalog?dataset='+ds).status_code, expected)
        self.assertEqual(before, (Record.objects.count(), AuditEvent.objects.count()))
        self.client.force_login(self.admin)
        self.assertEqual(self.client.post('/api/order-baselines/OB1').status_code, 405)

    def test_complete_sources_customer_due_and_partial_order(self):
        d = self.board().json()
        self.assertEqual(d['state'], 'aligned', d.get('error'))
        self.assertEqual(d['summary']['planned_qty'], 2)
        self.assertEqual(d['summary']['uncovered_qty'], 8)
        self.assertEqual(d['summary']['customer_late_jobs'], 1)
        r = self.client.get('/api/order-baselines/OB1/links/OLK1', dict(receipt=d['receipt']))
        self.assertEqual(r.status_code, 200)
        refs = {(s['dataset'], s['key']) for s in r.json()['sources']}
        for pair in [('order_lines', 'OL1'), ('work_orders', 'WO1'), ('allocations', 'AL1'), ('order_baseline_bom', 'OBS1'), ('bom', 'B1')]:
            self.assertIn(pair, refs)

    def test_current_bom_change_invalidates_receipt_but_preserves_baseline_arithmetic(self):
        old = self.board().json()
        self.change('bom', 'B1', qty=999)
        self.assertEqual(self.export(old).status_code, 409)
        current = self.board().json()
        self.assertEqual(current['state'], 'review')
        self.assertEqual(current['bom'][0]['required_qty'], '3')
        self.assertEqual(current['trial_state'], 'paused')
        self.assertEqual(current['summary']['scheduled_jobs'], 0)

    def test_new_unbound_bom_row_changes_complete_population(self):
        before = self.board().json()
        row = Record.objects.get(dataset='bom', business_key='B1').values
        self.record('bom', {**row, 'id': 'ADDED'})
        self.assertEqual(self.export(before).status_code, 409)
        current = self.board().json()
        self.assertEqual(len(current['bom']), 3)
        self.assertTrue(any('BOM集合' in w for w in current['warnings']))

    def test_frozen_snapshot_tamper_is_paused_with_original_inputs_in_export(self):
        self.change('order_baseline_bom', 'OBS1', unit_qty=777)
        d = self.board().json()
        self.assertEqual(d['state'], 'paused')
        self.assertIsNone(d['summary'])
        doc = self.export(d).json()
        self.assertEqual(len(doc['baseline_inputs']['order_baseline_bom']), 3)
        self.assertEqual(len(doc['trial']['resource_inputs']['schedule_tasks']), 4)

    def test_expiry_account_epoch_policy_and_rule_binding(self):
        self.assertEqual(self.client.get('/api/order-baselines/OB1/export').status_code, 400)
        with patch('django.core.signing.time.time', return_value=0):
            old = self.board().json()
        self.assertEqual(self.export(old).status_code, 409)
        d = self.board().json()
        self.assertEqual(self.export(d, policy='priority').status_code, 409)
        AccountAccessState.objects.create(user=self.admin, revision=2)
        self.assertEqual(self.export(d).status_code, 409)
        d = self.board().json()
        with patch('app.order_baseline.rule_hash', return_value='changed'):
            self.assertEqual(self.export(d).status_code, 409)
        user = User.objects.create_user('baseline-analyst')
        user.groups.add(Group.objects.get_or_create(name='analyst')[0])
        self.client.force_login(user)
        self.assertEqual(self.export(d).status_code, 409)

    def test_strict_query_foreign_link_and_source_pages(self):
        for query in ('?policy=bad', '?policy=due&policy=priority', '?filter=OL1', '?page=1'):
            self.assertEqual(self.client.get('/api/order-baselines/OB1'+query).status_code, 400)
        receipt = self.board().json()['receipt']
        for page in ('0', '-1', '1.5', '１００'):
            self.assertEqual(self.client.get('/api/order-baselines/OB1/sources', dict(receipt=receipt, page=page)).status_code, 400)
        self.assertEqual(self.client.get('/api/order-baselines/OB1/links/OTHER', dict(receipt=receipt)).status_code, 404)

    def test_complete_json_and_csv_no_prices_or_active_receipt(self):
        self.change('order_lines', 'OL1', unit_price_cents=9876543)
        self.change('materials', 'M1', unit_cost_cents=7654321)
        response = self.export()
        self.assertEqual(response.status_code, 200)
        raw = response.content.decode()
        for forbidden in ('unit_price_cents', 'unit_cost_cents', '9876543', '7654321', '"receipt"'):
            self.assertNotIn(forbidden, raw)
        doc = response.json()
        self.assertEqual(len(doc['trial']['resource_inputs']['schedule_tasks']), 4)
        self.assertEqual(response['Cache-Control'], 'no-store')
        self.change('order_baselines', 'OB1', name='  =SIM()')
        self.reseal()
        rows = list(csv.reader(io.StringIO(self.export(fmt='csv').content.decode('utf-8-sig'))))
        self.assertIn("'  =SIM()", rows[0])
        self.assertIn(['order_baseline_links'], rows)
        self.assertIn(['order_baseline_bom'], rows)

    def test_corrupt_source_and_audit_failure(self):
        before = (Record.objects.count(), AuditEvent.objects.count())
        with patch('app.order_baseline_views.AuditEvent.objects.create', side_effect=IntegrityError('SIM')):
            self.assertEqual(self.export().status_code, 409)
        self.assertEqual(self.export(fmt='xlsx').status_code, 400)
        self.assertEqual(before, (Record.objects.count(), AuditEvent.objects.count()))
        row = Record.objects.get(dataset='order_lines', business_key='OL1')
        row.values['qty'] = 30
        row.save()
        self.assertEqual(self.board().status_code, 400)
