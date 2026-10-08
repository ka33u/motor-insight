"""Validate an explicit, complete WIP cutover before scheduling any remainder."""
from collections import defaultdict
from datetime import timedelta
from decimal import Decimal
import hashlib
from pathlib import Path
from . import finite_schedule as resource, joint_schedule, wip_trial_contract as contract
from .wip_trial_schema import DATASETS
from .joint_schedule_contract import number

VERSION='WIP_REMAINDER_SHARED_POOLS_1'
MAX_ROWS=5000
NOTICE=('合成在制剩余试排：逐任务明确报工与剩余量；完成任务只保留实际时点，加工中任务固定原人机续作。'
        '逐任务按剩余数量计算定额并扣除声明已投入在制品的材料，未耗用余料另列独立共享或专属池；'
        '按任务取整与原整批取整不同，不把净领料当作线边实存，不复用原方案供给。'
        '连续窗口、单容量、保守尾部追加，不抢占或回填；试排不等于实物盘点证明、质量批准或正式派工。')


def parent_tables(joint):
    parent=joint['parent'];base=parent['base']
    return {**base['tables'],**parent['tables'],**joint['tables'],
        'schedule_studies':[base['result']['study']],'crew_studies':[parent['result']['study']],
        'joint_studies':[joint['result']['study']]}


def rule_hash():
    h=hashlib.sha256(joint_schedule.rule_hash().encode())
    for name in ('wip_trial.py','wip_trial_contract.py','wip_trial_schema.py','wip_trial_schedule.py','wip_trial_data.py','wip_trial_replay.py'):
        h.update((Path(__file__).parent/name).read_bytes())
    return h.hexdigest()


