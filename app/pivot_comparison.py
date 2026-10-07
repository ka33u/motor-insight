"""Compare complete, already aggregated matrices without reinterpreting their totals."""
import math
from decimal import Decimal

VERSION = 'pivot-comparison-v1'
NOTE = ('按行列身份对齐，两侧独有分组和空交叉格不补零；日期不自动平移。'
        '差值＝当前值－对照值，相对变化以正数对照值为分母；百分比指标只显示百分点差。'
        '行列合计与总计比较各侧从来源重算的结果，不能将格内差额直接相加。'
        '数值增减不代表好坏或因果，须核对配置、样本与单位。')


def finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def measure_unit(result, measure):
    key = measure['key']
    if measure.get('unit'):
        return measure['unit']
    if key == 'm0' and result.get('metric_receipt'):
        return result['metric_receipt']['unit']
    if key.startswith('m'):
        agg = result['resolved_definition']['metrics'][int(key[1:])]['agg']
        if agg == 'ratio':
            return '%'
        if agg == 'count':
            return '条'
        if agg == 'distinct':
            return '个'
    return '原指标单位'


def value_pair(a, b, measure, unit):
    key = measure['key']
    av, bv = (c.get(key) if c is not None else None for c in (a, b))
    au, bu = (c.get('units', {}).get(key, unit) if c is not None else unit for c in (a, b))
    reason = ''
    delta = relative = None
    if a is None or b is None:
        reason = '一侧无此行列分组，不补零'
    elif a.get('empty') or b.get('empty'):
        reason = '一侧交叉范围无来源对象，不补零'
    elif a.get('blocked') or b.get('blocked'):
        reason = '；'.join(f'{name}：{c["blocked"]}' for name, c in [('当前侧', a), ('对照侧', b)] if c.get('blocked'))
    elif not au or not bu or au != bu:
        reason = '两侧计量单位不同或未知，差值暂停'
    elif not finite(av) or not finite(bv):
        detail = '；'.join(f'{name}：{n["reason"]}' for name, c in [('当前侧', a), ('对照侧', b)]
                          for n in c.get('derived_notes', []) if n.get('metric') == key)
        reason = detail or '一侧缺少有效数值或为非数值度量'
    else:
        delta = float(Decimal(str(av)) - Decimal(str(bv)))
        if not math.isfinite(delta):
            delta = None
            reason = '差值超出数值范围'
        elif unit == '%':
            reason = '比例仅显示百分点差，不计算增长率'
        elif bv > 0:
            relative = float(Decimal(str(delta)) / Decimal(str(bv)) * 100)
            if not math.isfinite(relative):
                relative = None
                reason = '相对变化超出数值范围'
        else:
            reason = '对照值为零或负数，不计算相对变化'
    return dict(key=key, primary=av, reference=bv, primary_unit=au, reference_unit=bu,
                delta=delta, delta_unit='百分点' if unit == '%' else au,
                relative_pct=relative, reason=reason)


def compare(current, reference):
    base = dict(pivot=True, rows=[], rule_version=VERSION, note=NOTE)
    if not current.get('pivot') or not reference.get('pivot'):
        return dict(base, blocked=True, note='两侧必须都是完整透视矩阵。')
    if (current.get('truncated') or reference.get('truncated') or
            current['dataset'] != reference['dataset'] or
            current['resolved_definition'] != reference['resolved_definition'] or
            current['measures'] != reference['measures']):
        return dict(base, blocked=True, note='两侧定义不同或结果不完整，暂停逐格对照。')
    p, q = current['pivot'], reference['pivot']

    def axes(name):
        # Preserve the current result's sort; append reference-only identities.
        seen = {a['key'] for a in p[name]}
        return [*p[name], *(a for a in q[name] if a['key'] not in seen)]

    rr, cc = axes('rows'), axes('columns')
    if len(rr) > 200 or len(cc) > 50:
        return dict(base, blocked=True, note='两侧合并超过200行或50列，逐格对照暂停且未截断；仍可分侧查看完整矩阵，请缩小范围后比较。')
    measures = current['measures']

    def cell(a, b, row, column):
        return dict(row=row, column=column,
                    primary_rows=a['row_count'] if a is not None else None,
                    reference_rows=b['row_count'] if b is not None else None,
                    values=[value_pair(a, b, m, measure_unit(current, m)) for m in measures])

    def aligned(kind, keys):
        maps = [{(x['row'], x['column']): x for x in side[kind]} for side in (p, q)]
        return [cell(maps[0].get(k), maps[1].get(k), *k) for k in keys]

    matrix = dict(rows=rr, columns=cc,
                  cells=aligned('cells', [(r['key'], c['key']) for r in rr for c in cc]),
                  row_totals=aligned('row_totals', [(r['key'], None) for r in rr]),
                  column_totals=aligned('column_totals', [(None, c['key']) for c in cc]),
                  grand_total=cell(p['grand_total'], q['grand_total'], None, None))
    return dict(base, blocked=False, matrix=matrix, measures=measures,
                display_metric=current['display_metric'], dimension_label=current['dimension_label'], column_label=p['column_label'])


def export_rows(comparison):
    p = comparison['matrix']
    rr = {a['key']: a['label'] for a in p['rows']}
    cc = {a['key']: a['label'] for a in p['columns']}
    labels = {m['key']: m['label'] for m in comparison['measures']}
    rows = [['对照规则版本', '结果类型', '行身份', '列身份', comparison['dimension_label'], comparison['column_label'],
             '度量编码', '度量', '当前值', '当前单位', '对照值', '对照单位', '差值', '差值单位', '相对变化(%)',
             '当前来源行数', '对照来源行数', '说明', '计算规则']]
    for kind, items in [('交叉单元格', p['cells']), ('行合计', p['row_totals']), ('列合计', p['column_totals']), ('总计', [p['grand_total']])]:
        for c in items:
            for v in c['values']:
                rows.append([comparison['rule_version'], kind, c['row'], c['column'], rr.get(c['row'], '全部行'), cc.get(c['column'], '全部列'),
                             v['key'], labels[v['key']], v['primary'], v['primary_unit'], v['reference'], v['reference_unit'],
                             v['delta'], v['delta_unit'], v['relative_pct'], c['primary_rows'], c['reference_rows'], v['reason'], comparison['note']])
    return rows
