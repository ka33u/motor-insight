"""Quality investigation over a fixed assembly cohort and imported evidence.

Descriptive distributions always use one configuration, specification item and
version. They are not capability estimates, diagnoses or release instructions.
"""
from collections import Counter,defaultdict
from datetime import date
from functools import lru_cache
import math,statistics
from . import analytics,delivery
from .models import Record

STAGES={'all':'全部SN','untested':'无有效检测','incomplete':'最新检测漏项','failed':'最新检测不合格','retested':'有后续检测','release':'合格待核验放行','attention':'证据待核对'}
SAMPLES={'first_complete':'每台首次完整检测','latest':'每台最新有效检测','all_valid':'全部有效检测会话'}
NOTE='按装配日期选电机队列，检测与发货状态截至模拟快照；日期筛选不重放历史。首次检测包括漏项会话；首次完整检测可能发生在后续次数，二者分开计算。'
LIMIT_NOTE='模拟规范只供系统演练。分布仅描述已选配置、规范项目和版本的观测；设备、温度和时间差异不是因果证据，未验证过程稳定性与测量系统，不计算Cp/Cpk或自动批准放行。'

def index(rows):return {r['id']:r for r in rows}
def group(rows,key):
    out=defaultdict(list)
    for r in rows:out[r[key]].append(r)
    return out
def ref(ds,key):return {'dataset':ds,'key':key}
def finite(x):return isinstance(x,(int,float)) and not isinstance(x,bool) and math.isfinite(x)

