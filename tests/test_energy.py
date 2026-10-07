import copy,csv,io,json
from unittest.mock import patch
from django.test import SimpleTestCase,Client
from django.contrib.auth.models import User,Group
from tests.test_platform import PlatformCase
from app import energy_board as e,analytics
from app.models import Record,IssueDisposition

def fixture():
    d={k:[] for k in e.TABLES}
    d['energy']=[dict(id='R1',meter='EM1',workshop='装配车间',started='2026-09-21T00:00:00',ended='2026-09-22T00:00:00',kwh=240,tariff_cents=50,measurement='合成分表'),dict(id='R2',meter='EM2',workshop='仓储',started='2026-09-21T00:00:00',ended='2026-09-22T00:00:00',kwh=120,tariff_cents=60,measurement='合成分表')]
    d['units']=[dict(id='SN1',work_order_id='W1',product_id='P1',assembly_at='2026-09-21T08:00:00')]
    d['equipment']=[dict(id='EQ1',workshop='装配车间',process='装配')]
    d['operations']=[dict(id='OP1',object_type='整机',object_id='SN1',process='装配',equipment_id='EQ1',work_order_id='W1',started='2026-09-21T07:00:00',finished='2026-09-21T08:00:00',status='完成')]
    d['employees']=[dict(id='E1',name='模拟员工',hourly_cents=998877)]
    d['ehs']=[dict(id='AH1',workshop='装配车间',kind='现场整理',description='待复核的模拟事项',found='2026-09-20',due='2026-09-25',closed=None,status='整改中',owner_id='E1'),dict(id='AH2',workshop='仓储',kind='现场整理',description='已复核的模拟事项',found='2026-09-20',due='2026-09-25',closed='2026-09-24',status='已复核',owner_id='E1')]
    return d

