"""Intrinsic material-row checks; coverage and cross-source units are trial checks."""
from decimal import Decimal,InvalidOperation
from .finite_schedule_contract import time

def number(value,positive=False):
    if type(value) not in (int,float):raise ValueError('数量须为数值')
    result=Decimal(str(value))
    if not result.is_finite() or (result<=0 if positive else result<0):raise ValueError('数量须有限且满足正负要求')
    return result

def issues(dataset,row):
    out=[]
    def add(field,message):out.append(dict(code='JOINT_SOURCE',field=field,message=message))
    for field in ('binding_count','demand_count','supply_count'):
        if field in row and (type(row[field]) is not int or row[field]<0):add(field,'声明数量须为非负整数')
    for field in ('quantum','required_qty','qty','unavailable_qty'):
        if field in row:
            try:number(row[field],positive=field in ('quantum','required_qty'))
            except (ValueError,InvalidOperation):add(field,'需求/步长须为有限正数；供给及不可用量须为有限非负数')
    if dataset=='joint_supplies':
        try:time(row.get('available_from'))
        except (ValueError,TypeError):add('available_from','使用厂内YYYY-MM-DDTHH:MM:SS时间')
        if row.get('status') not in ('可预留','隔离'):add('status','物料假设状态须为可预留或隔离')
        if row.get('kind') not in ('期初假设','未来到料假设'):add('kind','供给假设类型无效')
        try:
            if number(row['unavailable_qty'])>number(row['qty']):add('unavailable_qty','不可预留量不能超过假设账面量')
        except (ValueError,InvalidOperation,KeyError):pass
    return out
