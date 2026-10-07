import csv, io, json
from copy import deepcopy
from unittest.mock import patch
from django.test import SimpleTestCase, Client
from django.contrib.auth.models import Group, User
from app import assets, analytics
from app.schema import SCHEMAS
from app.models import Record, IssueDisposition, AuditEvent
from tests.test_platform import PlatformCase


def fixture():
    d={k:[] for k in SCHEMAS}
    d['equipment']=[dict(id='E1',name='绕线机（模拟）',workshop='绕线',process='绕线',status='运行'),dict(id='E2',name='装配机（模拟）',workshop='装配',process='装配',status='运行')]
    d['production_resources']=[dict(id='R1',equipment_id='E1',effective='2026-01-01'),dict(id='R2',equipment_id='E1',effective='2026-01-01')]
    d['resource_calendars']=[dict(id='C1',resource_id='R1',started='2026-09-21T08:00:00',finished='2026-09-21T17:00:00'),dict(id='C2',resource_id='R2',started='2026-09-21T08:00:00',finished='2026-09-21T17:00:00')]
    d['downtime']=[dict(id='D1',equipment_id='E1',started='2026-09-21T09:00:00',finished='2026-09-21T11:00:00',reason='故障',work_order_id=None),dict(id='D2',equipment_id='E1',started='2026-09-21T10:00:00',finished='2026-09-21T12:00:00',reason='换型',work_order_id=None)]
    d['maintenance']=[dict(id='W1',equipment_id='E1',kind='故障维修',reported='2026-09-21T08:00:00',started='2026-09-21T09:00:00',finished='2026-09-21T12:00:00',status='已完成',failure='轴承',cost_cents=999),dict(id='W2',equipment_id='E1',kind='故障维修',reported='2026-09-22T08:00:00',started=None,finished=None,status='待备件',failure='传感器',cost_cents=888)]
    d['tools']=[dict(id='T1',name='量规',equipment_id='E1',kind='计量器具',calibrated='2026-03-01',next_due='2026-09-30',uses=100,maintenance_limit=100,status='待校准')]
    return d