class EnergyCalculations(SimpleTestCase):
    def setUp(self):self.d=fixture()
    def board(self,cutoff=None,**q):return e.EnergyBoard(self.d,e.filters(q),cutoff)
    def test_total_daily_hourly_and_tariff_conserve(self):
        d=self.board();s=d.summary(d.selected());b=d.breakdown(d.selected());self.assertEqual(s['kwh'],360);self.assertEqual(s['coverage_pct'],100);self.assertEqual(s['cost_cents'],19200)
        self.assertEqual(sum(x['kwh'] for x in b['hourly']),360);self.assertEqual(sum(x['kwh'] for x in b['daily']),360);self.assertEqual(b['assembly'][0]['kwh_per_assembly'],240)
        self.assertEqual(sum(x['kwh'] for x in d.meters['EM1']['tariffs']),240)
    def test_cross_midnight_splits_by_duration(self):
        self.d['energy']=[{**self.d['energy'][0],'started':'2026-09-20T23:00:00','ended':'2026-09-21T01:00:00','kwh':80}]
        d=self.board(**{'from':'2026-09-21','to':'2026-09-21'});r=d.selected()[0];self.assertEqual(r['kwh'],40);self.assertEqual(r['cost_cents'],2000);self.assertEqual(r['covered_hours'],1);self.assertFalse(r['complete']);self.assertIsNone(d.breakdown(d.selected())['assembly'][0]['kwh_per_assembly'])
    def test_cutoff_clips_future_part_without_future_unit(self):
        d=self.board(cutoff='2026-09-21T06:00:00');self.assertEqual(d.summary(d.selected())['kwh'],90);self.assertEqual(d.summary(d.selected())['coverage_pct'],100);self.assertEqual(d.breakdown(d.selected())['assembly'],[])
    def test_overlap_blocks_entire_meter_even_valid_remainder(self):
        self.d['energy'].append({**self.d['energy'][0],'id':'OVER','started':'2026-09-21T10:00:00','ended':'2026-09-21T11:00:00'})
        d=self.board();self.assertIsNone(d.meters['EM1']['row']['kwh']);self.assertIn('attention',d.meters['EM1']['row']['flags']);self.assertEqual(d.summary(d.selected())['kwh'],120);self.assertEqual(d.meters['EM1']['row']['covered_hours'],24)
    def test_adjacent_intervals_are_not_overlapping(self):
        self.d['energy'][0]['ended']='2026-09-21T12:00:00';self.d['energy'].append({**self.d['energy'][0],'id':'NEXT','started':'2026-09-21T12:00:00','ended':'2026-09-22T00:00:00'})
        r=self.board().meters['EM1']['row'];self.assertTrue(r['complete']);self.assertEqual(r['kwh'],480)
    def test_bad_energy_and_times_show_unknown(self):
        for field,val in [('kwh',-1),('kwh',None),('kwh','NaN'),('kwh',True),('ended','2026-09-20T00:00:00'),('started','nonsense'),('started','2026-09-21T00:00:00+08:00')]:
            self.d=fixture();self.d['energy'][0][field]=val
            with self.subTest(field=field,value=val):self.assertIsNone(self.board().meters['EM1']['row']['kwh'])
    def test_bad_tariff_only_blocks_money(self):
        self.d['energy'][0]['tariff_cents']=-1;d=self.board();r=d.meters['EM1']['row'];self.assertEqual(r['kwh'],240);self.assertIsNone(r['cost_cents']);self.assertTrue(r['cost_issues']);self.assertIsNone(d.summary(d.selected())['cost_cents'])
    def test_meter_mapping_conflict_blocks(self):
        self.d['energy'].append({**self.d['energy'][0],'id':'SHIFT','workshop':'别处','started':'2026-09-22T00:00:00','ended':'2026-09-23T00:00:00'})
        self.assertIsNone(self.board().meters['EM1']['row']['kwh'])
    def test_missing_days_and_zero_are_different(self):
        self.d['energy'][0]['kwh']=0;d=self.board(**{'from':'2026-09-21','to':'2026-09-23','meter':'EM1'});b=d.breakdown(d.selected());self.assertEqual([x['kwh'] for x in b['daily']],[0,None,None]);self.assertAlmostEqual(d.selected()[0]['coverage_pct'],100/3)
        self.assertEqual(b['assembly'][0]['kwh_per_assembly'],0)
    def test_partial_meter_selection_prevents_reference_ratio(self):
        self.d['energy'].append({**self.d['energy'][0],'id':'R3','meter':'EM3'})
        d=self.board(meter='EM1');self.assertIsNone(d.breakdown(d.selected())['assembly'][0]['kwh_per_assembly'])
    def test_no_sns_or_other_workshop_has_no_ratio(self):
        d=self.board(workshop='仓储');self.assertEqual(d.breakdown(d.selected())['assembly'],[])
        self.d['units']=[];d=self.board();self.assertEqual(d.breakdown(d.selected())['assembly'],[])
    def test_bad_sn_link_pauses_ratio_and_retains_evidence(self):
        self.d['units'].append({**self.d['units'][0],'id':'SN2'})
        d=self.board();self.assertIsNone(d.breakdown(d.selected())['assembly'][0]['kwh_per_assembly']);obj=d.detail('assembly','2026-09-21');self.assertIn({'dataset':'units','key':'SN2'},obj['sources'])
    def test_duplicate_or_wrong_order_assembly_link_not_assumed(self):
        for mode in ['duplicate','wrongorder','wrongtime']:
            self.d=fixture()
            if mode=='duplicate':self.d['operations'].append({**self.d['operations'][0],'id':'OP2'})
            if mode=='wrongorder':self.d['operations'][0]['work_order_id']='W2'
            if mode=='wrongtime':self.d['operations'][0]['finished']='2026-09-21T09:00:00'
            d=self.board();self.assertTrue(d.assembly_issues['2026-09-21']);self.assertEqual(d.breakdown(d.selected())['assembly'],[])
    def test_assembly_sources_exclude_adjacent_day_reading(self):
        self.d['energy'].append({**self.d['energy'][0],'id':'PREV','started':'2026-09-20T00:00:00','ended':'2026-09-21T00:00:00'})
        source=self.board().detail('assembly','2026-09-21')['sources'];self.assertNotIn({'dataset':'energy','key':'PREV'},source);self.assertIn({'dataset':'energy','key':'R1'},source);self.assertEqual(len(source),len({(x['dataset'],x['key']) for x in source}))
    def test_scope_intersection_and_bad_filters(self):
        for q in [dict(workshop='NONE'),dict(meter='NONE'),dict(q='NONE'),dict(workshop='仓储',meter='EM1')]:self.assertEqual(self.board(**q).selected(),[])
        for q in [dict(tab='bad'),dict(tab='ehs',meter='EM1'),dict(stage='bad'),{'from':'2026-10-02'},{'from':'2020-01-01'},{'from':'2026-09-22','to':'2026-09-21'},dict(customer='X')]:
            with self.assertRaises(ValueError):e.filters(q)
    def test_ehs_cohort_status_and_elapsed(self):
        d=self.board(tab='ehs');s=d.summary(d.selected());self.assertEqual((s['objects'],s['open'],s['overdue'],s['closed']),(2,1,1,1));self.assertEqual(s['closed_days'],4);self.assertEqual(d.cases['AH1']['overdue_days'],6)
        d=self.board(tab='ehs',**{'from':'2026-09-21'});self.assertEqual(d.selected(),[])
    def test_today_due_not_overdue_future_close_not_closed(self):
        self.d['ehs'][0].update(due='2026-10-01');self.d['ehs'][1]['closed']='2026-10-02';d=self.board(tab='ehs');self.assertIn('today',d.cases['AH1']['flags']);self.assertNotIn('overdue',d.cases['AH1']['flags']);self.assertIn('open',d.cases['AH2']['flags']);self.assertIsNone(d.cases['AH2']['closed_as_of'])
    def test_bad_ehs_dates_owner_state_pause_derived_status(self):
        for change in [dict(due='bad'),dict(due='2026-09-19'),dict(closed='2026-09-18'),dict(status='已复核'),dict(owner_id='MISSING'),dict(status='unknown'),dict(closed='2026-09-23')]:
            self.d=fixture();self.d['ehs'][0].update(change);r=self.board(tab='ehs').cases['AH1'];self.assertIn('attention',r['flags']);self.assertIsNone(r['open_days'])
    def test_late_close_separate_from_open_overdue(self):
        self.d['ehs'][1]['closed']='2026-09-27';r=self.board(tab='ehs').cases['AH2'];self.assertIn('late',r['flags']);self.assertNotIn('overdue',r['flags']);self.assertEqual(r['late_close_days'],2)
    def test_nonfinancial_safe_recursive(self):
        d=self.board();raw=d.detail('meter','EM1');public=e.safe(raw,False);self.assertNotIn('cents',json.dumps(public));self.assertNotIn('tariffs',public);self.assertIn('kwh',public['row'])

