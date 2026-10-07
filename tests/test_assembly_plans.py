import copy,csv,io,json
from django.test import SimpleTestCase,Client
from django.contrib.auth.models import User,Group
from app import assembly_plans as p
from app.models import Record,IssueDisposition
from tests.test_platform import PlatformCase

def fixture():
    data={'products':[dict(id='P',family='F')],'work_orders':[dict(id='W1',product_id='P',planned_qty=4),dict(id='W2',product_id='P',planned_qty=4)],'units':[dict(id='U'+str(i),work_order_id='W1' if i<4 else 'W2',product_id='P',assembly_at='2026-09-20T10:00:00',status='待检') for i in range(1,5)],p.DATASETS[0]:[],p.DATASETS[1]:[],p.DATASETS[2]:[]}
    for v,release,qty in [(1,'2026-09-19T16:00:00',[2,2]),(2,'2026-09-22T08:00:00',[3,1])]:
        data[p.DATASETS[0]].append(dict(id=f'V{v}',series='S',version=v,supersedes_id='V1' if v==2 else None,production_date='2026-09-20',freeze_at='2026-09-19T18:00:00',released=release,status='已发布',owner='模拟计划岗位',line_count=2,reason='首版' if v==1 else '模拟期后调整',basis='合成计划'))
        for i,q in enumerate(qty,1):data[p.DATASETS[1]].append(dict(id=f'L{v}-{i}',version_id=f'V{v}',work_order_id=f'W{i}',product_id='P',qty=q,reason='模拟安排'))
    data[p.DATASETS[2]].append(dict(id='C1',production_date='2026-09-20',through='2026-09-20T23:59:59',confirmed='2026-09-21T08:00:00',data_signature=p.signature(data['units']),status='完整',owner='模拟数据岗位',note='合成资料确认',voided=False))
    return data

