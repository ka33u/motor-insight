"""Read imported WIP/order evidence without inventing task progress or line-side stock."""
from collections import Counter, defaultdict
from functools import lru_cache
from pathlib import Path
import hashlib
import json
from . import analytics, material_planning as mp, supply, wip_flow, material_returns, return_stock
from .schema import SCHEMAS

VERSION = 'wip-replanning-evidence-v1'
NOTE = ('工单是本页阅读粒度。报工按时间登记分组，只计记录笔数，不累计良品作为完工台数；'
        '定子与转子按原批次份额分别核对，隔离和返工份额仍是在制，不等于可投入。'
        '整单待领沿用备料定义，不等于剩余工序耗料；缺失留空。')
BOUNDARY = ('当前尚缺工单批内任务与报工的明确映射、剩余工序数量及工时、线边实盘与实际消耗、'
            '在加工人机占用和恢复条件。本页不生成剩余工序排程，不证明可开工，不改写原试排。')
STAGES = {'all':'全部工单','active':'登记为待投料或生产中','reported':'有截止前报工','open':'有未结束时间登记',
          'positions':'有核定在制份额','unknown':'在制位置待核对','closed_wip':'完工登记仍有在制份额'}
OP_FIELDS = ('id','work_order_id','object_type','object_id','process','equipment_id','resource_id','employee_id',
             'started','finished','input_qty','good_qty','scrap_qty','rework_qty','status')
MATERIAL_FIELDS = ('material_id','material','unit','gross_required','gross_issued_qty','returned_qty','issued_qty','remaining_required','issues','warnings')


def filters(q):
    if set(q)-{'q','work_order_id','stage','page','receipt'}:raise ValueError('不支持的在制重排核对筛选')
    if hasattr(q,'getlist') and any(len(q.getlist(k))!=1 for k in q):raise ValueError('筛选字段不可重复')
    f={k:q.get(k,'') for k in ('q','work_order_id')};f['stage']=q.get('stage','all')
    if any(not isinstance(v,str) or len(v)>150 for v in f.values()) or f['stage'] not in STAGES:raise ValueError('在制重排核对筛选无效')
    return {k:v.strip() for k,v in f.items()}


def operation_state(r,cutoff):
    start=wip_flow.clock(r.get('started'));finish=wip_flow.clock(r.get('finished'))
    if not start or r.get('finished') and not finish or finish and finish<start:return 'unknown'
    if start>cutoff:return 'future'
    if finish and finish<=cutoff:return 'ended'
    return 'open'


