"""Reconcile imported production returns with original issue movements.

Net issued quantity is a document balance, never physical WIP or consumption.
No inventory mutation and no implied quality release.
"""
from collections import defaultdict
from datetime import datetime
from decimal import Decimal, InvalidOperation

VERSION = 'production-return-links-v1'
NOTICE = ('生产退料的来源单号须指向原生产领料流水；同工单、同物料、同批次，退料晚于领料，'
          '同一原领料的累计退料不得超过领料量。净领料＝累计领料－可核对退料；不是在制实存或实际消耗。'
          '退回库存只按原流水入账一次，可用性另按目标库位状态及库存证据核对。')
FIELDS = ('id','material_id','lot','location','occurred','movement','qty_signed','work_order_id','reference')


def number(value):
    if type(value) not in (int, float, Decimal):
        raise ValueError('数量须为数值')
    try:
        result = Decimal(str(value))
    except InvalidOperation:
        raise ValueError('数量无效') from None
    if not result.is_finite():
        raise ValueError('数量须为有限数值')
    return result


def stamp(value):
    if not isinstance(value, str):
        raise ValueError('业务时间缺失')
    try:
        result = datetime.fromisoformat(value)
    except ValueError:
        raise ValueError('业务时间无效') from None
    if result.tzinfo or result.isoformat(timespec='seconds') != value:
        raise ValueError('业务时间须为本地年月日时分秒')
    return result


def amount(value):
    return format(value.normalize(), 'f') if value else '0'


def reconcile(data, cutoff):
    until = stamp(cutoff)
    movements = {}
    for row in data.get('inventory_movements', []):
        key = row.get('id')
        if not isinstance(key,str) or not key or key in movements:
            raise ValueError('库存流水身份缺失或重复，退料核对未计算')
        movements[key] = row
    materials = {r['id']:r for r in data.get('materials', [])}
    works = {r['id']:r for r in data.get('work_orders', [])}
    returns, groups = {}, defaultdict(list)
    for key, row in sorted(movements.items()):
        if row.get('movement') != '生产退料':
            continue
        issues = []
        try:
            at = stamp(row.get('occurred'))
            if at > until:
                continue
        except ValueError as error:
            at = None; issues.append(str(error))
        source = movements.get(row.get('reference'))
        report = {f:row.get(f) for f in FIELDS}
        report.update(issue_id=row.get('reference'),issue=None,unit=materials.get(row.get('material_id'),{}).get('unit'),
                      issues=issues,verified=False,return_qty=None)
        returns[key] = report
        if source is None or source.get('movement') != '生产领料':
            issues.append('来源单号未指向原生产领料流水')
            continue
        groups[source['id']].append(report)
        report['issue'] = {f:source.get(f) for f in FIELDS}
        try:
            original_at = stamp(source.get('occurred'))
            if at is None or original_at >= at or original_at > until:
                issues.append('退料须晚于原领料；同刻不推断先后')
        except ValueError as error:
            issues.append('原领料：'+str(error))
        for field,label in (('work_order_id','工单'),('material_id','物料'),('lot','批次')):
            if not row.get(field) or row.get(field) != source.get(field):
                issues.append('退料与原领料'+label+'不一致')
        if source.get('work_order_id') not in works or source.get('reference') != source.get('work_order_id'):
            issues.append('原领料工单或来源单号待核对')
        material = materials.get(source.get('material_id'))
        if not material or not material.get('unit'):
            issues.append('原领料物料单位缺失')
        if not row.get('location') or not source.get('location'):
            issues.append('领退料库位缺失')
        try:
            issued, returned = -number(source.get('qty_signed')), number(row.get('qty_signed'))
            if issued <= 0 or returned <= 0:
                issues.append('领料须为负增减，退料须为正增减')
            if material and material.get('unit') == '件' and any(q != q.to_integral_value() for q in (issued,returned)):
                issues.append('整件领退料数量须为整数')
            if returned > 0:
                report['return_qty'] = amount(returned)
        except ValueError as error:
            issues.append(str(error))
    by_issue = {}
    for key, rows in sorted(groups.items()):
        source = movements[key]
        valid = all(not r['issues'] for r in rows)
        total = sum((number(Decimal(r['return_qty'])) for r in rows),Decimal(0)) if valid else None
        issued = -number(source['qty_signed']) if valid else None
        if valid and total > issued:
            for row in rows:row['issues'].append('同一原领料的累计退料超过领料量')
            valid = False
        if not valid:
            for row in rows:
                if not row['issues']:row['issues'].append('同一原领料存在其他待核对退料，未部分抵扣')
        for row in rows:row['verified'] = valid
        by_issue[key] = dict(issue_id=key,return_ids=[r['id'] for r in rows],verified=valid,
                            issued_qty=amount(issued) if valid else None,returned_qty=amount(total) if valid else None,
                            net_issued_qty=amount(issued-total) if valid else None,
                            issues=list(dict.fromkeys(e for r in rows for e in r['issues'])))
    return dict(version=VERSION,notice=NOTICE,cutoff=cutoff,returns=returns,by_issue=by_issue)
