"""Receivable-level reconciliation. Money is integer CNY cents; dates are daily.

Opening balances are never revenue. Raw invoice status is not a payment event.
The existing invoice-only semantic model remains unchanged.
"""
from collections import defaultdict
from datetime import date
from . import analytics

KINDS={'opening':'历史期初','invoice':'已导入发票'}
STAGES={'all':'全部','overdue':'逾期未结','due_today':'今日到期','not_due':'尚未到期','settled':'已结清','review':'待核对','future':'截止日后生效'}
BUCKETS={'not_due':'尚未到期','due_today':'今日到期','d1_30':'逾期1–30天','d31_60':'逾期31–60天','d61_90':'逾期61–90天','d91_180':'逾期91–180天','d181_plus':'逾期180天以上','settled':'已结清','review':'待核对','future':'截止日后生效'}
NOTE='仅核对已导入的CNY含税应收，按2026-10-01日记录计算；来源只有日期，不声称日内时点余额。历史期初使用切入日未核销余额，不计作本期销售。核销不等同银行流水。当前页不包含未开票应收、预收款、坏账计提或其他币种折算。'

def day(value):
    if not isinstance(value,str):return None
    try:
        d=date.fromisoformat(value)
        return d if d.isoformat()==value else None
    except ValueError:return None

def integer(value,minimum=None):
    return type(value) is int and (minimum is None or value>=minimum)

def filters(params):
    f={k:str(params.get(k,'') or '').strip() for k in ['customer_id','kind','q','bucket']}
    f['stage']=str(params.get('stage','all') or 'all')
    if f['kind'] and f['kind'] not in KINDS:raise ValueError('应收来源类型不可用')
    if f['bucket'] and f['bucket'] not in BUCKETS:raise ValueError('账龄区间不可用')
    if f['stage'] not in STAGES:raise ValueError('应收状态不可用')
    if len(f['q'])>200:raise ValueError('查询条件过长')
    return f

def aging(days):
    if days<0:return 'not_due'
    if days==0:return 'due_today'
    for limit,key in [(30,'d1_30'),(60,'d31_60'),(90,'d61_90'),(180,'d91_180')]:
        if days<=limit:return key
    return 'd181_plus'

