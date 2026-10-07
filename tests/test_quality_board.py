import json,io,csv
from copy import deepcopy
from unittest.mock import patch
from django.test import SimpleTestCase,Client
from django.contrib.auth.models import User,Group
from app import quality_board as quality,analytics
from app.models import Record,IssueDisposition,AuditEvent
from app.schema import SCHEMAS
from tests.test_platform import PlatformCase

def fixture():
    d={k:[] for k in SCHEMAS}
    d['products']=[dict(id='P1',model='模拟电机',family='YE4',price_cents=99999)]
    d['work_orders']=[dict(id='W1',product_id='P1')]
    d['units']=[dict(id='U'+str(i),product_id='P1',work_order_id='W1',assembly_at='2026-09-21T08:00:00',stator_batch='B1',rotor_batch='B2') for i in range(1,6)]
    d['test_specs']=[dict(id=k,product_id='P1',version='A',test_code=k,test_name=k+'项目',unit='A',lsl=0,usl=2,mandatory=True,effective='2026-09-01') for k in ['R','V']]
    sessions=[('T11','U1',1,'2026-09-21T09:00:00',False,True,3,'D1'),('T12','U1',2,'2026-09-21T10:00:00',False,True,1,'D2'),('T21','U2',1,'2026-09-21T09:00:00',False,False,1,'D1'),('T22','U2',2,'2026-09-21T10:00:00',False,True,1,'D2'),('T31','U3',1,'2026-09-21T09:00:00',True,True,1,'D1'),('T51','U5',1,'2026-09-21T09:00:00',False,True,1,'D1'),('T52','U5',2,'2026-09-21T10:00:00',False,False,1,'D1'),('FUT','U4',1,'2026-10-05T09:00:00',False,True,1,'D1')]
    for sid,uid,attempt,tested,voided,complete,value,device in sessions:
        d['test_sessions'].append(dict(id=sid,unit_id=uid,attempt=attempt,tested=tested,voided=voided,complete=complete,result='不完整' if not complete else '合格' if value<=2 else '不合格',equipment_id=device,spec_version='A',temperature_c=25,reason='模拟',operator_id='E1'))
        for code in ['R','V'] if complete else ['R']:
            v=value if code=='R' else 1
            d['measurements'].append(dict(id=sid+'-'+code,session_id=sid,spec_id=code,value=v,unit='A',raw_value=v,raw_unit='A',result='合格' if v<=2 else '不合格',file_reference=sid+'.csv'))
    d['releases']=[dict(id='REL1',unit_id='U1',session_id='T12',status='批准放行',released='2026-09-21T11:00:00'),dict(id='REL5',unit_id='U5',session_id='T51',status='批准放行',released='2026-09-21T09:30:00')]
    return d

