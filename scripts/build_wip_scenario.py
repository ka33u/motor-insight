"""Detailed physical mock journal against existing batches/SNs, no DB writes."""
import os,sys,json
from pathlib import Path
from datetime import datetime,timedelta
from collections import defaultdict,Counter
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings')
import django;django.setup()
from app import analytics,wip_flow as eng
from app.schema import SCHEMAS
raw=analytics.tables();tables={k:[] for k in eng.TABLES};cases={};roots=[r for r in raw['batches'] if r['kind'] in ['定子','转子']]
wos={w['id']:w for w in raw['work_orders']};employees=[e['id'] for e in raw['employees']];rootidx={r['id']:r for r in roots}
operations=defaultdict(list)
for o in raw['operations']:
    if o.get('object_type')=='生产批次' and o.get('status')=='完成' and eng.clock(o.get('finished')):operations[o['object_id']].append(o)
def stamp(t):return t.isoformat(timespec='seconds')
def moment(t):return datetime.fromisoformat(t)
locations={}
def location(key,name,kind='生产缓冲',process=None):
    locations[key]=dict(id=key,name=name,workshop='模拟'+('返工检验区' if kind in ['返工区','隔离区'] else '制造车间'),kind=kind,process=process,note='合成位置，非现场实际库位。');tables['wip_locations'].append(locations[key])
location('ZW.LOC.000','基准暂存');location('ZW.LOC.090','交接复核暂存');location('ZW.LOC.091','返工待处理','返工区');location('ZW.LOC.092','质量隔离','隔离区');location('ZW.LOC.098','已登记装配耗用','装配耗用');location('ZW.LOC.099','已登记报废','报废登记')
processes=sorted({o['process'] for oo in operations.values() for o in oo});process_locs={p:f'ZW.LOC.{i:03d}' for i,p in enumerate(processes,1)}
for p,key in process_locs.items():location(key,p+'后暂存',process=p)
state={};root_lot={};at_lot={};lotnum=0;eventnum=0;seq=Counter();first_transfer={}
def lot(root,at,tag):
    global lotnum
    lotnum+=1;key=f'ZW.L.{at[:10].replace("-","")}.{lotnum:06d}'
    tables['wip_lots'].append(dict(id=key,product_id=wos[root['work_order_id']]['product_id'],kind=root['kind'],created=at,container=f'ZZX-WIP-{lotnum:06d}',note='模拟周转批次 '+tag));return key
def append(kind,outs,ins,at,reference,op=None,series=None,version=1,previous=None,status='登记',recorded=None,sequence=None):
    global eventnum
    if not series:eventnum+=1;series=f'ZW.E.{at[:10].replace("-","")}.{eventnum:06d}'
    identifier=series+f'.V{version:02d}'
    input_ids=list(dict.fromkeys(x[0] for x in outs));output_ids=list(dict.fromkeys(x[0] for x in ins))
    if sequence is None:
        seq[at,tuple(input_ids)]+=1;sequence=seq[at,tuple(input_ids)]
    h=dict(id=identifier,series=series,version=version,previous_id=previous,occurred=at,sequence=sequence,recorded=recorded or at,status=status,kind=kind,input_lots=','.join(input_ids),output_lots=','.join(output_ids),line_count=len(outs)+len(ins),sender_id=employees[eventnum%len(employees)],receiver_id=employees[(eventnum+1)%len(employees)],operation_id=op,reference=reference,note='完整模拟登记；只核对流转，不作为质量批准。')
    tables['wip_event_versions'].append(h)
    for side,rows in [('出',outs),('入',ins)]:
        for i,x in enumerate(rows,1):tables['wip_event_lines'].append(dict(id=f'{identifier}.{"O" if side=="出" else "I"}.{i:03d}',event_id=identifier,side=side,lot_id=x[0],location_id=x[1],root_batch_id=x[2],qty=x[3],unit_id=x[4] if len(x)>4 else None,note='装配耗用对应已有SN' if len(x)>4 else '原批次份额，单位件'))
    return h
def transform(kind,inputs,outputs,at,reference,op=None):
    outs=[(l,at_lot[l],r,q) for l in inputs for r,q in state[l].items() if q>0]
    ins=[(l,loc,r,q) for l,loc,shares in outputs for r,q in shares.items() if q>0]
    h=append(kind,outs,ins,at,reference,op)
    for l in inputs:state[l]={}
    for l,loc,shares in outputs:
        state[l]=dict(shares);at_lot[l]=loc
        for r,q in shares.items():
            if q>0:root_lot[r]=l
    return h
