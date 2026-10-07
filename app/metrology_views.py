"""Read-only calibration evidence, with scope/source/account bound exports."""
import hashlib,json
from collections import Counter,defaultdict
from datetime import date
from functools import lru_cache
from pathlib import Path
from django.conf import settings
from django.db import transaction
from . import metrology as eng,analytics,access
from .models import Record,AuditEvent
from .views import api,reply
from .quality_views import csv_reply
from .trace_cases import capture_sources
from .file_sharing import account_receipt
from .import_review import ReviewConflict
from .schema import SCHEMAS

def rule_hash():
    return hashlib.sha256(b''.join((Path(settings.BASE_DIR)/'app'/n).read_bytes() for n in ['metrology.py','metrology_views.py','schema.py'])).hexdigest()
def filters(q):
    keys=['stage','instrument_id','parameter','from','to','q','cal','impact','review','as_of','known_as_of']
    if set(q)-set(keys+['page','receipt']):raise ValueError('计量筛选字段无效')
    if hasattr(q,'getlist') and any(len(q.getlist(k))!=1 for k in q):raise ValueError('计量筛选不可重复')
    f={k:q.get(k,'').strip() for k in keys};f['as_of']=q.get('as_of',analytics.AS_OF);f['known_as_of']=q.get('known_as_of',f['as_of'])
    if any(len(v)>160 for v in f.values()):raise ValueError('计量筛选过长')
    for field,allowed in [('stage',eng.STAGES),('cal',eng.CAL_STATES),('impact',eng.IMPACT_STATES),('review',eng.REVIEW_STATES)]:
        if f[field] and f[field] not in allowed:raise ValueError('计量状态或环节无效')
    if not eng.clock(f['as_of']) or f['as_of']>analytics.AS_OF:raise ValueError('业务截止须为本地标准时间且不晚于模拟截止')
    if not eng.clock(f['known_as_of']) or not f['as_of']<=f['known_as_of']<=analytics.AS_OF:raise ValueError('登记截止须不早于业务截止且不晚于模拟截止')
    for key in ['from','to']:
        if f[key] and (date.fromisoformat(f[key]).isoformat()!=f[key] or f[key]>f['as_of'][:10]):raise ValueError('测量日期须为标准日期且不晚于业务截止')
    if f['from'] and f['to'] and f['from']>f['to']:raise ValueError('测量日期倒序')
    return f
def page(q):
    p=q.get('page','1')
    if not p.isdecimal() or not 1<=int(p)<=100000:raise ValueError('页码无效')
    return int(p)
@lru_cache(maxsize=4)
def current(rev,cutoff,rules,known):return eng.Metrology(cutoff=cutoff,known_cutoff=known)
def context(request,required=False):
    f=filters(request.GET);page(request.GET);rev=tuple(analytics.revision());rules=rule_hash();d=current(rev,f['as_of'],rules,f['known_as_of'])
    if f['instrument_id'] and f['instrument_id'] not in d.idx['metrology_instruments']:raise ValueError('仪器通道不存在')
    if f['parameter'] and f['parameter'] not in {r['parameter'] for r in d.rows}:raise ValueError('特性不存在')
    receipt=eng.digest([f,rev,rules,account_receipt(request.user)])
    given=request.GET.get('receipt')
    if required and not given:raise ValueError('请先读取计量范围')
    if given and given!=receipt:raise ReviewConflict('计量来源、规则、账号、截止或筛选变化，请重新读取')
    if rev!=tuple(analytics.revision()) or rules!=rule_hash():raise ReviewConflict('计量读取期间来源或规则变化，请重试')
    cohort=d.cohort(f)
    rows=sorted([r for r in cohort if (not f['cal'] or r['calibration_state']==f['cal']) and (not f['impact'] or r['impact_state']==f['impact']) and (not f['review'] or r['review_state']==f['review'])],key=lambda r:(r['voided'],r['impact_state'] not in ['matched','potential','unknown'],r['measured'],r['id']))
    return d,f,receipt,cohort,rows