class QualityFactsTests(SimpleTestCase):
    def setUp(self):self.d=fixture()
    def data(self):return quality.QualityData(self.d)
    def dist(self,sample='first_complete',device='',spec='R'):
        d=self.data();return quality.distribution(d,d.rows,'P1',spec,sample,device)
    def test_first_event_first_complete_and_coverage_remain_distinct(self):
        s=quality.summary(self.data().rows)
        self.assertEqual((s['units'],s['tested'],s['complete'],s['first_pass'],s['first_complete_pass']),(5,3,3,1,2))
        self.assertEqual((s['first_pass_rate'],s['first_complete_pass_rate'],s['complete_coverage']),(33.33,66.67,60))
        self.assertEqual(s['retested'],3);self.assertEqual(s['recovered_after_first_fail'],1)
    def test_latest_incomplete_invalidates_old_release_without_erasing_first_complete(self):
        u=self.data().unit_index['U5'];self.assertEqual(u['first_complete_result'],'合格');self.assertEqual(u['latest_result'],'不完整');self.assertFalse(u['release_valid']);self.assertIn('incomplete',u['flags'])
    def test_voided_and_future_sessions_do_not_become_first_tests(self):
        d=self.data();s=quality.summary(d.rows)
        self.assertEqual((s['voided_sessions'],s['future_sessions_excluded']),(1,1));self.assertIsNone(d.unit_index['U3']['first_session']);self.assertIsNone(d.unit_index['U4']['first_session'])
        detail=d.detail('U3');self.assertTrue(detail['sessions'][0]['voided']);self.assertEqual(detail['sessions'][0]['calculated_result'],'作废，不参与统计')
        self.assertEqual(d.detail('U4')['sessions'],[])
    def test_missing_and_exceeding_items_are_separate_and_not_summed_as_sn(self):
        d=self.data();self.assertEqual(quality.defects(d.rows),[{'test_code':'V','unit_count':0,'missing_count':1}])
        self.assertEqual(next(c for c in d.unit_index['U5']['cells'] if c['test_code']=='V')['result'],'缺项')
    def test_time_and_spec_effective_errors_pause_rates_and_distribution(self):
        self.d['test_sessions'][0]['tested']='2026-09-20T09:00:00';self.d['test_specs'][0]['effective']='2026-09-22'
        d=self.data();self.assertTrue(quality.summary(d.rows)['rates_paused']);self.assertIsNone(quality.summary(d.rows)['first_pass_rate']);self.assertTrue(d.unit_index['U1']['issues'])
        self.assertEqual(self.dist()['stats']['n'],0)
    def test_duplicate_or_wrong_config_measurement_is_never_averaged(self):
        self.d['measurements'].append({**self.d['measurements'][0],'id':'DUP'})
        d=self.data();self.assertIn('attention',d.unit_index['U1']['flags']);self.assertFalse(d.unit_index['U1']['_sessions'][0]['calculated_complete'])
        self.d=fixture();self.d['test_specs'].append({**self.d['test_specs'][0],'id':'OTHER','product_id':'P2'})
        self.d['measurements'][0]['spec_id']='OTHER';self.assertTrue(quality.summary(self.data().rows)['rates_paused'])
    def test_mismatch_and_nonfinite_values_require_review(self):
        self.d['measurements'][0]['result']='合格';self.assertTrue(quality.summary(self.data().rows)['rates_paused'])
        self.d['measurements'][0]['value']=float('nan');r=self.dist();self.assertTrue(all(x['value']==x['value'] for x in r['observations']))
    def test_equipment_filter_does_not_relabel_retest_as_first(self):
        r=self.dist(device='D2');self.assertEqual([x['unit_id'] for x in r['observations']],['U2']);self.assertEqual(r['stats']['n'],1)
        self.assertEqual(r['excluded']['检测设备筛选排除'],2)
    def test_all_sessions_mode_preserves_repeated_units(self):
        r=self.dist(sample='all_valid');self.assertEqual(r['stats']['n'],6);self.assertEqual(r['stats']['unique_units'],3)
        latest=self.dist(sample='latest');self.assertEqual(latest['stats']['n'],3)
    def test_configuration_and_spec_version_are_hard_boundaries(self):
        d=self.data()
        with self.assertRaises(ValueError):quality.distribution(d,d.rows,'P2','R','latest')
        with self.assertRaises(ValueError):quality.distribution(d,d.rows,'','R','latest')
        self.d['test_sessions'][0]['spec_version']='B';r=self.dist(sample='all_valid');self.assertEqual(r['excluded']['规范版本不同'],1)
    def test_histogram_extremes_and_quantiles_reconcile(self):
        r=self.dist();self.assertEqual(sum(b['count'] for b in r['bins']),r['stats']['n']);self.assertEqual(r['stats']['outside'],1)
        self.assertEqual(r['stats']['median'],1);self.assertAlmostEqual(r['stats']['p90'],2.6)
        self.assertEqual(next(x for x in r['observations'] if x['value']==3)['bin'],7)
        constant=self.dist(spec='V');self.assertEqual(len(constant['bins']),1);self.assertEqual(constant['bins'][0]['count'],3)
    def test_binary_results_use_categories_and_no_numeric_mean(self):
        self.d['test_specs'][1].update(unit='bool',lsl=1,usl=1)
        for m in self.d['measurements']:
            if m['spec_id']=='V':m['unit']='bool'
        r=self.dist(spec='V');self.assertTrue(r['binary']);self.assertEqual([b['count'] for b in r['bins']],[0,3]);self.assertIsNone(r['stats']['mean'])
    def test_empty_scopes_keep_null_rates_and_no_phantom_sample(self):
        f=quality.filters({'q':'NONE'});self.assertEqual(quality.cohort(self.data().rows,f),[]);self.assertIsNone(quality.summary([])['complete_coverage'])
        d=self.data();r=quality.distribution(d,[],'P1','R','latest');self.assertEqual(r['bins'],[]);self.assertEqual(r['stats']['n'],0)
    def test_invalid_filters_fail_closed(self):
        for f in [{'stage':'bad'},{'assembly_from':'2026-10-03','assembly_to':'2026-09-01'},{'sql':'anything'}]:
            with self.assertRaises(ValueError):quality.filters(f)

