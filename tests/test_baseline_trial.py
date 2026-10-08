from collections import defaultdict
from copy import deepcopy
from decimal import Decimal
from django.test import SimpleTestCase
from app import baseline_trial as engine, order_baseline, joint_schedule, crew_schedule, finite_schedule
from app.order_baseline_contract import bundle_hash, signature, source_hash
from .test_order_baseline import fixture
from .test_crew_schedule import declare as crew_declare
from .test_joint_schedule import declare as joint_declare


def seal(args):
    s, tables, _, refs, _ = args
    for link in tables['order_baseline_links']:
        for ds, field in [('order_lines', 'order_hash'), ('work_orders', 'work_hash'), ('allocations', 'allocation_hash'), ('products', 'product_hash')]:
            link[field] = source_hash(ds, order_baseline.frozen_sources(link)[ds])
        rows = [r for r in tables['order_baseline_bom'] if r['link_id'] == link['id']]
        for row in rows:
            row['bom_hash'] = source_hash('bom', order_baseline.frozen_bom(row, link))
            row['route_hash'] = source_hash('routes', order_baseline.frozen_route(row, link))
            row['material_hash'] = source_hash('materials', dict(id=row['material_id'], unit=row['unit']))
        link.update(bom_count=len(rows), bom_set_hash=signature(sorted([order_baseline.frozen_bom(r, link) for r in rows], key=lambda r:r['id'])))
    s.update(link_count=len(tables['order_baseline_links']), bom_count=len(tables['order_baseline_bom']))
    s['content_hash'] = bundle_hash(s, tables)
    refs['order_baselines'][s['id']] = s


def run(args, policy='due', reseal=False):
    if reseal:
        seal(args)
    s, tables, joint, refs, cutoff = args
    crew, base = joint['parent'], joint['parent']['base']
    base['result'] = finite_schedule.analyze(base['study'], base['tables'], refs, policy)
    crew['result'] = crew_schedule.analyze(crew['result']['study'], crew['tables'], base, refs)
    joint['result'] = joint_schedule.analyze(joint['result']['study'], joint['tables'], crew, refs)
    checked = order_baseline.analyze(*args)
    return engine.analyze(checked, tables, joint, refs, cutoff)


def two_versions():
    args = list(fixture())
    s, tables, joint, refs, cutoff = args
    crew, base = joint['parent'], joint['parent']['base']
    rt, ct, jt = base['tables'], crew['tables'], joint['tables']
    refs['routes'] = {'A': refs['routes']['A']}
    refs['route_dependencies'] = {}
    refs['bom'] = {'B1': {**refs['bom']['B1'], 'qty':1.25, 'scrap_allowance':.1}}
    rt['schedule_jobs'] = [{**rt['schedule_jobs'][0], 'id':'J'+str(i), 'qty':q, 'priority':3-i,
                            'due':'2026-10-02T'+('10' if i==1 else '11')+':00:00', 'task_count':1, 'edge_count':0} for i,q in [(1,2),(2,3)]]
    rt['schedule_tasks'] = [{**rt['schedule_tasks'][0], 'id':'T'+str(i), 'job_id':'J'+str(i), 'lot_qty':q} for i,q in [(1,2),(2,3)]]
    rt['schedule_edges'] = []
    rt['schedule_options'] = [{**rt['schedule_options'][0], 'id':'O'+str(i), 'task_id':'T'+str(i), 'setup_minutes':0} for i in (1,2)]
    rt['schedule_windows'] = rt['schedule_windows'][:1]
    for field, ds in [('job_count','schedule_jobs'),('task_count','schedule_tasks'),('edge_count','schedule_edges'),('option_count','schedule_options'),('window_count','schedule_windows')]:
        base['study'][field] = len(rt[ds])
    ct['crew_candidates'] = [{**ct['crew_candidates'][0], 'id':'H'+str(i), 'task_id':'T'+str(i)} for i in (1,2)]
    ct['crew_credentials'] = ct['crew_credentials'][:1]
    ct['crew_windows'] = ct['crew_windows'][:1]
    crew_declare(crew['result']['study'],ct)
    jt['joint_bindings'] = [{**jt['joint_bindings'][0], 'quantum':.1}]
    jt['joint_demands'] = [{**jt['joint_demands'][0], 'id':'D'+str(i),'job_id':'J'+str(i),'required_qty':qty} for i,qty in [(1,2.8),(2,4.2)]]
    jt['joint_supplies'] = [{**jt['joint_supplies'][0], 'qty':6}]
    joint_declare(joint['result']['study'],jt)
    link, row = tables['order_baseline_links'][0], tables['order_baseline_bom'][0]
    tables['order_baseline_links'] = [{**link,'id':'OLK'+str(i),'job_id':'J'+str(i),'work_order_id':'WO'+str(i),'allocation_id':'AL'+str(i),
                                     'plan_qty':q,'work_order_qty':q,'allocation_qty':q,'order_qty':5,'bom_version':'B'+str(i)} for i,q in [(1,2),(2,3)]]
    tables['order_baseline_bom'] = [{**row,'id':'OBS'+str(i),'link_id':'OLK'+str(i),'version':'B'+str(i),'unit_qty':q,'scrap_allowance':scrap,'quantum':.1} for i,q,scrap in [(1,1.25,.1),(2,1.1,.05)]]
    refs['order_lines']['OL1']['qty'] = 5
    refs['work_orders'] = {'WO'+str(i):{**refs['work_orders']['WO1'],'id':'WO'+str(i),'planned_qty':q,'bom_version':'B'+str(i)} for i,q in [(1,2),(2,3)]}
    refs['allocations'] = {'AL'+str(i):{**refs['allocations']['AL1'],'id':'AL'+str(i),'work_order_id':'WO'+str(i),'qty':q} for i,q in [(1,2),(2,3)]}
    seal(args)
    return args


