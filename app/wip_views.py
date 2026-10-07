import hashlib,json
from functools import lru_cache
from pathlib import Path
from datetime import date
from collections import defaultdict
from django.conf import settings
from django.db import transaction
from . import wip_flow as eng,wip_comparison as compare,analytics,access
from .models import Record,AuditEvent
from .views import api,reply
from .import_review import ReviewConflict
from .quality_views import csv_reply
from .trace_cases import capture_sources
from .file_sharing import account_receipt

FILES=['wip_flow.py','wip_views.py','wip_comparison.py','schema.py']
def rule_hash():
    h=hashlib.sha256()
    for name in FILES:h.update((Path(settings.BASE_DIR)/'app'/name).read_bytes())
    return h.hexdigest()
def filters(q):
    keys=['family','product_id','work_order_id','kind','from','to','q','stage','as_of','known_as_of']
    if set(q)-set(keys+['page','receipt']):raise ValueError('在制筛选字段无效')
    if hasattr(q,'getlist') and any(len(q.getlist(k))!=1 for k in q):raise ValueError('在制筛选不可重复')
    f={k:q.get(k,'').strip() for k in keys};f['stage']=q.get('stage','all');f['as_of']=q.get('as_of',analytics.AS_OF)
    f['known_as_of']=q.get('known_as_of',f['as_of'])
    if f['stage'] not in eng.STATES or f['kind'] not in ['', '定子','转子'] or any(len(v)>150 for v in f.values()):raise ValueError('在制状态、类型或筛选长度无效')
    if not eng.clock(f['as_of']) or f['as_of']>analytics.AS_OF:raise ValueError('在制截止须为标准本地时间，且不晚于模拟截止')
    if not eng.clock(f['known_as_of']) or not f['as_of']<=f['known_as_of']<=analytics.AS_OF:raise ValueError('登记截止须为标准本地时间，不早于业务截止且不晚于模拟截止')
    for k in ['from','to']:
        if f[k] and (date.fromisoformat(f[k]).isoformat()!=f[k] or f[k]>f['as_of'][:10]):raise ValueError('批次建立日期须为标准日期且不晚于在制截止')
    if f['from'] and f['to'] and f['from']>f['to']:raise ValueError('批次建立日期倒序')
    return f
def page(q):
    p=q.get('page','1')
    if not p.isdecimal() or not 1<=int(p)<=100000:raise ValueError('页码无效')
    return int(p)
@lru_cache(maxsize=4)
def current(revision,cutoff,rules,known_as_of=None):return eng.Wip(cutoff=cutoff,known_cutoff=known_as_of)
def context(request,required=False):
    f=filters(request.GET);page(request.GET);rev=tuple(analytics.revision());rules=rule_hash();d=current(rev,f['as_of'],rules,f['known_as_of'])
    if f['family'] and f['family'] not in {p['family'] for p in d.data.get('products',[])}:raise ValueError('产品族不存在')
    for key,ds in [('product_id','products'),('work_order_id','work_orders')]:
        if f[key] and f[key] not in d.idx[ds]:raise ValueError('配置或工单不存在')
    receipt=hashlib.sha256(json.dumps([f,rev,rules,account_receipt(request.user)],ensure_ascii=False,sort_keys=True).encode()).hexdigest()
    given=request.GET.get('receipt')
    if required and not given:raise ValueError('请先读取在制范围')
    if given and given!=receipt:raise ReviewConflict('在制来源、截止、规则、账号或范围变化，请重新读取')
    if rev!=tuple(analytics.revision()):raise ReviewConflict('在制读取期间来源变化，请重试')
    cohort=d.cohort(f);rows=sorted([r for r in cohort if f['stage']=='all' or r['state']==f['stage']],key=lambda r:(r['state'] not in ['attention','missing'],r['created'] or '',r['id']))
    return d,f,receipt,cohort,rows
def response(data):
    r=reply(data);r['Cache-Control']='no-store';return r
def selected(rows,key):
    row=next((r for r in rows if r['id']==key),None)
    if row is None:raise Record.DoesNotExist()
    return row
def public(r):
    return {k:v for k,v in r.items() if k not in ['expected_consumption_sn','missing_consumption_sn']}|dict(expected_consumption_count=len(r['expected_consumption_sn']),missing_consumption_count=len(r['missing_consumption_sn']),state_label=eng.STATES[r['state']])
def positions(rows):
    groups=defaultdict(list)
    for r in rows:
        for p in r['positions']:groups[r['kind'],p['location_id']].append((r,p))
    return [dict(kind=kind,location_id=loc,name=parts[0][1]['location'],process=parts[0][1]['process'],share_qty=sum(p['qty'] for r,p in parts),containers=len({p['lot_id'] for r,p in parts}),roots=len(parts),max_dwell_hours=max(p['dwell_hours'] for r,p in parts)) for (kind,loc),parts in sorted(groups.items())]
