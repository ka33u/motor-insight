"""Read-only stocktake evidence; never posts a physical count into the ledger."""
from collections import Counter,defaultdict
from decimal import Decimal,InvalidOperation
from django.core.exceptions import ObjectDoesNotExist
from . import analytics,supply

DATASETS=['stocktake_runs','stocktake_lines','stocktake_recounts','stocktake_dispositions']
STAGES={'all':'全部计划行','variance':'有效盘差','uncounted':'尚未初盘','unknown':'账实不可比','resolved':'复盘恢复一致','pending':'处置待核对'}
NOTE='按各盘点单的账面截止重算期初及库存流水，再对照初盘和最后有效复盘；零实盘保留为零，未盘或未知账面留空。不同盘点单不当作同一时点库存，kg与件分别汇总。'
BOUNDARY='全部为模拟Excel。封库依据是导入登记，不能证明现场或U8流水完整；出现已导入的封库期间库存变动时暂停该行差异计算。复盘与处置登记均不调整账面库存，不代表审批或财务入账。'
def number(value):
    try:
        if isinstance(value,bool) or value is None:return None
        n=Decimal(str(value))
        return n if n.is_finite() and n>=0 else None
    except (InvalidOperation,ValueError):return None
def ref(ds,rows):return supply.refs(ds,rows)
def unique(xs):return list(dict.fromkeys(xs))
def qty_valid(value,unit):
    n=number(value)
    return n is not None and (unit!='件' or n==n.to_integral_value())
def delta(a,b):return float(Decimal(str(a))-Decimal(str(b)))

