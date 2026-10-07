"""Deterministic whole-batch material reservations with people/resource capacity.

Independent future assumptions; never writes inventory, orders or dispatches.
Decimal arithmetic is retained until quantities are serialized as decimal strings.
"""
import hashlib
from collections import defaultdict
from datetime import timedelta, date
from decimal import Decimal, ROUND_CEILING
from pathlib import Path
from . import finite_schedule as resource, crew_schedule as crew
from .joint_schedule_schema import DATASETS
from .joint_schedule_contract import issues as row_issues, number

VERSION = 'MATERIAL_CREW_RESOURCE_APPEND_1'
MAX_ROWS = 5000
NOTICE = ('独立合成未来假设；按当前产品BOM版本及批量向上取整需求，在绑定工序的首个成功排入任务准备开始时，'
          '一次预留整批需求。共享供给按可用时间、批次号FIFO；按派序优先预留，允许先占未来物料，后续任务不抢占。'
          '每任务一名操作员覆盖完整换型和加工；设备与人员容量均为1，尾部追加、不回填。'
          '未排完批次的已有预留保留；没有过期、替代料、单位换算、模具约束或自动释放。'
          '不代表库存实绩、采购承诺、最优计划或正式派工，不写回业务。')


def rule_hash():
    names = ('joint_schedule.py', 'joint_schedule_data.py', 'joint_schedule_contract.py', 'joint_schedule_schema.py')
    return resource.digest(dict(crew_rules=crew.rule_hash(), joint={n: hashlib.sha256(Path(__file__).with_name(n).read_bytes()).hexdigest() for n in names}))


def quantity(value):
    return format(value.normalize(), 'f') if value else '0'


def requirement(qty, bom_qty, scrap, quantum):
    step = number(quantum, True)
    return (number(qty, True) * number(bom_qty, True) * (1 + number(scrap)) / step).to_integral_value(rounding=ROUND_CEILING) * step