def analyze(study,tables,joint,refs,as_of,observations=None):
    result=dict(state='paused',study=study,rule_version=VERSION,notice=NOTICE,issues=[],summary=None,
        tasks=[],jobs=[],resources=[],workers=[],demands=[],lots=[],reservations=[],balances=[],
        policy=joint['result']['policy'],policy_name=joint['result']['policy_name'])
    problems=result['issues']
    def problem(message):problems.append(message)
    try:
        for issue in contract.issues('wip_trial_studies',study):problem(issue['message'])
        for field,ds in [('job_count','wip_trial_jobs'),('task_count','wip_trial_tasks'),('material_count','wip_trial_materials'),('supply_count','wip_trial_supplies')]:
            rows=tables.get(ds,[])
            if len(rows)>MAX_ROWS or len(rows)!=study.get(field):problem(ds+'声明行数与完整输入不一致')
            if len({r.get('id') for r in rows})!=len(rows):problem(ds+'声明编号重复')
            for r in rows:
                if r.get('study_id')!=study['id']:problem(r['id']+'不属于本方案')
                problems.extend(r['id']+'：'+i['message'] for i in contract.issues(ds,r))
        if study['content_hash']!=contract.bundle_hash(study,tables):problem('完整声明摘要不一致，未采用不完整或改写版本')
        if joint['result']['state']!='trial':problem('原联立输入未通过完整性核对')
        if study['joint_study_id']!=joint['result']['study']['id']:problem('原联立方案身份不一致')
        if study['reference_hash']!=contract.references_hash(parent_tables(joint),refs,tables):problem('原始工单、报工或试排依据已变化，须新版本重核')
        cutoff=resource.time(study['cutoff']);snapshot=resource.time(as_of)
        baseline=resource.time(joint['parent']['base']['result']['study']['baseline'])
        if cutoff>snapshot or cutoff>baseline:problem('进度截止不能晚于来源截止或试排起点')
        history=list(refs.get('wip_trial_studies',{}).values())
        if sum(r.get('series')==study['series'] and r.get('version')==study['version'] for r in history)>1:problem('同系列版本号重复，不能确定完整版本')
        prior=refs.get('wip_trial_studies',{}).get(study.get('supersedes_id'))
        if study['version']==1:
            if study.get('supersedes_id'):problem('首版不能声明前版')
        elif not prior or prior.get('series')!=study['series'] or prior.get('version')!=study['version']-1:
            problem('前版缺失或版本链不连续')
        if study.get('owner_id') not in refs.get('employees',{}):problem('负责工号缺失')
        if problems:return result
    except (KeyError,TypeError,ValueError) as e:
        problem('方案字段或依据无效：'+str(e));return result
    base=joint['parent']['base'];jobs={r['id']:r for r in base['tables']['schedule_jobs']}
    tasks={r['id']:r for r in base['tables']['schedule_tasks']}
    links={r['job_id']:r for r in tables['wip_trial_jobs']}
    progress={r['task_id']:r for r in tables['wip_trial_tasks']}
    if set(links)!=set(jobs) or len(links)!=len(tables['wip_trial_jobs']):problem('工单映射必须完整且每批唯一')
    if len({r['work_order_id'] for r in links.values()})!=len(links):problem('同工单不能重复分配到多个本方案批次')
    if set(progress)!=set(tasks) or len(progress)!=len(tables['wip_trial_tasks']):problem('每个原任务必须有且只有一条进度声明')
    if problems:return result
    operations=refs.get('operations',{});used_operations={};actual={};object_routes=set();portion_objects={}
    for jid,job in jobs.items():
        try:
            wo=refs['work_orders'][links[jid]['work_order_id']]
            if any(wo.get(a)!=job[b] for a,b in [('product_id','product_id'),('planned_qty','qty'),('route_version','route_version')]):problem(jid+'必须映射同配置、同路线版本的完整工单数量')
            if wo.get('bom_version')!=refs['products'][job['product_id']]['bom_version']:problem(jid+'工单BOM与原联立依据不同')
            if wo.get('status') not in ('未开工','已下达','生产中','进行中') and any(progress[t['id']]['state']!='已完成' for t in tasks.values() if t['job_id']==jid):problem(jid+'非活动工单仍声明剩余任务')
        except (KeyError,TypeError):problem(jid+'工单或配置资料缺失')
    for key,task in tasks.items():
        p=progress[key];job=jobs[task['job_id']];wo=links[job['id']]['work_order_id']
        try:
            if p['completed_qty']+p['remaining_qty']!=task['lot_qty']:problem(key+'完成与剩余数量未覆盖原任务数量')
            state=p['state'];minutes=number(p['remaining_minutes']);recovery=number(p['recovery_minutes'])
            if state!='中断待续' and recovery:problem(key+'仅中断待续任务可以声明恢复准备分钟')
            if (state=='已完成')!=(p['remaining_qty']==0) or (p['remaining_qty']==0)!=(minutes==0):problem(key+'状态、剩余数量和工时不一致')
            if state=='未开始':
                if p['operation_id'] or p['completed_qty'] or p.get('resource_id') or p.get('employee_id'):problem(key+'未开始任务不能带报工、完成量或在加工锁定')
                continue
            op=operations.get(p.get('operation_id'))
            if not op:problem(key+'已开始任务缺少明确原报工');continue
            if op['id'] in used_operations:problem(op['id']+'不能重复用于多个任务')
            used_operations[op['id']]=key;actual[key]=op
            route=refs['routes'][task['route_id']]
            if op['work_order_id']!=wo or op['process']!=route['process']:problem(key+'报工工单或工序不一致')
            if op.get('scrap_qty')!=0 or op.get('rework_qty')!=0:problem(key+'报废或返工尚未由独立补充任务覆盖，未猜测扣减')
            if op.get('input_qty')!=task['lot_qty'] or op.get('good_qty')!=p['completed_qty']:problem(key+'报工投入/良品与进度数量不一致')
            started=resource.time(op['started']);finished=resource.time(op['finished']) if op.get('finished') else None
            if started>cutoff or finished and (finished>cutoff or finished<=started):problem(key+'实际报工时间超出截止或先后错误')
            if op['object_type']=='生产批次':
                obj=refs.get('batches',{}).get(op['object_id'])
                if not obj or obj['work_order_id']!=wo or obj['kind']!=route['branch'] or obj['qty']<task['lot_qty']:problem(key+'报工生产批次与分支或数量不一致')
            elif op['object_type']=='整机':
                obj=refs.get('units',{}).get(op['object_id'])
                if not obj or obj['work_order_id']!=wo or obj['product_id']!=job['product_id'] or route['branch']!='整机' or task['lot_qty']!=1:problem(key+'报工SN与工单配置或单台任务不一致')
            else:problem(key+'报工对象没有可核对的原批次或SN身份')
            identity=(op['object_type'],op['object_id'],task['route_id'])
            if identity in object_routes:problem(key+'同一对象的同一路线不能重复覆盖多个任务')
            object_routes.add(identity)
            if op['object_type']=='生产批次' and obj and resource.time(obj['created'])>started:problem(key+'生产批次尚未建立便发生报工')
            if op['object_type']=='整机':
                portion=(task['job_id'],task['portion'])
                if portion in portion_objects and portion_objects[portion]!=op['object_id']:problem(key+'同一单台份号映射到不同SN')
                portion_objects[portion]=op['object_id']
            if state=='加工中':
                if finished or op.get('status')!='进行中' or not p.get('resource_id') or not p.get('employee_id'):problem(key+'加工中须为未结束报工并锁定原人机')
                if baseline!=cutoff:problem(key+'加工中只能从进度截止续作，不能忽略截止与起点之间的占用')
                resource_row=refs.get('production_resources',{}).get(p.get('resource_id'),{})
                if op.get('resource_id')!=p.get('resource_id') or op.get('employee_id')!=p.get('employee_id') or op.get('equipment_id')!=resource_row.get('equipment_id'):problem(key+'锁定人机与原报工不一致')
            else:
                if not finished:problem(key+'完成或中断待续任务须有已登记停止时点')
                if p.get('resource_id') or p.get('employee_id'):problem(key+'非加工中任务不锁定人机')
                if state=='已完成' and op.get('status')!='完成':problem(key+'完成声明与原报工状态不一致')
                if state=='中断待续' and op.get('status')!='中断':problem(key+'中断待续缺明确中断报工')
        except (KeyError,TypeError,ValueError) as e:problem(key+'进度依据无效：'+str(e))
    works={r['work_order_id'] for r in links.values()}
    for op in operations.values():
        if op.get('work_order_id') in works:
            try:
                if resource.time(op['started'])<=cutoff and op['id'] not in used_operations:problem(op['id']+'截止前报工未包含在任务映射中')
            except (ValueError,TypeError,KeyError):problem(op['id']+'报工时点未知，不能判定进度完整性')
    for sn in refs.get('units',{}).values():
        if sn.get('work_order_id') in works:
            try:
                if resource.time(sn['assembly_at'])<=cutoff and not any(op.get('object_id')==sn['id'] and op.get('object_type')=='整机' and op.get('process')=='装配' and progress[k]['state']=='已完成' for k,op in actual.items()):problem(sn['id']+'截止前装配SN缺明确已完成装配任务')
            except (ValueError,TypeError,KeyError):problem(sn['id']+'装配时间未知')
    # Within the declared task population, an actual operator/resource cannot
    # support overlapping occupied intervals. This is not a factory-wide audit.
    occupied=defaultdict(list)
    for key,op in actual.items():
        try:
            left=resource.time(op['started']);right=resource.time(op['finished']) if op.get('finished') else cutoff
            if left>=right:continue
            for field in ('resource_id','employee_id'):
                if op.get(field):occupied[field,op[field]].append((left,right,key))
        except (ValueError,TypeError,KeyError):continue
    for (field,identity),spans in occupied.items():
        spans.sort()
        for i,(left,right,key) in enumerate(spans):
            for a,b,prior_key in spans[:i]:
                if max(left,a)<min(right,b):problem(identity+'原报工占用重叠：'+prior_key+' / '+key)
    for edge in base['tables']['schedule_edges']:
        before,after=progress[edge['from_task_id']],progress[edge['to_task_id']]
        if after['state']!='未开始':
            if before['state']!='已完成':problem(edge['id']+'已开始任务的前序尚未完整完成')
            elif edge['from_task_id'] in actual and edge['to_task_id'] in actual:
                try:
                    earliest=resource.time(actual[edge['from_task_id']]['finished'])+timedelta(seconds=resource.seconds(edge['lag_minutes']))
                    if resource.time(actual[edge['to_task_id']]['started'])<earliest:problem(edge['id']+'实际前后序未满足最小等待')
                except (TypeError,ValueError,KeyError):problem(edge['id']+'前后序实际时间待核对')
    bindings={r['id']:r for r in joint['tables']['joint_bindings']}
    expected={(t['id'],b['id']) for t in tasks.values() for b in bindings.values() if b['route_id']==t['route_id']}
    declared={(r['task_id'],r['binding_id']):r for r in tables['wip_trial_materials']}
    if set(declared)!=expected or len(declared)!=len(tables['wip_trial_materials']):problem('每个任务与适用BOM绑定必须完整且唯一声明剩余用料')
    demands=[]
    for pair,r in declared.items():
        if pair not in expected:continue
        try:
            task=tasks[r['task_id']];binding=bindings[r['binding_id']];bom=refs['bom'][binding['bom_id']];unit=refs['materials'][bom['material_id']]['unit']
            remaining=progress[task['id']]['remaining_qty']
            gross=joint_schedule.requirement(remaining,bom['qty'],bom['scrap_allowance'],binding['quantum']) if remaining else Decimal(0)
            embedded=number(r['embedded_qty']);required=number(r['required_qty'])
            if r['unit']!=unit or unit=='件' and (embedded!=embedded.to_integral_value() or required!=required.to_integral_value()):problem(r['id']+'单位或整件数量不一致')
            if embedded>gross or required!=gross-embedded:problem(r['id']+'剩余需求须等于逐任务剩余定额减声明已投入量')
            demands.append(dict(r,job_id=task['job_id'],material_id=bom['material_id'],route_id=task['route_id'],
                gross_remaining_qty=joint_schedule.quantity(gross),calculated_qty=joint_schedule.quantity(required)))
        except (KeyError,ValueError,TypeError) as e:problem(r['id']+'用料依据无效：'+str(e))
    seen=set()
    for s in tables['wip_trial_supplies']:
        try:
            key=(s['material_id'],s['lot'],s['location']);material=refs['materials'][s['material_id']]
            if key in seen:problem(s['id']+'同一物料批次位置被重复作为余料来源')
            seen.add(key)
            if s['unit']!=material['unit']:problem(s['id']+'余料单位与主数据不一致')
            if s['unit']=='件' and any(number(s[k])!=number(s[k]).to_integral_value() for k in ('qty','unavailable_qty')):problem(s['id']+'余料件数须为整数')
            available,observed=resource.time(s['available_from']),resource.time(s['observed_at'])
            if observed>cutoff:problem(s['id']+'余料或承诺登记晚于进度截止')
            if s['kind']=='未来到料':
                if available<=cutoff:problem(s['id']+'未来到料时间须在截止之后')
            elif available>cutoff:problem(s['id']+'已盘点余料可用起点不能晚于截止')
            if s['kind']=='线边盘点':
                if s.get('owner_job_id') not in jobs:problem(s['id']+'线边盘点须明确专属批次')
            elif s.get('owner_job_id'):problem(s['id']+'共享仓库与未来供给不能同时声明线边专属批次')
        except (KeyError,ValueError,TypeError) as e:problem(s['id']+'余料依据无效：'+str(e))
    if problems:
        result['issues']=list(dict.fromkeys(problems));return result
    from .wip_trial_schedule import schedule
    return schedule(study,tables,joint,refs,progress,actual,demands,NOTICE,observations=observations)