def response(data):
    r=reply(data);r['Cache-Control']='no-store';return r
def selected(rows,key):
    r=next((r for r in rows if r['id']==key),None)
    if not r:raise Record.DoesNotExist()
    return r
def public(r):
    return {k:v for k,v in r.items() if k not in ['sources','sn_ids','batch_ids','work_order_ids']}|dict(sn_count=len(r['sn_ids']),batch_count=len(r['batch_ids']),calibration_label=eng.CAL_STATES[r['calibration_state']],impact_label=eng.IMPACT_STATES[r['impact_state']],review_label=eng.REVIEW_STATES[r['review_state']])
def allowed_sources(sources,user):return [s for s in eng.unique_sources(sources) if access.allowed(user,s['dataset'])]
def versions(groups,d):
    return [dict(series=g['series'],selected_id=g['selected']['id'] if g['selected'] else None,issues=g['issues'],rows=[dict(value=r,after_known_cutoff=bool(eng.clock(r.get('registered')) and r['registered']>d.known_cutoff),selected=bool(g['selected'] and r['id']==g['selected']['id'])) for r in g['history']]) for g in groups]

@api()
@transaction.atomic
def board(request):
    d,f,s,cohort,rows=context(request);p=page(request.GET)
    daily=defaultdict(list)
    for r in cohort:daily[r['measured'][:10]].append(r)
    return response(dict(filters=f,receipt=s,as_of=d.cutoff,known_as_of=d.known_cutoff,data_as_of=analytics.AS_OF,
        summary=eng.summary(cohort),selected_summary=eng.summary(rows),total=len(rows),page=p,size=25,rows=[public(r) for r in rows[(p-1)*25:p*25]],
        daily=[dict(date=k,summary=eng.summary(v)) for k,v in sorted(daily.items())],
        labels=dict(stages=eng.STAGES,cal=eng.CAL_STATES,impact=eng.IMPACT_STATES,review=eng.REVIEW_STATES),
        instruments=[dict(id=r['id'],name=r['name'],stage=r['stage'],parameter=r['parameter'],unit=r['unit']) for r in d.data.get('metrology_instruments',[])],
        parameters=sorted({r['parameter'] for r in d.rows if r['parameter']}),global_issues=d.global_issues,field_labels={field['name']:field['label'] for ds in eng.TABLES for field in SCHEMAS[ds]['fields']},
        note=eng.NOTE,time_note=eng.TIME_NOTE,order_note=eng.ORDER_NOTE))

@api()
@transaction.atomic
def detail(request,key):
    d,f,s,cohort,rows=context(request,True);r=selected(rows,key)
    groups=d.use_groups[(r['stage'],r['source_key'])];use=d.idx['metrology_uses'].get(r['use_id']);iid=use.get('instrument_id') if use else None
    instrument=d.idx['metrology_instruments'].get(iid)
    uid_history={h['id'] for g in groups for h in g['history']};reviews={g['series']:g for uid in uid_history for g in d.review_groups[uid]}
    down=d.downstream([r]);sources=allowed_sources(r['sources']+down['sources'],request.user)
    return response(dict(row=r|public(r),instrument=instrument,usage_versions=versions(groups,d),calibration_versions=versions(d.cal_groups[iid],d),
        rule_versions=versions(d.rule_groups[(r['stage'],r['parameter'],r['unit'])],d),notice_versions=versions(d.notice_groups[iid],d),review_versions=versions(reviews.values(),d),
        downstream={k:v for k,v in down.items() if k!='sources'},sources=sources,receipt=s,filters=f,note=eng.NOTE,time_note=eng.TIME_NOTE))

@api()
@transaction.atomic
def evidence(request,key):
    d,f,s,cohort,rows=context(request,True);r=selected(rows,key);p=page(request.GET);down=d.downstream([r])
    source=capture_sources({'sources':allowed_sources(r['sources']+down['sources'],request.user)})
    return response(dict(rows=source[(p-1)*40:p*40],total=len(source),page=p,size=40,receipt=s,can_download_original=access.can_import(request.user)))

