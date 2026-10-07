"""Case-cohort service analysis. Source timestamps are factory-local, not SLAs.

A customer-reported condition is never treated as a validated measurement or cause.
Shipment ownership uses explicit packing SN only; no shared-work-order allocation.
"""
from collections import defaultdict, Counter
from datetime import date
from statistics import mean
from math import isfinite
from . import analytics
from .assets import dt
from .models import Record

TABLES=('service','service_events','service_tasks','service_conditions','employees','customers','units','products','shipment_units','shipments','order_lines','orders','work_orders')
STAGES={'cases':{'all':'全部服务单','open':'截止未关闭','closed':'有关闭记录','no_response':'截止未响应','attention':'数据待核对'},
        'tasks':{'all':'全部任务','open':'截止未完成','overdue':'未完成且逾期','done':'有完成记录','late':'逾期后完成','attention':'数据待核对'}}
NOTE='全部为合成Excel演练。报修日期选择服务单队列，状态核对至固定快照；响应和关闭采用自然历时，未设置合同SLA。客户工况是待核实自报资料，不能据此判断制造根因或责任。'

def filters(q):
    if set(q)-{'tab','from','to','customer','family','product','failure','environment','q','stage','page'}:raise ValueError('不支持的售后筛选')
    f={k:q.get(k,'') for k in ['from','to','customer','family','product','failure','environment','q']};f.update(tab=q.get('tab','cases'),stage=q.get('stage','all'))
    if f['tab'] not in STAGES or f['stage'] not in STAGES[f['tab']]:raise ValueError('工作页或清单状态不可用')
    if any(len(v)>150 for v in f.values()):raise ValueError('筛选内容过长')
    for key in ['from','to']:
        if f[key] and (date.fromisoformat(f[key]).isoformat()!=f[key] or f[key]>analytics.AS_OF[:10]):raise ValueError('报修日期须在固定业务日以内')
    if f['from'] and f['to'] and f['from']>f['to']:raise ValueError('开始日期不能晚于结束日期')
    return f

def refs(ds,rows):return [{'dataset':ds,'key':r['id']} for r in rows]
def safe(value,money):
    if isinstance(value,dict):return {k:safe(v,money) for k,v in value.items() if money or 'cents' not in k}
    if isinstance(value,list):return [safe(v,money) for v in value]
    return value

def average(rows,key):
    values=[r[key] for r in rows if r.get(key) is not None]
    return mean(values) if values else None

def stamp(r,key,issues,required=True):
    if r.get(key) in [None,'']:
        if required:issues.append(key+'时间缺失')
        return None
    try:return dt(r[key])
    except (ValueError,TypeError):issues.append(key+'时间无效');return None

