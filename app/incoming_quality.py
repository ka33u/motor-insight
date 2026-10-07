"""Sample characteristic evidence; never replaces original IQC or disposition."""
from collections import defaultdict,Counter
from datetime import datetime,date
from math import isfinite
from statistics import mean,median
from . import analytics,supply

NEW_TABLES=['incoming_specs','incoming_check_plans','incoming_checks','incoming_readings']
STATES={'all':'全部来料检验','no_plan':'缺特性计划','pending':'尚无有效登记','attention':'资料待核对','missing':'最新样本有漏项','out':'最新齐项且见超限','pass':'最新齐项且范围内','disagreement':'样本与原不良数不同'}
NOTE='全部合成模拟，特性限值不是生产验收标准。以原来料检验为批次对象，日期按原检验登记选队列。逐样本范围判定、原批次结论和实际入库分别保留；抽样结果不外推整批不良数。'
BOUNDARY='首/最新登记先按测量顺序选择，再校验；无效最新记录不回退。作废和截止后登记不计算，同刻并列暂停首/最新选择。单一物料、特性、单位、规范版本才可比较数值；复查不是独立批次，未计算Cpk、控制限、供应商质量评分或正式批准。'
def timestamp(v):
    try:
        t=datetime.fromisoformat(v);return t if not t.tzinfo and t.isoformat(timespec='seconds')==v else None
    except (TypeError,ValueError):return None
def day(v):
    try:return date.fromisoformat(v) if date.fromisoformat(v).isoformat()==v else None
    except (TypeError,ValueError):return None
def number(v):return type(v) in [int,float] and isfinite(v)
def group(rows,key):
    out=defaultdict(list)
    for r in rows:out[r.get(key)].append(r)
    return out
def unique(xs):return list(dict.fromkeys(xs))
def public(r):return {k:v for k,v in r.items() if k not in ['executions','sources','expected']}