for i,r in enumerate(roots,1):
    l=lot(r,r['created'],'完整基准');state[l]={r['id']:r['qty']};root_lot[r['id']]=l;at_lot[l]='ZW.LOC.000'
    tables['wip_openings'].append(dict(id=f'ZW.O.{i:06d}',root_batch_id=r['id'],lot_id=l,location_id='ZW.LOC.000',qty=r['qty'],occurred=r['created'],recorded=r['created'],owner_id=employees[i%len(employees)],reference='模拟原批次基准 '+r['id'],note='基准等于原批次登记件数；非实际实盘。'))
    for j,o in enumerate(sorted(operations[r['id']],key=lambda x:x['finished'])):
        at=o['finished'];h=transform('工序交接',[l],[(l,process_locs[o['process']],dict(state[l]))],at,'模拟交接参考 '+o['id'],o['id'])
        if j==0:first_transfer[r['id']]=h
    if i%10==0 and operations[r['id']]:
        last=max(o['finished'] for o in operations[r['id']]);t=moment(last)+timedelta(minutes=1);q=r['qty']//2
        a=lot(r,stamp(t),'拆分A');b=lot(r,stamp(t),'拆分B');loc=at_lot[l]
        transform('拆批',[l],[(a,loc,{r['id']:q}),(b,loc,{r['id']:r['qty']-q})],stamp(t),'模拟拆批，保留来源份额')
        t+=timedelta(minutes=1);m=lot(r,stamp(t),'合回新批');transform('合批',[a,b],[(m,loc,{r['id']:r['qty']})],stamp(t),'模拟合批，不复用父批编号')
    if i%23==0:
        l=root_lot[r['id']];loc=at_lot[l];t=moment(max(o['finished'] for o in operations[r['id']]))+timedelta(minutes=5)
        transform('返工转入',[l],[(l,'ZW.LOC.091',dict(state[l]))],stamp(t),'模拟返工转入')
        transform('返工返回',[l],[(l,loc,dict(state[l]))],stamp(t+timedelta(minutes=15)),'模拟返工返回；不增加整机产出')
    if i%31==0:
        l=root_lot[r['id']];loc=at_lot[l];t=moment(max(o['finished'] for o in operations[r['id']]))+timedelta(minutes=25)
        transform('隔离转入',[l],[(l,'ZW.LOC.092',dict(state[l]))],stamp(t),'模拟隔离位置')
        transform('隔离解除',[l],[(l,loc,dict(state[l]))],stamp(t+timedelta(minutes=10)),'模拟离开隔离区，不替代质量放行')
# Cross-WO merge for compatible roots, before the earliest assembly consumption.
groups=defaultdict(list)
for r in roots:groups[wos[r['work_order_id']]['product_id'],r['kind']].append(r)
pair=next(v[:2] for v in groups.values() if len(v)>1 and v[0]['kind']=='定子');a,b=pair
la,lb=root_lot[a['id']],root_lot[b['id']];at=stamp(max(moment(x['finished']) for r in pair for x in operations[r['id']])+timedelta(hours=1));merged=lot(a,at,'跨工单来源份额')
transform('合批',[la,lb],[(merged,at_lot[la],{a['id']:a['qty'],b['id']:b['qty']})],at,'模拟跨工单合批；配置相同，保留原批次各自份额')
cases[a['id']]='同配置跨工单合批，整箱只计一次、每个工单保留份额';cases[b['id']]=cases[a['id']]
for u in sorted(raw['units'],key=lambda x:(x['assembly_at'],x['id'])):
    for field in ['stator_batch','rotor_batch']:
        root=u[field];l=root_lot[root];loc=at_lot[l];shares=state[l];assert shares[root]>0
        outs=[(l,loc,r,q) for r,q in shares.items() if q>0];retained=dict(shares);retained[root]-=1
        ins=[(l,'ZW.LOC.098',root,1,u['id'])]+[(l,loc,r,q) for r,q in retained.items() if q>0]
        append('装配耗用',outs,ins,u['assembly_at'],'模拟耗用依据已有装配 '+u['id']);state[l]=retained
assert all(sum(q.values())==0 for q in state.values())
# Deliberate, importable defects and version edge cases. Original facts untouched.
chosen=[r for r in roots if r['id'] not in {a['id'],b['id']}][:14]
def header_rows(h):return [x for x in tables['wip_event_lines'] if x['event_id']==h['id']]
def revised(root,kind='bad',status='登记',registered='2026-09-30T08:00:00'):
    h=first_transfer[root['id']];rows=header_rows(h)
    out=[(x['lot_id'],x['location_id'],x['root_batch_id'],x['qty']) for x in rows if x['side']=='出']
    ins=[(x['lot_id'],x['location_id'],x['root_batch_id'],x['qty']-(1 if kind=='bad' else 0)) for x in rows if x['side']=='入']
    v=append(h['kind'],out,ins,h['occurred'],'模拟完整版本更正',h['operation_id'],h['series'],2,h['id'],status,registered,h['sequence']);return h,v
