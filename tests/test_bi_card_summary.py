"""Population mathematics, provenance and exact-scope summary delivery."""
import copy,csv,io,json,uuid
from unittest.mock import patch
from django.contrib.auth.models import Group
from django.core.exceptions import PermissionDenied
from django.test import Client,SimpleTestCase
from app import bi_card_summary as bc,topic_workspace as ws,topic_snapshots as ss
from app.models import AnalysisModel,Topic,Record,AuditEvent,TopicSnapshot
from app.analysis_engine import run_analysis
from app.import_review import ReviewConflict
from tests.test_platform import PlatformCase

CONF=dict(scope={},reference_scope=None,primary_label='全部来源',reference_label='对照范围')

class PopulationSummaryTests(PlatformCase):
 def setUp(self):
  super().setUp();self.client.force_login(self.admin)
  self.model=AnalysisModel.objects.create(name='整范围分析',dataset='energy',definition={'dimension':'workshop','metrics':[{'agg':'sum','field':'kwh'}],'chart':'table'},owner='admin',is_public=True)
  self.topic=Topic.objects.create(name='整范围专题',layout=[{'model_id':self.model.pk}],owner='admin',is_public=True)
 def energy(self,key,value,group='A',day='25'):
  return self.record('energy',dict(id=key,workshop=group,kwh=value,tariff_cents=100,started=f'2026-09-{day}T08:00:00',ended=f'2026-09-{day}T09:00:00'))
 def define(self,d,dataset='energy'):
  self.model.dataset=dataset;self.model.definition=d;self.model.save()
 def run_topic(self,conf=None,user=None):
  user=user or self.admin;return ws.run(user,self.topic.pk,dict(context_token=ws.context(user,self.topic.pk)['context_token'],config=copy.deepcopy(conf or CONF)))
 def summary(self,**kw):return self.run_topic(**kw)['cards'][0]['scope_summary']['primary']
 def body(self,result):return dict(request_id=str(uuid.uuid4()),context_token=result['context_token'],facts_token=result['facts_token'],summary_token=result['summary_token'],config=result['config'],name='整范围快照',note='合成资料核查演练用途')
 def query(self,result):return {k:result[k] for k in ['context_token','facts_token','summary_token']}|{'config':json.dumps(result['config'])}
 def export(self,result):return self.client.get(f'/api/topics/{self.topic.pk}/summary/export',self.query(result))
 def test_whole_mean_is_not_mean_of_group_means(self):
  for i,(g,v) in enumerate([('A',10),('A',20),('B',90)]):self.energy(str(i),v,g)
  self.define({'dimension':'workshop','metrics':[{'agg':'avg','field':'kwh'}],'chart':'table'})
  r=self.run_topic();s=r['cards'][0]['scope_summary']['primary'];self.assertEqual(s['value'],40);self.assertEqual(s['source_rows'],3);self.assertEqual(s['unit'],'kWh');self.assertNotEqual(s['value'],52.5)
 def test_ratio_pools_numerators_and_denominators(self):
  self.define({'dimension':'family','metrics':[{'agg':'ratio','field':'on_time_plan_count','denominator':'due_plan_count'}],'chart':'table'},'bi_order_lines')
  rows=[dict(id='L1',family='YE3',order_date='2026-09-25',on_time_plan_count=1,due_plan_count=1),dict(id='L2',family='YE4',order_date='2026-09-25',on_time_plan_count=1,due_plan_count=9)]
  with patch('app.analysis_engine.semantic.rows',return_value=rows):s=self.summary()
  self.assertEqual((s['value'],s['numerator'],s['denominator'],s['unit']),(20,2,10,'%'))
 def test_distinct_is_deduplicated_across_groups(self):
  for i,g in enumerate(['A','A','B']):self.energy(str(i),10,g)
  self.define({'dimension':'id','metrics':[{'agg':'distinct','field':'workshop'}],'chart':'table'})
  r=self.run_topic();self.assertEqual(sum(x['m0'] for x in r['cards'][0]['primary']['rows']),3);self.assertEqual(r['cards'][0]['scope_summary']['primary']['value'],2)
 def test_quantiles_use_full_population(self):
  for i,v in enumerate([1,2,3,100]):self.energy(str(i),v,'A' if i<3 else 'B')
  for agg,expected in [('median',2.5),('p90',70.9),('p95',85.45)]:
   with self.subTest(agg=agg):
    self.define({'dimension':'workshop','metrics':[{'agg':'median' if agg=='median' else 'percentile','field':'kwh',**({} if agg=='median' else {'percentile':int(agg[1:])})}],'chart':'table'});s=self.summary();self.assertAlmostEqual(s['value'],expected);self.assertIsNotNone(s['quantile'])
 def test_selected_m1_is_not_replaced_by_m0(self):
  self.energy('1',4);self.energy('2',8)
  self.define({'dimension':'workshop','metrics':[{'agg':'count'},{'agg':'avg','field':'kwh'}],'display_metric':'m1','chart':'table'})
  s=self.summary();self.assertEqual((s['key'],s['value'],s['unit']),('m1',6,'kWh'))
 def test_derived_d2_reindexes_only_its_dependencies(self):
  for i,v in enumerate([4,8]):self.energy(str(i),v)
  self.define({'dimension':'workshop','metrics':[{'agg':'count'},{'agg':'sum','field':'kwh'},{'agg':'max','field':'kwh'},{'agg':'min','field':'kwh'},{'agg':'avg','field':'kwh'}],'derived':[dict(label='最小',expression='m3',unit='kWh'),dict(label='最大',expression='m2',unit='kWh'),dict(label='差额',expression='m1-m4',unit='kWh')],'display_metric':'d2','chart':'table'})
  before=copy.deepcopy(self.model.definition);s=self.summary();self.assertEqual((s['key'],s['value']),('d2',6));self.assertEqual(self.model.definition,before);self.assertEqual(s['measure']['expression'],'m1-m4')
 def test_derived_currency_conversion_is_preserved(self):
  self.record('costs',dict(id='C1',work_order_id='W1',amount_cents=1500,category='材料',occurred='2026-09-25'))
  self.record('costs',dict(id='C2',work_order_id='W2',amount_cents=500,category='材料',occurred='2026-09-25'))
  self.define({'dimension':'work_order_id','metrics':[{'agg':'sum','field':'amount_cents'},{'agg':'count'}],'derived':[dict(label='每行金额',expression='m0/m1',unit='元/条')],'display_metric':'d0','chart':'table'},'costs')
  s=self.summary();self.assertEqual((s['value'],s['unit']),(10,'元/条'))
 def inventory(self,units):
  self.define({'dimension':'unit','metrics':[{'agg':'sum','field':'balance_qty'},{'agg':'count'}],'chart':'table'},'bi_inventory')
  return [dict(id=f'I{i}',unit=u,balance_qty=10) for i,u in enumerate(units)]
 def test_mixed_units_pause_only_summary_and_keep_group_values(self):
  with patch('app.analysis_engine.semantic.rows',return_value=self.inventory(['件','kg'])):r=self.run_topic()
  self.assertEqual(len(r['cards'][0]['primary']['rows']),2);s=r['cards'][0]['scope_summary']['primary'];self.assertEqual(s['state'],'blocked');self.assertIsNone(s['value'])
 def test_missing_dynamic_unit_pauses_summary(self):
  with patch('app.analysis_engine.semantic.rows',return_value=self.inventory([None])):s=self.summary()
  self.assertEqual(s['state'],'blocked');self.assertIn('单位',s['reason'])
 def test_unused_mixed_unit_measure_does_not_block_selected_count(self):
  rows=self.inventory(['件','kg']);self.model.definition['display_metric']='m1';self.model.save()
  with patch('app.analysis_engine.semantic.rows',return_value=rows):s=self.summary()
  self.assertEqual((s['value'],s['state'],s['unit']),(2,'ready','条'))
 def test_unknown_unit_does_not_invent_scalar(self):
  self.record('customers',dict(id='C1',region='模拟区域',payment_days=2))
  self.define({'dimension':'region','metrics':[{'agg':'sum','field':'payment_days'}],'chart':'table'},'customers')
  r=self.run_topic();self.assertEqual(r['cards'][0]['primary']['rows'][0]['m0'],2);self.assertEqual(r['cards'][0]['scope_summary']['primary']['state'],'blocked')
 def test_no_source_is_distinct_from_known_empty_count(self):
  self.define({'dimension':'workshop','metrics':[{'agg':'count'}],'chart':'table'});s=self.summary();self.assertEqual((s['state'],s['value']),('no_source',None))
  self.energy('1',8);s=self.summary(conf={**CONF,'scope':{'from':'2030-01-01'}});self.assertEqual((s['state'],s['value']),('empty',0))
 def test_empty_mean_is_not_zero(self):
  self.energy('1',8);self.define({'metrics':[{'agg':'avg','field':'kwh'}],'chart':'table'});s=self.summary(conf={**CONF,'scope':{'from':'2030-01-01'}});self.assertEqual((s['state'],s['value']),('no_sample',None))
 def test_partial_missing_samples_keep_valid_count_and_block_delta(self):
  self.energy('1',8);self.energy('2',None);s=self.summary();self.assertEqual((s['state'],s['value'],s['valid_rows'],s['missing_rows']),('partial',8,1,1));self.assertTrue(bc.compare(s,s)['blocked'])
 def test_all_null_is_not_zero(self):
  self.energy('1',None);s=self.summary();self.assertEqual((s['state'],s['value'],s['valid_rows']),('partial',None,0))
 def test_zero_denominator_is_explicit(self):
  self.define({'metrics':[{'agg':'ratio','field':'on_time_plan_count','denominator':'due_plan_count'}],'chart':'table'},'bi_order_lines')
  with patch('app.analysis_engine.semantic.rows',return_value=[dict(id='1',on_time_plan_count=0,due_plan_count=0)]):s=self.summary()
  self.assertEqual((s['state'],s['value'],s['denominator']),('undefined',None,0))
 def test_scalar_datetime_can_be_read_without_numeric_delta(self):
  self.energy('1',8);self.define({'metrics':[{'agg':'max','field':'started'}],'chart':'table'});s=self.summary();self.assertEqual(s['value'],'2026-09-25T08:00:00');self.assertTrue(bc.compare(s,s)['blocked'])
 def test_full_population_survives_chart_group_cap(self):
  self.define({'dimension':'family','metrics':[{'agg':'count'}],'chart':'table'},'bi_order_lines')
  rows=[dict(id=str(i),family=f'F{i}') for i in range(1001)]
  with patch('app.analysis_engine.semantic.rows',return_value=rows):
   r=self.run_topic();response=self.export(r)
  self.assertEqual(response.status_code,200);self.assertTrue(r['cards'][0]['primary']['truncated']);self.assertEqual(len(r['cards'][0]['primary']['rows']),1000);self.assertEqual(r['cards'][0]['scope_summary']['primary']['value'],1001);self.assertIn(',1001,订单行,',response.content.decode('utf-8-sig'))
 def test_fixed_and_date_filters_apply_to_summary(self):
  self.energy('1',8,'A','25');self.energy('2',3,'B','25');self.energy('3',9,'A','24')
  self.define({'dimension':'workshop','metrics':[{'agg':'sum','field':'kwh'}],'filters':[{'field':'workshop','op':'eq','value':'A'}],'chart':'table'})
  s=self.summary(conf={**CONF,'scope':{'from':'2026-09-25','to':'2026-09-25'}});self.assertEqual((s['value'],s['source_rows']),(8,1));self.assertEqual(s['scope']['date_label'],'读数开始日')
 def test_source_count_drift_between_chart_and_summary_is_rejected(self):
  self.energy('1',8)
  original=bc.engine.selected_rows
  with patch('app.bi_card_summary.engine.selected_rows',side_effect=[original(self.admin,'energy',self.model.definition,{}),([],1,{})]):
   with self.assertRaises(ReviewConflict):self.run_topic()
 def test_uncertified_models_stay_analysis(self):
  self.energy('1',8);s=self.summary();self.assertEqual(s['definition_status'],'analysis');self.assertIsNone(s['metric_receipt']);self.assertIn('不判断达标',s['notice'])
 def test_run_preserves_engine_result_and_business_rows(self):
  self.energy('1',8);before=list(Record.objects.values());count=AuditEvent.objects.count();original=run_analysis(self.admin,self.model.dataset,self.model.definition,{});r=self.run_topic();self.assertEqual(r['cards'][0]['primary'],original);self.assertEqual(list(Record.objects.values()),before);self.assertEqual(AuditEvent.objects.count(),count)
 def test_export_exact_scope_and_csv_formula_protection(self):
  self.energy('1',8);r=self.run_topic(conf={**CONF,'primary_label':'  =1+1'});response=self.export(r);self.assertEqual(response.status_code,200);self.assertEqual(response['Cache-Control'],'no-store');self.assertIn("'=1+1",response.content.decode('utf-8-sig'));self.assertEqual(AuditEvent.objects.filter(action='topic_scope_summary.export').count(),1)
 def test_export_rejects_changed_summary_algorithm(self):
  self.energy('1',8);r=self.run_topic()
  with patch('app.bi_card_summary.algorithm',return_value='different'):response=self.export(r)
  self.assertEqual(response.status_code,409);self.assertFalse(AuditEvent.objects.exists())
 def test_export_rejects_source_edit_without_revision_or_timestamp(self):
  record=self.energy('1',8);r=self.run_topic();Record.objects.filter(pk=record.pk).update(values={**record.values,'kwh':20});self.assertEqual(self.export(r).status_code,409);self.assertFalse(AuditEvent.objects.exists())
 def test_export_rejects_stale_token_extra_and_duplicate_parameters(self):
  self.energy('1',8);r=self.run_topic();url=f'/api/topics/{self.topic.pk}/summary/export';q=self.query(r)
  self.assertEqual(self.client.get(url,{**q,'summary_token':'bad'}).status_code,409)
  self.assertEqual(self.client.get(url,{**q,'page':'2'}).status_code,400)
  self.assertEqual(self.client.get(url,{**q,'summary_token':[q['summary_token'],q['summary_token']]}).status_code,400);self.assertFalse(AuditEvent.objects.exists())
 def test_hidden_model_does_not_leak_summary_or_export_name(self):
  self.define({'metrics':[{'agg':'sum','field':'amount_cents'}],'chart':'table'},'costs');self.model.name='秘密成本';self.model.save();self.client.force_login(self.quality)
  r=self.run_topic(user=self.quality);self.assertNotIn('scope_summary',r['cards'][0]);response=self.export(r);self.assertEqual(response.status_code,200);self.assertNotIn('秘密成本',response.content.decode('utf-8-sig'))
 def test_frozen_summary_is_immutable_after_current_changes(self):
  record=self.energy('1',8);r=self.run_topic();s=ss.create(self.admin,self.topic.pk,self.body(r));old=copy.deepcopy(s.payload);record.values['kwh']=20;record.save();d=ss.compare_current(self.admin,self.topic.pk,s.pk);c=d['cards'][0]['scope_summary_comparison'];self.assertEqual(c['delta'],12);s.refresh_from_db();self.assertEqual(s.payload,old)
  response=self.client.get(f'/api/topics/{self.topic.pk}/snapshots/{s.pk}/summary/export');self.assertEqual(response.status_code,200);self.assertIn(',8,kWh,ready,',response.content.decode('utf-8-sig'))
 def test_snapshot_rejects_changed_summary_before_saving(self):
  record=self.energy('1',8);body=self.body(self.run_topic());Record.objects.filter(pk=record.pk).update(values={**record.values,'kwh':20})
  with self.assertRaises(ReviewConflict):ss.create(self.admin,self.topic.pk,body)
  self.assertFalse(TopicSnapshot.objects.exists())
 def test_snapshot_capture_checks_same_population_even_without_revision(self):
  record=self.energy('1',8);r=self.run_topic();original=ss.capture
  def changed(*args):
   Record.objects.filter(pk=record.pk).update(values={**record.values,'kwh':20});return original(*args)
  with patch('app.topic_snapshots.capture',side_effect=changed):
   with self.assertRaises(ReviewConflict):ss.create(self.admin,self.topic.pk,self.body(r))
  self.assertFalse(TopicSnapshot.objects.exists());self.assertEqual(Record.objects.get(pk=record.pk).values['kwh'],8)
 def test_legacy_snapshot_missing_summary_is_not_reconstructed(self):
  self.energy('1',8);r=self.run_topic();original=ss.capture
  def legacy(*args):
   p=original(*args);p['result'].pop('summary_token');p['result']['cards'][0].pop('scope_summary');return p
  with patch('app.topic_snapshots.capture',side_effect=legacy):s=ss.create(self.admin,self.topic.pk,self.body(r))
  d=ss.compare_current(self.admin,self.topic.pk,s.pk);self.assertTrue(d['cards'][0]['scope_summary_comparison']['blocked']);self.assertIn('未保存',d['cards'][0]['scope_summary_comparison']['reason'])
  response=self.client.get(f'/api/topics/{self.topic.pk}/snapshots/{s.pk}/summary/export');self.assertIn('旧快照未保存',response.content.decode('utf-8-sig'))
 def test_frozen_export_enforces_owner_current_role_and_no_filters(self):
  self.energy('1',8);s=ss.create(self.admin,self.topic.pk,self.body(self.run_topic()));url=f'/api/topics/{self.topic.pk}/snapshots/{s.pk}/summary/export'
  self.assertEqual(self.client.get(url,{'from':'2026-09-25'}).status_code,400);self.client.force_login(self.quality);self.assertEqual(self.client.get(url).status_code,404)
  self.client.force_login(self.admin);self.admin.groups.clear();self.admin.groups.add(Group.objects.get(name='quality'));self.assertEqual(self.client.get(url).status_code,403)
 def test_authentication_required_for_both_summary_exports(self):
  self.client.logout();self.assertEqual(self.client.get(f'/api/topics/{self.topic.pk}/summary/export').status_code,401);self.assertEqual(self.client.get(f'/api/topics/{self.topic.pk}/snapshots/{uuid.uuid4()}/summary/export').status_code,401)
 def test_published_datetime_receipt_serializes_and_freezes(self):
  from tests.test_metric_registry import payload
  self.energy('1',8);v=self.post('/api/metrics',dict(key='SUMMARY_ENERGY',dataset='energy',payload=payload())).json();v=self.post('/api/metrics/'+str(v['id']),dict(action='submit',revision=v['revision'])).json();self.client.force_login(self.quality);v=self.post('/api/metrics/'+str(v['id']),dict(action='publish',revision=v['revision'],reason='合成来源与指标定义已经核对')).json();self.assertEqual(v['status'],'published');self.client.force_login(self.admin)
  self.define({'metric_ref':dict(key=v['key'],version=v['version']),'chart':'table'});r=self.run_topic();s=ss.create(self.admin,self.topic.pk,self.body(r));f=s.payload['result']['cards'][0]['scope_summary']['primary'];self.assertEqual(f['definition_status'],'published');self.assertIsInstance(f['metric_receipt']['published_at'],str);self.assertEqual(f['value'],8);self.assertEqual(ss.get(self.admin,self.topic.pk,s.pk).payload_hash,ws.digest(s.payload))

