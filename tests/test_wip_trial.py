from copy import deepcopy
from datetime import datetime,timedelta
from decimal import Decimal
from django.test import SimpleTestCase
from app import wip_trial as engine,wip_trial_contract as contract,joint_schedule
from .test_joint_schedule import fixture as joint_fixture


def fixture():
    js,jt,parent,refs=joint_fixture()
    refs['products']['P1']['route_version']='V1'
    for res in refs['production_resources'].values():res['equipment_id']='EQ-'+res['id']
    refs['work_orders']={'WO1':dict(id='WO1',product_id='P1',planned_qty=2,bom_version='B1',route_version='V1',status='生产中',planned_start='2026-10-01',planned_end='2026-10-03')}
    refs['batches']={'BATCH1':dict(id='BATCH1',work_order_id='WO1',kind='定子',qty=2,created='2026-10-01T08:00:00',status='在制')}
    refs['operations']={'OP1':dict(id='OP1',work_order_id='WO1',object_type='生产批次',object_id='BATCH1',process='冲片',resource_id='R1',equipment_id='EQ-R1',employee_id='E1',started='2026-10-02T07:00:00',finished='2026-10-02T07:20:00',input_qty=2,good_qty=2,scrap_qty=0,rework_qty=0,status='完成')}
    refs['units']={}
    joint=dict(result=joint_schedule.analyze(js,jt,parent,refs),tables=jt,parent=parent)
    s=dict(id='WR1',name='在制剩余模拟',series='WR-S',version=1,supersedes_id=None,joint_study_id=js['id'],cutoff='2026-10-02T08:00:00',owner_id='E1',basis='SIM')
    t=dict(wip_trial_jobs=[dict(id='L1',study_id='WR1',job_id='J1',work_order_id='WO1',basis='SIM')],wip_trial_tasks=[],wip_trial_materials=[],wip_trial_supplies=[])
    for task in parent['base']['tables']['schedule_tasks']:
        done=task['id']=='TA'
        t['wip_trial_tasks'].append(dict(id='P-'+task['id'],study_id='WR1',task_id=task['id'],state='已完成' if done else '未开始',operation_id='OP1' if done else None,
            completed_qty=task['lot_qty'] if done else 0,remaining_qty=0 if done else task['lot_qty'],remaining_minutes=0 if done else task['lot_qty']*task['unit_minutes'],recovery_minutes=0,resource_id=None,employee_id=None,basis='SIM'))
        for b in jt['joint_bindings']:
            if b['route_id']!=task['route_id']:continue
            bom=refs['bom'][b['bom_id']];unit=refs['materials'][bom['material_id']]['unit']
            q=0 if done else float(joint_schedule.requirement(task['lot_qty'],bom['qty'],bom['scrap_allowance'],b['quantum']))
            t['wip_trial_materials'].append(dict(id='M-'+task['id']+'-'+b['id'],study_id='WR1',task_id=task['id'],binding_id=b['id'],embedded_qty=0,required_qty=q,unit=unit,basis='SIM'))
    for r in jt['joint_supplies']:
        t['wip_trial_supplies'].append(dict(id='S-'+r['id'],study_id='WR1',material_id=r['material_id'],lot=r['lot'],location='仓库',unit=r['unit'],qty=r['qty'],unavailable_qty=0,available_from=s['cutoff'],status='可投入',kind='仓库余料',owner_job_id=None,observed_at=s['cutoff'],reference='SIM',basis='SIM'))
    return seal(s,t,joint,refs)


def seal(s,t,joint,refs):
    for field,ds in [('job_count','wip_trial_jobs'),('task_count','wip_trial_tasks'),('material_count','wip_trial_materials'),('supply_count','wip_trial_supplies')]:s[field]=len(t[ds])
    s['reference_hash']=contract.references_hash(engine.parent_tables(joint),refs,t);s['content_hash']=contract.bundle_hash(s,t)
    return [s,t,joint,refs]