@api()
@transaction.atomic
def instruments(request):
    d,f,s,cohort,rows=context(request,True);p=page(request.GET);by=defaultdict(list)
    for r in rows:
        if r['instrument_id']:by[r['instrument_id']].append(r)
    out=[]
    for i in d.data.get('metrology_instruments',[]):
        if f['instrument_id'] and i['id']!=f['instrument_id'] or f['stage'] and i['stage']!=f['stage']:continue
        if f['parameter'] and i['parameter']!=f['parameter']:continue
        if any(f[k] for k in ['from','to','cal','impact','review','q']) and i['id'] not in by:continue
        out.append(dict(instrument=i,summary=eng.summary(by.get(i['id'],[])),calibration_series=len(d.cal_groups[i['id']]),no_use_in_scope=i['id'] not in by))
    out.sort(key=lambda x:x['instrument']['id'])
    return response(dict(rows=out[(p-1)*25:p*25],total=len(out),page=p,size=25,receipt=s,note='原计量工具档案另列为档案通道；未推断其历史使用或校准。通道校准系列数包含更正历史，不是当前有效校准数。'))

@api()
@transaction.atomic
def comparison(request):
    d,f,s,cohort,rows=context(request,True);rev=tuple(analytics.revision());old=current(rev,d.cutoff,rule_hash(),d.cutoff);p=page(request.GET)
    fields=['required','use_id','instrument_id','calibration_id','calibration_state','impact_state','notice_ids','review_state'];changed=[]
    for r in rows:
        before=old.index.get(r['id'])
        diff=[k for k in fields if not before or before[k]!=r[k]]
        if diff:changed.append(dict(id=r['id'],measured=r['measured'],differences=diff,before=public(before) if before else None,after=public(r)))
    if rev!=tuple(analytics.revision()):raise ReviewConflict('登记对照期间来源变化')
    return response(dict(total=len(changed),rows=changed[(p-1)*25:p*25],page=p,size=25,receipt=s,before_known_as_of=d.cutoff,after_known_as_of=d.known_cutoff,scope_count=len(rows),note='同一业务截止、当前筛选后的源测量集合，比较当时登记与后来登记。仅新台账具备登记版本；原测量及规范仍为当前已导入值，变化不代表新增缺陷或产量变化。'))

FIELDS=[('id','源测量标识'),('measured','测量时间'),('parameter','特性'),('value','源实测值'),('unit','单位'),('unit_basis','单位来源'),('source_result','原测量结论'),('source_context_result','原检验结论'),('required','模拟要求需校准'),('use_id','使用登记'),('instrument_id','核定仪器通道'),('calibration_id','选定校准登记'),('calibration_label','校准登记状态'),('impact_label','登记影响状态'),('review_label','核查登记状态'),('receipt_id','到货行')]
@api()
@transaction.atomic
def export(request):
    d,f,s,cohort,rows=context(request,True)
    out=[['计量校准 · 全部合成模拟','业务截止',d.cutoff,'登记截止',d.known_cutoff],['筛选',json.dumps(f,ensure_ascii=False)],['范围依据',s],['说明',eng.NOTE+' '+eng.TIME_NOTE+' '+eng.ORDER_NOTE]]
    out.append([label for key,label in FIELDS]+['影响登记','批次','SN','工单','待核查事项'])
    for r in rows:
        out.append([public(r).get(k) for k,label in FIELDS]+[','.join(r['notice_ids']),','.join(r['batch_ids']),','.join(r['sn_ids']),','.join(r['work_order_ids']),'；'.join(r['issues'])])
    AuditEvent.objects.create(action='metrology.export',actor=request.user.username,object_type='Metrology',object_id='measurement-cohort',detail={'filters':f,'receipt':s,'rows':len(rows),'business_facts_changed':False})
    result=csv_reply(out,'metrology-measurement-cohort');result['Cache-Control']='no-store';return result
