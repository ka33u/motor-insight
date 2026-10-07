"""Manufacturing evidence at work-order, component-batch and event grains.

No reporting event is interpreted as a stock movement, and quantities from
different processes or object types are never added into motor output.
"""
from collections import defaultdict,Counter
from datetime import date,datetime
from statistics import median
from . import analytics
from .models import Record
from .engineering import refs,unique_sources,safe,route_graph,day

TABLES=['work_orders','products','batches','units','operations','routes','route_dependencies','equipment','production_resources','employees','shipments','shipment_units']
STAGES={'work_orders':{'all':'全部工单','no_events':'截止未见有效报工','assembly_gap':'装配记录尚不足','late_gap':'计划到期且装配记录不足','attention':'有核对事项'},'batches':{'all':'全部批次','complete':'分支工序记录齐全','pending':'分支工序记录待补','kit':'装配件包','attention':'有核对事项'},'operations':{'all':'全部事件','done':'有有效完成记录','active':'截止未完成','rework':'含返工标记','attention':'有核对事项'}}
NOTE='模拟Excel事实。日期按工单计划开工日选队列，所有报工核对至业务截止。工单、半成品批次、整机SN和发货行分开计数；跨工序报工量不能累加为整机产量。缺记录不等于未生产，工序间隔不等于已证实排队，协调不修改生产事实。'

def filters(q):
    keys=['from','to','family','product','work_order','q','process','kind']
    if set(q)-set(keys+['tab','stage','page']):raise ValueError('不支持的制造筛选')
    f={k:q.get(k,'') for k in keys};f.update(tab=q.get('tab','work_orders'),stage=q.get('stage','all'))
    if f['tab'] not in STAGES or f['stage'] not in STAGES[f['tab']]:raise ValueError('工作区或清单状态不可用')
    if any(len(v)>150 for v in f.values()):raise ValueError('筛选内容过长')
    if f['process'] and f['tab']!='operations':raise ValueError('工序筛选只适用于事件页')
    if f['kind'] and f['tab']=='work_orders':raise ValueError('对象类型只适用于批次或事件页')
    for k in ['from','to']:
        if f[k] and date.fromisoformat(f[k]).isoformat()!=f[k]:raise ValueError('日期须为YYYY-MM-DD')
    if f['from'] and f['to'] and f['from']>f['to']:raise ValueError('开始日期晚于结束日期')
    return f

def stamp(r,key,issues,required=True):
    v=r.get(key)
    if v is None and not required:return None
    try:
        t=datetime.fromisoformat(v)
        if t.tzinfo or t.isoformat()!=v:raise ValueError()
        return t
    except (ValueError,TypeError):issues.append(key+'时间缺失或格式无效');return None
def integer(v,positive=False):return type(v) is int and (v>0 if positive else v>=0)
def span_minutes(a,b):return (b-a).total_seconds()/60
def group(rows,key):
    out=defaultdict(list)
    for r in rows:out[r.get(key)].append(r)
    return out

