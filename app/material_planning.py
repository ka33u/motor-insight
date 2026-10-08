"""Read-only BOM net demand and whole-order allocation rehearsal over imported facts."""
from collections import defaultdict,Counter
from datetime import date,datetime
from decimal import Decimal,InvalidOperation,ROUND_CEILING
from pathlib import Path
import hashlib,json
from . import analytics,supply,material_impact,material_lot_allocation,material_returns
from .models import Record

NOTE='合成数据备料推演：按工单指定BOM版本及计划开工日核对用量，需求＝计划台数×单位用量×(1＋损耗定额)，相同物料跨分支合并；件按工单物料向上取整。扣除截止前可核对的净领料（累计领料减已关联退料）后，按所选顺序整单试配。净领料不是在制实存或实际消耗；退料仅按仓储流水入池一次，可用性另核库位状态。只有全部物料可覆盖的工单才消耗本次模拟池，缺料或资料不全工单不占用。不是库存预留、领料指令或正式MRP。'
BOUNDARY='仅所选工单队列竞争当前库存；其他工单的需求、外部预留、替代料、在途到货、半成品跨工单调拨及工艺/设备/人员门槛未纳入。可覆盖不等于可承诺交期或允许投产。已知需求缺口不包含资料不全工单的未知需求。'
STAGES={'orders':{'all':'全部工单','active':'待投料工单','covered':'整单试配可覆盖','short':'已知物料不足','attention':'资料待核对','excluded':'已完工或取消'},
        'materials':{'all':'全部需求物料','short':'已知净需求有缺口','attention':'库存或需求待核对'},'impact':material_impact.STAGES}
PRIORITIES={'紧急':0,'加急':1,'普通':2}
ACTIVE={'未开工','已下达','生产中','进行中'}
CLOSED={'完工待清尾','已完工','已关闭'}
TABLES=['products','materials','bom','work_orders','units','inventory_movements']

def refs(ds,rows):return [{'dataset':ds,'key':r['id']} for r in rows]
def unique(rows):return list({(r['dataset'],r['key']):r for r in rows}.values())
def number(v,positive=False):
    if type(v) not in [int,float,Decimal]:raise ValueError('数量缺失或类型无效')
    try:n=Decimal(str(v))
    except InvalidOperation:raise ValueError('数量不是有效数字')
    if not n.is_finite() or n<0 or positive and n<=0:raise ValueError('数量必须为有效非负值')
    return n
def scalar(n):return None if n is None else int(n) if n==n.to_integral_value() else float(n)
def day(value):
    if not isinstance(value,str):raise ValueError('日期缺失')
    v=date.fromisoformat(value)
    if v.isoformat()!=value:raise ValueError('日期须为YYYY-MM-DD')
    return v
def stamp(value):
    if not isinstance(value,str):raise ValueError('时间缺失')
    v=datetime.fromisoformat(value)
    if v.tzinfo or v.isoformat()!=value:raise ValueError('时间格式无效')
    return value
def clean(value):
    if isinstance(value,dict):return {k:clean(v) for k,v in value.items() if not k.startswith('_')}
    if isinstance(value,list):return [clean(v) for v in value]
    if isinstance(value,Decimal):return scalar(value)
    return value

def filters(q):
    names={'family','product','work_order','from','to','q','order','stock_policy','lot_policy','tab','stage','page','receipt'}
    if set(q)-names:raise ValueError('不支持的备料筛选字段')
    if hasattr(q,'getlist') and any(len(q.getlist(k))!=1 for k in q):raise ValueError('筛选字段不可重复')
    f={k:q.get(k,'') for k in ['family','product','work_order','from','to','q']}
    f.update(order=q.get('order','start'),stock_policy=q.get('stock_policy','protect_safety'),lot_policy=q.get('lot_policy','ledger'),tab=q.get('tab','orders'),stage=q.get('stage','active' if q.get('tab','orders')=='orders' else 'all'))
    if any(not isinstance(v,str) or len(v)>150 for v in f.values()):raise ValueError('筛选内容无效')
    if f['order'] not in ['start','priority'] or f['stock_policy'] not in ['protect_safety','all_usable']:raise ValueError('请选择有效的试配顺序与库存策略')
    if f['lot_policy'] not in material_lot_allocation.POLICIES:raise ValueError('批次日期策略无效')
    if f['tab'] not in STAGES or f['stage'] not in STAGES[f['tab']]:raise ValueError('工作区或清单状态无效')
    for key in ['from','to']:
        if f[key]:day(f[key])
    if f['from'] and f['to'] and f['from']>f['to']:raise ValueError('开始日期晚于结束日期')
    return f

