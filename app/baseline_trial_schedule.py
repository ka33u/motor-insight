"""Pinned v1 scheduling tail for job-specific frozen BOM requirements.

Intentionally independent of the published current-BOM calculator. Inputs have
passed baseline_trial's gates; never called directly by a public API. Demand
identity is the snapshot row plus job, not a product-wide BOM version. The
shared supply and human/resource pools are initialized once for the whole study.
"""
from collections import defaultdict
from datetime import timedelta
from decimal import Decimal
from . import finite_schedule as resource, crew_schedule as crew
from .joint_schedule import quantity
from .joint_schedule_contract import number


def schedule(study, demand_rows, supplies, parent, refs, notice):
    original, base = parent['result'], parent['base']
    policy = original['policy']
    start = resource.time(original['resource_study']['baseline'])
    end = resource.time(original['resource_study']['horizon_end'])
    jobs = {r['id']: r for r in base['tables']['schedule_jobs']}
    tasks = {r['id']: r for r in base['tables']['schedule_tasks']}
    demands = {r['id']: r for r in demand_rows}
    materials = refs['materials']
    result = dict(state='trial', study=study, crew_study=original['study'], resource_study=original['resource_study'],
                  policy=policy, policy_name=original['policy_name'], rule_version='FROZEN_BOM_SHARED_POOLS_1', notice=notice,
                  issues=[], credentials=original['credentials'], tasks=[], jobs=[], resources=[], workers=[], demands=[],
                  lots=[], reservations=[], balances=[], summary=None,
                  crew_reference=dict(summary=original['summary'], notice='同一人机输入的参考输出；差值不是因果影响。'))
    result['state'] = 'trial'
    lots = {lot['id']: dict(raw=lot, remaining=number(lot['qty']) - number(lot['unavailable_qty']) if lot['status'] == '可预留' else Decimal(0)) for lot in supplies.values()}
    for lot in lots.values():
        lot['usable'] = lot['remaining']
    ordered_lots = sorted(lots.values(), key=lambda l: (l['raw']['available_from'], l['raw']['id']))
    by_route = defaultdict(list)
    for demand in demand_rows:
        by_route[demand['job_id'], demand['route_id']].append(demand)
    reserved = {}

    def pending(task):
        return [d for d in by_route[task['job_id'], task['route_id']] if d['id'] not in reserved]

    def material_ready(needed, ready):
        grouped = defaultdict(Decimal)
        for d in needed:
            grouped[d['material_id'], d['unit']] += Decimal(d['calculated_qty'])
        at, absent = ready, []
        for (material_id, unit), amount in sorted(grouped.items()):
            candidates = [l for l in ordered_lots if l['raw']['material_id'] == material_id and l['raw']['unit'] == unit and l['remaining'] > 0 and resource.time(l['raw']['available_from']) < end]
            total, found = Decimal(0), None
            for lot in candidates:
                total += lot['remaining']
                if total >= amount:
                    found = max(ready, resource.time(lot['raw']['available_from']))
                    break
            if found is None:
                absent.append(dict(material_id=material_id, unit=unit, required_qty=quantity(amount), available_qty=quantity(total), shortage_qty=quantity(amount-total)))
            else:
                at = max(at, found)
        return (None if absent else at), absent

    def allocate(needed, task_id, at):
        # All materials were proven available before selecting a joint slot.
        for demand in sorted(needed, key=lambda d: d['id']):
            remaining = Decimal(demand['calculated_qty'])
            for lot in ordered_lots:
                raw = lot['raw']
                if raw['material_id'] != demand['material_id'] or raw['unit'] != demand['unit'] or resource.time(raw['available_from']) > at:
                    continue
                amount = min(remaining, lot['remaining'])
                if amount <= 0:
                    continue
                lot['remaining'] -= amount
                remaining -= amount
                result['reservations'].append(dict(demand_id=demand['id'], job_id=demand['job_id'], task_id=task_id, supply_id=raw['id'], material_id=raw['material_id'], unit=raw['unit'], qty=quantity(amount), reserved_at=resource.stamp(at), available_from=raw['available_from']))
                if remaining == 0:
                    break
            if remaining:
                raise ValueError('预留守恒校验失败，未生成试排结果')
            reserved[demand['id']] = dict(task_id=task_id, reserved_at=resource.stamp(at))

    rw, rb, ww, wb, before, after, options, candidates = (defaultdict(list) for _ in range(8))
    for ds, group, field in [('schedule_windows', rw, 'resource_id'), ('schedule_blocks', rb, 'resource_id'), ('schedule_options', options, 'task_id')]:
        for row in base['tables'][ds]:
            group[row[field]].append(row)
    for ds, group, field in [('crew_windows', ww, 'employee_id'), ('crew_blocks', wb, 'employee_id'), ('crew_candidates', candidates, 'task_id')]:
        for row in parent['tables'][ds]:
            group[row[field]].append(row)
    for edge in base['tables']['schedule_edges']:
        before[edge['to_task_id']].append(edge)
        after[edge['from_task_id']].append(edge)
    resource_spans = {k: crew.spans(rows, start, end) for k, rows in rw.items()}
    worker_spans = {k: crew.spans(rows, start, end) for k, rows in ww.items()}
    resource_blocks = {k: [(resource.time(w['started']), resource.time(w['finished']), w['id']) for w in rows] for k, rows in rb.items()}
    worker_blocks = {k: [(resource.time(w['started']), resource.time(w['finished']), w['id']) for w in rows] for k, rows in wb.items()}
    credentials = {c['id']: c for c in original['credentials']}
    tails, worker_tails = defaultdict(lambda: start), defaultdict(lambda: start)
    families, assigned = {}, {}
    degree = {k: len(before[k]) for k in tasks}
    queue = [k for k, n in degree.items() if n == 0]
    templates = {t['id']: t for t in original['tasks']}

    def rank(key):
        j = jobs[tasks[key]['job_id']]
        return (j['due'], j['priority'], j['id'], key) if policy == 'due' else (j['priority'], j['due'], j['id'], key)

    while queue:
        queue.sort(key=rank)
        key = queue.pop(0)
        task = tasks[key]
        job = jobs[task['job_id']]
        ready = max([start, resource.time(job['released'])] + [resource.time(assigned[e['from_task_id']]['finished']) + timedelta(seconds=resource.seconds(e['lag_minutes'])) for e in before[key] if assigned[e['from_task_id']]['state'] == 'scheduled'])
        failed = [e['from_task_id'] for e in before[key] if assigned[e['from_task_id']]['state'] != 'scheduled']
        roots = sorted({root for k in failed for root in assigned[k]['root_tasks']})
        needed = pending(task)
        # Later-dispatched portions can choose a different resource. They must
        # never start before the already committed whole-batch reservation.
        material_floor = max([ready] + [resource.time(reserved[d['id']]['reserved_at']) for d in by_route[task['job_id'], task['route_id']] if d['id'] in reserved])
        available, shortages = material_ready(needed, material_floor) if not failed else (None, [])
        duration = resource.seconds(Decimal(str(task['unit_minutes'])) * task['lot_qty'])
        allowed = [o for o in options[key] if task['lot_qty'] <= refs['production_resources'][o['resource_id']]['max_batch_qty']]
        people = [(c, credentials[c['credential_id']]) for c in candidates[key] if credentials[c['credential_id']]['eligible']]
        reason = ('前序未排入：' + '、'.join(failed) if failed else '共享物料在试排范围内不足：' + '、'.join(s['material_id'] for s in shortages) if shortages else
                  '没有符合批量的候选资源' if not allowed else '没有可用人员资格候选' if not people else '设备、人员、资格与物料没有共同连续可用窗口')
        choices = []
        if not failed and available is not None:
            for option in allowed:
                res = option['resource_id']
                setup = resource.seconds(option['setup_minutes']) if families.get(res) != job['family'] else 0
                length = timedelta(seconds=setup+duration)
                for candidate, credential in people:
                    employee = credential['employee_id']
                    windows = []
                    for a, b, resource_window in resource_spans.get(res, []):
                        for x, y, worker_window in worker_spans.get(employee, []):
                            left = max(a, x, resource.time(credential['effective_from']))
                            right = min(b, y, resource.time(credential['effective_until']))
                            if left < right:
                                windows.append((left, right, (resource_window, worker_window)))
                    slot = crew.fit(max(available, tails[res], worker_tails[employee]), length, windows, resource_blocks.get(res, []) + worker_blocks.get(employee, []))
                    if slot:
                        at, (resource_window, worker_window) = slot
                        choices.append((at+length, at, res, employee, option['id'], candidate['id'], credential['skill_id'], credential['id'], resource_window, worker_window, setup))
        # Retain identity and predecessor fields; discard the parent trial's timings.
        row = {k: v for k, v in templates[key].items() if k in ('id', 'job_id', 'product_id', 'route_id', 'process', 'branch', 'qty', 'predecessors')}
        row.update(state='blocked', reason=reason, root_tasks=roots or [key], dependency_ready=resource.stamp(ready), process_minutes=duration/60,
                   resource_id=None, employee_id=None, skill_id=None, credential_id=None, candidate_id=None, option_id=None, window_id=None, worker_window_id=None,
                   started=None, process_started=None, finished=None, setup_minutes=None, wait_minutes=None,
                   material_ready=resource.stamp(available) if available else None, material_readiness_delay_minutes=(available-ready).total_seconds()/60 if available else None,
                   demand_ids=[d['id'] for d in by_route[task['job_id'], task['route_id']]], new_reservation_ids=[], shortages=shortages)
        if choices:
            finish, at, res, employee, option, candidate, skill, credential, resource_window, worker_window, setup = min(choices)
            allocate(needed, key, at)
            row.update(state='scheduled', reason='', root_tasks=[], resource_id=res, employee_id=employee, skill_id=skill, credential_id=credential, candidate_id=candidate,
                       option_id=option, window_id=resource_window, worker_window_id=worker_window, started=resource.stamp(at), process_started=resource.stamp(at+timedelta(seconds=setup)),
                       finished=resource.stamp(finish), setup_minutes=setup/60, wait_minutes=(at-ready).total_seconds()/60, new_reservation_ids=[d['id'] for d in needed])
            tails[res], worker_tails[employee], families[res] = finish, finish, job['family']
        assigned[key] = row
        result['tasks'].append(row)
        for edge in after[key]:
            degree[edge['to_task_id']] -= 1
            if degree[edge['to_task_id']] == 0:
                queue.append(edge['to_task_id'])

    references = {j['id']: j for j in original['jobs']}
    for job in sorted(jobs.values(), key=lambda j: j['id']):
        rows = [t for t in result['tasks'] if t['job_id'] == job['id']]
        complete = all(t['state'] == 'scheduled' for t in rows)
        finish = max(t['finished'] for t in rows) if complete else None
        previous = references[job['id']]['finished']
        result['jobs'].append(dict(id=job['id'], product_id=job['product_id'], qty=job['qty'], priority=job['priority'], due=job['due'], finished=finish,
                                   state='late' if finish and finish > job['due'] else 'scheduled' if finish else 'blocked',
                                   lateness_minutes=max(0, (resource.time(finish)-resource.time(job['due'])).total_seconds()/60) if finish else None,
                                   crew_reference_finished=previous, completion_delta_minutes=(resource.time(finish)-resource.time(previous)).total_seconds()/60 if finish and previous else None,
                                   task_count=len(rows), scheduled_count=sum(t['state'] == 'scheduled' for t in rows)))
    for group, field in [('resources', 'resource_id'), ('workers', 'employee_id')]:
        for old in original[group]:
            rows = [t for t in result['tasks'] if t[field] == old['id']]
            busy = sum((resource.time(t['finished'])-resource.time(t['started'])).total_seconds()/60 for t in rows)
            result[group].append({**old, 'busy_minutes': busy, 'load_percent': 100*busy/old['available_minutes'] if old['available_minutes'] else None, 'task_count': len(rows)})
    for demand in demand_rows:
        allocation = reserved.get(demand['id'])
        result['demands'].append({**demand, 'required_qty': demand['calculated_qty'], 'state': 'reserved' if allocation else 'unreserved',
                                  'reserved_qty': demand['calculated_qty'] if allocation else '0', 'reservation': allocation})
    for lot in ordered_lots:
        raw = lot['raw']
        result['lots'].append({**raw, 'qty': quantity(number(raw['qty'])), 'unavailable_qty': quantity(number(raw['unavailable_qty'])),
                               'usable_qty': quantity(lot['usable']), 'excluded_qty': quantity(number(raw['qty'])-lot['usable']),
                               'reserved_qty': quantity(lot['usable']-lot['remaining']), 'remaining_qty': quantity(lot['remaining'])})
    pairs = {(d['material_id'], d['unit']) for d in demand_rows} | {(s['material_id'], s['unit']) for s in supplies.values()}
    for material_id, unit in sorted(pairs):
        needs = [d for d in result['demands'] if d['material_id'] == material_id and d['unit'] == unit]
        stock = [s for s in result['lots'] if s['material_id'] == material_id and s['unit'] == unit]
        total = lambda rows, field: sum((Decimal(r[field]) for r in rows), Decimal(0))
        usable = total([s for s in stock if resource.time(s['available_from']) < end], 'usable_qty')
        required = total(needs, 'required_qty')
        result['balances'].append(dict(material_id=material_id, material_name=materials[material_id]['name'], unit=unit,
                                      required_qty=quantity(required), horizon_usable_qty=quantity(usable), reserved_qty=quantity(total(needs, 'reserved_qty')),
                                      total_excluded_qty=quantity(total(stock, 'excluded_qty')), total_remaining_qty=quantity(total(stock, 'remaining_qty')),
                                      initial_supply_gap_qty=quantity(max(Decimal(0), required-usable))))
    result['summary'] = dict(tasks=len(tasks), scheduled_tasks=sum(t['state'] == 'scheduled' for t in result['tasks']), blocked_tasks=sum(t['state'] == 'blocked' for t in result['tasks']),
                             jobs=len(jobs), qty=sum(j['qty'] for j in jobs.values()), complete_jobs=sum(j['state'] != 'blocked' for j in result['jobs']), late_jobs=sum(j['state'] == 'late' for j in result['jobs']),
                             blocked_jobs=sum(j['state'] == 'blocked' for j in result['jobs']), demands=len(demands), reserved_demands=len(reserved),
                             direct_shortage_tasks=sum(bool(t['shortages']) for t in result['tasks']), material_delayed_tasks=sum((t['material_readiness_delay_minutes'] or 0) > 0 and t['state'] == 'scheduled' for t in result['tasks']))
    return result