class AssetCalculationTests(SimpleTestCase):
    def setUp(self):self.d=fixture()
    def data(self,**q):return assets.AssetData(self.d,assets.filters(q))
    def test_equipment_union_and_parallel_resource_calendar_not_summed(self):
        r=self.data().index['E1'];self.assertEqual(r['stop_hours'],3);self.assertEqual(r['scheduled_hours'],9);self.assertEqual(r['scheduled_stop_hours'],3);self.assertAlmostEqual(r['stop_ratio'],100/3);self.assertEqual(r['overlap_minutes'],60)
    def test_reason_segments_are_exclusive_and_reconcile(self):
        d=self.data();rr=assets.breakdown(d,d.rows)['reasons'];self.assertEqual({r['label']:r['hours'] for r in rr},{'故障':1,'换型':1,'多原因重叠待核对':1});self.assertEqual(sum(r['hours'] for r in rr),3)
    def test_same_reason_overlap_and_touching_endpoints(self):
        self.d['downtime'][1]['reason']='故障';r=self.data().index['E1'];self.assertEqual(r['_reasons'],{'故障':3})
        self.d['downtime'][1]['started']='2026-09-21T11:00:00';r=self.data().index['E1'];self.assertEqual(r['overlap_minutes'],0)
    def test_cross_midnight_clipped_and_daily_reconciles(self):
        self.d['downtime']=[dict(self.d['downtime'][0],started='2026-09-20T23:00:00',finished='2026-09-22T01:00:00')]
        d=self.data(**{'from':'2026-09-21','to':'2026-09-22'});b=assets.breakdown(d,d.rows);self.assertEqual([r['hours'] for r in b['daily']],[24,1]);self.assertEqual(d.index['E1']['stop_hours'],25)
    def test_asof_clips_future_end_and_excludes_future_starts(self):
        self.d['downtime']=[dict(self.d['downtime'][0],started='2026-10-01T17:00:00',finished='2026-10-01T20:00:00'),dict(self.d['downtime'][1],started='2026-10-02T08:00:00',finished='2026-10-02T09:00:00')]
        self.assertEqual(self.data().index['E1']['stop_hours'],1)
    def test_no_calendar_is_unknown_and_weighted_ratio_uses_paired_devices(self):
        self.d['downtime'].append(dict(self.d['downtime'][0],id='D3',equipment_id='E2'))
        d=self.data();s=assets.summary(d.rows,'equipment');self.assertEqual(s['paired_equipment'],1);self.assertEqual(s['stop_hours'],5);self.assertIsNone(d.index['E2']['scheduled_hours']);self.assertAlmostEqual(s['stop_ratio'],100/3)
    def test_unequal_denominators_ratio_of_sums(self):
        self.d['production_resources'].append(dict(id='R3',equipment_id='E2',effective='2026-01-01'))
        self.d['resource_calendars'].append(dict(id='C3',resource_id='R3',started='2026-09-21T08:00:00',finished='2026-09-21T09:00:00'))
        self.d['downtime'].append(dict(self.d['downtime'][0],id='D3',equipment_id='E2',started='2026-09-21T08:00:00',finished='2026-09-21T09:00:00'))
        self.assertEqual(assets.summary(self.data().rows,'equipment')['stop_ratio'],40)
    def test_invalid_stop_pauses_total_but_source_retained(self):
        self.d['downtime'][0]['finished']='2026-09-21T08:00:00';d=self.data();r=d.index['E1'];self.assertIsNone(r['stop_hours']);self.assertIsNone(r['stop_ratio']);self.assertIsNone(assets.summary(d.rows,'equipment')['stop_hours']);self.assertTrue(all(x['hours'] is None for x in assets.breakdown(d,d.rows)['daily']));self.assertIn({'dataset':'downtime','key':'D1'},d.detail('equipment','E1')['sources'])
    def test_invalid_or_pre_effective_calendar_pauses_ratio(self):
        for change in ['reverse','effective']:
            self.d=fixture()
            if change=='reverse':self.d['resource_calendars'][0]['finished']='2026-09-21T07:00:00'
            else:self.d['production_resources'][0]['effective']='2026-09-22'
            self.assertIsNone(self.data().index['E1']['stop_ratio'])
    def test_orphan_events_and_resources_are_explicit(self):
        self.d['downtime'][0]['equipment_id']='unknown';self.d['resource_calendars'][0]['resource_id']='missing';d=self.data();self.assertEqual(len(d.global_issues),2);self.assertEqual(d.index['E1']['stop_hours'],2)
    def test_repairs_completed_and_open_samples_separate(self):
        rows=self.data(tab='maintenance').selected();s=assets.summary(rows,'maintenance');self.assertEqual(s['completed_samples'],1);self.assertEqual(s['mean_elapsed_hours'],4);self.assertEqual(s['mean_response_hours'],1);self.assertEqual(s['open'],1);self.assertEqual(s['max_open_hours'],226)
    def test_repair_reported_cohort_not_finish_cohort(self):
        d=self.data(tab='maintenance',**{'from':'2026-09-22','to':'2026-09-22'});self.assertEqual([r['id'] for r in d.selected()],['W2']);self.assertEqual(d.index['E1']['open_repairs'],1)
    def test_future_repair_not_completed_and_future_reports_excluded(self):
        self.d['maintenance'][0].update(finished='2026-10-02T12:00:00',status='维修中')
        self.d['maintenance'].append(dict(self.d['maintenance'][0],id='WF',reported='2026-10-02T08:00:00',started='2026-10-02T09:00:00'))
        d=self.data();self.assertEqual(d.maintenance['W1']['calculated_state'],'未完成');self.assertIsNone(d.maintenance['W1']['elapsed_hours']);self.assertNotIn('WF',d.maintenance)
    def test_reverse_repair_and_status_conflict_are_not_valid_samples(self):
        for change in [dict(started='2026-09-21T07:00:00'),dict(started=None),dict(status='待备件')]:
            self.d=fixture();self.d['maintenance'][0].update(change);r=self.data().maintenance['W1'];self.assertIn('attention',r['flags']);self.assertIsNone(r['elapsed_hours'])
    def test_tool_date_boundaries_and_usage_equality(self):
        for due,flag in [('2026-09-30','overdue'),('2026-10-01','today'),('2026-10-31','soon'),('2026-11-01',None)]:
            self.d['tools'][0]['next_due']=due;r=self.data().tools['T1'];self.assertIn('usage',r['flags']);self.assertEqual([x for x in r['flags'] if x in ['overdue','today','soon']],[flag] if flag else [])
    def test_tool_zero_threshold_and_invalid_dates(self):
        self.d['tools'][0]['maintenance_limit']=0;r=self.data().tools['T1'];self.assertIsNone(r['usage_ratio']);self.assertNotIn('usage',r['flags'])
        self.d['tools'][0]['calibrated']='2026-11-01';r=self.data().tools['T1'];self.assertIn('attention',r['flags']);self.assertIsNone(r['days_to_due']);self.assertNotIn('overdue',r['flags'])
    def test_negative_uses_not_in_usage_ratio(self):
        self.d['tools'][0]['uses']=-1;r=self.data().tools['T1'];self.assertIsNone(r['usage_ratio']);self.assertIn('attention',r['flags'])
    def test_filters_reject_unsupported_time_and_empty_scope_stays_empty(self):
        for q in [{'tab':'tool','from':'2026-09-21'},{'to':'2026-10-02'},{'from':'2026-09-22','to':'2026-09-21'},{'tab':'oops'},{'stage':'unknown'},{'family':'YE4'}]:
            with self.assertRaises(ValueError):assets.filters(q)
        self.assertEqual(self.data(q='absent').selected(),[]);self.assertEqual(self.data(equipment_id='NONE').selected(),[]);self.assertIsNone(assets.summary([],'equipment')['stop_ratio'])
    def test_empty_cohort_does_not_draw_zero_time_series(self):
        d=self.data(q='absent');self.assertEqual(assets.breakdown(d,d.selected()),{'reasons':[],'daily':[]})
    def test_detail_sources_deduplicated_and_financial_fields_absent(self):
        d=self.data().detail('equipment','E1');self.assertEqual(len(d['sources']),len({(x['dataset'],x['key']) for x in d['sources']}));self.assertNotIn('cents',json.dumps(d));self.assertIn({'dataset':'production_resources','key':'R2'},d['sources'])


