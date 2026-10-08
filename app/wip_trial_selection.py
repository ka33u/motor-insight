"""Exact task-list intersection of an already validated whole WIP trial."""
import hashlib
from pathlib import Path
from . import finite_schedule

VERSION='WIP_TASK_SELECTION_1'
STATES=('completed','carried','scheduled','blocked')
NOTICE=('筛选只选择原完整方案的任务，不重新安排人机、计算工单完工或分摊共享物料。'
        '同一任务仅列一次，原首阻断集合完整保留；工单台数和完成时间来自原完整工单，不能跨工序相加为产量。'
        'CSV是筛选清单及来源索引；离线重算须使用JSON内的完整方案输入。')


def definition_hash():return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def normalize(filters):
    if set(filters)-{'job','state','root'}:raise ValueError('任务筛选字段无效')
    out={k:filters.get(k,'') for k in ('job','state','root')}
    if any(not isinstance(v,str) or len(v)>200 for v in out.values()):raise ValueError('任务筛选值无效或过长')
    if out['state'] not in ('',*STATES):raise ValueError('任务状态无效')
    return out


def select(result,links,filters):
    filters=normalize(filters)
    if result['state']!='trial' or result['rule_version']!='WIP_REMAINDER_SHARED_POOLS_1':raise ValueError('当前完整在制方案未形成可筛选的试排结果')
    tasks=result['tasks'];jobs={r['id']:r for r in result['jobs']};task_ids={r['id']:r for r in tasks}
    if filters['job'] and filters['job'] not in jobs:raise ValueError('工单批次不属于当前方案')
    root=filters['root']
    if root:
        candidate=task_ids.get(root)
        if not candidate or candidate['state']!='blocked' or candidate['root_tasks']!=[root]:raise ValueError('首阻断不属于当前原始阻断点')
    selected=[r for r in tasks if (not filters['job'] or r['job_id']==filters['job']) and (not filters['state'] or r['state']==filters['state']) and (not root or root in r['root_tasks'])]
    chosen_jobs={r['job_id'] for r in selected};counts={state:sum(r['state']==state for r in selected) for state in STATES}
    out=dict(version=VERSION,definition_hash=definition_hash(),filters=filters,task_ids=[r['id'] for r in selected],selected_count=len(selected),whole_task_count=len(tasks),
        state_counts=counts,selected_tasks=selected,work_orders=[r for r in links if r['job_id'] in chosen_jobs],whole_job_results=[r for r in result['jobs'] if r['id'] in chosen_jobs],notice=NOTICE)
    if len(out['work_orders'])!=len(chosen_jobs) or len({r['job_id'] for r in out['work_orders']})!=len(chosen_jobs):raise ValueError('筛选任务的原工单映射不完整')
    out['selection_hash']=finite_schedule.digest(out)
    return out
