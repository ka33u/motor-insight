"""Resource/day facts and independent checks over imported production evidence."""
from collections import defaultdict, Counter
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP

def dt(s): return datetime.fromisoformat(s)
def idx(rows): return {r['id']: r for r in rows}
def group(rows, key):
    out=defaultdict(list)
    for r in rows: out[r[key]].append(r)
    return out
def merged(spans):
    out=[]
    for a,b in sorted(spans):
        if a>=b: continue
        if out and a<=out[-1][1]: out[-1]=(out[-1][0],max(out[-1][1],b))
        else: out.append((a,b))
    return out
def duration(spans): return sum((b-a).total_seconds()/60 for a,b in merged(spans))
def intersect(left,right):
    return [(max(a,c),min(b,e)) for a,b in left for c,e in right if max(a,c)<min(b,e)]
def span(r,end='finished',cutoff=None):
    a=dt(r['started']);b=dt(r.get(end) or cutoff)
    return a,min(b,dt(cutoff)) if cutoff else b

def blocks(d, cutoff):
    result=defaultdict(list)
    for key in ['downtime','maintenance']:
        for r in d.get(key,[]):
            if r.get('started') and r['started']<cutoff:
                a,b=span(r,cutoff=cutoff)
                if a<b: result[r['equipment_id']].append((a,b,key,r))
    return result

def resource_days(d,cutoff):
    resources=idx(d.get('production_resources',[]));equipment=idx(d['equipment'])
    blocked=blocks(d,cutoff);cal=defaultdict(list);ops=defaultdict(list)
    for key,source in [('calendar',d.get('resource_calendars',[])),('operation',d['operations'])]:
        for r in source:
            if not r.get('resource_id') or not r.get('finished') or r['started']>=cutoff: continue
            a,b=span(r,cutoff=cutoff)
            while a<b:
                stop=min(b,datetime.combine(a.date()+timedelta(days=1),datetime.min.time()))
                (cal if key=='calendar' else ops)[(r['resource_id'],a.date().isoformat())].append((a,stop,r))
                a=stop
    result=[]
    for rid,date in sorted(set(cal)|set(ops)):
        r=resources.get(rid)
        if not r: continue
        e=equipment[r['equipment_id']];cc=cal[(rid,date)];oo=ops[(rid,date)]
        windows=merged([(a,b) for a,b,_ in cc]);work=[(a,b) for a,b,_ in oo]
        bb=[(a,b,key,v) for a,b,key,v in blocked[e['id']] if a.date().isoformat()<=date<=b.date().isoformat()]
        lost=duration(intersect(windows,[(a,b) for a,b,_,_ in bb]));scheduled=duration(windows)
        # One independently modelled slot per resource; other capacities require
        # splitting the source into slots before interpreting this ratio.
        available=scheduled-lost;busy=sum((b-a).total_seconds()/60 for a,b in work)
        conflicts=busy-duration(work)+duration(intersect(work,[(a,b) for a,b,_,_ in bb]))
        outside=duration(work)-duration(intersect(work,windows))
        valid=r.get('capacity')==1 and conflicts<.0001 and outside<.0001
        result.append(dict(id=rid+'|'+date,resource_id=rid,equipment_id=e['id'],equipment=e['name'],station=r['station'],process=r['process'],workshop=e['workshop'],date=date,scheduled_minutes=round(scheduled,4),blocked_minutes=round(lost,4),available_minutes=round(available,4),busy_minutes=round(busy,4),event_count=len(oo),occupancy_pct=round(busy/available*100,3) if valid and available>0 else None,integrity='可计算' if valid else '资源容量或事件冲突待核查',_sources=[{'dataset':key,'key':row['id']} for key,rows in [('production_resources',[r]),('resource_calendars',[v for _,_,v in cc]),('operations',[v for _,_,v in oo]),('downtime',[v for _,_,k,v in bb if k=='downtime']),('maintenance',[v for _,_,k,v in bb if k=='maintenance'])] for row in rows]))
    return result

