"""Pinned remainder scheduler: explicit carry-in locks and task-level material pools."""
from collections import defaultdict
from datetime import timedelta
from decimal import Decimal
from . import finite_schedule as resource, crew_schedule as crew
from .joint_schedule_contract import number
from .joint_schedule import quantity
from .wip_trial import VERSION


def schedule(study,tables,joint,refs,progress,actual,demands,notice):
    parent=joint['parent'];base=parent['base'];original=parent['result']
    start=resource.time(original['resource_study']['baseline']);end=resource.time(original['resource_study']['horizon_end'])
    result=dict(state='trial',study=study,rule_version=VERSION,notice=notice,issues=[],summary=None,
        policy=original['policy'],policy_name=original['policy_name'],resource_study=original['resource_study'],
        tasks=[],jobs=[],resources=[],workers=[],demands=[],lots=[],reservations=[],balances=[])
    jobs={r['id']:r for r in base['tables']['schedule_jobs']};tasks={r['id']:r for r in base['tables']['schedule_tasks']}
    templates={r['id']:r for r in original['tasks']};credentials={r['id']:r for r in original['credentials']}
    rw,rb,ww,wb,before,after,options,candidates,by_task=(defaultdict(list) for _ in range(9))
    for ds,group,field in [('schedule_windows',rw,'resource_id'),('schedule_blocks',rb,'resource_id'),('schedule_options',options,'task_id')]:
        for r in base['tables'][ds]:group[r[field]].append(r)
    for ds,group,field in [('crew_windows',ww,'employee_id'),('crew_blocks',wb,'employee_id'),('crew_candidates',candidates,'task_id')]:
        for r in parent['tables'][ds]:group[r[field]].append(r)
    for edge in base['tables']['schedule_edges']:
        before[edge['to_task_id']].append(edge);after[edge['from_task_id']].append(edge)
    for d in demands:by_task[d['task_id']].append(d)
    rs={k:crew.spans(rows,start,end) for k,rows in rw.items()};ws={k:crew.spans(rows,start,end) for k,rows in ww.items()}
    rblocks={k:[(resource.time(r['started']),resource.time(r['finished']),r['id']) for r in rows] for k,rows in rb.items()}
    wblocks={k:[(resource.time(r['started']),resource.time(r['finished']),r['id']) for r in rows] for k,rows in wb.items()}
    lots={r['id']:dict(raw=r,usable=number(r['qty'])-number(r['unavailable_qty']) if r['status']=='可投入' else Decimal(0),
        remaining=number(r['qty'])-number(r['unavailable_qty']) if r['status']=='可投入' else Decimal(0)) for r in tables['wip_trial_supplies']}
    assigned={};reserved={};tails=defaultdict(lambda:start);worker_tails=defaultdict(lambda:start);families={}

    def eligible_lots(job,mid,unit):
        pool=[l for l in lots.values() if l['raw']['material_id']==mid and l['raw']['unit']==unit and l['remaining']>0 and
              l['raw'].get('owner_job_id') in (None,'',job) and resource.time(l['raw']['available_from'])<end]
        # Dedicated line-side stock first; it cannot serve another job.
        return sorted(pool,key=lambda l:(not bool(l['raw'].get('owner_job_id')),l['raw']['available_from'],l['raw']['id']))

    def material_ready(key,ready):
        grouped=defaultdict(Decimal);at=ready;shortages=[]
        for d in by_task[key]:grouped[d['material_id'],d['unit']]+=Decimal(d['calculated_qty'])
        for (mid,unit),amount in sorted(grouped.items()):
            if amount==0:continue
            total=Decimal(0);latest=ready;found=False
            for lot in eligible_lots(tasks[key]['job_id'],mid,unit):
                total+=lot['remaining'];latest=max(latest,resource.time(lot['raw']['available_from']))
                if total>=amount:found=True;break
            if not found:shortages.append(dict(material_id=mid,unit=unit,required_qty=quantity(amount),available_qty=quantity(total),shortage_qty=quantity(amount-total)))
            else:at=max(at,latest)
        return (None if shortages else at),shortages

    def allocate(key,at):
        for d in sorted(by_task[key],key=lambda r:r['id']):
            need=Decimal(d['calculated_qty'])
            for lot in eligible_lots(tasks[key]['job_id'],d['material_id'],d['unit']):
                if resource.time(lot['raw']['available_from'])>at:continue
                amount=min(need,lot['remaining'])
                if amount<=0:continue
                lot['remaining']-=amount;need-=amount
                result['reservations'].append(dict(demand_id=d['id'],task_id=key,job_id=tasks[key]['job_id'],supply_id=lot['raw']['id'],
                    material_id=d['material_id'],unit=d['unit'],qty=quantity(amount),reserved_at=resource.stamp(at),owner_job_id=lot['raw'].get('owner_job_id')))
                if need==0:break
            if need:raise ValueError('剩余任务预留未守恒，未返回试排')
            reserved[d['id']]=dict(task_id=key,reserved_at=resource.stamp(at))

    def windows(res,person,credential):
        out=[]
        for a,b,rid in rs.get(res,[]):
            for x,y,wid in ws.get(person,[]):
                left=max(a,x,resource.time(credential['effective_from']));right=min(b,y,resource.time(credential['effective_until']))
                if left<right:out.append((left,right,(rid,wid)))
        return out

    def template(key):
        p=progress[key];op=actual.get(key,{})
        r={k:v for k,v in templates[key].items() if k in ('id','job_id','product_id','route_id','process','branch','predecessors')}
        r.update(input_state=p['state'],progress_id=p['id'],operation_id=p.get('operation_id'),original_qty=tasks[key]['lot_qty'],
            completed_qty=p['completed_qty'],remaining_qty=p['remaining_qty'],process_minutes=float(number(p['remaining_minutes'])),
            recovery_minutes=float(number(p['recovery_minutes'])),actual_started=op.get('started'),actual_finished=op.get('finished'),
            actual_resource_id=op.get('resource_id'),actual_employee_id=op.get('employee_id'),
            state='blocked',reason='',root_tasks=[key],resource_id=None,employee_id=None,credential_id=None,option_id=None,candidate_id=None,
            started=None,process_started=None,finished=None,setup_minutes=None,dependency_ready=None,material_ready=None,
            demand_ids=[d['id'] for d in by_task[key]],shortages=[])
        return r

    # Historical tasks contribute predecessor times, never future capacity.
    for key,p in progress.items():
        if p['state']=='已完成':
            r=template(key);r.update(state='completed',reason='',root_tasks=[],finished=actual[key]['finished'],setup_minutes=0)
            assigned[key]=r
    held_resources=set();held_people=set()
    for key in sorted(k for k,p in progress.items() if p['state']=='加工中'):
        p=progress[key];res,person=p['resource_id'],p['employee_id'];r=template(key)
        if res in held_resources or person in held_people:result['issues'].append(key+'加工中人机锁定相互冲突');continue
        allowed=[o for o in options[key] if o['resource_id']==res and tasks[key]['lot_qty']<=refs['production_resources'][res]['max_batch_qty']]
        people=[(c,credentials[c['credential_id']]) for c in candidates[key] if credentials[c['credential_id']]['eligible'] and credentials[c['credential_id']]['employee_id']==person]
        length=timedelta(seconds=resource.seconds(p['remaining_minutes']));choices=[]
        for o in allowed:
            for c,credential in people:
                slot=crew.fit(start,length,windows(res,person,credential),rblocks.get(res,[])+wblocks.get(person,[]))
                if slot and slot[0]==start:choices.append((o['id'],c['id'],credential['id']))
        available,shortages=material_ready(key,start)
        if not choices:result['issues'].append(key+'原人机、资格或连续窗口不能从截止续作')
        if available!=start:result['issues'].append(key+'加工中剩余用料不能在截止时一次覆盖')
        if not choices or available!=start:continue
        finish=start+length;option,candidate,credential=min(choices)
        allocate(key,start);held_resources.add(res);held_people.add(person)
        r.update(state='carried',reason='',root_tasks=[],resource_id=res,employee_id=person,option_id=option,candidate_id=candidate,credential_id=credential,
            started=resource.stamp(start),process_started=resource.stamp(start),finished=resource.stamp(finish),setup_minutes=0,dependency_ready=resource.stamp(start),material_ready=resource.stamp(start))
        assigned[key]=r;tails[res]=finish;worker_tails[person]=finish;families[res]=jobs[tasks[key]['job_id']]['family']
    if result['issues']:
        # Carry-in failure invalidates the whole shared-pool premise; do not
        # expose provisional reservations from earlier locks as a usable plan.
        result.update(state='paused',tasks=[],reservations=[]);return result
    degree={k:len(before[k]) for k in tasks};queue=[k for k,n in degree.items() if n==0]
    def rank(key):
        j=jobs[tasks[key]['job_id']]
        return (j['due'],j['priority'],j['id'],key) if original['policy']=='due' else (j['priority'],j['due'],j['id'],key)
    while queue:
        queue.sort(key=rank);key=queue.pop(0);task=tasks[key];job=jobs[task['job_id']];p=progress[key]
        if key not in assigned:
            r=template(key)
            failed=[e['from_task_id'] for e in before[key] if assigned[e['from_task_id']]['state']=='blocked']
            ready=max([start,resource.time(job['released'])]+[resource.time(assigned[e['from_task_id']]['finished'])+timedelta(seconds=resource.seconds(e['lag_minutes'])) for e in before[key] if assigned[e['from_task_id']]['state']!='blocked'])
            available,shortages=material_ready(key,ready) if not failed else (None,[])
            allowed=[o for o in options[key] if p['remaining_qty']<=refs['production_resources'][o['resource_id']]['max_batch_qty']]
            people=[(c,credentials[c['credential_id']]) for c in candidates[key] if credentials[c['credential_id']]['eligible']]
            choices=[]
            if not failed and available is not None:
                for o in allowed:
                    res=o['resource_id'];setup=resource.seconds(p['recovery_minutes'])+(resource.seconds(o['setup_minutes']) if families.get(res)!=job['family'] else 0)
                    length=timedelta(seconds=setup+resource.seconds(p['remaining_minutes']))
                    for c,credential in people:
                        person=credential['employee_id'];slot=crew.fit(max(available,tails[res],worker_tails[person]),length,windows(res,person,credential),rblocks.get(res,[])+wblocks.get(person,[]))
                        if slot:
                            at,_=slot;choices.append((at+length,at,res,person,o['id'],c['id'],credential['id'],setup))
            r.update(dependency_ready=resource.stamp(ready),material_ready=resource.stamp(available) if available else None,shortages=shortages,
                root_tasks=sorted({root for k in failed for root in assigned[k]['root_tasks']}) or [key],
                reason='前序未排入：'+'、'.join(failed) if failed else '剩余物料不足' if shortages else '没有符合剩余批量的候选资源' if not allowed else '没有有效人员资格候选' if not people else '没有人机、资格与物料共同连续窗口')
            if choices:
                finish,at,res,person,option,candidate,credential,setup=min(choices);allocate(key,at)
                r.update(state='scheduled',reason='',root_tasks=[],resource_id=res,employee_id=person,option_id=option,candidate_id=candidate,credential_id=credential,
                    started=resource.stamp(at),process_started=resource.stamp(at+timedelta(seconds=setup)),finished=resource.stamp(finish),setup_minutes=setup/60)
                tails[res]=finish;worker_tails[person]=finish;families[res]=job['family']
            assigned[key]=r
        result['tasks'].append(assigned[key])
        for edge in after[key]:
            degree[edge['to_task_id']]-=1
            if degree[edge['to_task_id']]==0:queue.append(edge['to_task_id'])
    for job in sorted(jobs.values(),key=lambda j:j['id']):
        rows=[r for r in result['tasks'] if r['job_id']==job['id']];complete=all(r['state']!='blocked' for r in rows)
        finish=max(r['finished'] for r in rows) if complete else None
        result['jobs'].append(dict(id=job['id'],product_id=job['product_id'],qty=job['qty'],due=job['due'],finished=finish,
            state='late' if finish and finish>job['due'] else 'covered' if finish else 'blocked',
            actual_completed_tasks=sum(r['state']=='completed' for r in rows),remaining_tasks=sum(r['state']!='completed' for r in rows)))
    for name,field in [('resources','resource_id'),('workers','employee_id')]:
        for old in original[name]:
            rows=[r for r in result['tasks'] if r[field]==old['id'] and r['state'] in ('scheduled','carried')]
            busy=sum((resource.time(r['finished'])-resource.time(r['started'])).total_seconds()/60 for r in rows)
            result[name].append(dict(id=old['id'],available_minutes=old['available_minutes'],busy_minutes=busy,task_count=len(rows),
                load_percent=busy/old['available_minutes']*100 if old['available_minutes'] else None))
    for d in demands:
        allocation=reserved.get(d['id']);zero=Decimal(d['calculated_qty'])==0
        result['demands'].append(dict(d,required_qty=d['calculated_qty'],embedded_qty=quantity(number(d['embedded_qty'])),
            state='not_required' if zero else 'reserved' if allocation else 'unreserved',reserved_qty=d['calculated_qty'] if allocation else '0',reservation=allocation))
    for lot in sorted(lots.values(),key=lambda l:l['raw']['id']):
        result['lots'].append(dict(lot['raw'],usable_qty=quantity(lot['usable']),reserved_qty=quantity(lot['usable']-lot['remaining']),remaining_qty=quantity(lot['remaining'])))
    pairs={(d['material_id'],d['unit']) for d in demands}
    pairs|={(l['raw']['material_id'],l['raw']['unit']) for l in lots.values()}
    for mid,unit in sorted(pairs):
        needs=[d for d in result['demands'] if d['material_id']==mid and d['unit']==unit];pool=[l for l in result['lots'] if l['material_id']==mid and l['unit']==unit]
        total=lambda rr,k:quantity(sum((Decimal(str(r[k])) for r in rr),Decimal(0)))
        result['balances'].append(dict(material_id=mid,unit=unit,gross_remaining_qty=total(needs,'gross_remaining_qty'),embedded_qty=total(needs,'embedded_qty'),
            required_qty=total(needs,'required_qty'),reserved_qty=total(needs,'reserved_qty'),usable_qty=total(pool,'usable_qty'),remaining_qty=total(pool,'remaining_qty')))
    result['summary']=dict(tasks=len(tasks),historical_completed_tasks=sum(r['state']=='completed' for r in result['tasks']),
        carried_tasks=sum(r['state']=='carried' for r in result['tasks']),scheduled_tasks=sum(r['state']=='scheduled' for r in result['tasks']),
        blocked_tasks=sum(r['state']=='blocked' for r in result['tasks']),jobs=len(jobs),qty=sum(j['qty'] for j in jobs.values()),
        covered_jobs=sum(j['state']!='blocked' for j in result['jobs']),late_jobs=sum(j['state']=='late' for j in result['jobs']),
        blocked_jobs=sum(j['state']=='blocked' for j in result['jobs']))
    return result
