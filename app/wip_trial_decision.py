"""Explain one dispatch turn without changing the pinned scheduling result."""
from collections import defaultdict
from datetime import timedelta
import hashlib
from pathlib import Path
from . import finite_schedule as finite, crew_schedule as crew, wip_trial
from .joint_schedule import quantity

VERSION='WIP_DISPATCH_EVIDENCE_1'
MAX_PAIRS=1000
MAX_WINDOW_WORK=200000
NOTICE=('这是轮到该任务时的候选比较，物料余额和人机尾部均在该任务预留之前。'
        '单容量、连续窗口、保守尾部追加，不回填空档；可行未选只表示排序靠后，不表示全局最优或应替换人机。'
        '资格仅来自模拟声明及登记日期，不代表真实上岗批准。')
RANK=['完成时点','开始时点','资源编号','人员编号','资源候选编号','人员候选编号','资格编号','准备秒数']


def definition_hash():
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def build(context,task_id,as_of):
    result=context['result'];tasks={r['id']:r for r in result['tasks']}
    if result['state']!='trial' or task_id not in tasks:raise ValueError('没有可解释的当前试排任务')
    task=tasks[task_id]
    related_ids=set(task['predecessors'])|set(task['root_tasks'])
    if not related_ids<=tasks.keys():raise ValueError('任务关联依据不完整')
    out=dict(version=VERSION,definition_hash=definition_hash(),task_id=task_id,notice=NOTICE,
        state='explained',issues=[],rank_fields=['资源候选编号','人员候选编号','资格编号'] if task['state']=='carried' else RANK,
        pairs=[],lots=[],related_tasks=[tasks[k] for k in sorted(related_ids)],pair_count=0,
        dependency_ready=task['dependency_ready'],material_ready=task['material_ready'],failed_predecessors=[],predecessors=task['predecessors'],root_tasks=task['root_tasks'])
    if task['state']=='completed':
        out.update(state='historical',notice='历史完成任务只保留原报工，不重新选择未来人机，也不占用未来产能。')
        return out
    joint=context['joint_context'];parent=joint['parent'];base=parent['base']
    options=[r for r in base['tables']['schedule_options'] if r['task_id']==task_id]
    candidates=[r for r in parent['tables']['crew_candidates'] if r['task_id']==task_id]
    out['pair_count']=len(options)*len(candidates)
    def unavailable(message):
        out.update(state='unavailable',issues=[message],pairs=[],lots=[])
        return out
    if out['pair_count']>MAX_PAIRS:return unavailable('候选组合超过1000，未截断解释；原试排结果仍保留。')
    # Bound intersection and fit work before replay/matrix allocation.
    rw=defaultdict(int);ww=defaultdict(int);blocks=0
    for r in base['tables']['schedule_windows']:rw[r['resource_id']]+=1
    for r in parent['tables']['crew_windows']:ww[r['employee_id']]+=1
    blocks=len(base['tables']['schedule_blocks'])+len(parent['tables']['crew_blocks'])
    credentials={r['id']:r for r in parent['result']['credentials']}
    work=sum(rw[o['resource_id']]*ww[credentials[c['credential_id']]['employee_id']]*(1+blocks) for o in options for c in candidates)
    if work>MAX_WINDOW_WORK:return unavailable('窗口交集核对超过受控规模，未截断解释；原试排结果仍保留。')
    refs=defaultdict(dict,{ds:{r['id']:r for r in rows} for ds,rows in context['references'].items()})
    refs['wip_trial_studies']={r['id']:r for r in context['version_history']}
    observations={task_id:None}
    replay=wip_trial.analyze(result['study'],context['tables'],joint,refs,as_of,observations=observations)
    if replay!=result:return unavailable('解释重算与当前完整结果不一致，已停止解释，请重新读取。')
    observed=observations[task_id]
    if observed is None:return unavailable('没有取得该任务派序前状态，已停止解释。')
    baseline=finite.time(result['resource_study']['baseline']);horizon=finite.time(result['resource_study']['horizon_end'])
    carried=observed['carried'];failed=observed['failed'];available=observed['available']
    out['failed_predecessors']=failed
    job=next(r for r in base['tables']['schedule_jobs'] if r['id']==task['job_id'])
    progress=next(r for r in context['tables']['wip_trial_tasks'] if r['task_id']==task_id)
    choices=[]
    def stamp(value):return finite.stamp(value) if value is not None else None
    def tail_tasks(field,key,at):
        rows=[r for r in observed['assigned'].values() if r['state'] in ('carried','scheduled') and r[field]==key and finite.time(r['finished'])==at]
        for row in rows:related_ids.add(row['id'])
        return [r['id'] for r in sorted(rows,key=lambda r:r['id'])]
    for option in sorted(options,key=lambda r:r['id']):
        res=option['resource_id'];rt=observed['tails'].get(res,baseline)
        for candidate in sorted(candidates,key=lambda r:r['id']):
            credential=observed['credentials'][candidate['credential_id']];person=credential['employee_id'];wt=observed['worker_tails'].get(person,baseline)
            capacity=refs['production_resources'][res]['max_batch_qty'];qty=task['original_qty'] if carried else task['remaining_qty']
            reasons=[]
            if carried and (res!=progress['resource_id'] or person!=progress['employee_id']):reasons.append('加工中仅允许原锁定人机')
            if qty>capacity:reasons.append('批量超过资源上限')
            if not credential['eligible']:reasons.append('资格无效：'+credential['reason'])
            if failed:reasons.append('前序未排入：'+'、'.join(failed))
            elif available is None:reasons.append('剩余物料不足，未计算连续窗口')
            setup=0 if carried else finite.seconds(progress['recovery_minutes'])+(finite.seconds(option['setup_minutes']) if observed['families'].get(res)!=job['family'] else 0)
            length=timedelta(seconds=setup+finite.seconds(progress['remaining_minutes']))
            windows=[]
            if credential['eligible']:
                for a,b,rid in observed['resource_spans'].get(res,[]):
                    for x,y,wid in observed['worker_spans'].get(person,[]):
                        left=max(a,x,finite.time(credential['effective_from']));right=min(b,y,finite.time(credential['effective_until']))
                        if left<right:windows.append((left,right,(rid,wid)))
            blocked=observed['resource_blocks'].get(res,[])+observed['worker_blocks'].get(person,[])
            earliest=baseline if carried else max(available,rt,wt) if available is not None and not failed else None
            if reasons:earliest=None
            slot=crew.fit(earliest,length,windows,blocked) if not reasons else None
            if slot and carried and slot[0]!=baseline:slot=None
            chosen=None
            if slot:
                at=slot[0];finish=at+length
                chosen=(option['id'],candidate['id'],credential['id']) if carried else (finish,at,res,person,option['id'],candidate['id'],credential['id'],setup)
                choices.append(chosen)
            elif not reasons:reasons.append('没有共同连续窗口从截止续作' if carried else '尾部之后没有共同连续窗口')
            selected=(task['option_id'],task['candidate_id'],task['credential_id'])==(option['id'],candidate['id'],credential['id'])
            out['pairs'].append(dict(option_id=option['id'],candidate_id=candidate['id'],credential_id=credential['id'],resource_id=res,employee_id=person,
                checked_qty=qty,capacity_qty=capacity,capacity_basis='原处理批量' if carried else '剩余批量',credential=credential,
                resource_tail=stamp(rt),worker_tail=stamp(wt),resource_tail_tasks=tail_tasks('resource_id',res,rt),worker_tail_tasks=tail_tasks('employee_id',person,wt),
                previous_family=observed['families'].get(res),task_family=job['family'],setup_minutes=setup/60,recovery_minutes=0 if carried else task['recovery_minutes'],
                earliest=stamp(earliest),started=stamp(slot[0]) if slot else None,finished=stamp(slot[0]+length) if slot else None,
                selected=selected,status='selected' if selected else 'feasible' if slot else 'excluded',reasons=reasons,
                rank=[stamp(v) if hasattr(v,'isoformat') else v for v in chosen] if chosen else None,
                windows=[dict(started=stamp(a),finished=stamp(b),resource_window_id=ids[0],worker_window_id=ids[1]) for a,b,ids in sorted(windows)],
                blocks=[dict(started=stamp(a),finished=stamp(b),id=key) for a,b,key in sorted(blocked)]))
    if sorted(choices)!=sorted(observed['choices']):return unavailable('候选比较与派序时可行组合不一致，已停止解释。')
    selected=[p for p in out['pairs'] if p['selected']]
    if choices:
        best=min(choices)
        expected=(best[0],best[1],best[2]) if carried else (best[4],best[5],best[6])
        if len(selected)!=1 or (task['option_id'],task['candidate_id'],task['credential_id'])!=expected:return unavailable('候选排序与原选中人机不一致，已停止解释。')
        if (selected[0]['started'],selected[0]['finished'],selected[0]['setup_minutes'])!=(task['started'],task['finished'],task['setup_minutes']):return unavailable('候选时间与原试排不一致，已停止解释。')
    elif selected or task['state']!='blocked':return unavailable('候选可行性与任务状态不一致，已停止解释。')
    needed={(r['material_id'],r['unit']) for r in result['demands'] if r['task_id']==task_id}
    for key,lot in sorted(observed['lots'].items()):
        raw=lot['raw']
        if (raw['material_id'],raw['unit']) not in needed:continue
        reasons=[]
        if raw['status']!='可投入':reasons.append('隔离')
        if lot['remaining']<=0:reasons.append('派序到此任务时已无余量')
        if raw.get('owner_job_id') not in (None,'',task['job_id']):reasons.append('其他批次专属')
        if finite.time(raw['available_from'])>=horizon:reasons.append('可用时点不在试排范围内')
        out['lots'].append(dict(id=key,material_id=raw['material_id'],unit=raw['unit'],owner_job_id=raw.get('owner_job_id'),available_from=raw['available_from'],
            usable_qty=quantity(lot['usable']),remaining_before_task=quantity(lot['remaining']),eligible=not reasons,reasons=reasons))
    out['related_tasks']=[tasks[k] for k in sorted(related_ids)]
    return out