class AssemblyPlanTests(SimpleTestCase):
    def setUp(self):self.d=fixture()
    def calc(self,**kwargs):return p.Plans(self.d,**kwargs)
    def stats(self):return p.summary(list(self.calc().rows.values()))
    def test_overproduction_never_offsets_another_order_shortage(self):
        s=self.stats();self.assertEqual((s['observed_qty'],s['baseline_planned'],s['baseline_fulfilled'],s['baseline_rate']),(4,4,3,75));self.assertEqual(s['baseline_short'],1)
    def test_retrospective_plan_never_replaces_frozen_baseline(self):
        d=self.calc().days['2026-09-20'];self.assertEqual(d['baseline']['id'],'V1');self.assertEqual(d['current']['id'],'V2');self.assertTrue(d['current']['after_day']);self.assertEqual(self.stats()['current_rate'],100)
    def test_last_pre_freeze_version_becomes_baseline(self):
        self.d[p.DATASETS[0]][1]['released']='2026-09-19T17:00:00';self.assertEqual(self.calc().days['2026-09-20']['baseline']['id'],'V2')
    def test_future_revision_ignored(self):
        self.d[p.DATASETS[0]][1]['released']='2026-10-02T08:00:00';self.assertEqual(self.stats()['current_rate'],75)
    def test_draft_and_void_versions_not_selected(self):
        for status in ['草稿','作废']:
            self.d[p.DATASETS[0]][1].update(status=status,released=None);self.assertEqual(self.stats()['current_rate'],75)
    def test_no_prefreeze_version_no_invented_baseline(self):
        self.d[p.DATASETS[0]][0]['released']='2026-09-19T20:00:00';s=self.stats();self.assertIsNone(s['baseline_rate']);self.assertEqual(s['current_rate'],100)
    def test_broken_version_chain_and_moved_freeze_stop(self):
        for changes in [{'version':1},{'version':3},{'supersedes_id':None},{'series':'OTHER'},{'freeze_at':'2026-09-19T19:00:00'},{'released':'2026-09-19T15:00:00'},{'status':'unknown'}]:
            self.d=fixture();self.d[p.DATASETS[0]][1].update(changes);s=self.stats();self.assertIsNone(s['baseline_rate']);self.assertIsNone(s['current_rate'])
    def test_freeze_must_be_before_day_and_release_required(self):
        for changes in [{'freeze_at':'bad'},{'freeze_at':'2026-09-20T08:00:00'},{'released':None}]:
            self.d=fixture();self.d[p.DATASETS[0]][0].update(changes);self.assertIsNone(self.stats()['baseline_rate'])
    def test_incomplete_snapshot_not_treated_as_removed_lines(self):
        self.d[p.DATASETS[1]]=[r for r in self.d[p.DATASETS[1]] if r['id']!='L2-2'];s=self.stats();self.assertEqual(s['baseline_rate'],75);self.assertIsNone(s['current_rate'])
    def test_duplicate_order_in_snapshot_rejected(self):
        self.d[p.DATASETS[1]][3]['work_order_id']='W1';self.assertIsNone(self.stats()['current_rate'])
    def test_invalid_quantity_and_workorder_cap(self):
        for q in [True,-1,1.5,'2',None,5]:
            self.d=fixture();self.d[p.DATASETS[1]][2]['qty']=q;self.assertIsNone(self.stats()['current_rate'])
    def test_plan_product_reference_must_match_order(self):
        self.d[p.DATASETS[1]][2]['product_id']='OTHER';self.assertIsNone(self.stats()['current_rate'])
    def test_removed_and_zero_lines_preserved_as_changed(self):
        self.d[p.DATASETS[1]]=[r for r in self.d[p.DATASETS[1]] if r['id']!='L2-2'];self.d[p.DATASETS[0]][1]['line_count']=1;r=self.calc().rows['2026-09-20~W2'];self.assertEqual((r['baseline_qty'],r['current_qty'],r['current_extra']),(2,0,1));self.assertTrue(r['changed'])
    def test_all_zero_plan_no_rate(self):
        for line in self.d[p.DATASETS[1]]:line['qty']=0
        s=self.stats();self.assertIsNone(s['baseline_rate']);self.assertEqual(s['current_extra'],4)
    def test_unplanned_units_separate_from_plan_fulfillment(self):
        self.d['work_orders'].append(dict(id='W3',product_id='P',planned_qty=2));self.d['units'].append(dict(id='U5',product_id='P',work_order_id='W3',assembly_at='2026-09-20T12:00:00'));self.d[p.DATASETS[2]][0]['data_signature']=p.signature(self.d['units']);s=self.stats();self.assertEqual(s['current_rate'],100);self.assertEqual(s['current_extra'],1)
    def test_actual_zero_requires_confirmation_of_empty_set(self):
        self.d['units']=[];self.d[p.DATASETS[2]][0]['data_signature']=p.signature([]);self.assertEqual(self.stats()['baseline_rate'],0);self.d[p.DATASETS[2]]=[];self.assertIsNone(self.stats()['baseline_rate'])
    def test_changed_unit_even_same_count_invalidates_confirmation(self):
        self.d['units'][0]['status']='已发货';self.assertIsNone(self.stats()['baseline_rate']);self.assertEqual(self.stats()['observed_qty'],4)
    def test_incomplete_future_void_stale_checks(self):
        for changes in [{'status':'待补'},{'voided':True},{'voided':'False'},{'confirmed':'2026-10-02T08:00:00'},{'through':'2026-09-20T12:00:00'},{'data_signature':'0'*64},{'owner':''},{'note':''},{'confirmed':'2026-09-20T12:00:00'}]:
            self.d=fixture();self.d[p.DATASETS[2]][0].update(changes);self.assertIsNone(self.stats()['baseline_rate'])
    def test_tied_checks_and_later_retraction(self):
        self.d[p.DATASETS[2]].append({**self.d[p.DATASETS[2]][0],'id':'C2'});self.assertIsNone(self.stats()['baseline_rate']);self.d[p.DATASETS[2]][1].update(confirmed='2026-09-22T08:00:00',status='待补');self.assertIsNone(self.stats()['baseline_rate'])
    def test_current_day_and_future_do_not_get_final_rate(self):
        d=self.calc(as_of='2026-09-20T18:00:00');self.assertEqual(d.days['2026-09-20']['state'],'in_progress');self.assertIsNone(p.summary(list(d.rows.values()))['baseline_rate'])
        d=self.calc(as_of='2026-09-19T20:00:00');self.assertTrue(all(r['observed_qty'] is None for r in d.rows.values()));self.assertIsNone(p.summary(list(d.rows.values()))['observed_qty'])
        self.assertEqual(p.summary(list(d.rows.values()))['baseline_scheduled'],4)
    def test_future_intraday_unit_excluded(self):
        self.d['units'][0]['assembly_at']='2026-09-20T20:00:00';d=self.calc(as_of='2026-09-20T18:00:00');self.assertEqual(p.summary(list(d.rows.values()))['observed_qty'],3)
    def test_invalid_sn_relationship_or_unknown_date_blocks_actuals(self):
        for changes in [{'work_order_id':'MISSING'},{'product_id':'OTHER'},{'assembly_at':'bad'},{'work_order_id':None}]:
            self.d=fixture();self.d['units'][0].update(changes);self.d[p.DATASETS[2]][0]['data_signature']=p.signature(self.d['units']);self.assertIsNone(self.stats()['baseline_rate'])
    def test_missing_plan_not_zero_plan(self):
        self.d[p.DATASETS[0]]=[];self.d[p.DATASETS[1]]=[];s=self.stats();self.assertEqual(s['observed_qty'],4);self.assertIsNone(s['baseline_rate'])
    def test_cross_day_overplanning_flagged(self):
        h={**self.d[p.DATASETS[0]][0],'id':'NEXT','series':'NEXT','production_date':'2026-09-21','freeze_at':'2026-09-20T18:00:00','released':'2026-09-20T16:00:00','line_count':1};self.d[p.DATASETS[0]].append(h);self.d[p.DATASETS[1]].append(dict(id='NEXT-L1',version_id='NEXT',work_order_id='W1',product_id='P',qty=3,reason='模拟安排'));d=self.calc();self.assertFalse(d.rows['2026-09-20~W1']['current_eligible']);self.assertTrue(any('跨日累计' in x for x in d.days['2026-09-21']['issues']))
    def test_filter_summary_and_source_membership(self):
        d=self.calc();rows=d.selected(p.params({'q':'W2'}));self.assertEqual(len(rows),1);self.assertEqual(p.summary(rows)['baseline_rate'],50)
        r=rows[0];refs={(x['dataset'],x['key']) for x in r['sources']};self.assertIn(('units','U4'),refs);self.assertNotIn(('units','U1'),refs);self.assertIn((p.DATASETS[1],'L1-2'),refs);self.assertEqual(len(d.selected(p.params({'attention':'short'}))),1)
    def test_params_validation_and_empty(self):
        for f in [{'from':'bad'},{'attention':'unknown'},{'from':'2026-09-22','to':'2026-09-20'}]:
            with self.assertRaises(ValueError):p.params(f)
        self.assertIsNone(p.summary([])['current_rate']);self.assertEqual(self.calc().selected(p.params({'family':'OTHER'})),[])
    def test_inputs_unchanged(self):
        before=copy.deepcopy(self.d);self.calc();self.assertEqual(self.d,before)

