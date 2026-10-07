import copy,csv,io,json,uuid
from datetime import datetime,timezone as tz
from unittest.mock import patch
from django.test import SimpleTestCase,Client
from django.contrib.auth.models import User,Group
from django.utils import timezone
from tests.test_platform import PlatformCase
from app import data_health as h,analytics
from app.ingestion import fingerprint
from app.models import Record,DataQualityScan,DataMonitorPolicy,AuditEvent,ImportBatch


def item(ds,values,key=None,pk=1):
    key=key or values['id'];sha=fingerprint(values)
    return {'id':pk,'dataset':ds,'business_key':key,'values':values,'record_hash':sha,'source_row__batch_id':'B','source_row__dataset':ds,'source_row__business_key':key,'source_row__record_hash':sha,'source_row__normalized':copy.deepcopy(values)}

class StructuralChecks(SimpleTestCase):
    def scan(self,rows,ids=None):return h.inspect(rows,set(ids or [(r['dataset'],r['business_key']) for r in rows]),{'B':{'id':'B','filename':'模拟.xlsx','committed_at':'2026-10-01T10:00:00+00:00','status':'committed','file_hash':'mock'}})
    def test_valid_records_and_optional_null_are_not_bad(self):
        rows=[item('departments',dict(id='D01',name='车间',owner='主管'))];r=self.scan(rows);self.assertFalse(r['issues']);self.assertEqual(r['datasets']['departments']['rows'],1);self.assertEqual(r['datasets']['departments']['fields']['id']['present'],1)
    def test_missing_required_and_key_disagreement(self):
        r=self.scan([item('departments',dict(id='D02',name='  ',owner=None),key='D01')]);self.assertEqual(Counter(i['rule'] for i in r['issues']),{'required':2,'key':1})
    def test_strict_types_keep_zero_and_false(self):
        for val,kind,ok in [(0,'int',True),(False,'bool',True),(False,'int',False),(1.0,'int',False),('001','str',True),(1,'str',False),(' 001','str',False),(float('inf'),'float',False),(0,'float',True),('=1+1','str',False)]:
            with self.subTest(val=val,kind=kind):self.assertEqual(h.canonical(val,kind),ok)
    def test_canonical_dates_reject_timezone_and_wrong_grain(self):
        self.assertTrue(h.canonical('2026-10-01','date'));self.assertTrue(h.canonical('2026-10-01T18:00:00','datetime'))
        for val,kind in [('2026-10-01T18:00:00','date'),('2026-10-01','datetime'),('2026-10-01T18:00:00+08:00','datetime'),('2026-02-30','date')]:self.assertFalse(h.canonical(val,kind))
    def test_references_checked_without_target_payloads(self):
        r=item('employees',dict(id='E01',name='模拟人',department_id='D-X',role='操作',skill_level='一级',hourly_cents=10000,active=True));out=self.scan([r]);self.assertEqual([i['rule'] for i in out['issues']],['reference']);self.assertEqual(out['datasets']['employees']['fields']['department_id']['reference_missing'],1)
        self.assertFalse(self.scan([r],{('departments','D-X'),('employees','E01')})['issues'])
    def test_hash_and_source_drift_separate(self):
        r=item('departments',dict(id='D01',name='车间',owner='主管'));r['values']['name']='变化';out=self.scan([r]);self.assertEqual({i['rule'] for i in out['issues']},{'source','hash'});self.assertNotIn('变化',json.dumps(out['issues'],ensure_ascii=False))
    def test_source_wrong_identity_flag(self):
        r=item('departments',dict(id='D01',name='车间',owner='主管'));r['source_row__business_key']='D02';self.assertEqual(self.scan([r])['issues'][0]['rule'],'source')
    def test_future_dates_are_descriptive_not_structural_error(self):
        r=item('engineering_changes',dict(id='EC1',product_id='P1',from_version='A',to_version='B',reason='模拟',effective='2026-10-02',approved_by='E1',status='已批准'));out=self.scan([r],{('products','P1'),('employees','E1')});self.assertFalse(out['issues']);stat=out['datasets']['engineering_changes']['fields']['effective'];self.assertEqual(stat['future'],1);self.assertIsNone(stat['past_maximum'])
    def test_all_dates_kept_while_past_max_ignores_future(self):
        rows=[item('engineering_changes',dict(id='EC'+str(i),product_id='P1',from_version='A',to_version='B',reason='模拟',effective=day,approved_by='E1',status='已批准'),pk=i) for i,day in enumerate(['2026-09-28','2026-10-01','2026-10-02'])];out=self.scan(rows,{('products','P1'),('employees','E1')});field=out['datasets']['engineering_changes']['fields']['effective'];self.assertEqual((field['minimum'],field['maximum'],field['past_maximum']),('2026-09-28','2026-10-02','2026-10-01'))
    def test_unknown_dataset_not_claimed_checked(self):
        out=self.scan([], {('unknown','X')});self.assertEqual(out['unknown_datasets'],['unknown'])
    def test_bad_filter_rules(self):
        for f in [dict(stage='normal'),dict(rule='all-good'),dict(q='x'*151),dict(injected='x')]:
            with self.assertRaises(ValueError):h.filters(f)