class BaselineTrialTests(SimpleTestCase):
    def setUp(self):
        self.args = list(fixture())

    def paused(self, code):
        r = run(self.args)
        self.assertEqual(r['state'], 'paused', r['issues'])
        self.assertIn(code, [p['code'] for p in r['issues']])
        self.assertIsNone(r['trial'])
        self.assertFalse(r['comparison']['available'])
        return r

    def test_shared_material_two_versions_due_hand_oracle(self):
        r = run(two_versions())
        self.assertEqual(r['state'], 'trial', r['issues'])
        t = r['trial']
        self.assertEqual([d['required_qty'] for d in t['demands']], ['2.8','3.5'])
        self.assertEqual([d['bom_version'] for d in t['demands']], ['B1','B2'])
        self.assertEqual(t['jobs'][0]['finished'], '2026-10-02T08:20:00')
        self.assertIsNone(t['jobs'][1]['finished'])
        self.assertEqual(t['tasks'][1]['shortages'][0]['shortage_qty'], '0.3')
        self.assertEqual(t['lots'][0]['reserved_qty'], '2.8')
        self.assertEqual(t['lots'][0]['remaining_qty'], '3.2')
        self.assertEqual(t['demands'][1]['reserved_qty'], '0')

    def test_shared_material_two_versions_priority_hand_oracle(self):
        r = run(two_versions(),'priority')['trial']
        self.assertIsNone(r['jobs'][0]['finished'])
        self.assertEqual(r['jobs'][1]['finished'], '2026-10-02T08:30:00')
        self.assertEqual(r['lots'][0]['reserved_qty'], '3.5')
        self.assertEqual(r['lots'][0]['remaining_qty'], '2.5')
        self.assertEqual(r['tasks'][1]['shortages'][0]['shortage_qty'], '0.3')

    def test_sufficient_shared_supply_never_double_books_people_or_equipment(self):
        for policy, finishes in [('due',['08:20:00','08:50:00']),('priority',['08:50:00','08:30:00'])]:
            a = two_versions();a[2]['tables']['joint_supplies'][0]['qty'] = 6.3
            r = run(a,policy)['trial']
            self.assertEqual([j['finished'][-8:] for j in r['jobs']],finishes)
            self.assertEqual(r['tasks'][1]['started'],r['tasks'][0]['finished'])
            self.assertEqual(r['lots'][0]['reserved_qty'],'6.3')
            self.assertEqual(r['lots'][0]['remaining_qty'],'0')
            self.assertEqual(r['workers'][0]['busy_minutes'],50)
            self.assertEqual(r['resources'][0]['busy_minutes'],50)

    def test_same_workorder_cannot_have_conflicting_frozen_versions(self):
        self.args=two_versions();self.args[1]['order_baseline_links'][1]['work_order_id']='WO1';seal(self.args)
        self.paused('BASELINE_INVALID')

    def test_current_bom_invalid_does_not_overwrite_valid_frozen_requirements(self):
        self.args[3]['bom']['B1']['qty']=999
        r=run(self.args)
        self.assertEqual(r['state'],'trial',r['issues'])
        self.assertEqual(r['trial']['demands'][0]['required_qty'],'3')
        self.assertFalse(r['comparison']['available'])
        self.assertFalse(r['history_verified'])
        self.assertTrue(r['warnings'])

    def test_current_bom_add_delete_do_not_fabricate_historical_completeness(self):
        for mode in ('add','delete'):
            a=list(fixture())
            if mode=='add':a[3]['bom']['EXTRA']={**a[3]['bom']['B1'],'id':'EXTRA'}
            else:a[3]['bom'].pop('B1')
            r=run(a)
            self.assertEqual(r['state'],'trial',r['issues'])
            self.assertEqual(len(r['trial']['demands']),3)
            self.assertFalse(r['history_verified'])
            self.assertFalse(r['comparison']['available'])

    def test_frozen_changed_quantity_decimal_hand_oracle(self):
        self.assertEqual(joint_schedule.requirement(6,8.073,.035,.001),Decimal('50.134'))
        self.assertEqual(joint_schedule.requirement(6,8.97,.035,.001),Decimal('55.704'))
        self.assertEqual(Decimal('50.134')-Decimal('55.704'),Decimal('-5.570'))

    def test_unit_mismatch_never_implicit_conversion(self):
        self.args[1]['order_baseline_bom'][0]['unit']='g';seal(self.args)
        self.paused('UNIT_MISMATCH')

    def test_route_identity_mismatch_pauses(self):
        self.args[3]['routes']['A']['mandatory']=False
        self.paused('ROUTE_MISMATCH')

    def test_bom_identity_change_is_not_just_usage_change(self):
        self.args[3]['bom']['B1']['material_id']='M2'
        self.paused('MATERIAL_IDENTITY_INVALID')

    def test_missing_current_order_identity_pauses(self):
        for ds,key in [('orders','SO1'),('order_lines','OL1'),('allocations','AL1'),('work_orders','WO1')]:
            self.args=list(fixture());self.args[3][ds].pop(key)
            self.paused('ORDER_IDENTITY_CHANGED')

    def test_quantity_scope_or_unknown_closed_status_pauses(self):
        for ds,key,field,value,code in [('orders','SO1','status','已取消','ORDER_NOT_OPEN'),('orders','SO1','status','未知','ORDER_NOT_OPEN'),('order_lines','OL1','qty',11,'ORDER_SCOPE_CHANGED'),('allocations','AL1','effective','2026-09-22','ORDER_SCOPE_CHANGED'),('work_orders','WO1','status','在制','WORK_NOT_NEW')]:
            self.args=list(fixture());self.args[3][ds][key][field]=value;self.paused(code)

    def test_declared_snapshot_tampering_pauses_before_any_schedule(self):
        self.args[1]['order_baseline_bom'][0]['unit_qty']=3
        self.paused('BASELINE_INVALID')

    def test_registered_wip_or_operation_prevents_whole_batch_restart(self):
        for ds,clock in [('units','assembly_at'),('operations','started')]:
            self.args=list(fixture());self.args[3][ds]['X']=dict(id='X',work_order_id='WO1',**{clock:self.args[4]})
            self.paused('WIP_REGISTERED')

    def test_issued_and_returned_net_zero_is_not_new_work(self):
        self.args[3]['inventory_movements']={
            'I':dict(id='I',work_order_id='WO1',reference='WO1',material_id='M1',movement='生产领料',qty_signed=-3,occurred=self.args[4]),
            'R':dict(id='R',work_order_id='WO1',reference='WO1',material_id='M1',movement='生产退料',qty_signed=3,occurred=self.args[4])}
        r=self.paused('MATERIAL_ALREADY_ISSUED')
        self.assertIn('ISSUE_HISTORY_UNRESOLVED',[p['code'] for p in r['issues']])

    def test_invalid_issue_history_never_disappears_as_zero(self):
        for field,value in [('occurred','invalid'),('qty_signed',True),('qty_signed',0),('qty_signed',float('nan')),('movement','未知'),('reference','OTHER')]:
            self.args=list(fixture());row=dict(id='I',work_order_id='WO1',reference='WO1',movement='生产领料',qty_signed=-1,occurred=self.args[4]);row[field]=value
            self.args[3]['inventory_movements']={'I':row};self.paused('ISSUE_HISTORY_UNRESOLVED')

    def test_post_cutoff_history_is_not_counted_as_registered_issue(self):
        self.args[3]['inventory_movements']={'I':dict(id='I',work_order_id='WO1',reference='WO1',movement='生产领料',qty_signed=-1,occurred='2026-10-01T18:00:01')}
        self.assertEqual(run(self.args)['state'],'trial')

    def test_cross_order_allocation_after_baseline_before_cutoff_is_checked(self):
        self.args[0]['baseline_at']='2026-09-29T18:00:00';seal(self.args)
        self.args[3]['allocations']['A2']=dict(id='A2',work_order_id='WO1',order_line_id='OTHER',qty=1,effective='2026-09-30')
        self.paused('CROSS_ORDER_ALLOCATION')

    def test_shipments_after_baseline_before_cutoff_reduce_current_open_demand(self):
        self.args[0]['baseline_at']='2026-09-29T18:00:00';seal(self.args)
        self.args[3]['shipments']['SH1']=dict(id='SH1',order_line_id='OL1',qty=9,shipped='2026-09-30T09:00:00')
        self.paused('ORDER_OVERPLANNED')

    def test_invalid_supply_remains_pause_even_if_current_bom_also_invalid(self):
        self.args[3]['bom']['B1']['qty']=999
        self.args[2]['tables']['joint_supplies'][0]['unit']='g'
        self.paused('SUPPLY_INVALID')

    def test_no_windows_block_without_consuming_material_or_zero_completion(self):
        crew=self.args[2]['parent'];crew['tables']['crew_windows']=[];crew_declare(crew['result']['study'],crew['tables'])
        r=run(self.args)
        self.assertEqual(r['state'],'trial')
        self.assertEqual(r['trial']['reservations'],[])
        self.assertIsNone(r['trial']['jobs'][0]['finished'])
        self.assertIsNone(r['comparison']['jobs'][0]['delta_minutes'])

    def test_equal_basis_preserves_old_task_times_and_shared_balances(self):
        r=run(self.args);old=self.args[2]['result']
        self.assertEqual(r['trial']['jobs'],old['jobs'])
        self.assertEqual(r['trial']['balances'],old['balances'])
        for left,right in zip(old['tasks'],r['trial']['tasks']):
            for field in ('id','job_id','resource_id','employee_id','started','finished','state'):
                self.assertEqual(left[field],right[field])
        self.assertTrue(all(j['delta_minutes']==0 for j in r['comparison']['jobs']))

    def test_readonly_deterministic_preserves_both_source_engines(self):
        r=run(self.args);before=deepcopy(self.args)
        checked=order_baseline.analyze(*self.args)
        again=engine.analyze(checked,self.args[1],self.args[2],self.args[3],self.args[4])
        self.assertEqual(r,again)
        self.assertEqual(self.args,before)

    def test_complete_output_material_conservation_and_no_mixed_unit_total(self):
        r=run(self.args)['trial']
        self.assertEqual({(b['material_id'],b['unit']) for b in r['balances']},{('M1','kg'),('M2','件')})
        for lot in r['lots']:
            self.assertEqual(Decimal(lot['usable_qty']),Decimal(lot['reserved_qty'])+Decimal(lot['remaining_qty']))
        for demand in r['demands']:
            self.assertEqual(Decimal(demand['reserved_qty']),sum((Decimal(a['qty']) for a in r['reservations'] if a['demand_id']==demand['id']),Decimal(0)))
