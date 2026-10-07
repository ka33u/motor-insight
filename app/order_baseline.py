"""Order coverage and frozen BOM reconciliation, without replacing live facts."""
import hashlib
from collections import defaultdict
from decimal import Decimal
from pathlib import Path
from . import finite_schedule, joint_schedule
from .order_baseline_schema import DATASETS
from .order_baseline_contract import issues as row_issues, bundle_hash, project, source_hash, signature

VERSION = 'ORDER_BOM_BASELINE_1'
MAX_ROWS = 5000
NOTICE = ('版本化Excel合成快照；基线时点为模拟业务截止，不证明文件当时已存在或取得业务批准。'
          '快照自洽、来源当前字段和试排用料分别核对；源档案变化不覆盖基线用量，而是提示重新评审。'
          '批次加工完成不代表整单覆盖、质量放行、发运或签收。未登记报工不证明实际未开工；本页不下达生产或修改客户交期。')


def rule_hash():
    names = ('order_baseline.py', 'order_baseline_data.py', 'order_baseline_contract.py', 'order_baseline_schema.py')
    return signature(dict(joint_rules=joint_schedule.rule_hash(), files={n: hashlib.sha256(Path(__file__).with_name(n).read_bytes()).hexdigest() for n in names}))


def frozen_sources(link):
    return {
        'order_lines': dict(id=link['order_line_id'], order_id=link['order_id'], product_id=link['product_id'], qty=link['order_qty'], original_due=link['original_due'], due=link['due']),
        'work_orders': dict(id=link['work_order_id'], product_id=link['product_id'], planned_qty=link['work_order_qty'], bom_version=link['bom_version'], route_version=link['route_version'], status=link['work_status']),
        'allocations': dict(id=link['allocation_id'], work_order_id=link['work_order_id'], order_line_id=link['order_line_id'], qty=link['allocation_qty'], effective=link['allocation_effective']),
        'products': dict(id=link['product_id'], bom_version=link['product_bom_version'], route_version=link['product_route_version']),
    }


def frozen_bom(row, link):
    return dict(id=row['source_bom_id'], product_id=link['product_id'], material_id=row['material_id'], version=row['version'], qty=row['unit_qty'],
                scrap_allowance=row['scrap_allowance'], effective=row['effective'], assembly_level=row['branch'])


def frozen_route(row, link):
    return dict(id=row['route_id'], product_id=link['product_id'], version=link['route_version'], process=row['process'],
                branch='整机' if row['branch'] == '装配件包' else row['branch'], mandatory=row['route_mandatory'])