from collections import Counter
class Freshness(SimpleTestCase):
    def setUp(self):
        self.now=datetime(2026,10,3,12,tzinfo=tz.utc);self.row={'fields':{'when':{'past_maximum':'2026-09-30','future':2}},'batches':[{'committed_at':'2026-10-02T12:00:00+00:00'}]};self.policy={'business_clock':'when','max_business_lag_days':1,'max_import_age_hours':24}
    def result(self):return h.freshness(self.row,self.policy,self.now,analytics.AS_OF)
    def test_date_and_import_exact_threshold_are_within(self):
        r=self.result();self.assertEqual(r['business_lag_days'],1);self.assertEqual(r['import_age_hours'],24);self.assertEqual(r['flags'],['business_within','import_within']);self.assertEqual(r['future_dates'],2)
    def test_timestamp_uses_fractional_natural_days(self):
        self.row['fields']['when']['past_maximum']='2026-09-30T06:00:00';self.assertEqual(self.result()['business_lag_days'],1.5);self.assertIn('business_late',self.result()['flags'])
    def test_no_threshold_is_unconfigured_not_healthy(self):
        self.policy.update(max_business_lag_days=None,max_import_age_hours=None);r=self.result();self.assertFalse(r['has_target']);self.assertEqual(r['flags'],[])
    def test_no_valid_date_or_batch_is_unknown(self):
        self.row['fields']['when']['past_maximum']=None;self.row['batches']=[];self.assertEqual(self.result()['flags'],['business_unknown','import_unknown'])
    def test_bad_future_and_naive_commit_dates_are_unknown(self):
        for value in [None,'bad','2026-10-05T12:00:00+00:00','2026-10-02T12:00:00']:
            self.row['batches']=[{'committed_at':value}];self.assertIn('import_unknown',self.result()['flags'])
    def test_multiple_batches_show_oldest_and_latest(self):
        self.row['batches'].append({'committed_at':'2026-09-01T12:00:00+00:00'});r=self.result();self.assertEqual(r['first_commit'],'2026-09-01T12:00:00+00:00');self.assertEqual(r['import_age_hours'],24)