class QualityData:
    def __init__(self,d):
        self.d=d;self.products=index(d['products']);self.specs=index(d['test_specs']);self.spec_groups=defaultdict(list)
        for sp in d['test_specs']:self.spec_groups[(sp['product_id'],sp['version'])].append(sp)
        self.measurements=group(d['measurements'],'session_id');self.raw_sessions=group(d['test_sessions'],'unit_id')
        sessions,inconsistent=analytics.quality_state(d);self.inconsistent=set(inconsistent)
        releases=group([r for r in d['releases'] if r['released']<=analytics.AS_OF],'unit_id')
        ships=index([s for s in d['shipments'] if s['shipped']<=analytics.AS_OF]);packing=group([p for p in d['shipment_units'] if p['shipment_id'] in ships],'unit_id')
        ncr=group([n for n in d['nonconformities'] if n['found']<=analytics.AS_OF],'unit_id')
        self.rows=[];self.session_index={}
        for u in sorted(d['units'],key=lambda u:u['id']):
            if u['assembly_at']>analytics.AS_OF:continue
            pid=u['product_id'];ss=[self.session(s,u) for s in sessions[u['id']]]
            self.session_index.update({s['id']:s for s in ss})
            first=ss[0] if ss else None;complete=[s for s in ss if s['calculated_complete']];fc=complete[0] if complete else None;latest=ss[-1] if ss else None
            result=latest['calculated_result'] if latest else '未检测';rr=sorted(releases[u['id']],key=lambda r:(r['released'],r['id']));release=rr[-1] if rr else None
            valid=bool(latest and not latest['issues'] and release and result=='合格' and release['status']=='批准放行' and release['session_id']==latest['id'] and release['released']>=max(latest['tested'],u['assembly_at']))
            unit_issues=list(dict.fromkeys(message for s in ss for message in s['issues']))
            if pid not in self.products:unit_issues.append('产品配置档案缺失')
            shipped=bool(packing[u['id']]);ship_rows=[ships[x] for x in sorted({p['shipment_id'] for p in packing[u['id']]})]
            if any(s['shipped']<u['assembly_at'] for s in ship_rows):unit_issues.append('发货早于装配，需核对时间')
            if shipped and not valid:unit_issues.append('已有发货记录但当前检测/放行待核验，不回退发货事实')
            state='untested' if not ss else 'incomplete' if result=='不完整' else 'failed' if result=='不合格' else 'release' if not valid else 'released'
            flags=['all',state]+(['retested'] if len(ss)>1 else [])+(['attention'] if unit_issues else [])
            raw=[s for s in self.raw_sessions[u['id']] if s['tested']<=analytics.AS_OF]
            cells=latest['cells'] if latest else []
            r={'id':u['id'],'product_id':pid,'family':self.products.get(pid,{}).get('family','未知'),'work_order_id':u['work_order_id'],'assembly_at':u['assembly_at'],'stator_batch':u.get('stator_batch'),'rotor_batch':u.get('rotor_batch'),'first_result':first['calculated_result'] if first else '未检测','first_session':first['id'] if first else None,'first_complete_result':fc['calculated_result'] if fc else None,'first_complete_session':fc['id'] if fc else None,'latest_result':result,'latest_session':latest['id'] if latest else None,'latest_equipment':latest.get('equipment_id') if latest else None,'latest_version':latest['spec_version'] if latest else None,'session_count':len(ss),'voided_count':sum(s['voided'] for s in raw),'future_session_count':sum(s['tested']>analytics.AS_OF for s in self.raw_sessions[u['id']]),'release_valid':valid,'release_id':release['id'] if release else None,'shipped':shipped,'flags':flags,'issues':unit_issues,'cells':cells,'_sessions':ss,'_raw_sessions':raw,'_releases':rr,'_shipments':ship_rows,'_packing':packing[u['id']],'_ncr':ncr[u['id']]}
            self.rows.append(r)
        self.unit_index=index(self.rows)

    def session(self,s,u):
        s=dict(s);specs=self.spec_groups[(u['product_id'],s['spec_version'])];ms=self.measurements[s['id']];by_spec=group(ms,'spec_id');issues=[];cells=[]
        if s['tested']<u['assembly_at']:issues.append('检测早于装配')
        if not any(sp['mandatory'] for sp in specs):issues.append('未找到该配置与版本的必检规范')
        if len({sp.get('test_code',sp['id']) for sp in specs})!=len(specs):issues.append('同配置规范版本存在重复项目编码')
        if s['id'] in self.inconsistent:issues.append('原始会话结论/完整性与规范重算不一致')
        for sp in specs:
            entries=by_spec.get(sp['id'],[]);mandatory=sp['mandatory'];errors=[]
            if sp.get('effective','')>s['tested'][:10]:errors.append('规范尚未生效')
            if any(sp[k] is not None and not finite(sp[k]) for k in ['lsl','usl']):errors.append('规范限值无效')
            if sp['lsl'] is not None and sp['usl'] is not None and sp['lsl']>sp['usl']:errors.append('规范上下限倒置')
            if sp['lsl'] is None and sp['usl'] is None:errors.append('未定义判定限值')
            if len(entries)>1:errors.append('同会话同项目重复结果')
            m=entries[0] if len(entries)==1 else None
            if m and (m['unit']!=sp['unit'] or not finite(m['value'])):errors.append('数值或标准单位不可比较')
            if m and m['id'] in self.inconsistent:errors.append('原始项目结论与规范重算不一致')
            if m and sp['unit']=='bool' and m['value'] not in (0,1):errors.append('二值结果必须为0或1')
            result='待核对' if errors else '缺项' if mandatory and not entries else '未测选检' if not entries else '超限' if (sp['lsl'] is not None and m['value']<sp['lsl']) or (sp['usl'] is not None and m['value']>sp['usl']) else '符合'
            if errors:issues.extend(sp.get('test_name',sp['id'])+'：'+e for e in errors)
            cells.append({'spec_id':sp['id'],'test_code':sp.get('test_code',sp['id']),'test_name':sp.get('test_name',sp['id']),'version':sp['version'],'unit':sp['unit'],'lsl':sp['lsl'],'usl':sp['usl'],'mandatory':mandatory,'value':m['value'] if m and finite(m['value']) else None,'measurement_id':m['id'] if m else None,'result':result,'issues':errors,'measurement_count':len(entries)})
        extra=[m for m in ms if m['spec_id'] not in {sp['id'] for sp in specs}]
        if extra:issues.append('存在不属于当前配置/规范版本的检测项目')
        s.update(cells=cells,issues=list(dict.fromkeys(issues)),extra_measurement_ids=[m['id'] for m in extra]);return s

    def detail(self,uid):
        r=self.unit_index.get(uid)
        if not r:raise Record.DoesNotExist()
        sources=[ref('units',uid),ref('products',r['product_id']),ref('work_orders',r['work_order_id'])];sessions=[]
        for raw in sorted(r['_raw_sessions'],key=lambda s:(s['tested'],s['attempt'],s['id'])):
            s=self.session_index.get(raw['id']);ms=self.measurements[raw['id']]
            sessions.append({**raw,'calculated_result':s['calculated_result'] if s else '作废，不参与统计','calculated_complete':s['calculated_complete'] if s else False,'cells':s['cells'] if s else [],'issues':s['issues'] if s else [],'measurements':ms})
            sources.append(ref('test_sessions',raw['id']));sources.extend(ref('measurements',m['id']) for m in ms)
            sources.extend(ref('test_specs',sp['id']) for sp in self.spec_groups[(r['product_id'],raw['spec_version'])]);sources.extend(ref('test_specs',m['spec_id']) for m in ms)
        for ds,key in [('releases','_releases'),('shipments','_shipments'),('shipment_units','_packing'),('nonconformities','_ncr')]:sources.extend(ref(ds,x['id']) for x in r[key])
        sources=list({(s['dataset'],s['key']):s for s in sources}.values())
        # Do not expose product prices, employee wages or service costs.
        product={k:v for k,v in self.products.get(r['product_id'],{}).items() if k not in ['price_cents','standard_hours']}
        return {'unit':public(r),'product':product,'sessions':sessions,'releases':r['_releases'],'shipments':[{k:s[k] for k in ['id','order_line_id','shipped','qty']} for s in r['_shipments']],'nonconformities':r['_ncr'],'sources':sources,'as_of':analytics.AS_OF,'release_rule':delivery.RELEASE_RULE,'notice':LIMIT_NOTE+' 原始检测文件名是引用，不等同原件已归档；可在检测原件工作区查看本人确认的关联。未来会话未纳入此快照。'}

