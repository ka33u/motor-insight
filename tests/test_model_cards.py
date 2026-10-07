import json,uuid
from unittest.mock import patch
from django.contrib.auth.models import User,Group
from django.test import Client
from app import model_cards
from app.models import AnalysisModel,AnalysisModelCard,AnalysisModelCardVersion,AuditEvent,Record
from .test_platform import PlatformCase
class ModelCardTests(PlatformCase):
 def setUp(self):
  super().setUp();self.record('departments',dict(id='D1',name='生产',owner='SIM'));self.m=AnalysisModel.objects.create(name='部门记录数',dataset='departments',definition=dict(dimension='name',metrics=[dict(agg='count')],chart='table'),owner='system',is_public=True);self.client.force_login(self.quality)
 def preview(self):return self.client.get('/api/model-cards/preview/'+str(self.m.pk)).json()
 def data(self,**changes):return dict(code='MODEL.DEP.COUNT',name='部门计数口径卡',question='哪些部门有来源记录',reader='质量工程师',object_grain='一行一个部门',time_scope='业务截止下当前部门资料',limitations='计数不等于实际人数，不作绩效评价',review_on='2026-10-01',model_id=self.m.pk,receipt=self.preview()['receipt'],request_id=str(uuid.uuid4()),**changes)
 def create(self,data=None):return self.post('/api/model-cards',data or self.data())
 def card(self):return self.create().json()['card']
 def test_create_self_code_binding_no_business_or_shared_model_change(self):
  before=Record.objects.count();d=self.card();self.assertEqual(d['metadata']['code'],'MODEL.DEP.COUNT');self.assertEqual(d['binding']['source_model']['version'],1);self.assertEqual(Record.objects.count(),before);self.m.refresh_from_db();self.assertEqual(self.m.version,1);self.assertTrue(d['review_due'])
 def test_preview_does_not_add_audit_or_card(self):
  self.preview();self.assertEqual(AnalysisModelCard.objects.count(),0);self.assertEqual(AuditEvent.objects.count(),0)
 def test_all_six_roles_private_metadata_on_visible_model(self):
  for role in ['admin','analyst','quality','operations','finance','viewer']:
   user=User.objects.filter(username=role).first() or User.objects.create_user(role);g,_=Group.objects.get_or_create(name=role);user.groups.add(g);self.client.force_login(user);d=self.create().json()['card'];self.assertEqual(d['owner'],role);self.assertEqual(self.client.get('/api/model-cards').json()['total'],1)
  self.assertEqual(AnalysisModelCard.objects.count(),6)
 def test_private_owner_even_admin(self):
  d=self.card();self.client.force_login(self.admin);self.assertEqual(self.client.get('/api/model-cards/'+d['id']).status_code,404);self.assertEqual(self.client.get('/api/model-cards').json()['total'],0)
 def test_same_code_other_owner_allowed_self_duplicate_rejected(self):
  self.card();self.assertEqual(self.create().status_code,400);self.client.force_login(self.admin);self.assertEqual(self.create().status_code,200)
 def test_idempotent_creation_no_duplicate_version_or_audit(self):
  body=self.data();self.assertEqual(self.create(body).status_code,200);r=self.create(body);self.assertTrue(r.json()['repeated']);self.assertEqual(AnalysisModelCardVersion.objects.count(),1);self.assertEqual(AuditEvent.objects.count(),1)
 def test_request_id_different_content_conflict(self):
  body=self.data();self.create(body);body['question']='不同业务问题';self.assertEqual(self.create(body).status_code,409)
 def test_stale_definition_or_expired_receipt_cannot_save(self):
  body=self.data();self.m.name='更正名称';self.m.save();self.assertEqual(self.create(body).status_code,409)
  with patch('django.core.signing.time.time',return_value=0):body=self.data()
  self.assertEqual(self.create(body).status_code,409)
 def test_invalid_unknown_duplicate_and_code_rejected(self):
  for field,value in [('code','model-lower'),('question',''),('model_id',True),('review_on','2026-02-30')]:
   body=self.data();body[field]=value;self.assertEqual(self.create(body).status_code,400)
  body=self.data();body['unknown']=1;self.assertEqual(self.create(body).status_code,400)
  raw=json.dumps(self.data());self.assertEqual(self.client.post('/api/model-cards',raw[:-1]+',"name":"another"}',content_type='application/json').status_code,400)
 def test_update_append_versions_and_stale_revision_conflict(self):
  d=self.card();body=self.data();body.update(revision=d['revision'],question='修改后的业务问题');r=self.post('/api/model-cards/'+d['id'],body);self.assertEqual(r.status_code,200);self.assertEqual(r.json()['card']['revision'],2)
  body['request_id']=str(uuid.uuid4());self.assertEqual(self.post('/api/model-cards/'+d['id'],body).status_code,409);history=self.client.get('/api/model-cards/'+d['id']+'/history').json();self.assertEqual(history['total'],2);self.assertNotEqual(history['rows'][0]['metadata']['question'],history['rows'][1]['metadata']['question'])
 def test_old_version_save_cannot_overwrite(self):
  self.card();v=AnalysisModelCardVersion.objects.get();v.payload['metadata']['name']='覆写'
  with self.assertRaises(Exception):v.save()
 def test_definition_drift_visible_current_run_blocked(self):
  d=self.card();self.m.version+=1;self.m.definition['sort']='desc';self.m.save();r=self.client.get('/api/model-cards/'+d['id']).json();self.assertEqual(r['card']['definition_state'],'changed');self.assertEqual(self.client.get('/api/model-cards/'+d['id']+'/run').status_code,409)
 def test_run_current_data_does_not_capture_or_write(self):
  d=self.card();before=(AuditEvent.objects.count(),AnalysisModelCardVersion.objects.count(),Record.objects.count());r=self.client.get('/api/model-cards/'+d['id']+'/run');self.assertEqual(r.status_code,200);self.assertEqual(r.json()['result_mode'],'current_data');self.assertEqual(r.json()['result']['matched'],1);self.assertEqual(before,(AuditEvent.objects.count(),AnalysisModelCardVersion.objects.count(),Record.objects.count()))
 def test_archive_version_replay_and_restore(self):
  d=self.card();body=dict(request_id=str(uuid.uuid4()),revision=1,archived=True);url='/api/model-cards/'+d['id']+'/archive';a=self.post(url,body);self.assertEqual(a.status_code,200);self.assertEqual(a.json()['card']['revision'],2);self.assertTrue(self.post(url,body).json()['repeated']);self.assertEqual(self.client.get('/api/model-cards/'+d['id']+'/run').status_code,409)
  body.update(request_id=str(uuid.uuid4()),revision=2,archived=False);self.assertEqual(self.post(url,body).status_code,200);self.assertEqual(self.client.get('/api/model-cards/'+d['id']+'/run').status_code,200)
 def test_same_archive_confirmation_request_is_recorded_once(self):
  d=self.card();body=dict(request_id=str(uuid.uuid4()),revision=1,archived=False);url='/api/model-cards/'+d['id']+'/archive';self.assertEqual(self.post(url,body).status_code,200);self.assertTrue(self.post(url,body).json()['repeated']);self.assertEqual(AnalysisModelCardVersion.objects.count(),2)
 def test_audit_failure_rolls_back_entire_definition(self):
  body=self.data()
  with patch('app.model_cards.AuditEvent.objects.create',side_effect=RuntimeError('audit failed')):
   with self.assertRaises(RuntimeError):self.create(body)
  self.assertEqual(AnalysisModelCard.objects.count(),0);self.assertEqual(AnalysisModelCardVersion.objects.count(),0)
 def test_private_or_financial_source_permission(self):
  self.m.is_public=False;self.m.owner='other';self.m.save();self.assertEqual(self.client.get('/api/model-cards/preview/'+str(self.m.pk)).status_code,404)
  self.m.is_public=True;self.m.dataset='costs';self.m.save();self.assertEqual(self.client.get('/api/model-cards/preview/'+str(self.m.pk)).status_code,400)
 def test_money_field_model_not_visible_to_quality(self):
  self.m.dataset='products';self.m.definition=dict(dimension='id',metrics=[dict(agg='sum',field='price_cents')],chart='table');self.m.save();self.assertEqual(self.client.get('/api/model-cards/preview/'+str(self.m.pk)).status_code,400)
 def test_lost_source_visibility_removes_all_history_and_exports(self):
  d=self.card();self.m.is_public=False;self.m.owner='other';self.m.save()
  for tail in ['', '/history','/export','/run']:self.assertEqual(self.client.get('/api/model-cards/'+d['id']+tail).status_code,404)
  self.assertEqual(self.client.get('/api/model-cards').json()['unavailable'],1)
 def test_export_full_versions_no_result_and_audit(self):
  d=self.card();body=self.data();body.update(revision=1);self.post('/api/model-cards/'+d['id'],body);r=self.client.get('/api/model-cards/'+d['id']+'/export');self.assertEqual(r.status_code,200);self.assertEqual(len(r.json()['versions']),2);self.assertNotIn('result',r.json());self.assertEqual(r['Cache-Control'],'no-store');self.assertEqual(AuditEvent.objects.filter(action='model_card.export').count(),1)
 def test_queries_must_be_declared_not_silently_ignored(self):
  for suffix in ['?unknown=1','?archived=3','?archived=0&archived=1']:self.assertEqual(self.client.get('/api/model-cards'+suffix).status_code,400)
 def test_capture_binding_or_rule_tamper_detected(self):
  d=self.card();v=AnalysisModelCardVersion.objects.get();payload=v.payload;payload['metadata']['name']='破坏摘要';AnalysisModelCardVersion.objects.filter(pk=v.pk).update(payload=payload);self.assertEqual(self.client.get('/api/model-cards/'+d['id']).status_code,409)
 def test_current_user_bound_receipt_and_rules(self):
  body=self.data();self.client.force_login(self.admin);self.assertEqual(self.create(body).status_code,409);body=self.data()
  with patch('app.model_cards.rules',return_value='changed'):self.assertEqual(self.create(body).status_code,409)
 def test_current_data_changes_do_not_become_a_historical_result(self):
  d=self.card();self.record('departments',dict(id='D2',name='质量',owner='SIM'));r=self.client.get('/api/model-cards/'+d['id']+'/run').json();self.assertEqual(r['result']['matched'],2);self.assertEqual(r['card']['definition_state'],'same');self.assertEqual(AnalysisModelCardVersion.objects.count(),1)
 def test_dataset_grain_change_is_not_silently_accepted(self):
  d=self.card();from app import semantic_schema
  schemas=semantic_schema.schemas();schemas['departments']={**schemas['departments'],'grain':'改变后的对象粒度'}
  with patch('app.model_cards.semantic_schema.schemas',return_value=schemas):
   self.assertEqual(self.client.get('/api/model-cards/'+d['id']).json()['card']['definition_state'],'changed');self.assertEqual(self.client.get('/api/model-cards/'+d['id']+'/run').status_code,409)
 def test_update_and_archive_audit_failure_roll_back_revision(self):
  d=self.card();body=self.data();body['revision']=1
  with patch('app.model_cards.AuditEvent.objects.create',side_effect=RuntimeError('audit failed')):
   with self.assertRaises(RuntimeError):self.post('/api/model-cards/'+d['id'],body)
   with self.assertRaises(RuntimeError):self.post('/api/model-cards/'+d['id']+'/archive',dict(request_id=str(uuid.uuid4()),revision=1,archived=True))
  c=AnalysisModelCard.objects.get();self.assertEqual(c.revision,1);self.assertFalse(c.archived);self.assertEqual(AnalysisModelCardVersion.objects.count(),1)
 def test_deleted_current_model_does_not_release_saved_definition(self):
  d=self.card();self.m.delete();self.assertEqual(self.client.get('/api/model-cards/'+d['id']).status_code,404);self.assertEqual(self.client.get('/api/model-cards').json()['unavailable'],1)
 def published_metric_model(self):
  from tests.test_metric_registry import payload
  self.record('energy',dict(id='E1',workshop='A',kwh=40));self.client.force_login(self.admin)
  r=self.post('/api/metrics',dict(key='CARD_ENERGY',dataset='energy',payload=payload()));self.assertEqual(r.status_code,200,r.content);v=r.json()
  v=self.post('/api/metrics/'+str(v['id']),dict(action='submit',revision=v['revision'])).json();self.client.force_login(self.quality)
  v=self.post('/api/metrics/'+str(v['id']),dict(action='publish',revision=v['revision'],reason='核对合成计量范围')).json()
  self.m.dataset='energy';self.m.definition=dict(metric_ref=dict(key=v['key'],version=v['version']),filters=[],chart='table');self.m.save();return v
 def test_published_timestamp_survives_hash_json_storage_and_current_run(self):
  v=self.published_metric_model();d=self.card();self.assertIsInstance(d['binding']['metric']['published_at'],str)
  loaded=self.client.get('/api/model-cards/'+d['id']).json()['card'];self.assertEqual(loaded['definition_state'],'same');self.assertEqual(loaded['binding'],d['binding'])
  run=self.client.get('/api/model-cards/'+d['id']+'/run');self.assertEqual(run.status_code,200,run.content);self.assertEqual(run.json()['result']['rows'][0]['m0'],40)
 def test_pinned_metric_retirement_changes_state_and_pauses_card(self):
  v=self.published_metric_model();d=self.card();self.assertEqual(self.post('/api/metrics/'+str(v['id']),dict(action='retire',revision=v['revision'],reason='模拟停用演练')).status_code,200)
  self.assertEqual(self.client.get('/api/model-cards/'+d['id']).json()['card']['definition_state'],'changed');self.assertEqual(self.client.get('/api/model-cards/'+d['id']+'/run').status_code,409)
  self.assertEqual(self.client.get('/api/model-cards/'+d['id']+'/history').json()['rows'][0]['binding']['metric']['status'],'published')
 def test_published_calculation_drift_cannot_run_despite_visible_definition(self):
  self.published_metric_model();d=self.card()
  with patch('app.metric_registry.calculation_hash',return_value='changed'):
   self.assertEqual(self.client.get('/api/model-cards/'+d['id']+'/run').status_code,400)
 def test_grouping_version_remains_pinned_until_model_reference_changes(self):
  from tests.test_business_groups import payload
  from app import business_groups as bg
  self.client.force_login(self.admin);self.record('products',dict(id='P1',power_kw=7.5,family='YE3'))
  saved=bg.save(self.admin,dict(code='CARD.POWER',payload=payload()));ref=saved['versions'][0]['ref'];self.m.dataset='products';self.m.definition=dict(dimension='power_kw',grain='value',grouping_ref=ref,metrics=[dict(agg='count')],chart='bar');self.m.save();d=self.card()
  p=payload();p['rules'][0]['upper']='10';p['rules'][1]['lower']='10';new=bg.save(self.admin,dict(revision=1,payload=p),saved['id'])
  run=self.client.get('/api/model-cards/'+d['id']+'/run');self.assertEqual(run.status_code,200,run.content);self.assertEqual(run.json()['result']['rows'][0]['dimension'],'中功率')
  self.m.definition['grouping_ref']=new['versions'][0]['ref'];self.m.version+=1;self.m.save();self.assertEqual(self.client.get('/api/model-cards/'+d['id']).json()['card']['definition_state'],'changed');self.assertEqual(self.client.get('/api/model-cards/'+d['id']+'/run').status_code,409)
