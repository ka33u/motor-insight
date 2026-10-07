import csv,io
from copy import deepcopy
from datetime import datetime,timedelta
from unittest.mock import patch
from django.core import signing
from django.contrib.auth.models import User,Group
from django.test import SimpleTestCase
from app import spc,spc_source_contract,spc_views
from app.models import Record,AuditEvent,AccountAccessState
from app.ingestion import fingerprint
from .test_platform import PlatformCase

def fixture(n=40,end=20):
    start=datetime(2026,9,27,8)
    study=dict(id='S1',name='合成候选试验',product_id='P1',spec_id='R1',equipment_id='D1',owner_id='E1',
               method='I_MR',measurement_method='M1',unit='Ω',started=start.isoformat(),finished=(start+timedelta(hours=2)).isoformat(),
               expected_points=n,baseline_end=end,status='已结束',order_basis='设备计数（模拟）',measurement_system_ref=None)
    spec=dict(id='R1',product_id='P1',unit='Ω',lsl=0,usl=20,effective='2026-01-01')
    points=[dict(id='O'+str(i),study_id='S1',sequence=i,unit_id='U'+str(i),value=9 if i%2 else 11,unit='Ω',replicate=1,
                 method_version='M1',state='有效',measured=(start+timedelta(minutes=i)).isoformat(),
                 registered=(start+timedelta(minutes=i,seconds=20)).isoformat(),operator_id='E1',reference='SIM'+str(i),temperature_c=25)
            for i in range(1,n+1)]
    units={p['unit_id']:dict(id=p['unit_id'],product_id='P1',assembly_at='2026-09-26T08:00:00') for p in points}
    return study,points,spec,units

