"""Read production-return documents beside lot state evidence; never allocate returned stock."""
from collections import Counter
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from . import analytics, material_returns, supply

VERSION = 'return-stock-reading-v1'
NOTE = ('退料按流水计数，单据关联、退料时状态、当前库位证据分别核对。目标库存按物料×批次×库位去重；'
        '同库位还可能含其他收发，其余额不能分摊为某笔退料的剩余量。状态登记不证明检验报告、质量结论或正式授权。')
STAGES = {'all':'全部退料','attention':'有证据待核对','available':'目标当前可用状态','restricted':'目标当前受限状态'}
STATE_NOTE = '本页核对当前台账与同刻状态歧义；未知留空。原仓储余额和备料算法不写回、不替换。'


def filters(query):
    if set(query)-{'material_id','work_order_id','q','stage','page','receipt'}:
        raise ValueError('不支持的退料库存筛选字段')
    out={k:str(query.get(k,'')).strip() for k in ('material_id','work_order_id','q')}
    out['stage']=str(query.get('stage','all'))
    if any(len(v)>150 for v in out.values()) or out['stage'] not in STAGES:
        raise ValueError('退料库存筛选无效')
    return out


def lot_evidence(lot):
    if lot is None:return None
    issues=list(lot['issues'])
    counts=Counter(r['occurred'] for r in lot['_events'])
    if any(n>1 for n in counts.values()):issues.append('同刻有多笔库存状态变更，无法按单号推定先后')
    return dict(id=lot['id'],material_id=lot['material_id'],lot=lot['lot'],location=lot['location'],unit=lot['unit'],
                recorded_state=lot['state'],state=lot['state'] if not issues else None,
                balance_qty=lot['balance_qty'],usable_state_qty=lot['usable_state_qty'] if not issues else None,
                issues=issues,verified=not issues,
                opening=[supply.without_money(r) for r in lot['_opening']],
                timeline=deepcopy(lot['_timeline']),status_events=deepcopy(lot['_events']))


def lot_sources(lot,stock):
    if lot is None:return []
    refs=(supply.refs('inventory_opening',lot['_opening'])+supply.refs('inventory_movements',lot['_moves'])+
            supply.refs('inventory_status_events',lot['_events'])+
            [{'dataset':'employees','key':r['approver_id']} for r in lot['_events']])
    for move in lot['_moves']:
        if move['movement']!='采购入库':continue
        receipt=stock.receipts.get(move['reference'])
        if receipt:
            refs+=supply.refs('receipts',[receipt])+supply.refs('incoming_inspections',receipt['_inspections'])
            refs += [{'dataset':'purchase_lines','key':receipt['purchase_line_id']}]
            purchase=stock.purchase.get(receipt['purchase_line_id'])
            if purchase:refs += [{'dataset':'suppliers','key':purchase['supplier_id']}]
            refs += [{'dataset':'employees','key':r['inspector_id']} for r in receipt['_inspections']]
    return refs


