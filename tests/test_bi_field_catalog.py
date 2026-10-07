"""Field documentation must stay complete, permission-scoped and non-mutating."""
import copy,csv,io,json,uuid
from unittest.mock import patch
from django.contrib.auth.models import User,Group
from django.core.exceptions import ValidationError,PermissionDenied
from django.test import Client
from app import bi_field_catalog as fc,bi_card_summary as bc,topic_workspace as ws,topic_snapshots as ss
from app.semantic_schema import schemas
from app import access,derived_metrics as dm
from app.models import Record,AnalysisModel,Topic,AuditEvent
from tests.test_platform import PlatformCase

class BIFieldCatalogTests(PlatformCase):
 def setUp(self):
  super().setUp();self.client.force_login(self.admin)
 def board(self,user=None,filters=None,page=1):return fc.board(user or self.admin,filters or {},page)
 def field(self,dataset,field,user=None):return next(f for f in fc.dataset_contract(user or self.admin,dataset)['fields'] if f['name']==field)
 def export(self,d,**kw):return self.client.get('/api/bi-field-catalog/export',{**d['filters'],'receipt':d['receipt'],**kw})
 def summary(self,dataset,field,values,agg='sum',**extra):
  for v in values:self.record(dataset,v)
  m=AnalysisModel.objects.create(name='字段单位演练',dataset=dataset,definition={'metrics':[dict(agg=agg,field=field,**extra)],'chart':'table'},owner='admin',is_public=True)
  t=Topic.objects.create(name='单位专题',layout=[dict(model_id=m.pk)],owner='admin',is_public=True)
  r=ws.run(self.admin,t.pk,dict(context_token=ws.context(self.admin,t.pk)['context_token'],config=dict(scope={},reference_scope=None,primary_label='全部',reference_label='参照')))
  return r['cards'][0]['scope_summary']['primary']
 def test_every_authorized_schema_field_is_documented_once(self):
  d=fc.build(self.admin,{});expected={(key,f['name']) for key in schemas() if access.allowed(self.admin,key) for f in access.permitted_fields(self.admin,key)}
  actual=[(f['dataset'],f['name']) for f in d['rows']];self.assertEqual(set(actual),expected);self.assertEqual(len(actual),len(expected));self.assertEqual(d['authorized_fields'],len(expected));self.assertEqual(len(d['datasets']),len(schemas()));self.assertFalse(d['contains_business_values'])
 def test_all_pages_equal_export_population(self):
  d=self.board();identities=[]
  for page in range(1,(d['total']+24)//25+1):
   b=self.board(page=page);self.assertEqual(b['receipt'],d['receipt']);identities.extend((f['dataset'],f['name']) for f in b['rows'])
  self.assertEqual(len(identities),d['total']);self.assertEqual(len(identities),len(set(identities)));response=self.export(d,format='csv');self.assertEqual(response.status_code,200);rows=list(csv.reader(io.StringIO(response.content.decode('utf-8-sig'))));self.assertEqual(len(rows)-4,d['total']);self.assertEqual(set((r[1],r[5]) for r in rows[4:]),set(identities))
 def test_quality_sees_no_sensitive_money_or_personnel_fields(self):
  d=fc.build(self.quality,{});keys={s['key'] for s in d['datasets']};self.assertNotIn('costs',keys);self.assertNotIn('attendance',keys);self.assertTrue(all('cents' not in f['name'] for f in d['rows']));self.assertNotIn('tariff_cents',json.dumps(d));self.assertNotIn('amount_cents',json.dumps(d))
 def test_operations_has_personnel_but_no_money(self):
  user=User.objects.create_user('ops');user.groups.add(Group.objects.create(name='operations'));d=fc.build(user,{});self.assertIn('attendance',[s['key'] for s in d['datasets']]);self.assertNotIn('hourly_cents',json.dumps(d))
 def test_finance_has_money_but_no_personnel(self):
  user=User.objects.create_user('fin');user.groups.add(Group.objects.create(name='finance'));d=fc.build(user,{});self.assertIn('costs',[s['key'] for s in d['datasets']]);self.assertNotIn('attendance',[s['key'] for s in d['datasets']])
 def test_disabled_or_conflicting_account_cannot_use_cached_user(self):
  d=self.board();User.objects.filter(pk=self.admin.pk).update(is_active=False)
  with self.assertRaises(PermissionDenied):fc.export_data(self.admin,{},d['receipt'])
  User.objects.filter(pk=self.admin.pk).update(is_active=True);self.admin.groups.add(Group.objects.get(name='quality'))
  with self.assertRaises(PermissionDenied):self.board()
 def test_inaccessible_and_unknown_dataset_return_same_denial(self):
  for key in ['costs','not-a-dataset']:
   with self.subTest(key=key),self.assertRaises(PermissionDenied):fc.board(self.quality,{'dataset':key})
 def test_unknown_and_dynamic_and_fixed_units_are_explicit(self):
  self.assertEqual(self.field('customers','payment_days')['unit_info']['kind'],'unknown')
  self.assertEqual(self.field('bi_inventory','balance_qty')['unit_info']['unit_field'],'unit')
  self.assertEqual(self.field('shipments','qty')['unit_info']['unit'],'台')
  self.assertEqual(self.field('attendance','productive_hours')['unit_info']['unit'],'小时')
 def test_named_field_hints_do_not_enable_new_formulas(self):
  for dataset,name in fc.STATIC:
   f=self.field(dataset,name);self.assertFalse(f['unit_info']['formula_supported']);fields={f['name']:f for f in access.permitted_fields(self.admin,dataset)}
   with self.assertRaises(ValidationError):dm.field_unit(dataset,name,fields)
 def test_existing_derived_units_and_compound_units_are_preserved(self):
  self.assertEqual(self.field('bi_work_orders','unit_cost_cents')['unit_info']['unit'],'分/台');self.assertTrue(self.field('energy','kwh')['unit_info']['formula_supported']);self.assertEqual(self.field('energy','tariff_cents')['unit_info']['kind'],'unknown')
 def test_static_scatter_parameter_unit_is_explained_without_additivity(self):
  f=self.field('products','power_kw');self.assertEqual(f['unit_info']['unit'],'kW');self.assertFalse(f['unit_info']['formula_supported']);self.assertIn('参数',f['aggregation_note']);self.assertEqual(self.field('products','price_cents')['unit_info']['unit'],'分/台')
 def test_raw_measurement_units_require_per_row_evidence(self):
  for dataset,field,unit in [('measurements','value','unit'),('measurements','raw_value','raw_unit'),('process_specs','lsl','unit'),('service_conditions','value','unit')]:
   with self.subTest(dataset=dataset,field=field):self.assertEqual(self.field(dataset,field)['unit_info']['unit_field'],unit)
 def test_ids_are_text_and_boolean_has_no_min_or_max(self):
  self.assertTrue(self.field('units','id')['primary_key']);self.assertIn('前导零',self.field('units','id')['identity_rule']);self.assertNotIn('min',self.field('employees','active')['aggregations']);self.assertNotIn('sum',self.field('units','id')['aggregations'])
 def test_dates_and_scope_capabilities_match_existing_contracts(self):
  d=fc.dataset_contract(self.admin,'shipments');self.assertEqual(d['date_contract']['date_label'],'发货日');self.assertTrue(d['date_contract']['family']);self.assertTrue(d['date_contract']['customer_id']);self.assertFalse(fc.dataset_contract(self.admin,'materials')['date_contract']['date'])
 def test_sources_and_reference_targets_do_not_widen_access(self):
  d=fc.dataset_contract(self.quality,'bi_work_orders');self.assertNotIn('costs',[s['key'] for s in d['sources']]);self.assertEqual(self.field('units','work_order_id')['reference'],'work_orders');self.assertEqual(d['source_scope'],'只列当前账号可访问的来源表')
 def test_nullable_is_a_contract_and_does_not_claim_data_quality(self):
  self.assertFalse(self.field('bi_work_orders','unit_cost_cents')['required']);self.assertIn('空缺',self.field('bi_work_orders','unit_cost_cents')['missing_rule']);self.assertIn('不等于',self.field('units','id')['missing_rule'])
 def test_balance_time_and_money_have_distinct_aggregation_notes(self):
  self.assertIn('时点',self.field('bi_receivables','balance_cents')['aggregation_note']);self.assertIn('价税',self.field('costs','amount_cents')['aggregation_note']);self.assertIn('自然历时',self.field('attendance','productive_hours')['aggregation_note'])
 def test_filters_intersect_without_fabricating_business_values(self):
  d=fc.build(self.admin,dict(dataset='shipments',q='数量',kind='numeric',unit_state='fixed'));self.assertEqual([(f['name'],f['unit_info']['unit']) for f in d['rows']],[('qty','台')]);self.record('shipments',dict(id='SECRET_RECORD',qty=987654321));self.assertNotIn('SECRET_RECORD',json.dumps(d));self.assertNotIn('987654321',json.dumps(d))
 def test_no_match_and_out_of_range_page_are_empty(self):
  self.assertEqual(self.board(filters={'q':'无此字段不存在'})['total'],0);self.assertEqual(self.board(page=100000)['rows'],[])
 def test_invalid_filters_duplicate_params_and_page_rejected(self):
  for qs in [{'q':['a','b']},{'page':'0'},{'page':'1.1'},{'page':'True'},{'kind':'sql'},{'unit_state':'arbitrary'},{'q':'x'*101},{'source':'units'}]:
   with self.subTest(qs=qs):self.assertEqual(self.client.get('/api/bi-field-catalog',qs).status_code,400)
 def test_json_export_contains_all_contracts_in_same_range(self):
  d=self.board(filters={'dataset':'shipments'});r=self.export(d,format='json');self.assertEqual(r.status_code,200);j=json.loads(r.content);self.assertEqual(j['total'],d['total']);self.assertEqual(len(j['rows']),d['total']);self.assertEqual(j['receipt'],d['receipt']);self.assertEqual([s['key'] for s in j['datasets']],['shipments']);self.assertEqual(r['Cache-Control'],'no-store')
 def test_export_after_role_change_refuses_old_receipt(self):
  d=self.board();self.admin.groups.clear();self.admin.groups.add(Group.objects.get(name='quality'))
  with self.assertRaises(ReviewConflict):fc.export_data(self.admin,{},d['receipt'])
 def test_export_after_documentation_or_schema_change_refuses_old_receipt(self):
  d=self.board()
  with patch('app.bi_field_catalog.revision',return_value='changed'):
   with self.assertRaises(ReviewConflict):fc.export_data(self.admin,{},d['receipt'])
  original=schemas();changed=copy.deepcopy(original);changed['units']['fields'][0]['label']='修改标签'
  with patch('app.bi_field_catalog.schemas',return_value=changed),patch('app.access.schemas',return_value=changed):
   with self.assertRaises(ReviewConflict):fc.export_data(self.admin,{},d['receipt'])
 def test_export_parameter_errors_do_not_write_audit(self):
  d=self.board()
  for change in [{'receipt':'old'},{'format':'xlsx'},{'format':['csv','csv']},{'page':2}]:
   with self.subTest(change=change):self.assertIn(self.export(d,**change).status_code,(400,409))
  self.assertFalse(AuditEvent.objects.exists())
 def test_csv_text_formula_is_escaped(self):
  d=self.board(filters={'dataset':'shipments'});original=fc.export_data
  def changed(*a):
   r=original(*a);r['rows'][0]['label']='  =1+1';return r
  with patch('app.bi_field_catalog.export_data',side_effect=changed):r=self.export(d)
  self.assertIn("'  =1+1",r.content.decode('utf-8-sig'))
 def test_reading_does_not_change_records_schema_or_audit(self):
  original=copy.deepcopy(schemas());self.record('units',dict(id='SN01',status='模拟'));before=list(Record.objects.values());self.board();self.field('shipments','qty');self.assertEqual(schemas(),original);self.assertEqual(list(Record.objects.values()),before);self.assertFalse(AuditEvent.objects.exists())
 def test_export_audit_failure_rolls_back(self):
  d=self.board()
  with patch('app.bi_field_catalog_views.AuditEvent.objects.create',side_effect=RuntimeError('failed')):
   with self.assertRaises(RuntimeError):self.export(d)
  self.assertFalse(AuditEvent.objects.exists())
 def test_auth_and_no_write_endpoint(self):
  self.assertEqual(self.post('/api/bi-field-catalog',{}).status_code,405);self.client.logout();self.assertEqual(self.client.get('/api/bi-field-catalog').status_code,401);self.assertEqual(self.client.get('/api/bi-field-catalog/export').status_code,401)
 def test_delivery_quantity_summary_uses_declared_motor_units(self):
  s=self.summary('delivery_plans','qty',[dict(id='D1',qty=9),dict(id='D2',qty=12)]);self.assertEqual((s['state'],s['value'],s['unit']),('ready',21,'台'))
 def test_shipment_summary_keeps_record_count_distinct_from_motor_count(self):
  s=self.summary('shipments','qty',[dict(id='S1',qty=9),dict(id='S2',qty=12)]);self.assertEqual((s['source_rows'],s['value'],s['unit']),(2,21,'台'))
 def test_attendance_summary_is_hours_without_conversion(self):
  s=self.summary('attendance','productive_hours',[dict(id='A1',productive_hours=3.5),dict(id='A2',productive_hours=2)]);self.assertEqual((s['value'],s['unit']),(5.5,'小时'))
 def test_measurement_mixed_units_are_not_silently_summed(self):
  s=self.summary('measurements','value',[dict(id='M1',value=2,unit='V'),dict(id='M2',value=3,unit='A')]);self.assertEqual(s['state'],'blocked');self.assertIsNone(s['value'])
 def test_measurement_one_unit_can_be_summarized_but_is_not_conformance(self):
  s=self.summary('measurements','value',[dict(id='M1',value=2,unit='V'),dict(id='M2',value=4,unit='V')],agg='avg');self.assertEqual((s['state'],s['value'],s['unit']),('ready',3,'V'));self.assertIsNone(s['metric_receipt'])
 def test_unknown_field_unit_remains_blocked(self):
  s=self.summary('customers','payment_days',[dict(id='C1',payment_days=30)]);self.assertEqual(s['state'],'blocked')

from app.import_review import ReviewConflict
