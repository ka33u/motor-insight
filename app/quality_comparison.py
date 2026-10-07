"""Same-configuration descriptive comparisons; no fitted model or release decision."""
import hashlib,json
from collections import Counter,defaultdict
from decimal import Decimal
from pathlib import Path
from . import quality_board as quality,analytics
from .import_review import ReviewConflict

GROUPS={'equipment_id':'检测设备','test_day':'检测日期','assembly_day':'装配日期','work_order_id':'生产工单','stator_batch':'定子批次','rotor_batch':'转子批次'}
KINDS={'all':'全部有效测量','iqr':'组内统计离群','outside':'超出模拟规范限值'}
NOTICE='同配置、同规范项目、同版本、同单位比较。四分位数采用排序后(n−1)×p位置线性插值；箱体为Q1—Q3，中线为中位数，须线止于1.5×IQR围栏内的最远实测值，围栏外才标为统计离群。离群不等于不合格，规范超限独立判断。每条测量等权；全部会话会重复计入同一SN。小样本、分组差异和复测选择均不能证明设备、批次或人员原因；不计算过程能力或自动放行。'
BASE={'family','product_id','assembly_from','assembly_to','q','spec_id','sample','equipment_id','compare_by'}

def digest(value):return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),default=str).encode()).hexdigest()
def number(value):
    x=float(value)
    if not quality.finite(x):raise ValueError('统计结果超出可显示范围，请核对数值')
    return x
def quantile(values,p):
    if not values:return None
    position=(len(values)-1)*Decimal(p);i=int(position);fraction=position-i
    return values[i]+(values[min(i+1,len(values)-1)]-values[i])*fraction

def stats(rows,binary=False):
    if any(not quality.finite(r.get('value')) for r in rows):raise ValueError('比较样本包含无效数值')
    if len({r['id'] for r in rows})!=len(rows):raise ValueError('检测结果编号重复，暂停比较')
    values=sorted(Decimal(str(r['value'])) for r in rows);n=len(values)
    out={'n':n,'unique_units':len({r['unit_id'] for r in rows}),'outside':sum(r['result']=='超限' for r in rows),
         'small_sample':0<n<5,'min':number(values[0]) if n else None,'max':number(values[-1]) if n else None,
         **{k:None for k in ['q1','median','q3','iqr','lower_fence','upper_fence','lower_whisker','upper_whisker','mean','sample_stddev','outliers']},
         'outlier_points':[],'omitted_outlier_values':0,'binary_counts':[]}
    if binary:
        if any(v not in (0,1) for v in values):raise ValueError('二值项目只能包含0和1')
        out['binary_counts']=[{'value':v,'count':values.count(v)} for v in [0,1]];return out,set()
    if not n:return out,set()
    q1,median,q3=[quantile(values,p) for p in ['0.25','0.5','0.75']];iqr=q3-q1
    lower,upper=q1-Decimal('1.5')*iqr,q3+Decimal('1.5')*iqr
    included=[v for v in values if lower<=v<=upper];mean=sum(values)/n
    selected={r['id'] for r in rows if Decimal(str(r['value']))<lower or Decimal(str(r['value']))>upper}
    points=Counter(r['value'] for r in rows if r['id'] in selected)
    out.update({k:number(v) for k,v in dict(q1=q1,median=median,q3=q3,iqr=iqr,lower_fence=lower,upper_fence=upper,
                lower_whisker=min(included),upper_whisker=max(included),mean=mean).items()})
    out.update(sample_stddev=number((sum((v-mean)**2 for v in values)/(n-1)).sqrt()) if n>1 else None,
               outliers=len(selected),outlier_points=[{'value':v,'count':count} for v,count in sorted(points.items())[:100]],
               omitted_outlier_values=max(0,len(points)-100))
    return out,selected

def group_value(row,field):
    value=row.get(field);key=digest([type(value).__name__,value])
    label='未填写' if value is None else '空文本' if value=='' else str(value)
    if value in ('未填写','空文本'):label+='（原文）'
    return key,label