def public(r):return {k:v for k,v in r.items() if not k.startswith('_')}
def filters(query,extra=()):
    allowed={'family','product_id','assembly_from','assembly_to','q','stage','page','test_code','item_state'}|set(extra)
    if set(query)-allowed:raise ValueError('不支持的质量筛选字段')
    f={k:str(query.get(k,'')).strip() for k in ['family','product_id','assembly_from','assembly_to','q']}
    if any(len(v)>150 for v in f.values()):raise ValueError('筛选内容过长')
    for k in ['assembly_from','assembly_to']:
        if f[k] and date.fromisoformat(f[k]).isoformat()!=f[k]:raise ValueError('日期应为YYYY-MM-DD')
    if f['assembly_from']>(f['assembly_to'] or '9999-12-31'):raise ValueError('装配开始日期不能晚于结束日期')
    f['stage']=query.get('stage','all')
    if f['stage'] not in STAGES:raise ValueError('质量清单状态不可用')
    f['test_code']=str(query.get('test_code','')).strip();f['item_state']=query.get('item_state','any')
    if len(f['test_code'])>100 or f['item_state'] not in ['any','exceed','missing']:raise ValueError('项目筛选不可用')
    return f
def cohort(rows,f):
    return [r for r in rows if (not f['family'] or r['family']==f['family']) and (not f['product_id'] or r['product_id']==f['product_id']) and (not f['assembly_from'] or r['assembly_at'][:10]>=f['assembly_from']) and (not f['assembly_to'] or r['assembly_at'][:10]<=f['assembly_to']) and (not f['q'] or f['q'].lower() in ' '.join(str(r.get(k) or '') for k in ['id','work_order_id','stator_batch','rotor_batch','product_id']).lower())]
def selected(rows,stage,code='',item_state='any'):
    return [r for r in rows if stage in r['flags'] and (not code or any(c['test_code']==code and (item_state=='any' or c['result']=={'exceed':'超限','missing':'缺项'}[item_state]) for c in r['cells']))]
def summary(rows):
    tested=[r for r in rows if r['session_count']];complete=[r for r in rows if r['first_complete_session']]
    first_pass=sum(r['first_result']=='合格' for r in tested);fc_pass=sum(r['first_complete_result']=='合格' for r in complete)
    evidence=sum(bool(s['issues']) for r in rows for s in r['_sessions']);blocked=bool(evidence)
    return {'units':len(rows),'tested':len(tested),'complete':len(complete),'first_pass':first_pass,'first_complete_pass':fc_pass,'first_pass_rate':None if blocked else analytics.percent(first_pass,len(tested)),'first_complete_pass_rate':None if blocked else analytics.percent(fc_pass,len(complete)),'complete_coverage':None if blocked else analytics.percent(len(complete),len(rows)),'retested':sum(r['session_count']>1 for r in rows),'recovered_after_first_fail':sum(r['first_result']=='不合格' and r['latest_result']=='合格' and r['session_count']>1 for r in rows),'voided_sessions':sum(r['voided_count'] for r in rows),'future_sessions_excluded':sum(r['future_session_count'] for r in rows),'valid_release':sum(r['release_valid'] for r in rows),'post_shipment_attention':sum(r['shipped'] and not r['release_valid'] for r in rows),'evidence_issue_sessions':evidence,'rates_paused':blocked}

def aggregate(rows,key):
    return [{key:k,**summary(rr)} for k,rr in sorted(group(rows,key).items())]
