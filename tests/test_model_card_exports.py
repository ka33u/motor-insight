import csv,io,json,hashlib
from urllib.parse import urlencode
from unittest.mock import patch
from django.contrib.auth.models import User,Group
from app.models import AnalysisModel,AnalysisModelCardVersion,Record,AuditEvent
from tests.test_platform import PlatformCase
from tests import test_model_cards as fixtures

class ModelExportTests(PlatformCase):
 preview=fixtures.ModelCardTests.preview;data=fixtures.ModelCardTests.data;create=fixtures.ModelCardTests.create;card=fixtures.ModelCardTests.card
 def setUp(self):
  super().setUp();self.client.force_login(self.quality)
  for i,(group,value) in enumerate([('A',10),('A',20),('B',30),('B',40)]):self.record('energy',dict(id='E'+str(i),workshop=group,kwh=value))
  self.m=AnalysisModel.objects.create(name='分车间电量',dataset='energy',definition=dict(dimension='workshop',metrics=[dict(agg='sum',field='kwh')],chart='bar'),owner='system',is_public=True)
 def define(self,**changes):self.m.definition.update(changes);self.m.save()
 def evaluate(self):
  self.c=self.card();r=self.client.get('/api/model-cards/'+self.c['id']+'/run');self.assertEqual(r.status_code,200,r.content);return r.json()
 def export_result(self,value,kind='json',**extra):return self.client.get('/api/model-cards/'+self.c['id']+'/result-export?'+urlencode(dict(receipt=value['reading']['receipt'],format=kind,**extra)))
 def test_json_preserves_context_definition_and_whole_population_mean(self):
  self.record('energy',dict(id='E4',workshop='B',kwh=100));self.define(metrics=[dict(agg='avg',field='kwh')]);v=self.evaluate();r=self.export_result(v);self.assertEqual(r.status_code,200,r.content);d=r.json()
  self.assertEqual(d['reading']['summary'],v['reading']['summary']);self.assertEqual(d['reading']['summary']['value'],40);self.assertEqual(d['result'],v['result']);self.assertNotIn('receipt',d['reading']);self.assertEqual(d['card'],v['card']);self.assertEqual(d['reading']['exported_groups'],2)
 def test_csv_fixed_range_bom_and_audit_without_fact_or_version_writes(self):
  self.define(filters=[dict(field='kwh',op='gte',value='30')]);v=self.evaluate();before=(Record.objects.count(),AnalysisModelCardVersion.objects.count(),AuditEvent.objects.count());r=self.export_result(v,'csv');self.assertEqual(r.status_code,200,r.content)
  self.assertTrue(r.content.startswith(b'\xef\xbb\xbf'));rows=list(csv.reader(io.StringIO(r.content.decode('utf-8-sig'))));main=next(x for x in rows if x and x[0]=='主结果');self.assertEqual(main[3],'70');self.assertIn('kWh',main);self.assertEqual(next(x for x in rows if x and x[0]=='来源')[1],'2')
  event=AuditEvent.objects.latest('id');self.assertEqual(event.action,'model_card.result_export');self.assertEqual(event.detail['file_sha256'],hashlib.sha256(r.content).hexdigest());self.assertNotIn('receipt',event.detail);self.assertEqual(before[:2],(Record.objects.count(),AnalysisModelCardVersion.objects.count()));self.assertEqual(AuditEvent.objects.count(),before[2]+1);self.assertEqual(r['Cache-Control'],'no-store');self.assertEqual(r['X-Content-Type-Options'],'nosniff')
 def test_complete_more_than_1000_groups_same_prefix_all_arithmetic_and_csv(self):
  for i in range(1003):self.record('energy',dict(id='MORE'+str(i),workshop='G'+str(i).zfill(4),kwh=i))
  self.define(chart='table',sort='desc',metrics=[dict(agg='sum',field='kwh'),dict(agg='avg',field='kwh'),dict(agg='ratio',field='kwh',denominator='kwh'),dict(agg='median',field='kwh')]);v=self.evaluate();self.assertTrue(v['result']['truncated']);d=self.export_result(v).json()
  self.assertEqual(len(d['result']['rows']),1005);self.assertFalse(d['result']['truncated']);self.assertEqual(d['result']['rows'][:1000],v['result']['rows']);self.assertEqual(d['reading']['returned_groups'],1000);self.assertEqual(d['reading']['exported_groups'],1005);self.assertEqual(sum(x['row_count'] for x in d['result']['rows']),1007);self.assertEqual(sum(x['m0'] for x in d['result']['rows']),100+sum(range(1003)))
  self.assertEqual(next(x for x in d['result']['rows'] if x['dimension']=='A')['m3'],15);self.assertIsNone(next(x for x in d['result']['rows'] if x['dimension']=='G0000')['m2']);self.assertEqual(len(d['result']['components']),1005)
  rows=list(csv.reader(io.StringIO(self.export_result(v,'csv').content.decode('utf-8-sig'))));expected={x['dimension'] for x in d['result']['rows']};self.assertEqual({x[0] for x in rows if x and x[0] in expected},expected)
 def test_ratio_numerator_denominator_and_quantile_sample_preserved(self):
  self.define(metrics=[dict(agg='ratio',field='kwh',denominator='kwh'),dict(agg='median',field='kwh')],chart='table');v=self.evaluate();d=self.export_result(v).json();s=d['reading']['summary'];self.assertEqual((s['value'],s['numerator'],s['denominator']),(100,100,100));self.assertEqual(d['result']['rows'][0]['quantiles']['m1']['valid_rows'],2);self.assertEqual(d['group_units']['A']['m1']['unit'],'kWh')
 def test_missing_values_preserve_partial_and_null_not_zero(self):
  self.record('energy',dict(id='MISS',workshop='C',kwh=None));v=self.evaluate();d=self.export_result(v).json();self.assertEqual(d['reading']['summary']['state'],'partial');self.assertEqual(d['reading']['summary']['missing_rows'],1);self.assertIsNone(next(x for x in d['result']['rows'] if x['dimension']=='C')['m0']);self.assertEqual(self.export_result(v,'csv').status_code,200)
 def test_known_empty_scope_no_sample_and_no_source_distinct(self):
  self.define(filters=[dict(field='workshop',op='eq',value='unknown')]);v=self.evaluate();d=self.export_result(v).json();self.assertEqual(d['reading']['summary']['state'],'no_sample');self.assertIsNone(d['reading']['summary']['value']);self.assertEqual(d['result']['rows'],[])
  Record.objects.all().delete();new=self.client.get('/api/model-cards/'+self.c['id']+'/run').json();self.assertEqual(self.export_result(new).json()['reading']['summary']['state'],'no_source')
 def test_pivot_exports_all_cells_margins_grand_recomputed(self):
  self.define(chart='pivot',pivot=dict(dimension='id',grain='value'),metrics=[dict(agg='avg',field='kwh')]);v=self.evaluate();d=self.export_result(v).json();self.assertEqual(d['result']['pivot'],v['result']['pivot']);self.assertEqual(d['result']['pivot']['grand_total']['m0'],25);rows=list(csv.reader(io.StringIO(self.export_result(v,'csv').content.decode('utf-8-sig'))));self.assertEqual(len([x for x in rows if x and x[0]=='交叉单元格']),8);self.assertEqual(next(x for x in rows if x and x[0]=='总计')[3],'25')
 def test_scatter_preserves_unplotted_points_and_axes(self):
  self.record('energy',dict(id='MISS',workshop='C',kwh=None));self.define(chart='scatter',metrics=[dict(agg='sum',field='kwh'),dict(agg='avg',field='kwh')],scatter=dict(x='m0',y='m1'));v=self.evaluate();d=self.export_result(v).json();self.assertEqual(d['result']['scatter'],v['result']['scatter']);self.assertEqual(len(d['result']['scatter']['points']),3);self.assertFalse(next(x for x in d['result']['scatter']['points'] if x['dimension']=='C')['plotted']);self.assertEqual(self.export_result(v,'csv').status_code,200)
 def test_csv_formula_strings_including_leading_whitespace_are_neutralized(self):
  self.record('energy',dict(id='BAD',workshop=' \t=HYPERLINK("bad")',kwh=-12));body=self.data();body['question']='  =CMD';self.c=self.create(body).json()['card'];v=self.client.get('/api/model-cards/'+self.c['id']+'/run').json();r=self.export_result(v,'csv');rows=list(csv.reader(io.StringIO(r.content.decode('utf-8-sig'))));self.assertEqual(next(x for x in rows if x and x[0]=='业务问题')[1],"'"+v['card']['metadata']['question']);item=next(x for x in rows if x and 'HYPERLINK' in x[0]);self.assertTrue(item[0].startswith("'"));self.assertEqual(item[1],'-12')
 def test_missing_duplicate_unknown_format_and_changed_scope_rejected(self):
  v=self.evaluate();base='/api/model-cards/'+self.c['id']+'/result-export';self.assertEqual(self.client.get(base).status_code,400)
  for q in ['format=xml','page=1','group=A','row=R','format=csv&format=json','receipt=another']:
   r=self.client.get(base+'?'+urlencode(dict(receipt=v['reading']['receipt']))+'&'+q);self.assertEqual(r.status_code,400)
 def test_tampered_expired_receipts_rejected_without_export_audit(self):
  with patch('django.core.signing.time.time',return_value=0):v=self.evaluate()
  before=AuditEvent.objects.count();self.assertEqual(self.export_result(v).status_code,409);v['reading']['receipt']='tampered';self.assertEqual(self.export_result(v).status_code,409);self.assertEqual(AuditEvent.objects.count(),before)
 def test_same_count_changed_data_invalidates_receipt(self):
  v=self.evaluate();record=Record.objects.get(business_key='E0');record.values['kwh']=11;record.save();self.assertEqual(self.export_result(v).status_code,409)
 def test_definition_or_card_revision_change_invalidates_receipt(self):
  v=self.evaluate();body=self.data();body.update(revision=1,question='更正用途');self.post('/api/model-cards/'+self.c['id'],body);self.assertEqual(self.export_result(v).status_code,409);v=self.client.get('/api/model-cards/'+self.c['id']+'/run').json();self.m.version+=1;self.m.save();self.assertEqual(self.export_result(v).status_code,409)
 def test_archive_blocks_export(self):
  import uuid
  v=self.evaluate();self.post('/api/model-cards/'+self.c['id']+'/archive',dict(revision=1,archived=True,request_id=str(uuid.uuid4())));self.assertEqual(self.export_result(v).status_code,409)
 def test_owner_bound_even_admin_and_other_card_not_interchangeable(self):
  v=self.evaluate();old=self.c;body=self.data();body['code']='MODEL.OTHER.CARD';self.c=self.create(body).json()['card'];self.assertEqual(self.export_result(v).status_code,409);self.c=old;self.client.force_login(self.admin);self.assertEqual(self.export_result(v).status_code,404)
 def test_visibility_loss_blocks_export(self):
  v=self.evaluate();self.m.is_public=False;self.m.owner='other';self.m.save();self.assertEqual(self.export_result(v).status_code,404)
 def test_all_six_roles_exports_sanitize_unused_money_fields(self):
  self.m.dataset='products';self.m.definition=dict(dimension='family',metrics=[dict(agg='count')],chart='table');self.m.save();self.record('products',dict(id='P1',family='YE3',price_cents=12300,power_kw=1.5))
  for role in ['admin','analyst','quality','operations','finance','viewer']:
   user=User.objects.filter(username=role).first() or User.objects.create_user(role);g,_=Group.objects.get_or_create(name=role);user.groups.add(g);self.client.force_login(user);v=self.evaluate();r=self.export_result(v);self.assertEqual(r.status_code,200,r.content);self.assertEqual('price_cents' in r.content.decode(),role in {'admin','analyst','finance'})
 def test_account_disabled_or_financial_permission_lost_after_run(self):
  self.client.force_login(self.admin);self.m.dataset='products';self.m.definition=dict(dimension='family',metrics=[dict(agg='sum',field='price_cents')],chart='table');self.m.save();self.record('products',dict(id='P1',family='YE3',price_cents=100));v=self.evaluate();self.admin.groups.clear();self.admin.groups.add(self.quality.groups.first());self.assertEqual(self.export_result(v).status_code,401);self.client.force_login(self.admin);self.assertEqual(self.export_result(v).status_code,400);self.admin.is_active=False;self.admin.save();self.assertEqual(self.export_result(v).status_code,401)
 def test_summary_algorithm_change_invalidates_receipt(self):
  v=self.evaluate()
  with patch('app.bi_card_summary.algorithm',return_value='changed'):self.assertEqual(self.export_result(v).status_code,409)
 def test_audit_failure_no_file_response_or_business_mutation(self):
  v=self.evaluate();before=(Record.objects.count(),AuditEvent.objects.count(),AnalysisModelCardVersion.objects.count())
  with patch('app.model_card_views.AuditEvent.objects.create',side_effect=RuntimeError('audit failed')):
   with self.assertRaises(RuntimeError):self.export_result(v)
  self.assertEqual(before,(Record.objects.count(),AuditEvent.objects.count(),AnalysisModelCardVersion.objects.count()))