def calculate(distribution,units,compare_by):
    if compare_by not in GROUPS:raise ValueError('比较维度不可用')
    observations=[];groups=defaultdict(list);labels={};unit_map={u['id']:u for u in units}
    for r in distribution['observations']:
        u=unit_map[r['unit_id']]
        item={**r,**{f:u.get(f) for f in ['work_order_id','stator_batch','rotor_batch']},'assembly_day':u['assembly_at'][:10],'test_day':r['tested'][:10]}
        key,label=group_value(item,compare_by);item['group_key']=key;item['group_label']=label
        groups[key].append(item);labels[key]=label;observations.append(item)
    if len(groups)>500:raise ValueError('比较超过500个分组，请缩小范围；未截断统计')
    summaries=[]
    for key in sorted(groups,key=lambda k:(labels[k],k)):
        summary,ids=stats(groups[key],distribution['binary'])
        summaries.append({'key':key,'label':labels[key],**summary})
        for r in groups[key]:r['statistical_outlier']=r['id'] in ids if not distribution['binary'] else None
    overall,_=stats(observations,distribution['binary'])
    return {'groups':summaries,'overall':overall,'group_count':len(groups),'compare_by':compare_by,'compare_label':GROUPS[compare_by],
            'group_options':GROUPS,'kinds':KINDS,'observations':observations,'notice':NOTICE}

def context(query,extra=()):
    if set(query)-(BASE|set(extra)):raise ValueError('比较筛选包含未知字段')
    if hasattr(query,'lists') and any(len(v)!=1 for k,v in query.lists()):raise ValueError('比较参数不能重复')
    f=quality.filters({k:query[k] for k in ['family','product_id','assembly_from','assembly_to','q'] if k in query})
    by=query.get('compare_by','equipment_id');data=quality.current();rows=quality.cohort(data.rows,f)
    d=quality.distribution(data,rows,f['product_id'],query.get('spec_id',''),query.get('sample','first_complete'),query.get('equipment_id',''))
    comparison=calculate(d,rows,by)
    conf={**{k:f[k] for k in ['family','product_id','assembly_from','assembly_to','q']},'spec_id':d['spec']['id'],'sample':d['sample'],'equipment_id':d['equipment_id'],'compare_by':by}
    code=hashlib.sha256()
    for name in ['quality_comparison.py','quality_board.py','analytics.py']:code.update((Path(__file__).parent/name).read_bytes())
    revision=digest({'config':conf,'spec':d['spec'],'observations':comparison['observations'],'excluded':d['excluded'],
                     'cohort_units':d['cohort_units'],'data':list(analytics.revision()),'calculation':code.hexdigest(),'as_of':analytics.AS_OF})
    public={**{k:v for k,v in d.items() if k not in ['observations','bins','stats','notice']},
            **{k:v for k,v in comparison.items() if k!='observations'},'revision':revision,'config':conf,'as_of':analytics.AS_OF}
    return public,comparison['observations']

def selection(data,rows,query):
    if query.get('revision')!=data['revision']:raise ReviewConflict('比较的样本、条件或计算规则已变化，请重新比较后查看来源或导出')
    key=query.get('group','');kind=query.get('kind','all')
    if kind not in KINDS:raise ValueError('样本选择不可用')
    if key and key not in {g['key'] for g in data['groups']}:raise ValueError('所选分组不存在，未回退全部范围')
    if kind=='iqr' and data['binary']:raise ValueError('二值项目不计算箱线离群')
    chosen=[r for r in rows if not key or r['group_key']==key]
    if kind=='iqr':chosen=[r for r in chosen if r['statistical_outlier']]
    if kind=='outside':chosen=[r for r in chosen if r['result']=='超限']
    return chosen,{'group':key,'group_label':next((g['label'] for g in data['groups'] if g['key']==key),'全部分组'),
                   'kind':kind,'kind_label':KINDS[kind]}
