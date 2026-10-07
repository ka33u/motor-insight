import copy,json
from pathlib import Path
from unittest.mock import patch
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import SimpleTestCase,TestCase
from app import oee,oee_contract,oee_views
from app.ingestion import fingerprint
from app.models import ImportBatch,ImportRow,Record,AuditEvent

RESOURCE=dict(id='SB-08-01-W01',capacity=1,effective='2026-09-01',equipment_id='SB-08-01',process='终检',station='独立工位1',employee_id='E00009')
PRODUCTS={k:dict(id=k,model=k,family='YE3',price_cents=50000) for k in ('CP.00001.A','CP.00002.A')}
def fixture(number=1):
 data=json.loads((Path(__file__).parent/'fixtures/oee_scenario.json').read_text());study=copy.deepcopy(data['tables']['oee_studies'][number-1]);tables={ds:[copy.deepcopy(r) for r in data['tables'][ds] if r['study_id']==study['id']] for ds in ('oee_windows','oee_events','oee_cycles','oee_outputs')};return study,tables
def calculate(s,t,resource=None,products=None):return oee.analyze(s,t,RESOURCE if resource is None else resource,PRODUCTS if products is None else products,'2026-10-01T18:00:00')

class OeeMathTests(SimpleTestCase):
 def test_single_config_loss_conservation_and_factors(self):
  s,t=fixture();r=calculate(s,t);m=r['summary'];self.assertEqual(r['state'],'ready');self.assertEqual((m['planned_seconds'],m['stop_seconds'],m['run_seconds']),(25200,3600,21600));self.assertEqual(m['counts'],dict(total_qty=160,good_first_qty=150,rework_qty=6,scrap_qty=4,unknown_qty=0));self.assertAlmostEqual(m['oee'],150*90/25200);self.assertAlmostEqual(m['availability']*m['performance']*m['quality'],m['oee']);self.assertEqual(m['loss_conservation_seconds'],0);self.assertEqual(m['speed_loss_seconds']+m['quality_loss_seconds']+m['good_ideal_seconds']+m['stop_seconds'],m['planned_seconds'])
 def test_overlap_union_clip_and_nonadditive_causes(self):
  s,t=fixture(2);r=calculate(s,t);self.assertEqual(r['summary']['stop_seconds'],5100);self.assertEqual(r['events'][-1]['outside_seconds'],600);w=r['windows'][0];self.assertGreater(sum(w['cause_seconds'].values()),w['stop_seconds']);self.assertEqual(len(w['stop_segments']),3)
 def test_mixed_configs_never_average_oee_or_multiply_counts_quality(self):
  s,t=fixture(3);r=calculate(s,t);m=r['summary'];self.assertTrue(m['mixed_configuration']);self.assertIsNone(m['oee']);self.assertIsNone(m['performance']);self.assertIsNone(m['quality']);self.assertAlmostEqual(m['good_ideal_time_share'],15150/25200);self.assertNotAlmostEqual(m['good_ideal_time_share'],sum(w['oee'] for w in r['windows'])/2)
 def test_mixed_units_do_not_add_physical_counts(self):
  s,t=fixture(3);t['oee_windows'][1]['unit']='件';t['oee_cycles'][1]['unit']='件'
  for o in t['oee_outputs']:
   if o['window_id']==t['oee_windows'][1]['id']:o['unit']='件'
  r=calculate(s,t);self.assertEqual(r['state'],'ready');self.assertIsNone(r['summary']['counts']['total_qty']);self.assertIsNone(r['summary']['unit'])
 def test_complete_zero_output_is_real_zero_not_quality_100(self):
  s,t=fixture(4);r=calculate(s,t);self.assertEqual(r['state'],'ready');self.assertEqual(r['summary']['oee'],0);self.assertEqual(r['summary']['performance'],0);self.assertIsNone(r['summary']['quality'])
 def test_zero_run_and_known_zero_output(self):
  s,t=fixture(4);t['oee_events']=[dict(id=w['id']+'-STOP',study_id=s['id'],started=w['started'],finished=w['finished'],kind='故障',reference='SIM',basis='合成全窗口停机') for w in t['oee_windows']];s['event_count']=2;r=calculate(s,t);self.assertEqual(r['state'],'ready');self.assertEqual(r['summary']['oee'],0);self.assertIsNone(r['summary']['performance']);self.assertEqual(r['summary']['availability'],0)
 def test_six_incomplete_cases_pause_without_false_values(self):
  for number in range(5,11):
   with self.subTest(number=number):
    s,t=fixture(number);r=calculate(s,t);self.assertEqual(r['state'],'paused');self.assertTrue(r['issues']);self.assertIsNone(r['summary']);self.assertTrue(all(w['oee'] is None for w in r['windows']))
 def test_expected_count_mismatch_pauses(self):
  s,t=fixture();s['output_count']+=1;self.assertEqual(calculate(s,t)['state'],'paused')
 def test_performance_above_one_pauses_no_clamping(self):
  s,t=fixture();t['oee_cycles'][0]['seconds_per_unit']=900;r=calculate(s,t);self.assertEqual(r['state'],'paused');self.assertTrue(any('超过' in i for i in r['issues']))
 def test_duplicate_cycle_pauses(self):
  s,t=fixture();t['oee_cycles'].append({**t['oee_cycles'][0],'id':'SIM-C02'});s['cycle_count']=2;self.assertEqual(calculate(s,t)['state'],'paused')
 def test_duplicate_id_pauses(self):
  s,t=fixture();t['oee_outputs'].append(copy.deepcopy(t['oee_outputs'][0]));s['output_count']+=1;self.assertEqual(calculate(s,t)['state'],'paused')
 def test_foreign_window_and_study_pause(self):
  s,t=fixture();t['oee_outputs'][0]['window_id']='OTHER';self.assertEqual(calculate(s,t)['state'],'paused');s,t=fixture();t['oee_outputs'][0]['study_id']='OTHER';self.assertEqual(calculate(s,t)['state'],'paused')
 def test_output_unit_and_registration_time_pause(self):
  for field,value in [('unit','kg'),('reported','2026-09-25T12:30:00')]:
   s,t=fixture();t['oee_outputs'][0][field]=value;self.assertEqual(calculate(s,t)['state'],'paused')
 def test_independent_capacity_and_effective_date(self):
  s,t=fixture()
  for value in ({},dict(RESOURCE,capacity=2),dict(RESOURCE,effective='2026-09-26')):self.assertEqual(calculate(s,t,resource=value)['state'],'paused')
 def test_product_reference_missing(self):
  s,t=fixture();self.assertEqual(calculate(s,t,products={})['state'],'paused')
 def test_bad_intrinsic_values_and_required_fields(self):
  for field,value in [('total_qty',True),('good_first_qty',-1),('total_qty',99),('reported','2026-09-25T08:59:00Z')]:
   s,t=fixture();t['oee_outputs'][0][field]=value;self.assertEqual(calculate(s,t)['state'],'paused')
  s,t=fixture();del t['oee_outputs'][0]['basis'];self.assertEqual(calculate(s,t)['state'],'paused')
 def test_negative_nonfinite_ideal_cycles(self):
  for value in (0,-1,float('nan'),float('inf'),True):
   s,t=fixture();t['oee_cycles'][0]['seconds_per_unit']=value;self.assertEqual(calculate(s,t)['state'],'paused')
 def test_input_permutation_and_read_only(self):
  s,t=fixture();original=copy.deepcopy((s,t));first=calculate(s,t);self.assertEqual((s,t),original);reversed_tables={k:list(reversed(v)) for k,v in t.items()};other=calculate(s,reversed_tables);self.assertEqual(first['summary'],other['summary'])
 def test_stop_outside_plan_and_boundary_touching(self):
  s,t=fixture();t['oee_events'].append(dict(id='SIM-X',study_id=s['id'],started='2026-09-25T12:00:00',finished='2026-09-25T13:00:00',kind='故障',reference='SIM',basis='合成休息期间'));s['event_count']+=1;r=calculate(s,t);self.assertEqual(r['summary']['stop_seconds'],3600);self.assertEqual(r['events'][-1]['inside_seconds'],0)