class ReceivableData:
    def __init__(self,tables,cutoff=analytics.DAY):
        self.cutoff=cutoff;self.date=day(cutoff)
        if not self.date:raise ValueError('截止日期无效')
        self.tables=tables;self.rows=[];self.index={};self.global_issues=[]
        self.maps={k:{r['id']:r for r in tables.get(k,[])} for k in ['customers','orders','order_lines','shipments','invoices','ar_opening']}
        self.payments=defaultdict(list);self.events=defaultdict(list)
        for key,fk,dest,target in [('payments','invoice_id',self.payments,'invoices'),('ar_events','opening_id',self.events,'ar_opening')]:
            for r in tables.get(key,[]):
                if r.get(fk) not in self.maps[target]:self.global_issues.append(dict(dataset=key,id=r['id'],message='关联应收对象不存在'))
                else:dest[r[fk]].append(r)
        for kind,dataset in [('opening','ar_opening'),('invoice','invoices')]:
            for obj in tables.get(dataset,[]):self.rows.append(self.build(kind,obj))
        # The model knows internal invoice IDs, not legal invoice numbers. Only
        # exact imported identities are checked; do not claim broader matching.
        docs=defaultdict(list)
        for r in self.rows:docs[(r['customer_id'],r['currency'],r['document_no'])].append(r)
        for group in docs.values():
            if len(group)>1:
                for r in group:r['issues'].append('客户、币种和原单据号重复，不能重复计入应收')
        for r in self.rows:
            self.finish(r);self.index[r['key']]=r

    def build(self,kind,obj):
        cust=self.maps['customers'].get(obj.get('customer_id'),{})
        r=dict(id=obj['id'],key=kind+':'+obj['id'],kind=kind,kind_label=KINDS[kind],customer_id=obj.get('customer_id'),customer_name=cust.get('name','客户缺失'),region=cust.get('region','未登记'),
               document_no=obj.get('document_no',obj['id']),issued=obj.get('issued'),due=obj.get('due'),basis_date=obj.get('as_of') if kind=='opening' else obj.get('issued'),
               currency=obj.get('currency') if kind=='opening' else None,original_gross_cents=None,basis_cents=None,receipt_cents=0,reversal_cents=0,credit_cents=0,
               net_receipt_cents=None,balance_cents=None,raw_status=obj.get('status','期初未核销'),issues=[],ledger=[],sources=[],daily=[],future_events=0,excluded_events=0)
        def source(ds,key):
            if key:r['sources'].append({'dataset':ds,'key':key})
        source('ar_opening' if kind=='opening' else 'invoices',obj['id']);source('customers',obj.get('customer_id'))
        if not cust:r['issues'].append('客户档案缺失')
        issued=day(r['issued']);due=day(r['due']);basis=day(r['basis_date'])
        if not issued or not due or not basis:r['issues'].append('开票、到期或期初日期无效')
        if issued and due and due<issued:r['issues'].append('到期日期早于开票日期')
        if kind=='opening':
            gross=obj.get('original_gross_cents');amount=obj.get('opening_balance_cents')
            if not integer(gross,0) or not integer(amount,0) or amount>gross:r['issues'].append('期初或原单金额无效，或期初余额超过原单全额')
            else:r.update(original_gross_cents=gross,basis_cents=amount)
            if issued and basis and issued>=basis:r['issues'].append('期初原单必须早于期初零时切入日')
            if not r['document_no']:r['issues'].append('原单据号缺失')
            events=self.events[obj['id']]
        else:
            net=obj.get('net_cents');tax=obj.get('tax_cents')
            if not integer(net,0) or not integer(tax,0):r['issues'].append('发票金额或税额无效')
            else:r.update(original_gross_cents=net+tax,basis_cents=net+tax)
            ship=self.maps['shipments'].get(obj.get('shipment_id'),{})
            line=self.maps['order_lines'].get(ship.get('order_line_id'),{})
            order=self.maps['orders'].get(line.get('order_id'),{})
            source('shipments',obj.get('shipment_id'));source('order_lines',ship.get('order_line_id'));source('orders',line.get('order_id'))
            r['currency']=order.get('currency')
            if not ship or not line or not order:r['issues'].append('发票到发货/订单关系不完整，币种和客户待核对')
            if order and order.get('customer_id')!=r['customer_id']:r['issues'].append('发票与订单客户不一致')
            shipped=day(str(ship.get('shipped',''))[:10])
            if issued and shipped and issued<shipped:r['issues'].append('当前导入模型的开票早于发货，需核对单据关系')
            if obj.get('status') not in ['已收款','部分收款','未收款','已开票']:r['issues'].append('发票状态未纳入当前核对规则，需确认作废/冲销依据')
            events=[dict(id=p['id'],occurred=p.get('paid'),kind='收款核销',delta_cents=-p['amount_cents'] if integer(p.get('amount_cents'),1) else None,status='已过账',document_no=p['id'],reverses_id=None,reason=p.get('method','')) for p in self.payments[obj['id']]]
        if r['currency']!='CNY':r['issues'].append('当前工作台仅核对CNY，币种缺失或其他币种需另行核对')
        byid={e['id']:e for e in events};reversed_total=defaultdict(int)
        ordered=sorted(events,key=lambda e:(str(e.get('occurred','')),e['id']))
        for e in ordered:
            source('ar_events' if kind=='opening' else 'payments',e['id'])
            entry={**e,'included':False,'exclusion':'','day_balance_cents':None};r['ledger'].append(entry)
            when=day(e.get('occurred'));status=e.get('status')
            if status in ['草稿','已撤销']:
                entry['exclusion']=status+'，不计入';r['excluded_events']+=1;continue
            if status!='已过账':
                entry['exclusion']='过账状态未知';r['issues'].append(e['id']+'：过账状态未知');continue
            if not when:
                entry['exclusion']='过账日期无效';r['issues'].append(e['id']+'：过账日期无效');continue
            if when>self.date:
                entry['exclusion']='截止日之后';r['future_events']+=1;continue
            problems=[];amount=e.get('delta_cents');event_kind=e.get('kind')
            if not basis or when<basis:problems.append('事件早于余额起点或起点无效')
            if not integer(amount) or amount==0:problems.append('金额必须为非零整数分')
            elif event_kind in ['收款核销','贷项冲减']:
                if amount>=0:problems.append('收款或贷项必须减少余额')
                if e.get('reverses_id'):problems.append('非冲回事件不能引用冲回原事件')
            elif event_kind=='核销冲回':
                ref=byid.get(e.get('reverses_id'));refday=day(ref.get('occurred')) if ref else None
                if amount<=0:problems.append('核销冲回必须增加余额')
                if not ref or ref.get('kind')!='收款核销' or ref.get('status')!='已过账' or not integer(ref.get('delta_cents')) or ref['delta_cents']>=0:
                    problems.append('未关联同笔期初的有效已过账收款')
                elif not refday or refday>when or not basis or refday<basis:problems.append('原收款日期与冲回顺序无效')
                elif amount>0:
                    reversed_total[ref['id']]+=amount
                    if reversed_total[ref['id']]>-ref['delta_cents']:problems.append('累计冲回超过原核销金额')
            else:problems.append('事件类型未支持')
            if problems:
                entry['exclusion']='；'.join(problems);r['issues'].append(e['id']+'：'+entry['exclusion']);continue
            entry['included']=True
            if event_kind=='收款核销':r['receipt_cents']-=amount
            elif event_kind=='贷项冲减':r['credit_cents']-=amount
            elif event_kind=='核销冲回':r['reversal_cents']+=amount
        r['_future']=bool(basis and basis>self.date)
        if integer(r['basis_cents']):
            balance=r['basis_cents'];deltas=defaultdict(int)
            for e in r['ledger']:
                if e['included']:deltas[e['occurred']]+=e['delta_cents']
            for current,delta in sorted(deltas.items()):
                before=balance;balance+=delta
                r['daily'].append({'date':current,'before_cents':before,'delta_cents':delta,'balance_cents':balance})
                if balance<0:r['issues'].append(current+'：日末核销后余额为负，需核对超额核销或预收关系')
            r['_balance']=balance
        else:r['_balance']=None
        return r

    def finish(self,r):
        r['issues']=list(dict.fromkeys(r['issues']))
        r['net_receipt_cents']=r['receipt_cents']-r['reversal_cents']
        r['overdue_days']=None
        if r['issues']:r.update(stage='review',bucket='review')
        elif r['_future']:r.update(stage='future',bucket='future')
        else:
            r['balance_cents']=r['_balance']
            days=(self.date-day(r['due'])).days
            r['overdue_days']=max(days,0) if r['balance_cents']>0 else 0
            r['bucket']='settled' if r['balance_cents']==0 else aging(days)
            r['stage']='settled' if r['balance_cents']==0 else 'overdue' if days>0 else 'due_today' if days==0 else 'not_due'
        if r['stage'] not in ['review','future']:
            ends={x['date']:x['balance_cents'] for x in r['daily']}
            for e in r['ledger']:
                if e['included']:e['day_balance_cents']=ends[e['occurred']]
        else:
            for entry in r['daily']:entry['balance_cents']=None;entry['before_cents']=None
        r['status_label']=STAGES[r['stage']];r['bucket_label']=BUCKETS[r['bucket']]

    def selected(self,f,ignore_stage=False):
        result=[]
        for r in self.rows:
            if f['customer_id'] and r['customer_id']!=f['customer_id']:continue
            if f['kind'] and r['kind']!=f['kind']:continue
            if f['bucket'] and r['bucket']!=f['bucket']:continue
            if not ignore_stage and f['stage']!='all' and r['stage']!=f['stage']:continue
            if f['q'] and f['q'].lower() not in ' '.join(str(r[k]) for k in ['id','document_no','customer_id','customer_name']).lower():continue
            result.append(r)
        rank={'review':0,'overdue':1,'due_today':2,'not_due':3,'settled':4,'future':5}
        return sorted(result,key=lambda r:(rank[r['stage']],-(r['overdue_days'] or 0),-(r['balance_cents'] or 0),r['key']))

    def detail(self,kind,key):
        if kind not in KINDS:raise ValueError('应收类型不可用')
        r=self.index.get(kind+':'+key)
        if not r:raise ValueError('应收对象不存在')
        ds='ar_opening' if kind=='opening' else 'invoices'
        return {'row':safe(r),'ledger':r['ledger'],'daily':r['daily'],'original':self.maps[ds][key],'sources':r['sources']}

