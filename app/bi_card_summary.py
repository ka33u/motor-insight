"""Selected-measure summaries from complete authorized source populations.

Never total group outputs. Existing engines still calculate the formulas; only
the selected base measure or its derived dependencies enter this extra summary.
"""
import hashlib,json,math,re
from copy import deepcopy
from pathlib import Path
from decimal import Decimal
from django.core.exceptions import ValidationError
from django.core.serializers.json import DjangoJSONEncoder
from . import access,analysis_engine as engine,derived_metrics as dm,metric_registry
from . import bi_field_catalog as field_catalog
from .import_review import ReviewConflict

REVISION='bi-card-population-summary-v1'
NOTICE='摘要从整张卡的全部已筛选来源对象重算所选度量，不相加或平均图中的分组值；不同卡粒度与日期可能不同，不能跨卡合计。空缺、混合单位及分母为零分别说明；摘要不判断达标、不证明因果，也不自动认证临时分析模型。'

def digest(value):return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,default=str,separators=(',',':')).encode()).hexdigest()
def message(ex):return '；'.join(ex.messages) if isinstance(ex,ValidationError) else str(ex)
def algorithm(dataset):return digest([REVISION,hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),metric_registry.calculation_hash(dataset),field_catalog.revision()])

def calculation(definition,key,fields,dataset):
    """Prune unused measures without changing referenced arithmetic or units."""
    d=dict(dimension='',grain='value',chart='table',sort='dimension',filters=deepcopy(definition.get('filters',[])))
    if key.startswith('m'):
        i=int(key[1:]);d['metrics']=[deepcopy(definition['metrics'][i])];output='m0';used={key};measure=definition['metrics'][i]
    else:
        i=int(key[1:]);item=definition['derived'][i];_,refs=dm.parse_formula(item['expression'],len(definition['metrics']));used=set(refs)
        old=sorted(int(r[1:]) for r in refs);mapping={f'm{index}':f'm{n}' for n,index in enumerate(old)}
        d['metrics']=[deepcopy(definition['metrics'][index]) for index in old]
        d['derived']=[{**deepcopy(item),'expression':re.sub(r'\bm[0-4]\b',lambda m:mapping[m.group()],item['expression'])}]
        output='d0';measure=dict(agg='derived',expression=item['expression'],unit=item['unit'])
    d['display_metric']=output
    required={field for index,m in enumerate(definition['metrics']) if f'm{index}' in used and m['agg']!='count' for field in [m.get('field'),*([m['denominator']] if m['agg']=='ratio' else [])]}
    return d,output,used,required,measure

def metric_unit(dataset,metric,fields,rows):
    if metric['agg']=='derived':return metric['unit']
    names=[metric.get('field'),*([metric['denominator']] if metric['agg']=='ratio' else [])]
    dynamic=[]
    for name in names:
        f=fields.get(name,{})
        if f.get('unit_field') and metric['agg'] not in ('count','distinct'):
            values={r.get(f['unit_field']) for r in rows if r.get(name) is not None}
            if len(values)!=1 or next(iter(values)) in (None,''):raise ValidationError('所选度量的单位混合或缺失，整范围摘要暂停；可先按单位筛选')
            dynamic.append(next(iter(values)))
    if dynamic:
        if metric['agg']=='ratio' and (len(dynamic)!=2 or len(set(dynamic))!=1):raise ValidationError('比率两侧单位不能核对，摘要暂停')
        return '%' if metric['agg']=='ratio' else dynamic[0]
    if metric['agg'] in ('min','max') and fields.get(metric.get('field'),{}).get('type') in ('str','date','datetime'):return '时间/文本'
    try:unit=dm.metric_unit(dataset,metric,fields)
    except ValidationError:
        explicit=[fields.get(name,{}).get('unit') for name in names]
        if metric['agg']=='ratio' and all(explicit) and len(set(explicit))==1:return '%'
        if metric['agg']!='ratio' and explicit[0]:return explicit[0]
        raise ValidationError('所选度量尚无可核对的单位约定，摘要暂停；原分组分析保留')
    matches=[k for k,v in dm.ATOMS.items() if v==unit]
    if not matches:raise ValidationError('摘要单位约定尚不能呈现')
    return matches[0]

