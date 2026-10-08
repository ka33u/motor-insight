"""Project existing trial inputs for inspection; never fit slots or change a plan."""
import hashlib
from pathlib import Path

VERSION = 'joint-candidate-evidence-v1'
NOTICE = ('本任务候选资料来自同一次试排输入，不代表当前剩余容量或可立即开工。'
          '批量符合只核对设备上限；资格交集沿用原人员计算。输入窗口尚未扣除不可用段、其他任务占用或裁剪到试排范围，'
          '资格窗口和人机窗口还需共同满足。首次/跨族换型假设不等于本任务实际试排换型。'
          '不重排、不推荐替换人机、不生成正式派工。')

def definition_hash():
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()

def pick(row, fields):
    return {field: row.get(field) for field in fields}

def build(context, task):
    result, parent = context['result'], context['parent']
    if result['state'] != 'trial' or not any(t['id'] == task['id'] and t == task for t in result['tasks']):
        raise ValueError('候选依据只读取当前试排中的原任务')
    base = parent['base']['tables']
    staff = parent['tables']
    resources = {r['id']: r for r in context['references']['production_resources']}
    qualifications = {r['id']: r for r in result['credentials']}
    refs = {('schedule_tasks', task['id'])}
    resource_rows, people_rows = [], []
    for option in sorted(base['schedule_options'], key=lambda r:r['id']):
        if option['task_id'] != task['id']:
            continue
        resource = resources[option['resource_id']]
        resource_rows.append(dict(
            **pick(option, ('id','task_id','resource_id','setup_minutes','basis')),
            process=resource['process'], capacity=resource['capacity'],
            max_batch_qty=resource['max_batch_qty'], task_qty=task['qty'],
            batch_fits=task['qty'] <= resource['max_batch_qty'],
            selected=option['id'] == task['option_id']))
        refs.update({('schedule_options',option['id']),('production_resources',resource['id'])})
    qualification_fields = ('employee_id','skill_id','process','registered_status','registered_approved','registered_expires',
                            'assumed_from','assumed_until','effective_from','effective_until','eligible','reason')
    for candidate in sorted(staff['crew_candidates'], key=lambda r:r['id']):
        if candidate['task_id'] != task['id']:
            continue
        qualification = qualifications[candidate['credential_id']]
        people_rows.append(dict(**pick(candidate, ('id','task_id','credential_id','basis')),
                                **pick(qualification,qualification_fields),
                                selected=candidate['id'] == task['candidate_id']))
        refs.update({('crew_candidates',candidate['id']),('crew_credentials',qualification['id']),
                     ('skills',qualification['skill_id']),('employees',qualification['employee_id'])})
    resource_ids = {r['resource_id'] for r in resource_rows}
    employee_ids = {r['employee_id'] for r in people_rows}
    windows = {}
    for dataset, rows, identity, allowed in (
        ('schedule_windows',base['schedule_windows'],'resource_id',resource_ids),
        ('schedule_blocks',base['schedule_blocks'],'resource_id',resource_ids),
        ('crew_windows',staff['crew_windows'],'employee_id',employee_ids),
        ('crew_blocks',staff['crew_blocks'],'employee_id',employee_ids),
    ):
        fields = ('id',identity,'started','finished','basis') + (('reason',) if dataset.endswith('blocks') else ())
        selected = [r for r in rows if r[identity] in allowed]
        windows[dataset] = [pick(r,fields) for r in sorted(selected,key=lambda r:(r[identity],r['started'],r['id']))]
        refs.update((dataset,r['id']) for r in selected)
    tasks = {r['id']:r for r in result['tasks']}
    related = {}
    for name in ('predecessors','root_tasks'):
        related[name] = [pick(tasks[key],('id','job_id','product_id','route_id','process','branch','state','started','finished','reason')) for key in task[name]]
        for key in task[name]:
            row = tasks[key]
            refs.update({('schedule_tasks',key),('schedule_jobs',row['job_id']),('products',row['product_id']),('routes',row['route_id'])})
    for edge in base['schedule_edges']:
        if edge['to_task_id'] == task['id']:
            refs.update({('schedule_edges',edge['id']),('route_dependencies',edge['dependency_id'])})
    evidence = dict(version=VERSION,task_id=task['id'],notice=NOTICE,
                    baseline=result['resource_study']['baseline'],horizon_end=result['resource_study']['horizon_end'],
                    resource_options=resource_rows,people_candidates=people_rows,**windows,**related)
    return evidence, refs
