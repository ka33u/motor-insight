import copy,csv,io,json
from unittest.mock import patch
from django.test import SimpleTestCase,Client
from django.contrib.auth.models import User,Group
from app import process_quality as pq,analytics
from app.models import Record,IssueDisposition,AuditEvent
from .test_platform import PlatformCase

def fixture():
    return dict(products=[dict(id='P1',family='YE4',model='模拟型号',price_cents=100)],work_orders=[dict(id='W1',product_id='P1',route_version='R1')],batches=[dict(id='B1',work_order_id='W1',kind='定子')],equipment=[dict(id='EQ1',process='冲片')],employees=[dict(id='E1',hourly_cents=100)],routes=[dict(id='R01',product_id='P1',version='R1',process='冲片',branch='定子')],operations=[dict(id='OP1',work_order_id='W1',object_type='生产批次',object_id='B1',process='冲片',equipment_id='EQ1',started='2026-09-21T08:00:00',finished='2026-09-21T09:00:00')],process_specs=[dict(id='S1',product_id='P1',route_version='R1',process='冲片',branch='定子',version='V1',parameter='BURR',name='毛刺',unit='mm',lsl=0.,usl=.05,mandatory=True,effective='2026-09-01',expires=None,basis='模拟')],process_check_plans=[dict(id='PQC1',operation_id='OP1',stage='首件',due='2026-09-21T08:10:00',spec_version='V1',basis='模拟')],process_checks=[dict(id='C1',plan_id='PQC1',sample='SAMPLE1',checked='2026-09-21T08:11:00',inspector_id='E1',voided=False,reason='模拟记录')],process_readings=[dict(id='V1',check_id='C1',spec_id='S1',value=.025,unit='mm',instrument='I1')])