def defects(rows):
    found=defaultdict(lambda:{'units':set(),'missing':set()})
    for r in rows:
        for c in r['cells']:
            if c['result']=='超限':found[c['test_code']]['units'].add(r['id'])
            if c['result']=='缺项':found[c['test_code']]['missing'].add(r['id'])
    return sorted([{'test_code':code,'unit_count':len(v['units']),'missing_count':len(v['missing'])} for code,v in found.items()],key=lambda r:(-r['unit_count'],-r['missing_count'],r['test_code']))

def quantile(values,q):
    if not values:return None
    i=(len(values)-1)*q;lo=int(i);hi=math.ceil(i);return values[lo]+(values[hi]-values[lo])*(i-lo)

def distribution(data,rows,product_id,spec_id,sample,equipment_id=''):
    if not product_id:raise ValueError('先选择一个产品配置，再比较同规范项目')
    sp=data.specs.get(spec_id)
    if not sp or sp['product_id']!=product_id:raise ValueError('规范项目必须属于所选配置')
    if sample not in SAMPLES:raise ValueError('样本口径不可用')
    observations=[];excluded=Counter();equipment=Counter()
    for r in rows:
        ss=r['_sessions'];chosen=ss if sample=='all_valid' else [s for s in ss if s['id']==r['first_complete_session']] if sample=='first_complete' else ss[-1:]
        if not chosen:excluded['没有符合样本口径的会话']+=1
        for s in chosen:
            if s['spec_version']!=sp['version']:excluded['规范版本不同']+=1;continue
            equipment[s.get('equipment_id','未记录')]+=1
            if equipment_id and s.get('equipment_id')!=equipment_id:excluded['检测设备筛选排除']+=1;continue
            cell=next((c for c in s['cells'] if c['spec_id']==spec_id),None)
            if not cell or cell['value'] is None:excluded['所选项目缺项或重复']+=1;continue
            if s['issues'] or cell['issues']:excluded['会话证据待核验']+=1;continue
            if cell['result'] not in ['符合','超限']:excluded['项目不能判定']+=1;continue
            observations.append({'id':cell['measurement_id'],'unit_id':r['id'],'session_id':s['id'],'product_id':r['product_id'],'spec_id':spec_id,'tested':s['tested'],'equipment_id':s.get('equipment_id','未记录'),'temperature_c':s.get('temperature_c'),'value':cell['value'],'unit':sp['unit'],'result':cell['result']})
    observations.sort(key=lambda r:(r['tested'],r['session_id'],r['id']));values=sorted(r['value'] for r in observations);n=len(values);binary=sp['unit']=='bool';bins=[]
    if binary:
        bins=[{'index':i,'lower':i,'upper':i,'label':str(i),'count':sum(v==i for v in values),'upper_inclusive':True} for i in [0,1]]
        for r in observations:r['bin']=int(r['value'])
    elif n:
        low,high=values[0],values[-1]
        if low==high:bins=[{'index':0,'lower':low,'upper':high,'count':n,'upper_inclusive':True}]
        else:
            width=(high-low)/8
            bins=[{'index':i,'lower':low+width*i,'upper':high if i==7 else low+width*(i+1),'count':0,'upper_inclusive':i==7} for i in range(8)]
        for r in observations:
            b=next((b for b in bins if r['value']>=b['lower'] and (r['value']<b['upper'] or b['upper_inclusive'] and r['value']<=b['upper'])),None)
            if b is None:raise ValueError('分布边界无法归属，请核对数值精度')
            r['bin']=b['index']
            if len(bins)>1:b['count']+=1
    return {'spec':sp,'sample':sample,'sample_label':SAMPLES[sample],'equipment_id':equipment_id,'equipment_options':[{'id':k,'sessions':v} for k,v in sorted(equipment.items())],'cohort_units':len(rows),'observations':observations,'bins':bins,'excluded':dict(excluded),'stats':{'n':n,'unique_units':len({r['unit_id'] for r in observations}),'outside':sum(r['result']=='超限' for r in observations),'min':values[0] if n else None,'max':values[-1] if n else None,'mean':statistics.mean(values) if n and not binary else None,'median':quantile(values,.5) if not binary else None,'p10':quantile(values,.1) if not binary else None,'p90':quantile(values,.9) if not binary else None,'sample_stddev':statistics.stdev(values) if n>1 and not binary else None},'binary':binary,'notice':LIMIT_NOTE,'sample_note':'先为每台选择会话，再应用规范版本与设备条件；不会因设备筛选把复测改称首检。全部会话模式可重复计入同一SN。缺项/证据异常的排除数量单独列明。'}

@lru_cache(maxsize=1)
def cached(revision):return QualityData(analytics._tables(revision))
def current():return cached(analytics.revision())
