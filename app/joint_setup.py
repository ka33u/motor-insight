"""Read setup transitions and delivery tradeoffs from two existing trial outputs.

Pure projection: no fitting, scheduling, new resource capacity or database access.
"""
import hashlib
from collections import defaultdict
from datetime import datetime
from decimal import Decimal, ROUND_CEILING
from pathlib import Path
from . import joint_comparison as comparison

VERSION = 'joint-setup-reading-v1'
NOTICE = ('准备按原设备时序拆为首次上机和后续跨族；同族延续为零准备。'
          '0分钟首次或跨族仍计事件，不等于没有族切换。差值为优先级策略减应完成时间策略。'
          '准备差值仅比较非空且相同的已排任务集合；完整方案结束须全部任务排入。'
          '晚交按已完成批次与内部应完成时点核对，未排完另列；不是订单OTIF、效率或因果归责。')
KINDS = ('initial', 'change', 'same')


def definition_hash():
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def need(condition, message):
    if not condition:
        raise ValueError('换型核对：'+message)


def number(value):
    need(type(value) in (int, float), '分钟须为有限非负数')
    result = Decimal(str(value))
    need(result.is_finite() and result >= 0, '分钟须为有限非负数')
    return result


def time(value):
    need(isinstance(value, str), '时点缺失')
    try:
        result = datetime.fromisoformat(value)
    except ValueError:
        raise ValueError('换型核对：时点无效') from None
    need(result.tzinfo is None, '时点须沿用本地业务墙钟时间')
    return result


def index(rows):
    out = {}
    for row in rows:
        identity = row.get('id')
        need(isinstance(identity, str) and identity and identity not in out, '身份缺失或重复')
        out[identity] = row
    return out


def totals(events):
    out = dict(scheduled_tasks=len(events), setup_minutes=sum(e['setup_seconds'] for e in events)/60)
    for kind in KINDS:
        rows = [e for e in events if e['kind'] == kind]
        out[kind+'_tasks'] = len(rows)
        out[kind+'_minutes'] = sum(e['setup_seconds'] for e in rows)/60
    return out


def policy_result(result, inputs):
    jobs, tasks, options = [index(inputs[k]) for k in ('schedule_jobs', 'schedule_tasks', 'schedule_options')]
    actual_jobs, actual_tasks = index(result['jobs']), index(result['tasks'])
    need(jobs.keys() == actual_jobs.keys() and tasks.keys() == actual_tasks.keys(), '输入与结果范围不一致')
    need(result['resource_study']['job_count'] == len(jobs) and result['resource_study']['task_count'] == len(tasks), '声明范围不一致')
    start, end = [time(result['resource_study'][k]) for k in ('baseline', 'horizon_end')]
    need(start < end, '方案时间范围无效')
    for key, job in jobs.items():
        need(isinstance(job.get('family'), str) and job['family'].strip(), '批次换型族缺失')
        need(job['study_id'] == result['resource_study']['id'], '批次跨方案')
        need(all(job[k] == actual_jobs[key][k] for k in ('product_id', 'qty', 'priority', 'due', 'task_count')), '原批次身份或条件不同')
    by_resource, by_worker = defaultdict(list), defaultdict(list)
    for task in actual_tasks.values():
        source = tasks[task['id']]
        need(source['job_id'] in jobs, '任务批次不存在')
        need((task['job_id'], task['route_id'], task['qty']) == (source['job_id'], source['route_id'], source['lot_qty']), '任务身份不同')
        need(task['state'] in ('scheduled', 'blocked'), '任务状态无效')
        if task['state'] == 'blocked':
            need(all(task.get(k) is None for k in ('started', 'process_started', 'finished', 'setup_minutes', 'resource_id', 'employee_id', 'option_id')), '未排任务不能有准备或安排')
            continue
        need(isinstance(task['resource_id'], str) and task['resource_id'] and isinstance(task['employee_id'], str) and task['employee_id'], '人机身份缺失')
        option = options.get(task['option_id'])
        need(option and (option['task_id'], option['resource_id']) == (task['id'], task['resource_id']), '选中候选与任务人机不符')
        a, b, c = [time(task[k]) for k in ('started', 'process_started', 'finished')]
        need(start <= a <= b < c <= end, '任务时点越界或次序无效')
        need(abs(float(number(task['setup_minutes'])*60)-(b-a).total_seconds()) < 1e-6, '准备分钟与时点不同')
        need(abs(float(number(task['process_minutes'])*60)-(c-b).total_seconds()) < 1e-6, '加工分钟与时点不同')
        by_resource[task['resource_id']].append(task)
        by_worker[task['employee_id']].append(task)
    for groups in (by_resource, by_worker):
        for rows in groups.values():
            ordered = sorted(rows, key=lambda t: (t['started'], t['id']))
            need(all(time(a['finished']) <= time(b['started']) for a, b in zip(ordered, ordered[1:])), '同一设备或工号占用重叠')
    events = []
    for resource, rows in sorted(by_resource.items()):
        previous = None
        for task in sorted(rows, key=lambda t: (t['started'], t['id'])):
            family = jobs[task['job_id']]['family']
            prior_family = jobs[previous['job_id']]['family'] if previous else None
            kind = 'initial' if previous is None else 'same' if family == prior_family else 'change'
            minutes = number(options[task['option_id']]['setup_minutes'])
            seconds = int((minutes*60).to_integral_value(rounding=ROUND_CEILING)) if kind != 'same' else 0
            need((time(task['process_started'])-time(task['started'])).total_seconds() == seconds, '原准备与候选/换型族规则不符')
            events.append(dict(task_id=task['id'], job_id=task['job_id'], resource_id=resource, employee_id=task['employee_id'],
                option_id=task['option_id'], previous_task_id=previous['id'] if previous else None,
                previous_job_id=previous['job_id'] if previous else None, previous_family=prior_family, family=family,
                kind=kind, setup_seconds=seconds, setup_minutes=seconds/60, declared_setup_minutes=float(minutes),
                started=task['started'], process_started=task['process_started'], finished=task['finished']))
            previous = task
    complete, late = 0, 0
    for key, job in actual_jobs.items():
        rows = [t for t in actual_tasks.values() if t['job_id'] == key]
        need(len(rows) == jobs[key]['task_count'], '批次任务数不一致')
        all_done = bool(rows) and all(t['state'] == 'scheduled' for t in rows)
        finish = max((t['finished'] for t in rows), key=time) if all_done else None
        lateness = max(0, (time(finish)-time(job['due'])).total_seconds()/60) if all_done else None
        state = 'late' if lateness else 'scheduled' if all_done else 'blocked'
        need((job['finished'], job['state']) == (finish, state), '批次完成时点或状态不一致')
        need(job['lateness_minutes'] is None if lateness is None else abs(job['lateness_minutes']-lateness) < 1e-8, '批次晚交分钟不一致')
        complete += all_done
        late += bool(lateness)
    summary = result['summary']
    for field, value in dict(tasks=len(tasks), scheduled_tasks=len(events), blocked_tasks=len(tasks)-len(events),
            jobs=len(jobs), complete_jobs=complete, blocked_jobs=len(jobs)-complete, late_jobs=late,
            qty=sum(j['qty'] for j in jobs.values())).items():
        need(summary[field] == value, '完整摘要不一致：'+field)
    report = totals(events)
    report.update(tasks=len(tasks), blocked_tasks=len(tasks)-len(events), complete_jobs=complete, blocked_jobs=len(jobs)-complete,
                  late_jobs=late, finished=max((e['finished'] for e in events), key=time) if events and len(events) == len(tasks) else None)
    return report, events


