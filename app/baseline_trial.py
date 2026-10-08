"""Conditional frozen-BOM trial; integrity is not historical approval evidence."""
import hashlib
from collections import defaultdict
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from . import finite_schedule as finite, order_baseline as baseline, joint_schedule
from .baseline_trial_schedule import schedule
from .joint_schedule_contract import issues as supply_issues, number

VERSION = 'BASELINE_BOM_CONDITIONAL_1'
MAX_ROWS = 5000
NOTICE = ('按每个批次声明的冻结用料集合试算；来源是正常导入的模拟Excel。摘要只能核对快照自洽，历史完整性与业务批准未核实。'
          '同型号各批次可使用不同冻结版本，共同竞争同一个物料供给池、设备和人员；保持现有人机路线及窗口，按整批向上取整、FIFO预留、尾部追加。'
          '仅适用于未开工、无截至模拟业务截止的装配、报工及领料登记的整批假设；无登记不证明实际未开工或未领料。'
          '未建模的用料可能改变齐套和完工；没有替代料、单位换算、在制扣料、自动释放或正式派工。'
          '客户覆盖仅作基线参照，不生成整单完工、OTIF或交付承诺。')
COMPARE_NOTICE = '同一策略、人机和供给下，冻结用料试排减当前BOM试排；只有双方可计算且批次均完整安排时才比较完成时间。需求集合可能不同，不是因果估计。'


def rule_hash():
    return finite.digest(dict(baseline=baseline.rule_hash(), files={n: hashlib.sha256(Path(__file__).with_name(n).read_bytes()).hexdigest()
                         for n in ('baseline_trial.py', 'baseline_trial_schedule.py', 'baseline_trial_data.py', 'baseline_trial_views.py')}))


def compare(current, frozen):
    result = dict(available=False, notice=COMPARE_NOTICE, jobs=[], materials=[])
    if current['state'] != 'trial' or frozen is None or frozen['state'] != 'trial':
        return result
    old = {r['id']: r for r in current['jobs']}
    if set(old) != {r['id'] for r in frozen['jobs']}:
        raise ValueError('试排批次身份不一致，未生成差值')
    result['available'] = True
    for row in frozen['jobs']:
        prev = old[row['id']]
        if (prev['product_id'], prev['qty']) != (row['product_id'], row['qty']):
            raise ValueError('试排批次配置或台数不一致，未生成差值')
        a, b = prev['finished'], row['finished']
        result['jobs'].append(dict(id=row['id'], qty=row['qty'], current_state=prev['state'], frozen_state=row['state'], current_finished=a,
                                  frozen_finished=b, delta_minutes=(finite.time(b)-finite.time(a)).total_seconds()/60 if a and b else None))
    old = {(r['material_id'], r['unit']): r for r in current['balances']}
    new = {(r['material_id'], r['unit']): r for r in frozen['balances']}
    for key in sorted(set(old) | set(new)):
        a, b = old.get(key, {}).get('required_qty', '0'), new.get(key, {}).get('required_qty', '0')
        result['materials'].append(dict(material_id=key[0], unit=key[1], current_required_qty=a, frozen_required_qty=b,
                                        delta_qty=joint_schedule.quantity(Decimal(b)-Decimal(a))))
    return result


