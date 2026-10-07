"""Model-pinned, scoped target comparisons; observations remain read-only.

Imported target revisions never mutate the model. Data completeness is an
explicit synthetic source assertion tied to exactly the selected facts.
"""
import hashlib,json,re
from copy import deepcopy
from datetime import date,datetime
from decimal import Decimal,InvalidOperation
from collections import defaultdict,Counter
from django.core.exceptions import ValidationError,PermissionDenied,ObjectDoesNotExist
from . import analytics,access,analysis_engine as engine,metric_registry,bi_scope,derived_metrics as dm
from .semantic_schema import schemas
from .models import AnalysisModel,Record

STATES={'all':'全部','met':'达标','watch':'偏差需关注','missed':'未达标','in_progress':'期间进行中','future':'尚未开始','unconfirmed':'数据待确认','no_sample':'样本不足','blocked':'规则待核对','draft':'未生效目标','history':'历史目标版本'}
NOTE='合成目标演练；重算固定模型所选度量的整个目标范围，不平均各分组结果。期间结束且资料确认与当前事实一致后才判断达标。目标值为模拟假设，不是行业基准或正式考核标准；不同单位和重叠范围不合计为综合得分。'
DATASETS=['kpi_targets','kpi_target_checks']

def digest(value):return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,default=str,separators=(',',':')).encode()).hexdigest()
def model_signature(model):return digest({'dataset':model.dataset,'definition':model.definition})
def timestamp(v):
    try:return datetime.fromisoformat(v) if isinstance(v,str) and len(v)==19 and 'T' in v else None
    except ValueError:return None
def day(v):
    try:return isinstance(v,str) and len(v)==10 and date.fromisoformat(v).isoformat()==v
    except ValueError:return False
def number(v):
    if isinstance(v,bool) or v is None:return None
    try:
        d=Decimal(str(v));return d if d.is_finite() and abs(d)<=Decimal('1e15') else None
    except (InvalidOperation,ValueError):return None
def clean(v):return None if v is None else float(v)
def visible(user,model):return access.role(user)=='admin' or model.is_public or model.owner==user.username

def comparison(actual,direction,lower,upper,margin):
    a=number(actual);lo=number(lower);hi=number(upper);m=number(margin)
    if a is None or m is None or m<0:raise ValueError('实际值或关注区间宽度无效')
    if direction=='gte':
        if lo is None or upper is not None:raise ValueError('越高越好仅填写下限')
        delta=a-lo;gap=max(-delta,Decimal(0));attainment=a/lo*100 if lo>0 and a>=0 else None
    elif direction=='lte':
        if hi is None or lower is not None:raise ValueError('越低越好仅填写上限')
        delta=a-hi;gap=max(delta,Decimal(0));attainment=None
    elif direction=='between':
        if lo is None or hi is None or lo>hi:raise ValueError('区间目标须下限不大于上限')
        delta=a-lo if a<lo else a-hi if a>hi else Decimal(0);gap=abs(delta);attainment=None
    else:raise ValueError('达标方向无效')
    return {'delta':clean(delta),'gap':clean(gap),'attainment':clean(attainment),'candidate_state':'met' if gap==0 else 'watch' if gap<=m else 'missed'}

def target_contract(t):
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,80}',str(t.get('series',''))):raise ValueError('目标系列编码无效')
    for key in ['version','model_id','model_version','minimum_samples']:
        if type(t.get(key)) is not int or t[key]<1:raise ValueError('版本、模型号和最少样本须为正整数')
    if not day(t.get('period_start')) or not day(t.get('period_end')) or t['period_start']>t['period_end']:raise ValueError('目标期间无效')
    if not all(t.get(k) for k in ['name','department','owner','basis','reason']):raise ValueError('目标责任、依据与版本说明不完整')
    for k in ['model_signature','calculation_hash']:
        if not re.fullmatch(r'[a-f0-9]{64}',str(t.get(k,''))):raise ValueError('模型或计算摘要无效')
    comparison(0,t.get('direction'),t.get('lower'),t.get('upper'),t.get('warning_margin'))
    dm.parse_unit(t.get('unit'))
    if t.get('status') not in ['已确认','草稿','作废']:raise ValueError('目标状态无效')