class QualityApiTests(PlatformCase):
    def setUp(self):
        super().setUp();self.d=fixture()
        for ds,rows in self.d.items():
            for r in rows:self.record(ds,r)
        analytics._tables.cache_clear();quality.cached.cache_clear();self.addCleanup(analytics._tables.cache_clear);self.addCleanup(quality.cached.cache_clear);self.client.force_login(self.quality)
    def payload(self):return dict(version=0,status='排查中',owner='模拟质量岗位',note='核对原始检测和后续复测证据',due_date='2026-10-06',data_revision=list(analytics.revision()))
    def test_board_stage_export_and_scope_totals_are_explicit(self):
        b=self.client.get('/api/quality?stage=incomplete').json();self.assertEqual(b['total'],1);self.assertEqual(b['summary']['units'],5);self.assertEqual(b['rows'][0]['id'],'U5')
        data=list(csv.reader(io.StringIO(self.client.get('/api/quality/export?stage=incomplete').content.decode('utf-8-sig'))));self.assertEqual(len(data)-3,b['total']);self.assertEqual(data[3][0],'U5')
        self.assertEqual(self.client.get('/api/quality?assembly_from=2026-09-22').json()['summary']['units'],0)
    def test_item_drill_matches_missing_project_count_without_changing_cohort(self):
        b=self.client.get('/api/quality?test_code=V&item_state=missing').json();self.assertEqual(b['summary']['units'],5);self.assertEqual(b['total'],1);self.assertEqual(b['rows'][0]['id'],'U5')
        exported=list(csv.reader(io.StringIO(self.client.get('/api/quality/export?test_code=V&item_state=missing').content.decode('utf-8-sig'))));self.assertEqual(len(exported)-3,1)
    def test_selected_device_keeps_zero_rows_instead_of_falling_back_to_all(self):
        r=self.client.get('/api/quality/distribution?product_id=P1&spec_id=R&equipment_id=NONE').json();self.assertEqual(r['total'],0);self.assertEqual(r['stats']['n'],0);self.assertEqual(r['rows'],[])
    def test_distribution_bin_drill_and_export_use_same_observations(self):
        q='product_id=P1&spec_id=R&sample=first_complete&bin=7'
        r=self.client.get('/api/quality/distribution?'+q).json();self.assertEqual(r['stats']['n'],3);self.assertEqual(r['total'],1);self.assertEqual(r['rows'][0]['unit_id'],'U1')
        data=list(csv.reader(io.StringIO(self.client.get('/api/quality/distribution/export?'+q).content.decode('utf-8-sig'))));self.assertEqual(len(data)-5,1);self.assertEqual(data[5][0],'U1')
        self.assertEqual(self.client.get('/api/quality/distribution?'+q.replace('bin=7','bin=99')).status_code,400)
    def test_detail_sources_roles_and_sensitive_fields(self):
        self.assertEqual(Client().get('/api/quality').status_code,401)
        r=self.client.get('/api/quality/units/U1');self.assertNotIn('price_cents',r.content.decode());self.assertEqual(len(r.json()['sessions']),2)
        e=self.client.get('/api/quality/units/U1/evidence').json();self.assertFalse(e['can_download_original']);self.assertTrue(any(x.get('filename')=='unit-test.xlsx' for x in e['rows']))
        self.assertEqual(self.client.get('/api/quality/units/UNKNOWN').status_code,404)
    def test_coordination_has_versions_source_guard_and_no_fact_changes(self):
        before=list(Record.objects.values_list('values',flat=True));p=self.payload();r=self.post('/api/quality/units/U1/follow-up',p);self.assertEqual(r.status_code,200,r.content);self.assertEqual(r.json()['follow_up']['version'],1)
        self.assertEqual(self.post('/api/quality/units/U1/follow-up',p).status_code,409)
        p.update(version=1,data_revision=[0,'old']);self.assertEqual(self.post('/api/quality/units/U1/follow-up',p).status_code,409)
        self.assertEqual(list(Record.objects.values_list('values',flat=True)),before);self.assertEqual(self.client.get('/api/quality/units/U1/history').json()['rows'][0]['detail']['latest_session'],'T12')
    def test_followup_roles_csrf_and_audit_rollback(self):
        user=User.objects.create_user('ops-quality');user.groups.add(Group.objects.get_or_create(name='operations')[0]);self.client.force_login(user)
        p=self.payload();p['status']='演练已核验';self.assertEqual(self.post('/api/quality/units/U1/follow-up',p).status_code,403)
        user.groups.clear();self.assertEqual(self.post('/api/quality/units/U1/follow-up',self.payload()).status_code,401)
        self.client.force_login(user);self.assertEqual(self.post('/api/quality/units/U1/follow-up',self.payload()).status_code,403)
        self.client.force_login(self.quality)
        with patch('app.quality_views.AuditEvent.objects.create',side_effect=RuntimeError('audit failed')):
            with self.assertRaises(RuntimeError):self.post('/api/quality/units/U1/follow-up',self.payload())
        self.assertEqual(IssueDisposition.objects.count(),0)
        client=Client(enforce_csrf_checks=True);client.force_login(self.quality);self.assertEqual(client.post('/api/quality/units/U1/follow-up','{}',content_type='application/json').status_code,403)
    def test_export_escapes_formula_and_ignores_ui_pagination(self):
        r=Record.objects.get(dataset='units',business_key='U1');r.values['work_order_id']='=EVIL()';r.save()
        result=list(csv.reader(io.StringIO(self.client.get('/api/quality/export?page=2').content.decode('utf-8-sig'))));self.assertEqual(len(result)-3,5);self.assertEqual(result[3][2],"'=EVIL()")