def running(args):
    s,t,joint,refs=args;p=t['wip_trial_tasks'][0];p.update(state='加工中',completed_qty=1,remaining_qty=1,remaining_minutes=12,resource_id='R1',employee_id='E1')
    refs['operations']['OP1'].update(finished=None,status='进行中',good_qty=1)
    t['wip_trial_materials'][0].update(embedded_qty=1,required_qty=.5)
    return seal(*args)


def second_job(args):
    from app import finite_schedule,crew_schedule
    s,t,joint,refs=args;parent=joint['parent'];base=parent['base'];bt=base['tables'];original=list(bt['schedule_tasks'])
    bt['schedule_jobs'].append(dict(bt['schedule_jobs'][0],id='J2',priority=2))
    for r in original:bt['schedule_tasks'].append(dict(r,id='X'+r['id'],job_id='J2'))
    for ds in ('schedule_edges','schedule_options'):
        for r in list(bt[ds]):
            x=dict(r,id='X'+r['id'])
            for k in ('task_id','from_task_id','to_task_id'):
                if k in x:x[k]='X'+x[k]
            bt[ds].append(x)
    for r in list(parent['tables']['crew_candidates']):parent['tables']['crew_candidates'].append(dict(r,id='X'+r['id'],task_id='X'+r['task_id']))
    for r in list(joint['tables']['joint_demands']):joint['tables']['joint_demands'].append(dict(r,id='X'+r['id'],job_id='J2'))
    resource_study=base['result']['study'];crew_study=parent['result']['study'];joint_study=joint['result']['study']
    for field,ds in [('job_count','schedule_jobs'),('task_count','schedule_tasks'),('edge_count','schedule_edges'),('option_count','schedule_options')]:resource_study[field]=len(bt[ds])
    base['result']=finite_schedule.analyze(resource_study,bt,refs)
    crew_study['candidate_count']=len(parent['tables']['crew_candidates']);parent['result']=crew_schedule.analyze(crew_study,parent['tables'],base,refs)
    joint_study['demand_count']=len(joint['tables']['joint_demands']);joint['result']=joint_schedule.analyze(joint_study,joint['tables'],parent,refs)
    refs['work_orders']['WO2']=dict(refs['work_orders']['WO1'],id='WO2',status='已下达')
    t['wip_trial_jobs'].append(dict(t['wip_trial_jobs'][0],id='L2',job_id='J2',work_order_id='WO2'))
    for task in original:
        t['wip_trial_tasks'].append(dict(id='P-X'+task['id'],study_id='WR1',task_id='X'+task['id'],state='未开始',operation_id=None,completed_qty=0,remaining_qty=task['lot_qty'],remaining_minutes=task['lot_qty']*task['unit_minutes'],recovery_minutes=0,resource_id=None,employee_id=None,basis='SIM'))
        for b in joint['tables']['joint_bindings']:
            if b['route_id']!=task['route_id']:continue
            bom=refs['bom'][b['bom_id']]
            t['wip_trial_materials'].append(dict(id='M-X'+task['id']+'-'+b['id'],study_id='WR1',task_id='X'+task['id'],binding_id=b['id'],embedded_qty=0,required_qty=float(joint_schedule.requirement(task['lot_qty'],bom['qty'],bom['scrap_allowance'],b['quantum'])),unit=refs['materials'][bom['material_id']]['unit'],basis='SIM'))
    return seal(*args)


