import copy
import json
import time
from unittest.mock import patch
from django.contrib.auth.models import User, Group
from django.core.exceptions import ValidationError, PermissionDenied
from django.test import Client
from app import topic_journey as journey, topic_workspace as ws, topic_linkage
from app.models import AnalysisModel, Topic, TopicView, TopicPage, AuditEvent, Record, AccountAccessState
from app.import_review import ReviewConflict
from tests.test_platform import PlatformCase

CONFIG = dict(scope={'from': '2026-09-25', 'to': '2026-09-25'}, reference_scope={'from': '2026-09-24', 'to': '2026-09-24'}, primary_label='本期', reference_label='对照期')


class TopicJourneyTests(PlatformCase):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.admin)
        self.model = AnalysisModel.objects.create(name='车间能耗', dataset='energy', definition={'dimension': 'workshop', 'metrics': [{'agg': 'sum', 'field': 'kwh'}], 'chart': 'bar'}, owner='admin', is_public=True)
        self.source = Topic.objects.create(name='来源专题', layout=[{'model_id': self.model.pk}], owner='admin', is_public=True)
        self.target = Topic.objects.create(name='目标专题', layout=[{'model_id': self.model.pk}], owner='admin', is_public=True)
        for n, day, value in [(1, '24', 10), (2, '25', 20), (3, '25', 5)]:
            self.record('energy', dict(id=f'E{n}', workshop='绕组', started=f'2026-09-{day}T08:00:00', ended=f'2026-09-{day}T12:00:00', kwh=value, tariff_cents=100))

    def body(self, config=None, user=None):
        return dict(target_id=self.target.pk, context_token=ws.context(user or self.admin, self.source.pk)['context_token'], config=copy.deepcopy(config if config is not None else CONFIG))

    def open(self, config=None, mode='inherit', user=None):
        user = user or self.admin
        body = self.body(config, user)
        preview = journey.preview(user, self.source.pk, body)
        return journey.open_journey(user, self.source.pk, dict(**body, mode=mode, receipt=preview['receipt']))

    def resolve(self, opened, direction='forward', user=None, topic=None):
        return journey.resolve(user or self.admin, topic or (self.target.pk if direction == 'forward' else self.source.pk), dict(receipt=opened['receipt'], direction=direction))

    def option(self, preview, mode):
        return next(o for o in preview['options'] if o['mode'] == mode)

    def model_for(self, topic, dataset, definition=None):
        model = AnalysisModel.objects.create(name=dataset, dataset=dataset, definition=definition or {'metrics': [{'agg': 'count'}], 'chart': 'bar'}, owner='admin', is_public=True)
        topic.layout = [{'model_id': model.pk}]; topic.save()
        return model

    def test_inherit_and_return_exact_scope_and_numeric_results(self):
        opened = self.open()
        arrived = self.resolve(opened)
        self.assertEqual(arrived['config'], CONFIG)
        result = ws.run(self.admin, self.target.pk, {k: arrived[k] for k in ('config', 'context_token')})
        self.assertEqual(result['cards'][0]['primary']['rows'][0]['m0'], 25)
        self.assertEqual(result['cards'][0]['reference']['rows'][0]['m0'], 10)
        self.assertEqual(result['cards'][0]['comparison']['rows'][0]['values'][0]['delta'], 15)
        self.assertEqual(self.resolve(opened, 'return')['config'], CONFIG)

    def test_objects_reset_dates_comparison_labels_keep_exact_identifiers(self):
        self.model_for(self.source, 'units'); self.model_for(self.target, 'work_orders')
        links = dict(revision=topic_linkage.REVISION, rules_hash=topic_linkage.rules_hash(), selections=[dict(kind='configuration', value='00001')])
        config = dict(CONFIG, scope={**CONFIG['scope'], 'family': 'YE4', 'customer_id': '000009'}, reference_scope={'customer_id': 'OTHER'}, links=links)
        preview = journey.preview(self.admin, self.source.pk, self.body(config))
        self.assertFalse(self.option(preview, 'inherit')['allowed'])
        expected = dict(journey.defaults(), scope={'family': 'YE4', 'customer_id': '000009'}, links=links)
        self.assertEqual(self.resolve(self.open(config, 'objects'))['config'], expected)
        self.assertEqual(self.resolve(self.open(config, 'objects'), 'return')['config'], config)

    def test_objects_requires_current_object_not_only_reference_object(self):
        self.model_for(self.source, 'units'); self.model_for(self.target, 'work_orders')
        config = dict(CONFIG, reference_scope={'family': 'YE4'})
        self.assertFalse(self.option(journey.preview(self.admin, self.source.pk, self.body(config)), 'objects')['allowed'])

    def test_date_role_mismatch_blocks_even_when_both_accept_dates(self):
        self.model_for(self.target, 'units')
        p = journey.preview(self.admin, self.source.pk, self.body())
        self.assertIn('日期角色不同', ' '.join(self.option(p, 'inherit')['reasons']))
        with self.assertRaises(ValidationError): self.open()
        self.assertEqual(self.resolve(self.open(mode='new'))['config'], journey.defaults())

    def test_no_date_range_can_inherit_across_different_date_roles(self):
        self.model_for(self.target, 'units')
        self.assertEqual(self.resolve(self.open(journey.defaults()))['config'], journey.defaults())

    def test_reference_only_date_is_checked(self):
        self.model_for(self.target, 'units')
        p = journey.preview(self.admin, self.source.pk, self.body(dict(CONFIG, scope={})))
        self.assertFalse(self.option(p, 'inherit')['allowed'])

    def test_unavailable_source_date_card_blocks_inheritance(self):
        self.source.layout.append({'model_id': 999999}); self.source.save()
        self.assertFalse(self.option(journey.preview(self.admin, self.source.pk, self.body()), 'inherit')['allowed'])

    def test_unsupported_condition_on_any_card_or_side_is_visible(self):
        p = journey.preview(self.admin, self.source.pk, self.body(dict(CONFIG, reference_scope={'customer_id': 'C01'})))
        option = self.option(p, 'inherit')
        self.assertFalse(option['allowed']); self.assertIn('对照范围不支持客户', option['cards'][0]['reasons'])

    def test_no_inferred_join_for_identity(self):
        links = dict(revision=topic_linkage.REVISION, rules_hash=topic_linkage.rules_hash(), selections=[dict(kind='unit', value='SN0001')])
        p = journey.preview(self.admin, self.source.pk, self.body(dict(CONFIG, links=links)))
        self.assertFalse(self.option(p, 'objects')['allowed'])
        self.assertIn('直接身份字段', ' '.join(self.option(p, 'objects')['cards'][0]['reasons']))

    def test_link_intersection_preserves_local_model_filters(self):
        self.model.definition['filters'] = [dict(field='workshop', op='eq', value='绕组')]; self.model.save()
        links = dict(revision=topic_linkage.REVISION, rules_hash=topic_linkage.rules_hash(), selections=[dict(kind='workshop', value='组装')])
        arrived = self.resolve(self.open(dict(CONFIG, links=links)))
        result = ws.run(self.admin, self.target.pk, {k: arrived[k] for k in ('config', 'context_token')})
        self.assertEqual(result['cards'][0]['primary']['matched'], 0)
        self.model.refresh_from_db(); self.assertEqual(len(self.model.definition['filters']), 1)

    def test_native_filter_limit_blocks_inheritance(self):
        self.model.definition['filters'] = [dict(field='workshop', op='eq', value='绕组')] * 10; self.model.save()
        links = dict(revision=topic_linkage.REVISION, rules_hash=topic_linkage.rules_hash(), selections=[dict(kind='workshop', value='绕组')])
        p = journey.preview(self.admin, self.source.pk, self.body(dict(CONFIG, links=links)))
        self.assertFalse(self.option(p, 'inherit')['allowed']); self.assertTrue(self.option(p, 'new')['allowed'])

    def test_inactive_or_other_native_model_failures_checked_without_links(self):
        with patch('app.topic_journey.validate_definition', side_effect=ValidationError('指标已停用')):
            p = journey.preview(self.admin, self.source.pk, self.body())
            self.assertFalse(self.option(p, 'inherit')['allowed'])
            self.assertTrue(self.option(p, 'new')['allowed'])
            self.assertEqual(self.option(p, 'new')['cards'][0]['reasons'], ['指标已停用'])

    def test_hidden_card_metadata_never_exposed_new_scope_still_possible(self):
        model = self.model_for(self.target, 'costs', {'metrics': [{'agg': 'sum', 'field': 'amount_cents'}]})
        model.name = '财务秘密'; model.save()
        p = journey.preview(self.quality, self.source.pk, self.body(user=self.quality))
        self.assertNotIn('财务秘密', json.dumps(p, ensure_ascii=False)); self.assertNotIn('amount_cents', json.dumps(p))
        self.assertEqual(self.option(p, 'inherit')['cards'][0]['name'], '当前不可访问')
        self.assertFalse(self.option(p, 'inherit')['allowed'])
        self.assertEqual(self.resolve(self.open(mode='new', user=self.quality), user=self.quality)['config'], journey.defaults())

    def test_empty_target_supports_only_new(self):
        self.target.layout = []; self.target.save()
        p = journey.preview(self.admin, self.source.pk, self.body())
        self.assertFalse(self.option(p, 'inherit')['allowed']); self.assertTrue(self.option(p, 'new')['allowed'])

    def test_private_topic_returns_not_found(self):
        self.target.is_public = False; self.target.save(); self.client.force_login(self.quality)
        self.assertEqual(self.post(f'/api/topics/{self.source.pk}/journey/preview', self.body(user=self.quality)).status_code, 404)

    def test_receipts_reject_another_user_and_permission_revision(self):
        opened = self.open()
        with self.assertRaises(ReviewConflict): self.resolve(opened, user=self.quality)
        AccountAccessState.objects.create(user=self.admin, revision=2)
        with self.assertRaises(ReviewConflict): self.resolve(opened)

    def test_disabled_account_and_group_change_use_fresh_state(self):
        opened = self.open(); self.admin.is_active = False; self.admin.save()
        with self.assertRaises(PermissionDenied): self.resolve(opened)
        self.admin.is_active = True; self.admin.save(); self.admin.groups.clear()
        # No explicit role falls back to viewer in the existing access policy.
        with self.assertRaises(ReviewConflict): self.resolve(opened)

    def test_model_definition_drift_even_without_version_change_blocks_both_directions(self):
        opened = self.open(); self.model.definition['metrics'][0]['agg'] = 'avg'; self.model.save()
        for direction in ('forward', 'return'):
            with self.assertRaises(ReviewConflict): self.resolve(opened, direction)

    def test_target_version_change_blocks_preview_confirmation(self):
        body = self.body(); p = journey.preview(self.admin, self.source.pk, body)
        self.target.version += 1; self.target.save()
        with self.assertRaises(ReviewConflict): journey.open_journey(self.admin, self.source.pk, dict(**body, mode='inherit', receipt=p['receipt']))

    def test_config_change_and_rules_change_block_confirmation(self):
        body = self.body(); p = journey.preview(self.admin, self.source.pk, body)
        changed = copy.deepcopy(body); changed['config']['primary_label'] = '其他'
        with self.assertRaises(ReviewConflict): journey.open_journey(self.admin, self.source.pk, dict(**changed, mode='inherit', receipt=p['receipt']))
        opened = self.open()
        with patch('app.topic_journey.rules', return_value='changed'):
            with self.assertRaises(ReviewConflict): self.resolve(opened)

    def test_contract_change_invalidates_receipt_without_model_change(self):
        opened = self.open()
        with patch.dict('app.bi_scope.DATES', {'energy': ('started', '新日期角色')}):
            with self.assertRaises(ReviewConflict): self.resolve(opened)

    def test_fact_change_does_not_freeze_values_or_invalidate_scope_only_navigation(self):
        opened = self.open()
        self.record('energy', dict(id='E4', workshop='绕组', started='2026-09-25T13:00:00', ended='2026-09-25T14:00:00', kwh=1, tariff_cents=100))
        arrived = self.resolve(opened)
        result = ws.run(self.admin, self.target.pk, {k: arrived[k] for k in ('config', 'context_token')})
        self.assertEqual(result['cards'][0]['primary']['rows'][0]['m0'], 26)

    def test_expired_tampered_wrong_salt_and_wrong_route(self):
        now = time.time(); opened = self.open(); body = self.body(); p = journey.preview(self.admin, self.source.pk, body)
        with patch('django.core.signing.time.time', return_value=now + journey.PREVIEW_AGE + 2):
            with self.assertRaises(ReviewConflict): journey.open_journey(self.admin, self.source.pk, dict(**body, mode='inherit', receipt=p['receipt']))
        with patch('django.core.signing.time.time', return_value=now + journey.JOURNEY_AGE + 2):
            with self.assertRaises(ReviewConflict): self.resolve(opened)
        for receipt in (opened['receipt'] + 'x', p['receipt']):
            with self.assertRaises(ReviewConflict): self.resolve(dict(receipt=receipt))
        with self.assertRaises(ValidationError): self.resolve(opened, topic=self.source.pk)

    def test_malformed_inputs_fail_closed(self):
        for change in ({'target_id': True}, {'target_id': self.source.pk}, {'target_id': 0}, {'target_id': '2'}, {'extra': 1}, {'config': None}):
            with self.assertRaises(ValidationError): journey.preview(self.admin, self.source.pk, dict(self.body(), **change))
        for body in ({'receipt': 'x', 'direction': 'back'}, {'receipt': 'x', 'direction': []}, {'receipt': 'x' * 12001, 'direction': 'forward'}, {'receipt': 'x', 'direction': 'forward', 'config': CONFIG}):
            with self.assertRaises(ValidationError): journey.resolve(self.admin, self.target.pk, body)

    def test_read_only_preserves_models_views_pages_audit_and_facts(self):
        saved = ws.save_view(self.admin, self.source.pk, dict(name='保持私有视角', context_token=self.body()['context_token'], config=CONFIG))
        tables = [AnalysisModel, Topic, TopicView, TopicPage, AuditEvent, Record]
        before = [list(m.objects.order_by('pk').values()) for m in tables]
        opened = self.open(); self.resolve(opened); self.resolve(opened, 'return')
        self.assertEqual(before, [list(m.objects.order_by('pk').values()) for m in tables])
        self.assertEqual(TopicView.objects.get(pk=saved['id']).config, CONFIG)

    def test_post_only_auth_csrf_no_store_and_no_query_conditions(self):
        url = f'/api/topics/{self.source.pk}/journey/preview'
        self.assertEqual(self.client.get(url).status_code, 405)
        self.assertEqual(self.post(url + '?config=bad', self.body()).status_code, 400)
        secure = Client(enforce_csrf_checks=True); secure.force_login(self.admin)
        self.assertEqual(secure.post(url, json.dumps(self.body()), content_type='application/json').status_code, 403)
        self.assertEqual(self.post(url, self.body())['Cache-Control'], 'no-store')
        self.client.logout(); self.assertEqual(self.post(url, self.body()).status_code, 401)

    def test_http_open_resolve_and_viewer_can_explore(self):
        viewer = User.objects.create_user('viewer'); viewer.groups.add(Group.objects.create(name='viewer')); self.client.force_login(viewer)
        body = self.body(user=viewer); root = f'/api/topics/{self.source.pk}/journey/'
        p = self.post(root + 'preview', body); self.assertEqual(p.status_code, 200)
        opened = self.post(root + 'open', dict(**body, mode='inherit', receipt=p.json()['receipt']))
        self.assertEqual(opened.status_code, 200)
        arrived = self.post(f'/api/topics/{self.target.pk}/journey/resolve', dict(receipt=opened.json()['receipt'], direction='forward'))
        self.assertEqual(arrived.status_code, 200); self.assertEqual(arrived.json()['config'], CONFIG)
