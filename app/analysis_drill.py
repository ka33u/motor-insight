"""Ordered, same-grain drill paths over the existing analysis calculations."""
from copy import deepcopy
from django.core.exceptions import ValidationError
from .access import permitted_fields

NOTICE='逐层分析保持同一来源粒度、原筛选及指标定义，每层从来源记录重算。比率、均值和去重数不能相加；返回上层恢复原范围。路径仅为分组次序，不证明各字段存在业务父子关系。'

def levels(user,dataset,definition,fields=None):
    if fields is None:fields={f['name']:f for f in permitted_fields(user,dataset)}
    extra=definition.get('drilldown',[])
    if not isinstance(extra,list) or len(extra)>3:raise ValidationError('最多配置3个后续下钻层级')
    if extra and not definition.get('dimension'):raise ValidationError('配置下钻前请选择起始分组维度')
    root={'dimension':definition.get('dimension',''),'grain':definition.get('grain','value')}
    result=[root];seen=set() if definition.get('grouping_ref') else {(root['dimension'],root['grain'])}
    for level in extra:
        if not isinstance(level,dict) or set(level)!={'dimension','grain'}:raise ValidationError('下钻层级需包含维度与日期粒度')
        if not isinstance(level['dimension'],str):raise ValidationError('下钻字段须为字段名称')
        field=fields.get(level['dimension'])
        if not field:raise ValidationError('下钻字段不存在或无权访问')
        grain=level['grain']
        if grain not in ['value','day','month']:raise ValidationError('下钻日期粒度不可用')
        if grain!='value' and field['type'] not in ['date','datetime']:raise ValidationError('下钻日期归组仅适用于日期字段')
        key=(level['dimension'],grain)
        if key in seen:raise ValidationError('下钻层级不能重复相同维度与粒度')
        seen.add(key);result.append(deepcopy(level))
    return [{**l,'label':fields.get(l['dimension'],{}).get('label','全部')+({'day':' · 按日','month':' · 按月'}.get(l['grain'],''))} for l in result]

def at_level(definition,index):
    d=deepcopy(definition)
    if index:
        d.update(d['drilldown'][index-1]);d.pop('grouping_ref',None)
    # The path was validated against the original root, not this new dimension.
    d.pop('drilldown',None)
    return d

def select(user,dataset,definition,rows,path):
    from .analysis_engine import group_key
    ls=levels(user,dataset,definition)
    if not isinstance(path,list) or len(path)>=len(ls):raise ValidationError('下钻路径超出已配置层级')
    selected=rows
    for i,value in enumerate(path):
        if not isinstance(value,str) or len(value)>2000:raise ValidationError('下钻分组值无效')
        d=at_level(definition,i);selected=[r for r in selected if group_key(r,d)==value]
        if not selected:raise ValidationError('所选分组已不存在或不属于上层范围，请返回并刷新')
    return selected
