"""Engineering workbench over imported records, not a PLM approval engine."""
from collections import Counter,defaultdict
from datetime import date
from math import isfinite
from . import analytics
from .models import Record

TABLES=['products','materials','bom','routes','route_dependencies','projects','engineering_changes','project_milestones','change_actions','work_orders','employees']
NOTE='全部为模拟台账。产品登记版本、工单引用版本、项目结束与变更执行分开核对；记录编号不代表附件已验证，当前版本不能倒推历史生效，协调记录不代替技术批准。'
STAGES={'products':{'all':'全部配置','version_difference':'工单版本与配置不同','attention':'基础资料问题'},'projects':{'all':'全部项目','open':'截止未结束','closed':'有结束记录','overdue':'未结束且逾期','late':'逾期后结束','attention':'基础资料问题'},'changes':{'all':'全部变更','effective':'生效日期已到','pending':'有未完成执行项','overdue':'有逾期执行项','missing_baseline':'未覆盖变更前BOM版本','attention':'基础资料问题'}}

def safe(value,money):
    if isinstance(value,dict):return {k:safe(v,money) for k,v in value.items() if money or 'cents' not in k}
    if isinstance(value,list):return [safe(x,money) for x in value]
    return value

def filters(q):
    if set(q)-{'tab','family','product','owner','q','from','to','stage','page'}:raise ValueError('不支持的研发工艺筛选')
    f={k:q.get(k,'') for k in ['family','product','owner','q','from','to']};f['tab']=q.get('tab','products');f['stage']=q.get('stage','all')
    if f['tab'] not in STAGES or f['stage'] not in STAGES[f['tab']]:raise ValueError('工作区或清单状态不可用')
    for k in ['from','to']:
        if f[k] and date.fromisoformat(f[k]).isoformat()!=f[k]:raise ValueError('日期须为YYYY-MM-DD')
    if f['from'] and f['to'] and f['from']>f['to']:raise ValueError('起始日期晚于截止日期')
    if f['tab']=='products' and any(f[k] for k in ['from','to','owner']):raise ValueError('配置清单不支持项目责任人或期间筛选')
    if any(len(v)>150 for v in f.values()):raise ValueError('筛选内容过长')
    return f

def day(r,key,issues,required=True):
    v=r.get(key)
    if v is None and not required:return None
    try:
        parsed=date.fromisoformat(v)
        if parsed.isoformat()!=v:raise ValueError()
        return parsed
    except (ValueError,TypeError):issues.append(key+'日期缺失或格式无效');return None

def finite(v,positive=False):return type(v) in [int,float] and isfinite(v) and (v>0 if positive else v>=0)
def refs(ds,rows):return [{'dataset':ds,'key':r['id']} for r in rows]
def unique_sources(rows):return list({(r['dataset'],r['key']):r for r in rows}.values())

def route_graph(routes,dependencies,all_routes,product_id):
    issues=[];nodes={r['id']:r for r in routes};seen=set();edges=[]
    for r in routes:
        seq=r.get('sequence');position=(r.get('branch') or '',seq)
        if type(seq) is not int or seq<1:issues.append(r['id']+'工序序号无效')
        if position in seen:issues.append(r['id']+'同分支序号重复')
        seen.add(position)
        if not finite(r.get('minutes'),True):issues.append(r['id']+'标准分钟无效')
        if type(r.get('mandatory')) is not bool:issues.append(r['id']+'必经标记无效')
    edge_keys=set()
    for e in dependencies:
        a=all_routes.get(e.get('from_route_id'));b=all_routes.get(e.get('to_route_id'))
        if not a or not b or a.get('product_id')!=product_id or b.get('product_id')!=product_id:
            issues.append(e['id']+'依赖端点缺失或跨配置');continue
        if a['id'] not in nodes and b['id'] not in nodes:continue
        if a['id'] not in nodes or b['id'] not in nodes:issues.append(e['id']+'依赖混用路线版本');continue
        pair=(a['id'],b['id'])
        if pair in edge_keys:issues.append(e['id']+'依赖边重复');continue
        edge_keys.add(pair)
        if not finite(e.get('lag_minutes')):issues.append(e['id']+'最小等待分钟无效');continue
        edges.append(e)
    incoming={k:0 for k in nodes};following=defaultdict(list);rank={k:0 for k in nodes}
    for e in edges:incoming[e['to_route_id']]+=1;following[e['from_route_id']].append(e['to_route_id'])
    queue=sorted(k for k,v in incoming.items() if v==0);visited=[]
    while queue:
        key=queue.pop(0);visited.append(key)
        for nxt in following[key]:
            rank[nxt]=max(rank[nxt],rank[key]+1);incoming[nxt]-=1
            if incoming[nxt]==0:queue.append(nxt)
    if len(visited)!=len(nodes):issues.append('路线依赖存在环，暂停绘制有向顺序')
    if len(routes)>1 and not edges:issues.append('尚无路线依赖，不能确认工序先后')
    return {'nodes':[{**r,'rank':rank[r['id']]} for r in routes] if not issues else [],'edges':edges if not issues else [],'issues':issues,'valid':bool(routes) and not issues}

