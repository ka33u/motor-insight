"""Two-axis aggregates. Totals always aggregate source objects, never displayed cells."""
import hashlib,json
from collections import defaultdict
from django.core.exceptions import ValidationError
from . import business_groups

NOTICE='行合计、列合计和总计均从各自来源记录重算；均值、中位数、分位数、去重数、比率及派生值不能直接相加。无对象不补零；零分母、缺失输入和单位冲突单独说明。每次最多200行×50列，超过时请缩小范围。'
COMPARE_NOTICE='透视表分别展示两侧完整矩阵，不计算跨范围单元格差值；请先核对配置、样本与单位。'

def receipt(dataset,definition,scope):
    from . import analytics,metric_registry,bi_scope
    from .topic_workspace import digest
    return {'data':list(analytics.revision()),'calculation':metric_registry.calculation_hash(dataset),'definition':digest(definition),'scope':digest(bi_scope.validate_scope(scope)),'as_of':analytics.AS_OF}

def validate(definition,fields):
    p=definition.get('pivot')
    if p is None and definition.get('chart')!='pivot':return
    if not isinstance(p,dict) or set(p)-{'dimension','grain'}:raise ValidationError('透视列定义无效')
    dim=p.get('dimension');grain=p.get('grain','value')
    if not isinstance(dim,str) or dim not in fields:raise ValidationError('请选择可访问的透视列字段')
    if grain not in ['value','day','month'] or grain!='value' and fields[dim]['type'] not in ['date','datetime']:raise ValidationError('透视列日期粒度无效')
    if not definition.get('dimension'):raise ValidationError('透视分析需要行维度')
    if (dim,grain)==(definition['dimension'],definition.get('grain','value')) and not definition.get('grouping_ref'):raise ValidationError('透视行列不能使用完全相同的维度与粒度')

def axis(row,definition,column=False):
    d=definition['pivot'] if column else definition
    value=row.get(d['dimension'])
    if not column and d.get('grouping_ref'):
        value=business_groups.group(value,d);kind='group'
    else:kind='missing' if value is None else type(value).__name__
    if value is not None and d.get('grain') in ['day','month']:value=str(value)[:10 if d['grain']=='day' else 7]
    # Missing, the literal word 未填写, and margin rows are distinct identities.
    text=json.dumps([kind,value],ensure_ascii=False,sort_keys=True)
    key=hashlib.sha256(text.encode()).hexdigest()
    label='未填写' if value is None else str(value)
    if kind!='missing' and label=='未填写':label+='（原文）'
    return {'key':key,'label':label}

def axes(rows,definition):
    rr={};cc={}
    for row in rows:
        a=axis(row,definition);b=axis(row,definition,True)
        rr[a['key']]=a;cc[b['key']]=b
        if len(rr)>200 or len(cc)>50:raise ValidationError('透视超过200行或50列，请筛选后重试；未截断计算')
    order=lambda d:sorted(d.values(),key=lambda v:(v['label'],v['key']))
    row_axis=order(rr)
    if definition.get('grouping_ref'):
        labels=business_groups.order({v['label']:[] for v in row_axis},definition)
        rank={x:i for i,x in enumerate(labels)};row_axis.sort(key=lambda v:rank[v['label']])
    return row_axis,order(cc)

def select(rows,definition,selection,pivot=None):
    if not isinstance(selection,dict) or set(selection)!={'row','column'}:raise ValidationError('透视来源需要完整行列选择')
    rr,cc=(pivot['rows'],pivot['columns']) if pivot else axes(rows,definition)
    for key,items in [('row',rr),('column',cc)]:
        value=selection[key]
        if value is not None and (not isinstance(value,str) or value not in {a['key'] for a in items}):raise ValidationError('所选透视行列不存在，请重新运行；未回退全部范围')
    return [r for r in rows if all(selection[k] is None or axis(r,definition,c)['key']==selection[k] for k,c in [('row',False),('column',True)])]

