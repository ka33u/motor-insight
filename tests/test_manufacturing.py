import copy,csv,io,json
from unittest.mock import patch
from django.test import SimpleTestCase,Client
from django.contrib.auth.models import User,Group
from tests.test_platform import PlatformCase
from app import manufacturing as m,analytics
from app.models import Record,IssueDisposition

def fixture():
    d={k:[] for k in m.TABLES}
    d['products']=[dict(id='P1',model='演练电机',family='YE3',price_cents=123456)]
    d['employees']=[dict(id='E1',name='模拟工人',hourly_cents=123456)]
    d['work_orders']=[dict(id='W1',product_id='P1',planned_qty=2,planned_start='2026-09-28',planned_end='2026-09-30',status='执行中',route_version='V1'),dict(id='W2',product_id='P1',planned_qty=3,planned_start='2026-09-29',planned_end='2026-09-30',status='未开工',route_version='V1'),dict(id='W3',product_id='P1',planned_qty=1,planned_start='2026-10-01',planned_end='2026-09-30',status='未开工',route_version='V1')]
    d['batches']=[dict(id='B1',work_order_id='W1',kind='定子',qty=2,created='2026-09-29T08:00:00',status='装配领用',container='BOX1'),dict(id='K1',work_order_id='W1',kind='装配件包',qty=2,created='2026-09-29T08:00:00',status='装配领用',container='BOX2')]
    d['units']=[dict(id='SN1',work_order_id='W1',product_id='P1',assembly_at='2026-09-29T08:46:00',stator_batch='B1',assembly_batch='K1')]
    d['routes']=[dict(id='R1',product_id='P1',version='V1',sequence=10,branch='定子',process='冲片',minutes=10,mandatory=True),dict(id='R2',product_id='P1',version='V1',sequence=20,branch='定子',process='叠压',minutes=15,mandatory=True),dict(id='R3',product_id='P1',version='V1',sequence=30,branch='整机',process='装配',minutes=6,mandatory=True)]
    d['route_dependencies']=[dict(id='D1',product_id='P1',from_route_id='R1',to_route_id='R2',lag_minutes=5),dict(id='D2',product_id='P1',from_route_id='R2',to_route_id='R3',lag_minutes=5)]
    for i,process in enumerate(['冲片','叠压','装配','返修','终检','包装'],1):
        d['equipment'].append(dict(id=f'EQ{i}',process=process));d['production_resources'].append(dict(id=f'RS{i}',process=process,equipment_id=f'EQ{i}'))
    spec=[('OP1','生产批次','B1','冲片',1,'08:00:00','08:10:00',2,0),('OP2','生产批次','B1','叠压',2,'08:15:00','08:30:00',2,0),('OP3','整机','SN1','装配',3,'08:40:00','08:46:00',1,0),('OP4','整机','SN1','返修',4,'08:50:00','09:00:00',1,1),('OP5','整机','SN1','终检',5,'09:05:00','09:08:00',1,0)]
    for key,typ,obj,proc,e,a,b,qty,rw in spec:d['operations'].append(dict(id=key,work_order_id='W1',object_type=typ,object_id=obj,process=proc,equipment_id=f'EQ{e}',resource_id=f'RS{e}',employee_id='E1',started='2026-09-29T'+a,finished='2026-09-29T'+b,input_qty=qty,good_qty=qty,scrap_qty=0,rework_qty=rw,status='完成'))
    return d

