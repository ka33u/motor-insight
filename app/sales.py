"""Quote-cohort workbench with explicit, quantity-bounded order attribution."""
from collections import defaultdict,Counter
from datetime import date
from statistics import median
from . import analytics
from .models import Record
from .engineering import day,refs,unique_sources,safe

TABLES=['quotes','quote_details','quote_order_links','quote_tasks','customers','products','employees','order_lines','orders']
STATUS=['已转订单','部分转单','跟进中','待技术确认','已失单','客户暂停']
OPEN={'部分转单','跟进中','待技术确认','客户暂停'}
STAGES={'quotes':{'all':'全部报价','open':'仍待跟进','expired':'待跟进且已过有效期','linked':'有有效订单关联','unproven':'转单标记待核对','attention':'有资料问题'},'tasks':{'all':'全部任务','open':'未完成','overdue':'未完成且逾期','done':'有完成记录','attention':'有资料问题'}}
NOTE='全部为模拟Excel。日期选择报价发出队列，状态和任务核对至业务截止；一条报价对应一种配置。转单标记、有效订单关联和跟进完成分别展示，不把报价金额当收入，也不从客户/型号相同推断成交。'

def filters(q):
    keys=['from','to','customer','family','product','owner','task_owner','quote_status','q']
    if set(q)-set(keys+['tab','stage','page']):raise ValueError('不支持的销售筛选')
    f={k:q.get(k,'') for k in keys};f.update(tab=q.get('tab','quotes'),stage=q.get('stage','all'))
    if f['tab'] not in STAGES or f['stage'] not in STAGES[f['tab']]:raise ValueError('工作区或清单状态不可用')
    if f['tab']=='quotes' and f['task_owner']:raise ValueError('任务责任人仅适用于跟进任务页')
    if f['quote_status'] and f['quote_status'] not in STATUS:raise ValueError('报价状态不可用')
    if any(len(v)>150 for v in f.values()):raise ValueError('筛选内容过长')
    for k in ['from','to']:
        if f[k] and (date.fromisoformat(f[k]).isoformat()!=f[k] or f[k]>analytics.AS_OF[:10]):raise ValueError('报价日期须在业务截止日以内')
    if f['from'] and f['to'] and f['from']>f['to']:raise ValueError('开始日期不能晚于结束日期')
    return f

def integer(v,positive=False):return type(v) is int and (v>0 if positive else v>=0)
def total(values):return sum(values) if values else None

