"""Material/lot ledger and purchasing evidence over the imported fixed snapshot."""
from collections import defaultdict,Counter
from decimal import Decimal,InvalidOperation
from functools import lru_cache
import hashlib,json
from . import analytics
from .models import Record

NOTE='库存按物料×批次×库位核算，期初＋流入－流出；到货、检验批准、入库分别计数。可用状态余额未扣预留，不等于可承诺量或订单齐套。仅覆盖已导入模拟数据，截至固定快照，不重放历史。'
STOCK_STAGES={'all':'全部物料','low':'低于安全库存','blocked':'有受限库存','attention':'账据待核对'}
PO_STAGES={'all':'全部采购行','overdue':'逾期未到','quality':'来料待处置','putaway':'批准未入库','attention':'账据待核对'}
STATES={'可用','冻结','待检','隔离','待退货'}
def ix(rows):return {r['id']:r for r in rows}
def group(rows,key):
    out=defaultdict(list)
    for r in rows:out[r[key]].append(r)
    return out
def dec(v):
    try:x=Decimal(str(v))
    except InvalidOperation:raise ValueError('库存/采购数量不是有效数字')
    if not x.is_finite():raise ValueError('存在非有限库存/采购数量，请先核对来源')
    return x
def total(rows,key):return sum((dec(r[key]) for r in rows),Decimal(0))
def clean(r):return {k:v for k,v in r.items() if not k.startswith('_')}
def refs(ds,rows):return [{'dataset':ds,'key':r['id']} for r in rows]
def unique_refs(rows):return list({(r['dataset'],r['key']):r for r in rows}.values())
def without_money(r):return {k:v for k,v in r.items() if 'cents' not in k}
def lot_key(r):return (r['material_id'],r['lot'],r['location'])
def lot_id(key):return hashlib.sha256(json.dumps(key,ensure_ascii=False).encode()).hexdigest()[:24]