def audit(d,cutoff):
    findings=defaultdict(list)
    def fail(kind,key): findings[kind].append(key)
    resources=idx(d.get('production_resources',[]));operations=idx(d['operations']);employees=idx(d['employees']);cal=group(d.get('resource_calendars',[]),'resource_id');blocked=blocks(d,cutoff)
    skills=group(d.get('skills',[]),'employee_id');opgroups=group(d['operations'],'object_id');routes=idx(d['routes']);units=idx(d['units'])
    dependencies=group(d.get('route_dependencies',[]),'product_id');labor=group(d.get('labor_entries',[]),'operation_id');costs=Counter();daily=defaultdict(Counter)
    for op in d['operations']:
        rid=op.get('resource_id');r=resources.get(rid)
        if not r: fail('missing_resource',op['id']);continue
        a,b=span(op,cutoff=cutoff)
        if a>=b or op['finished']>cutoff: fail('invalid_event_time',op['id'])
        if r['capacity']!=1 or op['input_qty']>r['max_batch_qty']: fail('resource_capacity',op['id'])
        if any(op[k]!=r[k] for k in ['equipment_id','employee_id','process']) or r['effective']>op['started'][:10]: fail('resource_assignment',op['id'])
        if not any(c['employee_id']==op['employee_id'] and c['started']<=op['started'] and c['finished']>=op['finished'] for c in cal[rid]): fail('outside_resource_calendar',op['id'])
        if any(a<e and c<b for c,e,_,_ in blocked[op['equipment_id']]): fail('during_equipment_block',op['id'])
        if not any(s['process']==op['process'] and s['status']=='有效' and s['approved']<=op['started'][:10]<=s['expires'] for s in skills[op['employee_id']]): fail('missing_skill',op['id'])
        entries=sorted(labor[op['id']],key=lambda r:r['started']);cursor=op['started']
        for row in entries:
            if row['started']!=cursor or row['finished']>op['finished'] or row['started']>=row['finished']: fail('labor_coverage',row['id'])
            cursor=row['finished'];mins=(dt(row['finished'])-dt(row['started'])).total_seconds()/60
            if abs(mins-row['minutes'])>.0001 or row['employee_id']!=op['employee_id'] or row['work_order_id']!=op['work_order_id']: fail('labor_assignment',row['id'])
            rate=employees[op['employee_id']]['hourly_cents'];amount=int((Decimal(str(row['minutes']))/60*rate).quantize(Decimal('1'),rounding=ROUND_HALF_UP))
            if row['hourly_cents']!=rate or row['amount_cents']!=amount: fail('labor_cost',row['id'])
            costs[row['work_order_id']]+=row['amount_cents'];daily[(row['employee_id'],row['started'][:10])][row['activity']]+=row['minutes']
        if cursor!=op['finished']: fail('labor_missing_tail',op['id'])
    for key in ['resource_id','employee_id']:
        for obj,rows in group(d['operations'],key).items():
            last=None
            for row in sorted(rows,key=lambda r:r['started']):
                if last and row['started']<last['finished']: fail(key+'_overlap',row['id'])
                if last is None or row['finished']>last['finished']: last=row
    for row in d.get('labor_entries',[]):
        if row['operation_id'] not in operations: fail('orphan_labor',row['id'])
    observed_cost=Counter()
    for row in d['costs']:
        if row['category']=='直接人工': observed_cost[row['work_order_id']]+=row['amount_cents']
    for wo in set(costs)|set(observed_cost):
        if costs[wo]!=observed_cost[wo]: fail('direct_labor_not_reconciled',wo)
    seen_days=set()
    for row in d['attendance']:
        key=(row['employee_id'],row['date']);seen_days.add(key);x=daily[key]
        if row.get('scheduled_hours') is None: fail('missing_attendance_schedule',row['id']);continue
        parts=sum(row.get(k,0) or 0 for k in ['productive_hours','setup_hours','wait_hours','rework_hours','support_hours'])
        if abs(parts-row['scheduled_hours'])>.0003 or min(row[k] for k in ['productive_hours','setup_hours','wait_hours','rework_hours'])<0: fail('attendance_balance',row['id'])
        expected={'productive_hours':sum(x[k] for k in ['生产','检验','包装']),'setup_hours':x['换型'],'rework_hours':x['返工']}
        if any(abs(row[k]*60-v)>.004 for k,v in expected.items()): fail('attendance_not_reconciled',row['id'])
    for key in daily:
        if key not in seen_days: fail('labor_without_attendance',str(key))
    # Route precedence is evaluated per branch batch then per SN; no join fanout.
    for u in d['units']:
        objs={'定子':u['stator_batch'],'转子':u['rotor_batch'],'整机':u['id']}
        for dep in dependencies[u['product_id']]:
            left=routes[dep['from_route_id']];right=routes[dep['to_route_id']]
            if right['process']=='包装': continue  # shipping evidence checked below
            aa=[r for r in opgroups[objs[left['branch']]] if r['process']==left['process']]
            bb=[r for r in opgroups[objs[right['branch']]] if r['process']==right['process']]
            if bb and (not aa or dt(min(r['started'] for r in bb))<dt(min(r['finished'] for r in aa))+timedelta(minutes=dep['lag_minutes'])): fail('route_precedence',u['id']+'|'+dep['id'])
    releases=group(d['releases'],'unit_id');packed=group(d['shipment_units'],'shipment_id')
    for s in d['shipments']:
        pp=[o for o in opgroups[s['id']] if o['process']=='包装']
        if not pp: fail('shipment_without_packing',s['id']);continue
        start=min(p['started'] for p in pp);finish=max(p['finished'] for p in pp)
        if finish>s['shipped']: fail('shipment_before_packing',s['id'])
        for su in packed[s['id']]:
            if not any(r['status']=='批准放行' and r['released']<=start for r in releases[su['unit_id']]): fail('packing_without_release',su['id'])
    # Material lineage and signed issues reconcile at WO / lot / unit.
    issued=Counter();linked=Counter();batch_index=idx(d['batches']);materials=idx(d['materials'])
    for row in d['inventory_movements']:
        if row['qty_signed']<0 and row.get('work_order_id'): issued[(row['work_order_id'],row['lot'],materials[row['material_id']]['unit'])]+=Decimal(str(-row['qty_signed']))
    per_sn=defaultdict(list)
    for row in d['genealogy']:
        if row['parent_type']=='材料批次': linked[(row['work_order_id'],row['parent_id'],row['unit'])]+=Decimal(str(row['qty']))
        elif row['child_type']=='整机': per_sn[row['child_id']].append(row)
    for key in set(issued)|set(linked):
        if abs(issued[key]-linked[key])>Decimal('.0001'): fail('material_genealogy_balance',str(key))
    for u in d['units']:
        links=per_sn[u['id']];expected=[u['stator_batch'],u['rotor_batch'],u.get('assembly_batch')]
        if sorted(r['parent_id'] for r in links)!=sorted(expected) or any(r['qty']!=1 or r['unit']!='件' for r in links): fail('unit_assembly_genealogy',u['id'])
    return {'passed':not findings,'checked_operations':len(operations),'checked_labor_entries':sum(map(len,labor.values())),'findings':{k:{'count':len(v),'examples':v[:8]} for k,v in findings.items()},'scope':'模拟导入数据：独立资源位、生产操作人员、排班、停机避让、技能、路线先后、放行包装、工时成本与材料谱系守恒。维修人员现场工时、真实节拍与产能不在本次验证范围。'}