class Stocktakes:
    def __init__(self,data=None,cutoff=analytics.AS_OF):
        self.data=data if data is not None else analytics.tables();self.cutoff=cutoff
        d=self.data;self.materials=supply.ix(d['materials']);self.people=supply.ix(d['employees'])
        self.runs=[];self.rows=[];self.index={};self.global_issues=[]
        recs=supply.group(d.get('stocktake_recounts',[]),'line_id');disps=supply.group(d.get('stocktake_dispositions',[]),'line_id')
        headers={r['id'] for r in d.get('stocktake_runs',[])};lineids={r['id'] for r in d.get('stocktake_lines',[])}
        for ds,rows,field,keys in [('stocktake_lines',d.get('stocktake_lines',[]),'run_id',headers),('stocktake_recounts',d.get('stocktake_recounts',[]),'line_id',lineids),('stocktake_dispositions',d.get('stocktake_dispositions',[]),'line_id',lineids)]:
            self.global_issues += [f'{ds} · {r["id"]} 的关联对象缺失' for r in rows if r.get(field) not in keys]
        for run in sorted(d.get('stocktake_runs',[]),key=lambda r:(r['book_at'],r['id']),reverse=True):
            lines=[r for r in d.get('stocktake_lines',[]) if r['run_id']==run['id']];issues=[]
            if run['book_at']>cutoff:continue
            if run['status']=='已取消':continue
            if run['status'] not in ['已登记','进行中']:issues.append('盘点登记状态尚未映射')
            if run['kind'] not in ['范围全盘','指定抽盘']:issues.append('盘点范围类型尚未映射')
            if not run['location_prefix']:issues.append('库位范围未声明')
            if run['book_at']!=run['freeze_start'] or run['freeze_start']>run['freeze_end']:issues.append('账面截止与封库区间不一致')
            if not run['freeze_evidence'].strip():issues.append('缺少封库登记依据')
            if run['owner_id'] not in self.people:issues.append('负责工号待核对')
            if run['line_count']!=len(lines) or run['line_count']<=0:issues.append('声明盘点行数与明细不符')
            book=supply.SupplyData(d,run['book_at']);ledger={supply.lot_key(x):x for x in book.lots}
            plan_keys=Counter(supply.lot_key(x) for x in lines)
            scope_lots=[x for x in book.lots if x['location'].startswith(run['location_prefix'])]
            uncovered=[x for x in scope_lots if supply.lot_key(x) not in plan_keys] if run['kind']=='范围全盘' else []
            rr=[]
            for line in sorted(lines,key=lambda x:x['id']):
                key=supply.lot_key(line);lot=ledger.get(key);material=self.materials.get(line['material_id'],{});unit=material.get('unit');errors=list(issues)
                if plan_keys[key]>1:errors.append('同盘点单物料批次库位重复')
                if not line['location'].startswith(run['location_prefix']):errors.append('盘点行超出库位范围')
                if not material or line['unit']!=unit or not unit:errors.append('物料或计量单位待核对')
                if not lot:errors.append('该批次库位缺少账面基准，不能假定账面为零')
                elif lot['balance_qty'] is None or lot['issues']:errors.append('账面期初或流水存在核对事项')
                has_qty=line['initial_qty'] is not None;initial_valid=has_qty and qty_valid(line['initial_qty'],unit)
                if has_qty and not initial_valid:errors.append('初盘数量无效或件数非整数')
                if has_qty and (not line['counted'] or line['counter_id'] not in self.people):errors.append('初盘时间或人员缺失')
                if not has_qty and (line['counted'] or line['counter_id']):errors.append('无初盘数量但登记了时间或人员')
                if line['counted'] and not run['freeze_start']<=line['counted']<=min(run['freeze_end'],cutoff):errors.append('初盘时间不在有效封库区间内')
                recounts=sorted(recs[line['id']],key=lambda r:(r['attempt'],r['counted'],r['id']));active=[r for r in recounts if not r['voided'] and r['counted']<=cutoff]
                if active and not has_qty:errors.append('未初盘已有复盘，依据待核对')
                attempts=Counter(r['attempt'] for r in active)
                for n,r in enumerate(active):
                    if r['attempt']<=0 or attempts[r['attempt']]>1:errors.append('有效复盘轮次冲突')
                    if not qty_valid(r['qty'],unit):errors.append('复盘数量无效或件数非整数')
                    if r['counter_id'] not in self.people or r['counter_id']==line['counter_id']:errors.append('复盘人员未能独立核对')
                    if not r['reason'].strip():errors.append('复盘依据缺失')
                    if not line['counted'] or not line['counted']<=r['counted']<=run['freeze_end']:errors.append('复盘时间与初盘或封库不一致')
                    if n and active[n-1]['counted']>=r['counted']:errors.append('复盘轮次与时间顺序冲突')
                final=active[-1] if active else None;last_time=final['counted'] if final else line['counted']
                moving=[m for m in d['inventory_movements'] if supply.lot_key(m)==key and run['book_at']<m['occurred']<=(last_time or run['book_at'])]
                if moving:errors.append('账面截止至实盘期间发生库存变动，账实不同步')
                effective=final['qty'] if final else line['initial_qty'];eligible=has_qty and not errors
                bookqty=lot['balance_qty'] if lot else None;variance=delta(effective,bookqty) if eligible else None
                initial_delta=delta(line['initial_qty'],bookqty) if eligible else None
                dispositions=sorted(disps[line['id']],key=lambda r:(r['recorded'],r['id']));current=[r for r in dispositions if r['recorded']<=cutoff];disp=current[-1] if current else None;disp_issues=[]
                if disp:
                    if len([r for r in current if r['recorded']==disp['recorded']])>1:disp_issues.append('同刻处置记录冲突')
                    if disp['recount_id']!=(final['id'] if final else None) or not eligible or number(disp['confirmed_qty'])!=number(effective):disp_issues.append('处置依据未绑定当前有效实盘结果')
                    if not last_time or disp['recorded']<last_time:disp_issues.append('处置登记早于所依据实盘')
                    if disp['status'] not in ['待调查','待审批','已确认','复核无差异']:disp_issues.append('处置状态尚未映射')
                    if disp['owner_id'] not in self.people or not disp['evidence'].strip():disp_issues.append('处置人员或依据待核对')
                    if not disp['method'].strip():disp_issues.append('处置方式未登记')
                    if disp['status']=='复核无差异' and variance!=0:disp_issues.append('复核无差异与当前盘差不符')
                confirmed=bool(disp and not disp_issues and disp['status'] in ['已确认','复核无差异'])
                flags=['all']+(['uncounted'] if not has_qty else [])+(['unknown'] if errors else [])+(['variance'] if eligible and variance!=0 else [])+(['resolved'] if eligible and initial_delta!=0 and variance==0 else [])+(['pending'] if disp_issues or eligible and variance!=0 and not confirmed else [])
                sources=ref('stocktake_runs',[run])+ref('stocktake_lines',[line])+ref('stocktake_recounts',recounts)+ref('stocktake_dispositions',dispositions)+ref('materials',[material] if material else [])
                if lot:sources+=ref('inventory_opening',lot['_opening'])+ref('inventory_movements',lot['_moves'])+ref('inventory_status_events',lot['_events'])
                sources+=ref('inventory_movements',moving)
                out={**line,'run_kind':run['kind'],'book_at':run['book_at'],'material':material.get('name','档案缺失'),'book_qty':bookqty,'ledger_state':lot['state'] if lot else '未知','effective_qty':effective if eligible else None,'initial_delta':initial_delta,'variance':variance,'eligible':eligible,'confirmed':confirmed,'basis_id':final['id'] if final else line['id'],'recount_count':len(active),'disposition_state':disp['status'] if disp else '未登记','issues':unique(errors),'disposition_issues':unique(disp_issues),'flags':flags,'recounts':recounts,'dispositions':dispositions,'sources':supply.unique_refs(sources),'ledger_timeline':lot['_timeline'] if lot else [],'opening_qty':lot['opening_qty'] if lot else None,'period_movements':moving}
                rr.append(out);self.rows.append(out);self.index[line['id']]=out
            self.runs.append({**run,'owner':self.people.get(run['owner_id'],{}).get('name','档案缺失'),'issues':issues,'unplanned_lots':[supply.clean(x) for x in uncovered],'ledger_scope_lots':len(scope_lots),'planned_lots':len(plan_keys),'rows':rr})
    def selected(self,f):
        return [r for r in self.rows if (not f['run'] or r['run_id']==f['run']) and (not f['unit'] or r['unit']==f['unit']) and f['stage'] in r['flags'] and (not f['q'] or f['q'].lower() in ' '.join(str(r.get(k) or '') for k in ['id','material_id','material','lot','location']).lower())]
    def detail(self,key,f):
        row=self.index.get(key)
        if row is None or key not in {r['id'] for r in self.selected(f)}:raise ObjectDoesNotExist()
        return {**row,'run':next({k:v for k,v in run.items() if k!='rows'} for run in self.runs if run['id']==row['run_id'])}