def build(left, right, inputs):
    need(left['policy'] == 'due' and right['policy'] == 'priority', '策略顺序无效')
    need(all(left[k] == right[k] for k in ('study', 'crew_study', 'resource_study', 'rule_version')), '方案、范围或版本不同')
    out = dict(version=VERSION, notice=NOTICE, state='paused', columns={}, resources=[], events=[], summary=None)
    if left['state'] != 'trial' or right['state'] != 'trial':
        return out
    list(comparison.pairs(left['jobs'], right['jobs'], fixed=comparison.JOB_FIELDS))
    list(comparison.pairs(left['tasks'], right['tasks'], fixed=comparison.TASK_FIELDS))
    columns, events = {}, {}
    for policy, result in [('due', left), ('priority', right)]:
        columns[policy], events[policy] = policy_result(result, inputs)
    ids = [{e['task_id'] for e in events[p]} for p in ('due', 'priority')]
    comparable = bool(ids[0]) and ids[0] == ids[1]
    a, b = columns['due'], columns['priority']
    resources = sorted({e['resource_id'] for rows in events.values() for e in rows})
    for key in resources:
        columns_for_resource = {p: totals([e for e in events[p] if e['resource_id'] == key]) for p in events}
        out['resources'].append(dict(id=key, **columns_for_resource))
    out.update(state='ready', columns=columns, events=[dict(policy=p, **e) for p in ('due', 'priority') for e in events[p]],
        summary=dict(tasks=len(left['tasks']), same_scheduled_scope=comparable,
            setup_delta_minutes=b['setup_minutes']-a['setup_minutes'] if comparable else None,
            setup_comparison_reason='' if comparable else '两列均未排入任务' if not ids[0] and not ids[1] else '两列已排任务范围不同',
            finish_delta_minutes=(time(b['finished'])-time(a['finished'])).total_seconds()/60 if a['finished'] and b['finished'] else None,
            late_jobs_delta=b['late_jobs']-a['late_jobs'] if a['finished'] and b['finished'] else None,
            chart_max_minutes=max(a['setup_minutes'], b['setup_minutes'])))
    return out
