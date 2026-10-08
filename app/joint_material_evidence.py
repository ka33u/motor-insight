"""Read one original material/unit ledger; no allocation or scheduling decisions."""
import hashlib
from copy import deepcopy
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

VERSION='joint-material-evidence-v1'
NOTICE=('仅核对本次独立试排的同物料同单位。未预留不等于缺料，已预留不等于实际领料或批次已排完。'
        '供给排除含整批隔离，范围外剩余不参与本次试排；总量足够不证明时间齐套。'
        '流水沿原算法预留顺序，不按时刻重排，不释放或重新分配预留，不作正式派工。')
BALANCE=('material_id','material_name','unit','required_qty','horizon_usable_qty','reserved_qty','total_excluded_qty','total_remaining_qty','initial_supply_gap_qty')
DEMAND=('id','job_id','binding_id','product_id','bom_id','bom_version','route_id','material_id','unit','required_qty','reserved_qty','state','basis')
LOT=('id','material_id','unit','lot','qty','unavailable_qty','available_from','status','kind','reference','basis','usable_qty','excluded_qty','reserved_qty','remaining_qty')
ALLOCATION=('demand_id','job_id','task_id','supply_id','material_id','unit','qty','reserved_at','available_from')
TASK=('id','job_id','product_id','route_id','process','branch','qty','state','reason','started','finished','root_tasks')

def definition_hash():return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
def pick(row,fields):return {k:deepcopy(row[k]) for k in fields}
def fail():raise ValueError('物料需求、供给或预留关系无法核对，请重新读取完整方案')
def quantity(value):
    if not isinstance(value,str):fail()
    try:value=Decimal(value)
    except InvalidOperation:fail()
    if not value.is_finite() or value<0:fail()
    return value

def stamp(value):
    try:
        parsed=datetime.fromisoformat(value)
        if parsed.tzinfo is not None or parsed.isoformat(timespec='seconds')!=value:fail()
        return parsed
    except (TypeError,ValueError):fail()

def text(value):return format(value.normalize(),'f') if value else '0'
def total(rows,field):return sum((quantity(r[field]) for r in rows),Decimal(0))
def unique(rows):
    result={r['id']:r for r in rows}
    if len(result)!=len(rows):fail()
    return result