class ProcessEvidenceTests(SimpleTestCase):
    def setUp(self):self.d=fixture()
    def engine(self,**f):return pq.ProcessQuality(self.d,pq.filters(f))
    def add_check(self,**delta):
        self.d['process_checks'].append({**self.d['process_checks'][0],'id':'C2','checked':'2026-09-21T08:12:00',**delta})
        self.d['process_readings'].append({**self.d['process_readings'][0],'id':'V2','check_id':'C2','value':.03})
    def test_valid_zero_and_inclusive_bounds(self):
        for value in [0,.05,.025]:
            self.d['process_readings'][0]['value']=value;r=self.engine().selected()[0];self.assertEqual(r['state'],'齐项且范围内')
    def test_strict_outside_and_first_recheck_separate(self):
        self.d['process_readings'][0]['value']=.051;self.add_check();r=self.engine().selected()[0]
        self.assertEqual((r['first_state'],r['latest_state'],r['checks']),('有超限','齐项且范围内',2));self.assertEqual(self.engine().summary([r])['first_pass'],0)
        self.assertEqual(self.engine(tab='parameters',spec='S1',mode='first').parameters()['summary']['out'],1)
        self.assertEqual(self.engine(tab='parameters',spec='S1',mode='latest').parameters()['summary']['out'],0)
    def test_plan_without_checks_remains_pending(self):
        self.d['process_checks']=[];self.d['process_readings']=[];r=self.engine().selected()[0];self.assertIn('pending',r['flags']);self.assertNotIn('pass',r['flags'])
    def test_only_voided_is_pending(self):
        self.d['process_checks'][0]['voided']=True;r=self.engine().selected()[0];self.assertEqual((r['checks'],r['voided']),(0,1));self.assertIn('pending',r['flags'])
    def test_voided_latest_does_not_replace_bad_first(self):
        self.d['process_readings'][0]['value']=.06;self.add_check(voided=True);self.assertEqual(self.engine().selected()[0]['latest_state'],'有超限')
    def test_future_execution_hidden(self):
        self.add_check(checked='2026-10-02T08:00:00');r=self.engine().detail('PQC1');self.assertEqual(len(r['executions']),1);self.assertEqual(r['row']['future_checks'],1)
    def test_future_plan_not_overdue(self):
        self.d['process_check_plans'][0]['due']='2026-10-02T08:00:00';self.d['process_checks']=[];self.assertIn('future',self.engine().selected()[0]['flags'])
    def test_incomplete_latest_never_falls_back(self):
        self.add_check();self.d['process_readings'].pop();r=self.engine().selected()[0];self.assertEqual(r['latest_state'],'有漏项');self.assertNotIn('pass',r['flags'])
    def test_out_and_missing_flags_can_overlap(self):
        self.d['process_specs'].append({**self.d['process_specs'][0],'id':'S2','parameter':'THICKNESS'});self.d['process_readings'][0]['value']=.06
        r=self.engine().selected()[0];self.assertEqual(r['state'],'超限且漏项');self.assertTrue({'out','missing'}<=set(r['flags']))
    def test_wrong_unit_excluded_without_better_fallback(self):
        self.add_check();self.d['process_readings'][-1]['unit']='cm';r=self.engine(tab='parameters',spec='S1').parameters()
        self.assertEqual((r['summary']['samples'],r['summary']['excluded']),(0,1));self.assertEqual(self.engine().selected()[0]['state'],'资料待核对')
    def test_duplicate_spec_readings_suspend_execution(self):
        self.d['process_readings'].append({**self.d['process_readings'][0],'id':'V2'});self.assertIn('attention',self.engine().selected()[0]['flags']);self.assertFalse(self.engine(tab='parameters',spec='S1').parameters()['rows'])
    def test_tied_execution_order_suspends_first_and_latest(self):
        self.add_check(checked='2026-09-21T08:11:00');r=self.engine().selected()[0];self.assertFalse(r['ordering_valid']);self.assertEqual(self.engine(tab='parameters',spec='S1').parameters()['summary']['samples'],0)
    def test_expiry_is_exclusive(self):
        self.d['process_specs'][0]['expires']='2026-09-21';self.assertIn('attention',self.engine().selected()[0]['flags'])
    def test_overlapping_parameter_versions_not_picked_arbitrarily(self):
        self.d['process_specs'].append({**self.d['process_specs'][0],'id':'S2'});self.assertIn('attention',self.engine().selected()[0]['flags'])
    def test_spec_identity_mismatches(self):
        for key,value in [('product_id','P2'),('process','装配'),('branch','转子'),('version','V2'),('route_version','R2')]:
            self.d=fixture();self.d['process_specs'][0][key]=value;self.assertIn('attention',self.engine().selected()[0]['flags'],key)
    def test_invalid_spec_bounds_dates_or_no_mandatory(self):
        for delta in [dict(lsl=None,usl=None),dict(lsl=.1),dict(usl=float('inf')),dict(effective='bad'),dict(expires='2026-08-01'),dict(mandatory=False)]:
            self.d=fixture();self.d['process_specs'][0].update(delta);self.assertIn('attention',self.engine().selected()[0]['flags'])
    def test_nonfinite_bool_and_non_numeric_values(self):
        for v in [True,float('nan'),float('inf'),'.02',None]:
            self.d['process_readings'][0]['value']=v;self.assertIn('attention',self.engine().selected()[0]['flags']);self.assertFalse(self.engine(tab='parameters',spec='S1').parameters()['rows'])
    def test_negative_lower_limit_allowed(self):
        self.d['process_specs'][0].update(lsl=-1,usl=1);self.d['process_readings'][0]['value']=-.2;self.assertEqual(self.engine().selected()[0]['state'],'齐项且范围内')
    def test_missing_optional_not_incomplete(self):
        self.d['process_specs'].append({**self.d['process_specs'][0],'id':'S2','parameter':'OPT','mandatory':False});self.assertEqual(self.engine().selected()[0]['state'],'齐项且范围内')
    def test_bad_time_before_start_or_staff(self):
        for delta in [dict(checked='bad'),dict(checked='2026-09-20T08:00:00'),dict(inspector_id='E99'),dict(voided='no')]:
            self.d=fixture();self.d['process_checks'][0].update(delta);self.assertIn('attention',self.engine().selected()[0]['flags'])
    def test_missing_core_relation_or_wrong_equipment(self):
        for ds in ['operations','products','work_orders','routes','batches','equipment']:
            self.d=fixture();self.d[ds]=[];self.assertIn('attention',self.engine().selected()[0]['flags'],ds)
        self.d=fixture();self.d['equipment'][0]['process']='装配';self.assertIn('attention',self.engine().selected()[0]['flags'])
    def test_inspection_incomplete_valid_parameter_can_be_shown(self):
        self.d['process_specs'].append({**self.d['process_specs'][0],'id':'S2','parameter':'OTHER'});r=self.engine(tab='parameters',spec='S1').parameters();self.assertEqual(r['summary']['samples'],1);self.assertEqual(r['rows'][0]['check_state'],'有漏项')
    def test_histogram_constant_and_edge_max(self):
        r=self.engine(tab='parameters',spec='S1').parameters();self.assertEqual(len(r['bins']),1);self.assertEqual(r['bins'][0]['count'],1)
        self.add_check();r=self.engine(tab='parameters',spec='S1',mode='all').parameters();self.assertEqual(r['bins'][-1]['count'],1);self.assertEqual(sum(x['count'] for x in r['bins']),2)
    def test_bin_zero_is_not_all_and_summary_stays_total(self):
        self.add_check();r=self.engine(tab='parameters',spec='S1',mode='all',bin='0').parameters();self.assertEqual((len(r['rows']),r['summary']['samples']),(1,2));self.assertEqual(r['rows'][0]['id'],'V1')
    def test_filter_exact_scope_and_date_semantics(self):
        for f in [dict(product='none'),dict(family='none'),dict(equipment='none'),dict(branch='转子'),dict(kind='巡检'),{'from':'2026-09-22'}]:self.assertFalse(self.engine(**f).selected())
        self.assertEqual(len(self.engine(q='w1').selected()),1)
        with self.assertRaises(Record.DoesNotExist):self.engine(product='none').detail('PQC1')
    def test_stage_and_parameter_population_match(self):
        self.assertEqual(self.engine(stage='pending').parameters()['summary']['samples'],0)
        with self.assertRaises(Record.DoesNotExist):self.engine(stage='pending').detail('PQC1')
    def test_no_auto_spec_and_empty_range_does_not_fallback(self):
        self.assertEqual(self.engine(tab='parameters').parameters()['summary']['samples'],0);self.assertEqual(self.engine(tab='parameters',spec='S1',product='none').parameters()['summary']['samples'],0)
    def test_invalid_filters(self):
        for f in [dict(unknown='x'),dict(tab='bad'),dict(stage='bad'),dict(mode='bad'),dict(kind='抽检'),dict(bin='0'),dict(tab='parameters',spec='S1',bin='8'),{'from':'2026-10-02','to':'2026-10-01'}]:
            with self.assertRaises(ValueError):pq.filters(f)
    def test_orphan_evidence_is_exposed(self):
        self.d['process_checks'][0]['plan_id']='missing';self.d['process_readings'][0]['check_id']='missing';self.assertEqual(len(self.engine().orphans),2)
    def test_no_mutation(self):
        before=copy.deepcopy(self.d);e=self.engine(tab='parameters',spec='S1');e.parameters();e.detail('PQC1');self.assertEqual(before,self.d)

