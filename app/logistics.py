"""Shipment-grain transport and receipt reconciliation from imported facts.

One active receipt decision per packed SN. Ambiguity is never resolved by row
order or by assuming that a historical signed timestamp means full acceptance.
"""
from collections import defaultdict,Counter
from datetime import datetime,date
from . import analytics

DATASETS=['transport_dispatches','transport_events','customer_receipts','customer_receipt_units']
STAGES={'all':'全部','review':'数量待核对','refused':'含拒收','partial':'部分接收','received':'全部接收','pending':'待签收','future':'未来发货'}
NOTE='合成Excel演练；每行一条发货明细，按已装箱SN核对客户接收。签收登记不等于质量验收或收入确认；拒收不自动形成退货或库存。原签收时间单列核对。到货承诺按运输交接登记，不能替代销售订单交期。'

def timestamp(v):
    try:
        if not isinstance(v,str) or len(v)!=19 or 'T' not in v:return None
        t=datetime.fromisoformat(v)
        return t if t.tzinfo is None else None
    except ValueError:return None

def day(v):
    try:return isinstance(v,str) and len(v)==10 and date.fromisoformat(v).isoformat()==v
    except ValueError:return False

def params(p):
    f={k:str(p.get(k,'') or '').strip() for k in ['q','customer_id','carrier','from','to','attention']}
    f['stage']=str(p.get('stage','all') or 'all')
    if f['stage'] not in STAGES or f['attention'] not in ['', 'issues','late']:raise ValueError('签收筛选不可用')
    for k in ['from','to']:
        if f[k] and not day(f[k]):raise ValueError('日期格式无效')
    if f['from'] and f['to'] and f['from']>f['to']:raise ValueError('开始日期不能晚于结束日期')
    if len(f['q'])>200:raise ValueError('搜索过长')
    return f

def source(ds,key):return {'dataset':ds,'key':key}