def summary(rows):
    units=[]
    for run_id,unit in sorted({(r['run_id'],r['unit']) for r in rows}):
        valid=[r for r in rows if r['run_id']==run_id and r['unit']==unit and r['eligible']]
        units.append({'run_id':run_id,'unit':unit,'comparable':len(valid),'initial_abs':float(sum((abs(Decimal(str(r['initial_delta']))) for r in valid),Decimal(0))),'final_abs':float(sum((abs(Decimal(str(r['variance']))) for r in valid),Decimal(0))),'gain':float(sum((Decimal(str(r['variance'])) for r in valid if r['variance']>0),Decimal(0))),'loss':float(-sum((Decimal(str(r['variance'])) for r in valid if r['variance']<0),Decimal(0)))})
    for u in units:
        if not u['comparable']:
            for key in ['initial_abs','final_abs','gain','loss']:u[key]=None
    return {'planned':len(rows),'counted':sum(r['initial_qty'] is not None for r in rows),'comparable':sum(r['eligible'] for r in rows),'differences':sum('variance' in r['flags'] for r in rows),'uncounted':sum('uncounted' in r['flags'] for r in rows),'unknown':sum('unknown' in r['flags'] for r in rows),'resolved':sum('resolved' in r['flags'] for r in rows),'pending':sum('pending' in r['flags'] for r in rows),'units':units}
