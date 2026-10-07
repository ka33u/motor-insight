"""Exact, equal-record-weight quantiles over the selected source population."""
import math
from decimal import Decimal,localcontext
from django.core.exceptions import ValidationError

AGGS={'median','percentile'}
METHOD='linear_n_minus_1'
NOTICE='中位数等于P50；分位数先对当前组的有效来源数值排序，按(n−1)×P/100在线性相邻点间插值。每条来源记录等权，不按数量加权，也不先算小组分位数再平均；结果可能不是某条实际观测值。空值排除并单列有效样本数，异常数值或混合单位暂停计算。小样本的高分位不代表稳定尾部风险；不同配置、规范或观察期间须先核对可比性。'

def validate(metric,fields):
    agg=metric.get('agg')
    if agg not in AGGS:
        if 'percentile' in metric:raise ValidationError('分位参数只能用于分位数聚合')
        return
    if not isinstance(metric.get('field'),str) or fields.get(metric.get('field'),{}).get('type') not in ['int','float']:raise ValidationError('中位数和分位数只适用于数值字段')
    if 'denominator' in metric:raise ValidationError('中位数和分位数不接受比率分母')
    if agg=='median':
        if 'percentile' in metric:raise ValidationError('中位数固定为P50，不接受额外分位参数')
    else:
        p=metric.get('percentile')
        if type(p) not in [int,float] or not 0<=p<=100 or not math.isfinite(p):raise ValidationError('分位值须为0至100的有限数字，例如90或95')

def percent(metric):return 50 if metric['agg']=='median' else metric['percentile']
def label(metric):return '中位数 P50' if metric['agg']=='median' else 'P'+format(percent(metric),'g')+' 分位数'
def as_number(v):
    if v is None:return None
    try:
        if not math.isfinite(float(v)):raise ValueError()
        n=int(v) if v==v.to_integral_value() else float(v)
    except (OverflowError,ValueError):raise ValidationError('分位数超出可显示的数值范围')
    return n

def unit_field(dataset,field,fields):
    from .analysis_scatter import DYNAMIC
    return fields[field].get('unit_field') or DYNAMIC.get(dataset,{}).get(field)

def validate_units(dataset,field,fields,rows):
    uf=unit_field(dataset,field,fields)
    supplied=[r.get(uf) for r in rows if r.get(field) is not None] if uf else []
    if any(not isinstance(u,str) or not u.strip() for u in supplied):raise ValidationError('分位数来源计量单位缺失，请核对来源')
    units=set(supplied)
    if any(not isinstance(u,str) or not u.strip() for u in units):raise ValidationError('分位数来源计量单位缺失，请核对来源')
    if len(units)>1:raise ValidationError('分位数混合了不同计量单位，请筛选一种单位或分单位列表')
    return next(iter(units),'')

def calculate(dataset,metric,fields,rows):
    field=metric['field'];values=[];unit=validate_units(dataset,field,fields,rows)
    for r in rows:
        value=r.get(field)
        if value is None:continue
        if isinstance(value,bool) or not isinstance(value,(int,float,Decimal)):raise ValidationError('分位数来源包含非数值，未静默排除异常记录')
        value=Decimal(str(value))
        if not value.is_finite():raise ValidationError('分位数来源包含非有限数值，请核对来源')
        values.append(value)
    values.sort();n=len(values);p=percent(metric)
    info={'method':METHOD,'percentile':p,'source_rows':len(rows),'valid_rows':n,'missing_rows':len(rows)-n,'weight':'每条来源记录等权','unit':unit,'lower_rank':None,'upper_rank':None,'lower_value':None,'upper_value':None,'interpolated':False}
    if not n:return None,info
    with localcontext() as ctx:
        ctx.prec=50
        position=Decimal(n-1)*Decimal(str(p))/100;lo=int(position);hi=min(lo+1,n-1);fraction=position-lo
        if not fraction:hi=lo
        value=values[lo]+fraction*(values[hi]-values[lo])
    info.update(lower_rank=lo+1,upper_rank=hi+1,lower_value=as_number(values[lo]),upper_value=as_number(values[hi]),interpolated=bool(fraction))
    as_number(value)
    return value,info

def details(rows):
    return [{'dimension':r['dimension'],'metric':key,**info} for r in rows for key,info in r.get('quantiles',{}).items()]

def evidence(cell,key=None):
    """Stable portable evidence, used in CSV alongside the unchanged numeric result."""
    import json
    values=cell.get('quantiles',{})
    if key is not None:values={key:values[key]} if key in values else {}
    return json.dumps({'notice':NOTICE,'samples':values},ensure_ascii=False,separators=(',',':')) if values else ''