class Logistics:
    def __init__(self,tables,cutoff=None):
        self.cutoff=cutoff or analytics.AS_OF
        self.now=timestamp(self.cutoff)
        if not self.now:raise ValueError('截止时间无效')
        self.maps={k:{r['id']:r for r in rows} for k,rows in tables.items()}
        self.global_issues=[];self.rows={}
        def index(ds,field):
            d=defaultdict(list)
            for r in tables.get(ds,[]):d[r.get(field)].append(r)
            return d
        self.packs=index('shipment_units','shipment_id');self.dispatches=index('transport_dispatches','shipment_id')
        self.events=index('transport_events','dispatch_id');self.receipts=index('customer_receipts','dispatch_id');self.lines=index('customer_receipt_units','receipt_id')
        self.unit_packs=index('shipment_units','unit_id')
        for ds,field,parent in [('shipment_units','shipment_id','shipments'),('transport_dispatches','shipment_id','shipments'),('transport_events','dispatch_id','transport_dispatches'),('customer_receipts','dispatch_id','transport_dispatches'),('customer_receipt_units','receipt_id','customer_receipts')]:
            for r in tables.get(ds,[]):
                if r.get(field) not in self.maps.get(parent,{}):self.global_issues.append({'dataset':ds,'id':r['id'],'message':'父记录缺失：'+str(r.get(field))})
        for s in tables.get('shipments',[]):self.rows[s['id']]=self.build(s)

    def build(self,s):
        issues=[];qissues=[];timeline=[];evidence=[];sn_rows=[];excluded=0
        refs=[source('shipments',s['id'])];packs=self.packs[s['id']];dispatches=self.dispatches[s['id']]
        refs.extend(source('shipment_units',p['id']) for p in packs)
        units={p['unit_id'] for p in packs};shipped=timestamp(s.get('shipped'));qty=s.get('qty')
        order_line=self.maps.get('order_lines',{}).get(s.get('order_line_id'),{});order=self.maps.get('orders',{}).get(order_line.get('order_id'),{});customer=self.maps.get('customers',{}).get(order.get('customer_id'),{});product=self.maps.get('products',{}).get(order_line.get('product_id'),{})
        for ds,r in [('order_lines',order_line),('orders',order),('customers',customer),('products',product)]:
            if r:refs.append(source(ds,r['id']))
        if not order_line or not order or not customer or not product:qissues.append('订单、客户或配置关联缺失')
        if not shipped:qissues.append('发货时间无效')
        if type(qty) is not int or qty<=0 or len(units)!=qty or len(packs)!=len(units):qissues.append('发货数量与唯一装箱SN不一致')
        for uid in sorted(units):
            u=self.maps.get('units',{}).get(uid)
            refs.append(source('units',uid))
            if not u or u.get('product_id')!=order_line.get('product_id'):qissues.append('装箱SN缺失或配置与订单不符：'+uid)
            if len(self.unit_packs[uid])!=1:qissues.append('SN存在重复装箱关联：'+uid)
        if len(dispatches)!=1:issues.append('缺少唯一运输交接记录')
        if len(dispatches)>1:qissues.append('一条发货对应多条运输交接，需先核对拆单关系')
        d=dispatches[0] if len(dispatches)==1 else {}
        handed=timestamp(d.get('handed'));promised=timestamp(d.get('promised'))
        hand_ok=bool(shipped and handed and shipped<=handed<=self.now and d.get('reference'))
        promise_ok=bool(hand_ok and promised and promised>=handed)
        if d and not hand_ok:issues.append('交接时间或凭据待核对')
        if not promise_ok:issues.append('到货承诺缺失或时间顺序待核对')
        decisions=defaultdict(list)
        for dispatch in dispatches:
            refs.append(source('transport_dispatches',dispatch['id']))
            for e in sorted(self.events[dispatch['id']],key=lambda x:(str(x.get('occurred')),x['id'])):
                refs.append(source('transport_events',e['id']));t=timestamp(e.get('occurred'));reason=''
                if e.get('voided') is True:reason='作废节点'
                elif t and t>self.now:reason='未来节点'
                elif e.get('voided') is not False or not t or not shipped or t<shipped or (handed and t<handed) or e.get('kind') not in ['已交接','运输中','物流到达','运输异常']:reason='节点资料或时间无效';issues.append('运输节点待核对：'+e['id'])
                if not reason and e['kind']=='运输异常':issues.append('运输异常：'+e['note'])
                timeline.append({**e,'included':not reason,'exclusion':reason})
            for h in sorted(self.receipts[dispatch['id']],key=lambda x:(str(x.get('received')),x['id'])):
                refs.append(source('customer_receipts',h['id']));ls=self.lines[h['id']];t=timestamp(h.get('received'));reason=''
                if h.get('voided') is True:reason='作废凭据'
                elif t and t>self.now:reason='未来签收'
                elif h.get('voided') is not False or not t or not shipped or t<shipped or (handed and t<handed):reason='签收资料或时间无效';qissues.append('签收资料或时间无效：'+h['id'])
                elif not h.get('document') or not h.get('receiver'):reason='缺少签收文件编号或接收岗位';qissues.append('签收凭据要素缺失：'+h['id'])
                if not reason and not ls:qissues.append('签收凭据缺少SN明细：'+h['id'])
                evidence.append({**h,'included':not reason,'exclusion':reason,'units':len(ls)})
                for line in ls:
                    refs.append(source('customer_receipt_units',line['id']))
                    if reason:excluded+=1
                    else:
                        uid=line.get('unit_id')
                        if uid not in units:qissues.append('签收SN不属于本次装箱：'+str(uid))
                        if line.get('outcome') not in ['接收','拒收']:qissues.append('未知接收结论：'+line['id'])
                        if line.get('outcome')=='拒收' and not line.get('reason'):qissues.append('拒收原因缺失：'+line['id'])
                        decisions[uid].append({**line,'received':h['received'],'receipt_id':h['id']})
        for uid,ls in decisions.items():
            if len(ls)>1:qissues.append('同一SN存在多份有效接收结论：'+str(uid))
        for p in packs:
            ls=decisions.get(p['unit_id'],[])
            sn_rows.append({'id':p['unit_id'],'package':p['package'],'outcome':ls[0]['outcome'] if len(ls)==1 else '待签收' if not ls else '结论冲突','receipts':ls})
        current=bool(shipped and shipped<=self.now)
        valid=not qissues and current
        accepted=sum(ls[0]['outcome']=='接收' for ls in decisions.values()) if valid else None
        refused=sum(ls[0]['outcome']=='拒收' for ls in decisions.values()) if valid else None
        pending=qty-accepted-refused if valid else None
        full=max((ls[0]['received'] for ls in decisions.values()),default=None) if valid and accepted==qty else None
        stage='review' if qissues else 'future' if not current else 'refused' if refused else 'received' if full else 'partial' if accepted else 'pending'
        due=bool(current and promise_ok and promised<=self.now)
        on_time=bool(full and timestamp(full)<=promised) if due and valid else None
        late=bool(due and valid and not on_time)
        legacy=s.get('signed');legacy_t=timestamp(legacy)
        if not legacy:legacy_check='原台账无签收时间'
        elif not legacy_t:legacy_check='原签收时间无效'
        elif legacy_t>self.now:legacy_check='原签收时间在截止后'
        elif not full:legacy_check='原台账已签收，SN尚未全部接收'
        elif legacy_t!=timestamp(full):legacy_check='原签收与全量SN接收时间不同'
        else:legacy_check='原签收与全量SN接收时间一致'
        if legacy_t and legacy_t<=self.now and (not full or legacy_t!=timestamp(full)):issues.append(legacy_check)
        refs=list({(r['dataset'],r['key']):r for r in refs}.values())
        return {**s,'customer_id':order.get('customer_id'),'customer_name':customer.get('name','关联缺失'),'product_id':order_line.get('product_id'),'family':product.get('family'),'dispatch_id':d.get('id'),'handed':d.get('handed'),'promised':d.get('promised'),'route':d.get('route'),'reference':d.get('reference'),'stage':stage,'stage_label':STAGES[stage],'packed_qty':len(units),'accepted':accepted,'refused':refused,'pending':pending,'full_received':full,'due':due,'on_time':on_time,'late':late,'promise_ok':promise_ok,'handover_ok':hand_ok,'legacy_check':legacy_check,'issues':list(dict.fromkeys(qissues+issues)),'quantity_issues':list(dict.fromkeys(qissues)),'excluded_units':excluded,'timeline':sorted(timeline,key=lambda e:(str(e.get('occurred')),e['id'])),'receipts':evidence,'units':sn_rows,'sources':refs}

    def selected(self,f):
        out=[]
        for r in self.rows.values():
            if f['stage']!='all' and r['stage']!=f['stage']:continue
            if f['customer_id'] and r['customer_id']!=f['customer_id']:continue
            if f['carrier'] and r['carrier']!=f['carrier']:continue
            if f['from'] and (r.get('shipped') or '')[:10]<f['from']:continue
            if f['to'] and (r.get('shipped') or '')[:10]>f['to']:continue
            if f['attention']=='issues' and not r['issues']:continue
            if f['attention']=='late' and not r['late']:continue
            if f['q'] and f['q'].casefold() not in ' '.join(str(r.get(k) or '') for k in ['id','tracking','order_line_id','customer_id','customer_name','product_id','dispatch_id']).casefold() and not any(f['q'].casefold() in u['id'].casefold() for u in r['units']):continue
            out.append(r)
        return sorted(out,key=lambda r:(r['shipped'],r['id']),reverse=True)

    def detail(self,key):
        if key not in self.rows:
            from django.core.exceptions import ObjectDoesNotExist
            raise ObjectDoesNotExist()
        return self.rows[key]

def summary(rows):
    known=[r for r in rows if r['accepted'] is not None];due=[r for r in rows if r['due']];rated=[r for r in due if r['on_time'] is not None]
    return {'rows':len(rows),'quantity_known_rows':len(known),'quantity_unknown_rows':sum(r['stage']=='review' for r in rows),'future_rows':sum(r['stage']=='future' for r in rows),'accepted':sum(r['accepted'] for r in known) if known else None,'refused':sum(r['refused'] for r in known) if known else None,'pending':sum(r['pending'] for r in known) if known else None,'known_shipped':sum(r['qty'] for r in known) if known else None,'due_rows':len(due),'rated_due_rows':len(rated),'unknown_due_rows':len(due)-len(rated),'on_time_rows':sum(r['on_time'] for r in rated),'due_rate':sum(r['on_time'] for r in rated)/len(rated)*100 if rated else None,'unpromised_rows':sum(not r['promise_ok'] and r['stage']!='future' for r in rows),'issue_rows':sum(bool(r['issues']) for r in rows),'stages':dict(Counter(r['stage'] for r in rows))}

def safe(r):return {k:v for k,v in r.items() if k not in ['timeline','receipts','units','sources']}
def current():return Logistics(analytics.tables())
