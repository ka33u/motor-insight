"""Check fixed trial times against declared pre-start evidence; never dispatch."""
from collections import Counter, defaultdict
from datetime import date, datetime
import hashlib
from pathlib import Path
from . import order_baseline
from .finite_schedule_contract import time
from .launch_contract import KINDS, COUNTS, issues as row_issues, bundle_hash, signature

MAX_ROWS = 5000
NOTICE = ('仅自编资料核对，不是现场开工批准。固定使用原试排时间，不延时重排；工装按全部已排任务保守预占并累计次数，其他条件受阻也不释放。'
          '不适用须显式登记；文件号不证明原件已审阅，质量条件不是首件实测或整机放行。未覆盖的订单需求仍未安排。')


def rule_hash():
    return signature(dict(parent=order_baseline.rule_hash(), files={n: hashlib.sha256(Path(__file__).with_name(n).read_bytes()).hexdigest() for n in ('launch.py', 'launch_contract.py', 'launch_schema.py', 'launch_data.py')}))


def analyze(study, tables, parent, refs, cutoff):
    tables = {ds: list(tables.get(ds, [])) for ds in COUNTS}
    refs = {ds: dict(rows) for ds, rows in refs.items()}
    issues = []
    result = dict(study=study, policy=parent['result']['policy'], policy_name=parent['result']['policy_name'], baseline=parent['result']['study'],
                  state='paused', issues=issues, tasks=[], jobs=[], tools=[], summary=None, notice=NOTICE, basis_state=parent['result']['state'])
    for ds, rows in [('launch_studies', [study]), *tables.items()]:
        if len(rows) > MAX_ROWS:
            issues.append(ds+'超过受控规模')
        if len({r.get('id') for r in rows}) != len(rows):
            issues.append(ds+'编号重复')
        for row in rows:
            issues.extend(row.get('id', '')+'：'+x['message'] for x in row_issues(ds, row))
            if ds != 'launch_studies' and row.get('study_id') != study['id']:
                issues.append(row['id']+'跨核对方案')
    if issues:
        return result
    assessed = time(study['assessed_at'])
    if assessed > time(cutoff) or assessed < time(parent['result']['study']['baseline_at']):
        issues.append('核对时点须介于订单基线和资料截止之间')
    if study['baseline_id'] != parent['result']['study']['id']:
        issues.append('订单基线引用不符')
    for ds, field in COUNTS.items():
        if len(tables[ds]) != study[field]:
            issues.append(ds+'声明行数不符')
    if bundle_hash(study, tables) != study['content_hash']:
        issues.append('投产输入内容摘要不符')
    for row in [study, *[r for ds in COUNTS if ds != 'launch_requirements' for r in tables[ds]]]:
        if row.get('owner_id') not in refs.get('employees', {}):
            issues.append(row['id']+'登记工号缺失')
    if parent['result']['state'] == 'paused':
        issues.append('订单基线已暂停，不能推断投产条件')
    raw = parent['parent']['parent']['base']['tables']
    required_pairs = {(r['job_id'], r['route_id']) for r in raw['schedule_tasks']}
    requirements = {}
    for row in tables['launch_requirements']:
        key = (row['job_id'], row['route_id'], row['kind'])
        if key in requirements or key[:2] not in required_pairs:
            issues.append(row['id']+'重复条件或超出试排工序范围')
        requirements[key] = row
    if set(requirements) != {(*pair, kind) for pair in required_pairs for kind in KINDS}:
        issues.append('每个批次工序须明确工装、工艺文件和质量条件，不能将漏行当成不需要')
    if issues:
        return result
    job_links = {r['job_id']: r for r in parent['result']['links']}
    docs = {r['id']: r for r in tables['launch_documents']}
    quality = {r['id']: r for r in tables['launch_clearances']}
    fits = defaultdict(list)
    for row in tables['launch_tool_fits']:
        fits[row['group']].append(row)
    blocks = defaultdict(list)
    for row in tables['launch_tool_blocks']:
        blocks[row['tool_id']].append(row)
    used, reservations = Counter(), defaultdict(list)

    def evidence(row, req, task, good):
        failures = []
        unknown = False
        if not row:
            return ['指定登记资料缺失'], True
        if time(row['registered']) > assessed:
            failures.append('登记晚于资料截止'); unknown = True
        if row['version'] != req['version']:
            failures.append('登记版本与要求不符')
        if row['status'] != good:
            failures.append('登记状态：'+row['status'])
            unknown |= row['status'] in ('待核对', '草稿')
        if row['route_id'] != task['route_id']:
            failures.append('登记工序不匹配')
        if time(row['valid_from']) > time(task['started']) or time(row['valid_until']) < time(task['finished']):
            failures.append('有效窗口未覆盖完整换型和加工')
        return failures, unknown

    tasks = parent['parent']['result']['tasks']
    for task in sorted(tasks, key=lambda t: (t.get('started') or '9999', t['id'])):
        row = dict(id=task['id'], job_id=task['job_id'], route_id=task['route_id'], process=task['process'], product_id=task['product_id'],
                   order_line_id=job_links[task['job_id']]['order_line_id'], work_order_id=job_links[task['job_id']]['work_order_id'], qty=task['qty'],
                   started=task.get('started'), finished=task.get('finished'), trial_state=task['state'], resource_id=task.get('resource_id'), gates=[], blockers=[], upstream=[], state='unknown')
        for kind in KINDS:
            req = requirements[task['job_id'], task['route_id'], kind]
            gate = dict(kind=kind, requirement_id=req['id'], subject=req['subject'], version=req['version'], state='unknown', reasons=[], evidence_ids=[], candidates=[], tool_id=None, uses=None)
            row['gates'].append(gate)
            if not req['applicable']:
                gate.update(state='not_required', reasons=[req['reason']]); continue
            if task['state'] != 'scheduled':
                gate['reasons'] = ['原试排未形成完整时间：'+task.get('reason', '')]; continue
            if kind != '工装':
                obj = (docs if kind == '工艺文件' else quality).get(req['subject'])
                reasons, unknown = evidence(obj, req, task, '已发布' if kind == '工艺文件' else '具备登记条件')
                if obj:
                    gate['evidence_ids'] = [obj['id']]
                    if kind == '工艺文件' and obj['product_id'] != task['product_id']:
                        reasons.append('文件适用配置不符')
                    if kind == '质量条件' and obj['work_order_id'] != row['work_order_id']:
                        reasons.append('质量条件对应工单不符')
                gate.update(reasons=reasons, state='unknown' if unknown else 'blocked' if reasons else 'satisfied')
                continue
            candidates = sorted(fits.get(req['subject'], []), key=lambda f: (f['tool_id'], f['id']))
            selected = None
            for fit in candidates:
                reasons, unknown = evidence(fit, req, task, '配套有效')
                gate['evidence_ids'].append(fit['id'])
                if fit['product_id'] != task['product_id']:
                    reasons.append('工装配套配置不符')
                tool = refs.get('tools', {}).get(fit['tool_id'])
                use_qty = int(task['qty']) * req['uses_per_unit']
                if not tool:
                    reasons.append('工装原始台账缺失'); unknown = True
                else:
                    resource = refs.get('production_resources', {}).get(task.get('resource_id'))
                    if not resource or resource.get('equipment_id') != tool.get('equipment_id'):
                        reasons.append('工装绑定设备与试排设备不符')
                    if tool.get('status') != '有效':
                        reasons.append('工装台账状态非有效')
                    try:
                        start = datetime.combine(date.fromisoformat(tool['calibrated']), datetime.min.time())
                        end = datetime.combine(date.fromisoformat(tool['next_due']), datetime.min.time())
                        if end <= start:
                            raise ValueError()
                        if time(task['started']) < start or time(task['finished']) > end:
                            reasons.append('工装台账有效期未覆盖任务')
                    except (TypeError, ValueError, KeyError):
                        reasons.append('工装台账日期待核对'); unknown = True
                    if type(tool.get('uses')) is not int or tool['uses'] < 0 or type(tool.get('maintenance_limit')) is not int or tool['maintenance_limit'] <= 0:
                        reasons.append('工装次数或维护阈值待核对'); unknown = True
                    elif tool['uses'] + used[tool['id']] + use_qty > tool['maintenance_limit']:
                        reasons.append('本次安排将超过登记维护次数')
                    for block in blocks[tool['id']]:
                        if time(block['started']) < time(task['finished']) and time(task['started']) < time(block['ended']):
                            gate['evidence_ids'].append(block['id'])
                            reasons.append('工装预占或停用：'+block['id'])
                            unknown |= time(block['registered']) > assessed
                    overlap = [v['task_id'] for v in reservations[tool['id']] if v['started'] < task['finished'] and task['started'] < v['finished']]
                    if overlap:
                        reasons.append('同一工装与试排任务重叠：'+'、'.join(overlap))
                gate['candidates'].append(dict(fit_id=fit['id'], tool_id=fit['tool_id'], reasons=reasons, unknown=unknown, uses=use_qty))
                if not reasons and selected is None:
                    selected = fit, use_qty
            if selected:
                fit, use_qty = selected
                gate.update(state='satisfied', tool_id=fit['tool_id'], uses=use_qty)
                used[fit['tool_id']] += use_qty
                reservations[fit['tool_id']].append(dict(task_id=task['id'], started=task['started'], finished=task['finished'], uses=use_qty, fit_id=fit['id']))
            else:
                gate.update(state='unknown' if not candidates or any(c['unknown'] for c in gate['candidates']) else 'blocked',
                            reasons=['无可用配套登记'] if not candidates else list(dict.fromkeys(reason for c in gate['candidates'] for reason in c['reasons'])))
        row['blockers'] = [g['kind']+'：'+'；'.join(g['reasons']) for g in row['gates'] if g['state'] not in ('satisfied', 'not_required')]
        row['state'] = 'blocked' if any(g['state'] == 'blocked' for g in row['gates']) else 'unknown' if row['blockers'] or task['state'] != 'scheduled' else 'satisfied'
        if parent['result']['state'] != 'aligned':
            row['blockers'].append('订单与BOM基线需要重新核对')
            if row['state'] == 'satisfied': row['state'] = 'unknown'
        result['tasks'].append(row)
    # The fixed trial is a DAG; propagate unavailable predecessors without rescheduling.
    by_id = {r['id']: r for r in result['tasks']}
    incoming = defaultdict(list)
    for edge in raw['schedule_edges']:
        incoming[edge['to_task_id']].append(edge['from_task_id'])
    pending = set(by_id)
    while pending:
        available = sorted(k for k in pending if not (set(incoming[k]) & pending))
        if not available:
            issues.append('试排任务依赖无法完成条件传播'); result.update(tasks=[], tools=[], jobs=[], summary=None); return result
        for key in available:
            row = by_id[key]
            row['upstream'] = sorted(k for k in incoming[key] if k not in by_id or by_id[k]['state'] != 'satisfied')
            if row['upstream']:
                row['blockers'].append('前序投产条件未满足：'+'、'.join(row['upstream']))
                if row['state'] == 'satisfied': row['state'] = 'blocked'
            pending.remove(key)
    for job, link in sorted(job_links.items()):
        own = [r for r in result['tasks'] if r['job_id'] == job]
        counts = Counter(r['state'] for r in own)
        result['jobs'].append(dict(job_id=job, order_line_id=link['order_line_id'], work_order_id=link['work_order_id'], qty=link['plan_qty'], tasks=len(own), counts=dict(counts),
                                   state='satisfied' if own and counts['satisfied'] == len(own) else 'blocked' if counts['blocked'] else 'unknown'))
    for key in sorted({r['tool_id'] for r in tables['launch_tool_fits']} | set(blocks)):
        tool = refs.get('tools', {}).get(key, {})
        result['tools'].append(dict(id=key, name=tool.get('name'), baseline_uses=tool.get('uses'), limit=tool.get('maintenance_limit'), proposed_uses=used[key], reservations=reservations[key], blocks=blocks[key]))
    result['state'] = 'review'
    counts = Counter(r['state'] for r in result['tasks'])
    result['summary'] = dict(tasks=len(result['tasks']), satisfied=counts['satisfied'], blocked=counts['blocked'], unknown=counts['unknown'],
                           jobs=len(result['jobs']), satisfied_jobs=sum(r['state'] == 'satisfied' for r in result['jobs']), plan_qty=sum(r['qty'] for r in result['jobs']),
                           conditions=len(requirements), not_required=sum(not r['applicable'] for r in requirements.values()), proposed_tool_uses=sum(used.values()),
                           uncovered_qty=parent['result']['summary']['uncovered_qty'])
    return result
