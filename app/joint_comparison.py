"""Compare two existing heuristics at identical fact/identity scope, without ranking."""
from decimal import Decimal
from . import finite_schedule as finite, joint_schedule as joint
from .import_review import ReviewConflict

NOTICE='两列来自同一份合成物料、设备、人员、BOM和时间范围，只改变派序。差值统一为“批次优先级优先 − 应完成时间优先”；完成时间负值表示更早。未排完没有完成时间，不能用零替代。对照不是因果归因、最优性证明或正式排产批准。'
JOB_FIELDS=('product_id','qty','priority','due','task_count')
TASK_FIELDS=('job_id','product_id','route_id','qty','portion','process','branch','predecessors')
TASK_CHANGES=('state','started','finished','resource_id','employee_id','reason','root_tasks','shortages','new_reservation_ids')

def indexed(rows,fields=('id',)):
    out={}
    for row in rows:
        key=tuple(row[f] for f in fields)
        if key in out:raise ReviewConflict('对照对象身份重复，暂停比较')
        out[key]=row
    return out

def pairs(left,right,identity=('id',),fixed=()):
    a,b=indexed(left,identity),indexed(right,identity)
    if a.keys()!=b.keys():raise ReviewConflict('两种派序的完整对象范围不一致，暂停比较')
    for key in sorted(a):
        if any(a[key].get(f)!=b[key].get(f) for f in fixed):raise ReviewConflict('两种派序的对象身份或假设不一致，暂停比较')
        yield a[key],b[key]

def minutes(a,b):
    return (finite.time(b)-finite.time(a)).total_seconds()/60 if a is not None and b is not None else None

def compare(left,right):
    if left['policy']!='due' or right['policy']!='priority':raise ReviewConflict('策略列顺序无效')
    for field in ('study','crew_study','resource_study','rule_version'):
        if left[field]!=right[field]:raise ReviewConflict('方案、版本或时间范围不一致，暂停比较')
    result=dict(state='paused',study=left['study'],resource_study=left['resource_study'],notice=NOTICE,
                policies=finite.POLICIES,columns={p:dict(state=r['state'],summary=r['summary'],issues=r['issues']) for p,r in [('due',left),('priority',right)]},
                jobs=[],tasks=[],materials=[],allocations=[],transitions=[],summary=None)
    if left['state']!='trial' or right['state']!='trial':return result
    for a,b in pairs(left['jobs'],right['jobs'],fixed=JOB_FIELDS):
        delta=minutes(a['finished'],b['finished'])
        timing='both_blocked' if a['finished'] is None and b['finished'] is None else 'newly_complete' if a['finished'] is None else 'no_longer_complete' if b['finished'] is None else 'earlier' if delta<0 else 'later' if delta>0 else 'same'
        result['jobs'].append(dict(id=a['id'],**{f:a[f] for f in JOB_FIELDS},left=a,right=b,finish_delta_minutes=delta,
                                   lateness_delta_minutes=b['lateness_minutes']-a['lateness_minutes'] if delta is not None else None,
                                   timing=timing,changed=a['state']!=b['state'] or a['finished']!=b['finished'] or a['scheduled_count']!=b['scheduled_count']))
    for a,b in pairs(left['tasks'],right['tasks'],fixed=TASK_FIELDS):
        changed=[f for f in TASK_CHANGES if a.get(f)!=b.get(f)]
        result['tasks'].append(dict(id=a['id'],job_id=a['job_id'],process=a['process'],branch=a['branch'],left=a,right=b,
                                   start_delta_minutes=minutes(a['started'],b['started']),finish_delta_minutes=minutes(a['finished'],b['finished']),changes=changed,changed=bool(changed)))
    for a,b in pairs(left['balances'],right['balances'],identity=('material_id','unit'),fixed=('required_qty','horizon_usable_qty','initial_supply_gap_qty','total_excluded_qty')):
        delta=Decimal(b['reserved_qty'])-Decimal(a['reserved_qty'])
        remaining=Decimal(b['total_remaining_qty'])-Decimal(a['total_remaining_qty'])
        if delta+remaining:raise ReviewConflict('两列物料预留与剩余差值不守恒，暂停比较')
        result['materials'].append(dict(material_id=a['material_id'],material_name=a['material_name'],unit=a['unit'],left=a,right=b,
                                       reserved_delta_qty=joint.quantity(delta),remaining_delta_qty=joint.quantity(remaining),changed=bool(delta)))
    allocations=[indexed(r['reservations'],('demand_id','supply_id')) for r in (left,right)]
    for key in sorted(allocations[0].keys()|allocations[1].keys()):
        a,b=allocations[0].get(key),allocations[1].get(key);present=a or b
        if a and b and any(a[f]!=b[f] for f in ('job_id','material_id','unit','available_from')):raise ReviewConflict('预留批次身份或到料时点不一致')
        result['allocations'].append(dict(demand_id=key[0],supply_id=key[1],job_id=present['job_id'],material_id=present['material_id'],unit=present['unit'],left=a,right=b,
                                          qty_delta=joint.quantity(Decimal(b['qty'] if b else '0')-Decimal(a['qty'] if a else '0')),changed=a!=b))
    for a in ('scheduled','late','blocked'):
        for b in ('scheduled','late','blocked'):
            rows=[r for r in result['jobs'] if r['left']['state']==a and r['right']['state']==b]
            result['transitions'].append(dict(left=a,right=b,jobs=len(rows),qty=sum(r['qty'] for r in rows)))
    jobs=result['jobs'];tasks=result['tasks']
    result['summary']=dict(jobs=len(jobs),qty=sum(r['qty'] for r in jobs),tasks=len(tasks),changed_jobs=sum(r['changed'] for r in jobs),changed_tasks=sum(r['changed'] for r in tasks),changed_allocations=sum(r['changed'] for r in result['allocations']),
                           both_complete=sum(r['finish_delta_minutes'] is not None for r in jobs),**{k:sum(r['timing']==k for r in jobs) for k in ('earlier','later','same','newly_complete','no_longer_complete','both_blocked')})
    result['state']='compared';return result

def same_inputs(left,right):
    if any(left[k]!=right[k] for k in ('source_hash','rule_hash','sources','tables','references')):
        raise ReviewConflict('两次试排的资料或规则不一致，暂停比较')
    if left['parent']['tables']!=right['parent']['tables'] or left['parent']['base']['tables']!=right['parent']['base']['tables']:
        raise ReviewConflict('两次试排的人机输入不一致，暂停比较')
