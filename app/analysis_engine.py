"""Restricted declarative analysis: no SQL strings, eval, or user code."""
from collections import defaultdict
from decimal import Decimal
from django.core.exceptions import ValidationError
from .models import Record
from .schema import SCHEMAS
from .semantic_schema import SEMANTIC_SCHEMAS
from . import semantic,bi_scope,derived_metrics,business_groups
from .access import allowed,permitted_fields
from . import analysis_quantiles

OPS={'eq','ne','contains','gte','lte'}
AGGS={'count','sum','avg','min','max','distinct','ratio',*analysis_quantiles.AGGS}

def validate_definition(user,dataset,definition,allow_inactive=False):
    from .metric_registry import resolve
    if not isinstance(definition,dict):raise ValidationError('分析定义必须为对象')
    normalized,_=resolve(user,dataset,definition,allow_inactive=allow_inactive)
    return validate_raw_definition(user,dataset,normalized)

def validate_raw_definition(user,dataset,definition):
    if not allowed(user,dataset):raise ValidationError('没有该数据集的分析权限')
    fields={f['name']:f for f in permitted_fields(user,dataset)}
    dimension=definition.get('dimension')
    if dimension and dimension not in fields:raise ValidationError('分组字段不可用')
    business_groups.resolve(user,dataset,definition)
    from .analysis_drill import levels
    levels(user,dataset,definition,fields)
    metrics=definition.get('metrics',[])
    if not isinstance(metrics,list) or not 1<=len(metrics)<=5:raise ValidationError('需要1至5个指标')
    for metric in metrics:
        if not isinstance(metric,dict):raise ValidationError('指标定义必须为对象')
        if 'label' in metric and (not isinstance(metric['label'],str) or not 1<=len(metric['label'].strip())<=200):raise ValidationError('度量名称需为1至200字')
        agg=metric.get('agg');field=metric.get('field')
        if agg not in AGGS:raise ValidationError('不支持的聚合方式')
        analysis_quantiles.validate(metric,fields)
        if agg!='count' and field not in fields:raise ValidationError('指标字段不可用')
        if agg in ['sum','avg','ratio'] and fields[field]['type'] not in ['int','float']:raise ValidationError('数值聚合只适用于数值字段')
        if agg=='ratio':
            denominator=metric.get('denominator')
            if denominator not in fields or fields[denominator]['type'] not in ['int','float']:raise ValidationError('比率需要可用的数值分母字段')
        if agg in ['min','max'] and fields[field]['type']=='bool':raise ValidationError('布尔值不适用于最值')
    filters=definition.get('filters',[])
    if not isinstance(filters,list) or len(filters)>10:raise ValidationError('最多10个筛选条件')
    for item in filters:
        if not isinstance(item,dict):raise ValidationError('筛选条件必须为对象')
        field=fields.get(item.get('field'))
        if not field or item.get('op') not in OPS:raise ValidationError('筛选字段或运算符不可用')
        if item['op']!='contains' and field['type'] in ['int','float']:
            try:
                if not Decimal(str(item.get('value'))).is_finite():raise ValueError()
            except Exception:raise ValidationError('数值筛选需要有效数字')
    if definition.get('chart','bar') not in ['bar','line','table','donut','pivot','scatter']:raise ValidationError('图形类型不可用')
    compiled=derived_metrics.compile_definitions(dataset,definition,fields)
    display=definition.get('display_metric','m0')
    keys=[f'm{i}' for i in range(len(metrics))]+[x['key'] for x in compiled]
    if display not in keys:raise ValidationError('请选择存在的图形主指标')
    if definition.get('sort','dimension') not in ['dimension','asc','desc']:raise ValidationError('排序方式不可用')
    if definition.get('chart')=='donut' and (display.startswith('d') or metrics[int(display[1:])]['agg'] not in ['count','sum']):raise ValidationError('占比图仅适用于可加总的记录数或总量；派生值、比率、均值和去重数请用柱图、折线或表格')
    if definition.get('grain','value') not in ['value','day','month']:raise ValidationError('日期粒度不可用')
    if definition.get('grain','value')!='value' and (not dimension or fields[dimension]['type'] not in ['date','datetime']):raise ValidationError('日期粒度仅适用于日期字段')
    if definition.get('chart','bar') not in ['table','pivot'] and any(m['agg'] in ['min','max'] and fields[m['field']]['type'] not in ['int','float'] for m in metrics):raise ValidationError('非数值最值请使用表格呈现')
    from .analysis_pivot import validate
    validate(definition,fields)
    from .analysis_scatter import validate as validate_scatter
    validate_scatter(dataset,definition,fields,compiled)
    return definition

def matches(row,filters,fields):
    for f in filters:
        value=row.get(f['field']);expected=f.get('value');op=f['op']
        if value is None:return False
        if fields[f['field']]['type'] in ['int','float'] and op!='contains':
            try:value=Decimal(str(value));expected=Decimal(str(expected))
            except Exception:return False
        elif fields[f['field']]['type']=='bool':
            expected=str(expected).lower() in ['true','1','是'];value=bool(value)
        else:value=str(value);expected=str(expected)
        if op=='eq' and value!=expected:return False
        if op=='ne' and value==expected:return False
        if op=='contains' and str(expected).lower() not in str(value).lower():return False
        if op=='gte' and value<expected:return False
        if op=='lte' and value>expected:return False
    return True