class AssemblyPlanApiTests(PlatformCase):
    def setUp(self):
        super().setUp();self.d=fixture()
        for ds,rows in self.d.items():
            for r in rows:self.record(ds,r)
        self.client.force_login(self.admin)
    def test_authenticated_reads_and_missing_object(self):
        self.client.force_login(self.quality);self.assertEqual(self.client.get('/api/assembly-plans').status_code,200);d=self.client.get('/api/assembly-plans/rows/2026-09-20~W1').json();self.assertFalse(d['can_follow']);self.assertEqual(self.client.get('/api/assembly-plans/rows/NO').status_code,400);self.client.logout();self.assertEqual(self.client.get('/api/assembly-plans').status_code,401)
    def test_board_and_day_versions(self):
        b=self.client.get('/api/assembly-plans').json();self.assertEqual(b['summary']['baseline_rate'],75);d=self.client.get('/api/assembly-plans/dates/2026-09-20').json();self.assertEqual(d['day']['baseline']['id'],'V1');self.assertEqual(d['day']['current']['id'],'V2')
    def test_same_scope_csv_and_full_export_beyond_page(self):
        for i in range(3,31):
            self.record('work_orders',dict(id=f'W{i}',product_id='P',planned_qty=1));self.record('units',dict(id=f'U{i+2}',product_id='P',work_order_id=f'W{i}',assembly_at='2026-09-20T12:00:00'))
        d=self.client.get('/api/assembly-plans').json();self.assertEqual(len(d['rows']),25);self.assertEqual(d['total'],30);self.assertEqual(len(self.client.get('/api/assembly-plans?page=2').json()['rows']),5)
        export=self.client.get('/api/assembly-plans/export',{'receipt':d['receipt']});rows=list(csv.reader(io.StringIO(export.content.decode('utf-8-sig'))));self.assertEqual(len(rows)-5,30)
        e=self.client.get('/api/assembly-plans/export',{'receipt':d['receipt'],'q':'W2'});self.assertEqual(len(list(csv.reader(io.StringIO(e.content.decode('utf-8-sig')))))-5,11)
    def test_evidence_and_sn_scope_receipt(self):
        d=self.client.get('/api/assembly-plans').json();base='/api/assembly-plans/rows/2026-09-20~W2';s=self.client.get(base+'/units',{'receipt':d['receipt']}).json();self.assertEqual([x['id'] for x in s['rows']],['U4']);self.assertEqual(self.client.get(base+'/evidence?receipt=old').status_code,409);refs=self.client.get(base+'/evidence',{'receipt':d['receipt']}).json()['rows'];self.assertTrue(any(x['key']=='U4' for x in refs));self.assertFalse(any(x['key']=='U1' for x in refs))
    def test_followup_versions_audit_and_no_fact_edits(self):
        d=self.client.get('/api/assembly-plans').json();payload=dict(version=0,status='计划原因核查中',owner='模拟生产协调岗',due_date='2026-10-06',note='核对期后调整与原计划的差异依据',receipt=d['receipt']);url='/api/assembly-plans/rows/2026-09-20~W2/follow-up';before=list(Record.objects.values_list('values',flat=True));r=self.post(url,payload);self.assertEqual(r.status_code,200);self.assertEqual(r.json()['follow_up']['version'],1);self.assertEqual(self.post(url,payload).status_code,409);self.assertEqual(list(Record.objects.values_list('values',flat=True)),before);self.assertEqual(len(self.client.get(url.replace('/follow-up','/history')).json()['rows']),1)
    def test_role_csrf_and_stale_data(self):
        b=self.client.get('/api/assembly-plans').json();url='/api/assembly-plans/rows/2026-09-20~W2/follow-up';self.client.force_login(self.quality);self.assertEqual(self.post(url,{}).status_code,403);c=Client(enforce_csrf_checks=True);c.force_login(self.admin);self.assertEqual(c.post(url,'{}',content_type='application/json').status_code,403);self.record('units',dict(id='NEW',assembly_at='2026-09-21T08:00:00'));self.assertEqual(self.client.get('/api/assembly-plans/export',{'receipt':b['receipt']}).status_code,409)