def safe(r):return {k:v for k,v in r.items() if not k.startswith('_') and k not in ['ledger','sources','daily']}
def current():return ReceivableData(analytics.tables())

def summary(rows):
    valid=[r for r in rows if r['balance_cents'] is not None]
    s={'rows':len(rows),'valid_rows':len(valid),'review_rows':sum(r['stage']=='review' for r in rows),'future_rows':sum(r['stage']=='future' for r in rows),'customers':len({r['customer_id'] for r in rows}),
       'overdue_rows':sum(r['stage']=='overdue' for r in rows),'settled_rows':sum(r['stage']=='settled' for r in rows),'overdue_cents':sum(r['balance_cents'] for r in valid if r['stage']=='overdue'),
       'future_events':sum(r['future_events'] for r in rows),'excluded_events':sum(r['excluded_events'] for r in rows)}
    for k in ['basis_cents','receipt_cents','reversal_cents','net_receipt_cents','credit_cents','balance_cents']:s[k]=sum(r[k] for r in valid)
    s['overdue_ratio']=s['overdue_cents']/s['balance_cents']*100 if s['balance_cents'] else None
    s['complete']=not s['review_rows']
    return s

def breakdown(rows):
    groups=defaultdict(list)
    for r in rows:groups[r['customer_id']].append(r)
    customers=[{'id':key,'name':group[0]['customer_name'],**summary(group)} for key,group in groups.items()]
    customers.sort(key=lambda r:(-r['overdue_cents'],-r['balance_cents'],r['id']))
    return {'aging':[dict(key=k,label=label,rows=sum(r['bucket']==k for r in rows),value=sum(r['balance_cents'] or 0 for r in rows if r['bucket']==k)) for k,label in BUCKETS.items() if k not in ['review','future','settled']],
            'customers':customers,'by_kind':[dict(kind=k,label=label,**summary([r for r in rows if r['kind']==k])) for k,label in KINDS.items()]}