def receipt(f,revision):
    h=hashlib.sha256()
    for name in ['material_planning.py','material_planning_views.py','material_lot_allocation.py','inventory_age.py','material_impact.py','material_returns.py','supply.py','schema.py']:h.update((Path(__file__).parent/name).read_bytes())
    conf={k:v for k,v in f.items() if k not in ['tab','stage']}
    payload={'scope':conf,'data':list(revision),'as_of':analytics.AS_OF,'calculation':h.hexdigest()}
    return hashlib.sha256(json.dumps(payload,sort_keys=True,ensure_ascii=False).encode()).hexdigest()

class MaterialPlanning:
    def __init__(self,data,f,cutoff=None,stock=None):
        self.f=f;self.cutoff=cutoff or analytics.AS_OF;self.as_of=day(self.cutoff[:10]);self.data=data;self.stock=stock or supply.SupplyData(data,self.cutoff)
        self.lot_pool=material_lot_allocation.LotAllocation(data,self.cutoff,f['lot_policy']) if f.get('lot_policy','ledger')!='ledger' else None
        self.products={r['id']:r for r in data.get('products',[])};self.materials={r['id']:r for r in data.get('materials',[])}
        self.bom=defaultdict(list);self.units=defaultdict(list);self.movements=defaultdict(list);self.global_issues=[]
        for b in data.get('bom',[]):self.bom[b.get('product_id'),b.get('version')].append(b)
        for r in data.get('units',[]):self.units[r.get('work_order_id')].append(r)
        for r in data.get('inventory_movements',[]):
            if r.get('work_order_id'):self.movements[r['work_order_id']].append(r)
        self.pool={};self.material_rows={};self.orders={}
        selected=[]
        for w in data.get('work_orders',[]):
            p=self.products.get(w.get('product_id'),{});text=' '.join(str(v) for v in [w.get('id'),w.get('product_id'),p.get('model'),p.get('family')]).lower()
            if f['family'] and p.get('family')!=f['family'] or f['product'] and w.get('product_id')!=f['product'] or f['work_order'] and w['id']!=f['work_order']:continue
            if f['q'] and f['q'].lower() not in text:continue
            if f['from'] or f['to']:
                try:start=day(w.get('planned_start')).isoformat()
                except ValueError:self.global_issues.append(w['id']+'计划开工日无效，不能判断是否属于所选日期范围');continue
                if f['from'] and start<f['from'] or f['to'] and start>f['to']:continue
            selected.append(w)
        for w in selected:self.orders[w['id']]=self.build_order(w)
        rank=lambda w:(PRIORITIES.get(w['priority'],99),w.get('planned_start') or '',w.get('planned_end') or '',w['id']) if f['order']=='priority' else (w.get('planned_start') or '',PRIORITIES.get(w['priority'],99),w.get('planned_end') or '',w['id'])
        ordered=sorted(self.orders.values(),key=rank);self.ordered=ordered
        for i,w in enumerate(ordered,1):
            w['sequence']=i
            if w['issues']:w['state']='attention'
            elif w['excluded']:w['state']='excluded'
            else:self.allocate(w)
            w['flags']=['all',w['state']]+(['active'] if not w['excluded'] else [])
        for m in self.material_rows.values():
            m['remaining_pool']=self.pool[m['id']];m['known_gap']=None if m['initial_pool'] is None else max(Decimal(0),m['net_demand']-m['initial_pool'])
            m['flags']=['all']+(['short'] if m['known_gap'] and m['known_gap']>0 else [])+(['attention'] if m['issues'] or m['unknown_work_orders'] else [])
            m['demand_work_orders']=sorted(set(m['demand_work_orders']));m['unknown_work_orders']=sorted(set(m['unknown_work_orders']))

    def material(self,mid):
        if mid in self.material_rows:return self.material_rows[mid]
        m=self.materials.get(mid,{});s=self.stock.stock_index.get(mid);issues=[];usable=None;buffer=Decimal(0);pool=None
        if not m:issues.append('物料档案缺失')
        if not s:issues.append('无可核对库存记录，未当作零库存')
        else:
            issues+=s['issues']
            try:
                usable=number(s['usable_state_qty'])
                if self.f['stock_policy']=='protect_safety':buffer=number(m.get('safety_qty'))
                if m.get('unit')=='件' and (usable!=usable.to_integral_value() or buffer!=buffer.to_integral_value()):raise ValueError('整件库存或安全库存非整数')
                pool=max(Decimal(0),usable-buffer)
            except ValueError as e:issues.append(str(e))
        if issues:pool=None
        dated=None
        if self.lot_pool:
            dated=self.lot_pool.candidate_qty(mid)
            if pool is not None:pool=self.lot_pool.setup(mid,buffer)
        obj={'id':mid,'material':m.get('name','档案缺失'),'category':m.get('category','未知'),'unit':m.get('unit','未知'),
             'usable_state_qty':usable,'safety_buffer':buffer,'initial_pool':pool,'net_demand':Decimal(0),'simulated_allocated':Decimal(0),
             'known_gap':None,'remaining_pool':None,'open_purchase_qty':s.get('open_purchase_qty') if s else None,
             'demand_work_orders':[],'unknown_work_orders':[],'allocations':[],'issues':list(dict.fromkeys(issues))}
        if self.lot_pool:obj.update(date_candidate_qty=dated,date_excluded_usable_qty=usable-dated if usable is not None else None,lot_policy=self.f['lot_policy'])
        self.pool[mid]=pool;self.material_rows[mid]=obj;return obj

    def build_order(self,w):
        p=self.products.get(w.get('product_id'));issues=[];warnings=[];sources=refs('work_orders',[w]);items={};plan=None;start=None;end=None
        if p:sources+=refs('products',[p])
        else:issues.append('产品配置档案缺失')
        try:
            if type(w.get('planned_qty')) is not int:raise ValueError('计划数量须为整数')
            plan=number(w['planned_qty'],True);start=day(w.get('planned_start'));end=day(w.get('planned_end'))
            if end<start:raise ValueError('计划完工早于开工')
        except ValueError as e:issues.append(str(e))
        if w.get('priority') not in PRIORITIES:issues.append('工单优先级未映射，不能确定试配次序')
        status=w.get('status');cancelled=status=='已取消';assembled=0
        for u in self.units[w['id']]:
            try:
                if stamp(u.get('assembly_at'))>self.cutoff:continue
                sources+=refs('units',[u])
                if u.get('product_id')!=w.get('product_id'):issues.append('装配SN配置与工单不一致')
                assembled+=1
            except ValueError as e:issues.append(u['id']+'：'+str(e))
        if status not in ACTIVE|CLOSED|{'已取消'}:issues.append('工单状态未映射')
        if status in CLOSED and plan is not None and assembled<plan:issues.append('完工状态与已登记装配数量不一致')
        if plan is not None and assembled>plan:warnings.append('装配数量超过计划，需另查超产原因')
        excluded=cancelled or status in CLOSED or plan is not None and assembled>=plan
        if excluded:return {'id':w['id'],'product_id':w.get('product_id'),'family':p.get('family','未匹配') if p else '未匹配','model':p.get('model','未匹配') if p else '未匹配',
            'planned_qty':w.get('planned_qty'),'planned_start':w.get('planned_start'),'planned_end':w.get('planned_end'),'priority':w.get('priority'),'status':status,'bom_version':w.get('bom_version'),'assembled_qty':assembled,'excluded':True,'state':'excluded','items':[],
            'issues':list(dict.fromkeys(issues)),'warnings':warnings,'sources':sources,'short_materials':0,'unknown_materials':0,'material_count':0,'_eligible':False}
        version=w.get('bom_version');bom=self.bom[w.get('product_id'),version];basis=min(start,self.as_of) if start else self.as_of
        if not version or not bom:issues.append('工单指定BOM版本没有明细，未回退配置当前版本')
        if p and version!=p.get('bom_version'):warnings.append('工单BOM与配置当前登记版本不同；按工单版本核查')
        seen=set();lines=[]
        for b in bom:
            sources+=refs('bom',[b]);mid=b.get('material_id');m=self.material(mid);sources+=refs('materials',[self.materials[mid]]) if mid in self.materials else []
            if self.lot_pool:sources+=self.lot_pool.sources(mid)
            item=items.setdefault(mid,{'material_id':mid,'material':m['material'],'unit':m['unit'],'net_per_unit':Decimal(0),'gross_unrounded':Decimal(0),'gross_required':None,'issued_qty':Decimal(0),'remaining_required':None,'before_pool':None,'simulated_allocated':Decimal(0),'after_pool':None,'gap':None,'bom_lines':[],'issue_rows':[],'issues':[],'warnings':[]})
            local=[];raw=None
            try:
                if day(b.get('effective'))>basis:raise ValueError('BOM行尚未在计划开工与快照共同基准前生效')
                qty=number(b.get('qty'),True);scrap=number(b.get('scrap_allowance'))
                if scrap>=1:raise ValueError('损耗定额须小于1')
                if mid not in self.materials or not self.materials[mid].get('unit'):raise ValueError('物料或计量单位缺失')
                if m['unit']=='件' and qty!=qty.to_integral_value():raise ValueError('单位用量为非整数件数')
                branch=b.get('assembly_level')
                if not isinstance(branch,str) or not branch:raise ValueError('BOM分支缺失，无法核对重复行')
                if (mid,branch) in seen:raise ValueError('同版本同物料同分支存在重复BOM行')
                seen.add((mid,branch))
                if plan is not None:raw=plan*qty*(1+scrap);item['gross_unrounded']+=raw;item['net_per_unit']+=qty
            except ValueError as e:local.append(str(e));issues.append(b['id']+'：'+str(e));item['issues']+=local
            item['bom_lines'].append({k:b.get(k) for k in ['id','assembly_level','effective','qty','scrap_allowance']}|{'gross_contribution':raw,'issues':local})
        for item in items.values():
            item.update(gross_issued_qty=Decimal(0),returned_qty=Decimal(0),return_rows=[],issue_balance_known=True)
        related=self.stock.return_reconciliation
        # Include linked return evidence even when its declared work order is wrong.
        source_ids={r['id'] for r in self.movements[w['id']]}
        linked_returns=[r for r in related['returns'].values() if r['work_order_id']==w['id'] or r['issue_id'] in source_ids]
        for r in linked_returns:
            sources+=refs('inventory_movements',[r])
            if r['issue']:sources+=refs('inventory_movements',[r['issue']])
            if r['issues']:issues.append(r['id']+'：'+'；'.join(r['issues']))
        for r in self.movements[w['id']]:
            try:
                if stamp(r.get('occurred'))>self.cutoff:continue
                sources+=refs('inventory_movements',[r]);mid=r.get('material_id');item=items.get(mid)
                if r.get('movement')=='生产退料':
                    report=related['returns'][r['id']]
                    if item:item['return_rows'].append(report)
                    if not item:raise ValueError('退料物料不属于指定BOM版本')
                    if not report['verified']:raise ValueError('退料关联待核对，净领料未计算')
                    lot=self.stock.lot_index.get(supply.lot_id(supply.lot_key(r)))
                    origin=self.stock.lot_index.get(supply.lot_id(supply.lot_key(report['issue'])))
                    if not lot or lot['issues'] or not origin or origin['issues']:raise ValueError('领退料批次库位账据待核对')
                    item['returned_qty']+=Decimal(report['return_qty'])
                    continue
                if r.get('movement')!='生产领料':raise ValueError('工单关联流水类型尚未映射，未自动扣减或回退领料')
                if r.get('reference')!=w['id']:raise ValueError('领料来源单号与工单不一致')
                if not item:raise ValueError('领料物料不属于指定BOM版本')
                signed=Decimal(str(r.get('qty_signed')))
                if not signed.is_finite() or signed>=0:raise ValueError('领料数量方向无效')
                if item['unit']=='件' and signed!=signed.to_integral_value():raise ValueError('领料件数非整数')
                lot=self.stock.lot_index.get(supply.lot_id(supply.lot_key(r)))
                if not lot or lot['issues']:raise ValueError('领料所在批次库位账据待核对')
                item['gross_issued_qty']-=signed;item['issue_rows'].append({'id':r['id'],'qty':-signed,'lot':r.get('lot'),'location':r.get('location'),'occurred':r['occurred']})
            except (ValueError,InvalidOperation) as e:
                issues.append(r['id']+'：'+str(e))
                if items.get(r.get('material_id')):items[r['material_id']]['issue_balance_known']=False
        for item in items.values():
            if any(r['issues'] and (r['material_id']==item['material_id'] or r['issue'] and r['issue']['material_id']==item['material_id']) for r in linked_returns):item['issue_balance_known']=False
            item['issued_qty']=item['gross_issued_qty']-item['returned_qty'] if item['issue_balance_known'] else None
            if not item['issue_balance_known']:
                item['gross_issued_qty']=None;item['returned_qty']=None
            if plan is not None and not item['issues']:
                gross=item['gross_unrounded'];gross=gross.to_integral_value(rounding=ROUND_CEILING) if item['unit']=='件' else gross
                item['gross_required']=gross;item['remaining_required']=max(Decimal(0),gross-item['issued_qty']) if item['issued_qty'] is not None else None
                if item['issued_qty'] is not None and item['issued_qty']>gross:item['warnings'].append('净领量超过模拟需求，不退回模拟库存')
        eligible=not issues
        for mid,item in items.items():
            mat=self.material(mid)
            if eligible:
                mat['net_demand']+=item['remaining_required'];mat['demand_work_orders'].append(w['id'])
            else:mat['unknown_work_orders'].append(w['id'])
        return {'id':w['id'],'product_id':w.get('product_id'),'family':p.get('family','未匹配') if p else '未匹配','model':p.get('model','未匹配') if p else '未匹配',
            'planned_qty':w.get('planned_qty'),'planned_start':w.get('planned_start'),'planned_end':w.get('planned_end'),'priority':w.get('priority'),'status':status,'bom_version':version,'assembled_qty':assembled,
            'excluded':False,'state':'attention','items':list(items.values()),'issues':list(dict.fromkeys(issues)),'warnings':warnings,'sources':unique(sources),'short_materials':0,'unknown_materials':0,'material_count':len(items),'_eligible':eligible}

    def allocate(self,w):
        short=0;unknown=0
        for item in w['items']:
            need=item['remaining_required'];mid=item['material_id'];available=self.pool[mid];item['before_pool']=available;item['after_pool']=available
            if self.lot_pool:
                use_day=max(self.cutoff[:10],w['planned_start']);checked=self.lot_pool.available(mid,use_day) if available is not None else None
                item.update(use_day=use_day,date_available_pool=checked,date_excluded_at_use=available-checked if available is not None else None,lot_allocations=[])
                available=checked
            if need is None or need>0 and available is None:unknown+=1;item['issues']+=self.material_rows[mid]['issues'] or ['净需求未知']
            else:
                item['gap']=max(Decimal(0),need-available) if need>0 else Decimal(0)
                if item['gap']>0:short+=1
        w['unknown_materials']=unknown;w['short_materials']=short;w['state']='attention' if unknown else 'short' if short else 'covered'
        if unknown:w['issues'].append('部分需求物料库存不可核对，整单未试配')
        if w['state']=='covered':
            for item in w['items']:
                mid=item['material_id'];need=item['remaining_required'];item['simulated_allocated']=need
                if need:
                    if self.lot_pool:
                        plans=self.lot_pool.preview(mid,need,item['use_day']);self.lot_pool.commit(mid,plans);item['lot_allocations']=plans
                    self.pool[mid]-=need;self.material_rows[mid]['simulated_allocated']+=need
                    self.material_rows[mid]['allocations'].append({'work_order_id':w['id'],'sequence':w['sequence'],'qty':need,'before':item['before_pool'],'after':self.pool[mid]})
                item['after_pool']=self.pool[mid]

    def summary(self):
        counts=Counter(w['state'] for w in self.ordered)
        return {'orders':len(self.ordered),'active':sum(not w['excluded'] for w in self.ordered),**{k:counts[k] for k in ['covered','short','attention','excluded']},'materials':len(self.material_rows),'short_materials':sum(bool(r['known_gap']) for r in self.material_rows.values()),
                'covered_planned_qty':sum(w['planned_qty'] for w in self.ordered if w['state']=='covered'),'unknown_demand_orders':sum(not w['excluded'] and not w['_eligible'] for w in self.ordered)}

    def rows(self,tab):return self.ordered if tab=='orders' else sorted(self.material_rows.values(),key=lambda r:(r['unit'],r['known_gap'] is None,-(r['known_gap'] or 0),r['id']))
    def detail(self,kind,key):
        if kind=='orders':
            if key not in self.orders:raise Record.DoesNotExist()
            w=self.orders[key];sources=list(w['sources'])
            for item in w['items']:
                if item['material_id'] in self.stock.stock_index:sources+=self.stock.detail('material',item['material_id'])['sources']
                if self.lot_pool:sources+=self.lot_pool.sources(item['material_id'])
            returns=[r for r in self.stock.return_reconciliation['returns'].values() if r['work_order_id']==key or r['issue'] and r['issue']['work_order_id']==key]
            for row in returns:
                sources+=refs('inventory_movements',[row])
                if row['issue']:sources+=refs('inventory_movements',[row['issue']])
                for record in (row,row['issue']):
                    if record and record['material_id'] in self.stock.stock_index:sources+=self.stock.detail('material',record['material_id'])['sources']
            return {'row':w,'sources':unique(sources),'return_reconciliation':dict(version=material_returns.VERSION,notice=material_returns.NOTICE,rows=returns)}
        if kind=='materials':
            if key not in self.material_rows:raise Record.DoesNotExist()
            m=self.material_rows[key];sources=[]
            if key in self.stock.stock_index:sources+=self.stock.detail('material',key)['sources']
            for wid in set(m['demand_work_orders']+m['unknown_work_orders']):sources+=self.orders[wid]['sources']
            if self.lot_pool:sources+=self.lot_pool.sources(key)
            return {'row':m,'sources':unique(sources),'lots':[supply.clean(x) for x in self.stock.stock_index.get(key,{}).get('_lots',[])],'date_lots':self.lot_pool.details(key) if self.lot_pool else [],'work_orders':[{'id':w['id'],'sequence':w['sequence'],'state':w['state'],'product_id':w['product_id'],'planned_start':w['planned_start'],'item':next(i for i in w['items'] if i['material_id']==key)} for w in self.ordered if any(i['material_id']==key for i in w['items'])]}
        raise ValueError('备料对象类型无效')

def current(f):
    rev=analytics.revision();return MaterialPlanning(analytics._tables(rev),f,stock=supply.cached(rev)),rev