class ManufacturingCalculations(SimpleTestCase):
    def setUp(self):self.d=fixture()
    def board(self,cutoff=None,**f):return m.Manufacturing(self.d,m.filters(f),cutoff)
    def test_work_order_grain_not_reported_quantities(self):
        b=self.board();s=b.summary(b.selected());self.assertEqual((s['objects'],s['planned_qty'],s['assembled_qty'],s['assembly_gap']),(3,6,1,5));self.assertEqual(s['no_events'],2)
    def test_bad_plan_dates_keep_quantity_but_suspend_due(self):
        r=self.board().work_orders['W3']['row'];self.assertTrue(r['issues']);self.assertEqual(r['assembly_gap'],1);self.assertNotIn('late_gap',r['flags'])
    def test_due_day_not_late(self):
        self.assertNotIn('late_gap',self.board(cutoff='2026-09-30T23:59:59').work_orders['W1']['row']['flags']);self.assertIn('late_gap',self.board().work_orders['W1']['row']['flags'])
    def test_missing_plan_date_unfiltered_visible_filtered_excluded(self):
        self.d['work_orders'][0]['planned_start']='bad';self.assertEqual(len(self.board().selected()),3);self.assertEqual(len(self.board(**{'from':'2026-09-01'}).selected()),2)
    def test_invalid_planned_qty_and_overassembly_suspend_gap(self):
        for value in [True,0,-1,1.5]:
            self.d=fixture();self.d['work_orders'][0]['planned_qty']=value;self.assertIsNone(self.board().work_orders['W1']['row']['assembly_gap'])
        self.d=fixture();self.d['units'].append({**self.d['units'][0],'id':'SN2'});self.d['work_orders'][0]['planned_qty']=1;self.assertIsNone(self.board().work_orders['W1']['row']['assembly_gap'])
    def test_future_assembly_not_counted(self):
        self.d['units'][0]['assembly_at']='2026-10-02T08:46:00';self.assertEqual(self.board().work_orders['W1']['row']['assembled_qty'],0)
    def test_mismatched_unit_or_invalid_time_suspends_gap(self):
        for delta in [dict(product_id='other'),dict(assembly_at='bad')]:
            self.d=fixture();self.d['units'][0].update(delta);self.assertIsNone(self.board().work_orders['W1']['row']['assembly_gap'])
    def test_batch_route_quantity_and_interval(self):
        b=self.board(tab='batches');r=b.batches['B1'];self.assertTrue(r['row']['complete']);self.assertEqual((r['row']['route_steps'],r['row']['done_steps'],r['row']['assembly_refs'],r['row']['unreferenced_qty'],r['row']['interval_minutes']),(2,2,1,1,5));self.assertEqual(r['gaps'][0]['minimum_minutes'],5)
    def test_kit_is_not_missing_route_or_physical_inventory(self):
        r=self.board().batches['K1']['row'];self.assertIn('kit',r['flags']);self.assertNotIn('pending',r['flags']);self.assertIsNone(r['unreferenced_qty']);self.assertEqual(r['issues'],[])
    def test_missing_operation_pending_not_zero_duration(self):
        self.d['operations']=self.d['operations'][1:];r=self.board().batches['B1'];self.assertFalse(r['row']['complete']);self.assertIsNone(r['steps'][0]['elapsed_minutes']);self.assertIsNone(r['row']['unreferenced_qty'])
    def test_repeated_process_requires_split_rework_link(self):
        self.d['operations'].append({**self.d['operations'][0],'id':'OP6'});r=self.board().batches['B1']['row'];self.assertFalse(r['complete']);self.assertTrue(any('多次' in x for x in r['issues']))
    def test_route_version_missing_and_cycle(self):
        self.d['work_orders'][0]['route_version']='other';self.assertFalse(self.board().batches['B1']['row']['complete'])
        self.d=fixture();self.d['route_dependencies'].append(dict(id='D3',product_id='P1',from_route_id='R2',to_route_id='R1',lag_minutes=0));self.assertTrue(any('环' in x for x in self.board().batches['B1']['row']['issues']))
    def test_flow_qty_and_minimum_interval_checked(self):
        for delta in [dict(input_qty=1,good_qty=1),dict(started='2026-09-29T08:12:00')]:
            self.d=fixture();self.d['operations'][1].update(delta);self.assertFalse(self.board().batches['B1']['row']['complete'])
    def test_first_process_qty_matches_batch(self):
        self.d['batches'][0]['qty']=3;self.assertTrue(any('首工序' in x for x in self.board().batches['B1']['row']['issues']))
    def test_cross_batch_to_assembly_dependency(self):
        self.d['operations'][2]['started']='2026-09-29T08:32:00';self.assertTrue(any('依赖' in x for x in self.board().batches['B1']['row']['issues']))
    def test_wrong_batch_reference_kind_and_duplicate_ref(self):
        self.d['units'][0]['assembly_batch']='B1';self.assertTrue(self.board().batches['B1']['row']['issues']);self.assertFalse(self.board().batches['B1']['row']['complete'])
    def test_future_batch_excluded_and_before_create_rejected(self):
        self.d['batches'][0]['created']='2026-10-02T08:00:00';self.assertNotIn('B1',self.board().batches);self.assertFalse(self.board().operations['OP1']['row']['done'])
    def test_future_operation_excluded_but_future_finish_is_active(self):
        self.d['operations'][4].update(started='2026-10-02T09:00:00',finished='2026-10-02T10:00:00');b=self.board();self.assertNotIn('OP5',b.operations);self.assertEqual(b.work_orders['W1']['future_events'],1)
        self.d=fixture();self.d['operations'][4]['finished']='2026-10-02T09:00:00';r=self.board().operations['OP5']['row'];self.assertTrue(r['active']);self.assertIsNone(r['output_as_of'])
    def test_running_event_duration_clamped_and_output_unknown(self):
        self.d['operations'][4].update(status='进行中',finished=None);r=self.board().operations['OP5']['row'];self.assertTrue(r['active']);self.assertEqual(r['elapsed_minutes'],3415);self.assertIsNone(r['output_as_of'])
    def test_rework_is_subset_not_added_to_good(self):
        b=self.board(tab='operations');r=next(r for r in b.breakdown(b.selected()) if r['process']=='返修');self.assertEqual((r['completed_input'],r['completed_good'],r['completed_rework']),(1,1,1))
    def test_bad_quantities_states_times_not_completed(self):
        for delta in [dict(input_qty=True),dict(good_qty=-1),dict(scrap_qty=1),dict(rework_qty=3),dict(good_qty=1),dict(status='撤销'),dict(started='bad'),dict(finished=None),dict(finished='2026-09-29T07:00:00')]:
            self.d=fixture();self.d['operations'][0].update(delta);self.assertFalse(self.board().operations['OP1']['row']['done'])
    def test_resource_equipment_owner_and_object_guards(self):
        for delta in [dict(equipment_id='EQ2'),dict(resource_id='RS2'),dict(employee_id='missing'),dict(object_id='missing'),dict(work_order_id='W2'),dict(object_type='other')]:
            self.d=fixture();self.d['operations'][0].update(delta);self.assertFalse(self.board().operations['OP1']['row']['done'])
    def test_assembly_timestamp_and_single_sn_grain(self):
        for delta in [dict(finished='2026-09-29T08:47:00'),dict(input_qty=2,good_qty=2)]:
            self.d=fixture();self.d['operations'][2].update(delta);self.assertFalse(self.board().operations['OP3']['row']['done'])
    def test_pack_mixed_work_order_or_qty_cannot_allocate(self):
        self.d['shipments']=[dict(id='SH1',qty=1,shipped='2026-09-29T11:00:00')];self.d['shipment_units']=[dict(id='PACK1',shipment_id='SH1',unit_id='SN1')]
        op={**self.d['operations'][4],'id':'PACK','object_type':'发货行','object_id':'SH1','equipment_id':'EQ6','resource_id':'RS6','process':'包装'};self.d['operations'].append(op);self.assertTrue(self.board().operations['PACK']['row']['done'])
        self.d['units'].append({**self.d['units'][0],'id':'SN2','work_order_id':'W2'});self.d['shipment_units'].append(dict(id='PACK2',shipment_id='SH1',unit_id='SN2'));self.assertFalse(self.board().operations['PACK']['row']['done'])
    def test_repeat_tests_are_events_not_motor_output(self):
        self.d['operations'].append({**self.d['operations'][-1],'id':'OP6'});b=self.board(tab='operations');r=next(x for x in b.breakdown(b.selected()) if x['process']=='终检');self.assertEqual((r['events'],r['objects'],r['completed_good']),(2,1,2));self.assertEqual(b.work_orders['W1']['row']['assembled_qty'],1)
    def test_scopes_intersect_and_empty_not_fallback(self):
        self.assertEqual([r['id'] for r in self.board(**{'from':'2026-09-29','to':'2026-09-30'}).selected()],['W2']);self.assertEqual(self.board(family='no').selected(),[])
        self.assertEqual([r['id'] for r in self.board(tab='operations',kind='整机',process='终检',work_order='W1').selected()],['OP5']);self.assertEqual(self.board(tab='batches',kind='转子').selected(),[])
    def test_unknown_filters_and_detail_scope(self):
        for f in [dict(tab='bad'),dict(stage='done'),dict(process='冲片'),dict(kind='定子'),dict(x='y'),{'from':'2026-10-02','to':'2026-10-01'}]:
            with self.assertRaises(ValueError):m.filters(f)
        with self.assertRaises(Record.DoesNotExist):self.board(work_order='W2').detail('work_orders','W1')
    def test_orphans_are_visible_and_safe_hides_costs(self):
        self.d['operations'][0]['work_order_id']='missing';self.d['batches'][0]['work_order_id']='missing';b=self.board();self.assertEqual(len(b.global_issues),2);self.assertNotIn('cents',json.dumps(m.safe(b.work_orders,False)))