class OeeApiTests(TestCase):
 @classmethod
 def setUpTestData(cls):
  cls.users={}
  for role in ('admin','analyst','quality','operations','finance','viewer'):
   user=get_user_model().objects.create_user(username='oee_'+role,password='fixture-only');user.groups.add(Group.objects.get_or_create(name=role)[0]);cls.users[role]=user
  cls.batch=ImportBatch.objects.create(filename='38_班次设备效率_模拟.xlsx',file_hash='a'*64,file_path='data/imports/fixture.xlsx',status='committed')
  i=0
  def add(ds,value):
   nonlocal i;i+=1;h=fingerprint(value);row=ImportRow.objects.create(batch=cls.batch,sheet=ds,row_number=i+1,dataset=ds,business_key=value['id'],normalized=value,record_hash=h,status='valid');return Record.objects.create(dataset=ds,business_key=value['id'],values=value,record_hash=h,source_row=row)
  add('production_resources',RESOURCE)
  for p in PRODUCTS.values():add('products',p)
  data=json.loads((Path(__file__).parent/'fixtures/oee_scenario.json').read_text())
  for ds,rows in data['tables'].items():
   for row in rows:add(ds,row)
 def login(self,role='viewer'):self.client.force_login(self.users[role])
 def read(self,key='OE-260925-001'):
  r=self.client.get('/api/oee/'+key);self.assertEqual(r.status_code,200);return r.json()
 def test_all_six_roles_read_drill_sources_and_export_same_scope(self):
  for role in self.users:
   with self.subTest(role=role):
    self.login(role);d=self.read();self.assertEqual(d['summary']['counts']['good_first_qty'],150);self.assertNotIn('employee_id',d['resource']);self.assertTrue(all('price_cents' not in p for p in d['products'].values()));q={'receipt':d['receipt']};self.assertEqual(self.client.get('/api/oee/OE-260925-001/sources',q).status_code,200);self.assertEqual(self.client.get('/api/oee/OE-260925-001/windows/OE-260925-001-W01',q).status_code,200);e=self.client.get('/api/oee/OE-260925-001/export',{**q,'format':'json'});self.assertEqual(e.status_code,200);self.assertEqual(e.json()['result']['summary'],d['summary']);self.assertNotIn('receipt',e.json());self.assertEqual(len(e.json()['inputs']['oee_outputs']),7)
 def test_paused_json_and_csv_keep_complete_inputs(self):
  self.login();d=self.read('OE-260925-006');self.assertEqual(d['state'],'paused')
  for fmt in ('csv','json'):
   r=self.client.get('/api/oee/OE-260925-006/export',dict(receipt=d['receipt'],format=fmt));self.assertEqual(r.status_code,200);self.assertIn('OE-260925-006-P101',r.content.decode());self.assertIn('unknown_qty',r.content.decode())
 def test_anonymous_inactive_and_conflicting_roles(self):
  self.assertEqual(self.client.get('/api/oee').status_code,401);self.login();u=self.users['viewer'];u.groups.add(Group.objects.get(name='finance'));self.assertIn(self.client.get('/api/oee').status_code,(401,403));u.groups.clear();u.is_active=False;u.save();self.assertIn(self.client.get('/api/oee').status_code,(401,403))
 def test_foreign_account_or_study_receipt_rejected(self):
  self.login('admin');d=self.read();self.login('viewer');self.assertEqual(self.client.get('/api/oee/OE-260925-001/export',dict(receipt=d['receipt'])).status_code,409);d=self.read();self.assertEqual(self.client.get('/api/oee/OE-260925-002',dict(receipt=d['receipt'])).status_code,409)
 def test_unknown_duplicate_filter_and_missing_receipt_rejected(self):
  self.login();self.assertEqual(self.client.get('/api/oee/OE-260925-001?family=X').status_code,400);self.assertEqual(self.client.get('/api/oee/OE-260925-001?receipt=x&receipt=y').status_code,400);self.assertEqual(self.client.get('/api/oee/OE-260925-001/export').status_code,400);self.assertEqual(self.client.get('/api/oee/UNKNOWN').status_code,404)
 def test_invalid_expired_and_rule_changed_receipts(self):
  self.login();d=self.read();self.assertEqual(self.client.get('/api/oee/OE-260925-001',dict(receipt='invalid')).status_code,409)
  with patch('django.core.signing.time.time',return_value=10**12):self.assertEqual(self.client.get('/api/oee/OE-260925-001',dict(receipt=d['receipt'])).status_code,409)
  with patch('app.oee.rule_hash',return_value='changed'):self.assertEqual(self.client.get('/api/oee/OE-260925-001',dict(receipt=d['receipt'])).status_code,409)
 def test_changed_normalized_source_invalidates_receipt(self):
  self.login();d=self.read();r=Record.objects.get(dataset='oee_outputs',business_key='OE-260925-001-P101');r.values['basis']='更正后的合成依据';r.record_hash=fingerprint(r.values);r.revision+=1;r.save();row=r.source_row;row.normalized=r.values;row.record_hash=r.record_hash;row.save();self.assertEqual(self.client.get('/api/oee/OE-260925-001',dict(receipt=d['receipt'])).status_code,409)
 def test_changed_account_epoch_invalidates_receipt(self):
  from app.models import AccountAccessState
  self.login();d=self.read();u=self.users['viewer'];state,_=AccountAccessState.objects.get_or_create(user=u);state.revision+=1;state.save();self.assertEqual(self.client.get('/api/oee/OE-260925-001',dict(receipt=d['receipt'])).status_code,409)
 def test_unknown_drill_and_invalid_export_rejected_without_audit(self):
  self.login();d=self.read();before=AuditEvent.objects.count();q=dict(receipt=d['receipt']);self.assertEqual(self.client.get('/api/oee/OE-260925-001/windows/UNKNOWN',q).status_code,404);self.assertEqual(self.client.get('/api/oee/OE-260925-001/export',{**q,'format':'html'}).status_code,400);self.assertEqual(AuditEvent.objects.count(),before)
 def test_export_atomic_audit_failure_no_successful_file(self):
  self.login();d=self.read();before=AuditEvent.objects.count()
  with patch('app.oee_views.AuditEvent.objects.create',side_effect=ValueError('audit failed')):self.assertEqual(self.client.get('/api/oee/OE-260925-001/export',dict(receipt=d['receipt'])).status_code,400)
  self.assertEqual(AuditEvent.objects.count(),before)
 def test_csv_formula_injection_and_zero_preserved(self):
  self.login();s=Record.objects.get(dataset='oee_studies',business_key='OE-260925-004');s.values['name']='=SUM(1,2)';s.record_hash=fingerprint(s.values);s.save();row=s.source_row;row.normalized=s.values;row.record_hash=s.record_hash;row.save();d=self.read('OE-260925-004');r=self.client.get('/api/oee/OE-260925-004/export',dict(receipt=d['receipt']));self.assertEqual(r.status_code,200);self.assertIn("'=SUM(1,2)",r.content.decode());self.assertEqual(d['summary']['oee'],0)
 def test_sources_page_and_cache_contract(self):
  self.login();d=self.read();q=dict(receipt=d['receipt']);self.assertEqual(self.client.get('/api/oee/OE-260925-001/sources',{**q,'page':'0'}).status_code,400);self.assertEqual(self.client.get('/api/oee/OE-260925-001/sources',{**q,'page':'１'}).status_code,400);r=self.client.get('/api/oee/OE-260925-001/sources',q);self.assertEqual(r['Cache-Control'],'no-store');self.assertFalse(r.json()['can_download_original']);self.assertEqual(r.json()['total'],16)
