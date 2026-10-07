"""Typed snapshot rows and canonical, nonfinancial source projections."""
import re
from datetime import date
from decimal import Decimal
from .finite_schedule import digest
from .finite_schedule_contract import time
from .joint_schedule_contract import number

FIELDS = {
    'order_lines': ('id', 'order_id', 'product_id', 'qty', 'original_due', 'due'),
    'work_orders': ('id', 'product_id', 'planned_qty', 'bom_version', 'route_version', 'status'),
    'allocations': ('id', 'work_order_id', 'order_line_id', 'qty', 'effective'),
    'products': ('id', 'bom_version', 'route_version'),
    'bom': ('id', 'product_id', 'material_id', 'version', 'qty', 'scrap_allowance', 'effective', 'assembly_level'),
    'routes': ('id', 'product_id', 'version', 'process', 'branch', 'mandatory'),
    'materials': ('id', 'unit'),
}


def canonical(value):
    if isinstance(value, dict):
        return {k: canonical(v) for k, v in value.items()}
    if isinstance(value, list):
        return [canonical(v) for v in value]
    if type(value) in (int, float):
        result = Decimal(str(value))
        if not result.is_finite():
            raise ValueError('基线数值必须有限')
        return format(result.normalize(), 'f') if result else '0'
    return value


def signature(value):
    return digest(canonical(value))


def project(dataset, row):
    return {field: row.get(field) for field in FIELDS[dataset]}


def source_hash(dataset, row):
    return signature(project(dataset, row))


def bundle_hash(study, tables):
    return signature(dict(study={k: v for k, v in study.items() if k != 'content_hash'}, tables={ds: sorted(rows, key=lambda r: r['id']) for ds, rows in tables.items()}))


def issues(dataset, row):
    out = []
    def add(field, message):
        out.append(dict(code='ORDER_BASELINE_SOURCE', field=field, message=message))
    for field in ('version', 'link_count', 'bom_count', 'plan_qty', 'order_qty', 'allocation_qty', 'work_order_qty'):
        if field in row and (dataset == 'order_baselines' or field != 'version') and (type(row[field]) is not int or row[field] <= 0):
            add(field, '版本、台数及声明行数须为正整数')
    for field in ('unit_qty', 'scrap_allowance', 'quantum'):
        if field in row:
            try:
                number(row[field], positive=field != 'scrap_allowance')
            except (ValueError, TypeError):
                add(field, '单耗、步长须为有限正数，损耗须为有限非负数')
    for field, value in row.items():
        if field.endswith('_hash') and (not isinstance(value, str) or not re.fullmatch('[0-9a-f]{64}', value)):
            add(field, '摘要须为64位小写十六进制')
    if 'baseline_at' in row:
        try:
            time(row['baseline_at'])
        except (ValueError, TypeError):
            add('baseline_at', '基线时点须为厂内YYYY-MM-DDTHH:MM:SS')
    for field in ('original_due', 'due', 'allocation_effective', 'effective'):
        if field in row:
            try:
                if date.fromisoformat(row[field]).isoformat() != row[field]:
                    raise ValueError()
            except (ValueError, TypeError):
                add(field, '日期须为YYYY-MM-DD')
    return out