def evaluation(user,t,model,as_of=analytics.AS_OF):
    if not visible(user,model):raise PermissionDenied('没有关联模型的访问权限')
    if model.version!=t['model_version'] or model_signature(model)!=t['model_signature']:raise ValueError('模型版本或定义已变化，需核对并另建目标版本')
    if metric_registry.calculation_hash(model.dataset)!=t['calculation_hash']:raise ValueError('计算规则已变化，需复核目标版本')
    original=engine.validate_definition(user,model.dataset,model.definition)
    if not bi_scope.contract(model.dataset)['date']:raise ValueError('模型没有明确的期间日期口径')
    definition=deepcopy(model.definition)
    for k in ['grouping_ref','drilldown','pivot','scatter']:definition.pop(k,None)
    definition.update(dimension='',grain='value',chart='table',sort='dimension',display_metric=t['measure'])
    fields={f['name']:f for f in access.permitted_fields(user,model.dataset)}
    metric_key=t['measure']
    if not isinstance(metric_key,str) or not re.fullmatch('[md][0-4]',metric_key):raise ValueError('度量编号无效')
    if metric_key.startswith('m'):
        i=int(metric_key[1:])
        if i>=len(original['metrics']):raise ValueError('度量不存在')
        expected=dm.metric_unit(model.dataset,original['metrics'][i],fields)
        used_metrics=[original['metrics'][i]]
    else:
        compiled=dm.compile_definitions(model.dataset,original,fields);found=next((x for x in compiled if x['key']==metric_key),None)
        if not found:raise ValueError('派生度量不存在')
        expected=dm.parse_unit(found['unit'])
        used_metrics=[original['metrics'][int(ref[1:])] for ref in found['refs']]
    requested=dm.parse_unit(t['unit'])
    if expected[0]!=requested[0]:raise ValueError('目标单位与模型度量不一致')
    factor=expected[1]/requested[1]
    end=min(t['period_end'],as_of[:10]);scope={'from':t['period_start'],'to':end}
    for k in ['family','customer_id']:
        if t.get(k):scope[k]=t[k]
    if scope['from']>scope['to']:
        return {'actual':None,'matched':0,'valid_rows':0,'missing_rows':0,'data_signature':None,'scope':scope,'date_label':bi_scope.contract(model.dataset)['date_label'],'definition':definition,'rows':[],'model_name':model.name,'dataset':model.dataset,'components':[],'unit_factor':str(factor),'note':'目标期间尚未开始'}
    date_field=bi_scope.DATES[model.dataset][0]
    if fields.get(date_field,{}).get('type')=='datetime':
        definition['filters']=[*definition.get('filters',[]),{'field':date_field,'op':'lte','value':as_of}]
    result=engine.run_analysis(user,model.dataset,definition,scope=scope)
    selected,_,_=engine.selected_rows(user,model.dataset,definition,scope=scope)
    required={f for m in used_metrics if m['agg']!='count' for f in ([m.get('field')]+([m['denominator']] if m['agg']=='ratio' else []))}
    missing=sum(any(r.get(f) is None for f in required) for r in selected)
    scalar=result['rows'][0].get(metric_key) if result['rows'] else None
    if scalar is not None and number(scalar) is None:raise ValueError('目标只能比较有限数值度量')
    # Bind to all reviewed selected values, not just the latest timestamp/count.
    signature=digest({'model_signature':t['model_signature'],'calculation_hash':t['calculation_hash'],'measure':metric_key,'unit':t['unit'],'scope':scope,'rows':sorted(selected,key=lambda r:str(r['id']))})
    return {'actual':clean(Decimal(str(scalar))*factor) if scalar is not None else None,'matched':result['matched'],'valid_rows':len(selected)-missing,'missing_rows':missing,'data_signature':signature,'scope':scope,'date_label':result['scope']['date_label'],'definition':definition,'rows':selected,'model_name':model.name,'dataset':model.dataset,'components':result['components'],'quantiles':result['rows'][0].get('quantiles',{}) if result['rows'] else {},'unit_factor':str(factor),'note':result['note']}