class SPCFormulaTests(SimpleTestCase):
    def setUp(self):self.s,self.p,self.spec,self.units=fixture()
    def result(self):return spc.analyze(self.s,self.p,self.spec,self.units)
    def test_known_i_mr_formula_and_no_formal_capability(self):
        d=self.result();l=d['limits'];self.assertEqual(d['state'],'trial');self.assertEqual(l['center'],10);self.assertEqual(l['mr_mean'],2)
        self.assertAlmostEqual(l['i_ucl'],10+6/1.128);self.assertAlmostEqual(l['mr_ucl'],6.534);self.assertEqual(l['mr_lcl'],0)
        self.assertFalse(d['formal_qualification']);self.assertIsNone(d['cpk']);self.assertFalse(d['baseline_policy']['refit_on_filter'])
    def test_monitoring_shift_never_refits_baseline(self):
        old=self.result()['limits']
        for p in self.p[20:]:p['value']+=7
        d=self.result();self.assertEqual(d['limits'],old);self.assertEqual(d['signal_counts']['monitor']['i'],20)
        self.assertEqual(d['coverage']['spec_outside'],0)
    def test_product_outside_and_control_signal_independent(self):
        self.p[-1]['value']=19;d=self.result();self.assertTrue(d['points'][-1]['i_signal']);self.assertFalse(d['points'][-1]['spec_outside'])
        self.spec['usl']=10;d=self.result();self.assertTrue(d['points'][1]['spec_outside']);self.assertFalse(d['points'][1]['i_signal'])
    def test_monitoring_missing_sequence_breaks_mr_pair(self):
        self.p=[p for p in self.p if p['sequence']!=30];d=self.result();self.assertEqual(d['state'],'trial');self.assertEqual(d['coverage']['missing_sequences'],[30])
        self.assertIsNone(next(p for p in d['points'] if p['sequence']==31)['mr'])
    def test_missing_baseline_pauses_all_limits(self):
        self.p=self.p[1:];d=self.result();self.assertEqual(d['state'],'paused');self.assertIsNone(d['limits'])
    def test_declared_missing_value_is_not_zero(self):
        self.p[29].update(state='缺测',value=None);d=self.result();self.assertEqual(d['coverage']['held'],1)
        self.assertIsNone(d['points'][29]['mr']);self.assertIsNone(d['points'][30]['mr'])
    def test_voided_and_pending_break_pairs(self):
        for state in ['作废','待核查']:
            with self.subTest(state=state):
                self.p[29]['state']=state;d=self.result();self.assertIsNone(d['points'][30]['mr'])
    def test_repeated_baseline_sn_and_replicate_are_retained_and_pause(self):
        self.p[5].update(unit_id=self.p[4]['unit_id'],replicate=2);d=self.result()
        self.assertEqual(d['coverage']['recorded'],40);self.assertEqual(d['coverage']['held'],2);self.assertIsNone(d['limits'])
    def test_duplicate_sequence_or_id_pauses_baseline(self):
        for field in ['sequence','id']:
            with self.subTest(field=field):
                p=deepcopy(self.p);p[1][field]=p[0][field];d=spc.analyze(self.s,p,self.spec,self.units);self.assertIsNone(d['limits'])
    def test_20_point_policy_is_explicit_not_stability_proof(self):
        self.s['baseline_end']=19;d=self.result();self.assertIsNone(d['limits']);self.assertTrue(d['baseline_policy']['is_project_policy'])
    def test_binary_unknown_method_or_order_pauses(self):
        for patcher in [lambda:self.spec.update(unit='bool'),lambda:self.s.update(method='待选型'),lambda:self.s.update(order_basis='未知')]:
            self.setUp();patcher();self.assertIsNone(self.result()['limits'])
    def test_zero_variation_pauses_without_discarding_points(self):
        for p in self.p:p['value']=0
        d=self.result();self.assertEqual(d['coverage']['eligible'],40);self.assertIsNone(d['limits'])
    def test_negative_controls_are_not_clipped_and_zero_value_is_valid(self):
        for p in self.p:p['value']-=10
        d=self.result();self.assertLess(d['limits']['i_lcl'],0);self.assertEqual(d['coverage']['eligible'],40)
    def test_single_sided_spec_still_compares_available_limit(self):
        self.spec['lsl']=None;self.assertIsNotNone(self.result()['limits']);self.spec['usl']=None;self.assertIsNotNone(self.result()['limits'])
    def test_no_spec_limits_never_claim_spec_pass(self):
        self.spec.update(lsl=None,usl=None);d=self.result();self.assertTrue(all(p['spec_outside'] is None for p in d['points']))
    def test_incompatible_unit_method_product_or_timing_held(self):
        mutations=[dict(unit='mΩ'),dict(method_version='M2'),dict(unit_id='UNKNOWN'),dict(measured=None),
                   dict(measured='2026-10-02T08:00:00'),dict(registered='2026-09-27T07:00:00')]
        for fields in mutations:
            self.setUp();self.p[29].update(fields);d=self.result();self.assertFalse(d['points'][29]['eligible']);self.assertIsNone(d['points'][30]['mr'])
    def test_clock_reversal_held_and_does_not_bridge(self):
        self.p[29]['measured']=self.p[27]['measured'];d=self.result();self.assertFalse(d['points'][29]['eligible']);self.assertIsNone(d['points'][30]['mr'])
    def test_nonfinite_boolean_or_string_not_numeric(self):
        for value in [float('nan'),float('inf'),True,'1',None]:
            self.setUp();self.p[0]['value']=value;d=self.result();self.assertIsNone(d['limits']);self.assertFalse(d['points'][0]['eligible'])
    def test_overflow_pauses_instead_of_infinite_control_limit(self):
        for i,p in enumerate(self.p):p['value']=(-1 if i%2 else 1)*1e308
        d=self.result();self.assertIsNone(d['limits']);self.assertGreater(d['coverage']['held'],0)
    def test_malformed_sequence_does_not_crash(self):
        self.p[0]['sequence']=None;self.assertIsNone(self.result()['limits'])
    def test_baseline_signals_are_shown_not_removed(self):
        self.p[0]['value']=30;d=self.result();self.assertTrue(d['points'][0]['i_signal']);self.assertGreater(d['signal_counts']['baseline']['i'],0)
    def test_original_input_is_not_changed(self):
        before=deepcopy((self.s,self.p,self.spec,self.units));self.result();self.assertEqual((self.s,self.p,self.spec,self.units),before)
    def test_no_causal_claim_from_event(self):
        e=dict(id='EV',study_id='S1',sequence=30,occurred=self.p[29]['measured'],registered=self.p[29]['registered'])
        d=spc.analyze(self.s,self.p,self.spec,self.units,[e]);self.assertTrue(d['events'][0]['context_valid']);self.assertFalse(d['events'][0]['causal_claim'])

class SPCSourceContractTests(SimpleTestCase):
    def test_zero_valid_missing_blank_and_finite_contract(self):
        self.assertEqual(spc_source_contract.issues('spc_observations',dict(state='有效',value=0)),[])
        self.assertTrue(spc_source_contract.issues('spc_observations',dict(state='有效',value=float('inf'))))
        self.assertTrue(spc_source_contract.issues('spc_observations',dict(state='缺测',value=0)))
    def test_plan_range_and_naive_time(self):
        self.assertTrue(spc_source_contract.issues('spc_studies',dict(expected_points=20,baseline_end=21)))
        self.assertTrue(spc_source_contract.issues('spc_observations',dict(measured='2026-09-27T08:00:00+08:00')))