class Engineering:
    def __init__(self,data,f,cutoff=None):
        self.data={ds:data.get(ds,[]) for ds in TABLES};self.f=f;self.cutoff=cutoff or analytics.AS_OF;self.as_of=date.fromisoformat(self.cutoff[:10]);self.global_issues=[]
        self.idx={ds:{r['id']:r for r in rows} for ds,rows in self.data.items()};self.by_product={ds:defaultdict(list) for ds in ['bom','routes','route_dependencies','projects','engineering_changes','work_orders']}
        for ds,buckets in self.by_product.items():
            for r in self.data[ds]:
                buckets[r.get('product_id')].append(r)
                if r.get('product_id') not in self.idx['products']:self.global_issues.append(ds+' / '+r['id']+'未关联产品配置')
        self.children={ds:defaultdict(list) for ds in ['project_milestones','change_actions']}
        for ds,fk,parent in [('project_milestones','project_id','projects'),('change_actions','change_id','engineering_changes')]:
            for r in self.data[ds]:
                self.children[ds][r.get(fk)].append(r)
                if r.get(fk) not in self.idx[parent]:self.global_issues.append(ds+' / '+r['id']+'未关联父单据')
        self.products={p['id']:self.product(p) for p in self.data['products']}
        self.projects={p['id']:self.project(p) for p in self.data['projects']}
        self.changes={c['id']:self.change(c) for c in self.data['engineering_changes']}

    def owner(self,r,field,issues,sources):
        employee=self.idx['employees'].get(r.get(field))
        if employee:sources+=refs('employees',[employee])
        else:issues.append('责任工号未关联人员档案')
        return employee.get('name','') if employee else '未匹配'

    def product(self,p):
        key=p['id'];sources=refs('products',[p]);issues=[];bom=[];other_bom=[]
        for r in self.by_product['bom'][key]:
            sources+=refs('bom',[r]);problems=[];effective=day(r,'effective',problems);material=self.idx['materials'].get(r.get('material_id'))
            if material:sources+=refs('materials',[material])
            else:problems.append('物料档案缺失')
            if not finite(r.get('qty'),True):problems.append('单位用量无效')
            if not finite(r.get('scrap_allowance')) or r.get('scrap_allowance',2)>=1:problems.append('损耗定额须在0至小于1之间')
            if material and material.get('unit')=='件' and finite(r.get('qty'),True) and r['qty']%1:problems.append('件数用量非整数')
            out={**r,'material_name':material.get('name','') if material else '未匹配','unit':material.get('unit') if material else None,'issues':problems}
            if r.get('version')==p.get('bom_version'):
                issues += [r['id']+'：'+x for x in problems]
                if effective and effective<=self.as_of:bom.append(out)
                else:other_bom.append(out)
            else:other_bom.append(out)
        if not bom:issues.append('当前BOM版本没有截止前生效明细')
        all_routes=self.by_product['routes'][key];routes=[r for r in all_routes if r.get('version')==p.get('route_version')];dependencies=self.by_product['route_dependencies'][key]
        sources+=refs('routes',all_routes)+refs('route_dependencies',dependencies)
        graph=route_graph(routes,dependencies,self.idx['routes'],key);issues+=graph['issues']
        if not routes:issues.append('当前路线版本没有明细')
        work=[];known_bom={r['version'] for r in self.by_product['bom'][key]};known_route={r['version'] for r in all_routes}
        for w in self.by_product['work_orders'][key]:
            sources+=refs('work_orders',[w]);difference=w.get('bom_version')!=p.get('bom_version') or w.get('route_version')!=p.get('route_version')
            covered=w.get('bom_version') in known_bom and w.get('route_version') in known_route
            work.append({**w,'version_difference':difference,'version_rows_present':covered})
            if not covered:issues.append(w['id']+'引用版本的明细未覆盖')
        row={**p,'bom_rows':len(bom),'route_rows':len(routes),'work_orders':len(work),'version_differences':sum(w['version_difference'] for w in work),'issues':issues,'flags':['all']+(['attention'] if issues else [])+(['version_difference'] if any(w['version_difference'] for w in work) else [])}
        return {'row':row,'bom':bom,'other_bom':other_bom,'routes':routes,'graph':graph,'work_orders':work,'projects':self.by_product['projects'][key],'changes':self.by_product['engineering_changes'][key],'sources':unique_sources(sources+refs('projects',self.by_product['projects'][key])+refs('engineering_changes',self.by_product['engineering_changes'][key]))}

    def task(self,r,kind):
        issues=[];sources=refs('project_milestones' if kind=='milestone' else 'change_actions',[r]);due_key='planned_end' if kind=='milestone' else 'due';end_key='actual_end' if kind=='milestone' else 'completed'
        due=day(r,due_key,issues);end=day(r,end_key,issues,False);start=day(r,'actual_start' if kind=='milestone' else 'created',issues,kind!='milestone')
        if kind=='milestone':
            planned_start=day(r,'planned_start',issues)
            if planned_start and due and planned_start>due:issues.append('计划开始晚于计划完成')
            if type(r.get('sequence')) is not int or r['sequence']<=0:issues.append('阶段序号无效')
        elif start and due and start>due:issues.append('任务期限早于建立日期')
        if end and (not start or end<start):issues.append('完成早于开始或缺少实际开始')
        if r.get('status') not in (['已完成','进行中','未开始'] if kind=='milestone' else ['已完成','待反馈','执行中']):issues.append('未知台账状态')
        if r.get('status')=='已完成' and not end:issues.append('已完成状态缺少完成日期')
        if end and end<=self.as_of and r.get('status')!='已完成':issues.append('完成日期与台账状态不一致')
        if kind=='milestone' and r.get('status')=='进行中' and not start:issues.append('进行中阶段缺少实际开始日期')
        if kind=='milestone' and r.get('status')=='未开始' and start and start<=self.as_of:issues.append('未开始状态却有截止前实际开始')
        owner=self.owner(r,'owner_id',issues,sources);done=bool(not issues and end and end<=self.as_of);opened=not issues and not done;overdue=bool(opened and due<self.as_of)
        return {**r,'owner_name':owner,'done':done,'open':opened,'overdue':overdue,'late':bool(done and end>due),'completed_as_of':end.isoformat() if done else None,'future_completion':bool(end and end>self.as_of),'future_created':bool(kind=='action' and start and start>self.as_of),'days_late':(self.as_of-due).days if overdue else 0 if not issues else None,'calculated_state':'资料待核对' if issues else '有完成记录' if done else '未完成且逾期' if overdue else '截止未完成','issues':issues,'sources':sources}

    def base(self,r,ds,owner_field):
        issues=[];sources=refs(ds,[r]);p=self.idx['products'].get(r.get('product_id'))
        if not p:issues.append('产品配置档案缺失')
        else:sources+=refs('products',[p])
        owner=self.owner(r,owner_field,issues,sources)
        return issues,sources,{'family':p.get('family','') if p else '未匹配','model':p.get('model','') if p else '未匹配','owner_name':owner,'owner_id':r.get(owner_field)}

    def project(self,r):
        issues,sources,info=self.base(r,'projects','owner_id');due=day(r,'planned_end',issues);end=day(r,'actual_end',issues,False)
        if r.get('status') not in ['已转产','验证中']:issues.append('未知项目状态')
        if r.get('status')=='已转产' and not end:issues.append('已转产状态缺少结束日期')
        if end and end<=self.as_of and r.get('status')!='已转产':issues.append('结束日期与项目状态不一致')
        lifecycle_valid=not issues;done=bool(lifecycle_valid and end and end<=self.as_of);opened=lifecycle_valid and not done
        milestones=[self.task(m,'milestone') for m in self.children['project_milestones'][r['id']]]
        sequences=[x.get('sequence') for x in milestones]
        if len(sequences)!=len(set(sequences)):issues.append('项目阶段序号重复')
        for m in milestones:issues += [m['id']+'：'+x for x in m['issues']];sources+=m['sources']
        if done and any(m['open'] for m in milestones):issues.append('项目有结束记录但仍有未完成阶段')
        if not milestones:issues.append('未导入项目里程碑')
        budget=r.get('budget_cents');row={**r,**info,'budget_cents':budget if type(budget) is int and budget>=0 else None,'milestones':len(milestones),'completed_milestones':sum(x['done'] for x in milestones),'overdue_milestones':sum(x['overdue'] for x in milestones),'record_numbers':sum(bool(x.get('record_no')) for x in milestones),'days_overdue':(self.as_of-due).days if opened and due<self.as_of else 0 if lifecycle_valid else None,'closed_as_of':end.isoformat() if done else None,'calculated_state':'资料待核对' if not lifecycle_valid else '有结束记录' if done else '未结束且逾期' if due<self.as_of else '截止未结束','issues':issues,'flags':['all']+(['closed'] if done else ['open'] if opened else [])+(['overdue'] if opened and due<self.as_of else [])+(['late'] if done and end>due else [])+(['attention'] if issues else [])}
        return {'row':row,'milestones':sorted(milestones,key=lambda x:(x.get('sequence') if type(x.get('sequence')) is int else 0,x['id'])),'sources':unique_sources(sources)}

    def change(self,r):
        issues,sources,info=self.base(r,'engineering_changes','approved_by');effective=day(r,'effective',issues)
        if not r.get('from_version') or not r.get('to_version') or r.get('from_version')==r.get('to_version'):issues.append('变更前后版本无效')
        all_actions=[self.task(x,'action') for x in self.children['change_actions'][r['id']]]
        actions=[x for x in all_actions if not x['future_created']]
        for a in actions:issues += [a['id']+'：'+x for x in a['issues']];sources+=a['sources']
        if not actions:issues.append('未导入变更执行任务')
        p=self.idx['products'].get(r.get('product_id'));bom=self.by_product['bom'][r.get('product_id')];work=self.by_product['work_orders'][r.get('product_id')]
        before=[x for x in bom if x.get('version')==r.get('from_version')];after=[x for x in bom if x.get('version')==r.get('to_version')]
        sources+=refs('bom',before+after)+refs('work_orders',work)
        matches=[{**w,'version_relation':'与目标号一致' if w.get('bom_version')==r.get('to_version') else '与原号一致' if w.get('bom_version')==r.get('from_version') else '其他或未知版本'} for w in work]
        row={**r,**info,'actions':len(actions),'completed_actions':sum(a['done'] for a in actions),'pending_actions':sum(a['open'] for a in actions),'overdue_actions':sum(a['overdue'] for a in actions),'before_bom_rows':len(before),'after_bom_rows':len(after),'current_bom_version':p.get('bom_version') if p else None,'work_orders':len(work),'issues':issues,'flags':['all']+(['effective'] if effective and effective<=self.as_of else [])+(['pending'] if any(a['open'] for a in actions) else [])+(['overdue'] if any(a['overdue'] for a in actions) else [])+(['missing_baseline'] if not before else [])+(['attention'] if issues else [])}
        return {'row':row,'actions':actions,'future_actions':sum(x['future_created'] for x in all_actions),'work_orders':matches,'sources':unique_sources(sources),'comparison_note':'仅按关联配置和BOM版本字符串列候选工单；原单未声明变更对象类型、适用SN或旧料处置范围，不能据此认定工单必须切换或已落实。缺少历史完整BOM时不计算物料差异。'}

    def selected(self):
        f=self.f;collection=getattr(self,f['tab']);rows=[]
        for obj in collection.values():
            r=obj['row'];pid=r['id'] if f['tab']=='products' else r.get('product_id')
            if f['family'] and r.get('family')!=f['family'] or f['product'] and pid!=f['product'] or f['owner'] and r.get('owner_id')!=f['owner']:continue
            clock=r.get('planned_end') if f['tab']=='projects' else r.get('effective')
            if f['from'] and (not clock or clock<f['from']) or f['to'] and (not clock or clock>f['to']):continue
            if f['q'] and f['q'].casefold() not in ' '.join(str(r.get(k) or '') for k in ['id','name','model','product_id','reason','owner_id','owner_name','drawing']).casefold():continue
            rows.append(r)
        return sorted(rows,key=lambda r:(not bool(r['issues']),'overdue' not in r['flags'],r['id']))

    def summary(self,rows):
        total={'objects':len(rows),'attention':sum('attention' in r['flags'] for r in rows)}
        if self.f['tab']=='products':return {**total,'bom_rows':sum(r['bom_rows'] for r in rows),'route_rows':sum(r['route_rows'] for r in rows),'work_orders':sum(r['work_orders'] for r in rows),'version_differences':sum(r['version_differences'] for r in rows)}
        if self.f['tab']=='projects':return {**total,**{k:sum(k in r['flags'] for r in rows) for k in ['open','closed','overdue','late']},'milestones':sum(r['milestones'] for r in rows),'completed_milestones':sum(r['completed_milestones'] for r in rows),'overdue_milestones':sum(r['overdue_milestones'] for r in rows),'budget_cents':sum(r['budget_cents'] for r in rows) if rows and all(r['budget_cents'] is not None for r in rows) else None}
        return {**total,**{k:sum(k in r['flags'] for r in rows) for k in ['effective','pending','overdue','missing_baseline']},**{k:sum(r[k] for r in rows) for k in ['actions','completed_actions','pending_actions','overdue_actions']}}

    def breakdown(self,rows):
        names=sorted({r.get('family') or '未填写' for r in rows})
        return [{'family':name,'objects':sum((r.get('family') or '未填写')==name for r in rows),'attention':sum((r.get('family') or '未填写')==name and bool(r['issues']) for r in rows)} for name in names]

    def detail(self,kind,key):
        if kind!=self.f['tab'] or key not in {r['id'] for r in self.selected()}:raise Record.DoesNotExist()
        return getattr(self,kind)[key]

def current(f):return Engineering({ds:list(Record.objects.filter(dataset=ds).values_list('values',flat=True)) for ds in TABLES},f)