def build(result,material_id,unit):
    if result['state']!='trial':raise ValueError('物料核对只读取已计算的完整试排')
    pair=lambda row:row['material_id']==material_id and row['unit']==unit
    balances=[r for r in result['balances'] if pair(r)]
    if len(balances)!=1:fail()
    balance=balances[0];end=stamp(result['resource_study']['horizon_end'])
    demands=unique(result['demands']);lots=unique(result['lots']);tasks=unique(result['tasks']);jobs=unique(result['jobs'])
    summary=result['summary']
    if summary['tasks']!=len(tasks) or summary['jobs']!=len(jobs) or summary['demands']!=len(demands):fail()
    needs=[r for r in demands.values() if pair(r)];stock=[r for r in lots.values() if pair(r)]
    allocations=[];seen=set()
    for sequence,row in enumerate(result['reservations'],1):
        if not pair(row):continue
        key=row['demand_id'],row['supply_id']
        if key in seen:fail()
        seen.add(key)
        need=demands.get(row['demand_id']);lot=lots.get(row['supply_id']);task=tasks.get(row['task_id'])
        if not need or not lot or not task or not pair(need) or not pair(lot) or row['job_id']!=need['job_id'] or task['job_id']!=need['job_id'] or task['route_id']!=need['route_id']:fail()
        if quantity(row['qty'])<=0 or task['state']!='scheduled' or row['demand_id'] not in task['new_reservation_ids']:fail()
        if row['available_from']!=lot['available_from'] or row['reserved_at']!=task['started'] or not stamp(row['available_from'])<=stamp(row['reserved_at'])<end:fail()
        if need['reservation']!=dict(task_id=row['task_id'],reserved_at=row['reserved_at']):fail()
        allocations.append(dict(sequence=sequence,**pick(row,ALLOCATION)))
    # A row labelled with another unit/material must not hide use of this pair.
    for row in result['reservations']:
        if not pair(row) and (row['demand_id'] in {r['id'] for r in needs} or row['supply_id'] in {r['id'] for r in stock}):fail()
    demand_rows=[];selected_tasks={};refs={('materials',material_id)}
    for need in sorted(needs,key=lambda r:r['id']):
        amount=quantity(need['required_qty']);reserved=quantity(need['reserved_qty'])
        rows=[a for a in allocations if a['demand_id']==need['id']]
        related=[t for t in tasks.values() if t['job_id']==need['job_id'] and t['route_id']==need['route_id']]
        if not related or need['job_id'] not in jobs or any(need['id'] not in t['demand_ids'] for t in related):fail()
        if amount<=0 or reserved!=total(rows,'qty') or reserved not in (Decimal(0),amount):fail()
        if (need['state']=='reserved')!=(reserved==amount) or (need['state']=='unreserved')!=(reserved==0) or bool(need['reservation'])!=bool(rows):fail()
        reservation=pick(need['reservation'],('task_id','reserved_at')) if rows else None
        demand_rows.append(dict(**pick(need,DEMAND),unreserved_qty=text(amount-reserved),reservation=reservation,task_ids=sorted(t['id'] for t in related)))
        for task in related:selected_tasks[task['id']]=pick(task,TASK)
        refs.update({('joint_demands',need['id']),('joint_bindings',need['binding_id']),('bom',need['bom_id']),('routes',need['route_id']),('products',need['product_id']),('schedule_jobs',need['job_id'])})
    lot_rows=[]
    for lot in sorted(stock,key=lambda r:(r['available_from'],r['id'])):
        q,u,e,r,left,unavailable=(quantity(lot[f]) for f in ('qty','usable_qty','excluded_qty','reserved_qty','remaining_qty','unavailable_qty'))
        inside=stamp(lot['available_from'])<end
        if unavailable>q or lot['status'] not in ('可预留','隔离'):fail()
        if u!=(q-unavailable if lot['status']=='可预留' else Decimal(0)) or q!=u+e or u!=r+left:fail()
        if r!=total([a for a in allocations if a['supply_id']==lot['id']],'qty') or (not inside and r):fail()
        lot_rows.append(dict(**pick(lot,LOT),inside_horizon=inside))
        refs.add(('joint_supplies',lot['id']))
    required=total(needs,'required_qty');reserved=total(needs,'reserved_qty')
    usable=total([r for r in lot_rows if r['inside_horizon']],'usable_qty')
    quantities=dict(required_qty=required,horizon_usable_qty=usable,reserved_qty=reserved,
                    total_excluded_qty=total(stock,'excluded_qty'),total_remaining_qty=total(stock,'remaining_qty'),initial_supply_gap_qty=max(Decimal(0),required-usable))
    if any(quantity(balance[k])!=value for k,value in quantities.items()) or reserved!=total(stock,'reserved_qty'):fail()
    by_job=[]
    for key in sorted({r['job_id'] for r in needs}):
        job=jobs[key];rows=[r for r in demand_rows if r['job_id']==key]
        by_job.append(dict(**pick(job,('id','product_id','qty','due','state')),demands=len(rows),reserved_demands=sum(r['state']=='reserved' for r in rows),
                           required_qty=text(total(rows,'required_qty')),reserved_qty=text(total(rows,'reserved_qty')),unreserved_qty=text(total(rows,'unreserved_qty'))))
    refs.update(('schedule_tasks',key) for key in selected_tasks)
    report=dict(version=VERSION,notice=NOTICE,balance=pick(balance,BALANCE),baseline=result['resource_study']['baseline'],horizon_end=result['resource_study']['horizon_end'],
                summary=dict(demands=len(needs),reserved_demands=sum(r['state']=='reserved' for r in needs),jobs=len(by_job),lots=len(stock),allocations=len(allocations),
                             required_qty=text(required),reserved_qty=text(reserved),unreserved_qty=text(required-reserved),
                             total_supply_qty=text(total(stock,'qty')),excluded_qty=text(total(stock,'excluded_qty')),
                             horizon_remaining_qty=text(total([r for r in lot_rows if r['inside_horizon']],'remaining_qty')),
                             outside_remaining_qty=text(total([r for r in lot_rows if not r['inside_horizon']],'remaining_qty'))),
                jobs=by_job,demands=demand_rows,lots=lot_rows,allocations=allocations,tasks=[selected_tasks[k] for k in sorted(selected_tasks)])
    return report,refs
