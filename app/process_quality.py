"""Inspection evidence for explicit plans, not production or quality approval.

Plans, inspection executions, and readings have different grains. Selecting the
first/latest execution precedes validity filtering, so bad evidence cannot be
silently replaced by a better result. Specification end dates are exclusive.
"""
from collections import defaultdict,Counter
from datetime import date,datetime
from math import isfinite
from statistics import median
from . import analytics
from .models import Record
from .engineering import refs,unique_sources,safe

NEW_TABLES=['process_specs','process_check_plans','process_checks','process_readings']
TABLES=NEW_TABLES+['operations','work_orders','products','batches','units','equipment','employees','routes']
STATES={'all':'全部计划','pending':'到期待检','out':'最新有超限','missing':'最新有漏项','pass':'最新齐项且范围内','attention':'有资料核对事项','future':'尚未到期'}
NOTE='合成模拟数据，所有参数限值仅供功能演练，不是生产工艺标准。日期按应检计划时间选队列；检验仅统计至业务截止。首件、巡检、首次和复查分开；范围内不等于首件批准、整批合格或出厂放行。'

def filters(q):
    keys=['from','to','family','product','process','branch','kind','equipment','q','spec','mode','bin','stage','tab']
    if set(q)-set(keys+['page']):raise ValueError('不支持的工序检验筛选')
    f={k:q.get(k,'') for k in keys};f.update(tab=q.get('tab','plans'),stage=q.get('stage','all'),mode=q.get('mode','latest'))
    if f['tab'] not in ['plans','parameters'] or f['stage'] not in STATES or f['mode'] not in ['first','latest','all']:raise ValueError('工作区、状态或执行口径无效')
    if f['kind'] not in ['','首件','巡检']:raise ValueError('检验类型无效')
    if any(not isinstance(v,str) or len(v)>150 for v in f.values()):raise ValueError('筛选内容无效')
    for k in ['from','to']:
        if f[k] and date.fromisoformat(f[k]).isoformat()!=f[k]:raise ValueError('日期须为YYYY-MM-DD')
    if f['from'] and f['to'] and f['from']>f['to']:raise ValueError('开始日期晚于结束日期')
    if f['bin'] and (not f['bin'].isdigit() or int(f['bin'])>7 or f['tab']!='parameters' or not f['spec']):raise ValueError('区间选择无效')
    return f

def timestamp(value):
    try:
        t=datetime.fromisoformat(value)
        return t if not t.tzinfo and t.isoformat()==value else None
    except (TypeError,ValueError):return None
def day(value):
    try:return date.fromisoformat(value) if date.fromisoformat(value).isoformat()==value else None
    except (TypeError,ValueError):return None
def number(value):return type(value) in [int,float] and isfinite(value)
def group(rows,key):
    d=defaultdict(list)
    for r in rows:d[r.get(key)].append(r)
    return d