class DataHealthAPI(PlatformCase):
    def setUp(self):
        super().setUp();self.batch.status='committed';self.batch.committed_at=timezone.now();self.batch.save();self.record('departments',dict(id='D01',name='模拟车间',owner='主管'));self.client.force_login(self.admin)
    def run_scan(self):return self.post('/api/data-health/run',{'request_id':str(uuid.uuid4())})
    def policy(self):return {'version':0,'owner':'质量数据负责人（模拟）','business_clock':'tested','max_business_lag_days':1,'max_import_age_hours':48,'note':'合成数据演练约定，未获真实业务验收'}
    def test_empty_state_does_not_make_healthy_claim(self):
        d=self.client.get('/api/data-health').json();self.assertIsNone(d['scan']);self.assertTrue(d['can_run'])
    def test_run_snapshot_is_idempotent_and_business_facts_preserved(self):
        before=list(Record.objects.values_list('id','values','record_hash'));rid=str(uuid.uuid4());a=self.post('/api/data-health/run',{'request_id':rid});b=self.post('/api/data-health/run',{'request_id':rid});self.assertEqual(a.status_code,200);self.assertEqual(a.json()['id'],b.json()['id']);self.assertEqual(DataQualityScan.objects.count(),1);self.assertEqual(before,list(Record.objects.values_list('id','values','record_hash')))
    def test_record_change_marks_snapshot_stale_without_overwrite(self):
        self.run_scan();scan=DataQualityScan.objects.get();before=copy.deepcopy(scan.snapshot);self.record('departments',dict(id='D02',name='第二车间',owner='主管'));d=self.client.get('/api/data-health').json();self.assertTrue(d['stale']);self.assertEqual(d['summary']['records'],1);scan.refresh_from_db();self.assertEqual(scan.snapshot,before)
    def test_engine_change_marks_stale(self):
        self.run_scan()
        with patch('app.data_health.engine_hash',return_value='changed'):self.assertTrue(self.client.get('/api/data-health').json()['stale'])
    def test_tampered_snapshot_is_blocked(self):
        self.run_scan();scan=DataQualityScan.objects.get();scan.snapshot['as_of']='tampered';scan.save();self.assertEqual(self.client.get('/api/data-health').status_code,400)
    def test_role_projection_hides_financial_rows_and_fields(self):
        self.record('invoices',{'id':'I01'});self.record('employees',dict(id='E01',name='模拟',department_id='D01',role='操作',skill_level='一级',hourly_cents=None,active=True));self.run_scan();self.client.force_login(self.quality);d=self.client.get('/api/data-health').json();self.assertNotIn('invoices',[r['dataset'] for r in d['rows']]);self.assertNotIn('hourly_cents',json.dumps(d));self.assertEqual(self.client.get('/api/data-health/invoices').status_code,403);self.assertEqual(self.client.get('/api/data-health/imports').status_code,403);self.assertEqual(self.run_scan().status_code,403)
        r=self.client.get('/api/data-health/employees');self.assertEqual(r.status_code,200);self.assertNotIn('cents',r.content.decode());self.assertEqual(r.json()['total'],0)
    def test_explicit_scan_can_be_reopened(self):
        a=self.run_scan().json()['id'];b=self.run_scan().json()['id'];self.assertNotEqual(a,b);self.assertEqual(self.client.get('/api/data-health?scan='+a).json()['scan'],a)
    def test_policy_updates_are_versioned_with_audit(self):
        p=self.policy();a=self.post('/api/data-health/test_sessions/policy',p);self.assertEqual(a.status_code,200);self.assertEqual(a.json()['policy']['version'],1);self.assertEqual(self.post('/api/data-health/test_sessions/policy',p).status_code,409);self.assertEqual(len(self.client.get('/api/data-health/test_sessions/history').json()['rows']),1)
    def test_policy_validation_and_no_foreign_date_fields(self):
        for change in [dict(version=True),dict(business_clock='cost_cents'),dict(max_business_lag_days=-1),dict(max_business_lag_days=True),dict(business_clock=''),dict(max_import_age_hours=0),dict(max_import_age_hours=1.5),dict(note='短')]:self.assertEqual(self.post('/api/data-health/test_sessions/policy',{**self.policy(),**change}).status_code,400)
    def test_policy_freshness_changes_without_rescanning(self):
        self.record('test_sessions',dict(id='TS1',unit_id='SN1',attempt=1,equipment_id='EQ1',operator_id='E1',tested='2026-09-25T12:00:00',temperature_c=20,spec_version='A',complete=True,result='合格',reason='模拟',voided=False));self.run_scan();self.post('/api/data-health/test_sessions/policy',self.policy());d=self.client.get('/api/data-health?dataset=test_sessions&stage=late').json();self.assertEqual(d['summary']['tables'],1);self.assertEqual(d['rows'][0]['freshness']['business_lag_days'],6.25);self.assertFalse(d['stale'])
    def test_required_counts_and_issue_scope_match_export(self):
        rec=self.record('departments',dict(id='D02',name=None,owner=None));self.run_scan();d=self.client.get('/api/data-health?dataset=departments&rule=required').json();self.assertEqual(d['summary']['affected_rows'],1);self.assertEqual(d['summary']['issues'],2);self.assertEqual(d['summary']['required_cells'],6);self.assertEqual(d['summary']['missing_required'],2)
        rows=list(csv.reader(io.StringIO(self.client.get('/api/data-health/export?dataset=departments&rule=required').content.decode('utf-8-sig'))));self.assertEqual(len(rows),5);self.assertEqual({r[1] for r in rows[3:]},{'D02'});self.assertEqual(self.client.get('/api/data-health/record/'+str(rec.pk)).status_code,200)
    def test_record_inspection_warns_after_content_changes(self):
        r=self.record('departments',dict(id='D02',name=None,owner='主管'));self.run_scan();r.values['name']='已补';r.record_hash=fingerprint(r.values);r.save();d=self.client.get('/api/data-health/record/'+str(r.pk)).json();self.assertTrue(d['changed_since_scan'])
    def test_import_queue_omits_superseded_but_keeps_staged_failed(self):
        ImportBatch.objects.create(filename='old.xlsx',file_hash='old',file_path='',status='superseded');ImportBatch.objects.create(filename='failed.xlsx',file_hash='failed',file_path='',status='failed');d=self.client.get('/api/data-health/imports').json();self.assertEqual(len(d['rows']),2);self.assertEqual({x['status'] for x in d['rows']},{'committed','failed'})
    def test_permissions_and_csrf(self):
        self.assertEqual(Client().get('/api/data-health').status_code,401);c=Client(enforce_csrf_checks=True);c.force_login(self.admin);self.assertEqual(c.post('/api/data-health/run',json.dumps({'request_id':str(uuid.uuid4())}),content_type='application/json').status_code,403);self.client.force_login(self.quality);self.assertEqual(self.post('/api/data-health/test_sessions/policy',self.policy()).status_code,403)
    def test_scan_audit_failure_rolls_back(self):
        with patch('app.data_health.AuditEvent.objects.create',side_effect=RuntimeError('audit')):
            with self.assertRaises(RuntimeError):self.run_scan()
        self.assertFalse(DataQualityScan.objects.exists())
    def test_policy_audit_failure_rolls_back(self):
        with patch('app.data_health_views.AuditEvent.objects.create',side_effect=RuntimeError('audit')):
            with self.assertRaises(RuntimeError):self.post('/api/data-health/test_sessions/policy',self.policy())
        self.assertFalse(DataMonitorPolicy.objects.exists())
    def test_csv_formula_in_key_safe(self):
        self.record('departments',dict(id='=1+1',name=None,owner='模拟'));self.run_scan();text=self.client.get('/api/data-health/export').content.decode('utf-8-sig');self.assertIn("'=1+1",text)
    def test_new_unchecked_field_is_not_silently_counted_as_valid(self):
        self.run_scan();schema=copy.deepcopy(h.SCHEMAS['departments']);schema['fields'].append(dict(name='new_field',label='新字段',type='str',required=True,reference=None))
        with patch.dict(h.SCHEMAS,{'departments':schema}):
            d=self.client.get('/api/data-health/departments').json();self.assertIn('new_field',d['row']['not_checked_fields']);self.assertEqual(d['row']['required_cells'],3)

    def test_table_export_scope_and_policy_version(self):
        self.run_scan();response=self.client.get('/api/data-health/export?kind=tables&dataset=departments');self.assertEqual(response.status_code,200);rows=list(csv.reader(io.StringIO(response.content.decode('utf-8-sig'))));self.assertEqual(len(rows),4);self.assertEqual(rows[3][0],'departments');self.assertEqual(rows[3][3],'1');self.assertEqual(rows[3][-1],'0')
