import uuid
from unittest.mock import patch
from urllib.parse import urlencode
from django.contrib.auth.models import User,Group
from app.models import AnalysisModel,AnalysisModelCardVersion,Record,AuditEvent
from tests.test_platform import PlatformCase
from tests import test_model_cards as card_fixtures
class ModelResultTests(PlatformCase):
 preview=card_fixtures.ModelCardTests.preview;data=card_fixtures.ModelCardTests.data;create=card_fixtures.ModelCardTests.create;card=card_fixtures.ModelCardTests.card
 def setUp(self):
  super().setUp();self.client.force_login(self.quality)
  for i,(workshop,kwh) in enumerate([('A',10),('A',20),('B',30),('B',40)]):self.record('energy',dict(id='E'+str(i),workshop=workshop,kwh=kwh))
  self.m=AnalysisModel.objects.create(name='分车间电量',dataset='energy',definition=dict(dimension='workshop',metrics=[dict(agg='sum',field='kwh')],chart='bar'),owner='system',is_public=True)
 def evaluate(self):
  self.c=self.card();r=self.client.get('/api/model-cards/'+self.c['id']+'/run');self.assertEqual(r.status_code,200,r.content);return r.json()
 def evidence(self,v,**query):return self.client.get('/api/model-cards/'+self.c['id']+'/evidence?'+urlencode(dict(receipt=v['reading']['receipt'],**query)))
 def define(self,**changes):self.m.definition.update(changes);self.m.save()
 def test_complete_population_summary_no_business_or_definition_writes(self):
  self.c=self.card();before=(Record.objects.count(),AuditEvent.objects.count(),AnalysisModelCardVersion.objects.count());v=self.client.get('/api/model-cards/'+self.c['id']+'/run').json();self.assertEqual(v['reading']['summary']['value'],100);self.assertEqual(v['reading']['summary']['unit'],'kWh');self.assertEqual(v['reading']['summary']['state'],'ready');self.assertEqual(before,(Record.objects.count(),AuditEvent.objects.count(),AnalysisModelCardVersion.objects.count()))
 def test_average_not_average_of_group_means(self):
  self.record('energy',dict(id='E4',workshop='B',kwh=100));self.define(metrics=[dict(agg='avg',field='kwh')]);v=self.evaluate();self.assertEqual(v['reading']['summary']['value'],40);self.assertNotEqual(v['reading']['summary']['value'],sum(r['m0'] for r in v['result']['rows'])/2)
 def test_fixed_filter_is_explained_and_sources_match(self):
  self.define(filters=[dict(field='kwh',op='gte',value='30')]);v=self.evaluate();self.assertEqual(v['reading']['summary']['value'],70);self.assertEqual(v['reading']['conditions'][0]['field'],'kwh');d=self.evidence(v).json();self.assertEqual(d['total'],2);self.assertEqual({r['values']['id'] for r in d['rows']},{'E2','E3'})
 def test_source_group_exact_and_unknown_not_all(self):
  v=self.evaluate();d=self.evidence(v,group='A').json();self.assertEqual(d['total'],2);self.assertEqual(sum(r['values']['kwh'] for r in d['rows']),30);self.assertEqual(d['rows'][0]['source']['file'],'unit-test.xlsx');self.assertEqual(self.evidence(v,group='unknown').status_code,400)
 def test_invalid_missing_or_duplicate_query_rejected(self):
  v=self.evaluate();base='/api/model-cards/'+self.c['id']+'/evidence';self.assertEqual(self.client.get(base).status_code,400)
  for q in [dict(page='0'),dict(page='-1'),dict(page='1.5'),dict(unknown='1'),dict(group='A',point='bad')]:self.assertEqual(self.evidence(v,**q).status_code,400)
  q=urlencode(dict(receipt=v['reading']['receipt']));self.assertEqual(self.client.get(base+'?'+q+'&page=1&page=2').status_code,400)
 def test_data_change_rejects_old_result_receipt(self):
  v=self.evaluate();self.record('energy',dict(id='new',workshop='A',kwh=1));self.assertEqual(self.evidence(v).status_code,409)
 def test_definition_change_or_archive_blocks_source(self):
  v=self.evaluate();self.m.version+=1;self.m.save();self.assertEqual(self.evidence(v).status_code,409)
 def test_card_metadata_revision_invalidates_result_receipt(self):
  v=self.evaluate();body=self.data();body.update(revision=1,question='更正用途说明');self.post('/api/model-cards/'+self.c['id'],body);self.assertEqual(self.evidence(v).status_code,409)
 def test_owner_source_visibility_checked_even_admin(self):
  v=self.evaluate();self.client.force_login(self.admin);self.assertEqual(self.evidence(v).status_code,404)
 def test_private_source_loss_blocks_old_receipt(self):
  v=self.evaluate();self.m.is_public=False;self.m.owner='other';self.m.save();self.assertEqual(self.evidence(v).status_code,404)
 def test_expiry_and_result_rule_change(self):
  with patch('django.core.signing.time.time',return_value=0):v=self.evaluate()
  self.assertEqual(self.evidence(v).status_code,409)
  v=self.client.get('/api/model-cards/'+self.c['id']+'/run').json()
  with patch('app.bi_card_summary.algorithm',return_value='changed-summary-algorithm'):self.assertEqual(self.evidence(v).status_code,409)
 def test_pagination_covers_complete_selected_population(self):
  for i in range(63):self.record('energy',dict(id='MORE'+str(i),workshop='A',kwh=1))
  v=self.evaluate();rows=[]
  for p in [1,2,3]:rows.extend(self.evidence(v,page=p).json()['rows'])
  self.assertEqual(len(rows),67);self.assertEqual(len({r['values']['id'] for r in rows}),67);self.assertEqual(v['reading']['summary']['value'],sum(r['values']['kwh'] for r in rows))
 def test_missing_inputs_remain_partial_and_known_empty_scope_distinct(self):
  self.record('energy',dict(id='missing',workshop='A',kwh=None));v=self.evaluate();self.assertEqual(v['reading']['summary']['state'],'partial');self.assertEqual(v['reading']['summary']['missing_rows'],1)
 def test_no_sample_not_filled_with_zero(self):
  self.define(filters=[dict(field='workshop',op='eq',value='unknown')]);v=self.evaluate();self.assertEqual(v['reading']['summary']['state'],'no_sample');self.assertIsNone(v['reading']['summary']['value']);self.assertEqual(self.evidence(v).json()['total'],0)
 def test_ratio_recomputed_from_population_not_sum_of_group_percentages(self):
  self.define(metrics=[dict(agg='ratio',field='kwh',denominator='kwh')],chart='bar');v=self.evaluate();self.assertEqual(v['reading']['summary']['value'],100);self.assertEqual(sum(r['m0'] for r in v['result']['rows']),200);self.assertEqual((v['reading']['summary']['numerator'],v['reading']['summary']['denominator']),(100,100))
 def test_quantile_is_from_all_sources_and_retains_sample_detail(self):
  self.define(metrics=[dict(agg='median',field='kwh')],chart='table');v=self.evaluate();self.assertEqual(v['reading']['summary']['value'],25);self.assertEqual(v['reading']['summary']['quantile']['valid_rows'],4)
 def test_pivot_cell_and_grand_total_sources(self):
  self.define(chart='pivot',pivot=dict(dimension='id',grain='value'));v=self.evaluate();p=v['result']['pivot'];d=self.evidence(v,row=p['rows'][0]['key'],column=p['columns'][0]['key']);self.assertEqual(d.status_code,200,d.content);self.assertEqual(d.json()['total'],1);self.assertEqual(self.evidence(v,row='',column='').json()['total'],4);self.assertEqual(self.evidence(v,row='wrong',column='').status_code,400)
 def test_scatter_point_sources_and_invalid_point(self):
  self.define(chart='scatter',metrics=[dict(agg='sum',field='kwh'),dict(agg='avg',field='kwh')],scatter=dict(x='m0',y='m1'));v=self.evaluate();point=v['result']['scatter']['points'][0];d=self.evidence(v,point=point['key']);self.assertEqual(d.status_code,200,d.content);self.assertEqual(d.json()['total'],point['row_count']);self.assertEqual(self.evidence(v,point='unknown').status_code,400)
 def test_read_all_six_roles_and_sensitive_fields_are_sanitized(self):
  self.m.dataset='products';self.m.definition=dict(dimension='family',metrics=[dict(agg='count')],chart='table');self.m.save();self.record('products',dict(id='P1',family='YE3',price_cents=12300,power_kw=1.5))
  for role in ['admin','analyst','quality','operations','finance','viewer']:
   user=User.objects.filter(username=role).first() or User.objects.create_user(role);g,_=Group.objects.get_or_create(name=role);user.groups.add(g);self.client.force_login(user);v=self.evaluate();d=self.evidence(v).json();self.assertEqual('price_cents' in d['rows'][0]['values'],role in {'admin','analyst','finance'})