def build(user,model,result,scope):
    ds=model['dataset'];key=result['display_metric'];definition=result['resolved_definition'];fields={f['name']:f for f in access.permitted_fields(user,ds)}
    fields=deepcopy(fields)
    for name,f in fields.items():
        unit=field_catalog.unit_info(ds,name,fields)
        if unit['kind']=='row':f['unit_field']=unit['unit_field']
        elif unit['kind']=='fixed':f['unit']=unit['unit']
    rows,scanned,meta=engine.selected_rows(user,ds,model['definition'],scope)
    if len(rows)!=result['matched']:raise ReviewConflict('摘要与图形的来源范围发生变化，请重新运行专题')
    d,output,used,required,measure=calculation(definition,key,fields,ds)
    missing=sum(any(r.get(k) is None for k in required) for r in rows)
    out=dict(format_revision=REVISION,algorithm=algorithm(ds),key=key,label=result['display_label'],measure=measure,
        value=None,unit=None,state='blocked',reason='',source_rows=len(rows),valid_rows=len(rows)-missing,missing_rows=missing,
        source_scanned=scanned,grain=result['grain'],scope=deepcopy(meta),as_of=result['as_of'],
        model_id=model['id'],model_version=model['version'],definition_hash=digest(model['definition']),
        metric_receipt=json.loads(json.dumps(result.get('metric_receipt'),cls=DjangoJSONEncoder)),definition_status='published' if result.get('metric_receipt') else 'analysis',
        population_digest=digest(sorted(rows,key=lambda r:str(r['id']))),numerator=None,denominator=None,components=[],quantile=None,notes=[],notice=NOTICE)
    if not scanned:out.update(state='no_source',reason='当前数据集没有来源对象；不以零代替未采集资料');return out
    if not rows and measure['agg'] not in ('count','distinct'):out.update(state='no_sample',reason='来源已存在，但本范围没有有效样本');return out
    try:
        out['unit']=metric_unit(ds,measure,fields,rows)
        receipt=out['metric_receipt']
        if receipt and receipt['unit']!=out['unit']:raise ValidationError('发布定义的结果单位与计算单位不一致，摘要暂停；需核对指标定义')
        # Derived expressions may depend on dynamically unit-bearing raw fields;
        # enforce their entire selected population before evaluating arithmetic.
        for m in d['metrics']:metric_unit(ds,m,fields,rows)
        compiled=dm.compile_definitions(ds,d,fields)
        values,components,notes=engine.aggregate_group(ds,d,fields,compiled,rows,'全部所选对象')
        value=values.get(output)
        if isinstance(value,(float,int)) and (isinstance(value,bool) or not math.isfinite(value)):raise ValidationError('摘要不是有限有效数值')
        out.update(value=value,components=components,quantile=values.get('quantiles',{}).get(output),notes=[n['reason'] for n in notes if n['metric']==output])
        if measure['agg']=='ratio':out.update(numerator=components[0]['numerator'],denominator=components[0]['denominator'])
        out['state']='partial' if missing else 'undefined' if value is None else 'empty' if not rows else 'ready'
        out['reason']='仅有效部分；缺失字段不补零，差值比较暂停' if missing else '分母为零或所选计算没有有效结果' if value is None else '已知来源下所选对象为空' if not rows else '整范围来源重算，未汇总分组显示值'
        if out['notes']:out['reason']='；'.join(out['notes'])
    except (ValidationError,ValueError,TypeError,KeyError,ArithmeticError) as ex:out.update(state='blocked',value=None,reason=message(ex),unit=out.get('unit'))
    return out

def compare(current,reference):
    result=dict(blocked=True,primary=current.get('value') if current else None,reference=reference.get('value') if reference else None,delta=None,relative_pct=None,delta_unit=None,reason='')
    if not current or not reference:result['reason']='本次或旧快照未保存整范围摘要；不从分组结果补算历史摘要';return result
    for field in ('format_revision','algorithm','key','measure','unit','grain','definition_hash','model_id','model_version','metric_receipt'):
        if current.get(field)!=reference.get(field):result['reason']='摘要算法、模型、指标版本、单位或所选度量不同，差值暂停';return result
    if any(x['state'] not in ('ready','empty') for x in (current,reference)):result['reason']='一侧无来源、缺样本、仅有效部分或计算待核对，差值暂停';return result
    a,b=result['primary'],result['reference']
    if type(a) not in (float,int) or type(b) not in (float,int):result['reason']='所选摘要是时间或文本，不能形成数值改善差值';return result
    delta=float(Decimal(str(a))-Decimal(str(b)));relative=float((Decimal(str(a))/Decimal(str(b))-1)*100) if b>0 and current['unit']!='%' else None
    if not math.isfinite(delta) or relative is not None and not math.isfinite(relative):result['reason']='差值超出有限数值范围';return result
    result.update(blocked=False,delta=delta,relative_pct=relative,delta_unit='百分点' if current['unit']=='%' else current['unit'],reason='同定义独立重算的描述性差值；范围可以重叠，配置构成不同不证明效率或原因')
    return result

def attach(user,model,card,config):
    value={'primary':build(user,model,card['primary'],config['scope']),'reference':None,'comparison':None,'notice':NOTICE}
    if card.get('reference'):
        value['reference']=build(user,model,card['reference'],config['reference_scope']);value['comparison']=compare(value['primary'],value['reference'])
    card['scope_summary']=value