def selected_rows(user,dataset,definition,scope=None,drill_path=None):
    definition=validate_definition(user,dataset,definition)
    fields={f['name']:f for f in permitted_fields(user,dataset)}
    source=semantic.rows(dataset) if dataset in SEMANTIC_SCHEMAS else list(Record.objects.filter(dataset=dataset).values_list('values',flat=True))
    scoped,scope_info=bi_scope.apply(dataset,source,scope)
    selected=[r for r in scoped if matches(r,definition.get('filters',[]),fields)]
    if drill_path is not None:
        from .analysis_drill import select
        selected=select(user,dataset,definition,selected,drill_path)
    return selected,len(source),scope_info

def group_key(row,definition):
    dimension=definition.get('dimension');grain=definition.get('grain','value')
    key=row.get(dimension) if dimension else '全部'
    if definition.get('grouping_ref'):return business_groups.group(key,definition)
    if key is None:key='未填写'
    if grain in ['day','month']:key=str(key)[:10 if grain=='day' else 7]
    return str(key)

def aggregate_group(dataset,definition,fields,compiled,rows,key):
    components=[];derived_notes=[]
    out={'dimension':key,'row_count':len(rows)};raw={};incomplete={}
    for i,m in enumerate(definition['metrics']):
        vals=[r.get(m.get('field')) for r in rows if r.get(m.get('field')) is not None]
        agg=m['agg']
        unit_field=fields.get(m.get('field'),{}).get('unit_field')
        if unit_field and agg not in ['count','distinct'] and len({r.get(unit_field) for r in rows if r.get(m.get('field')) is not None})>1:raise ValidationError(f'{key}组混合了不同计量单位，请按单位或物料分组后分析')
        if agg=='count':v=len(rows)
        elif agg=='distinct':v=len(set(vals))
        elif agg=='ratio':
            if dataset=='bi_resource_day' and {m['field'],m['denominator']}=={'busy_minutes','available_minutes'} and any(r.get('integrity')!='可计算' for r in rows):
                raise ValidationError('此范围有资源容量或事件时间冲突，排班占用率暂停计算；请先核查资源日明细')
            numerator=sum((Decimal(str(r[m['field']])) for r in rows if r.get(m['field']) is not None and r.get(m['denominator']) is not None),Decimal(0))
            denominator=sum((Decimal(str(r[m['denominator']])) for r in rows if r.get(m['field']) is not None and r.get(m['denominator']) is not None),Decimal(0))
            v=numerator/denominator*100 if denominator else None
            components.append({'dimension':key,'metric_index':i,'numerator':float(numerator),'denominator':float(denominator),'valid_rows':sum(r.get(m['field']) is not None and r.get(m['denominator']) is not None for r in rows),'excluded_null_rows':sum(r.get(m['field']) is None or r.get(m['denominator']) is None for r in rows)})
        elif not vals:v=None
        elif agg in analysis_quantiles.AGGS:
            v,detail=analysis_quantiles.calculate(dataset,m,fields,rows)
            out.setdefault('quantiles',{})[f'm{i}']=detail
        elif agg in ['sum','avg']:
            total=sum((Decimal(str(v)) for v in vals),Decimal(0));v=total if agg=='sum' else total/len(vals)
        else:v=min(vals) if agg=='min' else max(vals)
        raw[f'm{i}']=v
        if agg in analysis_quantiles.AGGS and not vals:
            v,detail=analysis_quantiles.calculate(dataset,m,fields,rows)
            out.setdefault('quantiles',{})[f'm{i}']=detail
        out[f'm{i}']=(int(v) if v==v.to_integral_value() else float(v)) if isinstance(v,Decimal) else v
        required=[m.get('field')]+([m['denominator']] if agg=='ratio' else [])
        incomplete[f'm{i}']=0 if agg=='count' else sum(any(r.get(f) is None for f in required) for r in rows)
    values,notes=derived_metrics.evaluate(compiled,raw,incomplete,
        dataset=='bi_resource_day' and any(r.get('integrity')!='可计算' for r in rows))
    out.update(values);derived_notes.extend({'dimension':key,**n} for n in notes)
    return out,components,derived_notes