class AssetApiTests(PlatformCase):
    def setUp(self):
        super().setUp();self.d=fixture()
        for ds,rows in self.d.items():
            for row in rows:self.record(ds,row)
        analytics._tables.cache_clear();self.addCleanup(analytics._tables.cache_clear);self.client.force_login(self.quality)
    def payload(self):return dict(status='待备件协调',owner='模拟设备岗位',due_date='2026-10-06',note='核对维修台账并确认备件需求',version=0,data_revision=list(analytics.revision()))
    def test_summary_stage_filter_and_export_same_list(self):
        r=self.client.get('/api/assets?stage=open').json();self.assertEqual(r['summary']['objects'],2);self.assertEqual(r['total'],1)
        out=list(csv.reader(io.StringIO(self.client.get('/api/assets/export?stage=open&page=9').content.decode('utf-8-sig'))));self.assertEqual(len(out)-3,1);self.assertEqual(out[3][0],'E1')
    def test_role_auth_detail_and_sources_exclude_costs(self):
        for url in ['/api/assets','/api/assets?tab=maintenance','/api/assets/maintenance/W1','/api/assets/equipment/E1']:
            r=self.client.get(url);self.assertEqual(r.status_code,200);self.assertNotIn('cents',r.content.decode());self.assertEqual(r.headers['Cache-Control'],'no-store')
        self.assertEqual(Client().get('/api/assets').status_code,401);self.assertEqual(self.client.get('/api/assets/tool/MISSING').status_code,404)
        r=self.client.get('/api/assets/equipment/E1/evidence').json();self.assertFalse(r['can_download_original']);self.assertGreater(r['total'],1)
    def test_follow_version_fact_revision_audit_and_no_fact_mutation(self):
        before=list(Record.objects.values_list('values',flat=True));p=self.payload();r=self.post('/api/assets/maintenance/W2/follow-up',p);self.assertEqual(r.status_code,200);self.assertEqual(r.json()['follow_up']['version'],1)
        self.assertEqual(self.post('/api/assets/maintenance/W2/follow-up',p).status_code,409)
        p.update(version=1,data_revision=[0,'stale']);self.assertEqual(self.post('/api/assets/maintenance/W2/follow-up',p).status_code,409)
        self.assertEqual(list(Record.objects.values_list('values',flat=True)),before);self.assertEqual(len(self.client.get('/api/assets/maintenance/W2/history').json()['rows']),1)
    def test_readonly_and_csrf_and_unknown_fields(self):
        viewer=User.objects.create_user('asset-viewer');self.client.force_login(viewer);self.assertEqual(self.post('/api/assets/tool/T1/follow-up',self.payload()).status_code,403)
        self.client.force_login(self.quality);self.assertEqual(self.post('/api/assets/tool/T1/follow-up',{**self.payload(),'cost_cents':3}).status_code,400)
        strict=Client(enforce_csrf_checks=True);strict.force_login(self.quality);self.assertEqual(strict.post('/api/assets/tool/T1/follow-up',json.dumps(self.payload()),content_type='application/json').status_code,403)
    def test_audit_failure_rolls_back_followup(self):
        with patch('app.asset_views.AuditEvent.objects.create',side_effect=RuntimeError('audit fail')):
            with self.assertRaises(RuntimeError):self.post('/api/assets/tool/T1/follow-up',self.payload())
        self.assertFalse(IssueDisposition.objects.filter(key='asset:tool:T1').exists())
    def test_export_formula_guard(self):
        r=Record.objects.get(dataset='tools',business_key='T1');r.values['name']='=DANGEROUS()';r.save();data=list(csv.reader(io.StringIO(self.client.get('/api/assets/export?tab=tool').content.decode('utf-8-sig'))));self.assertEqual(data[3][1],"'=DANGEROUS()")
    def test_stage_restricted_by_tab_and_data_revision_changes(self):
        self.assertEqual(self.client.get('/api/assets?tab=tool&stage=open').status_code,400)
        p=self.payload();r=Record.objects.get(dataset='maintenance',business_key='W2');r.values['failure']='changed';r.save();self.assertEqual(self.post('/api/assets/maintenance/W2/follow-up',p).status_code,409)
