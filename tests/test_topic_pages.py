import copy,json,uuid
from unittest.mock import patch
from django.contrib.auth.models import User,Group
from django.core.exceptions import ValidationError,PermissionDenied
from django.test import Client
from app import topic_pages as p,topic_workspace as ws,topic_snapshots as ss,topic_linkage
from app.models import Topic,AnalysisModel,Record,AuditEvent,TopicPage,TopicPageVersion,TopicPageRequest
from app.import_review import ReviewConflict
from tests.test_platform import PlatformCase
CONF={'scope':{'from':'2026-09-25'},'reference_scope':{'to':'2026-09-24'},'primary_label':'观察日','reference_label':'比较日'}
class TopicPageTests(PlatformCase):
 def setUp(self):
  super().setUp();self.client.force_login(self.admin)
  self.model=AnalysisModel.objects.create(name='原能耗口径',dataset='energy',definition={'dimension':'workshop','metrics':[{'agg':'sum','field':'kwh'}],'chart':'bar'},owner='admin',is_public=True)
  self.topic=Topic.objects.create(name='来源专题',layout=[{'model_id':self.model.pk,'span':1},{'model_id':self.model.pk,'span':2}],owner='admin',is_public=True)
  self.target=Topic.objects.create(name='同期间目标',layout=[{'model_id':self.model.pk,'span':2}],owner='admin',is_public=True)
  for key,day,val in [('E1','24',10),('E2','25',20)]:self.record('energy',{'id':key,'workshop':'绕组','started':f'2026-09-{day}T08:00:00','ended':f'2026-09-{day}T10:00:00','kwh':val,'tariff_cents':100})
 def definition(self):
  return dict(topic_id=self.topic.pk,code='PAGE.ENERGY.DAILY.0001',title='车间能耗复查',question='哪些读数需要回查？',cadence='每日核对，处理后复查',sections=[dict(id='RESULT',title='结果',role='result',note='检查时间和单位',cards=[dict(slot=1,span=1,title='先看同范围',note='数据来自原模型')]),dict(id='OBJECTS',title='回查对象',role='objects',note='',cards=[dict(slot=0,span=2,title='',note='')])],navigation=[dict(topic_id=self.target.pk,label='继续核查',mode='inherit')])
 def body(self,user=None,d=None):
  d=d or self.definition();u=user or self.admin;preview=p.preview(u,d)
  return dict(request_id=str(uuid.uuid4()),definition=d,receipt=preview['receipt'],reason='核对原口径后建立每日阅读顺序')
 def save(self,user=None,d=None):return p.save(user or self.admin,self.body(user,d))
 def read(self,r,user=None):return p.read(user or self.admin,r['id'])
 def nav(self,r,conf=None,index=0,user=None):
  u=user or self.admin;d=self.read(r,u);return p.navigation(u,r['id'],dict(version=d['version'],receipt=d['receipt'],index=index,config=copy.deepcopy(CONF if conf is None else conf)))
 def test_create_normal_api_is_private_metadata_without_fact_changes(self):
  before=list(Record.objects.values());topic=copy.deepcopy(self.topic.layout);model=copy.deepcopy(self.model.definition)
  r=self.post('/api/topic-pages',self.body());self.assertEqual(r.status_code,200);v=self.read(r.json());self.assertTrue(v['ready']);self.assertFalse(v['stale']);self.assertEqual(v['definition'],self.definition())
  self.assertEqual(list(Record.objects.values()),before);self.topic.refresh_from_db();self.model.refresh_from_db();self.assertEqual(self.topic.layout,topic);self.assertEqual(self.model.definition,model)
  self.assertEqual((TopicPage.objects.count(),TopicPageVersion.objects.count(),TopicPageRequest.objects.count()),(1,1,1));self.assertFalse(TopicPageVersion.objects.get().payload.get('result'));self.assertFalse(AuditEvent.objects.get(action='topic_page.create').detail['business_facts_changed'])
 def test_definition_validation_rejects_unknown_malformed_and_bool_fields(self):
  mutations=[lambda d:d.update(extra=1),lambda d:d.update(topic_id=True),lambda d:d.update(code='page.lower'),lambda d:d.update(code='A'),lambda d:d.update(title='bad\x00'),lambda d:d.update(question=' '),lambda d:d.update(sections=[]),lambda d:d['sections'][0].update(extra=1),lambda d:d['sections'][0].update(id='1BAD'),lambda d:d['sections'][0].update(role='unknown'),lambda d:d['sections'][0]['cards'][0].update(span=True),lambda d:d['sections'][0]['cards'][0].update(slot=True),lambda d:d['sections'][0]['cards'][0].update(slot=12),lambda d:d['navigation'][0].update(mode='silent'),lambda d:d['navigation'][0].update(topic_id=self.topic.pk),lambda d:d.update(navigation=d['navigation']*2)]
  for mutate in mutations:
   d=self.definition();mutate(d)
   with self.subTest(d=d),self.assertRaises(ValidationError):p.preview(self.admin,d)
 def test_all_original_slots_exactly_once_including_unavailable_cards(self):
  for kind in ('duplicate','missing','unknown'):
   d=self.definition()
   if kind=='duplicate':d['sections'][1]['cards'][0]['slot']=1
   elif kind=='missing':d['sections'].pop()
   else:d['sections'][1]['cards'][0]['slot']=8
   with self.subTest(kind=kind),self.assertRaises(ValidationError):p.preview(self.admin,d)
  self.model.dataset='costs';self.model.definition={'metrics':[{'agg':'sum','field':'amount_cents'}]};self.model.save()
  result=p.preview(self.quality,self.definition());self.assertEqual(result['unavailable_cards'],2);r=self.save(self.quality);self.assertTrue(self.read(r,self.quality)['ready']);self.assertNotIn('原能耗口径',json.dumps(result,ensure_ascii=False))
 def test_three_primary_cards_limit_is_global_and_other_sections_allowed(self):
  self.topic.layout=self.topic.layout*2;self.topic.save();d=self.definition();d['sections'][0]['cards']=[dict(slot=i,span=1,title='',note='') for i in range(3)];d['sections'][1]['cards']=[dict(slot=3,span=2,title='',note='')];p.preview(self.admin,d)
  d['sections'][1]['role']='result'
  with self.assertRaises(ValidationError):p.preview(self.admin,d)
 def test_cross_owner_same_code_allowed_and_all_read_operations_isolated(self):
  r=self.save(self.quality);self.save(self.admin);self.assertEqual(TopicPage.objects.count(),2)
  for suffix in ('','/history','/export?receipt=bad'):
   self.assertEqual(self.client.get('/api/topic-pages/'+r['id']+suffix).status_code,404)
  self.assertEqual(len(self.client.get('/api/topic-pages').json()['rows']),1)
  with self.assertRaises(TopicPage.DoesNotExist):p.navigation(self.admin,r['id'],dict(version=1,receipt='bad',index=0,config=CONF))
 def test_same_owner_code_unique_and_identity_fixed_after_create(self):
  r=self.save()
  with self.assertRaises(ReviewConflict):self.save()
  for field,value in [('code','PAGE.NEW.001'),('topic_id',self.target.pk)]:
   d=self.definition();d[field]=value
   if field=='topic_id':d['navigation']=[];d['sections']=d['sections'][:1];d['sections'][0]['cards'][0]['slot']=0
   b=self.body(d=d);b['revision']=1
   with self.assertRaises(ValidationError):p.save(self.admin,b,r['id'])
 def test_six_roles_can_arrange_only_personal_presentation(self):
  for role in ('admin','analyst','operations','quality','finance','viewer'):
   u=self.admin if role=='admin' else self.quality if role=='quality' else User.objects.create_user('u_'+role)
   if role not in ('admin','quality'):u.groups.add(Group.objects.get_or_create(name=role)[0])
   with self.subTest(role=role):r=self.save(u);self.assertTrue(self.read(r,u)['ready'])
  self.assertEqual(TopicPage.objects.count(),6)
 def test_fresh_account_role_disabled_and_conflict_block(self):
  b=self.body();self.admin.is_active=False;self.admin.save()
  with self.assertRaises(PermissionDenied):p.save(self.admin,b)
  self.admin.is_active=True;self.admin.save();self.admin.groups.add(Group.objects.get(name='quality'))
  with self.assertRaises(PermissionDenied):p.preview(self.admin,self.definition())
 def test_preview_receipt_rejects_tamper_expiry_content_rule_role_or_topic_drift(self):
  b=self.body()
  for kind in ('tamper','expire','content','rules','role','topic'):
   with self.subTest(kind=kind):
    body=copy.deepcopy(b)
    if kind=='tamper':body['receipt']='bad'
    elif kind=='content':body['definition']['title']='另一个标题'
    elif kind=='topic':self.topic.version+=1;self.topic.save()
    elif kind=='role':self.admin.groups.clear();self.admin.groups.add(Group.objects.get(name='quality'))
    if kind=='expire':
     with patch('django.core.signing.time.time',return_value=4000000000),self.assertRaises(ReviewConflict):p.save(self.admin,body)
    elif kind=='rules':
     with patch('app.topic_pages.rules',return_value='new-rules'),self.assertRaises(ReviewConflict):p.save(self.admin,body)
    else:
     with self.assertRaises(ReviewConflict):p.save(self.admin,body)
    self.admin.groups.clear();self.admin.groups.add(Group.objects.get(name='admin'));self.topic.version=1;self.topic.save()
  self.assertFalse(TopicPage.objects.exists())
 def test_target_drift_invalidates_preview_and_saved_page_until_new_version(self):
  b=self.body();self.target.version+=1;self.target.save()
  with self.assertRaises(ReviewConflict):p.save(self.admin,b)
  r=self.save();self.target.version+=1;self.target.save();self.assertTrue(self.read(r)['stale'])
  with self.assertRaises(ReviewConflict):self.nav(r)
  b=self.body();b['revision']=1;new=p.save(self.admin,b,r['id']);self.assertEqual(new['version'],2);self.assertTrue(self.read(new)['ready'])
 def test_version_update_retains_original_payload_and_optimistic_revision(self):
  r=self.save();v1=copy.deepcopy(TopicPageVersion.objects.get().payload);d=self.definition();d['sections'].reverse();d['title']='新的阅读次序';b=self.body(d=d);b['revision']=1
  updated=p.save(self.admin,b,r['id']);self.assertEqual((updated['version'],updated['revision']),(2,2));self.assertEqual(TopicPageVersion.objects.get(number=1).payload,v1)
  with self.assertRaises(ReviewConflict):p.save(self.admin,{**b,'request_id':str(uuid.uuid4())},r['id'])
  historical=p.read(self.admin,r['id'],1);self.assertEqual(historical['definition']['title'],self.definition()['title']);self.assertTrue(historical['ready']);self.assertEqual(historical['current_version'],2)
 def test_immutable_history_and_hash_corruption_pause_read_list_export(self):
  r=self.save();v=TopicPageVersion.objects.get()
  with self.assertRaises(ValidationError):v.save()
  TopicPageVersion.objects.filter(pk=v.pk).update(payload={'broken':True})
  for url in ['/api/topic-pages','/api/topic-pages/'+r['id'],'/api/topic-pages/'+r['id']+'/history']:
   self.assertEqual(self.client.get(url).status_code,409)
 def test_create_and_update_exact_replay_and_collision_have_single_audit(self):
  b=self.body();r=p.save(self.admin,b);self.assertTrue(p.save(self.admin,{**b,'receipt':'expired retry'})['replayed']);self.assertEqual(TopicPageVersion.objects.count(),1)
  with self.assertRaises(ReviewConflict):p.save(self.admin,{**b,'reason':'改变原操作内容不能再用此编号'})
  with self.assertRaises(ReviewConflict):p.save(self.quality,b)
  b2=self.body();b2['revision']=1;p.save(self.admin,b2,r['id']);self.assertTrue(p.save(self.admin,b2,r['id'])['replayed']);self.assertEqual(TopicPageVersion.objects.count(),2);self.assertEqual(AuditEvent.objects.filter(action__startswith='topic_page.').count(),2)
 def test_archive_restore_revision_replay_and_no_history_deletion(self):
  r=self.save();b=dict(request_id=str(uuid.uuid4()),revision=1,archived=True,reason='暂时停用每日阅读页面')
  p.archive(self.admin,r['id'],b);self.assertTrue(p.archive(self.admin,r['id'],b)['replayed']);self.assertFalse(self.read(r)['ready']);self.assertEqual(TopicPageVersion.objects.count(),1)
  with self.assertRaises(ValidationError):p.save(self.admin,{**self.body(),'revision':2},r['id'])
  with self.assertRaises(ReviewConflict):p.archive(self.admin,r['id'],{**b,'request_id':str(uuid.uuid4()),'archived':False})
  p.archive(self.admin,r['id'],{**b,'request_id':str(uuid.uuid4()),'revision':2,'archived':False,'reason':'核对页面用途后恢复使用'});self.assertTrue(self.read(r)['ready'])
 def test_audit_failure_rolls_back_creation_update_and_archive_atomically(self):
  with patch('app.topic_pages.AuditEvent.objects.create',side_effect=RuntimeError('audit unavailable')):
   with self.assertRaises(RuntimeError):self.save()
  self.assertEqual((TopicPage.objects.count(),TopicPageVersion.objects.count(),TopicPageRequest.objects.count()),(0,0,0))
  r=self.save()
  with patch('app.topic_pages.AuditEvent.objects.create',side_effect=RuntimeError('audit unavailable')):
   with self.assertRaises(RuntimeError):p.save(self.admin,{**self.body(),'revision':1},r['id'])
   with self.assertRaises(RuntimeError):p.archive(self.admin,r['id'],dict(request_id=str(uuid.uuid4()),revision=1,archived=True,reason='核对后暂时归档页面'))
  self.assertEqual((self.read(r)['revision'],TopicPageVersion.objects.count(),TopicPageRequest.objects.count()),(1,1,1));self.assertFalse(self.read(r)['archived'])
 def test_navigation_exact_both_scopes_labels_links_and_no_fact_writes(self):
  r=self.save();conf={**CONF,'links':dict(revision=topic_linkage.REVISION,rules_hash=topic_linkage.rules_hash(),selections=[dict(kind='workshop',value='绕组')])};before=list(Record.objects.values());audit=AuditEvent.objects.count();v=self.nav(r,conf)
  self.assertEqual(v['config'],conf);self.assertEqual(v['context_token'],ws.context(self.admin,self.target.pk)['context_token']);self.assertEqual(list(Record.objects.values()),before);self.assertEqual(AuditEvent.objects.count(),audit)
 def test_navigation_explicit_new_resets_all_ranges_comparison_and_links(self):
  d=self.definition();d['navigation'][0]['mode']='new';r=self.save(d=d);v=self.nav(r,{'scope':{'sql':'forbidden'}});self.assertEqual(v['config'],dict(scope={},reference_scope=None,primary_label='当前范围',reference_label='对照范围'));self.assertNotIn('links',v['config'])
 def test_navigation_unsupported_family_customer_link_and_period_fail_without_dropping(self):
  r=self.save()
  for conf in [{**CONF,'scope':{'family':'YE4'}},{**CONF,'reference_scope':{'customer_id':'C01'}},{**CONF,'links':dict(revision=topic_linkage.REVISION,rules_hash=topic_linkage.rules_hash(),selections=[dict(kind='unit',value='SN001')])}]:
   with self.subTest(conf=conf),self.assertRaises(ReviewConflict):self.nav(r,conf)
  self.model.dataset='equipment';self.model.definition={'metrics':[{'agg':'count'}]};self.model.save();r=self.save(d={**self.definition(),'code':'PAGE.OTHER.001'})
  with self.assertRaises(ReviewConflict):self.nav(r)
 def test_navigation_date_role_mismatch_with_same_iso_bounds_pauses(self):
  r=self.save();original=ws.context
  def context(user,key):
   c=original(user,key)
   if key==self.target.pk:
    for card in c['cards']:card['contract']['date_label']='检测发生日'
   return c
  with patch('app.topic_pages.ws.context',side_effect=context),self.assertRaises(ReviewConflict):self.nav(r)
 def test_navigation_unavailable_target_card_denies_and_new_mode_remains_explicit(self):
  self.model.dataset='costs';self.model.definition={'metrics':[{'agg':'sum','field':'amount_cents'}]};self.model.save();r=self.save(self.quality)
  with self.assertRaises(PermissionDenied):self.nav(r,dict(scope={},reference_scope=None,primary_label='当前',reference_label='比较'),user=self.quality)
 def test_navigation_pointer_change_and_wrong_receipt_or_index_rejected(self):
  r=self.save();d=self.read(r);p.save(self.admin,{**self.body(),'revision':1},r['id']);body=dict(version=1,receipt=d['receipt'],index=0,config=CONF)
  with self.assertRaises(ReviewConflict):p.navigation(self.admin,r['id'],body)
  d=self.read(r)
  for index in (True,-1,1):
   with self.subTest(index=index),self.assertRaises(ValidationError):p.navigation(self.admin,r['id'],{**body,'version':2,'receipt':d['receipt'],'index':index})
 def test_private_source_or_target_visibility_revoked_blocks_read(self):
  r=self.save(self.quality);self.target.is_public=False;self.target.save()
  with self.assertRaises(Topic.DoesNotExist):self.read(r,self.quality)
  self.target.is_public=True;self.target.save();self.topic.is_public=False;self.topic.save()
  with self.assertRaises(Topic.DoesNotExist):self.read(r,self.quality)
 def test_changed_facts_do_not_turn_layout_into_snapshot_or_invalidate_definition(self):
  r=self.save();Record.objects.filter(business_key='E2').update(values={'id':'E2','workshop':'绕组','started':'2026-09-25T08:00:00','ended':'2026-09-25T10:00:00','kwh':99,'tariff_cents':100});self.assertTrue(self.read(r)['ready']);self.assertFalse(self.read(r)['stale'])
 def test_original_numeric_evidence_export_and_snapshot_unaffected_by_page(self):
  ctx=ws.context(self.admin,self.topic.pk);body=dict(context_token=ctx['context_token'],config=CONF);run=ws.run(self.admin,self.topic.pk,body);evidence=dict(context_token=ctx['context_token'],facts_token=run['facts_token'],config=CONF,slot=0,side='primary',group=None,page=1);ev=ws.evidence(self.admin,self.topic.pk,evidence)
  snapshot=ss.create(self.admin,self.topic.pk,dict(request_id=str(uuid.uuid4()),context_token=ctx['context_token'],facts_token=run['facts_token'],config=CONF,name='原分析结果',note='保存原模型同范围结果和来源'));payload=copy.deepcopy(snapshot.payload)
  self.save();after=ws.run(self.admin,self.topic.pk,body);self.assertEqual(after,run);self.assertEqual(ws.evidence(self.admin,self.topic.pk,evidence),ev);snapshot.refresh_from_db();self.assertEqual(snapshot.payload,payload)
 def test_export_metadata_only_hash_bound_historical_and_stale_labelled(self):
  r=self.save();d=self.read(r);url='/api/topic-pages/'+r['id']+'/export';response=self.client.get(url,dict(version=1,receipt=d['receipt']));self.assertEqual(response.status_code,200);doc=json.loads(response.content);self.assertFalse(doc['contains_business_values']);self.assertNotIn('receipt',doc);self.assertEqual(doc['payload_hash'],d['payload_hash']);self.assertEqual(response['Cache-Control'],'no-store')
  self.model.version+=1;self.model.save();self.assertEqual(self.client.get(url,dict(version=1,receipt=d['receipt'])).status_code,409);d=self.read(r);doc=json.loads(self.client.get(url,dict(version=1,receipt=d['receipt'])).content);self.assertTrue(doc['stale']);self.assertEqual(doc['version'],1)
 def test_export_audit_failure_does_not_return_success_or_persist_audit(self):
  r=self.save();d=self.read(r);before=AuditEvent.objects.count()
  with patch('app.topic_page_views.AuditEvent.objects.create',side_effect=RuntimeError('failed')):
   with self.assertRaises(RuntimeError):self.client.get('/api/topic-pages/'+r['id']+'/export',dict(version=1,receipt=d['receipt']))
  self.assertEqual(AuditEvent.objects.count(),before)
 def test_auth_csrf_methods_and_strict_parameters(self):
  secure=Client(enforce_csrf_checks=True);secure.force_login(self.admin);self.assertEqual(secure.post('/api/topic-pages/preview',json.dumps(self.definition()),content_type='application/json').status_code,403)
  r=self.save();base='/api/topic-pages/'+r['id']
  for query in ('?version=0','?version=true','?version=1&version=2','?extra=1'):self.assertEqual(self.client.get(base+query).status_code,400)
  self.assertEqual(self.client.delete(base).status_code,405);self.client.logout();self.assertEqual(self.client.get(base).status_code,401)