class IncomingQuality:
    def __init__(self,data=None,cutoff=None):
        self.data=data if data is not None else analytics.tables();self.cutoff=cutoff or analytics.AS_OF;self.clock=timestamp(self.cutoff)
        self.idx={ds:supply.ix(self.data.get(ds,[])) for ds in NEW_TABLES+['incoming_inspections','receipts','purchase_lines','materials','suppliers','employees']}
        self.plans=group(self.data.get('incoming_check_plans',[]),'inspection_id');self.checks=group(self.data.get('incoming_checks',[]),'plan_id');self.readings=group(self.data.get('incoming_readings',[]),'check_id');self.specs=group(self.data.get('incoming_specs',[]),'material_id')
        self.physical=supply.SupplyData(self.data,self.cutoff)
        self.rows=[self.build(q) for q in self.data['incoming_inspections'] if q['inspected']<=self.cutoff];self.index=supply.ix(self.rows)
        self.global_issues=[]
        for ds,parent,key,clock in [('incoming_check_plans','incoming_inspections','inspection_id','created'),('incoming_checks','incoming_check_plans','plan_id','registered'),('incoming_readings','incoming_checks','check_id',None)]:
            self.global_issues.extend({'dataset':ds,'id':r['id'],'message':'缺少'+parent+'引用'} for r in self.data.get(ds,[]) if r.get(key) not in self.idx[parent] and (not clock or not timestamp(r.get(clock)) or r[clock]<=self.cutoff))

    def applicable(self,material,version,when):
        candidates=[s for s in self.specs[material] if s['version']==version];specs=[];issues=[]
        for s in candidates:
            a,b=day(s.get('effective')),day(s['expires']) if s.get('expires') else None
            if not a or s.get('expires') and not b or a and b and a>=b:issues.append(s['id']+'生效区间无效');continue
            if when and a<=when.date() and (not b or when.date()<b):specs.append(s)
        if not specs:issues.append('此物料、版本及测量日期未找到有效规范')
        if len({s.get('parameter') for s in specs})!=len(specs):issues.append('同特性存在重叠生效规范')
        for s in specs:
            lo,hi=s.get('lsl'),s.get('usl')
            if lo is None and hi is None or any(v is not None and not number(v) for v in [lo,hi]) or number(lo) and number(hi) and lo>hi:issues.append(s['id']+'限值无效')
            if type(s.get('mandatory')) is not bool or not all(s.get(k) for k in ['parameter','name','unit','basis']):issues.append(s['id']+'特性定义不完整')
        if specs and not any(s['mandatory'] is True for s in specs):issues.append('缺少必检项目，不能认定样本齐项')
        return specs,issues,supply.refs('incoming_specs',candidates)

    def execution(self,c,p,q,r,plan_issues):
        issues=list(plan_issues);when,registered=timestamp(c.get('checked')),timestamp(c.get('registered'));a=timestamp(p.get('created'));due=timestamp(p.get('due'))
        if not when or not registered or when and registered and when>registered or a and when and when<a or registered and registered>self.clock:issues.append('测量、计划建立或登记时间无效')
        if not all(c.get(k) for k in ['reference','reason']) or c.get('inspector_id') not in self.idx['employees']:issues.append('检验人员或原始依据缺失')
        if type(c.get('voided')) is not bool:issues.append('作废标志无效')
        specs,problems,ss=self.applicable(r.get('material_id'),p.get('spec_version'),when);issues+=problems;expected=supply.ix(specs);readings=self.readings[c['id']];counts=Counter((x.get('sample_no'),x.get('spec_id')) for x in readings);values=[]
        count=p.get('sample_count');count=count if type(count) is int and 1<=count<=10000 else 0
        for v in readings:
            s=expected.get(v.get('spec_id'));bad=[]
            if not s:bad.append('规范不属于当前物料、版本及有效日期')
            if type(v.get('sample_no')) is not int or not 1<=v['sample_no']<=count:bad.append('样本序号超出计划范围')
            if counts[(v.get('sample_no'),v.get('spec_id'))]>1:bad.append('同样本、同规范重复实测')
            if not number(v.get('value')):bad.append('实测值须为有限数值')
            if s and v.get('unit')!=s['unit']:bad.append('单位与规范不一致')
            if not v.get('instrument') or not v.get('file_reference'):bad.append('量具或原文件依据缺失')
            bounded=s and all(x is None or number(x) for x in [s.get('lsl'),s.get('usl')]);out=bool(bounded and number(v.get('value')) and (s.get('lsl') is not None and v['value']<s['lsl'] or s.get('usl') is not None and v['value']>s['usl']))
            values.append(v|dict(name=s.get('name') if s else None,parameter=s.get('parameter') if s else None,lsl=s.get('lsl') if s else None,usl=s.get('usl') if s else None,mandatory=s.get('mandatory') if s else None,issues=bad,out=out if not bad else None))
            issues += [v['id']+'：'+x for x in bad]
        cells=group(values,'sample_no');samples=[];required=[s for s in specs if s['mandatory'] is True]
        for n in range(1,count+1):
            vv=cells[n];present={v['spec_id'] for v in vv};missing=[s['id'] for s in required if s['id'] not in present];invalid=bool(issues or any(v['issues'] for v in vv));state='attention' if invalid else 'missing' if missing else 'out' if any(v['out'] is True for v in vv) else 'pass'
            samples.append(dict(sample_no=n,state=state,missing_specs=missing,out_evidence=sum(v['out'] is True for v in vv)))
        tally=Counter(s['state'] for s in samples);known=bool(count and not issues and not tally['missing'] and not tally['attention']);defects=tally['out'] if known else None
        state='attention' if issues else 'missing' if tally['missing'] else 'out' if tally['out'] else 'pass'
        refs=supply.refs('incoming_checks',[c])+supply.refs('incoming_readings',readings)+ss
        if c.get('inspector_id') in self.idx['employees']:refs+=supply.refs('employees',[self.idx['employees'][c['inspector_id']]])
        return dict(**c,issues=unique(issues),state=state,sample_count=count,known=known,defect_count=defects,known_samples=tally['pass']+tally['out'],out_samples=tally['out'],missing_samples=tally['missing'],unknown_samples=tally['attention'],values=values,samples=samples,expected=specs,sources=supply.unique_refs(refs))

    def build(self,q):
        r=self.idx['receipts'].get(q['receipt_id'],{});po=self.idx['purchase_lines'].get(r.get('purchase_line_id'),{});m=self.idx['materials'].get(r.get('material_id'),{});supplier=self.idx['suppliers'].get(po.get('supplier_id'),{});issues=[]
        physical=self.physical.receipts.get(r.get('id'));issues+=list(physical['issues']) if physical else ['截止内到货资料缺失']
        if not all([po,m,supplier]):issues.append('采购、物料或供应商档案缺失')
        plans=[p for p in self.plans[q['id']] if not timestamp(p.get('created')) or p['created']<=self.cutoff];p=plans[0] if len(plans)==1 else None
        if len(plans)>1:issues.append('同一原检验存在多份特性计划，归属不明确')
        expected=[];executions=[];sources=supply.refs('incoming_inspections',[q])+supply.refs('receipts',[r] if r else [])+supply.refs('purchase_lines',[po] if po else [])+supply.refs('materials',[m] if m else [])+supply.refs('suppliers',[supplier] if supplier else [])+supply.refs('incoming_check_plans',self.plans[q['id']]);ordering_issues=[]
        # Ambiguous/future plans still retain their children as evidence; do not
        # choose one plan merely to make its registrations appear computable.
        for header in self.plans[q['id']]:
            children=self.checks[header['id']]
            sources+=supply.refs('incoming_checks',children)
            for child in children:sources+=supply.refs('incoming_readings',self.readings[child['id']])
        if p:
            a,b=timestamp(p.get('created')),timestamp(p.get('due'));arrival=timestamp(r.get('received'));qt=timestamp(q.get('inspected'))
            if not a or not b or not arrival or not qt or not arrival<=a<=b<=qt:issues.append('计划建立或应检时间不在到货与原检验之间')
            if type(p.get('sample_count')) is not int or not 1<=p['sample_count']<=10000 or p['sample_count']!=q.get('sample_size'):issues.append('计划样本数与原抽样数不一致')
            if not all(p.get(k) for k in ['reference','note','spec_version']) or p.get('owner_id') not in self.idx['employees']:issues.append('计划责任或依据缺失')
            expected,problems,ss=self.applicable(r.get('material_id'),p.get('spec_version'),b);issues+=problems;sources+=ss
            if p.get('owner_id') in self.idx['employees']:sources+=supply.refs('employees',[self.idx['employees'][p['owner_id']]])
            for c in self.checks[p['id']]:
                checked,registered=timestamp(c.get('checked')),timestamp(c.get('registered'))
                if not checked or not registered:ordering_issues.append(c['id']+'测量/登记时间无法排序')
                excluded='已作废，不采用' if c.get('voided') is True else '测量或登记在截止后' if checked and checked>self.clock or registered and registered>self.clock else ''
                e=self.execution(c,p,q,r,issues) if not excluded else dict(**c,issues=[],state='excluded',values=[],samples=[],expected=[],sources=supply.refs('incoming_checks',[c])+supply.refs('incoming_readings',self.readings[c['id']]))
                e['exclusion']=excluded;executions.append(e);sources+=e['sources']
        eligible=[e for e in executions if not e['exclusion'] and timestamp(e.get('checked')) and timestamp(e.get('registered'))];eligible.sort(key=lambda e:(e['checked'],e['id']))
        if any(n>1 for n in Counter(e['checked'] for e in eligible).values()):ordering_issues.append('有效登记同刻并列，首/最新顺序不明确')
        first=eligible[0] if eligible and not ordering_issues else None;latest=eligible[-1] if eligible and not ordering_issues else None
        selected_issues=issues+ordering_issues+(latest['issues'] if latest else []);state='attention' if issues or ordering_issues else 'no_plan' if not p else latest['state'] if latest else 'pending'
        known_defects=latest.get('defect_count') if latest and not selected_issues else None;different=known_defects is not None and known_defects!=q['defect_count']
        flags=['all',state]+(['disagreement'] if different else [])
        return dict(id=q['id'],receipt_id=q['receipt_id'],purchase_line_id=po.get('id'),material_id=m.get('id'),material=m.get('name','档案缺失'),category=m.get('category','未知'),supplier_id=supplier.get('id'),supplier=supplier.get('name','档案缺失'),lot=r.get('lot'),inspected=q['inspected'],raw_result=q['result'],raw_disposition=q['disposition'],raw_sample_count=q['sample_size'],raw_defect_count=q['defect_count'],plan_id=p['id'] if p else None,spec_version=p.get('spec_version') if p else None,state=state,state_label=STATES[state],flags=flags,issues=unique(selected_issues),ordering_issues=ordering_issues,first_id=first['id'] if first else None,latest_id=latest['id'] if latest else None,first_state=first['state'] if first else None,latest_defect_count=known_defects,disagreement=different,check_count=len(eligible),excluded_count=len(executions)-len(eligible),expected=expected,executions=executions,sources=supply.unique_refs(sources))

    def cohort(self,f):
        return [r for r in self.rows if all(not f.get(k) or f[k]==r[k] for k in ['category','material_id','supplier_id']) and (not f.get('inspection_from') or r['inspected'][:10]>=f['inspection_from']) and (not f.get('inspection_to') or r['inspected'][:10]<=f['inspection_to']) and (not f.get('q') or f['q'].casefold() in ' '.join(str(r[k]) for k in ['id','receipt_id','purchase_line_id','material_id','material','lot','supplier']).casefold())]

    def distribution(self,rows,spec_id,mode='latest'):
        if mode not in ['first','latest','all']:raise ValueError('检测登记口径无效')
        spec=self.idx['incoming_specs'].get(spec_id)
        if not spec:raise ValueError('规范项目不存在')
        observations=[];exclusions=[]
        for r in rows:
            if r['material_id']!=spec['material_id'] or r['spec_version']!=spec['version']:continue
            ids={r[mode+'_id']} if mode in ['first','latest'] else {e['id'] for e in r['executions'] if not e['exclusion']}
            for e in r['executions']:
                if e['id'] not in ids:continue
                vv=[v for v in e['values'] if v['spec_id']==spec_id]
                for v in vv:
                    reason='；'.join(unique((r['ordering_issues'] if mode!='all' else [])+e['issues']+v['issues']))
                    if reason or v['out'] is None:exclusions.append(dict(id=v['id'],check_id=e['id'],inspection_id=r['id'],reason=reason or '判定未知'));continue
                    observations.append(v|dict(check_id=e['id'],inspection_id=r['id'],receipt_id=r['receipt_id'],supplier_id=r['supplier_id'],checked=e['checked'],inspected=r['inspected'],lot=r['lot']))
        values=[v['value'] for v in observations];n=len(values);lo=min(values) if n else None;hi=max(values) if n else None;bins=[]
        if n:
            if lo==hi:bins=[dict(index=0,lower=lo,upper=hi,count=n)]
            else:
                bins=[dict(index=i,lower=lo+(hi-lo)*i/8,upper=lo+(hi-lo)*(i+1)/8,count=0) for i in range(8)]
                for value in values:bins[min(7,int((value-lo)/(hi-lo)*8))]['count']+=1
        batches=[]
        for key,vv in sorted(group(observations,'inspection_id').items(),key=lambda x:(x[1][0]['inspected'],x[0])):
            xx=[v['value'] for v in vv];batches.append(dict(inspection_id=key,receipt_id=vv[0]['receipt_id'],inspected=vv[0]['inspected'],supplier_id=vv[0]['supplier_id'],lot=vv[0]['lot'],checks=len({v['check_id'] for v in vv}),n=len(xx),minimum=min(xx),maximum=max(xx),median=median(xx),out=sum(v['out'] for v in vv)))
        return dict(spec=spec,mode=mode,n=n,inspection_count=len(batches),check_count=len({v['check_id'] for v in observations}),mean=mean(values) if n else None,median=median(values) if n else None,minimum=lo,maximum=hi,out=sum(v['out'] for v in observations),bins=bins,batches=batches,observations=observations,exclusions=exclusions,note='每条是一个登记内的一个样本特性。全部登记模式可能重复同一批次的样本；未假定独立随机样本，也未计算过程能力。缺其他特性仍可展示本项有效值，但该样本不据此认定齐项。')

def summary(rows):
    return dict(objects=len(rows),with_plan=sum(bool(r['plan_id']) for r in rows),registered=sum(bool(r['latest_id']) for r in rows),complete=sum(r['latest_defect_count'] is not None for r in rows),**{k:sum(k in r['flags'] for r in rows) for k in STATES if k!='all'})
