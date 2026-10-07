import copy
import json
from pathlib import Path
from unittest.mock import patch
from django.contrib.auth.models import User,Group
from django.test import SimpleTestCase,TestCase,Client,RequestFactory
from app import curing,curing_views
from app.models import Record,ImportBatch,ImportRow,AuditEvent,AccountAccessState
from app.ingestion import fingerprint

def fixture():return json.loads((Path(__file__).parent/'fixtures/curing_scenario.json').read_text())
def calc(f):return curing.analyze(f['tables'],f['refs'],f['as_of'])
def case(f,name):return next(r for r in calc(f)['rows'] if r['run']['id']==f['cases'][name])
def points(f,name,channel='T01'):return [s for s in f['tables']['cure_samples'] if s['run_id']==f['cases'][name] and s['channel_code']==channel]

class CuringMathTests(SimpleTestCase):
    def test_independent_34_cases(self):
        f=fixture();self.assertEqual({r['run']['id']:r['state'] for r in calc(f)['rows']},f['expected'])
        self.assertEqual(curing.scoped(calc(f),curing.filters({}))['summary']['states'],dict(ready=5,out=3,missing=6,attention=16,open=2,future=1,voided=1))
    def test_continuous_interval_duration_and_inclusive_boundaries(self):
        f=fixture()
        for name,minutes in [('normal',60),('inclusive',60),('exact45',45),('split_hold',25),('short',20)]:
            self.assertEqual([c['longest_hold_minutes'] for c in case(f,name)['channels']],[minutes,minutes])
        self.assertEqual(case(f,'split_hold')['state'],'out')
    def test_no_interpolation_missing_or_long_gap(self):
        f=fixture();r=case(f,'gap');self.assertEqual(r['state'],'missing');self.assertEqual(r['channels'][0]['gaps'][0]['minutes'],15)
        r=case(f,'missing_point');self.assertIsNone(r['channels'][0]['points'][9]['value_c']);self.assertEqual(r['channels'][0]['longest_hold_minutes'],25)
    def test_wrong_unit_never_plotted_as_celsius(self):
        f=fixture();r=case(f,'wrong_unit');p=r['channels'][0]['points'][9];self.assertEqual(p['unit'],'K');self.assertIsNone(p['value_c']);self.assertFalse(p['valid'])
    def test_no_extrapolation_and_ramp_not_false_underlimit(self):
        f=fixture();self.assertEqual(case(f,'normal')['state'],'ready');self.assertEqual(case(f,'missing_start')['state'],'missing');self.assertEqual(case(f,'missing_end')['state'],'missing')
    def test_overtemperature_exact_point_and_absolute_limit_inclusive(self):
        f=fixture();self.assertEqual(case(f,'overtemp')['channels'][0]['max_observed_c'],190)
        p=points(f,'normal')[0];p['value']=170;self.assertEqual(case(f,'normal')['state'],'ready');p['value']=170.001;self.assertEqual(case(f,'normal')['state'],'out')
    def test_nan_infinite_bool_and_missing_value_do_not_become_zero(self):
        for v in (None,True,float('nan'),float('inf')):
            f=fixture();points(f,'normal')[9]['value']=v;r=case(f,'normal');self.assertEqual(r['state'],'missing');self.assertIsNone(r['channels'][0]['points'][9]['value_c'])
    def test_timestamp_sequence_anomalies_fail_closed(self):
        for name in ('duplicate_time','duplicate_sequence','sequence_gap','future_point'):
            f=fixture();self.assertEqual(case(f,name)['state'],'attention')
        f=fixture();points(f,'normal')[9]['measured']='wrong';self.assertEqual(case(f,'normal')['state'],'attention')
        f=fixture();points(f,'normal')[0]['sequence']=True;self.assertEqual(case(f,'normal')['state'],'attention')
        f=fixture();self.assertEqual(case(f,'sequence_gap')['channels'][0]['longest_hold_minutes'],30)
    def test_profile_version_never_falls_back_and_expiry_end_exclusive(self):
        f=fixture();self.assertEqual(case(f,'unknown_version')['channels'],[]);self.assertEqual(case(f,'expired')['state'],'attention')
        p=f['tables']['cure_profiles'][0];p['expires']=case(f,'normal')['run']['finished'];self.assertEqual(case(f,'normal')['state'],'attention')
    def test_required_channel_missing_and_undeclared_channel(self):
        f=fixture();self.assertEqual(case(f,'missing_channel')['channels'][1]['points'],[]);self.assertEqual(case(f,'extra_channel')['state'],'attention')
    def test_mapping_wrong_does_not_return_false_order_relationship(self):
        f=fixture();l=case(f,'batch_mismatch')['loads'][0];self.assertFalse(l['linked']);self.assertIsNone(l['work_order_id']);self.assertEqual(l['orders'],[])
    def test_old_completed_operation_unclosed_does_not_say_in_production(self):
        f=fixture();r=case(f,'unclosed');self.assertEqual(r['state'],'open');self.assertEqual(r['label'],'采集未闭合');self.assertTrue(f['refs']['operations'][r['loads'][0]['operation_id']]['finished'])
    def test_global_overlap_survives_filters_and_touching_not_overlap(self):
        f=fixture();r=case(f,'overlap_a');scope=curing.filters({'q':r['run']['id']});s=curing.scoped(calc(f),scope);self.assertEqual(len(s['rows']),1);self.assertTrue(s['rows'][0]['conflict_ids'])
        other=next(v for v in f['tables']['cure_runs'] if v['id']==f['cases']['overlap_b']);other['started']=r['run']['finished'];self.assertEqual(case(f,'overlap_a')['conflict_ids'],[])
    def test_voided_and_future_never_count_as_ready(self):
        f=fixture();self.assertEqual(case(f,'voided')['state'],'voided');self.assertEqual(case(f,'future')['state'],'future');self.assertEqual(case(f,'future')['loads'],[])
    def test_date_scope_is_run_start_not_registration_and_empty_means_zero(self):
        f=fixture();result=calc(f);s=curing.scoped(result,curing.filters({'from':'2026-09-16','to':'2026-09-16'}));self.assertTrue(s['rows']);self.assertTrue(all(r['run']['started'].startswith('2026-09-16') for r in s['rows']))
        self.assertEqual(curing.scoped(calc(f),curing.filters({'q':'does-not-exist'}))['summary']['runs'],0)
    def test_invalid_scopes(self):
        for s in ({'unknown':1},{'q':True},{'from':'2026-02-30'},{'state':'pass'},{'from':'2026-10-01','to':'2026-09-01'}):
            with self.assertRaises(ValueError):curing.filters(s)
    def test_input_immutable_and_permutation_stable(self):
        f=fixture();old=copy.deepcopy(f);r=calc(f);self.assertEqual(f,old)
        for rows in f['tables'].values():rows.reverse()
        other=calc(f);self.assertEqual({v['run']['id']:v['state'] for v in r['rows']},{v['run']['id']:v['state'] for v in other['rows']})
    def test_counts_duplicate_mapping_capacity_and_unsupported_sensor(self):
        f=fixture();run=next(r for r in f['tables']['cure_runs'] if r['id']==f['cases']['normal']);run['sample_count']+=1;self.assertEqual(case(f,'normal')['state'],'missing')
        f=fixture();self.assertEqual(case(f,'part_sensor')['state'],'attention');self.assertEqual(case(f,'invalid_limits')['state'],'attention')

class CuringApiTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.users={};cls.f=fixture()
        for role in ('admin','analyst','quality','operations','finance','viewer'):
            u=User.objects.create_user(username='curing_'+role);u.groups.add(Group.objects.get_or_create(name=role)[0]);cls.users[role]=u
        cls.batch=ImportBatch.objects.create(filename='43_固化温度曲线_模拟.xlsx',file_hash='a'*64,file_path='data/imports/fixture.xlsx',status='committed')
        i=0
        for ds,values in {**cls.f['tables'],**{k:list(v.values()) for k,v in cls.f['refs'].items()}}.items():
            for v in values:
                i+=1;hash=fingerprint(v);r=ImportRow.objects.create(batch=cls.batch,sheet=ds,row_number=i+1,dataset=ds,business_key=v['id'],normalized=v,record_hash=hash,status='valid')
                Record.objects.create(dataset=ds,business_key=v['id'],values=v,record_hash=hash,source_row=r)
    def post(self,suffix='',data=None,status=200):
        r=self.client.post('/api/curing'+suffix,json.dumps(data or {}),content_type='application/json');self.assertEqual(r.status_code,status,r.content[:200]);return r
    def login(self,role='viewer'):self.client.force_login(self.users[role])
    def read(self,scope=None):return self.post(data={'scope':scope or {}}).json()
    def test_all_six_roles_exact_scope_export_and_source_paging(self):
        for role in self.users:
            self.login(role);d=self.read({'state':'ready'});self.assertEqual(d['total'],5);q=dict(scope=d['scope'],receipt=d['receipt']);key=d['rows'][0]['run']['id']
            detail=self.post('/runs/'+key,q).json();self.assertEqual(detail['total'],38);self.assertTrue(detail['row']['loads'][0]['orders'])
            sources=self.post('/sources',q).json();self.assertEqual(len(sources['rows']),40);self.assertEqual(sources['can_download_original'],role=='admin')
            for fmt in ('json','csv'):
                e=self.post('/export',{**q,'format':fmt});self.assertEqual(e['Cache-Control'],'no-store');self.assertNotIn('price_cents',e.json()['text']);self.assertNotIn('hourly_cents',e.json()['text'])
                if fmt=='json':
                    doc=json.loads(e.json()['text']);self.assertEqual(doc['result']['summary'],d['summary']);self.assertEqual(len(doc['inputs']['cure_samples']),190);self.assertNotIn('receipt',doc)
    def test_no_identity_query_and_strict_body_page_and_method(self):
        self.login();self.assertEqual(self.client.get('/api/curing').status_code,405)
        for v in ('1',0,True,-1,10001):self.post(data={'page':v},status=400)
        self.post(data={'unknown':1},status=400);self.assertEqual(self.client.post('/api/curing?q=X','{}',content_type='application/json').status_code,400)
        self.assertEqual(self.client.post('/api/curing','{"scope":{"q":"A","q":"B"}}',content_type='application/json').status_code,400)
        self.post('/export',status=400);self.post('/sources',status=400)
    def test_empty_scope_exports_no_old_result_or_missing_raw_points(self):
        self.login();d=self.read({'q':'not-found'});q=dict(scope=d['scope'],receipt=d['receipt']);doc=json.loads(self.post('/export',q).json()['text']);self.assertEqual(doc['inputs']['cure_samples'],[])
        d=self.read({'q':self.f['cases']['extra_channel']});doc=json.loads(self.post('/export',dict(scope=d['scope'],receipt=d['receipt'])).json()['text']);self.assertTrue(any(s['channel_code']=='T99' for s in doc['inputs']['cure_samples']))
    def test_receipt_scope_account_rule_expiry_and_tamper(self):
        self.login();d=self.read();q=dict(scope=d['scope'],receipt=d['receipt']);self.post('/export',{**q,'scope':{'state':'ready'}},409);self.post('/export',{**q,'receipt':'invalid'},409)
        with patch('django.core.signing.time.time',return_value=10**12):self.post('/sources',q,409)
        with patch('app.curing.rule_hash',return_value='changed'):self.post('/sources',q,409)
        self.login('admin');self.post('/sources',q,409)
    def test_fact_source_revision_change_and_foreign_detail(self):
        self.login();d=self.read({'state':'ready'});q=dict(scope=d['scope'],receipt=d['receipt']);self.post('/runs/'+self.f['cases']['short'],q,404)
        r=Record.objects.get(dataset='cure_runs',business_key=self.f['cases']['normal']);r.values['note']='更正';r.record_hash=fingerprint(r.values);r.revision+=1;r.save();row=r.source_row;row.normalized=r.values;row.record_hash=r.record_hash;row.save();self.post('/sources',q,409)
    def test_account_epoch_and_fresh_inactive_account(self):
        self.login();d=self.read();state,_=AccountAccessState.objects.get_or_create(user=self.users['viewer']);state.revision+=1;state.save();self.post('/export',dict(scope=d['scope'],receipt=d['receipt']),409)
        u=self.users['viewer'];req=RequestFactory().post('/api/curing','{}',content_type='application/json');req.user=u;User.objects.filter(pk=u.pk).update(is_active=False);self.assertEqual(curing_views.board(req).status_code,403)
    def test_read_only_and_export_audit_atomicity(self):
        self.login();before=list(Record.objects.values_list('id','record_hash','revision'));n=AuditEvent.objects.count();d=self.read();q=dict(scope=d['scope'],receipt=d['receipt']);self.post('/sources',q);self.assertEqual(AuditEvent.objects.count(),n)
        with patch('app.curing_views.AuditEvent.objects.create',side_effect=ValueError('audit failure')):self.post('/export',q,400)
        self.assertEqual(AuditEvent.objects.count(),n);self.assertEqual(list(Record.objects.values_list('id','record_hash','revision')),before)
    def test_anonymous_csrf_invalid_format_and_conflicting_roles(self):
        self.post(status=401);self.login();d=self.read();q=dict(scope=d['scope'],receipt=d['receipt']);self.post('/export',{**q,'format':'html'},400)
        secure=Client(enforce_csrf_checks=True);secure.force_login(self.users['viewer']);self.assertEqual(secure.post('/api/curing','{}',content_type='application/json').status_code,403)
        self.users['viewer'].groups.add(Group.objects.get(name='finance'));self.post(status=401)
    def test_source_identity_mismatch_rejected(self):
        self.login();r=Record.objects.get(dataset='cure_samples',business_key=self.f['tables']['cure_samples'][0]['id']);r.values['id']='different';r.save();self.post(status=400)
    def test_csv_formula_guard_and_original_values(self):
        self.login();r=Record.objects.get(dataset='cure_runs',business_key=self.f['cases']['wrong_unit']);r.values['note']='=SUM(1,2)';r.record_hash=fingerprint(r.values);r.save();row=r.source_row;row.normalized=r.values;row.record_hash=r.record_hash;row.save()
        d=self.read({'q':r.business_key});text=self.post('/export',dict(scope=d['scope'],receipt=d['receipt'],format='csv')).json()['text'];self.assertIn("'=SUM(1,2)",text);self.assertIn(',K,',text)
    def test_no_silent_truncation(self):
        self.login()
        with patch.dict('app.curing_data.LIMITS',cure_runs=1):self.post(status=400)