class ServiceBoard:
    def __init__(self,data,f,cutoff=None):
        self.data=data;self.f=f;self.cutoff=cutoff or analytics.AS_OF;self.end=dt(self.cutoff);self.global_issues=[]
        self.idx={ds:{r['id']:r for r in data.get(ds,[])} for ds in TABLES};self.cases={};self.children={ds:defaultdict(list) for ds in ['service_events','service_tasks','service_conditions']};self.packing=defaultdict(list)
        for p in data.get('shipment_units',[]):self.packing[p['unit_id']].append(p)
        for ds,groups in self.children.items():
            for r in data.get(ds,[]):
                groups[r.get('service_id')].append(r)
                if r.get('service_id') not in self.idx['service']:self.global_issues.append(r['id']+'：没有对应售后单')
        for r in data.get('service',[]):
            issues=[];reported=stamp(r,'reported',issues)
            if not reported:self.global_issues.append(r['id']+'：报修时间无效，无法归入日期队列');continue
            if reported<=self.end:self.cases[r['id']]=self.case(r,reported)

    def case(self,r,reported):
        timeline=[];links=[];sources=refs('service',[r]);response=stamp(r,'response',timeline,False);closed=stamp(r,'closed',timeline,False)
        if response and response<reported:timeline.append('首次响应早于报修')
        if closed and (closed<reported or response and closed<response):timeline.append('关闭早于报修或首次响应')
        if r.get('status') not in ['已关闭','跟进中','待响应']:timeline.append('未知售后台账状态')
        if r.get('status')=='已关闭' and not closed:timeline.append('已关闭状态缺少关闭时间')
        if closed and closed<=self.end and r.get('status')!='已关闭':timeline.append('关闭时间与台账状态不一致')
        if closed and closed<=self.end and not response:timeline.append('有关闭时间但缺少首次响应依据')
        responded=bool(response and reported<=response<=self.end)
        done=bool(not timeline and closed and closed<=self.end);opened=bool(not timeline and not done)
        unit=self.idx['units'].get(r.get('unit_id'));customer=self.idx['customers'].get(r.get('customer_id'));product=self.idx['products'].get(unit.get('product_id')) if unit else None
        if not unit:links.append('SN没有对应装配档案')
        if not customer:links.append('服务客户没有对应档案')
        if not product:links.append('SN配置没有对应档案')
        for ds,obj in [('units',unit),('customers',customer),('products',product)]:
            if obj:sources+=refs(ds,[obj])
        if unit:
            wo=self.idx['work_orders'].get(unit.get('work_order_id'))
            if wo:sources+=refs('work_orders',[wo])
            else:links.append('SN工单档案缺失')
            try:
                if dt(unit['assembly_at'])>reported:links.append('报修早于装配完成')
            except (ValueError,TypeError,KeyError):links.append('装配完成时间无效')
        shipments=[];eligible=[]
        for p in self.packing[r.get('unit_id')]:
            sources+=refs('shipment_units',[p]);s=self.idx['shipments'].get(p.get('shipment_id'))
            if not s:links.append('装箱关联发货行缺失');continue
            sources+=refs('shipments',[s]);problem=[];shipped=stamp(s,'shipped',problem)
            if problem:links.append('发货时间无效');continue
            if shipped>reported:continue
            line=self.idx['order_lines'].get(s.get('order_line_id'));order=self.idx['orders'].get(line.get('order_id')) if line else None
            for ds,obj in [('order_lines',line),('orders',order)]:
                if obj:sources+=refs(ds,[obj])
            if not line or not order:links.append('发货关联订单资料缺失');continue
            if unit and line.get('product_id')!=unit.get('product_id'):links.append('发货订单行配置与SN不符');continue
            ship_customer=self.idx['customers'].get(order.get('customer_id'))
            if ship_customer:sources+=refs('customers',[ship_customer])
            eligible.append(order.get('customer_id'));shipments.append({'packing_id':p['id'],'id':s['id'],'shipped':s['shipped'],'order_line_id':line['id'],'order_id':order['id'],'customer_id':order.get('customer_id')})
        if len(eligible)!=1:links.append('报修前未匹配唯一装箱发货关系，客户归属待核对')
        elif eligible[0]!=r.get('customer_id'):links.append('服务客户与发货客户不同，待核对渠道或转售关系')
        events=[];tasks=[];conditions=[];child_issues=[]
        for ds,target,timekey in [('service_events',events,'occurred'),('service_tasks',tasks,'created'),('service_conditions',conditions,'recorded')]:
            for child in self.children[ds][r['id']]:
                issues=[];time=stamp(child,timekey,issues)
                if time and time>self.end:continue
                if time and time<reported:issues.append('记录早于售后报修')
                owner=self.idx['employees'].get(child.get('owner_id'))
                if not owner:issues.append('负责工号缺少档案')
                else:sources+=refs('employees',[owner])
                out={**child,'owner_name':owner.get('name') if owner else '未匹配','issues':issues}
                if ds=='service_tasks':self.task(out,time,reported)
                elif ds=='service_events':
                    anchor={'客户报修':reported,'首次响应':response,'台账关闭':closed}.get(child.get('kind'))
                    if child.get('kind') in ['客户报修','首次响应','台账关闭'] and (not anchor or time!=anchor):issues.append('过程节点与售后原单时间不一致')
                    if closed and time and time>closed:issues.append('过程记录晚于台账关闭，待核对重开或后续联系')
                else:
                    value=child.get('value');unit_text=child.get('unit')
                    if value is not None and (type(value) not in [int,float] or not isfinite(value)):issues.append('客户自报数值格式无效')
                    if value is not None and not unit_text or value is None and unit_text and child.get('status')!='未提供':issues.append('数值与单位不完整')
                    if child.get('status') not in ['待核实','未提供','已核实']:issues.append('未知资料核实状态')
                    if child.get('status')=='未提供' and value is not None:issues.append('未提供状态却存在数值')
                target.append(out);sources+=refs(ds,[child]);child_issues += [child['id']+'：'+x for x in issues]
        for kind in ['客户报修','首次响应','台账关闭']:
            count=sum(x.get('kind')==kind for x in events)
            expected=kind=='客户报修' or kind=='首次响应' and responded or kind=='台账关闭' and done
            if count>1:child_issues.append(kind+'过程节点重复')
            if events and expected and count==0:child_issues.append(kind+'过程节点缺失')
        cost=r.get('cost_cents');cost_ok=type(cost) is int and cost>=0
        issues=timeline+links+child_issues
        row={**r,'customer_name':customer.get('name','') if customer else '未匹配','product_id':product.get('id','') if product else '', 'model':product.get('model','') if product else '', 'family':product.get('family','未匹配') if product else '未匹配', 'work_order_id':unit.get('work_order_id') if unit else None,
             'response_hours':(response-reported).total_seconds()/3600 if responded else None,'closed_hours':(closed-reported).total_seconds()/3600 if done else None,'open_hours':(self.end-reported).total_seconds()/3600 if opened else None,
             'calculated_state':'时间状态待核对' if timeline else '有关闭记录' if done else '截止未关闭','responded':responded,'closed_as_of':closed.isoformat() if done else None,'cost_cents':cost if cost_ok else None,'cost_issues':[] if cost_ok else ['费用分缺失或无效'],
             'event_count':len(events),'task_count':len(tasks),'condition_count':len(conditions),'missing_conditions':sum(x.get('status')=='未提供' for x in conditions),'unverified_conditions':sum(x.get('status')!='已核实' for x in conditions),
             'flags':['all']+(['closed'] if done else ['open'] if opened else [])+(['no_response'] if not responded and not timeline else [])+(['attention'] if issues else []),'issues':issues,'link_issues':links,'time_issues':timeline,'shipment_customer_match':len(eligible)==1 and eligible[0]==r.get('customer_id')}
        for task in tasks:task.update(unit_id=r.get('unit_id'),customer_id=r.get('customer_id'),customer_name=row['customer_name'],failure=r.get('failure'),family=row['family'])
        return {'row':row,'events':sorted(events,key=lambda x:(x.get('occurred') or '',x['id'])),'tasks':tasks,'conditions':conditions,'shipments':shipments,'sources':list({(x['dataset'],x['key']):x for x in sources}.values())}

    def task(self,out,created,reported):
        issues=out['issues'];due=stamp(out,'due',issues);completed=stamp(out,'completed',issues,False)
        if due and created and due<created:issues.append('期限早于任务建立')
        if completed and created and completed<created:issues.append('完成早于任务建立')
        if out.get('status') not in ['已完成','待资料','执行中']:issues.append('未知任务状态')
        if out.get('status')=='已完成' and not completed:issues.append('已完成状态缺少完成时间')
        if completed and completed<=self.end and out.get('status')!='已完成':issues.append('完成时间与任务状态不一致')
        done=bool(not issues and completed and completed<=self.end);opened=not issues and not done;overdue=bool(opened and due<self.end);late=bool(done and completed>due)
        out.update(calculated_state='数据待核对' if issues else '有完成记录' if done else '未完成且逾期' if overdue else '截止未完成',completed_as_of=completed.isoformat() if done else None,overdue_hours=(self.end-due).total_seconds()/3600 if overdue else 0 if not issues else None,
                   flags=['all']+(['attention'] if issues else ['done'] if done else ['open'])+(['overdue'] if overdue else [])+(['late'] if late else []))

    def selected_cases(self):
        f=self.f;out=[]
        for obj in self.cases.values():
            r=obj['row']
            if f['from'] and r['reported'][:10]<f['from'] or f['to'] and r['reported'][:10]>f['to']:continue
            if any(f[k] and r.get(field)!=f[k] for k,field in [('customer','customer_id'),('family','family'),('product','product_id'),('failure','failure'),('environment','environment')]):continue
            if f['q'] and f['q'].casefold() not in ' '.join(str(r.get(k) or '') for k in ['id','unit_id','customer_id','customer_name','model','failure','environment']).casefold():continue
            out.append(r)
        return sorted(out,key=lambda r:(r['reported'],r['id']),reverse=True)

    def selected(self):
        cases=self.selected_cases()
        if self.f['tab']=='cases':return cases
        return sorted([t for r in cases for t in self.cases[r['id']]['tasks']],key=lambda t:('overdue' not in t['flags'],t.get('due') or '',t['id']))

    def summary(self,rows):
        if self.f['tab']=='tasks':return {'objects':len(rows),**{k:sum(k in r['flags'] for r in rows) for k in ['open','done','overdue','late','attention']}}
        return {'objects':len(rows),'units':len({r['unit_id'] for r in rows}),'repeat_units':sum(n>1 for n in Counter(r['unit_id'] for r in rows).values()),**{k:sum(k in r['flags'] for r in rows) for k in ['open','closed','no_response','attention']},
                'response_hours':average(rows,'response_hours'),'response_count':sum(r['response_hours'] is not None for r in rows),'closed_hours':average(rows,'closed_hours'), 'cost_cents':sum(r['cost_cents'] for r in rows) if rows and all(r['cost_cents'] is not None for r in rows) else None,'cost_coverage':sum(r['cost_cents'] is not None for r in rows),
                'with_events':sum(r['event_count']>0 for r in rows),'with_tasks':sum(r['task_count']>0 for r in rows),'with_conditions':sum(r['condition_count']>0 for r in rows),'missing_conditions':sum(r['missing_conditions'] for r in rows),'unverified_conditions':sum(r['unverified_conditions'] for r in rows)}

    def breakdown(self,rows):
        def counts(key):
            names=Counter(r.get(key) or '未填写' for r in rows)
            return [{'name':k,'count':v} for k,v in sorted(names.items(),key=lambda kv:(-kv[1],kv[0]))]
        if self.f['tab']=='tasks':return {'kinds':counts('kind'),'owners':[{'name':e,'open':sum('open' in r['flags'] for r in rows if r['owner_id']==e),'done':sum('done' in r['flags'] for r in rows if r['owner_id']==e)} for e in sorted({r['owner_id'] for r in rows})]}
        return {'failures':counts('failure'),'environments':counts('environment'),'daily':[{'name':day,'count':sum(r['reported'][:10]==day for r in rows)} for day in sorted({r['reported'][:10] for r in rows})],
                'age':[{'name':name,'count':sum(r['open_hours'] is not None and lo<=r['open_hours']<hi for r in rows)} for name,lo,hi in [('不足24小时',0,24),('24至不足72小时',24,72),('72小时及以上',72,float('inf'))]]}

    def detail(self,key):
        if key not in {r['id'] for r in self.selected_cases()}:raise Record.DoesNotExist()
        return self.cases[key]

def current(f):return ServiceBoard({ds:list(Record.objects.filter(dataset=ds).values_list('values',flat=True)) for ds in TABLES},f)