class Sales:
    def __init__(self,data,f,cutoff=None):
        self.data={k:data.get(k,[]) for k in TABLES};self.f=f;self.cutoff=cutoff or analytics.AS_OF;self.as_of=date.fromisoformat(self.cutoff[:10]);self.global_issues=[]
        self.idx={k:{r['id']:r for r in rows} for k,rows in self.data.items()}
        self.children={k:defaultdict(list) for k in ['quote_details','quote_order_links','quote_tasks']}
        for ds in self.children:
            for r in self.data[ds]:
                self.children[ds][r.get('quote_id')].append(r)
                if r.get('quote_id') not in self.idx['quotes']:self.global_issues.append(r['id']+'没有对应报价')
        self.quotes={};self.links={};self.tasks={}
        for q in self.data['quotes']:
            issues=[];quoted=day(q,'quote_date',issues)
            if quoted is None:self.global_issues.append(q['id']+'报价日期无效，不能归入队列');continue
            if quoted<=self.as_of:self.quotes[q['id']]=self.quote(q,quoted)
        for r in self.data['quote_order_links']:
            if r.get('quote_id') in self.quotes:
                link=self.link(r)
                if not link['future']:self.links[r['id']]=link
                else:self.quotes[r['quote_id']]['future_links']+=1
        candidates=[x for x in self.links.values() if not x['issues']]
        quote_qty=Counter();order_qty=Counter();pairs=Counter((x['quote_id'],x['order_line_id']) for x in candidates)
        for x in candidates:quote_qty[x['quote_id']]+=x['qty'];order_qty[x['order_line_id']]+=x['qty']
        for x in candidates:
            if pairs[x['quote_id'],x['order_line_id']]>1:x['issues'].append('同一报价与订单行关联重复')
            if quote_qty[x['quote_id']]>self.quotes[x['quote_id']]['row']['qty']:x['issues'].append('该报价关联数量合计超过报价数量')
            if order_qty[x['order_line_id']]>self.idx['order_lines'][x['order_line_id']]['qty']:x['issues'].append('该订单行被分配的报价数量合计超额')
        for obj in self.quotes.values():self.finish_quote(obj)

    def quote(self,q,quoted):
        issues=[];state_issues=[];sources=refs('quotes',[q]);valid=day(q,'valid_until',state_issues)
        if valid and valid<quoted:state_issues.append('报价有效截至早于报价日期')
        if q.get('status') not in STATUS:state_issues.append('未知报价状态')
        if not integer(q.get('qty'),True):issues.append('报价数量须为正整数')
        if not integer(q.get('unit_price_cents')):issues.append('报价单价须为非负整数分')
        customer=self.idx['customers'].get(q.get('customer_id'));product=self.idx['products'].get(q.get('product_id'))
        for ds,r in [('customers',customer),('products',product)]:
            if r:sources+=refs(ds,[r])
            else:issues.append(ds+'档案缺失')
        details=self.children['quote_details'][q['id']];sources+=refs('quote_details',details)
        meta=details[0] if len(details)==1 else None
        if not meta:issues.append('报价商务资料缺失或重复，责任和计价口径待核对')
        owner=None;inquiry=None;outcome=None;response_days=None
        if meta:
            owner=self.idx['employees'].get(meta.get('owner_id'));inquiry=day(meta,'inquiry_date',issues);outcome=day(meta,'outcome_date',state_issues,False)
            if owner:sources+=refs('employees',[owner])
            else:issues.append('报价责任工号没有人员档案')
            if inquiry and inquiry>quoted:issues.append('收到询价晚于报价日期')
            elif inquiry:response_days=(quoted-inquiry).days
            if meta.get('currency') not in ['CNY','USD','EUR']:issues.append('报价币种未识别')
            if meta.get('tax_basis') not in ['未税','含税']:issues.append('报价价税口径待确认')
        if q.get('status') in ['已转订单','部分转单','已失单']:
            if not outcome:state_issues.append('结果状态缺少确认日期')
        elif outcome:state_issues.append('待跟进状态却有结果日期')
        if outcome and outcome<quoted:state_issues.append('结果确认早于报价')
        if outcome and outcome>self.as_of:state_issues.append('结果确认晚于截止，历史状态待核对')
        state_known=not state_issues;opened=state_known and q.get('status') in OPEN
        expired=bool(opened and valid and valid<self.as_of)
        issues+=state_issues
        row={**q,'customer_name':customer.get('name') if customer else '未匹配','region':customer.get('region') if customer else '', 'industry':customer.get('industry') if customer else '', 'model':product.get('model') if product else '未匹配','family':product.get('family') if product else '', 'owner_id':meta.get('owner_id') if meta else '', 'owner_name':owner.get('name') if owner else '待补','currency':meta.get('currency') if meta else None,'tax_basis':meta.get('tax_basis') if meta else None,'version':meta.get('version') if meta else None,'inquiry_date':inquiry.isoformat() if inquiry else None,'outcome_date':outcome.isoformat() if outcome else None,'quote_days':response_days,'state_known':state_known,'open':opened,'expired':expired,'expiry_days':(self.as_of-valid).days if expired else 0,'calculated_state':q.get('status') if state_known else '截止状态待核对','issues':issues}
        return {'row':row,'metadata':meta,'sources':sources,'links':[],'tasks':[],'future_links':0}

    def link(self,r):
        issues=[];sources=refs('quote_order_links',[r]);obj=self.quotes[r['quote_id']];q=obj['row'];confirmed=day(r,'confirmed',issues);line=self.idx['order_lines'].get(r.get('order_line_id'));order=self.idx['orders'].get(line.get('order_id')) if line else None
        qty=r.get('qty');order_day=None
        if r.get('status')!='有效':issues.append('关联状态未经确认')
        if not integer(qty,True):issues.append('对应数量须为正整数')
        if not integer(q.get('qty'),True):issues.append('原报价数量无效')
        if q.get('status') not in ['已转订单','部分转单'] or not q['state_known']:issues.append('转单关联与报价截止状态不一致')
        if confirmed and confirmed<date.fromisoformat(q['quote_date']):issues.append('确认日期早于报价')
        if not line or not order:issues.append('关联订单行或订单缺失')
        else:
            sources+=refs('order_lines',[line])+refs('orders',[order]);order_day=day(order,'order_date',issues)
            if order.get('customer_id')!=q['customer_id']:issues.append('订单客户与报价客户不同')
            if line.get('product_id')!=q['product_id']:issues.append('订单配置与报价配置不同')
            if not integer(line.get('qty'),True):issues.append('订单行数量无效')
            if order.get('status') not in ['待生产','执行中','部分交付','已交付','已完成']:issues.append('订单状态无效或需核对')
            if order_day and (order_day<date.fromisoformat(q['quote_date']) or confirmed and confirmed<order_day):issues.append('订单与关联确认日期顺序异常')
        future=bool(confirmed and confirmed>self.as_of or order_day and order_day>self.as_of)
        price_ok=bool(line and order and q['currency']==order.get('currency')=='CNY' and q['tax_basis']=='未税' and integer(q.get('unit_price_cents')) and integer(line.get('unit_price_cents')) and integer(qty,True))
        return {**r,'issues':issues,'future':future,'sources':sources,'order_id':order.get('id') if order else None,'order_date':order.get('order_date') if order else None,'order_currency':order.get('currency') if order else None,'order_unit_price_cents':line.get('unit_price_cents') if line else None,'quote_unit_price_cents':q.get('unit_price_cents'),'price_comparable':price_ok,'order_value_cents':line['unit_price_cents']*qty if price_ok else None,'quote_reference_cents':q['unit_price_cents']*qty if price_ok else None,'price_difference_cents':(line['unit_price_cents']-q['unit_price_cents'])*qty if price_ok else None}

    def task(self,r,q):
        issues=[];sources=refs('quote_tasks',[r]);created=day(r,'created',issues);due=day(r,'due',issues);done_date=day(r,'completed',issues,False);owner=self.idx['employees'].get(r.get('owner_id'))
        if owner:sources+=refs('employees',[owner])
        else:issues.append('任务责任工号没有人员档案')
        if created and created<date.fromisoformat(q['quote_date']):issues.append('任务建立早于报价')
        if created and due and due<created:issues.append('任务期限早于建立')
        if created and done_date and done_date<created:issues.append('任务完成早于建立')
        if r.get('status') not in ['已完成','待反馈']:issues.append('未知任务状态')
        if r.get('status')=='已完成' and not done_date:issues.append('完成状态缺少日期')
        if done_date and done_date<=self.as_of and r.get('status')!='已完成':issues.append('完成日期与状态不一致')
        future=bool(created and created>self.as_of);done=bool(not issues and not future and done_date and done_date<=self.as_of);opened=not issues and not future and not done;overdue=bool(opened and due and due<self.as_of)
        return {**r,'issues':issues,'sources':sources,'future':future,'done':done,'open':opened,'overdue':overdue,'late':bool(done and due and done_date>due),'completed_as_of':done_date.isoformat() if done else None,'calculated_state':'资料待核对' if issues else '有完成记录' if done else '未完成且逾期' if overdue else '截止未完成','owner_name':owner.get('name') if owner else '未匹配','customer_name':q['customer_name'],'product_id':q['product_id'],'model':q['model'],'flags':['all']+(['done'] if done else ['open'] if opened else [])+(['overdue'] if overdue else [])+(['attention'] if issues else [])}

    def finish_quote(self,obj):
        q=obj['row'];links=[x for x in self.links.values() if x['quote_id']==q['id']];good=[x for x in links if not x['issues']]
        tasks=[self.task(x,q) for x in self.children['quote_tasks'][q['id']]];future_tasks=sum(t['future'] for t in tasks);tasks=[t for t in tasks if not t['future']]
        for x in links+tasks:q['issues'] += [x['id']+'：'+y for y in x['issues']];obj['sources']+=x['sources']
        unknown=any(x['issues'] for x in links)
        linked_qty=None if unknown else sum(x['qty'] for x in good)
        unproven=q.get('status') in ['已转订单','部分转单'] and (not q['state_known'] or linked_qty is None or not good or q['status']=='已转订单' and linked_qty!=q['qty'] or q['status']=='部分转单' and not 0<linked_qty<q['qty'])
        if unproven:q['issues'].append('转单台账状态与可核对关联数量未一致')
        if not tasks:q['issues'].append('未登记跟进任务')
        comparable=[x for x in good if x['price_comparable']]
        q.update(linked_qty=linked_qty,unlinked_qty=q['qty']-linked_qty if integer(q.get('qty'),True) and linked_qty is not None else None,valid_links=len(good),invalid_links=len(links)-len(good),comparable_links=len(comparable),order_value_cents=total([x['order_value_cents'] for x in comparable]),quote_reference_cents=total([x['quote_reference_cents'] for x in comparable]),price_difference_cents=total([x['price_difference_cents'] for x in comparable]),tasks=len(tasks),completed_tasks=sum(t['done'] for t in tasks),overdue_tasks=sum(t['overdue'] for t in tasks),unproven=bool(unproven),flags=['all']+(['open'] if q['open'] else [])+(['expired'] if q['expired'] else [])+(['linked'] if good else [])+(['unproven'] if unproven else [])+(['attention'] if q['issues'] else []))
        obj.update(links=links,tasks=sorted(tasks,key=lambda x:(not x['overdue'],x.get('due') or '',x['id'])),future_tasks=future_tasks,sources=unique_sources(obj['sources']))
        self.tasks.update({x['id']:x for x in tasks})

    def selected(self):
        f=self.f;rows=[]
        for obj in self.quotes.values():
            q=obj['row']
            if any(f[k] and f[k]!=q.get(target) for k,target in [('customer','customer_id'),('product','product_id'),('family','family'),('owner','owner_id'),('quote_status','status')]):continue
            if f['from'] and q['quote_date']<f['from'] or f['to'] and q['quote_date']>f['to']:continue
            if f['q'] and f['q'].lower() not in ' '.join(str(q.get(k,'')) for k in ['id','customer_name','model','reason']).lower():continue
            rows.append(q)
        return sorted(rows,key=lambda r:(not r['unproven'],not r['expired'],-r['overdue_tasks'],r['id']))

    def task_rows(self,quotes):
        keys={q['id'] for q in quotes};owner=self.f['task_owner']
        return sorted([t for t in self.tasks.values() if t['quote_id'] in keys and (not owner or owner==t['owner_id'])],key=lambda r:(not r['overdue'],r.get('due') or '',r['id']))

    def summary(self,quotes):
        tasks=self.task_rows(quotes);valid=[x for q in quotes for x in self.quotes[q['id']]['links'] if not x['issues']];comparable=[x for x in valid if x['price_comparable']]
        waits=[q['quote_days'] for q in quotes if q['quote_days'] is not None]
        return {'quotes':len(quotes),'open':sum(q['open'] for q in quotes),'expired':sum(q['expired'] for q in quotes),'linked_quotes':sum(q['valid_links']>0 for q in quotes),'unproven':sum(q['unproven'] for q in quotes),'attention':sum(bool(q['issues']) for q in quotes),'tasks':len(tasks),'completed_tasks':sum(t['done'] for t in tasks),'open_tasks':sum(t['open'] for t in tasks),'overdue_tasks':sum(t['overdue'] for t in tasks),'late_tasks':sum(t['late'] for t in tasks),'task_quotes':len({t['quote_id'] for t in tasks}),'task_attention':sum(bool(t['issues']) for t in tasks),'valid_links':len(valid),'comparable_links':len(comparable),'order_lines':len({x['order_line_id'] for x in valid}),'order_value_cents':total([x['order_value_cents'] for x in comparable]),'quote_reference_cents':total([x['quote_reference_cents'] for x in comparable]),'price_difference_cents':total([x['price_difference_cents'] for x in comparable]),'quote_days_median':median(waits) if waits else None,'quote_days_samples':len(waits)}

    def detail(self,key):
        if key not in {q['id'] for q in self.selected()}:raise Record.DoesNotExist()
        return self.quotes[key]

def current(f):return Sales({ds:list(Record.objects.filter(dataset=ds).values_list('values',flat=True)) for ds in TABLES},f)