class ProcessQuality:
    def __init__(self,data,f,cutoff=None):
        self.data={k:data.get(k,[]) for k in TABLES};self.f=f;self.cutoff=cutoff or analytics.AS_OF;self.end=datetime.fromisoformat(self.cutoff)
        self.idx={ds:{r['id']:r for r in rows} for ds,rows in self.data.items()}
        self.checks=group(self.data['process_checks'],'plan_id');self.readings=group(self.data['process_readings'],'check_id')
        self.spec_groups=defaultdict(list)
        for s in self.data['process_specs']:self.spec_groups[self.signature(s)].append(s)
        self.plans={};self.orphans=[]
        for ds,parent,field in [('process_checks','process_check_plans','plan_id'),('process_readings','process_checks','check_id')]:
            self.orphans += [dict(dataset=ds,key=r['id'],problem='缺少'+parent+'引用') for r in self.data[ds] if r.get(field) not in self.idx[parent]]
        for p in self.data['process_check_plans']:self.plans[p['id']]=self.plan(p)

    @staticmethod
    def signature(s):return tuple(s.get(k) for k in ['product_id','route_version','process','branch','version'])

    def specification(self,base,when):
        group_specs=self.spec_groups[(base.get('product_id'),base.get('route_version'),base.get('process'),base.get('branch'),base.get('spec_version'))]
        issues=[];applicable=[]
        for s in group_specs:
            start=day(s.get('effective'));end=day(s.get('expires')) if s.get('expires') else None
            if not start or s.get('expires') and not end or start and end and start>=end:
                issues.append(s['id']+'生效区间无效');continue
            if when and start<=when.date() and (not end or when.date()<end):applicable.append(s)
        if not applicable:issues.append('未找到此配置、路线、分支、工序及版本的有效规范')
        if len({s.get('parameter') for s in applicable})!=len(applicable):issues.append('同参数存在重叠生效规范')
        for s in applicable:
            lo,hi=s.get('lsl'),s.get('usl')
            if (lo is None and hi is None) or any(v is not None and not number(v) for v in [lo,hi]) or number(lo) and number(hi) and lo>hi:issues.append(s['id']+'限值无效')
            if type(s.get('mandatory')) is not bool or not s.get('parameter') or not s.get('unit'):issues.append(s['id']+'参数、单位或必检定义无效')
        if applicable and not any(s.get('mandatory') is True for s in applicable):issues.append('没有必检项目，不能认定齐项')
        return applicable,issues,refs('process_specs',group_specs)

    def execution(self,c,base,plan_issues):
        issues=list(plan_issues);when=timestamp(c.get('checked'));rows=self.readings[c['id']];sources=refs('process_checks',[c])+refs('process_readings',rows)
        if not when:issues.append('检验时间无效')
        if c.get('inspector_id') not in self.idx['employees']:issues.append('检验人员档案缺失')
        else:sources+=refs('employees',[self.idx['employees'][c['inspector_id']]])
        if type(c.get('voided')) is not bool:issues.append('作废标志无效')
        if when and base.get('started') and when<timestamp(base['started']):issues.append('检验早于工序开始')
        specs,problems,ss=self.specification(base,when);issues+=problems;sources+=ss
        expected={s['id']:s for s in specs};counts=Counter(r.get('spec_id') for r in rows);values=[]
        for r in rows:
            s=expected.get(r.get('spec_id'));problems=[]
            if not s:problems.append('规范不属于当前有效配置/工序/分支/版本')
            if counts[r.get('spec_id')]>1:problems.append('同一检验中规范项目重复')
            if not number(r.get('value')):problems.append('实测值不是有限数值')
            if s and r.get('unit')!=s.get('unit'):problems.append('实测单位与规范不一致')
            bounded=s and all(v is None or number(v) for v in [s.get('lsl'),s.get('usl')])
            out=bool(bounded and number(r.get('value')) and (s.get('lsl') is not None and r['value']<s['lsl'] or s.get('usl') is not None and r['value']>s['usl']))
            values.append({**r,'parameter':s.get('parameter') if s else None,'name':s.get('name') if s else None,'lsl':s.get('lsl') if s else None,'usl':s.get('usl') if s else None,'issues':problems,'out':out if not problems else None})
            issues += [r['id']+'：'+p for p in problems]
        missing=[s for s in specs if s.get('mandatory') and not counts[s['id']]]
        out=sum(v['out'] is True for v in values)
        state='已作废' if c.get('voided') is True else '资料待核对' if issues else '超限且漏项' if out and missing else '有超限' if out else '有漏项' if missing else '齐项且范围内'
        return {'row':{**c,'issues':issues,'state':state,'missing':len(missing),'out':out,'readings':len(rows)},'values':values,'missing_specs':missing,'sources':unique_sources(sources)}

    def plan(self,p):
        issues=[];sources=refs('process_check_plans',[p]);op=self.idx['operations'].get(p.get('operation_id'),{});wo=self.idx['work_orders'].get(op.get('work_order_id'),{});prod=self.idx['products'].get(wo.get('product_id'),{})
        for ds,r in [('operations',op),('work_orders',wo),('products',prod)]:
            if not r:issues.append(ds+'来源缺失')
            else:sources+=refs(ds,[r])
        branch='整机' if op.get('object_type')=='整机' else self.idx['batches'].get(op.get('object_id'),{}).get('kind')
        objds='units' if op.get('object_type')=='整机' else 'batches';obj=self.idx[objds].get(op.get('object_id'))
        if not obj or obj.get('work_order_id')!=wo.get('id'):issues.append('报工对象与工单关系待核对')
        else:sources+=refs(objds,[obj])
        eq=self.idx['equipment'].get(op.get('equipment_id'))
        if not eq or eq.get('process')!=op.get('process'):issues.append('设备与工序不一致')
        else:sources+=refs('equipment',[eq])
        start=timestamp(op.get('started'));due=timestamp(p.get('due'))
        if not start or not due or due<start:issues.append('应检时间或工序开始无效')
        if p.get('stage') not in ['首件','巡检']:issues.append('检验类型无效')
        routes=[r for r in self.data['routes'] if r.get('product_id')==wo.get('product_id') and r.get('version')==wo.get('route_version') and r.get('process')==op.get('process') and r.get('branch')==branch]
        if len(routes)!=1:issues.append('所属路线工序不唯一或缺失')
        sources+=refs('routes',routes)
        base={**p,'process':op.get('process'),'branch':branch,'product_id':wo.get('product_id'),'route_version':wo.get('route_version'),'family':prod.get('family'),'model':prod.get('model'),'work_order_id':wo.get('id'),'equipment_id':op.get('equipment_id'),'object_id':op.get('object_id'),'object_type':op.get('object_type'),'started':op.get('started') if start else None}
        expected,problems,ss=self.specification(base,due);issues+=problems;sources+=ss
        executions=[];future_count=0
        for c in self.checks[p['id']]:
            when=timestamp(c.get('checked'))
            if when and when>self.end:future_count+=1;continue
            e=self.execution(c,base,issues);executions.append(e);sources+=e['sources']
        executions.sort(key=lambda e:(e['row'].get('checked') or '',e['row']['id']))
        effective=[e for e in executions if e['row'].get('voided') is not True]
        times=[e['row'].get('checked') for e in effective]
        if len(times)!=len(set(times)):issues.append('有效检验记录同刻并列，首次/最新顺序不明确')
        if due and due>self.end and effective:issues.append('未到期计划已检验，需核对应检窗口')
        first=effective[0] if effective else None;last=effective[-1] if effective else None
        check_issues=[e['row']['id']+'：'+x for e in effective for x in e['row']['issues']]
        current_state='资料待核对' if issues else last['row']['state'] if last else '到期待检' if due and due<=self.end else '尚未到期'
        flags=['all']+(['attention'] if issues or check_issues else [])
        if not issues:
            if not last:flags+=['pending' if due and due<=self.end else 'future']
            elif not last['row']['issues']:
                flags+=(['out'] if last['row']['out'] else [])+(['missing'] if last['row']['missing'] else [])+(['pass'] if last['row']['state']=='齐项且范围内' else [])
        row={**base,'issues':list(dict.fromkeys(issues+check_issues)),'state':current_state,'first_state':first['row']['state'] if first else '未检','latest_state':last['row']['state'] if last else '未检','first_id':first['row']['id'] if first else None,'latest_id':last['row']['id'] if last else None,'checks':len(effective),'voided':len(executions)-len(effective),'future_checks':future_count,'flags':flags,'ordering_valid':not issues}
        return {'row':row,'executions':executions,'expected':expected,'sources':unique_sources(sources)}

    def selected(self,stage=False):
        rows=[];f=self.f
        for obj in self.plans.values():
            r=obj['row'];clock=r.get('due','')[:10] if day(str(r.get('due',''))[:10]) else ''
            if any(f[k] and f[k]!=r.get(k) for k in ['family','process','branch']):continue
            if f['product'] and f['product']!=r.get('product_id') or f['equipment'] and f['equipment']!=r.get('equipment_id') or f['kind'] and f['kind']!=r.get('stage'):continue
            if f['from'] and (not clock or clock<f['from']) or f['to'] and (not clock or clock>f['to']):continue
            if f['q'] and f['q'].casefold() not in ' '.join(str(r.get(k) or '') for k in ['id','operation_id','object_id','work_order_id','product_id','model']).casefold():continue
            if stage and f['stage'] not in r['flags']:continue
            rows.append(r)
        return sorted(rows,key=lambda r:('attention' not in r['flags'],'pending' not in r['flags'],'out' not in r['flags'],str(r.get('due') or ''),r['id']))

    def summary(self,rows):return {'plans':len(rows),**{k:sum(k in r['flags'] for r in rows) for k in STATES if k!='all'},'inspected':sum(r['checks']>0 for r in rows),'first_pass':sum(r['ordering_valid'] and r['first_state']=='齐项且范围内' for r in rows),'unique_operations':len({r['operation_id'] for r in rows})}
    def breakdown(self,rows):
        return [{'process':p,**self.summary([r for r in rows if r['process']==p])} for p in sorted({r['process'] or '未匹配' for r in rows})]
    def detail(self,key):
        if key not in {r['id'] for r in self.selected(stage=True)}:raise Record.DoesNotExist()
        return self.plans[key]

    def parameters(self):
        f=self.f;selected=self.selected(stage=True);options={};samples=[];excluded=0
        for p in selected:
            obj=self.plans[p['id']]
            for s in obj['expected']:options[s['id']]=s
            effective=[c for c in obj['executions'] if c['row'].get('voided') is not True]
            chosen=effective[:1] if f['mode']=='first' else effective[-1:] if f['mode']=='latest' else effective
            for c in chosen:
                for v in c['values']:
                    if v.get('spec_id')!=f['spec']:continue
                    if not p['ordering_valid'] or c['row']['issues'] or v['issues']:excluded+=1;continue
                    samples.append({**v,'plan_id':p['id'],'check_id':c['row']['id'],'checked':c['row']['checked'],'sample':c['row']['sample'],'kind':p['stage'],'operation_id':p['operation_id'],'object_id':p['object_id'],'object_type':p['object_type'],'equipment_id':p['equipment_id'],'check_state':c['row']['state']})
        if f['spec'] and f['spec'] not in self.idx['process_specs']:raise ValueError('规范项目不存在')
        spec=self.idx['process_specs'].get(f['spec']);bins=[];values=[r['value'] for r in samples]
        if values:
            lo,hi=min(values),max(values);width=(hi-lo)/8 if hi>lo else 0
            bins=[{'index':i,'lo':lo+width*i,'hi':lo+width*(i+1),'count':0,'last':i==(7 if width else 0)} for i in range(8 if width else 1)]
            for row in samples:
                i=min(7,int((row['value']-lo)/width)) if width else 0;row['bin']=i;bins[i]['count']+=1
        kept=[r for r in samples if not f['bin'] or r['bin']==int(f['bin'])]
        return {'spec':spec,'options':sorted(options.values(),key=lambda s:s['id']),'bins':bins,'rows':kept,'summary':{'samples':len(samples),'plans':len({r['plan_id'] for r in samples}),'objects':len({(r['object_type'],r['object_id']) for r in samples}),'out':sum(r['out'] for r in samples),'min':min(values) if values else None,'max':max(values) if values else None,'median':median(values) if values else None,'excluded':excluded},'note':'必须固定配置、路线、分支、工序、规范版本和参数；仅使用所选执行中的可核对数值，漏项执行的已有有效项目可列入，作废/截止后/资料异常记录不列入。样本数是测量条数，不是产量。分布不等于过程能力。'}

def current(f):return ProcessQuality({ds:list(Record.objects.filter(dataset=ds).values_list('values',flat=True)) for ds in TABLES},f)
