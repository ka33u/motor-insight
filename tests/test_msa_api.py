import csv,io
from unittest.mock import patch
from django.contrib.auth.models import User,Group
from app.models import Record,AuditEvent,AccountAccessState
from app.ingestion import fingerprint
from .test_platform import PlatformCase
from .test_msa import fixture

class MSAAPITests(PlatformCase):
 def setUp(self):
  super().setUp();s,m,p,spec,g,units,people,cal=fixture()
  self.record('msa_studies',s);self.record('test_specs',spec);self.record('metrology_instruments',g)
  self.record('products',dict(id='P1',family='SIM',price_cents=100))
  for ds,values in [('msa_members',m),('msa_observations',p),('units',units.values()),('employees',people.values()),('metrology_calibrations',cal)]:
   for v in values:self.record(ds,v)
  self.client.force_login(self.quality)
 def board(self,q=''):return self.client.get('/api/msa/MS1'+q)
 def d(self):return self.board().json()
 def detail(self,d=None,key='O1'):return self.client.get('/api/msa/MS1/points/'+key,{'receipt':(d or self.d())['receipt']})
 def change(self,ds,key,**fields):
  r=Record.objects.get(dataset=ds,business_key=key);r.values.update(fields);r.record_hash=fingerprint(r.values);r.revision+=1;r.save()
  row=r.source_row;row.normalized=r.values;row.record_hash=r.record_hash;row.save()
 def test_login_and_method(self):
  self.client.logout();self.assertEqual(self.board().status_code,401);self.client.force_login(self.quality);self.assertEqual(self.client.post('/api/msa/MS1').status_code,405)
 def test_directory_and_normal_result(self):
  d=self.d();self.assertEqual(d['state'],'trial');self.assertEqual(d['coverage']['registered'],8);self.assertEqual(len(self.client.get('/api/msa').json()['rows']),1);self.assertEqual(d['result']['grand_mean'],10)
 def test_six_roles_read_sanitized_product(self):
  for role in ['admin','analyst','quality','operations','finance','viewer']:
   user=User.objects.filter(username=role).first() or User.objects.create_user(role);group,_=Group.objects.get_or_create(name=role);user.groups.add(group);self.client.force_login(user)
   d=self.d();self.assertEqual(d['state'],'trial');self.assertEqual('price_cents' in d['product'],role in ['admin','analyst','finance'])
 def test_paging_never_filters_model_or_chart(self):
  self.change('msa_studies','MS1',repeat_count=10)
  originals=list(Record.objects.filter(dataset='msa_observations'))
  for r in originals:
   for k in (r.values['repeat']+2,r.values['repeat']+4,r.values['repeat']+6,r.values['repeat']+8):
    p={**r.values,'id':r.business_key+'R'+str(k),'repeat':k,'run_order':(k-1)*4+(r.values['run_order']+1)//2};self.record('msa_observations',p)
  for i,r in enumerate(Record.objects.filter(dataset='msa_observations').order_by('business_key'),1):self.change('msa_observations',r.business_key,run_order=i)
  a=self.d();b=self.board('?page=2').json();self.assertEqual(a['state'],'trial');self.assertEqual(a['result'],b['result']);self.assertEqual(a['chart_points'],b['chart_points']);self.assertEqual((len(a['rows']),len(b['rows'])),(25,15))
 def test_read_only_and_no_account_state(self):
  before=(Record.objects.count(),AuditEvent.objects.count(),AccountAccessState.objects.count());d=self.d();self.detail(d);self.client.get('/api/msa/MS1/sources',{'receipt':d['receipt']});self.assertEqual(before,(Record.objects.count(),AuditEvent.objects.count(),AccountAccessState.objects.count()))
 def test_receipt_required_bad_expired_and_other_user(self):
  self.assertEqual(self.client.get('/api/msa/MS1/points/O1').status_code,400);d=self.d();self.assertEqual(self.detail({'receipt':d['receipt']+'x'}).status_code,409)
  with patch('django.core.signing.time.time',return_value=0):expired=self.d()
  self.assertEqual(self.detail(expired).status_code,409);self.client.force_login(self.admin);self.assertEqual(self.detail(d).status_code,409)
 def test_source_or_rules_change_invalidates(self):
  d=self.d();self.change('msa_observations','O1',value=9);self.assertEqual(self.detail(d).status_code,409);d=self.d()
  with patch('app.msa.rule_hash',return_value='changed'):self.assertEqual(self.detail(d).status_code,409)
 def test_account_revision_invalidates(self):
  d=self.d();AccountAccessState.objects.create(user=self.quality,revision=2);self.assertEqual(self.detail(d).status_code,409)
 def test_unknown_repeated_or_invalid_query(self):
  for q in ['?dimension=operator','?page=0','?page=-1','?page=1&page=2','?page=1.5','?page=１００']:
   self.assertEqual(self.board(q).status_code,400)
 def test_cross_study_point_and_unknown_cell_404(self):
  d=self.d();self.assertEqual(self.detail(d,'FOREIGN').status_code,404);self.assertEqual(self.client.get('/api/msa/MS1/cells/P1/FOREIGN',{'receipt':d['receipt']}).status_code,404)
 def test_missing_cell_pauses_no_zero(self):
  Record.objects.get(dataset='msa_observations',business_key='O1').delete();d=self.d();self.assertEqual(d['state'],'paused');self.assertIsNone(d['result']);v=self.client.get('/api/msa/MS1/cells/P1/A1',{'receipt':d['receipt']}).json();self.assertEqual(v['cell']['missing_repeats'],[1]);self.assertEqual(len(v['rows']),1)
 def test_duplicate_round_all_rows_preserved(self):
  p=Record.objects.get(dataset='msa_observations',business_key='O1').values;self.record('msa_observations',{**p,'id':'O9','run_order':9});d=self.d();v=self.client.get('/api/msa/MS1/cells/P1/A1',{'receipt':d['receipt']}).json();self.assertEqual(d['state'],'paused');self.assertEqual(len(v['rows']),3);self.assertEqual(v['cell']['duplicate_repeats'],[1])
 def test_point_provenance_includes_plan_roster_sn_worker_calibration(self):
  d=self.detail().json();keys={(s['dataset'],s['key']) for s in d['sources']}
  for pair in [('msa_studies','MS1'),('msa_members','P1'),('msa_members','A1'),('units','U1'),('employees','E1'),('metrology_calibrations','C1'),('msa_observations','O1')]:self.assertIn(pair,keys)
  self.assertTrue(all(s['source_row_id'] for s in d['sources']));self.assertFalse(d['can_download_original'])
 def test_admin_original_available(self):
  self.client.force_login(self.admin);self.assertTrue(self.detail().json()['can_download_original'])
 def test_full_csv_formula_safe_and_audited(self):
  self.change('msa_observations','O8',reference='=SIM()');d=self.d();r=self.client.get('/api/msa/MS1/export',{'receipt':d['receipt'],'page':2});self.assertEqual(r.status_code,200);rows=list(csv.reader(io.StringIO(r.content.decode('utf-8-sig'))));self.assertEqual(len(rows)-6,8);self.assertIn("'=SIM()",rows[-1]);self.assertEqual(r['Cache-Control'],'no-store');self.assertEqual(AuditEvent.objects.get(action='msa.export').detail['rows'],8)
 def test_export_stale_does_not_audit(self):
  d=self.d();self.change('msa_observations','O8',value=12);before=AuditEvent.objects.count();self.assertEqual(self.client.get('/api/msa/MS1/export',{'receipt':d['receipt']}).status_code,409);self.assertEqual(AuditEvent.objects.count(),before)
 def test_source_fact_mismatch_rejected(self):
  r=Record.objects.get(dataset='msa_observations',business_key='O1');r.values['value']=99;r.save();self.assertEqual(self.board().status_code,400)
 def test_same_value_replacement_source_identity_invalidates(self):
  d=self.d();r=Record.objects.get(dataset='msa_observations',business_key='O1');r.source_row=self.row('msa_observations',r.values,'committed');r.save();self.assertEqual(self.detail(d).status_code,409)
 def test_changed_file_metadata_invalidates(self):
  d=self.d();self.batch.filename='changed.xlsx';self.batch.save();self.assertEqual(self.detail(d).status_code,409)
 def test_missing_product_or_plan_owner_pauses(self):
  Record.objects.get(dataset='products',business_key='P1').delete();d=self.d();self.assertEqual(d['state'],'paused');self.assertIsNone(d['result'])
 def test_expired_calibration_pauses_result_preserves_raw(self):
  self.change('metrology_calibrations','C1',valid_until='2026-09-27T00:00:00');d=self.d();self.assertEqual(d['state'],'paused');self.assertEqual(len(d['chart_points']),8);self.assertIsNone(d['result'])
 def test_all_sources_receipt_and_private_cache(self):
  d=self.d();r=self.client.get('/api/msa/MS1/sources',{'receipt':d['receipt']});self.assertEqual(r.status_code,200);self.assertEqual(len(r.json()['rows']),r.json()['total']);self.assertEqual(r['Cache-Control'],'no-store');self.assertEqual(self.board()['Cache-Control'],'no-store')