def analyze(study, tables, parent, refs):
    original = parent['result']
    base = parent['base']
    policy = original['policy']
    problems = []

    def issue(message):
        if message not in problems:
            problems.append(message)

    for ds in DATASETS:
        for row in [study] if ds == 'joint_studies' else tables.get(ds, []):
            for error in row_issues(ds, row):
                issue(row['id'] + '：' + error['message'])
    for field, ds in [('binding_count', 'joint_bindings'), ('demand_count', 'joint_demands'), ('supply_count', 'joint_supplies')]:
        if study.get(field) != len(tables.get(ds, [])):
            issue('方案声明数量不一致：' + field)
    if any(len(rows) > MAX_ROWS for rows in tables.values()):
        issue('物料输入超过受控规模，不截断计算')
    if original['state'] != 'trial':
        problems.extend('人员资源方案：' + v for v in original['issues'])
    if study['crew_study_id'] != original['study']['id']:
        issue('人员资源方案身份不一致')
    if study['owner_id'] not in refs['employees']:
        issue('负责人员来源缺失')
    result = dict(state='paused', study=study, crew_study=original['study'], resource_study=original['resource_study'],
                  policy=policy, policy_name=original['policy_name'], rule_version=VERSION, notice=NOTICE, issues=problems,
                  credentials=original['credentials'], tasks=[], jobs=[], resources=[], workers=[], demands=[], lots=[], reservations=[], balances=[], summary=None,
                  crew_reference=dict(summary=original['summary'], notice='相同设备与人员输入的参考试排；批次差值来自两个启发式输出，不是物料影响的因果估计。'))
    if problems:
        return result

    start = resource.time(result['resource_study']['baseline'])
    end = resource.time(result['resource_study']['horizon_end'])

    def index(rows, label):
        indexed = {row['id']: row for row in rows}
        if len(indexed) != len(rows):
            issue(label + '编号重复')
        return indexed

    jobs = index(base['tables']['schedule_jobs'], '批次')
    tasks = index(base['tables']['schedule_tasks'], '任务')
    bindings = index(tables['joint_bindings'], '绑定')
    demands = index(tables['joint_demands'], '需求')
    supplies = index(tables['joint_supplies'], '供给')
    products, routes, materials = refs['products'], refs['routes'], refs['materials']
    current_bom = {}
    selected_products = {job['product_id'] for job in jobs.values()}
    for product_id in sorted(selected_products):
        product = products.get(product_id)
        if not product or not product.get('bom_version'):
            issue(product_id + '：当前产品BOM版本来源缺失')
            continue
        lines = [b for b in refs['bom'].values() if b['product_id'] == product_id and b['version'] == product['bom_version']]
        if not lines:
            issue(product_id + '：当前BOM没有用料行')
        for b in lines:
            try:
                effective = date.fromisoformat(b['effective'])
                if effective.isoformat() != b['effective'] or effective > start.date():
                    raise ValueError()
                number(b['qty'], True)
                number(b['scrap_allowance'])
            except (KeyError, ValueError, TypeError):
                issue(b['id'] + '：BOM数量、损耗或生效日期无效')
            if b['material_id'] not in materials:
                issue(b['id'] + '：物料档案缺失')
            current_bom[b['id']] = b

    mapped = {}
    for b in bindings.values():
        bom, route = current_bom.get(b['bom_id']), routes.get(b['route_id'])
        if b['study_id'] != study['id'] or not bom or not route:
            issue(b['id'] + '：绑定跨方案、当前BOM或工序缺失')
            continue
        if b['bom_id'] in mapped:
            issue(b['id'] + '：同一BOM行重复绑定')
        mapped[b['bom_id']] = b
        branch = '整机' if bom['assembly_level'] == '装配件包' else bom['assembly_level']
        if route['product_id'] != bom['product_id'] or route['branch'] != branch:
            issue(b['id'] + '：BOM产品或分支与绑定工序不符')
        for job in jobs.values():
            if job['product_id'] == bom['product_id'] and (route['version'] != job['route_version'] or not any(t['job_id'] == job['id'] and t['route_id'] == route['id'] for t in tasks.values())):
                issue(b['id'] + '：该批次路线版本没有绑定工序')
        material = materials.get(bom['material_id'])
        if material and material['unit'] == '件' and number(b['quantum']) % 1:
            issue(b['id'] + '：计件物料取整步长须为整数')
    missing = sorted(set(current_bom) - set(mapped))
    if missing:
        issue('当前BOM用料未完整绑定：' + '、'.join(missing))

    expected = {(j['id'], mapped[b['id']]['id']) for j in jobs.values() for b in current_bom.values() if b['product_id'] == j['product_id'] and b['id'] in mapped}
    actual, demand_rows = set(), []
    for d in demands.values():
        job, binding = jobs.get(d['job_id']), bindings.get(d['binding_id'])
        bom = current_bom.get(binding['bom_id']) if binding else None
        pair = (d['job_id'], d['binding_id'])
        if pair in actual:
            issue(d['id'] + '：批次用料重复')
        actual.add(pair)
        if d['study_id'] != study['id'] or not job or not bom or bom['product_id'] != job['product_id']:
            issue(d['id'] + '：需求跨方案、批次或BOM产品不符')
            continue
        material = materials.get(bom['material_id'])
        if not material:
            continue
        if d['unit'] != material['unit']:
            issue(d['id'] + '：需求单位与物料档案不一致')
        try:
            calculated = requirement(job['qty'], bom['qty'], bom['scrap_allowance'], binding['quantum'])
        except (ValueError, TypeError, KeyError):
            issue(d['id'] + '：整批需求无法计算')
            continue
        if number(d['required_qty']) != calculated:
            issue(d['id'] + '：整批需求与BOM、损耗及取整步长不一致')
        demand_rows.append(dict(**d, product_id=job['product_id'], bom_id=bom['id'], route_id=binding['route_id'], material_id=material['id'], material_name=material['name'],
                                bom_version=bom['version'], bom_qty=quantity(number(bom['qty'])), scrap_allowance=quantity(number(bom['scrap_allowance'])), quantum=quantity(number(binding['quantum'])),
                                calculated_qty=quantity(calculated)))
    if actual != expected:
        issue('批次×当前BOM需求覆盖不完整或包含额外行')
    for lot in supplies.values():
        material = materials.get(lot['material_id'])
        if lot['study_id'] != study['id'] or not material:
            issue(lot['id'] + '：供给跨方案或物料缺失')
        elif lot['unit'] != material['unit']:
            issue(lot['id'] + '：供给单位与物料档案不一致')
        if lot['kind'] == '期初假设' and resource.time(lot['available_from']) > start:
            issue(lot['id'] + '：期初假设晚于试排起点')
    if problems:
        return result

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