def analyze(checked, tables, joint, refs, cutoff):
    """checked is the unchanged baseline integrity result, in the same snapshot."""
    study = checked['study']
    current, parent = joint['result'], joint['parent']
    problems = []
    out = dict(state='paused', study=study, policy=current['policy'], policy_name=current['policy_name'], rule_version=VERSION, notice=NOTICE,
               history_verified=False, cutoff=cutoff, issues=problems, warnings=list(checked['warnings']), changes=checked['changes'],
               coverage=checked['orders'], trial=None, comparison=compare(current, None))

    def issue(code, ds, key, field, message):
        row = dict(code=code, dataset=ds, key=key, field=field, message=message)
        if row not in problems:
            problems.append(row)

    if checked['state'] == 'paused':
        for message in checked['issues']:
            issue('BASELINE_INVALID', 'order_baselines', study['id'], '', message)
        return out
    if parent['result']['state'] != 'trial':
        issue('CREW_BASE_INVALID', 'crew_studies', current['crew_study']['id'], '', '人机资料暂停；不能将缺失依据当成正常未排任务')
        return out
    cutoff_time = finite.time(cutoff)
    start = finite.time(current['resource_study']['baseline'])
    if cutoff_time > start:
        issue('CUTOFF_AFTER_START', 'order_baselines', study['id'], 'baseline_at', '业务截止晚于试排起点，整批新开工模式不适用')
    links = tables['order_baseline_links']
    by_link = {r['id']: r for r in links}
    planned = {ds: defaultdict(int) for ds in ('allocations', 'work_orders', 'order_lines')}
    for link in links:
        for ds, fk in [('allocations', 'allocation_id'), ('work_orders', 'work_order_id'), ('order_lines', 'order_line_id')]:
            planned[ds][link[fk]] += link['plan_qty']
        saved = baseline.frozen_sources(link)
        identities = dict(order_lines=('order_id', 'product_id'), work_orders=('product_id',), allocations=('work_order_id', 'order_line_id'), products=())
        scopes = dict(order_lines=('qty',), work_orders=('planned_qty',), allocations=('qty', 'effective'), products=())
        for ds in identities:
            row = refs.get(ds, {}).get(saved[ds]['id'])
            if not row:
                issue('ORDER_IDENTITY_CHANGED', ds, saved[ds]['id'], '', '当前业务对象缺失，无法核对整批安排范围')
                continue
            for field in identities[ds]:
                if row.get(field) != saved[ds][field]:
                    issue('ORDER_IDENTITY_CHANGED', ds, row['id'], field, '当前身份与冻结映射不一致')
            for field in scopes[ds]:
                if row.get(field) != saved[ds][field]:
                    issue('ORDER_SCOPE_CHANGED', ds, row['id'], field, '当前数量或分配范围已变，需要重新建立基线')
        order = refs.get('orders', {}).get(link['order_id'])
        if not order:
            issue('ORDER_IDENTITY_CHANGED', 'orders', link['order_id'], '', '订单头缺失')
        else:
            if order.get('status') not in ('待生产', '执行中', '部分交付'):
                issue('ORDER_NOT_OPEN', 'orders', order['id'], 'status', '订单状态不在可试算的开放状态中')
            try:
                value = date.fromisoformat(order['order_date'])
                if value.isoformat() != order['order_date'] or value.isoformat() > study['baseline_at'][:10]:
                    raise ValueError()
            except (ValueError, TypeError, KeyError):
                issue('ORDER_DATE_INVALID', 'orders', order['id'], 'order_date', '订单日期无效或晚于冻结时点')
        work = refs.get('work_orders', {}).get(link['work_order_id'], {})
        if link['work_status'] != '未开工' or work.get('status') != '未开工':
            issue('WORK_NOT_NEW', 'work_orders', link['work_order_id'], 'status', '只支持整批未开工假设，不能重新领用已开工批次全部物料')
        if work.get('route_version') != link['route_version']:
            issue('ROUTE_MISMATCH', 'work_orders', link['work_order_id'], 'route_version', '当前工单路线与保留的人机任务不一致')
        for row in refs.get('allocations', {}).values():
            if row['work_order_id'] != link['work_order_id']:
                continue
            try:
                day = date.fromisoformat(row['effective'])
                if day.isoformat() != row['effective']:
                    raise ValueError()
                number(row['qty'], True)
            except (ValueError, TypeError, KeyError):
                issue('ALLOCATION_INVALID', 'allocations', row['id'], '', '关联分配日期或数量无效')
                continue
            if day <= cutoff_time.date() and row['order_line_id'] != link['order_line_id']:
                issue('CROSS_ORDER_ALLOCATION', 'allocations', row['id'], 'order_line_id', '截止时点工单存在跨订单分配，须先拆分核对')
    for ds, totals in planned.items():
        for key, amount in totals.items():
            row = refs.get(ds, {}).get(key)
            if not row:
                continue
            field = 'planned_qty' if ds == 'work_orders' else 'qty'
            try:
                limit = number(row[field], True)
            except (ValueError, TypeError, KeyError):
                issue('ORDER_SCOPE_CHANGED', ds, key, field, '当前范围数量无效')
                continue
            if ds == 'order_lines':
                shipped = sum(r['qty'] for r in refs.get('shipments', {}).values() if r['order_line_id'] == key and finite.time(r['shipped']) <= cutoff_time)
                if shipped > limit or amount > limit-shipped:
                    issue('ORDER_OVERPLANNED', ds, key, field, '截止时点登记发货与整批安排超过订单需求')
            elif amount > limit:
                issue('OVER_ALLOCATED', ds, key, field, '跨批次安排超过当前工单或分配数量')
    for ds, clock in [('units', 'assembly_at'), ('operations', 'started')]:
        for row in refs.get(ds, {}).values():
            if finite.time(row[clock]) <= cutoff_time:
                issue('WIP_REGISTERED', ds, row['id'], clock, '截止时点已有装配或报工登记，须先核对在制')
    for row in refs.get('inventory_movements', {}).values():
        try:
            at = finite.time(row.get('occurred'))
            if at > cutoff_time:
                continue
            signed = row.get('qty_signed')
            if type(signed) not in (int, float) or not Decimal(str(signed)).is_finite() or signed >= 0:
                raise ValueError()
            if row.get('movement') != '生产领料' or row.get('reference') != row.get('work_order_id'):
                raise ValueError()
            issue('MATERIAL_ALREADY_ISSUED', 'inventory_movements', row['id'], 'qty_signed', '截止前已有生产领料；退料或净额为零也不证明整批未领料')
        except (ValueError, TypeError, InvalidOperation):
            issue('ISSUE_HISTORY_UNRESOLVED', 'inventory_movements', row['id'], '', '工单流水类型、时点、方向或关联不明确；不自动抵扣')
    demand_rows = []
    for row in tables['order_baseline_bom']:
        link = by_link[row['link_id']]
        material = refs.get('materials', {}).get(row['material_id'])
        if not material:
            issue('MATERIAL_IDENTITY_INVALID', 'materials', row['material_id'], '', '冻结物料当前档案缺失')
            continue
        if material.get('unit') != row['unit']:
            issue('UNIT_MISMATCH', 'order_baseline_bom', row['id'], 'unit', '冻结用料与当前物料单位不同，不做隐式换算')
        bom = refs.get('bom', {}).get(row['source_bom_id'])
        expected = baseline.frozen_bom(row, link)
        if bom and any(bom.get(f) != expected[f] for f in ('product_id', 'material_id', 'assembly_level')):
            issue('MATERIAL_IDENTITY_INVALID', 'bom', row['source_bom_id'], '', '原BOM编号当前对应不同产品、物料或分支')
        route = refs.get('routes', {}).get(row['route_id'])
        if not route or any(route.get(f) != v for f, v in baseline.frozen_route(row, link).items()):
            issue('ROUTE_MISMATCH', 'routes', row['route_id'], '', '执行路线与冻结绑定不一致，不能沿用现有人机任务')
        required = joint_schedule.requirement(link['plan_qty'], row['unit_qty'], row['scrap_allowance'], row['quantum'])
        # Computed analysis values, never inserted as imported business facts.
        demand_rows.append(dict(id=row['id'], snapshot_row_id=row['id'], link_id=link['id'], job_id=link['job_id'], product_id=link['product_id'],
                                bom_id=row['source_bom_id'], route_id=row['route_id'], material_id=row['material_id'], material_name=material.get('name', row['material_id']),
                                unit=row['unit'], bom_version=row['version'], bom_qty=joint_schedule.quantity(number(row['unit_qty'])),
                                scrap_allowance=joint_schedule.quantity(number(row['scrap_allowance'])), quantum=joint_schedule.quantity(number(row['quantum'])),
                                calculated_qty=joint_schedule.quantity(required), basis='冻结快照推导，非导入需求事实'))
    if current['study']['owner_id'] not in refs.get('employees', {}) or current['study']['crew_study_id'] != parent['result']['study']['id']:
        issue('SUPPLY_INVALID', 'joint_studies', current['study']['id'], '', '供给假设负责人或人机方案身份缺失')
    for error in supply_issues('joint_studies', current['study']):
        issue('SUPPLY_INVALID', 'joint_studies', current['study']['id'], error['field'], error['message'])
    supplies = joint['tables']['joint_supplies']
    if len(supplies) != current['study']['supply_count'] or len({r['id'] for r in supplies}) != len(supplies) or len(supplies) > MAX_ROWS:
        issue('SUPPLY_INVALID', 'joint_studies', current['study']['id'], 'supply_count', '供给数量不完整、重复或超出受控规模')
    for row in supplies:
        errs = supply_issues('joint_supplies', row)
        for error in errs:
            issue('SUPPLY_INVALID', 'joint_supplies', row['id'], error['field'], error['message'])
        material = refs.get('materials', {}).get(row['material_id'])
        if row['study_id'] != current['study']['id'] or not material or row['unit'] != material['unit']:
            issue('SUPPLY_INVALID', 'joint_supplies', row['id'], '', '供给身份或物料单位不一致')
        if not errs and row['kind'] == '期初假设' and finite.time(row['available_from']) > start:
            issue('SUPPLY_INVALID', 'joint_supplies', row['id'], 'available_from', '期初假设晚于试排起点')
    if problems:
        return out
    trial = schedule(study, demand_rows, {r['id']: r for r in supplies}, parent, refs, NOTICE)
    out.update(state='trial', trial=trial, comparison=compare(current, trial))
    return out