revised(chosen[0]);cases[chosen[0]['id']]='最新完整版本份额不平，不回退首版'
old,bad=revised(chosen[1]);good=append(old['kind'],[(x['lot_id'],x['location_id'],x['root_batch_id'],x['qty']) for x in header_rows(old) if x['side']=='出'],[(x['lot_id'],x['location_id'],x['root_batch_id'],x['qty']) for x in header_rows(old) if x['side']=='入'],old['occurred'],'模拟纠正完整版本',old['operation_id'],old['series'],3,bad['id'],'登记','2026-09-30T08:01:00',old['sequence']);cases[chosen[1]['id']]='坏版后完整更正，按新版一次应用'
revised(chosen[2],kind='good',status='作废');cases[chosen[2]['id']]='最新撤销使后续交接前提缺失，位置需复核'
revised(chosen[3],registered='2026-10-02T08:00:00');cases[chosen[3]['id']]='截止后坏版尚不可知，保留当时有效版'
revised(chosen[4],status='草稿');cases[chosen[4]['id']]='未发布草稿不影响现有登记'
h=first_transfer[chosen[5]['id']];h['line_count']+=1;cases[chosen[5]['id']]='完整明细行数缺一行'
opening=next(x for x in tables['wip_openings'] if x['root_batch_id']==chosen[6]['id']);opening['qty']-=1;cases[chosen[6]['id']]='基准与原批次件数不平'
tables['wip_openings']=[x for x in tables['wip_openings'] if x['root_batch_id']!=chosen[7]['id']];cases[chosen[7]['id']]='有原批次但缺基准，未知不填零'
for index,conflict in [(8,True),(9,False)]:
    r=chosen[index];h=first_transfer[r['id']];l=header_rows(h)[0]['lot_id'];loc=next(x['location_id'] for x in header_rows(h) if x['side']=='入')
    append('工序交接',[(l,loc,r['id'],r['qty'])],[(l,'ZW.LOC.090',r['id'],r['qty'])],h['occurred'],'模拟同刻明确交接',sequence=1 if conflict else 2)
    append('工序交接',[(l,'ZW.LOC.090',r['id'],r['qty'])],[(l,loc,r['id'],r['qty'])],h['occurred'],'模拟复核后返回',sequence=2 if conflict else 3)
    cases[r['id']]='同刻同顺序冲突' if conflict else '同刻明确顺序，可核对后返回'
h=first_transfer[chosen[10]['id']];rows=header_rows(h);incoming=next(x for x in rows if x['side']=='入');incoming['qty']+=1;cases[chosen[10]['id']]='交接入向多一件，守恒失败'
badroot=chosen[11];h=next(v for v in tables['wip_event_versions'] if v['kind']=='装配耗用' and any(x['root_batch_id']==badroot['id'] for x in header_rows(v)))
line=next(x for x in header_rows(h) if x.get('unit_id'));line['unit_id']=next(u['id'] for u in raw['units'] if u['stator_batch']!=badroot['id'] and u['rotor_batch']!=badroot['id']);cases[badroot['id']]='耗用引用已有但属于别批的SN'
r=chosen[12];h=first_transfer[r['id']];badlot=lot(r,h['occurred'],'故意错配置');tables['wip_lots'][-1]['product_id']=next(p['id'] for p in raw['products'] if p['id']!=wos[r['work_order_id']]['product_id']);h['output_lots']=badlot
for line in header_rows(h):
    if line['side']=='入':line['lot_id']=badlot
cases[r['id']]='周转档案配置与原批次不一致'
r=chosen[13];consumptions=[v for v in tables['wip_event_versions'] if v['kind']=='装配耗用' and any(x['root_batch_id']==r['id'] for x in header_rows(v))];last=max(consumptions,key=lambda v:v['occurred']);tables['wip_event_versions'].remove(last);tables['wip_event_lines']=[x for x in tables['wip_event_lines'] if x['event_id']!=last['id']];cases[r['id']]='已有装配SN但最后耗用漏登记，不能推定仍在缓冲区'
scenario=dict(as_of=analytics.AS_OF,schema_version='motor-source-v1',notice='全部为合成在制流转登记。关联原有400个定转子批次和4500台SN，基准、移交、拆合、返工、隔离与耗用分别留证。完整版本保留更正、撤销、草稿、未来和故意错误，不改原订单、工单、批次、报工或SN。实物位置仅是模拟登记；报工不作为库存流水，定转子件数不加成电机台数。',schemas={k:SCHEMAS[k] for k in eng.TABLES},tables=tables,cases=cases,cross_work_order_roots=[a['id'],b['id']])
(ROOT/'data/wip_scenario.json').write_text(json.dumps(scenario,ensure_ascii=False,indent=2))
w=eng.Wip(raw|tables);hist=eng.Wip(raw|tables,'2026-09-20T18:00:00')
healthy_cases=[chosen[i]['id'] for i in [1,3,4,9]]+[a['id'],b['id']]
assert all(not w.index[k]['issues'] for k in healthy_cases),{k:w.index[k]['issues'] for k in healthy_cases}
assert all(w.index[r['id']]['wip_qty'] is None for i,r in enumerate(chosen) if i not in [1,3,4,9])
assert not w.global_issues
report=dict(tables={k:len(v) for k,v in tables.items()},summary=eng.summary(w.rows),historical_summary=eng.summary(hist.rows),cross_work_order_roots=scenario['cross_work_order_roots'],cases={k:dict(case=v,state=w.index[k]['state'],issues=w.index[k]['issues']) for k,v in cases.items()},original_component_roots=len(roots),original_assembly_kits=200,original_units=4500)
(ROOT/'data/wip_scenario_build.json').write_text(json.dumps(report,ensure_ascii=False,indent=2));print(json.dumps({k:v for k,v in report.items() if k!='cases'},ensure_ascii=False,indent=2))
