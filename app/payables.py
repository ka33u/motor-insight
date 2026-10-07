"""Imported supplier subledger, payment allocation and procurement reconciliation.

Amounts are integer CNY cents. Matching findings never erase a booked liability.
Payment plans are dated source records, not instructions to a bank.
"""
from collections import defaultdict
from datetime import date
from decimal import Decimal,InvalidOperation,ROUND_HALF_UP
from . import analytics
from .receivables import day,integer,aging,BUCKETS
BUCKETS={**BUCKETS,'future':'未计入应付'}

DATASETS=['purchase_terms','ap_invoices','ap_invoice_lines','ap_payments','ap_payment_plans','ap_allocations','ap_adjustments']
NOTE='合成Excel演练，截止业务日2026-10-01。应付余额＝已确认发票含税额－净付款核销－贷项冲减；付款登记与未核销金额单独列示，付款安排不抵减应付。只核对CNY，无期初应付、银行余额或汇率折算。到货对账差异保留已确认应付，不自动判定拒付。'
STAGES={'all':'全部','overdue':'逾期未结','due_today':'今日到期','not_due':'尚未到期','settled':'已结清','review':'余额待核对','excluded':'未计入应付'}
TABS={'invoices':'应付发票','payments':'付款与核销','plans':'付款安排','receipts':'到货对账'}

def number(v):
    if isinstance(v,bool) or v is None:return None
    try:
        x=Decimal(str(v));return x if x.is_finite() else None
    except (InvalidOperation,ValueError):return None

def rounded(v):return int(v.quantize(Decimal('1'),rounding=ROUND_HALF_UP))
def source(ds,key):return {'dataset':ds,'key':key}
def unique(items):return list(dict.fromkeys(items))
def params(p):
    f={k:str(p.get(k,'') or '').strip() for k in ['supplier_id','q','bucket','match']}
    f.update(tab=str(p.get('tab','invoices') or 'invoices'),stage=str(p.get('stage','all') or 'all'))
    if f['tab'] not in TABS or f['stage'] not in STAGES:raise ValueError('应付页面或状态不可用')
    if f['bucket'] and f['bucket'] not in BUCKETS:raise ValueError('账龄区间不可用')
    if f['match'] not in ['', 'issues','clear']:raise ValueError('对账条件不可用')
    if len(f['q'])>200:raise ValueError('查询条件过长')
    return f

