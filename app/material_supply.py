"""A quantity-conserving procurement bridge for an existing material demand scope."""
from collections import defaultdict
from decimal import Decimal
from pathlib import Path
import hashlib,json
from . import material_planning as mp,access

STAGES={'unreceived':'未到货登记','held':'到货未批准入库','approved_unposted':'批准未入库','posted':'累计采购入库'}
NOTE='以采购行为粒度：未到货＋到货未批准＋批准未入库＋累计入库＝有效采购数量。只汇总资料可核对的非取消采购行；异常行单列，未知不补零。'
BOUNDARY='采购覆盖该物料的全部已导入采购，需求沿用所选工单队列；二者没有逐工单预留关系。累计入库可能已被领用，不能再加到当前库存。承诺日不是到货预测，也未包含检验、运输与入库耗时；本页不改变试配结果。'

def digest(planning_receipt,user,key):
    payload=[planning_receipt,key,user.pk,access.role(user),hashlib.sha256(Path(__file__).read_bytes()).hexdigest()]
    return hashlib.sha256(json.dumps(payload,ensure_ascii=False).encode()).hexdigest()

def build(d,key):
    context=d.detail('materials',key);m=context['row'];material=d.materials.get(key,{})
    purchases=[];sources=list(context['sources']);totals={k:Decimal(0) for k in STAGES};ordered=Decimal(0);overdue=Decimal(0);promises=defaultdict(lambda:{'qty':Decimal(0),'purchase_ids':[]})
    source_receipts=set();issues=[]
    for p in sorted((p for p in d.stock.po_rows if p['material_id']==key),key=lambda p:(p['due'],p['id'])):
        local=list(p['issues']);rr=[];parts={k:Decimal(0) for k in STAGES};qty=None
        sources+=d.stock.po_sources(p)
        try:
            qty=mp.number(p['qty'],True);mp.day(p['ordered']);mp.day(p['due'])
            if not material.get('unit'):raise ValueError('计量单位缺失')
            if m['unit']=='件' and qty!=qty.to_integral_value():raise ValueError('采购件数非整数')
        except ValueError as e:local.append(str(e))
        received=Decimal(0)
        for r in p['_receipts']:
            source_receipts.add(r['id']);row_issues=list(r['issues']);rq=None;posted=None
            try:
                rq=mp.number(r['qty'],True);mp.stamp(r['received']);posted=mp.number(r['putaway_qty'])
                if m['unit']=='件' and (rq!=rq.to_integral_value() or posted!=posted.to_integral_value()):raise ValueError('到货或入库件数非整数')
                if r['status'] not in ['待检','检验合格','隔离','待退货']:raise ValueError('到货状态尚未映射')
                at=defaultdict(list)
                for q in r['_inspections']:
                    mp.stamp(q['inspected']);at[q['inspected']].append((q['result'],q['disposition']))
                if any(len(set(v))>1 for v in at.values()):raise ValueError('同一时刻检验处置冲突，无法确定批准顺序')
                for movement in r['_moves']:mp.stamp(movement['occurred'])
                if not r['_inspections'] and r['status']=='检验合格':raise ValueError('合格到货缺少检验批准记录')
            except ValueError as e:row_issues.append(str(e))
            if rq is not None:received+=rq
            if not row_issues:
                parts['posted']+=posted
                parts['approved_unposted' if r['approved'] else 'held']+=rq-posted
            local += [r['id']+'：'+x for x in row_issues]
            latest=r['latest_inspection']
            rr.append({'id':r['id'],'lot':r['lot'],'received':r['received'],'qty':rq,'status':r['status'],'approved':r['approved'] and not row_issues,
                       'inspection_id':latest['id'] if latest else None,'inspection_at':latest['inspected'] if latest else None,'result':latest['result'] if latest else None,'disposition':latest['disposition'] if latest else None,
                       'posted':posted if not row_issues else None,'unposted':rq-posted if rq is not None and not row_issues else None,'issues':list(dict.fromkeys(row_issues)),
                       'movements':[{k:x.get(k) for k in ['id','occurred','movement','qty_signed','lot','location','reference']} for x in r['_moves']]})
        cancelled=p['status']=='已取消'
        if qty is not None:
            if p['status']=='已到货' and received!=qty or p['status']=='未到货' and received!=0 or p['status']=='部分到货' and not 0<received<qty:local.append('采购状态与已登记到货数量不一致')
            parts['unreceived']=max(Decimal(0),qty-received)
        local=list(dict.fromkeys(local));valid=not local and not cancelled
        if valid:
            assert sum(parts.values())==qty
            ordered+=qty
            for stage in STAGES:totals[stage]+=parts[stage]
            if parts['unreceived']:
                promises[p['due']]['qty']+=parts['unreceived'];promises[p['due']]['purchase_ids'].append(p['id'])
                if p['due']<d.cutoff[:10]:overdue+=parts['unreceived']
        purchases.append({'id':p['id'],'supplier_id':p['supplier_id'],'supplier':p['supplier'],'ordered':p['ordered'],'due':p['due'],'status':p['status'],'qty':qty,
                          **(parts if valid else {k:None for k in STAGES}),'valid':valid,'cancelled':cancelled,'issues':local,'receipts':rr})
    for r in d.stock.receipts.values():
        if r['material_id']==key and r['id'] not in source_receipts:
            issues.append({'id':r['id'],'message':'到货未能归入该物料的截止前采购行，未加入供应数量'})
            sources+=mp.refs('receipts',[r])+mp.refs('incoming_inspections',r['_inspections'])+mp.refs('inventory_movements',r['_moves'])
    demand=[w for w in context['work_orders'] if w['item']['remaining_required'] is not None and w['item']['remaining_required']>0]
    return mp.clean({'material':{k:m[k] for k in ['id','material','unit','known_gap','net_demand','initial_pool','usable_state_qty','safety_buffer','unknown_work_orders']},
      'summary':{'purchase_lines':len(purchases),'valid_lines':sum(p['valid'] for p in purchases),'attention_lines':sum(bool(p['issues']) for p in purchases),'cancelled_lines':sum(p['cancelled'] and not p['issues'] for p in purchases),'ordered':ordered,**totals,'overdue_unreceived':overdue},
      'promises':[{'due':due,'qty':v['qty'],'purchase_ids':v['purchase_ids'],'overdue':due<d.cutoff[:10]} for due,v in sorted(promises.items())],
      'purchases':purchases,'unmatched_receipts':issues,'sources':mp.unique(sources),'as_of':d.cutoff,'filters':d.f,'note':NOTE,'boundary':BOUNDARY,
      'demand_start_range':{'first':min((w['planned_start'] for w in demand if w['planned_start']),default=None),'last':max((w['planned_start'] for w in demand if w['planned_start']),default=None)}})
