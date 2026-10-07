import json
from copy import deepcopy
from pathlib import Path
from django.conf import settings
from django.contrib.auth.models import Group,User
from django.test import TestCase,SimpleTestCase,Client
from app.bi_design_drafts import parse_input,build_draft
from app.models import Record,AnalysisModel,AuditEvent

CATALOG=Path(settings.BASE_DIR)/'data/bi_design.json'
VALUE=dict(model='VERSION',need='I-07',metric='K14',format='analysis',code='ANA.PURCHASE.PROMISE',question='供应商是否通过改期掩盖原承诺逾期？',owner='采购',scope='按原承诺到货日期选队列；原版与当前有效版分别核对；截止时点待确认')


class DraftDefinitionTests(SimpleTestCase):
    def test_all_model_format_combinations_remain_proposals(self):
        d=json.loads(CATALOG.read_text());before=deepcopy(d)
        for model in d['framework']['model_library']:
            for fmt in d['framework']['presentation_choices']:
                p=build_draft(d,VALUE|dict(model=model['id'],need=model['example_need_id'],metric=model['metric_ids'][0] if model['metric_ids'] else '',format=fmt['id']))
                self.assertEqual(p['state'],'设计草稿，待业务与数据评审')
                self.assertEqual(p['model']['id'],model['id']);self.assertEqual(p['presentation']['id'],fmt['id']);self.assertGreaterEqual(len(p['pending_confirmations']),7)
        self.assertEqual(d,before)

    def test_invalid_fields_and_catalog_references(self):
        d=json.loads(CATALOG.read_text())
        for field,value in [('code','../x'),('model','X'),('need','I-999'),('metric','K999'),('format','X'),('owner',''),('scope',''),('question',''),('scope','x'*2001),('owner',7)]:
            with self.subTest(field=field),self.assertRaises(ValueError):build_draft(d,VALUE|{field:value})

    def test_strict_json_and_duplicate_keys(self):
        for raw in ['[]','{}','null','{"model":"VERSION","model":"STATUS"}',json.dumps(VALUE|{'extra':'x'})]:
            with self.subTest(raw=raw),self.assertRaises(ValueError):parse_input(raw)
        self.assertEqual(parse_input(json.dumps(VALUE)),VALUE)

    def test_unspecified_metric_explicitly_pending(self):
        p=build_draft(json.loads(CATALOG.read_text()),VALUE|{'metric':''})
        self.assertIsNone(p['metric_candidate']);self.assertIn('主指标及可计算定义',p['pending_confirmations'])


class DraftExportTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user=User.objects.create_user('draft_viewer',password='test-only');cls.user.groups.add(Group.objects.create(name='viewer'))

    def export(self,value=VALUE,client=None):
        return (client or self.client).post('/api/catalog/design-draft/export',{'draft_input':json.dumps(value)})

    def test_authentication_and_method(self):
        self.assertEqual(self.export().status_code,401);self.client.force_login(self.user)
        self.assertEqual(self.client.get('/api/catalog/design-draft/export').status_code,405)

    def test_export_is_catalog_backed_and_does_not_write(self):
        self.client.force_login(self.user);before=[m.objects.count() for m in [Record,AnalysisModel,AuditEvent]]
        response=self.export();self.assertEqual(response.status_code,200)
        self.assertEqual(response['Cache-Control'],'no-store');self.assertIn('attachment',response['Content-Disposition'])
        payload=json.loads(b''.join(response.streaming_content));self.assertEqual(payload,build_draft(json.loads(CATALOG.read_text()),VALUE))
        self.assertEqual(payload['requirement']['implementation'],'模拟部分覆盖');self.assertEqual(payload['metric_candidate']['id'],'K14')
        self.assertEqual([m.objects.count() for m in [Record,AnalysisModel,AuditEvent]],before)

    def test_bad_definition_and_extra_request_fields(self):
        self.client.force_login(self.user);self.assertEqual(self.export(VALUE|{'metric':'K999'}).status_code,400)
        self.assertEqual(self.client.post('/api/catalog/design-draft/export',{'draft_input':json.dumps(VALUE),'publish':1}).status_code,400)

    def test_csrf_required(self):
        c=Client(enforce_csrf_checks=True);c.force_login(self.user);self.assertEqual(self.export(client=c).status_code,403)
        c.get('/');token=c.cookies['csrftoken'].value
        response=c.post('/api/catalog/design-draft/export',{'draft_input':json.dumps(VALUE),'csrfmiddlewaretoken':token});self.assertEqual(response.status_code,200)