class SPCAPITests(PlatformCase):
    def setUp(self):
        super().setUp();self.s,self.p,self.spec,self.units=fixture(n=40);self.record('spc_studies',self.s);self.record('test_specs',self.spec)
        self.record('products',dict(id='P1',family='SIM',price_cents=900));self.record('equipment',dict(id='D1',name='模拟设备',cost_cents=100))
        self.record('employees',dict(id='E1',name='合成人员'))
        for u in self.units.values():self.record('units',u)
        for p in self.p:self.record('spc_observations',p)
        self.client.force_login(self.quality)
    def board(self,query=''):return self.client.get('/api/spc/S1'+query)
    def d(self):return self.board().json()
    def detail(self,d=None,point='O30'):
        return self.client.get('/api/spc/S1/points/'+point,{'receipt':(d or self.d())['receipt']})
    def change(self,dataset,key,fields):
        r=Record.objects.get(dataset=dataset,business_key=key);r.values.update(fields);r.record_hash=fingerprint(r.values);r.revision+=1;r.save()
        row=r.source_row;row.normalized=r.values;row.record_hash=r.record_hash;row.save()
    def test_requires_login_and_supported_method(self):
        self.client.logout();self.assertEqual(self.board().status_code,401);self.client.force_login(self.quality);self.assertEqual(self.client.post('/api/spc/S1').status_code,405)
    def test_all_six_roles_see_chart_but_money_is_removed(self):
        for role in ['admin','analyst','quality','operations','finance','viewer']:
            user=User.objects.filter(username=role).first() or User.objects.create_user(role)
            g,_=Group.objects.get_or_create(name=role);user.groups.add(g);self.client.force_login(user);response=self.board();self.assertEqual(response.status_code,200)
            self.assertEqual('price_cents' in response.json()['product'],role in ['admin','analyst','finance'])
    def test_page_never_changes_baseline_or_full_chart(self):
        a=self.d();b=self.board('?page=2').json();self.assertEqual(a['limits'],b['limits']);self.assertEqual(a['chart_points'],b['chart_points']);self.assertEqual(len(a['rows']),25);self.assertEqual(len(b['rows']),15)
    def test_reads_never_add_audit_facts_or_account_states(self):
        before=(AuditEvent.objects.count(),Record.objects.count(),AccountAccessState.objects.count());d=self.d();self.detail(d)
        self.client.get('/api/spc/S1/sources',{'receipt':d['receipt']});self.assertEqual(before,(AuditEvent.objects.count(),Record.objects.count(),AccountAccessState.objects.count()))
    def test_receipt_required_tampered_expired_and_cross_user(self):
        self.assertEqual(self.client.get('/api/spc/S1/points/O30').status_code,400);d=self.d()
        self.assertEqual(self.client.get('/api/spc/S1/points/O30',{'receipt':d['receipt']+'x'}).status_code,409)
        with patch('django.core.signing.time.time',return_value=0):old=self.d()
        self.assertEqual(self.detail(old).status_code,409);self.client.force_login(self.admin);self.assertEqual(self.detail(d).status_code,409)
    def test_scope_and_rules_or_source_changes_conflict(self):
        d=self.d();self.change('spc_observations','O40',dict(value=15));self.assertEqual(self.detail(d).status_code,409)
        d=self.d()
        with patch('app.spc.rule_hash',return_value='changed'):self.assertEqual(self.detail(d).status_code,409)
        self.assertEqual(self.detail(d,point='FOREIGN').status_code,404)
    def test_receipt_invalidated_on_account_epoch(self):
        d=self.d();AccountAccessState.objects.create(user=self.quality,session_epoch=1)
        self.assertEqual(self.detail(d).status_code,401) # Middleware ends the stale session.
    def test_unknown_repeated_or_invalid_params_rejected(self):
        for q in ['?unknown=1','?page=0','?page=-1','?page=1&page=2','?page=1.5']:
            self.assertEqual(self.board(q).status_code,400)
    def test_detail_evidence_includes_exact_predecessor(self):
        d=self.detail().json();ids={(s['dataset'],s['key']) for s in d['sources']};self.assertIn(('spc_observations','O29'),ids);self.assertIn(('units','U30'),ids)
        self.change('spc_observations','O29',dict(state='作废'));d=self.detail().json();self.assertNotIn(('spc_observations','O29'),{(s['dataset'],s['key']) for s in d['sources']})
    def test_full_csv_not_page_and_formula_safe(self):
        self.change('spc_observations','O40',dict(reference='=SIM()'));d=self.d();response=self.client.get('/api/spc/S1/export',{'page':'2','receipt':d['receipt']})
        self.assertEqual(response.status_code,200);rows=list(csv.reader(io.StringIO(response.content.decode('utf-8-sig'))));self.assertEqual(len(rows)-8,40)
        self.assertEqual(rows[-1][0],'O40');self.assertIn("'=SIM()",rows[-1]);self.assertEqual(AuditEvent.objects.filter(action='spc.export').get().detail['rows'],40)
    def test_changed_original_registration_invalidates_receipt(self):
        d=self.d();self.batch.filename='changed.xlsx';self.batch.save();self.assertEqual(self.detail(d).status_code,409)
    def test_fact_import_row_mismatch_fails_instead_of_displaying(self):
        r=Record.objects.get(dataset='spc_observations',business_key='O1');r.values['value']=100;r.save();self.assertEqual(self.board().status_code,400)
    def test_export_conflict_never_creates_audit(self):
        d=self.d();self.change('spc_observations','O40',dict(value=15));before=AuditEvent.objects.count()
        r=self.client.get('/api/spc/S1/export',{'receipt':d['receipt']});self.assertEqual(r.status_code,409);self.assertEqual(AuditEvent.objects.count(),before)