def plan_context(d,f):
    # This explicitly separate context uses planned-start dates, not a physical
    # inventory estimate. No planned quantity is turned into WIP.
    has_roots={r['work_order_id'] for r in d.roots.values()};out=[]
    for w in d.data.get('work_orders',[]):
        p=d.idx['products'].get(w.get('product_id'),{});start=w.get('planned_start','')
        if not start or start>f['as_of'][:10] or w['id'] in has_roots:continue
        if any(f[k] and f[k]!=v for k,v in [('family',p.get('family')),('product_id',w.get('product_id')),('work_order_id',w['id'])]):continue
        if f['from'] and start<f['from'] or f['to'] and start>f['to']:continue
        if f['q'] and f['q'].lower() not in (w['id']+' '+w.get('product_id','')).lower():continue
        out.append(dict(id=w['id'],product_id=w.get('product_id'),planned_start=start,status=w.get('status')))
    return dict(rows=out,total=len(out),date_basis='独立计划参照：按工单计划开工日筛选；只表示未见截止前原批次，不推算在制数量。')

@api()
@transaction.atomic
def board(request):
    d,f,s,cohort,rows=context(request);p=page(request.GET);plan=plan_context(d,f)
    return response(dict(filters=f,receipt=s,as_of=d.cutoff,known_as_of=d.known_cutoff,time_note=eng.TIME_NOTE,summary=eng.summary(cohort),positions=positions(cohort),rows=[public(r) for r in rows[(p-1)*25:p*25]],total=len(rows),page=p,size=25,
        stages=eng.STATES,facets={k:len(cohort) if k=='all' else sum(r['state']==k for r in cohort) for k in eng.STATES},note=eng.NOTE,global_issues=d.global_issues,
        plan_context=plan,options=dict(families=sorted({x.get('family','') for x in d.data.get('products',[])}),products=sorted(d.idx['products']),work_orders=sorted(d.idx['work_orders'])),data_as_of=analytics.AS_OF,
        replay_presets=['2026-09-20T18:00:00','2026-09-22T12:00:00',analytics.AS_OF]))

@api()
@transaction.atomic
def detail(request,key):
    d,f,s,cohort,rows=context(request,True);r=selected(rows,key)
    events=[];related=[e for e in d.events if key in e['roots'] or key in e['history_roots']]
    for e in sorted(related,key=lambda e:(e['occurred'] or '',e['sequence'] or 0,e['series'])):
        events.append(dict(series=e['series'],selected_id=e['header']['id'] if e['header'] else None,occurred=e['occurred'],sequence=e['sequence'],applied=e['applied'],future=e['future'],withdrawn=e['withdrawn'],issues=e['issues'],inputs=e['inputs'],outputs=e['outputs'],
            versions=[dict(header=h,selected=bool(e['header'] and h['id']==e['header']['id']),after_cutoff=bool((eng.clock(h.get('occurred')) and h['occurred']>d.cutoff) or (eng.clock(h.get('recorded')) and h['recorded']>d.known_cutoff)),after_business_cutoff=bool(eng.clock(h.get('occurred')) and h['occurred']>d.cutoff),after_known_cutoff=bool(eng.clock(h.get('recorded')) and h['recorded']>d.known_cutoff),lines=d.lines[h['id']]) for h in sorted(e['history'],key=lambda h:(h.get('recorded') or '',str(h.get('version'))))]))
    allocations=[a for a in d.data.get('allocations',[]) if a.get('work_order_id')==r['work_order_id'] and a.get('effective','')<=d.cutoff[:10]]
    candidates=[]
    for a in allocations:
        line=d.idx['order_lines'].get(a.get('order_line_id'),{});order=d.idx['orders'].get(line.get('order_id'),{})
        if line:candidates.append(dict(allocation_id=a['id'],order_line_id=line['id'],order_id=line.get('order_id'),customer_id=order.get('customer_id')))
    sources=[x for x in d.evidence(key) if access.allowed(request.user,x['dataset'])]
    lots={l for e in related for l in e['inputs']+e['outputs']}|{x['lot_id'] for x in d.openings[key]}
    genealogy=[dict(lot_id=l,parents=d.parents[l]) for l in sorted(lots) if d.parents.get(l)]
    return response(dict(row=r|dict(state_label=eng.STATES[r['state']]),events=events,openings=d.openings[key],genealogy=genealogy,candidate_orders=candidates,
        units=[dict(id=sn,assembly_at=d.idx['units'][sn].get('assembly_at'),work_order_id=d.idx['units'][sn].get('work_order_id'),consumption_verified=(sn,r['kind']) in d.sn_used) for sn in r['expected_consumption_sn']],
        sources=sources,receipt=s,filters=f,as_of=d.cutoff,known_as_of=d.known_cutoff,time_note=eng.TIME_NOTE,note=eng.NOTE,
        order_boundary='工单分配只列候选订单；不把跨工单整箱数量归给一个订单，SN归属以既有有效分配另查。'))

@api()
@transaction.atomic
def evidence(request,key):
    d,f,s,cohort,rows=context(request,True);selected(rows,key);p=page(request.GET)
    sources=capture_sources({'sources':[x for x in d.evidence(key) if access.allowed(request.user,x['dataset'])]})
    return response(dict(rows=sources[(p-1)*40:p*40],total=len(sources),page=p,size=40,receipt=s,can_download_original=access.can_import(request.user)))