class ReturnStock:
    def __init__(self, stock):
        self.stock=stock;self.cutoff=stock.cutoff;self.rows=[];self.lots={};self.details={}
        lot_views={lot['id']:lot_evidence(lot) for lot in stock.lots}
        for _ in range(len(lot_views)+1):
            changed=False
            for r in stock.return_reconciliation['returns'].values():
                origin=r['issue']
                source=lot_views.get(supply.lot_id(supply.lot_key(origin))) if origin else None
                target=lot_views.get(supply.lot_id(supply.lot_key(r)))
                if target and (source is None or not source['verified']):
                    message='原领料库位证据待核对：'+str(r['issue_id'] or '未关联')
                    if message not in target['issues']:
                        target['issues'].append(message);target.update(verified=False,state=None,usable_state_qty=None);changed=True
            if not changed:break
        for report in stock.return_reconciliation['returns'].values():
            r=deepcopy(report);origin=r['issue']
            target_lot=stock.lot_index.get(supply.lot_id(supply.lot_key(r)))
            origin_lot=stock.lot_index.get(supply.lot_id(supply.lot_key(origin))) if origin else None
            target=deepcopy(lot_views.get(target_lot['id'])) if target_lot else None
            source=deepcopy(lot_views.get(origin_lot['id'])) if origin_lot else None
            current_issues=list(target['issues']) if target else ['退回库位台账缺失']
            current_issues=list(dict.fromkeys(current_issues))
            arrival_issues=[];arrival=None
            if target_lot:
                trace=next((x for x in target_lot['_timeline'] if x['dataset']=='inventory_movements' and x['id']==r['id']),None)
                if not trace or trace['running_qty'] is None:arrival_issues.append('缺少退料时可核对的运行台账')
                else:
                    if any(supply.dec(o['qty'])<0 or o['status'] not in supply.STATES for o in target_lot['_opening']):
                        arrival_issues.append('期初数量或库存状态待核对')
                    earlier=[x for x in target_lot['_timeline'] if x['occurred']<=r['occurred']]
                    if any(x['issues'] for x in earlier):arrival_issues.append('退料时及之前存在台账问题')
                    events=[x for x in target_lot['_events'] if x['occurred']<=r['occurred']]
                    if any(x['occurred']==r['occurred'] for x in events):arrival_issues.append('退料与状态变更同刻，发生先后未核对')
                    if any(n>1 for n in Counter(x['occurred'] for x in events).values()):arrival_issues.append('退料之前存在同刻多笔状态变更')
                    if trace['state'] not in supply.STATES:arrival_issues.append('退料时库存状态未映射')
                    if not arrival_issues:arrival=trace['state']
            else:arrival_issues.append('退回库位台账缺失')
            current_known=not current_issues
            state=target['state'] if current_known else None
            issues=list(dict.fromkeys(r['issues']+current_issues+arrival_issues))
            material=stock.materials.get(r['material_id'],{})
            row={k:r[k] for k in material_returns.FIELDS}
            row.update(material=material.get('name','档案缺失'),unit=r['unit'],issue_id=r['issue_id'],
                original_work_order_id=origin['work_order_id'] if origin else None,
                document_verified=r['verified'],document_issues=r['issues'],
                arrival_state=arrival,arrival_issues=arrival_issues,current_state=state,
                recorded_state=target['recorded_state'] if target else None,current_issues=current_issues,
                current_verified=current_known,lot_id=target['id'] if target else None,
                issues=issues,flags=['all']+(['attention'] if issues else [])+
                (['available' if state=='可用' else 'restricted'] if current_known else []))
            self.rows.append(row)
            if target:
                # Multiple return records share one authoritative lot summary.
                # Origin uncertainty must never be hidden by another good return.
                view={k:v for k,v in target.items() if k not in ('opening','timeline','status_events')}
                view['issues']=list(dict.fromkeys(view['issues']+current_issues))
                old=self.lots.get(target['id'])
                if old:view['issues']=list(dict.fromkeys(old['issues']+view['issues']))
                view['verified']=not view['issues']
                if not view['verified']:view.update(state=None,usable_state_qty=None)
                self.lots[target['id']]=view
            refs=(supply.refs('inventory_movements',[r])+supply.refs('materials',[{'id':r['material_id']}])+
                  lot_sources(target_lot,stock)+lot_sources(origin_lot,stock))
            if origin:refs+=supply.refs('inventory_movements',[origin])+supply.refs('materials',[{'id':origin['material_id']}])
            refs += [{'dataset':'work_orders','key':key} for key in {r['work_order_id'],row['original_work_order_id']} if key]
            self.details[r['id']]=dict(row=row,original_issue=origin,
                original_unit=stock.materials.get(origin['material_id'],{}).get('unit') if origin else None,
                origin_lot=source,target_lot=target,sources=supply.unique_refs(refs))
        self.rows.sort(key=lambda r:(r['occurred'] or '',r['id']),reverse=True)
        self.index={r['id']:r for r in self.rows}

    def cohort(self,f):
        return [r for r in self.rows if (not f['material_id'] or r['material_id']==f['material_id']) and
                (not f['work_order_id'] or f['work_order_id'] in (r['work_order_id'],r['original_work_order_id'])) and
                (not f['q'] or f['q'].casefold() in ' '.join(str(r.get(k) or '') for k in
                ('id','issue_id','material_id','material','lot','location','work_order_id','original_work_order_id')).casefold())]

    def selected(self,f):return [r for r in self.cohort(f) if f['stage'] in r['flags']]

    def unique_lots(self,rows):return [self.lots[key] for key in sorted({r['lot_id'] for r in rows if r['lot_id']})]

    def summary(self,rows):
        return dict(returns=len(rows),target_lots=len(self.unique_lots(rows)),
                    documents_verified=sum(r['document_verified'] for r in rows),
                    current_verified=sum(r['current_verified'] for r in rows),
                    arrival_known=sum(r['arrival_state'] is not None for r in rows),
                    attention=sum('attention' in r['flags'] for r in rows))

    def units(self,rows):
        lots=self.unique_lots(rows);out=[]
        for unit,rr in sorted(supply.group(rows,'unit').items(),key=lambda pair:str(pair[0])):
            ll=[l for l in lots if l['unit']==unit]
            valid=bool(unit) and all(r['document_verified'] for r in rr)
            out.append(dict(unit=unit or '未知',returns=len(rr),target_lots=len(ll),unknown_lots=sum(not l['verified'] for l in ll),
                returned_qty=float(supply.total(rr,'qty_signed')) if valid else None,
                target_balance_qty=float(supply.total(ll,'balance_qty')) if ll and all(l['balance_qty'] is not None for l in ll) else None,
                target_usable_qty=float(supply.total(ll,'usable_state_qty')) if ll and all(l['verified'] and l['usable_state_qty'] is not None for l in ll) else None))
        return out

    def matrix(self,rows):
        labels=sorted({r['current_state'] or '当前证据待核对' for r in rows})
        return [dict(label=label,returns=sum((r['current_state'] or '当前证据待核对')==label for r in rows),
                     document_verified=sum((r['current_state'] or '当前证据待核对')==label and r['document_verified'] for r in rows)) for label in labels]


def current():
    revision=analytics.revision()
    return ReturnStock(supply.cached(revision)),revision


def receipt(f,revision):
    hashes=[hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest() for module in (supply,material_returns)]
    hashes.append(hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    return hashlib.sha256(json.dumps([VERSION,f,list(revision),hashes],ensure_ascii=False,sort_keys=True).encode()).hexdigest()
