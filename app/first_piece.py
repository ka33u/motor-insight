"""Read-only first-piece evidence over existing, normally imported Excel facts."""
from collections import Counter
from pathlib import Path
from . import process_quality as pq, metrology as mt

STATES = {'ready': '所列证据齐备', 'waiting': '到期待检', 'future': '尚未到期',
          'out': '实测有超限', 'missing': '必检有漏项', 'metrology': '计量依据待核对', 'attention': '检验资料待核对'}
NOTICE = '合成演练：粒度为首件应检计划，按当前已导入事实核对至业务截止。证据齐备仅指最新非作废实测齐项且在模拟限值内、所列计量登记适用且未命中登记影响；不是复核签字、首件批准、整批合格或生产放行。真实证书原件和测量能力仍需独立核验。'
TABLES = tuple(dict.fromkeys([*pq.TABLES, *mt.TABLES]))


def rule_hash():
    return mt.digest({p: (Path(__file__).parent/p).read_text() for p in
                      ('first_piece.py', 'first_piece_data.py', 'first_review.py', 'first_review_schema.py', 'process_quality.py', 'metrology.py')})


def analyze(data, cutoff):
    quality = pq.ProcessQuality(data, pq.filters({}), cutoff)
    meter = mt.Metrology(data, cutoff, cutoff)
    rows, details = [], {}
    for key, obj in sorted(quality.plans.items()):
        source = obj['row']
        if source['stage'] != '首件':
            continue
        row = dict(source)
        last = next((e for e in obj['executions'] if e['row']['id'] == row['latest_id']), None)
        measures = []
        for reading in last['values'] if last else []:
            m = meter.index.get('process:'+reading['id'])
            fields = ('id', 'measured', 'instrument_id', 'use_id', 'calibration_id', 'calibration_state', 'impact_state', 'review_state', 'notice_ids', 'issues')
            evidence = {f: m.get(f) for f in fields} if m else dict(calibration_state='unknown_use', impact_state='unknown', issues=['未找到计量核对结果'])
            evidence['ready'] = bool(m and m['calibration_state'] in ('valid', 'not_required') and m['impact_state'] == 'none' and not m['issues'])
            measures.append(dict(reading=reading, metrology=evidence))
        problems = list(row['issues'])
        if problems or not row['ordering_valid']:
            state = 'attention'
        elif not last:
            state = 'waiting' if row['state'] == '到期待检' else 'future'
        elif last['row']['out']:
            state = 'out'
        elif last['row']['missing']:
            state = 'missing'
        elif last['row']['state'] != '齐项且范围内' or not measures:
            state = 'attention'
        elif any(not r['metrology']['ready'] for r in measures):
            state = 'metrology'
        else:
            state = 'ready'
        row.update(evidence_state=state, evidence_label=STATES[state], latest_out=last['row']['out'] if last else None,
                   latest_missing=last['row']['missing'] if last else None, meter_attention=sum(not r['metrology']['ready'] for r in measures),
                   measured_items=len(measures), approval='未提供正式首件批准记录')
        sources = list(obj['sources'])
        for e in measures:
            m = meter.index.get('process:'+e['reading']['id'])
            if m:
                sources.extend(m['sources'])
        details[key] = dict(row=row, measures=measures, executions=obj['executions'], expected=obj['expected'], sources=mt.unique_sources(sources))
        rows.append(row)
    return dict(rows=rows, details=details, summary=summary(rows), as_of=cutoff, notice=NOTICE,
                calibration_labels=mt.CAL_STATES, impact_labels=mt.IMPACT_STATES)


def summary(rows):
    counts = Counter(r['evidence_state'] for r in rows)
    return dict(plans=len(rows), **{k: counts[k] for k in STATES},
                work_orders=len({r['work_order_id'] for r in rows if r.get('work_order_id')}),
                measurements=sum(r['measured_items'] for r in rows))


def targets(data, first, study, cutoff):
    """Candidate discovery, never a product/batch release or coverage assertion."""
    if not study:
        raise ValueError('未找到投产条件方案')
    idx = {ds: {r['id']: r for r in data.get(ds, [])} for ds in ('routes', 'work_orders')}
    rows = []
    for clearance in sorted(data.get('launch_clearances', []), key=lambda r: r['id']):
        if clearance.get('study_id') != study['id']:
            continue
        route = idx['routes'].get(clearance.get('route_id'), {})
        wo = idx['work_orders'].get(clearance.get('work_order_id'), {})
        same_order = [r for r in first['rows'] if r.get('work_order_id') == wo.get('id')]
        candidates = [r for r in same_order if route and wo and route.get('product_id') == wo.get('product_id')
                      and route.get('version') == wo.get('route_version')
                      and (r.get('product_id'), r.get('route_version'), r.get('process'), r.get('branch')) ==
                      (route.get('product_id'), route.get('version'), route.get('process'), route.get('branch'))]
        valid = bool(route and wo and route.get('product_id') == wo.get('product_id') and route.get('version') == wo.get('route_version'))
        rows.append(dict(id=clearance['id'], work_order_id=clearance['work_order_id'], route_id=clearance['route_id'],
                         process=route.get('process'), branch=route.get('branch'), clearance_status=clearance['status'],
                         state='attention' if not valid else 'candidates' if candidates else 'missing',
                         plan_ids=[r['id'] for r in candidates], ready_candidates=sum(r['evidence_state'] == 'ready' for r in candidates),
                         other_route_plans=len(same_order)-len(candidates),
                         reason='工单配置或路线版本不符' if not valid else '候选计划需按批次、设备、换型及首件触发范围人工对应；未确认覆盖或批准' if candidates else '未找到同工单、同配置、同路线版本、同工序分支的首件应检计划'))
    return dict(study=dict(id=study['id'], name=study['name']), rows=rows, as_of=cutoff,
                summary=dict(rows=len(rows), **{s: sum(r['state'] == s for r in rows) for s in ('missing', 'candidates', 'attention')}),
                notice='开工准备与首件放量分阶段核对。此表仅按开工质量条件逐行查找候选计划，不判断该工序是否必须首件，也不证明批次覆盖。无候选不阻止首件试制；禁止借用其他工单的历史实测认定放量依据齐备。')