class ProcessQualityAPI(PlatformCase):
    def setUp(self):
        super().setUp()
        for ds,rows in fixture().items():
            for row in rows:self.record(ds,row)
        self.client.force_login(self.admin)
    def payload(self):return dict(status='待工艺核对',owner='工艺岗位（模拟）',note='核对单位和规范适用版本',due_date='2026-10-05',version=0,data_revision=list(analytics.revision()))
    def test_board_detail_sources_and_read_only_permissions(self):
        self.client.force_login(self.quality)
        for url in ['/api/process-quality','/api/process-quality/PQC1','/api/process-quality/PQC1/evidence','/api/process-quality/export']:
            r=self.client.get(url);self.assertEqual(r.status_code,200);self.assertEqual(r.headers['Cache-Control'],'no-store');self.assertNotIn('cents',r.content.decode())
        self.assertEqual(Client().get('/api/process-quality').status_code,401)
        rows=self.client.get('/api/process-quality/PQC1/evidence').json()['rows'];self.assertTrue(any(r['dataset']=='process_specs' for r in rows))
    def test_export_scope_and_grain(self):
        r=self.client.get('/api/process-quality/export?tab=parameters&spec=S1').content.decode('utf-8-sig');rows=list(csv.reader(io.StringIO(r)));self.assertEqual((len(rows),rows[3][0]),(4,'V1'))
        self.assertEqual(self.client.get('/api/process-quality?stage=pending').json()['total'],0)
        self.assertEqual(self.client.get('/api/process-quality/PQC1?stage=pending').status_code,404)
    def test_followup_preserves_facts_and_versions(self):
        before=list(Record.objects.values_list('id','values'));p=self.payload();url='/api/process-quality/PQC1/follow-up'
        self.assertEqual(self.post(url,p).status_code,200);self.assertEqual(self.post(url,p).status_code,409);self.assertEqual(before,list(Record.objects.values_list('id','values')))
        self.assertEqual(self.client.get('/api/process-quality/PQC1/history').json()['rows'][0]['detail']['after']['version'],1)
        p.update(version=1,data_revision=['stale']);self.assertEqual(self.post(url,p).status_code,409)
    def test_viewer_cannot_follow_and_csrf_required(self):
        viewer=User.objects.create_user('viewer');self.client.force_login(viewer);self.assertEqual(self.post('/api/process-quality/PQC1/follow-up',self.payload()).status_code,403)
        c=Client(enforce_csrf_checks=True);c.force_login(self.admin);self.assertEqual(c.post('/api/process-quality/PQC1/follow-up',json.dumps(self.payload()),content_type='application/json').status_code,403)
    def test_bad_payload_and_atomic_audit(self):
        for delta in [dict(status='批准投产'),dict(version=True),dict(due_date='bad'),dict(note='短'),dict(other=1)]:self.assertEqual(self.post('/api/process-quality/PQC1/follow-up',{**self.payload(),**delta}).status_code,400)
        with patch('app.process_quality_views.AuditEvent.objects.create',side_effect=RuntimeError('failed')):
            with self.assertRaises(RuntimeError):self.post('/api/process-quality/PQC1/follow-up',self.payload())
        self.assertFalse(IssueDisposition.objects.filter(key='process-quality:PQC1').exists())
    def test_csv_formula_injection(self):
        r=Record.objects.get(dataset='process_checks');r.values['sample']='=1+1';r.save();self.assertIn("'=1+1",self.client.get('/api/process-quality/export?tab=parameters&spec=S1').content.decode('utf-8-sig'))
    def test_ops_cannot_confirm_review(self):
        u=User.objects.create_user('ops');u.groups.add(Group.objects.create(name='operations'));self.client.force_login(u)
        self.assertEqual(self.post('/api/process-quality/PQC1/follow-up',{**self.payload(),'status':'演练已核对'}).status_code,403)
