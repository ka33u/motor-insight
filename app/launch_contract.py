"""Intrinsic validation; complete-set and task checks belong to the evaluator."""
import re
from .finite_schedule_contract import time
from .order_baseline_contract import bundle_hash, signature

KINDS = ('工装', '工艺文件', '质量条件')
COUNTS = dict(launch_requirements='requirement_count', launch_tool_fits='fit_count', launch_documents='document_count', launch_clearances='clearance_count', launch_tool_blocks='block_count')


def issues(dataset, row):
    out = []
    def add(field, message):
        out.append(dict(code='LAUNCH_SOURCE', field=field, message=message))
    for field in (*COUNTS.values(), 'uses_per_unit'):
        if field in row and (type(row[field]) is not int or row[field] < 0 or field == 'requirement_count' and row[field] == 0):
            add(field, '声明行数与使用次数须为非负整数，条件行数必须大于0')
    for field in ('assessed_at', 'registered', 'valid_from', 'valid_until', 'started', 'ended'):
        if field in row:
            try:
                time(row[field])
            except (ValueError, TypeError):
                add(field, '时间须为不带时区的完整本地时间')
    for a, b in (('valid_from', 'valid_until'), ('started', 'ended')):
        if a in row and b in row and not any(x['field'] in (a, b) for x in out) and time(row[a]) >= time(row[b]):
            add(a, '区间须起点早于终点，按左闭右开核对')
    if dataset == 'launch_studies' and not re.fullmatch('[0-9a-f]{64}', str(row.get('content_hash', ''))):
        add('content_hash', '内容摘要须为64位小写十六进制')
    if dataset == 'launch_requirements':
        if row.get('kind') not in KINDS or type(row.get('applicable')) is not bool:
            add('kind', '须明确三类条件和是否适用')
        if not str(row.get('reason') or '').strip():
            add('reason', '须保留需要或不适用的依据')
        if row.get('applicable'):
            if not row.get('subject') or not row.get('version'):
                add('subject', '适用条件须指定对象及版本')
            if row.get('kind') == '工装' and (type(row.get('uses_per_unit')) is not int or row['uses_per_unit'] <= 0):
                add('uses_per_unit', '工装每台使用次数须为正整数')
        elif row.get('subject') or row.get('version') or row.get('uses_per_unit') != 0:
            add('subject', '不适用行不应带对象、版本或使用量')
        if row.get('kind') != '工装' and row.get('uses_per_unit') != 0:
            add('uses_per_unit', '非工装条件不累计工装使用次数')
    allowed = {'launch_tool_fits': ('配套有效', '禁止使用', '待核对'), 'launch_documents': ('已发布', '草稿', '作废'), 'launch_clearances': ('具备登记条件', '限制开工', '待核对')}
    if dataset in allowed and row.get('status') not in allowed[dataset]:
        add('status', '登记状态不在受控枚举中')
    return out