def run_analysis(user,dataset,definition,scope=None,drill_path=None):
    from .metric_registry import resolve
    if not isinstance(definition,dict):raise ValidationError('分析定义必须为对象')
    original=definition
    definition,metric_receipt=resolve(user,dataset,definition)
    pivot_revision=None
    if definition.get('chart') in ['pivot','scatter']:
        from .analysis_pivot import receipt
        pivot_revision=receipt(dataset,original,scope)
    source,scanned,scope_info=selected_rows(user,dataset,definition,scope,drill_path)
    if drill_path is not None:
        from .analysis_drill import at_level
        definition=at_level(definition,len(drill_path))
    fields={f['name']:f for f in permitted_fields(user,dataset)}
    if definition.get('chart')=='scatter':
        from .analysis_scatter import guard
        guard(source,definition)
    groups=defaultdict(list);matched=len(source);dimension=definition.get('dimension')
    for row in source:groups[group_key(row,definition)].append(row)
    compiled=derived_metrics.compile_definitions(dataset,definition,fields)
    result=[];components=[];derived_notes=[]
    pivot=None
    if definition.get('chart')=='pivot':
        from .analysis_pivot import calculate
        pivot=calculate(dataset,definition,fields,compiled,source)
        if receipt(dataset,original,scope)!=pivot_revision:
            from .import_review import ReviewConflict
            raise ReviewConflict('透视计算期间来源或规则变化，请重新运行')
        pivot['revision']=pivot_revision
        result=pivot['row_totals']
    for key in ([] if pivot is not None else business_groups.order(groups,definition)):
        rows=groups[key]
        out,parts,notes=aggregate_group(dataset,definition,fields,compiled,rows,key)
        components.extend(parts);derived_notes.extend(notes)
        result.append(out)
    if definition.get('chart','bar') not in ['table','pivot','scatter']:
        display=definition.get('display_metric','m0')
        for metric in ([definition['metrics'][int(display[1:])]] if display.startswith('m') else []):
            uf=fields.get(metric.get('field'),{}).get('unit_field')
            if uf and metric['agg'] not in ['count','distinct'] and len({r.get(uf) for rows in groups.values() for r in rows})>1:raise ValidationError('图形不能在同一数值轴比较件和kg等不同单位；请筛选一种单位，或使用分单位的表格')
    sort=definition.get('sort','dimension')
    display=definition.get('display_metric','m0')
    if sort in ['asc','desc']:
        valid=sorted([r for r in result if r[display] is not None],key=lambda r:r[display],reverse=sort=='desc')
        result=valid+[r for r in result if r[display] is None]
    labels=[m.get('label') or ('记录数' if m['agg']=='count' else f"{fields[m['field']]['label']} ÷ {fields[m['denominator']]['label']} (%)" if m['agg']=='ratio' else f"{fields[m['field']]['label']} · {m['agg']}") for m in definition['metrics']]
    for i,m in enumerate(definition['metrics']):
        if m['agg'] in analysis_quantiles.AGGS and not m.get('label'):labels[i]=fields[m['field']]['label']+' · '+analysis_quantiles.label(m)
    if definition.get('chart','bar') not in ['table','pivot'] and display.startswith('m'):
        m=definition['metrics'][int(display[1:])]
        if m['agg'] in analysis_quantiles.AGGS:analysis_quantiles.validate_units(dataset,m['field'],fields,source)
    measures=[{'key':f'm{i}','label':label} for i,label in enumerate(labels)]+derived_metrics.describe(compiled)
    for i,m in enumerate(definition['metrics']):
        if m['agg'] in analysis_quantiles.AGGS:measures[i].update(aggregation=m['agg'],percentile=analysis_quantiles.percent(m),method=analysis_quantiles.METHOD)
    labels=[m['label'] for m in measures]
    contract=SEMANTIC_SCHEMAS.get(dataset,{})
    grouping_receipt=business_groups.resolve(user,dataset,definition)
    scatter=None
    if definition.get('chart')=='scatter':
        from .analysis_scatter import calculate
        scatter=calculate(dataset,definition,fields,compiled,groups,result,measures,pivot_revision)
        if receipt(dataset,original,scope)!=pivot_revision:
            from .import_review import ReviewConflict
            raise ReviewConflict('散点计算期间来源或规则变化，请重新运行')
    return {**({'quantile_notice':analysis_quantiles.NOTICE} if any(m['agg'] in analysis_quantiles.AGGS for m in definition['metrics']) else {}),**({'scatter':scatter} if scatter is not None else {}),**({'pivot':pivot} if pivot is not None else {}),'rows':result[:1000],'components':[c for c in components if c['dimension'] in {r['dimension'] for r in result[:1000]}],
      'measures':measures,'display_metric':display,'display_label':next(m['label'] for m in measures if m['key']==display),
      'derived_notes':[n for n in derived_notes if n['dimension'] in {r['dimension'] for r in result[:1000]}],
      'derived_notice':derived_metrics.NOTICE if compiled else '',
      'grouping_receipt':grouping_receipt,
      'scanned':scanned,'matched':matched,'groups':len(pivot['rows']) if pivot is not None else len(groups),'truncated':len(result)>1000,'labels':labels,'dimension_label':grouping_receipt['name'] if grouping_receipt else fields[dimension]['label'] if dimension else '全部','definition':original,'resolved_definition':definition,'metric_receipt':metric_receipt,'dataset':dataset,'grain':contract.get('grain','一行一条来源业务记录'),'note':contract.get('note','按数据集字段定义计算'),'as_of':semantic.analytics.AS_OF if contract else None,'scope':scope_info}