class Targets:
    def __init__(self,user,tables=None,models=None,as_of=analytics.AS_OF):
        if not access.can_edit(user):raise PermissionDenied('经营目标资料与工作台仅开放管理员和经营分析师')
        self.user=user;self.as_of=as_of;self.now=timestamp(as_of);self.models=models if models is not None else {m.pk:m for m in AnalysisModel.objects.all()}
        if tables is None:tables={ds:list(Record.objects.filter(dataset=ds).values_list('values',flat=True)) for ds in DATASETS}
        self.targets={r['id']:r for r in tables.get('kpi_targets',[])};self.checks=defaultdict(list);self.series=defaultdict(list);self.errors=defaultdict(list);self.latest={};self.rows={};self.cache={};self.global_issues=[]
        for c in tables.get('kpi_target_checks',[]):
            self.checks[c.get('target_id')].append(c)
            if c.get('target_id') not in self.targets:self.global_issues.append('数据确认缺目标：'+c['id'])
        for t in self.targets.values():self.series[t.get('series')].append(t)
        for key,versions in self.series.items():
            good=[]
            for t in versions:
                try:target_contract(t)
                except (ValueError,ValidationError) as e:self.errors[t['id']].append(str(e));continue
                previous=self.targets.get(t.get('supersedes_id'))
                chain_ok=bool((t['version']==1 and not t.get('supersedes_id')) or (previous and previous['series']==key and previous['version']==t['version']-1))
                same_scope=not previous or all(previous.get(k)==t.get(k) for k in ['period_start','period_end','family','customer_id','model_id','measure','unit'])
                approval=timestamp(t.get('approved'))
                if not chain_ok or not same_scope:self.errors[t['id']].append('目标版本链或适用范围不一致')
                if t['status']=='已确认' and not approval:self.errors[t['id']].append('目标确认时间无效')
                if previous and timestamp(previous.get('approved')) and approval and approval<timestamp(previous['approved']):self.errors[t['id']].append('后续目标确认时间早于前一版本')
                if t['status']=='已确认' and approval and approval<=self.now:good.append(t)
            if len({t.get('version') for t in versions})!=len(versions):
                for t in versions:self.errors[t['id']].append('同系列存在重复目标版本')
            # A bad version chain must not silently fall back to a convenient target.
            if any(self.errors[t['id']] for t in versions):
                for t in versions:
                    if not self.errors[t['id']]:self.errors[t['id']].append('同系列有版本问题，需共同核对')
            if good:self.latest[key]=max(good,key=lambda t:t['version'])['id']
        for t in self.targets.values():self.rows[t['id']]=self.build(t)

    def calculate(self,t):
        model=self.models.get(t['model_id'])
        if not model:raise ValueError('关联分析模型不存在')
        key=digest({k:t.get(k) for k in ['model_id','model_version','model_signature','calculation_hash','measure','unit','period_start','period_end','family','customer_id']})
        if key not in self.cache:self.cache[key]=evaluation(self.user,t,model,self.as_of)
        return self.cache[key]

    def build(self,t):
        issues=list(self.errors[t['id']]);current=self.latest.get(t.get('series'))==t['id'];history=not current and t.get('status')=='已确认' and timestamp(t.get('approved')) and t['approved']<=self.as_of
        r={**t,'current':current,'history':bool(history),'state':'blocked','actual':None,'delta':None,'gap':None,'attainment':None,'candidate_state':None,'matched':None,'issues':issues,'checks':[],'data_signature':None,'date_label':None,'model_name':None,'dataset':None,'unit_factor':None,'coverage_ok':False,'retroactive':bool(timestamp(t.get('approved')) and t['approved']>str(t.get('period_end'))+'T23:59:59')}
        if issues:return r
        try:
            e=self.calculate(t);r.update({k:v for k,v in e.items() if k not in ['rows','definition']})
            if r['actual'] is not None:r.update(comparison(r['actual'],t['direction'],t['lower'],t['upper'],t['warning_margin']))
        except (ValidationError,ValueError,PermissionDenied,KeyError,TypeError) as error:
            r['issues'].append('; '.join(error.messages) if isinstance(error,ValidationError) else str(error));return r
        applicable=[];end=t['period_end']+'T23:59:59'
        if r.get('missing_rows'):r['issues'].append('所选度量必需字段存在空缺；实际值仅含有效部分')
        for c in sorted(self.checks[t['id']],key=lambda c:(str(c.get('confirmed')),c['id'])):
            when=timestamp(c.get('confirmed'));through=timestamp(c.get('through'));reason=''
            if c.get('voided') is True:reason='作废确认'
            elif when and when>self.now:reason='未来确认'
            elif c.get('voided') is not False or not when or not through or through>when or (timestamp(t.get('approved')) and when<timestamp(t['approved'])) or c.get('status') not in ['完整','待补'] or not c.get('owner') or not c.get('note'):reason='确认资料无效';r['issues'].append('数据确认资料待核对：'+c['id'])
            else:applicable.append(c)
            r['checks'].append({**c,'exclusion':reason})
        latest=max((c['confirmed'] for c in applicable),default=None);last=[c for c in applicable if c['confirmed']==latest]
        if len(last)>1:r['issues'].append('同一时点多份数据确认，结论待核对')
        elif last:
            c=last[0];r['coverage_ok']=bool(c['status']=='完整' and c['through']>=end and c['data_signature']==r['data_signature'] and not r['issues'])
            if c['data_signature']!=r['data_signature']:r['issues'].append('事实已变化或确认摘要不匹配，请重新核对资料')
            if c['through']<end:r['issues'].append('资料覆盖尚未到目标期末')
        else:r['issues'].append('缺少有效的数据完整性确认')
        r['delta_unit']='百分点' if t['unit']=='%' else t['unit']
        r['state']='history' if history else 'draft' if not current else 'future' if t['period_start']>self.as_of[:10] else 'in_progress' if end>self.as_of else 'no_sample' if r['actual'] is None or r['valid_rows']<t['minimum_samples'] else 'unconfirmed' if not r['coverage_ok'] else r['candidate_state']
        # Until all gates pass, numeric difference is descriptive, not a lamp.
        if r['state'] not in ['met','watch','missed']:r['candidate_state']=None
        return r

    def detail(self,key):
        if key not in self.rows:raise ObjectDoesNotExist()
        return self.rows[key]
    def selected(self,f):
        rows=[]
        for r in self.rows.values():
            if f['history']!='all' and r['history']:continue
            if f['department'] and r['department']!=f['department']:continue
            if f['state']!='all' and r['state']!=f['state']:continue
            if f['q'] and f['q'].casefold() not in ' '.join(str(r.get(k) or '') for k in ['id','series','name','owner','model_name','basis']).casefold():continue
            rows.append(r)
        priority={s:i for i,s in enumerate(['missed','watch','unconfirmed','blocked','no_sample','in_progress','future','met','draft','history'])}
        return sorted(rows,key=lambda r:(priority[r['state']],-date.fromisoformat(r['period_end']).toordinal() if day(r.get('period_end')) else 0,r['department'],r['series'],-r['version']))

def params(p):
    f={k:str(p.get(k,'') or '').strip() for k in ['q','department']};f.update(state=str(p.get('state','all')),history=str(p.get('history','current')))
    if f['state'] not in STATES or f['history'] not in ['current','all'] or len(f['q'])>200:raise ValueError('目标筛选不可用')
    return f
def summary(rows):
    eligible=[r for r in rows if r['state'] in ['met','watch','missed']]
    return {'rows':len(rows),'eligible':len(eligible),'met':sum(r['state']=='met' for r in eligible),'watch':sum(r['state']=='watch' for r in eligible),'missed':sum(r['state']=='missed' for r in eligible),'pending':sum(r['state'] not in ['met','watch','missed','history','draft'] for r in rows),'history':sum(r['state']=='history' for r in rows),'states':dict(Counter(r['state'] for r in rows))}
def safe(r):return {k:v for k,v in r.items() if k not in ['checks','components','quantiles']}
