"""Compare batch recipients of each material, without changing either heuristic."""
import hashlib
from decimal import Decimal
from pathlib import Path
from . import joint_comparison as comparison, joint_material_evidence as evidence

VERSION = 'joint-batch-material-v1'
NOTICE = ('按物料原编码、单位和批次核对两列整批需求；差值为优先级策略减应完成时间策略。'
          '增加/减少获配只是两次假设输出的差异，不代表物料实际转移、因果归责或交付批准。'
          '本物料全预留不等于全部物料齐套或批次排完；未预留也可能来自人机或前序受阻。')


def definition_hash():
    return hashlib.sha256((Path(__file__).read_text()+evidence.definition_hash()).encode()).hexdigest()


def build(left, right):
    if left['policy'] != 'due' or right['policy'] != 'priority':
        raise ValueError('批次获料对照的策略顺序无效')
    if any(left[k] != right[k] for k in ('study', 'crew_study', 'resource_study', 'rule_version')):
        raise ValueError('批次获料对照的方案、范围或版本不同')
    report = dict(version=VERSION, notice=NOTICE, state='paused', materials=[], rows=[], summary=None)
    if left['state'] != 'trial' or right['state'] != 'trial':
        return report
    jobs = {a['id']: (a, b) for a, b in comparison.pairs(left['jobs'], right['jobs'], fixed=comparison.JOB_FIELDS)}
    list(comparison.pairs(left['tasks'], right['tasks'], fixed=comparison.TASK_FIELDS))
    list(comparison.pairs(left['demands'], right['demands'], fixed=('job_id', 'binding_id', 'bom_id', 'route_id', 'product_id', 'material_id', 'unit', 'required_qty')))
    list(comparison.pairs(left['lots'], right['lots'], fixed=('material_id', 'unit', 'lot', 'qty', 'unavailable_qty', 'available_from', 'status', 'kind', 'reference', 'basis')))
    balances = list(comparison.pairs(left['balances'], right['balances'], identity=('material_id', 'unit'),
                    fixed=('required_qty', 'horizon_usable_qty', 'initial_supply_gap_qty', 'total_excluded_qty')))
    for a, b in balances:
        material, unit = a['material_id'], a['unit']
        l, _ = evidence.build(left, material, unit)
        r, _ = evidence.build(right, material, unit)
        rows = []
        for x, y in comparison.pairs(l['jobs'], r['jobs'], fixed=('product_id', 'qty', 'due', 'demands', 'required_qty')):
            key = x['id']
            if type(x['qty']) is not int or x['qty'] <= 0:
                raise ValueError('批次台数不是正整数')
            required = Decimal(x['required_qty'])
            delta = Decimal(y['reserved_qty'])-Decimal(x['reserved_qty'])
            needs = [d for d in l['demands'] if d['job_id'] == key]
            other = [d for d in r['demands'] if d['job_id'] == key]
            list(comparison.pairs(needs, other, fixed=('required_qty', 'task_ids', 'route_id', 'bom_id')))
            def signature(result):
                # Ignore global sequence shifts caused only by unrelated material rows.
                return sorted(tuple(v[f] for f in evidence.ALLOCATION) for v in result['allocations'] if v['job_id'] == key)
            allocation_changed = signature(l) != signature(r)
            row = dict(material_id=material, unit=unit, job_id=key, product_id=x['product_id'], qty=x['qty'], due=x['due'],
                       required_qty=evidence.text(required), reserved_delta_qty=evidence.text(delta),
                       quantity_change='more' if delta > 0 else 'less' if delta < 0 else 'same', allocation_changed=allocation_changed,
                       demand_ids=sorted(d['id'] for d in needs), task_ids=sorted({t for d in needs for t in d['task_ids']}))
            for side, job, original in [('left', x, jobs[key][0]), ('right', y, jobs[key][1])]:
                row[side] = {k: job[k] for k in ('reserved_qty', 'unreserved_qty', 'reserved_demands', 'demands')}
                row[side].update(job_state=original['state'], job_finished=original['finished'])
            rows.append(row)
        rows.sort(key=lambda row: (row['due'], row['job_id']))
        scale = max((Decimal(row['required_qty']) for row in rows), default=Decimal(0))
        for row in rows:
            row['required_percent'] = float(Decimal(row['required_qty'])/scale*100)
            for side in ('left', 'right'):
                for part in ('reserved', 'unreserved'):
                    row[side][part+'_percent'] = float(Decimal(row[side][part+'_qty'])/scale*100)
        increased = sum((Decimal(row['reserved_delta_qty']) for row in rows if row['quantity_change'] == 'more'), Decimal(0))
        decreased = -sum((Decimal(row['reserved_delta_qty']) for row in rows if row['quantity_change'] == 'less'), Decimal(0))
        delta = Decimal(b['reserved_qty'])-Decimal(a['reserved_qty'])
        if increased-decreased != delta:
            raise ValueError('批次获料变化不能核对到物料总预留量')
        report['materials'].append(dict(material_id=material, material_name=a['material_name'], unit=unit,
            jobs=len(rows), required_qty=a['required_qty'], chart_max_qty=evidence.text(scale), left_reserved_qty=a['reserved_qty'], right_reserved_qty=b['reserved_qty'],
            reserved_delta_qty=evidence.text(delta), increased_qty=evidence.text(increased), decreased_qty=evidence.text(decreased),
            more_jobs=sum(row['quantity_change'] == 'more' for row in rows), less_jobs=sum(row['quantity_change'] == 'less' for row in rows),
            allocation_only_jobs=sum(row['quantity_change'] == 'same' and row['allocation_changed'] for row in rows)))
        report['rows'].extend(rows)
    changed = [row for row in report['rows'] if row['quantity_change'] != 'same']
    report.update(state='ready', summary=dict(materials=len(balances), job_material_pairs=len(report['rows']), quantity_changed_pairs=len(changed),
        allocation_only_changed_pairs=sum(row['quantity_change'] == 'same' and row['allocation_changed'] for row in report['rows']),
        unique_quantity_changed_jobs=len({row['job_id'] for row in changed})))
    return report