class PayableData:
    def __init__(self,tables,cutoff=analytics.DAY):
        if not day(cutoff):raise ValueError('应付截止日无效')
        self.cutoff=cutoff;self.date=day(cutoff);self.tables=tables;self.global_issues=[]
        self.maps={ds:{r['id']:r for r in tables.get(ds,[])} for ds in ['suppliers','materials','purchase_lines','receipts',*DATASETS]}
        self.invoices={k:self.invoice(v) for k,v in self.maps['ap_invoices'].items()}
        self.payments={k:self.payment(v) for k,v in self.maps['ap_payments'].items()}
        self.allocations={};self.adjustments={};self.plans={};self.receipts={}
        docs=defaultdict(list)
        for r in self.invoices.values():
            if r['eligible']:docs[(r['supplier_id'],r['invoice_no'])].append(r)
        for group in docs.values():
            if len(group)>1:
                for r in group:r['issues'].append('同一供应商发票号重复确认，余额待核对')
        payment_docs=defaultdict(list)
        for r in self.payments.values():
            if r['eligible']:payment_docs[(r['supplier_id'],r.get('document_no'))].append(r)
        for group in payment_docs.values():
            if len(group)>1:
                for r in group:r['issues'].append('同一供应商付款凭据号重复，付款金额待核对')
        self.invoice_headers={k:bool(r['issues']) for k,r in self.invoices.items()}
        self.payment_headers={k:bool(r['issues']) for k,r in self.payments.items()}
        self.build_allocations();self.build_adjustments();self.finish_ledgers();self.match_receipts();self.build_plans()
        for r in self.invoices.values():
            r['issues']=unique(r['issues']);r['match_issues']=unique(r['match_issues'])
            r['stage']='excluded' if not r['eligible'] and not r['issues'] else 'review' if r['issues'] else 'settled' if r['balance_cents']==0 else 'overdue' if r['due']<cutoff else 'due_today' if r['due']==cutoff else 'not_due'
            r['bucket']='review' if r['issues'] else 'future' if not r['eligible'] else 'settled' if not r['balance_cents'] else aging((self.date-day(r['due'])).days)
            r['stage_label']=STAGES[r['stage']];r['bucket_label']=BUCKETS[r['bucket']]
            r['overdue_days']=max((self.date-day(r['due'])).days,0) if r['balance_cents'] else 0 if r['balance_cents']==0 else None
        for rows in [self.payments,self.plans,self.receipts]:
            for r in rows.values():r['issues']=unique(r['issues'])

    def base(self,ds,obj,supplier=None):
        sid=obj.get('supplier_id',supplier);supp=self.maps['suppliers'].get(sid,{})
        return {**obj,'supplier_id':sid,'supplier_name':supp.get('name','供应商缺失'),'issues':[],
                'sources':[source(ds,obj['id']),source('suppliers',sid)],'eligible':False,'exclusion':''}

    def gate(self,r,date_field,active,inactive):
        status=r.get('status');dt=day(r.get(date_field))
        if status in inactive:r['exclusion']=status;return
        if status!=active:r['issues'].append('登记状态未纳入核对规则');return
        if not dt:r['issues'].append(date_field+'日期无效');return
        if dt>self.date:r['exclusion']='截止日后生效';return
        r['eligible']=True

    def invoice(self,obj):
        r=self.base('ap_invoices',obj);r.update(gross_cents=None,balance_cents=None,allocated_cents=0,reversal_cents=0,credit_cents=0,net_allocation_cents=None,ledger=[],daily=[],lines=[],plans=[],match_issues=[])
        self.gate(r,'posted','已确认',['草稿','已作废'])
        if not r['eligible']:return r
        if r['supplier_id'] not in self.maps['suppliers']:r['issues'].append('供应商档案缺失')
        if r.get('currency')!='CNY':r['issues'].append('当前仅支持CNY，其他币种不并入汇总')
        if not r.get('invoice_no'):r['issues'].append('供应商发票号缺失')
        issued=day(r.get('issued'));due=day(r.get('due'))
        if not issued or not due or issued>day(r['posted']) or due<issued:r['issues'].append('开票、确认与到期日期关系无效')
        if not integer(r.get('net_cents'),0) or not integer(r.get('tax_cents'),0):r['issues'].append('发票金额必须为非负整数分')
        else:r['gross_cents']=r['net_cents']+r['tax_cents']
        return r

    def payment(self,obj):
        r=self.base('ap_payments',obj);r.update(allocated_cents=0,reversal_cents=0,net_allocation_cents=None,unallocated_cents=None,allocations=[],adjustments=[],daily=[])
        self.gate(r,'paid','已付款',['草稿','已撤销'])
        if r['eligible']:
            if r['supplier_id'] not in self.maps['suppliers']:r['issues'].append('供应商档案缺失')
            if r.get('currency')!='CNY':r['issues'].append('当前仅支持CNY')
            if not integer(r.get('amount_cents'),1):r['issues'].append('付款金额必须为正整数分')
            if not r.get('document_no'):r['issues'].append('付款凭据号缺失')
        return r

    def orphan(self,ds,r,field):self.global_issues.append({'dataset':ds,'id':r['id'],'message':field+'关联对象缺失'})
    def build_allocations(self):
        for a in self.maps['ap_allocations'].values():
            inv=self.invoices.get(a.get('invoice_id'));pay=self.payments.get(a.get('payment_id'))
            r={**a,'issues':[],'eligible':False,'exclusion':'','reversed_cents':0,'net_cents':None};self.allocations[a['id']]=r
            self.gate(r,'occurred','已核销',['草稿','已撤销'])
            for obj in [inv,pay]:
                if obj:obj['sources'].append(source('ap_allocations',a['id']))
            if inv:
                inv['ledger'].append({'dataset':'ap_allocations',**r,'kind':'付款核销','delta_cents':-a['amount_cents'] if integer(a.get('amount_cents')) else None});inv['sources'].append(source('ap_payments',a.get('payment_id')))
            if pay:pay['allocations'].append(r);pay['sources'].append(source('ap_invoices',a.get('invoice_id')))
            if not inv:self.orphan('ap_allocations',r,'应付发票')
            if not pay:self.orphan('ap_allocations',r,'付款')
            if not r['eligible'] and not r['issues']:continue
            if not inv or not pay:r['issues'].append('核销的发票或付款不存在')
            else:
                if not inv['eligible'] or not pay['eligible'] or self.invoice_headers[inv['id']] or self.payment_headers[pay['id']]:r['issues'].append('核销依赖的发票或付款未生效或待核对')
                if inv['supplier_id']!=pay['supplier_id'] or inv.get('currency')!=pay.get('currency'):r['issues'].append('付款与发票供应商或币种不一致')
                if day(r.get('occurred')) and (r['occurred']<str(inv.get('posted','')) or r['occurred']<str(pay.get('paid',''))):r['issues'].append('核销日期早于发票确认或付款')
            if not integer(a.get('amount_cents'),1):r['issues'].append('核销金额必须为正整数分')
            if r['issues']:
                for obj in [inv,pay]:
                    if obj:obj['issues'].append(a['id']+'：'+'；'.join(r['issues']))

    def build_adjustments(self):
        reverse_groups=defaultdict(list)
        for obj in self.maps['ap_adjustments'].values():
            inv=self.invoices.get(obj.get('invoice_id'));r={**obj,'eligible':False,'exclusion':'','issues':[]};self.adjustments[obj['id']]=r
            self.gate(r,'occurred','已过账',['草稿','已撤销'])
            if not inv:self.orphan('ap_adjustments',r,'应付发票')
            else:inv['sources'].append(source('ap_adjustments',r['id']))
            if not r['eligible'] and not r['issues']:
                if inv:inv['ledger'].append({'dataset':'ap_adjustments',**r})
                continue
            if not inv or not inv['eligible']:r['issues'].append('调整的应付发票未生效或不存在')
            elif day(r.get('occurred')) and r['occurred']<str(inv.get('posted','')):r['issues'].append('调整早于发票确认')
            amount=r.get('delta_cents');kind=r.get('kind');a=self.allocations.get(r.get('allocation_id'))
            if not integer(amount) or amount==0:r['issues'].append('调整金额必须为非零整数分')
            elif kind=='贷项冲减':
                if amount>=0 or r.get('allocation_id'):r['issues'].append('贷项应减少应付且不能引用付款核销')
            elif kind=='核销冲回':
                if amount<=0:r['issues'].append('核销冲回应增加应付')
                if not a or not a['eligible'] or a['issues'] or a.get('invoice_id')!=r.get('invoice_id'):r['issues'].append('冲回未关联同票有效付款核销')
                elif not day(r.get('occurred')) or r['occurred']<a['occurred']:r['issues'].append('冲回早于原核销')
                else:reverse_groups[a['id']].append(r)
            else:r['issues'].append('调整类型未支持')
            if kind=='核销冲回' and a and a.get('payment_id') in self.payments:
                p=self.payments[a['payment_id']];p['adjustments'].append(r);p['sources'].append(source('ap_adjustments',r['id']))
            if inv:inv['ledger'].append({'dataset':'ap_adjustments',**r})
        for key,items in reverse_groups.items():
            a=self.allocations[key];valid=[r for r in items if not r['issues']]
            if sum(r['delta_cents'] for r in valid)>a['amount_cents']:
                for r in valid:r['issues'].append('累计冲回超过原付款核销额')
            else:a['reversed_cents']=sum(r['delta_cents'] for r in valid)
        for r in self.adjustments.values():
            if r['issues'] and r.get('invoice_id') in self.invoices:self.invoices[r['invoice_id']]['issues'].append(r['id']+'：'+'；'.join(r['issues']))
            a=self.allocations.get(r.get('allocation_id'))
            if r['issues'] and a and a.get('payment_id') in self.payments:self.payments[a['payment_id']]['issues'].append(r['id']+'：冲回依据待核对')

    def finish_ledgers(self):
        for p in self.payments.values():
            daily=defaultdict(int)
            for a in p['allocations']:
                if a['eligible'] and not a['issues']:p['allocated_cents']+=a['amount_cents'];daily[a['occurred']]+=a['amount_cents'];a['net_cents']=a['amount_cents']-a['reversed_cents']
            for r in p['adjustments']:
                if r['eligible'] and not r['issues']:p['reversal_cents']+=r['delta_cents'];daily[r['occurred']]-=r['delta_cents']
            total=0
            for dt,change in sorted(daily.items()):
                total+=change;p['daily'].append({'date':dt,'net_allocated_cents':total})
                if integer(p.get('amount_cents'),1) and (total<0 or total>p['amount_cents']):p['issues'].append(dt+'：累计净核销超出付款金额')
            if p['eligible'] and not p['issues']:p.update(net_allocation_cents=total,unallocated_cents=p['amount_cents']-total)
            if p['issues']:
                for a in p['allocations']:
                    if a['eligible'] and a.get('invoice_id') in self.invoices:self.invoices[a['invoice_id']]['issues'].append(p['id']+'：关联付款核对未通过')
        for inv in self.invoices.values():
            daily=defaultdict(int)
            for entry in inv['ledger']:
                r=(self.allocations if entry['dataset']=='ap_allocations' else self.adjustments)[entry['id']]
                entry.update(eligible=r['eligible'],issues=r['issues'],exclusion=r['exclusion'],included=r['eligible'] and not r['issues'])
                if not entry['included']:continue
                if entry['dataset']=='ap_allocations':inv['allocated_cents']+=r['amount_cents']
                elif r['kind']=='核销冲回':inv['reversal_cents']+=r['delta_cents']
                else:inv['credit_cents']-=r['delta_cents']
                daily[r['occurred']]+=entry['delta_cents']
            if inv['gross_cents'] is not None:
                balance=inv['gross_cents']
                for dt,delta in sorted(daily.items()):
                    before=balance;balance+=delta;inv['daily'].append({'date':dt,'before_cents':before,'delta_cents':delta,'balance_cents':balance})
                    if balance<0:inv['issues'].append(dt+'：日末应付为负，需核对超额核销或贷项')
                if inv['eligible'] and not inv['issues']:inv['balance_cents']=balance
            inv['net_allocation_cents']=inv['allocated_cents']-inv['reversal_cents']
            inv['ledger'].sort(key=lambda e:(str(e.get('occurred','')),e['id']))

    def match_receipts(self):
        terms=defaultdict(list);billed=defaultdict(list)
        for t in self.maps['purchase_terms'].values():terms[t.get('purchase_line_id')].append(t)
        for obj in self.maps['ap_invoice_lines'].values():
            inv=self.invoices.get(obj.get('invoice_id'));receipt=self.maps['receipts'].get(obj.get('receipt_id'));po=self.maps['purchase_lines'].get(receipt.get('purchase_line_id')) if receipt else None
            line={**obj,'issues':[],'expected_net_cents':None,'expected_tax_cents':None}
            if not inv:self.orphan('ap_invoice_lines',obj,'应付发票');continue
            inv['lines'].append(line);inv['sources'].append(source('ap_invoice_lines',obj['id']))
            if receipt:inv['sources'].append(source('receipts',receipt['id']))
            if po:inv['sources'].append(source('purchase_lines',po['id']))
            qty=number(obj.get('qty'));price=obj.get('unit_price_cents');tax=obj.get('tax_bps')
            if qty is None or qty<=0 or not integer(price,0) or not integer(tax,0) or tax>10000:line['issues'].append('发票行数量、单价或税率无效')
            else:
                net=rounded(qty*price);line.update(expected_net_cents=net,expected_tax_cents=rounded(Decimal(net)*tax/10000))
                if obj.get('net_cents')!=line['expected_net_cents'] or obj.get('tax_cents')!=line['expected_tax_cents']:line['issues'].append('发票行金额与数量、未税单价、税率不符')
            if not receipt or not po:line['issues'].append('发票行到货或采购关系缺失')
            else:
                if po.get('supplier_id')!=inv['supplier_id']:line['issues'].append('发票与采购供应商不一致')
                if receipt.get('material_id')!=po.get('material_id'):line['issues'].append('到货与采购物料不一致')
                rd=day(str(receipt.get('received',''))[:10]);issued=day(inv.get('issued'))
                if not rd or not issued or rd>issued:line['issues'].append('到货晚于开票或日期无效')
                if receipt.get('status')!='检验合格':line['issues'].append('到货尚未检验合格，需业务核对')
                ts=terms[po['id']]
                inv['sources'].extend(source('purchase_terms',t['id']) for t in ts)
                if len(ts)!=1:line['issues'].append('采购价税约定缺失或重复')
                else:
                    t=ts[0]
                    if t.get('currency')!=inv.get('currency') or t.get('price_basis')!='未税' or not day(t.get('confirmed')) or t['confirmed']>str(inv.get('issued','')):line['issues'].append('采购价税约定与发票不适配')
                    if t.get('tax_bps')!=tax or po.get('unit_price_cents')!=price:line['issues'].append('发票与采购约定单价或税率不同')
            if inv['eligible']:
                billed[obj.get('receipt_id')].append((inv,line))
                inv['match_issues'].extend(obj['id']+'：'+x for x in line['issues'])
        for inv in self.invoices.values():
            if not inv['eligible']:continue
            if not inv['lines']:inv['match_issues'].append('缺少发票明细与到货关联')
            elif any(not integer(l.get('net_cents'),0) or not integer(l.get('tax_cents'),0) for l in inv['lines']):inv['match_issues'].append('发票明细金额无效')
            elif sum(l['net_cents'] for l in inv['lines'])!=inv.get('net_cents') or sum(l['tax_cents'] for l in inv['lines'])!=inv.get('tax_cents'):inv['match_issues'].append('发票头与明细金额不一致')
        for obj in self.maps['receipts'].values():
            received_day=day(str(obj.get('received',''))[:10])
            if received_day and received_day>self.date:continue
            po=self.maps['purchase_lines'].get(obj.get('purchase_line_id'),{});mat=self.maps['materials'].get(obj.get('material_id'),{})
            r=self.base('receipts',obj,po.get('supplier_id'));r.update(material_name=mat.get('name','物料缺失'),unit=mat.get('unit'),billed_qty=None,unbilled_qty=None,reference_net_cents=None,invoices=[],match_issues=[])
            if not received_day:r['issues'].append('到货业务日期无效，无法确认截止范围')
            if po.get('supplier_id') not in self.maps['suppliers']:r['issues'].append('采购供应商档案缺失')
            if po and obj.get('material_id')!=po.get('material_id'):r['issues'].append('到货物料与采购行不一致')
            if not mat.get('unit'):r['issues'].append('到货物料单位缺失')
            if obj.get('status')!='检验合格':r['match_issues'].append('到货尚未检验合格')
            r['sources'] += [source('purchase_lines',po.get('id')),source('materials',obj.get('material_id'))]
            qty=number(obj.get('qty'));lines=billed[obj['id']];values=[number(l.get('qty')) for _,l in lines]
            if not po or not mat or qty is None or qty<0 or any(v is None or v<=0 for v in values):r['issues'].append('到货或开票数量/关系不完整')
            else:
                total=sum(values,Decimal(0));r.update(billed_qty=float(total),unbilled_qty=float(qty-total))
                if total>qty:
                    r['issues'].append('累计已确认开票数量超过到货数量')
                    for inv,line in lines:inv['match_issues'].append(obj['id']+'：累计开票超过到货');line['issues'].append('累计开票超过到货')
                ts=terms.get(po.get('id'),[])
                if len(ts)==1 and ts[0].get('currency')=='CNY' and ts[0].get('price_basis')=='未税' and day(ts[0].get('confirmed')) and ts[0]['confirmed']<=self.cutoff and integer(po.get('unit_price_cents'),0) and total<=qty:r['reference_net_cents']=rounded((qty-total)*po['unit_price_cents'])
                else:r['issues'].append('未开票数量的价税约定未核对')
                r['sources'].extend(source('purchase_terms',t['id']) for t in ts)
            for inv,line in lines:
                r['invoices'].append({'id':inv['id'],'line_id':line['id'],'qty':line['qty'],'issues':line['issues']});r['sources'] += [source('ap_invoices',inv['id']),source('ap_invoice_lines',line['id'])]
                r['match_issues'].extend(line['id']+'：'+x for x in line['issues'])
            if r['issues']:r['reference_net_cents']=None
            self.receipts[r['id']]=r

    def build_plans(self):
        groups=defaultdict(list)
        for obj in self.maps['ap_payment_plans'].values():
            inv=self.invoices.get(obj.get('invoice_id'));r=self.base('ap_payment_plans',obj,inv.get('supplier_id') if inv else None)
            r.update(executed_cents=None,remaining_cents=None,unresolved_cents=None,late=False,allocations=[])
            self.plans[r['id']]=r
            if inv:inv['plans'].append(r['id']);r['sources'].append(source('ap_invoices',inv['id']))
            else:self.orphan('ap_payment_plans',r,'应付发票')
            self.gate(r,'approved','已批准',['草稿','待审批','已撤销'])
            linked=[a for a in self.allocations.values() if a.get('plan_id')==r['id']]
            for a in linked:
                r['sources'].append(source('ap_allocations',a['id']));r['allocations'].append(a)
            if not r['eligible'] and not r['issues']:
                if any(a['eligible'] and not a['issues'] for a in linked):r['issues'].append('未生效安排已有核销执行关联')
                continue
            created=day(r.get('created'));approved=day(r.get('approved'));planned=day(r.get('planned'))
            if not created or not approved or not planned or created>approved or approved>planned:r['issues'].append('安排登记、批准、计划日期无效')
            if not integer(r.get('amount_cents'),1):r['issues'].append('安排金额必须为正整数分')
            if not inv or inv['balance_cents'] is None:r['issues'].append('关联应付余额不可核对')
            elif approved and approved<day(inv['posted']):r['issues'].append('安排批准早于应付确认')
            for a in linked:
                if not a['eligible']:continue
                if a['issues'] or a.get('invoice_id')!=r.get('invoice_id') or a['net_cents'] is None or approved and a['occurred']<r['approved']:r['issues'].append(a['id']+'：执行核销与安排关系无效')
                p=self.payments.get(a.get('payment_id'))
                if not p or p['issues']:r['issues'].append(a['id']+'：执行付款待核对')
                if p:r['sources'].append(source('ap_payments',p['id']))
                r['sources'].extend(source('ap_adjustments',x['id']) for x in self.adjustments.values() if x.get('allocation_id')==a['id'])
            if not r['issues']:
                executed=sum(a['net_cents'] for a in linked if a['eligible']);r['executed_cents']=executed
                if executed>r['amount_cents']:r['issues'].append('关联执行超过安排金额')
                else:r['unresolved_cents']=r['amount_cents']-executed;groups[r['invoice_id']].append(r)
        for key,rows in groups.items():
            if sum(r['unresolved_cents'] for r in rows)>self.invoices[key]['balance_cents']:
                for r in rows:r['issues'].append('同票未执行安排合计超过当前应付余额')
            else:
                for r in rows:r['remaining_cents']=r['unresolved_cents'];r['late']=r['remaining_cents']>0 and r['planned']<self.cutoff
        for a in self.allocations.values():
            if a.get('plan_id') and a['plan_id'] not in self.plans:self.orphan('ap_allocations',a,'付款安排')

    def selected(self,f,ignore_stage=False):
        rows=list({'invoices':self.invoices,'payments':self.payments,'plans':self.plans,'receipts':self.receipts}[f['tab']].values())
        if f['supplier_id']:rows=[r for r in rows if r['supplier_id']==f['supplier_id']]
        if f['q']:rows=[r for r in rows if f['q'].lower() in ' '.join(str(r.get(k,'')) for k in ['id','supplier_name','supplier_id','invoice_no','document_no','invoice_id','material_name','lot']).lower()]
        if f['match']:rows=[r for r in rows if bool(r.get('match_issues') or r['issues'])==(f['match']=='issues')]
        if f['tab']=='invoices':
            if not ignore_stage and f['stage']!='all':rows=[r for r in rows if r['stage']==f['stage']]
            if f['bucket']:rows=[r for r in rows if r['bucket']==f['bucket']]
        return sorted(rows,key=lambda r:(str(r.get('due',r.get('planned',r.get('paid',r.get('received',''))))),r['id']))

    def detail(self,kind,key):
        index={'invoices':self.invoices,'payments':self.payments,'plans':self.plans,'receipts':self.receipts}.get(kind)
        if index is None or key not in index:raise ValueError('应付对象不存在')
        return index[key]