def calculate(dataset,definition,fields,compiled,source):
    from .analysis_engine import aggregate_group
    rr,cc=axes(source,definition);rg=defaultdict(list);cg=defaultdict(list);cells=defaultdict(list)
    for row in source:
        a=axis(row,definition)['key'];b=axis(row,definition,True)['key'];rg[a].append(row);cg[b].append(row);cells[a,b].append(row)
    keys=[f'm{i}' for i in range(len(definition['metrics']))]+[d['key'] for d in compiled]
    def calc(rows,row=None,column=None,label='总计'):
        out={'dimension':label,'row':row,'column':column,'row_count':len(rows),'empty':not rows,'blocked':'','components':[],'derived_notes':[]}
        if not rows:return {**out,**{k:None for k in keys},'reason':'无来源对象'}
        try:
            for m in definition['metrics']:
                uf=fields.get(m.get('field'),{}).get('unit_field')
                if uf and m['agg'] not in ['count','distinct'] and any(not r.get(uf) for r in rows if r.get(m.get('field')) is not None):raise ValidationError('计量单位缺失，暂停聚合')
            values,parts,notes=aggregate_group(dataset,definition,fields,compiled,rows,label)
            for i,m in enumerate(definition['metrics']):
                if values['m'+str(i)] is None:notes.append({'metric':'m'+str(i),'reason':'分母为零或没有完整分子分母' if m['agg']=='ratio' else '度量值全部缺失'})
            units={f'm{i}':next(iter({r.get(fields[m['field']]['unit_field']) for r in rows if r.get(m['field']) is not None}),'') for i,m in enumerate(definition['metrics']) if fields.get(m.get('field'),{}).get('unit_field') and m['agg'] not in ['count','distinct','ratio']}
            units.update({key:q['unit'] for key,q in values.get('quantiles',{}).items() if q['unit']})
            return {**out,**values,'units':units,'components':parts,'derived_notes':notes,'reason':'；'.join(n.get('reason','') for n in notes)}
        except ValidationError as e:
            return {**out,**{k:None for k in keys},'blocked':'；'.join(e.messages),'reason':'；'.join(e.messages)}
    row_totals=[calc(rg[a['key']],a['key'],label=a['label']) for a in rr]
    if definition.get('sort') in ['asc','desc']:
        key=definition.get('display_metric','m0');valid=sorted([r for r in row_totals if r[key] is not None],key=lambda r:r[key],reverse=definition['sort']=='desc')
        row_totals=valid+[r for r in row_totals if r[key] is None];rank={r['row']:i for i,r in enumerate(row_totals)};rr.sort(key=lambda a:rank[a['key']])
    return {'rows':rr,'columns':cc,'column_label':fields[definition['pivot']['dimension']]['label'],
      'cells':[calc(cells[a['key'],b['key']],a['key'],b['key'],a['label']+' / '+b['label']) for a in rr for b in cc],
      'row_totals':row_totals,'column_totals':[calc(cg[b['key']],column=b['key'],label=b['label']) for b in cc],
      'grand_total':calc(source),'notice':NOTICE}

def export_rows(result):
    from .analysis_quantiles import evidence
    p=result['pivot'];rr={a['key']:a['label'] for a in p['rows']};cc={a['key']:a['label'] for a in p['columns']}
    rows=[['结果类型',result['dimension_label'],p['column_label'],*[m['label'] for m in result['measures']],'来源行数','说明']]
    for kind,items in [('交叉单元格',p['cells']),('行合计',p['row_totals']),('列合计',p['column_totals']),('总计',[p['grand_total']])]:
        for cell in items:rows.append([kind,rr.get(cell['row'],'全部'),cc.get(cell['column'],'全部'),*[cell[m['key']] for m in result['measures']],cell['row_count'],'；'.join(x for x in [cell['reason'],evidence(cell)] if x)])
    return rows