class EnergyAPI(PlatformCase):
    def setUp(self):
        super().setUp()
        for ds,rows in fixture().items():
            for r in rows:self.record(ds,r)
        self.client.force_login(self.admin)
    def payload(self):return {'status':'待现场核查','owner':'演练负责人','due_date':'2026-10-05','note':'仅演练核对，不批准现场关闭','version':0,'data_revision':list(analytics.revision())}
    def test_authenticated_board_sources_money_permission(self):
        for user in [self.admin,self.quality]:
            self.client.force_login(user)
            for url in ['/api/energy','/api/energy/meter/EM1','/api/energy/assembly/2026-09-21','/api/energy/meter/EM1/evidence','/api/energy/export','/api/energy/ehs/AH1?tab=ehs']:
                r=self.client.get(url);self.assertEqual(r.status_code,200);self.assertEqual(r.headers['Cache-Control'],'no-store')
                if user==self.quality:self.assertNotIn('cents',r.content.decode());self.assertNotIn('按记录电价估算分',r.content.decode())
        self.assertEqual(Client().get('/api/energy').status_code,401)
    def test_list_stage_preserves_summary_and_same_scope_export(self):
        d=self.client.get('/api/energy?tab=ehs&stage=overdue').json();self.assertEqual(d['total'],1);self.assertEqual(d['summary']['objects'],2)
        data=list(csv.reader(io.StringIO(self.client.get('/api/energy/export?tab=ehs&stage=overdue').content.decode('utf-8-sig'))));self.assertEqual(len(data),4);self.assertEqual(data[3][0],'AH1')
    def test_followup_optimistic_versions_and_facts_unchanged(self):
        before=list(Record.objects.values_list('values',flat=True));url='/api/energy/ehs/AH1/follow-up?tab=ehs';p=self.payload();self.assertEqual(self.post(url,p).status_code,200);self.assertEqual(self.post(url,p).status_code,409)
        p.update(version=1,data_revision=[0,'stale']);self.assertEqual(self.post(url,p).status_code,409);self.assertEqual(before,list(Record.objects.values_list('values',flat=True)));self.assertEqual(len(self.client.get('/api/energy/ehs/AH1/history?tab=ehs').json()['rows']),1)
    def test_viewer_and_finance_cannot_follow_and_csrf(self):
        for role in ['viewer','finance']:
            u=User.objects.create_user(role);u.groups.add(Group.objects.create(name=role));self.client.force_login(u);self.assertEqual(self.client.get('/api/energy').status_code,200);self.assertEqual(self.post('/api/energy/meter/EM1/follow-up',self.payload()).status_code,403)
        c=Client(enforce_csrf_checks=True);c.force_login(self.admin);self.assertEqual(c.post('/api/energy/meter/EM1/follow-up',json.dumps(self.payload()),content_type='application/json').status_code,403)
    def test_invalid_fields_wrong_scope_or_unknown_object(self):
        for change in [dict(status='批准整改关闭'),dict(version=True),dict(note='短'),dict(due_date='bad')]:self.assertEqual(self.post('/api/energy/meter/EM1/follow-up',{**self.payload(),**change}).status_code,400)
        for url in ['/api/energy/meter/MISSING','/api/energy/meter/EM1?workshop=仓储','/api/energy/ehs/AH1']:
            self.assertEqual(self.client.get(url).status_code,404)
        self.assertEqual(self.post('/api/energy/assembly/2026-09-21/follow-up',self.payload()).status_code,403)
    def test_audit_error_rolls_back_note(self):
        with patch('app.energy_views.AuditEvent.objects.create',side_effect=RuntimeError('audit unavailable')):
            with self.assertRaises(RuntimeError):self.post('/api/energy/meter/EM1/follow-up',self.payload())
        self.assertFalse(IssueDisposition.objects.filter(key='energy:meter:EM1').exists())
    def test_csv_formula_escape_and_source_permission(self):
        r=Record.objects.get(dataset='ehs',business_key='AH1');r.values['description']='=1+1';r.save();self.assertIn("'=1+1",self.client.get('/api/energy/export?tab=ehs').content.decode('utf-8-sig'))
        self.client.force_login(self.quality);self.assertFalse(self.client.get('/api/energy/meter/EM1/evidence').json()['can_download_original'])