def safe(r):return {k:v for k,v in r.items() if k not in ['sources','ledger','daily','lines','allocations','adjustments','invoices','plans']}
def current():return PayableData(analytics.tables())
def summary(rows,tab):
    result={'rows':len(rows),'review_rows':sum(bool(r['issues']) for r in rows),'complete':all(not r['issues'] for r in rows)}
    if tab=='invoices':
        known=[r for r in rows if r['balance_cents'] is not None]
        result.update(valid_rows=len(known),excluded_rows=sum(not r['eligible'] for r in rows),match_issue_rows=sum(bool(r['match_issues']) for r in rows))
        for k in ['gross_cents','allocated_cents','reversal_cents','credit_cents','balance_cents']:result[k]=sum(r[k] for r in known) if known else None
        result['overdue_cents']=sum(r['balance_cents'] for r in known if r['stage']=='overdue') if known else None
    elif tab=='payments':
        known=[r for r in rows if r['unallocated_cents'] is not None];result['valid_rows']=len(known)
        for k in ['amount_cents','net_allocation_cents','unallocated_cents']:result[k]=sum(r[k] for r in known) if known else None
    elif tab=='plans':
        known=[r for r in rows if r['remaining_cents'] is not None];result['valid_rows']=len(known)
        for k in ['amount_cents','executed_cents','remaining_cents']:result[k]=sum(r[k] for r in known) if known else None
        result['late_cents']=sum(r['remaining_cents'] for r in known if r['late']) if known else None
    else:
        known=[r for r in rows if r['reference_net_cents'] is not None and not r['issues']];result['valid_rows']=len(known);result['reference_net_cents']=sum(r['reference_net_cents'] for r in known) if known else None
        result['units']=[{'unit':u,'received_qty':float(sum(number(r['qty']) for r in rows if r['unit']==u and r['billed_qty'] is not None)) if u!='未登记' else None,'unbilled_qty':float(sum(number(r['unbilled_qty']) for r in rows if r['unit']==u and r['unbilled_qty'] is not None)) if u!='未登记' else None} for u in sorted({r['unit'] or '未登记' for r in rows})]
    return result