def analyze(study, tables, parent, refs, cutoff):
    refs = defaultdict(dict, refs)
    issues, warnings, changes = [], [], []
    def issue(message):
        if message not in issues:
            issues.append(message)
    def warn(message):
        if message not in warnings:
            warnings.append(message)
    joint = parent['result']
    result = dict(state='paused', study=study, joint_study=joint['study'], resource_study=joint['resource_study'], policy=joint['policy'], policy_name=joint['policy_name'],
                  rule_version=VERSION, notice=NOTICE, issues=issues, warnings=warnings, changes=changes, links=[], orders=[], bom=[], versions=[], summary=None,
                  trial_summary=joint['summary'], trial_state=joint['state'])
    for ds in DATASETS:
        for row in [study] if ds == 'order_baselines' else tables.get(ds, []):
            for error in row_issues(ds, row):
                issue(row['id']+'：'+error['message'])
    for field, ds in [('link_count', 'order_baseline_links'), ('bom_count', 'order_baseline_bom')]:
        if study[field] != len(tables.get(ds, [])):
            issue('基线声明数量不一致：'+field)
    if any(len(rows) > MAX_ROWS for rows in tables.values()):
        issue('基线超出受控规模，未截断计算')
    if study['joint_study_id'] != joint['study']['id']:
        issue('物料人机方案身份不一致')
    if study['owner_id'] not in refs['employees']:
        issue('基线负责人档案缺失')
    if issues:
        return result
    if study['content_hash'] != bundle_hash(study, tables):
        issue('基线内容摘要不符；不能把局部变更视为原冻结版本')
    if study['baseline_at'] > cutoff or study['baseline_at'] > joint['resource_study']['baseline']:
        issue('模拟基线时点晚于业务截止或试排起点')
    versions = [r['version'] for r in refs['order_baselines'].values() if r['series'] == study['series']]
    if len(set(versions)) != len(versions):
        issue('同一系列基线版本重复')
    chain, seen, current = [], set(), study
    while current:
        if current['id'] in seen or len(chain) >= 100:
            issue('基线版本链循环或过长')
            break
        seen.add(current['id'])
        chain.append({k: current[k] for k in ('id', 'name', 'series', 'version', 'supersedes_id', 'baseline_at')})
        previous = refs['order_baselines'].get(current.get('supersedes_id'))
        if current['version'] == 1:
            if current.get('supersedes_id'):
                issue('首版基线不能引用前版')
            break
        if not previous or previous['version'] != current['version']-1 or previous['series'] != study['series'] or previous['baseline_at'] > current['baseline_at']:
            issue('基线版本链缺失、不连续或时间倒置')
            break
        current = previous
    result['versions'] = chain
    links = {row['id']: row for row in tables['order_baseline_links']}
    bom_rows = tables['order_baseline_bom']
    if len(links) != len(tables['order_baseline_links']) or len({r['id'] for r in bom_rows}) != len(bom_rows):
        issue('基线明细编号重复')
    raw = parent['parent']['base']['tables']
    jobs = {j['id']: j for j in raw['schedule_jobs']}
    mapped = [r['job_id'] for r in links.values()]
    if len(mapped) != len(set(mapped)) or set(mapped) != set(jobs):
        issue('试排批次须完整且唯一地映射到订单工单基线')
    by_link = defaultdict(list)
    for row in bom_rows:
        if row['baseline_id'] != study['id'] or row['link_id'] not in links:
            issue(row['id']+'：用料快照跨基线或映射缺失')
        by_link[row['link_id']].append(row)
    for ds, clock in [('units', 'assembly_at'), ('operations', 'started'), ('shipments', 'shipped')]:
        for row in refs[ds].values():
            try:
                finite_schedule.time(row[clock])
                if ds == 'shipments' and (type(row['qty']) is not int or row['qty'] <= 0):
                    raise ValueError()
            except (ValueError, TypeError, KeyError):
                issue(ds+'/'+row['id']+'：登记时点或发货台数无效，不能补零')

    def compare(dataset, saved, expected, link_id):
        if source_hash(dataset, saved) != expected:
            issue(link_id+'：快照字段与声明来源摘要不符：'+dataset)
        current = refs[dataset].get(saved['id'])
        if not current or source_hash(dataset, current) != expected:
            fields = [field for field in saved if canonical_value(saved.get(field)) != canonical_value(current.get(field) if current else None)]
            changes.append(dict(link_id=link_id, dataset=dataset, key=saved['id'], fields=fields, frozen=project(dataset, saved), current=project(dataset, current) if current else None))
            warn(link_id+'：当前资料缺失、已变化或与基线不符：'+dataset+'/'+saved['id'])

    order_signatures, work_signatures, allocation_totals = {}, {}, defaultdict(int)
    for link in links.values():
        job = jobs.get(link['job_id'])
        if link['baseline_id'] != study['id'] or not job or job['product_id'] != link['product_id'] or job['qty'] != link['plan_qty'] or job['route_version'] != link['route_version']:
            issue(link['id']+'：批次身份、配置、数量或路线版本与基线不符')
        if link['allocation_effective'] > study['baseline_at'][:10]:
            issue(link['id']+'：分配生效晚于基线时点')
        order = refs['orders'].get(link['order_id'])
        if not order or order.get('order_date', '9999') > study['baseline_at'][:10]:
            warn(link['id']+'：当前订单头缺失或晚于基线时点')
        elif order.get('status') in ('取消', '已取消', '关闭', '已关闭', '作废', '已作废'):
            warn(link['id']+'：当前订单已取消、关闭或作废，不能按原基线继续安排')
        if link['allocation_qty'] > min(link['order_qty'], link['work_order_qty']):
            issue(link['id']+'：基线分配数量超过订单或工单数量')
        allocation_totals[link['allocation_id']] += link['plan_qty']
        for ds, field in [('order_lines', 'order_hash'), ('work_orders', 'work_hash'), ('allocations', 'allocation_hash'), ('products', 'product_hash')]:
            compare(ds, frozen_sources(link)[ds], link[field], link['id'])
        for identity, key, value in [(order_signatures, link['order_line_id'], link['order_hash']), (work_signatures, link['work_order_id'], link['work_hash'])]:
            if key in identity and identity[key] != value:
                issue(link['id']+'：同一业务对象的基线字段互相矛盾')
            identity[key] = value
        rows = by_link[link['id']]
        if len(rows) != link['bom_count'] or len({r['source_bom_id'] for r in rows}) != len(rows):
            issue(link['id']+'：BOM快照数量不完整或重复')
        frozen = sorted([frozen_bom(row, link) for row in rows], key=lambda r: r['id'])
        if signature(frozen) != link['bom_set_hash']:
            issue(link['id']+'：完整BOM集合摘要不符')
        current_bom = sorted([project('bom', r) for r in refs['bom'].values() if r['product_id'] == link['product_id'] and r['version'] == link['bom_version']], key=lambda r: r['id'])
        if signature(current_bom) != link['bom_set_hash']:
            warn(link['id']+'：当前工单版本BOM集合与基线不符，不能静默增删用料')
        for row in rows:
            if row['version'] != link['bom_version'] or row['effective'] > study['baseline_at'][:10]:
                issue(row['id']+'：BOM版本不符或生效晚于基线')
            if row['branch'] not in ('定子', '转子', '装配件包'):
                issue(row['id']+'：用料分支未知')
            if row['unit'] == '件' and Decimal(str(row['quantum'])) % 1:
                issue(row['id']+'：计件物料步长须为整数')
            if not any(t['job_id'] == link['job_id'] and t['route_id'] == row['route_id'] for t in raw['schedule_tasks']):
                issue(row['id']+'：试排批次没有绑定工序')
            compare('bom', frozen_bom(row, link), row['bom_hash'], link['id'])
            compare('routes', frozen_route(row, link), row['route_hash'], link['id'])
            compare('materials', dict(id=row['material_id'], unit=row['unit']), row['material_hash'], link['id'])
    for link in links.values():
        if allocation_totals[link['allocation_id']] > link['allocation_qty']:
            issue(link['allocation_id']+'：多个试排批次累计超过基线分配数量')
    if issues:
        return result

    # Current references do not change copied baseline arithmetic.
    joint_bindings = {b['id']: b for b in parent['tables']['joint_bindings']}
    joint_demands = defaultdict(list)
    for demand in parent['tables']['joint_demands']:
        binding = joint_bindings.get(demand['binding_id'])
        if binding:
            joint_demands[demand['job_id'], binding['bom_id']].append((demand, binding))
    for link in links.values():
        for row in by_link[link['id']]:
            required = joint_schedule.requirement(link['plan_qty'], row['unit_qty'], row['scrap_allowance'], row['quantum'])
            candidates = joint_demands[link['job_id'], row['source_bom_id']]
            matching = len(candidates) == 1 and candidates[0][0]['unit'] == row['unit'] and Decimal(str(candidates[0][0]['required_qty'])) == required and candidates[0][1]['route_id'] == row['route_id'] and Decimal(str(candidates[0][1]['quantum'])) == Decimal(str(row['quantum']))
            if not matching:
                warn(row['id']+'：当前试排需求、步长或工序与BOM基线不一致')
            result['bom'].append(dict(**row, job_id=link['job_id'], order_line_id=link['order_line_id'], product_id=link['product_id'], plan_qty=link['plan_qty'],
                                      required_qty=joint_schedule.quantity(required), matches_trial=matching,
                                      trial_demands=[dict(id=d['id'], qty=d['required_qty'], unit=d['unit'], route_id=b['route_id'], quantum=b['quantum']) for d, b in candidates]))
    if joint['state'] != 'trial':
        warn('物料人机方案已暂停：'+'；'.join(joint['issues']))
    computed_jobs = {j['id']: j for j in joint['jobs']}
    per_order, planned_per_work = defaultdict(list), defaultdict(int)
    for link in links.values():
        planned_per_work[link['work_order_id']] += link['plan_qty']
        job = computed_jobs.get(link['job_id'])
        finish = job.get('finished') if job else None
        due_end = link['due']+'T23:59:59'
        related_work_allocations = [a for a in refs['allocations'].values() if a['work_order_id'] == link['work_order_id'] and a['effective'] <= study['baseline_at'][:10]]
        if any(a['order_line_id'] != link['order_line_id'] for a in related_work_allocations):
            warn(link['id']+'：工单跨订单分配，当前新开工范围须重新拆分核对')
        if link['work_status'] != '未开工':
            warn(link['id']+'：基线工单不是未开工，不能按整批新开工理解用料')
        for ds, clock in [('units', 'assembly_at'), ('operations', 'started')]:
            observed = [r for r in refs[ds].values() if r['work_order_id'] == link['work_order_id'] and r[clock] <= cutoff]
            if observed:
                warn(link['id']+'：截止时点已有'+('装配' if ds == 'units' else '报工')+'登记，重新安排须核对在制及已领料')
        row = dict(**link, finished=finish, internal_due=jobs[link['job_id']]['due'], trial_state=job['state'] if job else 'paused',
                   customer_late_minutes=max(0, (finite_schedule.time(finish)-finite_schedule.time(due_end)).total_seconds()/60) if finish else None,
                   source_changed=any(c['link_id'] == link['id'] for c in changes))
        result['links'].append(row)
        per_order[link['order_line_id']].append(row)
    for order_id, rows in sorted(per_order.items()):
        reference = rows[0]
        registered = [s for s in refs['shipments'].values() if s['order_line_id'] == order_id and s['shipped'] <= study['baseline_at']]
        shipped = sum(s['qty'] for s in registered)
        needed = max(0, reference['order_qty']-shipped)
        planned = sum(r['plan_qty'] for r in rows)
        if shipped > reference['order_qty'] or planned > needed:
            warn(order_id+'：已登记发货与试排覆盖超过基线订单需求，须复核')
        complete = all(r['finished'] for r in rows)
        result['orders'].append(dict(id=order_id, order_id=reference['order_id'], product_id=reference['product_id'], order_qty=reference['order_qty'], registered_shipped_qty=shipped,
                                    baseline_open_qty=needed, planned_qty=planned, uncovered_qty=max(0, needed-planned), overplanned_qty=max(0, planned-needed),
                                    coverage_percent=100*planned/needed if needed else None, fully_covered=planned == needed, trial_jobs=len(rows),
                                    scheduled_qty=sum(r['plan_qty'] for r in rows if r['finished']), original_due=reference['original_due'], due=reference['due'],
                                    mapped_jobs_finish=max(r['finished'] for r in rows) if complete else None,
                                    order_finish=max(r['finished'] for r in rows) if complete and planned == needed and planned else None))
    for work_id, planned in planned_per_work.items():
        reference = next(l for l in links.values() if l['work_order_id'] == work_id)
        if planned > reference['work_order_qty']:
            warn(work_id+'：跨批次安排超过基线工单台数')
    if warnings:
        # Keep the independently calculated batch reference visible, but do
        # not turn it into an order completion claim while the basis differs.
        for order in result['orders']:
            order['order_finish'] = None
    result['state'] = 'review' if warnings else 'aligned'
    result['summary'] = dict(order_lines=len(result['orders']), jobs=len(links), order_qty=sum(r['order_qty'] for r in result['orders']),
                             baseline_open_qty=sum(r['baseline_open_qty'] for r in result['orders']), planned_qty=sum(r['plan_qty'] for r in links.values()),
                             uncovered_qty=sum(r['uncovered_qty'] for r in result['orders']), fully_covered_lines=sum(r['fully_covered'] for r in result['orders']),
                             scheduled_jobs=sum(bool(r['finished']) for r in result['links']), customer_late_jobs=sum((r['customer_late_minutes'] or 0) > 0 for r in result['links']),
                             source_changes=len(changes), mismatched_bom_rows=sum(not r['matches_trial'] for r in result['bom']))
    return result


def canonical_value(value):
    from .order_baseline_contract import canonical
    return canonical(value)