class WipReadiness:
    def __init__(self,data,cutoff=None,stock=None):
        data={**{k:[] for k in SCHEMAS},**data}
        self.data=data;self.cutoff=cutoff or analytics.AS_OF
        self.wip=wip_flow.Wip(data,self.cutoff,self.cutoff)
        self.stock=stock or supply.SupplyData(data,self.cutoff)
        # Reuse existing definitions, but never expose allocation as remaining-task demand.
        self.material=mp.MaterialPlanning(data,mp.filters({}),self.cutoff,self.stock)
        self.ops=defaultdict(list);self.roots=defaultdict(list);self.units=defaultdict(list);self.routes=defaultdict(list)
        self.products={r['id']:r for r in data.get('products',[])}
        for r in data.get('operations',[]):self.ops[r.get('work_order_id')].append(r)
        for r in self.wip.rows:self.roots[r['work_order_id']].append(r)
        for r in data.get('units',[]):self.units[r.get('work_order_id')].append(r)
        for r in data.get('routes',[]):self.routes[r.get('product_id')].append(r)
        # A mixed container depends on all contributing root shares, including
        # their openings and earlier events outside this work order.
        self.root_links=defaultdict(set)
        for e in self.wip.events:
            roots=set(e['roots'])|set(e['history_roots'])
            for root in roots:self.root_links[root].update(roots)
        self.rows=[];self.details={}
        for w in sorted(data.get('work_orders',[]),key=lambda r:r['id']):self.build(w)

    def build(self,w):
        key=w['id'];product=self.products.get(w.get('product_id'),{});root_rows=self.roots[key]
        refs=supply.refs('work_orders',[w])+supply.refs('products',[product] if product else [])
        op_rows=[]
        for r in sorted(self.ops[key],key=lambda r:(r.get('started') or '',r['id'])):
            row={k:r.get(k) for k in OP_FIELDS};row['time_state']=operation_state(r,self.wip.end)
            row['route_id']=None
            row['route_candidates']=[{k:t.get(k) for k in ('id','version','branch','process')} for t in self.routes[w.get('product_id')]
                if t.get('process')==r.get('process') and t.get('version')==product.get('route_version')]
            op_rows.append(row)
        counts=Counter(r['time_state'] for r in op_rows)
        refs+=supply.refs('operations',op_rows)
        refs += [{'dataset':ds,'key':r.get(k)} for r in op_rows for ds,k in
            [('equipment','equipment_id'),('employees','employee_id'),('production_resources','resource_id')]
            if r.get(k)]
        refs += [{'dataset':'routes','key':t['id']} for r in op_rows for t in r['route_candidates']]
        groups=[];positions=[]
        for kind in ('定子','转子'):
            roots=[r for r in root_rows if r['kind']==kind]
            known=[r for r in roots if r['state'] not in ('missing','attention') and r['baseline_qty'] is not None and r['wip_qty'] is not None]
            groups.append(dict(kind=kind,roots=len(roots),verified_roots=len(known),
                wip_qty=sum(r['wip_qty'] for r in known) if roots and len(known)==len(roots) else None,
                known_wip_qty=sum(r['wip_qty'] for r in known),unknown_roots=len(roots)-len(known)))
        for r in root_rows:
            pending=[r['id']];seen=set()
            while pending:
                root=pending.pop()
                if root in seen or root not in self.wip.roots:continue
                seen.add(root);refs+=self.wip.evidence(root);pending.extend(self.root_links[root]-seen)
            if r['state'] not in ('missing','attention'):
                positions += [dict(p,root_id=r['id'],kind=r['kind'],location_kind=p['kind']) for p in r['positions']]
        unit_rows=[{k:r.get(k) for k in ('id','assembly_at','product_id','stator_batch','rotor_batch')} for r in self.units[key]]
        known_units=[u for u in unit_rows if wip_flow.clock(u.get('assembly_at')) and u['assembly_at']<=self.cutoff and u['product_id']==w.get('product_id')]
        unknown_units=[u for u in unit_rows if not wip_flow.clock(u.get('assembly_at')) or u['product_id']!=w.get('product_id')]
        refs+=supply.refs('units',unit_rows)
        m=self.material.orders[key]
        materials=mp.clean([{k:r.get(k) for k in MATERIAL_FIELDS} for r in m['items']])
        material_issues=list(m['issues'])
        if m['excluded']:material_issues.append('原备料规则已排除该工单，未计算整单待领，不能当作零需求')
        refs+=m['sources']
        for lot in self.stock.lots:
            if lot['material_id'] in {r['material_id'] for r in materials}:refs+=return_stock.lot_sources(lot,self.stock)
        active=w.get('status') in mp.ACTIVE;closed=w.get('status') in mp.CLOSED
        known_positions=sum(g['known_wip_qty'] for g in groups)>0
        position_unknown=any(g['roots']==0 or g['unknown_roots'] for g in groups) or bool(self.wip.global_issues)
        row=dict(id=key,product_id=w.get('product_id'),model=product.get('model'),status=w.get('status'),planned_qty=w.get('planned_qty'),
            bom_version=w.get('bom_version'),reported=counts['ended']+counts['open'],ended_reports=counts['ended'],open_reports=counts['open'],
            unknown_reports=counts['unknown'],future_reports=counts['future'],assembled_sn=len(known_units),unknown_sn=len(unknown_units),
            wip_groups=groups,position_unknown=position_unknown,material_count=len(materials),
            material_unknown=sum(r['remaining_required'] is None for r in materials),material_uncomputed=m['excluded'] or not materials,
            material_attention=bool(material_issues),remaining_task_qty=None,remaining_task_minutes=None,remaining_material_qty=None,
            scheduling_state='not_computed',
            flags=['all']+(['active'] if active else [])+(['reported'] if counts['ended']+counts['open'] else [])+
                (['open'] if counts['open'] else [])+(['positions'] if known_positions else [])+(['unknown'] if position_unknown else [])+
                (['closed_wip'] if closed and known_positions else []))
        gaps=[dict(code='task_mapping',owner='计划 / 车间',need='工单、批内份号、路线版本与报工编号的明确映射；重复与返工归属'),
              dict(code='remaining_work',owner='工艺 / 车间',need='逐任务完成、报废、返工与剩余数量，以及剩余工时和前序约束'),
              dict(code='line_side',owner='仓储 / 车间',need='线边实盘、批次状态、实际耗用及剩余工序需求；净领料不能替代'),
              dict(code='running_capacity',owner='计划 / 设备 / 人员',need='在加工任务的设备、人员占用与预计释放；中断后的恢复和换型条件')]
        self.rows.append(row)
        self.details[key]=dict(row=row,operations=op_rows,roots=root_rows,positions=positions,units=unit_rows,materials=materials,
            material_issues=material_issues,wip_global_issues=self.wip.global_issues,gaps=gaps,
            sources=sorted(supply.unique_refs(refs),key=lambda r:(r['dataset'],r['key'])))

    def cohort(self,f):
        return [r for r in self.rows if (not f['work_order_id'] or r['id']==f['work_order_id']) and
                (not f['q'] or f['q'].casefold() in ' '.join(str(r.get(k) or '') for k in ('id','product_id','model')).casefold())]

    def selected(self,f):return [r for r in self.cohort(f) if f['stage'] in r['flags']]

    def summary(self,rows):
        return dict(work_orders=len(rows),reported=sum('reported' in r['flags'] for r in rows),
            open=sum('open' in r['flags'] for r in rows),positions=sum('positions' in r['flags'] for r in rows),
            unknown=sum(r['position_unknown'] for r in rows),closed_wip=sum('closed_wip' in r['flags'] for r in rows),
            unknown_reports=sum(r['unknown_reports'] for r in rows))

    def matrix(self,rows):
        return [dict(label=status,orders=len(selected),reported=sum('reported' in r['flags'] for r in selected),
                    positions=sum('positions' in r['flags'] for r in selected))
                for status in sorted({r['status'] or '未登记' for r in rows})
                for selected in [[r for r in rows if (r['status'] or '未登记')==status]]]


def rule_hash():
    modules=(wip_flow,mp,supply,material_returns,return_stock)
    h=hashlib.sha256()
    for path in [Path(__file__),Path(__file__).with_name('wip_readiness_views.py')]+[Path(m.__file__) for m in modules]:h.update(path.read_bytes())
    return h.hexdigest()


@lru_cache(maxsize=1)
def cached(revision,rules):return WipReadiness(analytics._tables(revision),stock=supply.cached(revision))


def current():
    revision=analytics.revision();return cached(revision,rule_hash()),revision


def receipt(f,revision):
    return hashlib.sha256(json.dumps([VERSION,f,list(revision),analytics.AS_OF,rule_hash()],ensure_ascii=False,sort_keys=True).encode()).hexdigest()