class ManufacturingAPI(PlatformCase):
    def setUp(self):
        super().setUp()
        for ds,rows in fixture().items():
            for r in rows:self.record(ds,r)
        self.client.force_login(self.admin)
    def payload(self):return dict(status='待计划核对',owner='生产计划岗位（模拟）',due_date='2026-10-05',note='核对计划时间与原始排程依据',version=0,data_revision=list(analytics.revision()))
    def test_auth_no_store_and_money_hiding(self):
        self.client.force_login(self.quality)
        for url in ['/api/manufacturing','/api/manufacturing?tab=batches','/api/manufacturing?tab=operations','/api/manufacturing/work_orders/W1','/api/manufacturing/work_orders/W1/evidence','/api/manufacturing/export']:
            r=self.client.get(url);self.assertEqual(r.status_code,200,url);self.assertEqual(r.headers['Cache-Control'],'no-store');self.assertNotIn('cents',r.content.decode())
        self.assertEqual(Client().get('/api/manufacturing').status_code,401)
    def test_scope_stage_csv_and_wrong_tab(self):
        r=self.client.get('/api/manufacturing?stage=attention').json();self.assertEqual((r['total'],r['summary']['objects']),(1,3))
        rows=list(csv.reader(io.StringIO(self.client.get('/api/manufacturing/export?stage=attention').content.decode('utf-8-sig'))));self.assertEqual(rows[3][0],'W3');self.assertEqual(len(rows),4)
        for url in ['/api/manufacturing/batches/B1','/api/manufacturing/work_orders/W1?work_order=W2','/api/manufacturing/work_orders/missing']:self.assertEqual(self.client.get(url).status_code,404)
    def test_detail_evidence_and_kind_filtered(self):
        r=self.client.get('/api/manufacturing/batches/B1?tab=batches').json();self.assertEqual(r['row']['unreferenced_qty'],1)
        r=self.client.get('/api/manufacturing/batches/B1/evidence?tab=batches').json();self.assertTrue(any(x['dataset']=='routes' for x in r['rows']));self.assertTrue(any(x['dataset']=='operations' for x in r['rows']))
        self.client.force_login(self.quality);self.assertFalse(self.client.get('/api/manufacturing/batches/B1/evidence?tab=batches').json()['can_download_original'])
    def test_followup_versions_revision_and_unchanged_facts(self):
        before=list(Record.objects.values_list('id','values','revision'));url='/api/manufacturing/work_orders/W3/follow-up';p=self.payload();self.assertEqual(self.post(url,p).status_code,200);self.assertEqual(self.post(url,p).status_code,409);self.assertEqual(before,list(Record.objects.values_list('id','values','revision')))
        self.assertEqual(self.client.get('/api/manufacturing/work_orders/W3/history').json()['rows'][0]['detail']['after']['version'],1)
        p.update(version=1,data_revision=['old']);self.assertEqual(self.post(url,p).status_code,409)
    def test_roles_and_csrf(self):
        u=User.objects.create_user('viewer');self.client.force_login(u);self.assertEqual(self.post('/api/manufacturing/work_orders/W3/follow-up',self.payload()).status_code,403)
        ops=User.objects.create_user('ops');ops.groups.add(Group.objects.create(name='operations'));self.client.force_login(ops);self.assertEqual(self.post('/api/manufacturing/work_orders/W3/follow-up',{**self.payload(),'status':'演练已核对'}).status_code,403)
        c=Client(enforce_csrf_checks=True);c.force_login(self.admin);self.assertEqual(c.post('/api/manufacturing/work_orders/W3/follow-up',json.dumps(self.payload()),content_type='application/json').status_code,403)
    def test_invalid_payload_and_atomic_audit(self):
        url='/api/manufacturing/work_orders/W3/follow-up'
        for delta in [dict(status='批准生产'),dict(version=True),dict(due_date='bad'),dict(note='短'),dict(other=1)]:self.assertEqual(self.post(url,{**self.payload(),**delta}).status_code,400)
        with patch('app.manufacturing_views.AuditEvent.objects.create',side_effect=RuntimeError('audit failed')):
            with self.assertRaises(RuntimeError):self.post(url,self.payload())
        self.assertFalse(IssueDisposition.objects.filter(key='manufacturing:work_orders:W3').exists())
    def test_csv_formula_injection_escaped(self):
        r=Record.objects.get(dataset='work_orders',business_key='W1');r.values['status']='=1+1';r.save();self.assertIn("'=1+1",self.client.get('/api/manufacturing/export').content.decode('utf-8-sig'))