FIELDS=[('id','原生产批次'),('work_order_id','工单'),('product_id','配置'),('kind','半成品类型'),('created','原批次建立'),('state_label','核对状态'),('baseline_qty','有效基准件数'),('wip_qty','可核对在制件数'),('prefix_consumed_qty','有效前缀耗用件数'),('prefix_scrap_qty','有效前缀报废件数'),('unknown_remainder','前缀后未核定件数'),('expected_consumption_count','截止已装配SN引用数'),('missing_consumption_count','缺有效耗用SN数')]
def preface(d,f,s):return [['在制流转 · 全部合成模拟','业务截止',d.cutoff,'登记截止',d.known_cutoff,'来源截止',analytics.AS_OF],['筛选',json.dumps(f,ensure_ascii=False)],['依据',s],['说明',eng.NOTE+' '+eng.TIME_NOTE]]
@api()
@transaction.atomic
def export(request):
    d,f,s,cohort,rows=context(request,True);values=[public(r) for r in rows]
    out=preface(d,f,s)+[[label for key,label in FIELDS]+['待核查事项']]+[[r.get(k) for k,label in FIELDS]+['；'.join(r['issues'])] for r in values]
    AuditEvent.objects.create(action='wip.export',actor=request.user.username,object_type='WipFlow',object_id='root-cohort',detail={'filters':f,'receipt':s,'rows':len(values),'business_facts_changed':False})
    result=csv_reply(out,'wip-root-cohort');result['Cache-Control']='no-store';return result
@api()
@transaction.atomic
def position_export(request):
    d,f,s,cohort,rows=context(request,True)
    fields=[('lot_id','周转批次'),('location_id','位置编码'),('location','位置'),('qty','本原批次份额件数'),('whole_lot_qty','整批已核定位置件数'),('root_count','整批来源数'),('entered_at','本位置进入'),('dwell_hours','位置自然停留小时')]
    out=preface(d,f,s)+[['原生产批次','工单','半成品类型']+[label for key,label in fields]]
    out += [[r['id'],r['work_order_id'],r['kind']]+[p.get(k) for k,label in fields] for r in rows for p in r['positions']]
    AuditEvent.objects.create(action='wip.position_export',actor=request.user.username,object_type='WipFlow',object_id='root-shares',detail={'filters':f,'receipt':s,'rows':len(out)-5,'business_facts_changed':False})
    result=csv_reply(out,'wip-position-shares');result['Cache-Control']='no-store';return result

def comparison_context(request):
    rev=tuple(analytics.revision());rules=rule_hash()
    d,f,s,cohort,rows=context(request,True)
    before=current(rev,d.cutoff,rules,d.cutoff)
    result=compare.comparison(before,d,rows)
    if rev!=tuple(analytics.revision()) or rules!=rule_hash():raise ReviewConflict('在制对照期间来源或规则变化，请重新读取')
    return d,f,s,rows,result

@api()
@transaction.atomic
def comparison(request):
    d,f,s,rows,result=comparison_context(request);p=page(request.GET)
    return response({k:v for k,v in result.items() if k not in ['all_rows','changed']}|dict(rows=result['changed'][(p-1)*25:p*25],total=len(result['changed']),page=p,size=25,receipt=s,filters=f))

@api()
@transaction.atomic
def comparison_detail(request,key):
    d,f,s,rows,result=comparison_context(request);selected(rows,key)
    r=next(x for x in result['all_rows'] if x['id']==key)
    return response(dict(row=r,as_of=d.cutoff,before_known_as_of=d.cutoff,after_known_as_of=d.known_cutoff,receipt=s,filters=f,note=result['note']))

@api()
@transaction.atomic
def comparison_export(request):
    d,f,s,rows,result=comparison_context(request)
    out=preface(d,f,s);out[3]=['对照说明',result['note']]
    columns=['原生产批次','工单','半成品','变化分类','左核对状态','右核对状态','左有效基准','右有效基准','左可核对在制','右可核对在制','同批次可比在制差','左前缀耗用','右前缀耗用','左前缀报废','右前缀报废','结果变化项','流转依据变化系列','左基准登记','右基准登记']
    out.append(columns)
    for r in result['all_rows']:
        a,b=r['before'],r['after']
        out.append([r['id'],r['work_order_id'],r['kind'],r['change_type'],a['state_label'],b['state_label'],a['baseline_qty'],b['baseline_qty'],a['wip_qty'],b['wip_qty'],r['wip_delta'],a['prefix_consumed_qty'],b['prefix_consumed_qty'],a['prefix_scrap_qty'],b['prefix_scrap_qty'],'；'.join(r['differences']),','.join(v['series'] for v in r['version_changes']),','.join(r['opening_before']),','.join(r['opening_after'])])
    AuditEvent.objects.create(action='wip.comparison_export',actor=request.user.username,object_type='WipFlow',object_id='registration-cutoffs',detail={'filters':f,'receipt':s,'rows':len(rows),'business_facts_changed':False,'before_known_as_of':d.cutoff,'after_known_as_of':d.known_cutoff})
    result=csv_reply(out,'wip-registration-comparison');result['Cache-Control']='no-store';return result
