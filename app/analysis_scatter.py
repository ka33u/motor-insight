"""Two-axis descriptive plots of existing grouped measures, without regression."""
import hashlib,math,json
from django.core.exceptions import ValidationError
from . import derived_metrics

NOTICE='每个点代表一个分组的汇总结果，点大小相同，不代表原始记录权重。横纵轴分别沿用各度量的空值与聚合规则，来源行数及各轴有效输入数单列；不能把分组点数当作原始配对样本量。缺失坐标保留在表中但不画点，重叠点不抖动、不合并。横纵轴可以有不同单位，同一轴不能混用单位；不自动换算、不拟合相关系数或推断因果。'
DYNAMIC={'measurements':{'value':'unit','raw_value':'raw_unit'},'process_readings':{'value':'unit'},'test_specs':{'lsl':'unit','usl':'unit'},'process_specs':{'lsl':'unit','usl':'unit'},'service_conditions':{'value':'unit'}}
STATIC={'products':{'price_cents':'分/台','power_kw':'kW','voltage':'V','poles':'极','standard_hours':'小时/台'},
        'bi_units':{'power_kw':'kW','voltage':'V'},'bi_order_lines':{'power_kw':'kW'},
        'order_lines':{'qty':'台','unit_price_cents':'分/台'},'quotes':{'qty':'台','unit_price_cents':'分/台'},'work_orders':{'qty':'台'}}

def validate(dataset,definition,fields,compiled):
    p=definition.get('scatter')
    if p is None and definition.get('chart')!='scatter':return
    if definition.get('chart')!='scatter':raise ValidationError('散点坐标定义仅用于散点图')
    if not isinstance(p,dict) or set(p)!={'x','y'}:raise ValidationError('散点图需要横轴和纵轴度量')
    if not definition.get('dimension'):raise ValidationError('散点图需要明确的点分组维度')
    if definition.get('pivot'):raise ValidationError('散点图不能同时配置透视列')
    keys={f'm{i}' for i in range(len(definition['metrics']))}|{c['key'] for c in compiled}
    if any(not isinstance(v,str) or v not in keys for v in p.values()) or p['x']==p['y']:raise ValidationError('请选择两个不同且存在的数值度量')
    for key in p.values():
        if key.startswith('d'):continue
        m=definition['metrics'][int(key[1:])]
        if m['agg'] not in ['count','distinct'] and fields[m['field']]['type'] not in ['int','float']:raise ValidationError('散点坐标必须是数值度量，日期或文本最值请使用表格')
        if m['agg']=='ratio':derived_metrics.metric_unit(dataset,m,fields)
    for key in p.values():unit(dataset,definition,fields,compiled,key,[])

def dependencies(definition,compiled,key):
    return next(c['refs'] for c in compiled if c['key']==key) if key.startswith('d') else [key]

def required(definition,compiled,key):
    out=set()
    for ref in dependencies(definition,compiled,key):
        m=definition['metrics'][int(ref[1:])]
        if m['agg']!='count':out.add(m['field'])
        if m['agg']=='ratio':out.add(m['denominator'])
    return out

def unit(dataset,definition,fields,compiled,key,source):
    units={}
    for ref in dependencies(definition,compiled,key):
        m=definition['metrics'][int(ref[1:])]
        if m['agg'] in ['count','distinct']:continue
        for f in [m['field']]+([m['denominator']] if m['agg']=='ratio' else []):
            uf=fields[f].get('unit_field') or DYNAMIC.get(dataset,{}).get(f)
            if uf:
                values={r.get(uf) for r in source if r.get(f) is not None}
                if any(not isinstance(v,str) or not v.strip() for v in values):raise ValidationError('散点坐标的计量单位缺失，请核对来源')
                if len(values)>1:raise ValidationError('同一散点坐标轴混合不同单位，请筛选一种单位后分析')
                units[ref]=next(iter(values),'待有数据后确认')
    if key.startswith('d'):return next(c['unit'] for c in compiled if c['key']==key)
    m=definition['metrics'][int(key[1:])]
    if m['agg']=='ratio':return '%'
    if key in units:return units[key]
    if m['agg'] not in ['count','distinct'] and m.get('field') in STATIC.get(dataset,{}):return STATIC[dataset][m['field']]
    try:
        v=derived_metrics.metric_unit(dataset,m,fields)
        for label,value in derived_metrics.ATOMS.items():
            if value==v:return label
        for a in derived_metrics.ATOMS:
            for b in derived_metrics.ATOMS:
                if derived_metrics.parse_unit(a+'/'+b)==v:return a+'/'+b
    except ValidationError:pass
    raise ValidationError('散点度量字段尚未登记统一单位，请选择已有单位约定的字段、语义模型或派生指标')

def guard(source,definition):
    from .analysis_engine import group_key
    identities={}
    for row in source:
        key=group_key(row,definition)
        if not definition.get('grouping_ref') and definition.get('grain','value')=='value':
            value=row.get(definition['dimension']);identity=json.dumps([type(value).__name__,value],ensure_ascii=False,default=str)
            if key in identities and identities[key]!=identity:raise ValidationError('分组显示名称对应不同原始值，请先建立明确的业务分组')
            identities[key]=identity
        else:identities[key]=key
    if len(identities)>1000:raise ValidationError('散点超过1000个分组，请缩小范围；未截断计算')

def calculate(dataset,definition,fields,compiled,groups,rows,measures,revision):
    source=[r for values in groups.values() for r in values];axes={}
    for side,key in definition['scatter'].items():
        axes[side]={'key':key,'label':next(m['label'] for m in measures if m['key']==key),'unit':unit(dataset,definition,fields,compiled,key,source)}
    points=[]
    for row in rows:
        values={side:row[a['key']] for side,a in axes.items()}
        if any(v is not None and (type(v) not in [float,int] or not math.isfinite(v)) for v in values.values()):raise ValidationError('散点坐标包含无法显示的数值，请核对计算')
        valid={side:sum(all(r.get(f) is not None for f in required(definition,compiled,a['key'])) for r in groups[row['dimension']]) for side,a in axes.items()}
        reason='、'.join('横轴' if side=='x' else '纵轴' for side,v in values.items() if v is None)
        points.append({'key':hashlib.sha256(row['dimension'].encode()).hexdigest(),'dimension':row['dimension'],**values,'row_count':row['row_count'],'valid_inputs':valid,'plotted':not reason,'reason':reason+'无有效结果，详见口径及分子分母' if reason else ''})
    return {'axes':axes,'points':points,'plotted':sum(p['plotted'] for p in points),'omitted':sum(not p['plotted'] for p in points),'notice':NOTICE,'revision':revision}

def selection(result,key):
    if not isinstance(key,str):raise ValidationError('散点分组身份无效')
    point=next((p for p in result['scatter']['points'] if p['key']==key),None)
    if point is None:raise ValidationError('所选散点分组不存在；未回退全部范围')
    return point

def export_rows(result):
    from .analysis_quantiles import evidence
    samples={r['dimension']:r for r in result['rows']}
    s=result['scatter'];axes=s['axes']
    return [['分组','横轴：'+axes['x']['label'],'横轴单位','纵轴：'+axes['y']['label'],'纵轴单位','来源行数','横轴完整输入行数','纵轴完整输入行数','是否绘点','说明']]+[
      [p['dimension'],p['x'],axes['x']['unit'],p['y'],axes['y']['unit'],p['row_count'],p['valid_inputs']['x'],p['valid_inputs']['y'],p['plotted'],'；'.join(x for x in [p['reason'],evidence(samples.get(p['dimension'],{}))] if x)] for p in s['points']]