class WipTrialRules(SimpleTestCase):
    def setUp(self):self.args=fixture()
    def calc(self,seal_inputs=True):
        if seal_inputs:seal(*self.args)
        return engine.analyze(*self.args,self.args[0]['cutoff'])
    def test_completed_prefix_no_future_capacity_or_duplicate_material(self):
        r=self.calc();self.assertEqual(r['state'],'trial',r['issues']);rows={t['id']:t for t in r['tasks']}
        self.assertEqual(rows['TA']['state'],'completed');self.assertIsNone(rows['TA']['started'])
        self.assertEqual(rows['TA']['finished'],'2026-10-02T07:20:00');self.assertEqual(r['summary']['historical_completed_tasks'],1)
        self.assertEqual(next(x for x in r['resources'] if x['id']=='R1')['busy_minutes'],0)
        self.assertFalse(any(x['task_id']=='TA' for x in r['reservations']))
        self.assertEqual(next(x for x in r['demands'] if x['task_id']=='TA')['state'],'not_required')
        self.assertEqual(r['jobs'][0]['finished'],'2026-10-02T08:50:00')
    def test_running_partial_locks_original_people_resource_and_remaining_minutes(self):
        running(self.args);r=self.calc();self.assertEqual(r['state'],'trial',r['issues']);row=next(t for t in r['tasks'] if t['id']=='TA')
        self.assertEqual((row['state'],row['resource_id'],row['employee_id'],row['setup_minutes']),('carried','R1','E1',0))
        self.assertEqual((row['started'],row['finished']),('2026-10-02T08:00:00','2026-10-02T08:12:00'))
        d=next(x for x in r['demands'] if x['task_id']=='TA');self.assertEqual((d['gross_remaining_qty'],d['embedded_qty'],d['required_qty']),('1.5','1','0.5'))
    def test_stopped_partial_has_explicit_recovery_on_top_of_setup(self):
        running(self.args);p=self.args[1]['wip_trial_tasks'][0];p.update(state='中断待续',resource_id=None,employee_id=None,recovery_minutes=3)
        self.args[3]['operations']['OP1'].update(status='中断',finished='2026-10-02T07:50:00')
        r=self.calc();self.assertEqual(r['state'],'trial',r['issues']);row=next(t for t in r['tasks'] if t['id']=='TA')
        self.assertEqual((row['state'],row['setup_minutes'],row['recovery_minutes']),('scheduled',8,3));self.assertEqual(row['finished'],'2026-10-02T08:20:00')
    def test_actual_finish_and_lag_survive_completed_task_removal(self):
        self.args[3]['operations']['OP1']['finished']='2026-10-02T07:59:00'
        self.args[2]['parent']['base']['tables']['schedule_edges'][0]['lag_minutes']=80
        r=self.calc();self.assertEqual(next(t for t in r['tasks'] if t['id']=='TC1')['dependency_ready'],'2026-10-02T09:19:00')
    def test_running_material_shortage_pauses_atomically(self):
        running(self.args);self.args[1]['wip_trial_supplies'][0]['qty']=.4;r=self.calc()
        self.assertEqual(r['state'],'paused');self.assertIsNone(r['summary']);self.assertFalse(r['tasks']);self.assertFalse(r['reservations'])
    def test_running_cannot_move_to_later_window_or_new_resource(self):
        running(self.args);self.args[2]['parent']['tables']['crew_windows'][0]['started']='2026-10-02T09:00:00'
        r=self.calc();self.assertEqual(r['state'],'paused');self.assertTrue(any('连续窗口' in e for e in r['issues']))
    def test_snapshot_and_reference_changes_pause_without_resealing(self):
        self.args[3]['operations']['OP1']['good_qty']=1
        r=self.calc(False);self.assertEqual(r['state'],'paused');self.assertTrue(any('依据已变化' in e for e in r['issues']))
        self.args=fixture();self.args[1]['wip_trial_tasks'][0]['completed_qty']=1
        self.assertTrue(any('摘要不一致' in e for e in self.calc(False)['issues']))
    def test_missing_task_or_material_rows_do_not_hide_progress(self):
        for ds in ('wip_trial_tasks','wip_trial_materials','wip_trial_jobs'):
            self.args=fixture();self.args[1][ds].pop();r=self.calc();self.assertEqual(r['state'],'paused');self.assertIsNone(r['summary'])
    def test_unmapped_operation_and_scrap_require_explicit_task_coverage(self):
        self.args[3]['operations']['EXTRA']=dict(self.args[3]['operations']['OP1'],id='EXTRA')
        self.assertTrue(any('未包含' in e for e in self.calc()['issues']))
        self.args=fixture();self.args[3]['operations']['OP1']['scrap_qty']=1;self.assertTrue(any('报废或返工' in e for e in self.calc()['issues']))
    def test_wrong_branch_identity_and_remaining_quantity_pause(self):
        for change in ('branch','qty'):
            self.args=fixture()
            if change=='branch':self.args[3]['batches']['BATCH1']['kind']='转子'
            else:self.args[1]['wip_trial_tasks'][0]['remaining_qty']=1
            self.assertEqual(self.calc()['state'],'paused')
    def test_line_side_owned_by_other_job_cannot_cover_this_job(self):
        self.args[1]['wip_trial_supplies'][0].update(kind='线边盘点',owner_job_id='OTHER')
        self.assertEqual(self.calc()['state'],'paused')
    def test_duplicate_lot_location_cannot_double_count(self):
        t=self.args[1];t['wip_trial_supplies'].append(dict(t['wip_trial_supplies'][0],id='DUP'))
        self.assertTrue(any('重复作为余料' in e for e in self.calc()['issues']))
    def test_dedicated_stock_before_shared_and_each_lot_conserved(self):
        t=self.args[1];t['wip_trial_supplies'].append(dict(t['wip_trial_supplies'][0],id='LINE',lot='LINE',kind='线边盘点',owner_job_id='J1',qty=1))
        r=self.calc();self.assertEqual(r['reservations'][0]['supply_id'],'LINE')
        for lot in r['lots']:self.assertEqual(Decimal(lot['usable_qty']),Decimal(lot['reserved_qty'])+Decimal(lot['remaining_qty']))
    def test_future_supply_and_isolation_do_not_become_available_now(self):
        for kind in ('future','isolate'):
            self.args=fixture();s=self.args[1]['wip_trial_supplies'][0]
            if kind=='future':s.update(kind='未来到料',available_from='2026-10-02T09:00:00')
            else:s['status']='隔离'
            r=self.calc();self.assertEqual(r['state'],'trial',r['issues'])
            row=next(t for t in r['tasks'] if t['id']=='TB')
            self.assertEqual(row['started'],'2026-10-02T09:00:00' if kind=='future' else None)
    def test_zero_remainder_needs_no_supply_and_pure_inputs(self):
        before=deepcopy(self.args);r=self.calc();self.assertEqual(self.args,before);self.assertTrue(r['tasks'])
    def test_bad_numeric_rows_and_hash_are_rejected_at_ingestion_contract(self):
        for value in (True,-1,float('nan'),float('inf'),'1'):
            r=dict(self.args[1]['wip_trial_tasks'][0],remaining_minutes=value);self.assertTrue(contract.issues('wip_trial_tasks',r))
        self.assertTrue(contract.issues('wip_trial_studies',dict(self.args[0],content_hash='bad')))

    def test_running_people_cannot_be_reused_before_release(self):
        running(self.args)
        # Permit the same worker for rotor work as an explicit current candidate.
        parent=self.args[2]['parent'];old=parent['result']['credentials'][1]
        old['employee_id']='E1'
        self.args[3]['skills']['S2']['employee_id']='E1'
        r=self.calc();self.assertEqual(r['state'],'trial',r['issues'])
        rows={r['id']:r for r in r['tasks']}
        self.assertEqual(rows['TB']['started'],'2026-10-02T08:12:00')
        self.assertEqual(rows['TB']['employee_id'],'E1')
    def test_historical_overlapping_operator_reports_pause(self):
        running(self.args)
        p=self.args[1]['wip_trial_tasks'][1];p.update(state='加工中',operation_id='OP2',completed_qty=1,remaining_qty=1,remaining_minutes=5,resource_id='R2',employee_id='E1')
        refs=self.args[3];refs['batches']['BATCH2']=dict(refs['batches']['BATCH1'],id='BATCH2',kind='转子')
        refs['operations']['OP2']=dict(refs['operations']['OP1'],id='OP2',process='转子铸铝',object_id='BATCH2',resource_id='R2',equipment_id='EQ-R2')
        self.args[1]['wip_trial_materials'][1]['required_qty']=1
        r=self.calc();self.assertEqual(r['state'],'paused');self.assertTrue(any('占用重叠' in e for e in r['issues']))
    def test_reference_projection_ignores_unrelated_objects_but_not_new_target_report(self):
        refs=self.args[3];before=self.args[0]['reference_hash']
        refs['operations']['OTHER']=dict(refs['operations']['OP1'],id='OTHER',work_order_id='NOT_SELECTED')
        self.assertEqual(contract.references_hash(engine.parent_tables(self.args[2]),refs,self.args[1]),before)
        refs['operations']['OTHER']['work_order_id']='WO1'
        self.assertNotEqual(contract.references_hash(engine.parent_tables(self.args[2]),refs,self.args[1]),before)
    def test_version_chain_and_complete_empty_stock(self):
        self.args[0].update(version=2,supersedes_id='NOT_FOUND')
        self.assertTrue(any('版本链' in e for e in self.calc()['issues']))
        self.args=fixture();self.args[1]['wip_trial_supplies']=[]
        r=self.calc();self.assertEqual(r['state'],'trial',r['issues']);self.assertEqual(r['summary']['blocked_jobs'],1)
    def test_running_cannot_ignore_gap_between_snapshot_and_baseline(self):
        running(self.args);self.args[0]['cutoff']='2026-10-02T07:59:00'
        r=self.calc();self.assertEqual(r['state'],'paused');self.assertTrue(any('截止续作' in e for e in r['issues']))
    def test_declared_material_rounding_is_per_remaining_task(self):
        self.args[1]['wip_trial_materials'][0].update(embedded_qty=1,required_qty=0)
        r=self.calc();self.assertEqual(r['state'],'paused');self.assertTrue(any('剩余需求须等于' in e for e in r['issues']))

    def test_two_jobs_cannot_borrow_dedicated_line_side_stock(self):
        second_job(self.args);self.args[1]['wip_trial_supplies'][0].update(kind='线边盘点',owner_job_id='J1',qty=20)
        self.args[1]['wip_trial_supplies'][1]['qty']=4
        r=self.calc();self.assertEqual(r['state'],'trial',r['issues']);self.assertEqual(r['summary']['covered_jobs'],1)
        self.assertFalse(any(a['job_id']=='J2' and a['material_id']=='M1' for a in r['reservations']))
        self.assertEqual(next(t for t in r['tasks'] if t['id']=='XTA')['shortages'][0]['available_qty'],'0')
    def test_own_line_side_first_preserves_shared_stock_for_other_job(self):
        second_job(self.args);t=self.args[1];t['wip_trial_supplies'][1]['qty']=4
        t['wip_trial_supplies'].append(dict(t['wip_trial_supplies'][0],id='LINE',lot='LINE',kind='线边盘点',owner_job_id='J1',qty=2))
        r=self.calc();self.assertEqual(r['state'],'trial',r['issues']);self.assertEqual(r['summary']['covered_jobs'],2)
        self.assertEqual(r['reservations'][0]['supply_id'],'LINE')
        for field in ('resource_id','employee_id'):
            grouped={}
            for task in r['tasks']:
                if task['state'] in ('scheduled','carried'):grouped.setdefault(task[field],[]).append(task)
            for tasks in grouped.values():
                tasks.sort(key=lambda t:t['started'])
                self.assertTrue(all(a['finished']<=b['started'] for a,b in zip(tasks,tasks[1:])))
    def test_two_running_jobs_cannot_lock_same_resource_at_boundary(self):
        running(self.args);second_job(self.args);t=self.args[1];refs=self.args[3]
        refs['batches']['BATCH2']=dict(refs['batches']['BATCH1'],id='BATCH2',work_order_id='WO2')
        refs['operations']['OP2']=dict(refs['operations']['OP1'],id='OP2',work_order_id='WO2',object_id='BATCH2',started=self.args[0]['cutoff'],good_qty=0)
        p=next(p for p in t['wip_trial_tasks'] if p['task_id']=='XTA');p.update(state='加工中',operation_id='OP2',resource_id='R1',employee_id='E1')
        r=self.calc();self.assertEqual(r['state'],'paused');self.assertTrue(any('锁定相互冲突' in e for e in r['issues']));self.assertFalse(r['reservations'])