class SupplyData:
    def __init__(self,d,cutoff=analytics.AS_OF):
        self.d=d;self.cutoff=cutoff;day=cutoff[:10];self.materials=ix(d['materials']);self.suppliers=ix(d['suppliers']);employees=ix(d['employees'])
        self.purchase=ix([p for p in d['purchase_lines'] if p['ordered']<=day]);self.raw_receipts=ix([r for r in d['receipts'] if r['received']<=cutoff]);work_orders=ix(d['work_orders'])
        inspections=group([q for q in d['incoming_inspections'] if q['inspected']<=cutoff],'receipt_id')
        moves=[m for m in d['inventory_movements'] if m['occurred']<=cutoff];move_refs=group(moves,'reference');self.receipts={}
        for rid,r in self.raw_receipts.items():
            issues=[];p=self.purchase.get(r['purchase_line_id']);qs=sorted(inspections[rid],key=lambda q:(q['inspected'],q['id']));q=qs[-1] if qs else None
            if not p or r['material_id']!=p['material_id']:issues.append('到货与采购物料/下单时间不匹配')
            if p and r['received'][:10]<p['ordered']:issues.append('到货早于采购日期')
            if dec(r['qty'])<=0:issues.append('到货数量须为正')
            for inspection in qs:
                if inspection['inspected']<r['received']:issues.append('检验早于到货')
                if not 0<=inspection['defect_count']<=inspection['sample_size'] or inspection['sample_size']<=0:issues.append('抽样数量或不良样本数无效')
            approved=bool(q and q['result']=='合格' and q['disposition']=='批准入库' and r['status']=='检验合格' and not issues)
            if q and ((r['status']=='检验合格')!=(q['result']=='合格' and q['disposition']=='批准入库')):issues.append('到货状态与最新检验处置不一致')
            linked=move_refs[rid];matching=[]
            for m in linked:
                if m['movement']!='采购入库' or m['material_id']!=r['material_id'] or m['lot']!=r['lot'] or dec(m['qty_signed'])<=0:issues.append('入库流水与到货物料/批次/业务类型不匹配');continue
                matching.append(m)
                at=[x for x in qs if x['inspected']<=m['occurred']];prior=at[-1] if at else None
                if m['occurred']<r['received'] or not prior or prior['result']!='合格' or prior['disposition']!='批准入库':issues.append('入库时缺少合格及批准证据')
            put=total(matching,'qty_signed')
            if put>dec(r['qty']):issues.append('入库量超过到货量')
            if put>0 and not approved:issues.append('已有入库但当前检验批准待核对')
            self.receipts[rid]={**without_money(r),'latest_inspection':q,'inspection_count':len(qs),'approved':approved and not issues,'putaway_qty':float(put),'unposted_qty':float(max(Decimal(0),dec(r['qty'])-put)),'issues':list(dict.fromkeys(issues)),'_inspections':qs,'_moves':linked}
        by_po=group(self.receipts.values(),'purchase_line_id');self.po_rows=[]
        for p in self.purchase.values():
            rr=by_po[p['id']];m=self.materials.get(p['material_id'],{});issues=[e for r in rr for e in r['issues']]
            if not m:issues.append('物料档案缺失')
            if p['supplier_id'] not in self.suppliers:issues.append('供应商档案缺失')
            if p['status'] not in ['已到货','未到货','部分到货','已取消']:issues.append('采购状态尚未映射')
            qty=dec(p['qty']);received=total(rr,'qty');cancelled=p['status']=='已取消'
            if qty<=0:issues.append('采购数量须为正')
            if p['due']<p['ordered']:issues.append('承诺到货早于采购日期')
            if received>qty:issues.append('累计到货超过采购数量')
            if cancelled and received>0:issues.append('已取消采购存在到货，需核对取消范围')
            remaining=max(Decimal(0),qty-received) if not cancelled else Decimal(0)
            overdue=p['due']<day and not cancelled;ontime=total([r for r in rr if r['received'][:10]<=p['due']],'qty')>=qty
            approved=total([r for r in rr if r['approved']],'qty');put=total(rr,'putaway_qty');pending=total([r for r in rr if r['approved']],'unposted_qty')
            flags=['all']+(['overdue'] if overdue and remaining>0 else [])+(['quality'] if any(not r['approved'] for r in rr) else [])+(['putaway'] if pending>0 else [])+(['attention'] if issues else [])
            self.po_rows.append({**without_money(p),'material':m.get('name','档案缺失'),'category':m.get('category','未知'),'unit':m.get('unit','未知'),'supplier':self.suppliers.get(p['supplier_id'],{}).get('name','档案缺失'),'received_qty':float(received),'approved_qty':float(approved),'putaway_qty':float(put),'approved_unposted_qty':float(pending),'remaining_qty':float(remaining),'receipt_count':len(rr),'quality_pending_receipts':sum(not r['approved'] for r in rr),'due_count':int(overdue),'ontime_count':int(overdue and ontime),'days_late':max(0,(date_day(day)-date_day(p['due'])).days) if remaining else 0,'flags':flags,'issues':list(dict.fromkeys(issues)),'_receipts':rr})
        self.po_index=ix(self.po_rows)
        stocks=defaultdict(lambda:{'opening':[],'moves':[],'events':[]})
        for ds,col,stamp in [('inventory_opening','opening','as_of'),('inventory_movements','moves','occurred'),('inventory_status_events','events','occurred')]:
            for r in d[ds]:
                if r[stamp]<=(day if stamp=='as_of' else cutoff):stocks[lot_key(r)][col].append(r)
        self.lots=[]
        for key,v in sorted(stocks.items()):
            mid,lot,loc=key;m=self.materials.get(mid,{});opens=v['opening'];mm=sorted(v['moves'],key=lambda x:(x['occurred'],x['id']));ev=sorted(v['events'],key=lambda x:(x['occurred'],x['id']));issues=[]
            if not m:issues.append('物料档案缺失')
            if len(opens)>1:issues.append('同批次库位有多个期初，期初基准不唯一')
            if any(o['status'] not in STATES for o in opens):issues.append('期初状态尚未映射')
            first_receipt=self.receipts.get(mm[0]['reference']) if mm else None
            base=dec(opens[0]['qty']) if len(opens)==1 else Decimal(0);baseline_known=len(opens)==1 or bool(mm and mm[0]['movement']=='采购入库' and dec(mm[0]['qty_signed'])>0 and first_receipt and first_receipt['material_id']==mid and first_receipt['lot']==lot)
            if not baseline_known:issues.append('缺少期初或可核对的首次入库')
            state=opens[0]['status'] if len(opens)==1 else '可用' if baseline_known and first_receipt and first_receipt['approved'] and first_receipt['material_id']==mid and first_receipt['lot']==lot else '未知'
            start=opens[0]['as_of']+'T00:00:00' if len(opens)==1 else None
            if start and any(r['occurred']<start for r in mm+ev):issues.append('存在早于期初基准的流水或状态变更')
            timeline=[];running=base;last_change=None
            for stamp,kind,row in sorted([(r['occurred'],0,r) for r in ev]+[(r['occurred'],1,r) for r in mm],key=lambda x:(x[0],x[1],x[2]['id'])):
                local=[]
                if kind==0:
                    if row['from_status']!=state:local.append('状态链前值不匹配')
                    if row['to_status'] not in STATES or row['approver_id'] not in employees:local.append('状态或批准人档案待核对')
                    state=row['to_status'];last_change=stamp;delta=Decimal(0);ds='inventory_status_events';label=row['from_status']+' → '+row['to_status']
                else:
                    delta=dec(row['qty_signed']);ds='inventory_movements';label=row['movement']
                    if m.get('unit')=='件' and delta!=delta.to_integral_value():local.append('件数必须为整数')
                    if row['movement']=='采购入库':
                        receipt=self.receipts.get(row['reference'])
                        if delta<=0 or not receipt or receipt['material_id']!=mid or receipt['lot']!=lot:local.append('采购入库引用或方向待核对')
                        elif receipt['issues'] or not receipt['approved']:local.append('入库关联检验/到货证据待核对')
                    elif row['movement']=='生产领料':
                        if delta>=0 or row.get('work_order_id') not in work_orders:local.append('领料方向或工单待核对')
                    else:local.append('流水类型尚未映射，需核对数量方向')
                    if delta<0 and state!='可用':local.append('非可用状态发生出库')
                    if delta<0 and stamp==last_change:local.append('出库与状态变更同刻，先后待核对')
                    running+=delta
                    if running<0:local.append('运行余额为负')
                issues.extend(local);timeline.append({'id':row['id'],'dataset':ds,'occurred':stamp,'kind':label,'qty_signed':float(delta),'running_qty':float(running) if baseline_known and len(opens)<=1 else None,'state':state,'reference':row.get('reference'),'work_order_id':row.get('work_order_id'),'issues':local})
            if base<0:issues.append('期初余额为负')
            if m.get('unit')=='件' and base!=base.to_integral_value():issues.append('期初件数必须为整数')
            issues=list(dict.fromkeys(issues));qty=base+total(mm,'qty_signed');balance=float(qty) if baseline_known and len(opens)<=1 and not (start and any(r['occurred']<start for r in mm)) else None
            self.lots.append({'id':lot_id(key),'material_id':mid,'lot':lot,'location':loc,'unit':m.get('unit','未知'),'state':state,'opening_qty':float(base) if len(opens)<=1 else None,'inbound_qty':float(total([r for r in mm if dec(r['qty_signed'])>0],'qty_signed')),'outbound_qty':float(-total([r for r in mm if dec(r['qty_signed'])<0],'qty_signed')),'balance_qty':balance,'usable_state_qty':balance if state=='可用' and not issues else 0 if not issues else None,'last_movement':mm[-1]['occurred'] if mm else None,'issues':issues,'_opening':opens,'_moves':mm,'_events':ev,'_timeline':timeline})
        self.lot_index=ix(self.lots);by_material=group(self.lots,'material_id');po_material=group(self.po_rows,'material_id');self.stock_rows=[]
        for mid,m in sorted(self.materials.items()):
            ll=by_material[mid];pp=po_material[mid];issues=list(dict.fromkeys(x for l in ll for x in l['issues']));covered=bool(ll)
            if not covered:issues.append('尚无期初或库存流水，不能将缺少记录当作零库存')
            balance=float(total(ll,'balance_qty')) if covered and all(l['balance_qty'] is not None for l in ll) else None
            usable=float(total(ll,'usable_state_qty')) if covered and not issues else None
            safety=float(dec(m['safety_qty']));gap=max(0,safety-usable) if usable is not None else None
            flags=['all']+(['low'] if gap is not None and gap>0 else [])+(['blocked'] if any(l['state']!='可用' and (l['balance_qty'] or 0)>0 for l in ll) else [])+(['attention'] if issues else [])
            self.stock_rows.append({'id':mid,'material_id':mid,'material':m['name'],'spec':m['spec'],'category':m['category'],'unit':m['unit'],'safety_qty':safety,'balance_qty':balance,'usable_state_qty':usable,'safety_gap':gap,'lot_count':len(ll),'open_purchase_qty':float(total(pp,'remaining_qty')),'overdue_purchase_qty':float(total([p for p in pp if 'overdue' in p['flags']],'remaining_qty')),'flags':flags,'issues':issues,'_lots':ll,'_purchase':pp})
        self.stock_index=ix(self.stock_rows)
        self.global_issues=[{'dataset':'receipts','id':r['id'],'message':'截止快照内到货缺少对应采购行，未归入采购统计'} for r in self.receipts.values() if r['purchase_line_id'] not in self.purchase]
        self.global_issues += [{'dataset':'inventory_movements','id':r['id'],'message':'库存流水物料档案缺失，未归入物料汇总'} for r in moves if r['material_id'] not in self.materials]

    def detail(self,kind,key):
        if kind=='material':
            row=self.stock_index.get(key)
            if not row:raise Record.DoesNotExist()
            sources=refs('materials',[self.materials[key]]);lots=[]
            for l in row['_lots']:
                sources+=refs('inventory_opening',l['_opening'])+refs('inventory_movements',l['_moves'])+refs('inventory_status_events',l['_events'])
                lots.append(clean(l))
            for p in row['_purchase']:sources+=self.po_sources(p)
            return {'row':clean(row),'lots':lots,'purchases':[clean(p) for p in row['_purchase']],'sources':unique_refs(sources)}
        if kind=='purchase':
            row=self.po_index.get(key)
            if not row:raise Record.DoesNotExist()
            return {'row':clean(row),'receipts':[{**clean(r),'inspections':r['_inspections'],'movements':[without_money(m) for m in r['_moves']]} for r in row['_receipts']],'sources':unique_refs(self.po_sources(row))}
        raise ValueError('不支持的供应对象类型')

    def po_sources(self,row):
        sources=[{'dataset':'purchase_lines','key':row['id']},{'dataset':'materials','key':row['material_id']},{'dataset':'suppliers','key':row['supplier_id']}]
        for r in row['_receipts']:sources+=refs('receipts',[r])+refs('incoming_inspections',r['_inspections'])+refs('inventory_movements',r['_moves'])
        return sources