class SummaryComparisonTests(SimpleTestCase):
 def scalar(self,value,unit='kWh',**kw):return dict(format_revision='v',algorithm='a',key='m0',measure={'agg':'sum'},unit=unit,grain='row',definition_hash='d',model_id=1,model_version=1,metric_receipt=None,state='ready',value=value,**kw)
 def test_percentages_use_points_and_negative_baselines_do_not_make_percent(self):
  c=bc.compare(self.scalar(80,'%'),self.scalar(75,'%'));self.assertEqual((c['delta'],c['delta_unit'],c['relative_pct']),(5,'百分点',None))
  for base in [0,-5]:self.assertIsNone(bc.compare(self.scalar(10),self.scalar(base))['relative_pct'])
 def test_definition_and_algorithm_drift_pause_comparison(self):
  for k,v in [('algorithm','b'),('unit','分钟'),('model_version',2),('key','m1')]:
   with self.subTest(k=k):self.assertTrue(bc.compare(self.scalar(1),{**self.scalar(1),k:v})['blocked'])
 def test_partial_nonfinite_text_and_missing_do_not_become_zero(self):
  for reference in [None,self.scalar(None),self.scalar(float('inf')),self.scalar('2026-09-25'),{**self.scalar(1),'state':'partial'}]:self.assertTrue(bc.compare(self.scalar(2),reference)['blocked'])