class Manufacturing:
    def __init__(self,data,f,cutoff=None):
        self.data={k:data.get(k,[]) for k in TABLES};self.f=f;self.cutoff=cutoff or analytics.AS_OF;self.end=datetime.fromisoformat(self.cutoff);self.as_of=self.end.date();self.global_issues=[]
        self.idx={k:{r['id']:r for r in rows} for k,rows in self.data.items()}
        self.by_wo={ds:group(self.data[ds],'work_order_id') for ds in ['operations','batches','units']}
        self.routes=group(self.data['routes'],'product_id');self.edges=group(self.data['route_dependencies'],'product_id')
        self.pack=group(self.data['shipment_units'],'shipment_id');self.unit_refs=defaultdict(list)
        for r in self.data['units']:
            for key in ['stator_batch','rotor_batch','assembly_batch']:
                if r.get(key):self.unit_refs[r[key]].append((key,r))
        self.operations={};self.op_wo=defaultdict(list);self.op_object=defaultdict(list);self.future_ops=Counter()
        for r in self.data['operations']:
            if r.get('work_order_id') not in self.idx['work_orders']:self.global_issues.append(r['id']+'缺少对应工单');continue
            obj=self.operation(r)
            if obj['row']['future']:self.future_ops[r['work_order_id']]+=1;continue
            self.operations[r['id']]=obj;self.op_wo[r['work_order_id']].append(obj);self.op_object[r['object_type'],r['object_id']].append(obj)
        self.batches={}
        for r in self.data['batches']:
            if r.get('work_order_id') not in self.idx['work_orders']:self.global_issues.append(r['id']+'缺少对应工单');continue
            obj=self.batch(r)
            if not obj['future']:self.batches[r['id']]=obj
        self.work_orders={r['id']:self.work_order(r) for r in self.data['work_orders']}

    def base(self,wo):
        w=self.idx['work_orders'][wo];p=self.idx['products'].get(w.get('product_id'),{})
        return dict(work_order_id=wo,product_id=w.get('product_id'),family=p.get('family','未匹配'),model=p.get('model','未匹配'),planned_start=w.get('planned_start'))

    def operation(self,r):
        issues=[];sources=refs('operations',[r]);a=stamp(r,'started',issues);b=stamp(r,'finished',issues,False)
        if a and b and b<=a:issues.append('完成时间不晚于开始')
        if r.get('status') not in ['完成','进行中']:issues.append('未知报工状态')
        if r.get('status')=='完成' and not b:issues.append('完成标记缺少结束时间')
        if b and b<=self.end and r.get('status')!='完成':issues.append('结束时间与状态不一致')
        for key in ['input_qty','good_qty','scrap_qty','rework_qty']:
            if not integer(r.get(key),key=='input_qty'):issues.append(key+'数量无效')
        quantities=all(integer(r.get(k),k=='input_qty') for k in ['input_qty','good_qty','scrap_qty','rework_qty'])
        if quantities:
            if r['good_qty']+r['scrap_qty']>r['input_qty']:issues.append('合格与报废合计超过投入')
            if r['rework_qty']>r['input_qty']:issues.append('返工标记超过投入；返工为投入子集')
            if r.get('status')=='完成' and r['good_qty']+r['scrap_qty']!=r['input_qty']:issues.append('完成事件的投入与合格加报废未对平')
        for ds,key in [('equipment','equipment_id'),('employees','employee_id'),('production_resources','resource_id')]:
            parent=self.idx[ds].get(r.get(key))
            if not parent:issues.append(ds+'档案缺失')
            else:
                sources+=refs(ds,[parent])
                if ds=='equipment' and parent.get('process')!=r.get('process'):issues.append('设备适用工序不同')
                if ds=='production_resources' and (parent.get('process')!=r.get('process') or parent.get('equipment_id')!=r.get('equipment_id')):issues.append('资源位与设备或工序不一致')
        typ=r.get('object_type');obj=None;kind=typ
        if typ in ['生产批次','整机']:
            ds='batches' if typ=='生产批次' else 'units';obj=self.idx[ds].get(r.get('object_id'))
            if not obj:issues.append('报工对象缺失')
            else:
                sources+=refs(ds,[obj]);kind=obj.get('kind','整机')
                if obj.get('work_order_id')!=r['work_order_id']:issues.append('报工对象属于其他工单')
                if typ=='生产批次':
                    created=stamp(obj,'created',issues)
                    if a and created and a<created:issues.append('报工早于批次建立')
                elif r.get('process')=='装配':
                    if r.get('input_qty')!=1:issues.append('单台装配投入须为1')
                    if b and obj.get('assembly_at')!=b.isoformat():issues.append('装配结束与SN档案时间不一致')
                elif a and a.isoformat()<obj.get('assembly_at',''):issues.append('整机后续工序早于装配')
        elif typ=='发货行':
            obj=self.idx['shipments'].get(r.get('object_id'));packs=self.pack[r.get('object_id')];units=[self.idx['units'].get(x.get('unit_id')) for x in packs]
            if not obj:issues.append('发货行对象缺失')
            else:
                sources+=refs('shipments',[obj])+refs('shipment_units',packs)+refs('units',[u for u in units if u])
                if not packs or any(not u or u.get('work_order_id')!=r['work_order_id'] for u in units):issues.append('包装SN与工单关系缺失或混合，不能归入单工单')
                if len({x.get('unit_id') for x in packs})!=len(packs):issues.append('同发货行SN重复')
                if r.get('input_qty')!=len(packs) or obj.get('qty')!=len(packs):issues.append('包装投入与发货SN数未对平')
                if b and obj.get('shipped') and b.isoformat()>obj['shipped']:issues.append('包装完成晚于发货')
        else:issues.append('未知报工对象类型')
        future=bool(a and a>self.end);done=bool(not issues and not future and b and b<=self.end);active=bool(not issues and not future and not done)
        elapsed=span_minutes(a,b if done else self.end) if (done or active) else None
        row={**r,**self.base(r['work_order_id']),'kind':kind,'future':future,'done':done,'active':active,'elapsed_minutes':elapsed,'completed_as_of':b.isoformat() if done else None,'output_as_of':r.get('good_qty') if done else None,'issues':issues,'calculated_state':'资料待核对' if issues else '有完成记录' if done else '截止未完成','flags':['all']+(['done'] if done else ['active'] if active else [])+(['rework'] if integer(r.get('rework_qty')) and r['rework_qty']>0 else [])+(['attention'] if issues else [])}
        wo=self.idx['work_orders'][r['work_order_id']];product=self.idx['products'].get(wo.get('product_id'))
        return {'row':row,'sources':unique_sources(sources+refs('work_orders',[wo])+refs('products',[product] if product else []))}

    def batch(self,r):
        issues=[];sources=refs('batches',[r]);created=stamp(r,'created',issues);w=self.idx['work_orders'][r['work_order_id']];sources+=refs('work_orders',[w]);kind=r.get('kind');kit=kind=='装配件包'
        if kind not in ['定子','转子','装配件包']:issues.append('未识别批次分支')
        if not integer(r.get('qty'),True):issues.append('批次数量无效')
        product=self.idx['products'].get(w.get('product_id'));sources+=refs('products',[product] if product else [])
        all_routes=[x for x in self.routes[w['product_id']] if x.get('version')==w.get('route_version')]
        edges=self.edges[w['product_id']];graph=route_graph(all_routes,edges,self.idx['routes'],w['product_id']);sources+=refs('routes',all_routes)+refs('route_dependencies',edges)
        routes=sorted([x for x in all_routes if x.get('branch')==kind],key=lambda x:x.get('sequence') if type(x.get('sequence')) is int else 0)
        if not kit:
            issues+=graph['issues']
            if not routes:issues.append('工单引用版本缺少此分支路线')
        events=self.op_object['生产批次',r['id']];by_process=group([o['row'] for o in events],'process');steps=[];valid_ops={};gaps=[]
        for obj in events:sources+=obj['sources'];issues += [obj['row']['id']+'：'+x for x in obj['row']['issues']]
        for route in routes:
            matches=by_process[route['process']];op=matches[0] if len(matches)==1 else None
            if len(matches)>1:issues.append(route['process']+'有多次报工，拆批或返工关系待核对')
            if op and op['done']:valid_ops[route['id']]=op
            steps.append({'route_id':route['id'],'sequence':route['sequence'],'process':route['process'],'mandatory':route['mandatory'],'operation_id':op['id'] if op else None,'state':'多次报工待核对' if len(matches)>1 else '未见报工' if not op else op['calculated_state'],'started':op.get('started') if op else None,'finished':op.get('completed_as_of') if op else None,'elapsed_minutes':op.get('elapsed_minutes') if op else None,'good_qty':op.get('output_as_of') if op else None})
        known={x['process'] for x in routes}
        if any(o['row']['process'] not in known for o in events):issues.append('存在分支路线外报工')
        for edge in edges:
            a=valid_ops.get(edge['from_route_id']);b=valid_ops.get(edge['to_route_id'])
            if a and b:
                gap=span_minutes(datetime.fromisoformat(a['finished']),datetime.fromisoformat(b['started']));minimum=edge.get('lag_minutes')
                if type(minimum) not in [int,float] or minimum<0:continue
                gaps.append({'from_process':a['process'],'to_process':b['process'],'minutes':gap,'minimum_minutes':minimum})
                if gap<minimum:issues.append(a['process']+'→'+b['process']+'未满足路线最小间隔')
                if b['input_qty']!=a['good_qty']:issues.append(a['process']+'→'+b['process']+'流转数量未对平，需拆合批依据')
        if routes and routes[0]['id'] in valid_ops and valid_ops[routes[0]['id']]['input_qty']!=r.get('qty'):issues.append('首工序投入与批次数量未对平')
        unit_rows=[];expected_field={'定子':'stator_batch','转子':'rotor_batch','装配件包':'assembly_batch'}.get(kind)
        for field,u in self.unit_refs[r['id']]:
            problems=[];when=stamp(u,'assembly_at',problems)
            if when and when>self.end:continue
            sources+=refs('units',[u]);issues+=problems
            if field!=expected_field or u.get('work_order_id')!=r['work_order_id'] or u.get('product_id')!=w.get('product_id'):issues.append(u['id']+'装配批次类型、工单或配置不一致')
            if created and when and when<created:issues.append(u['id']+'装配早于批次建立')
            unit_rows.append(u)
        if len({u['id'] for u in unit_rows})!=len(unit_rows):issues.append('同SN重复引用此批次')
        if integer(r.get('qty'),True) and len(unit_rows)>r['qty']:issues.append('引用SN数超过批次数量')
        complete=bool(not kit and routes and not issues and all(not x['mandatory'] or x['id'] in valid_ops for x in routes))
        terminal=valid_ops.get(routes[-1]['id']) if routes else None
        if complete and terminal and len(unit_rows)>terminal['good_qty']:issues.append('装配引用超过末工序合格数量');complete=False
        if complete and terminal:
            for u in unit_rows:
                assembly_ops=self.op_object['整机',u['id']];assembly=[o['row'] for o in assembly_ops if o['row']['process']=='装配' and o['row']['done']]
                for obj in assembly_ops:
                    if obj['row']['process']=='装配':sources+=obj['sources']
                if len(assembly)!=1:issues.append(u['id']+'缺少唯一有效装配报工');continue
                for e in edges:
                    dest=self.idx['routes'].get(e['to_route_id'],{})
                    if e['from_route_id']==routes[-1]['id'] and dest.get('process')=='装配' and span_minutes(datetime.fromisoformat(terminal['finished']),datetime.fromisoformat(assembly[0]['started']))<e['lag_minutes']:issues.append(u['id']+'装配开始未满足分支完成依赖')
        if issues:complete=False
        available=None if kit or not complete or not terminal else terminal['good_qty']-len(unit_rows)
        row={**r,**self.base(r['work_order_id']),'route_steps':len(routes),'done_steps':len(valid_ops),'complete':complete,'assembly_refs':len(unit_rows),'unreferenced_qty':available,'interval_minutes':sum(g['minutes'] for g in gaps) if complete else None,'issues':list(dict.fromkeys(issues)),'flags':['all']+(['kit'] if kit else ['complete'] if complete else ['pending'])+(['attention'] if issues else [])}
        return {'row':row,'steps':steps,'gaps':gaps,'units':unit_rows,'future':bool(created and created>self.end),'sources':unique_sources(sources)}

    def work_order(self,r):
        issues=[];sources=refs('work_orders',[r]);start=day(r,'planned_start',issues);due=day(r,'planned_end',issues)
        if start and due and start>due:issues.append('计划开工晚于完工')
        date_valid=not issues
        quantity_issues=[]
        if not integer(r.get('planned_qty'),True):issues.append('计划数量须为正整数')
        p=self.idx['products'].get(r.get('product_id'))
        if not p:issues.append('配置档案缺失')
        else:sources+=refs('products',[p])
        units=[]
        for u in self.by_wo['units'][r['id']]:
            problems=[];when=stamp(u,'assembly_at',problems)
            if when and when>self.end:continue
            sources+=refs('units',[u]);quantity_issues+=problems
            if u.get('product_id')!=r.get('product_id'):quantity_issues.append(u['id']+'配置与工单不符')
            units.append(u)
        qty=len(units)
        if integer(r.get('planned_qty'),True) and qty>r['planned_qty']:quantity_issues.append('装配SN超过工单计划数量')
        issues+=quantity_issues
        gap=None if quantity_issues or not integer(r.get('planned_qty'),True) else r['planned_qty']-qty
        events=self.op_wo[r['id']];good=[o['row'] for o in events if not o['row']['issues']]
        sources+=refs('operations',[x for x in self.by_wo['operations'][r['id']] if x['id'] not in self.operations])
        batches=[x for x in self.batches.values() if x['row']['work_order_id']==r['id']]
        for obj in events+batches:sources+=obj['sources'];issues += [obj['row']['id']+'：'+x for x in obj['row']['issues']]
        row={**r,**self.base(r['id']),'assembled_qty':qty,'assembly_gap':gap,'date_valid':date_valid,'events':len(events),'valid_events':len(good),'batches':len(batches),'first_started':min((x['started'] for x in good),default=None),'last_finished':max((x['completed_as_of'] for x in good if x['done']),default=None),'issues':list(dict.fromkeys(issues)),'flags':['all']+(['no_events'] if not good else [])+(['assembly_gap'] if gap is not None and gap>0 else [])+(['late_gap'] if date_valid and gap is not None and gap>0 and due and due<self.as_of else [])+(['attention'] if issues else [])}
        return {'row':row,'batches':[x['row'] for x in batches],'processes':self.process_groups(good),'future_events':self.future_ops[r['id']],'sources':unique_sources(sources)}

    def selected(self):
        f=self.f;rows=[]
        for obj in getattr(self,f['tab']).values():
            r=obj['row'];w=self.idx['work_orders'][r['work_order_id']]
            if any(f[k] and f[k]!=r.get(target) for k,target in [('family','family'),('product','product_id'),('work_order','work_order_id'),('process','process'),('kind','kind')]):continue
            ds=[];start=day(w,'planned_start',ds)
            if not start:
                if f['from'] or f['to']:continue
            elif f['from'] and start.isoformat()<f['from'] or f['to'] and start.isoformat()>f['to']:continue
            if f['q'] and f['q'].lower() not in ' '.join(str(r.get(k,'')) for k in ['id','work_order_id','object_id','product_id','model']).lower():continue
            rows.append(r)
        return sorted(rows,key=lambda r:(not bool(r['issues']),not ('late_gap' in r['flags']),r['id']))

    def detail(self,kind,key):
        if kind!=self.f['tab'] or key not in {r['id'] for r in self.selected()}:raise Record.DoesNotExist()
        return getattr(self,kind)[key]

    def process_groups(self,rows):
        groups=defaultdict(list)
        for r in rows:groups[r['kind'],r['process']].append(r)
        out=[]
        for (kind,process),events in groups.items():
            done=[r for r in events if r['done']];times=[r['elapsed_minutes'] for r in done]
            out.append(dict(kind=kind,process=process,events=len(events),done=len(done),active=sum(r['active'] for r in events),attention=sum(bool(r['issues']) for r in events),objects=len({r['object_id'] for r in events}),completed_input=sum(r['input_qty'] for r in done),completed_good=sum(r['good_qty'] for r in done),completed_scrap=sum(r['scrap_qty'] for r in done),completed_rework=sum(r['rework_qty'] for r in done),median_minutes=median(times) if times else None))
        return sorted(out,key=lambda r:(r['kind'],r['process']))

    def summary(self,rows):
        f=self.f;summary={'objects':len(rows),'attention':sum(bool(r['issues']) for r in rows)}
        if f['tab']=='work_orders':summary.update(planned_qty=sum(r['planned_qty'] for r in rows if integer(r.get('planned_qty'),True)),assembled_qty=sum(r['assembled_qty'] for r in rows),assembly_gap=sum(r['assembly_gap'] for r in rows if r['assembly_gap'] is not None),unknown_gaps=sum(r['assembly_gap'] is None for r in rows),no_events=sum('no_events' in r['flags'] for r in rows),late_gap=sum('late_gap' in r['flags'] for r in rows))
        elif f['tab']=='batches':summary.update(complete=sum(r['complete'] for r in rows),pending=sum('pending' in r['flags'] for r in rows),kits=sum('kit' in r['flags'] for r in rows))
        else:summary.update(done=sum(r['done'] for r in rows),active=sum(r['active'] for r in rows),rework=sum('rework' in r['flags'] for r in rows))
        return summary

    def breakdown(self,rows):
        if self.f['tab']=='operations':return self.process_groups(rows)
        if self.f['tab']=='batches':
            buckets=group(rows,'kind')
            return [{'name':k,'total':len(v),'complete':sum(r['complete'] for r in v),'pending':sum('pending' in r['flags'] for r in v),'attention':sum(bool(r['issues']) for r in v)} for k,v in sorted(buckets.items())]
        buckets=group(rows,'family')
        return [{'name':k,'total':len(v),'planned_qty':sum(r['planned_qty'] for r in v if integer(r.get('planned_qty'),True)),'assembled_qty':sum(r['assembled_qty'] for r in v),'gap':sum(r['assembly_gap'] for r in v if r['assembly_gap'] is not None),'unknown':sum(r['assembly_gap'] is None for r in v)} for k,v in sorted(buckets.items())]

def current(f):return Manufacturing({ds:list(Record.objects.filter(dataset=ds).values_list('values',flat=True)) for ds in TABLES},f)