def date_day(value):
    from datetime import date
    return date.fromisoformat(value)
def filters(query):
    if set(query)-{'tab','category','material_id','supplier_id','q','stage','page'}:raise ValueError('不支持的供应筛选字段')
    f={k:str(query.get(k,'')).strip() for k in ['category','material_id','supplier_id','q']};f['tab']=query.get('tab','stock');f['stage']=query.get('stage','all')
    if f['tab'] not in ['stock','purchase']:raise ValueError('工作页不可用')
    if f['tab']=='stock' and f['supplier_id']:raise ValueError('供应商筛选只适用于采购行，不能据此裁剪库存')
    if f['stage'] not in (STOCK_STAGES if f['tab']=='stock' else PO_STAGES):raise ValueError('清单状态不可用')
    if any(len(v)>150 for v in f.values()):raise ValueError('筛选内容过长')
    return f
def cohort(data,f):
    rows=data.stock_rows if f['tab']=='stock' else data.po_rows
    return [r for r in rows if (not f['category'] or r['category']==f['category']) and (not f['material_id'] or r['material_id']==f['material_id']) and (not f['supplier_id'] or r.get('supplier_id')==f['supplier_id']) and (not f['q'] or f['q'].lower() in ' '.join(str(r.get(k,'')) for k in ['id','material','material_id','supplier','spec']).lower())]
def summary(rows,tab):
    result={'objects':len(rows),'attention':sum(bool(r['issues']) for r in rows)}
    if tab=='stock':result.update(low=sum('low' in r['flags'] for r in rows),blocked=sum('blocked' in r['flags'] for r in rows),lots=sum(r['lot_count'] for r in rows))
    else:
        due=sum(r['due_count'] for r in rows);ontime=sum(r['ontime_count'] for r in rows)
        result.update(overdue=sum('overdue' in r['flags'] for r in rows),quality=sum('quality' in r['flags'] for r in rows),putaway=sum('putaway' in r['flags'] for r in rows),receipts=sum(r['receipt_count'] for r in rows),due=due,ontime=ontime,ontime_rate=None if result['attention'] else analytics.percent(ontime,due))
    return result
@lru_cache(maxsize=1)
def cached(revision):return SupplyData(analytics._tables(revision))
def current():return cached(analytics.revision())
