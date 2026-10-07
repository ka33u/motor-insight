"""Current instrument queue, exact calibration evidence, and bound downloads."""
import csv,io,json,hashlib
from pathlib import Path
from django.conf import settings
from django.db import transaction
from . import analytics,access,metrology as reg,metrology_views as registers,metrology_evidence as eng
from .views import api,reply
from .models import Record,AuditEvent
from .file_sharing import account_receipt
from .import_review import ReviewConflict
from .trace_cases import capture_sources
from .quality_views import csv_reply
from .device_file_views import download_response
from .schema import SCHEMAS

def rules():
    h=hashlib.sha256()
    for name in ['metrology_evidence.py','metrology_evidence_views.py','schema.py','device_files.py','file_sharing.py']:
        h.update((Path(settings.BASE_DIR)/'app'/name).read_bytes())
    h.update(registers.rule_hash().encode());return h.hexdigest()
def filters(q):
    fields=['stage','instrument_id','q','state','due','archives','window','as_of','known_as_of']
    if set(q)-set(fields+['page','receipt']):raise ValueError('证书范围字段无效')
    if hasattr(q,'getlist') and any(len(q.getlist(k))!=1 for k in q):raise ValueError('证书范围不可重复')
    f={k:q.get(k,'').strip() for k in fields};f['archives']=q.get('archives','0');f['window']=q.get('window','30');f['as_of']=q.get('as_of',analytics.AS_OF);f['known_as_of']=q.get('known_as_of',f['as_of'])
    if any(len(v)>160 for v in f.values()):raise ValueError('证书筛选过长')
    if f['stage'] not in ['',*reg.STAGES] or f['state'] not in ['',*eng.STATES] or f['due'] not in ['',*eng.DUE] or f['archives'] not in ['0','1']:raise ValueError('证书环节、状态或档案选项无效')
    if not f['window'].isascii() or not f['window'].isdecimal() or not 1<=int(f['window'])<=365:raise ValueError('提醒窗口须为1至365个自然天')
    if not reg.clock(f['as_of']) or f['as_of']>analytics.AS_OF or not reg.clock(f['known_as_of']) or not f['as_of']<=f['known_as_of']<=analytics.AS_OF:raise ValueError('业务及登记截止须为标准本地时间且不晚于模拟截止')
    return f
def stamp(f,rev,user,d):return reg.digest([f,rev,rules(),account_receipt(user),d.observations()])
def context(request,required=False):
    f=filters(request.GET);registers.page(request.GET);rev=tuple(analytics.revision());m=registers.current(rev,f['as_of'],registers.rule_hash(),f['known_as_of'])
    if f['instrument_id'] and f['instrument_id'] not in m.idx['metrology_instruments']:raise ValueError('仪器通道不存在')
    d=eng.Evidence(m,resolve=eng.resolver(request.user),window=int(f['window']));s=stamp(f,rev,request.user,d);given=request.GET.get('receipt')
    if required and not given:raise ValueError('请先读取证书范围')
    if given and given!=s:raise ReviewConflict('范围、来源、原件、规则或账号权限变化，请重新读取')
    if rev!=tuple(analytics.revision()):raise ReviewConflict('证书读取期间来源变化')
    cohort=d.cohort(f);rows=sorted([r for r in cohort if (not f['state'] or r['evidence_state']==f['state']) and (not f['due'] or r['due_state']==f['due'])],key=lambda r:(r['evidence_state']=='consistent',r['due_state']=='later',r['hours_to_expiry'] is None,r['hours_to_expiry'] or 0,r['id']))
    return d,f,s,rev,cohort,rows
def finish(request,d,f,s,rev):
    again=eng.Evidence(d.registry,data=d.data,resolve=eng.resolver(request.user),window=d.window)
    if tuple(analytics.revision())!=rev or stamp(f,rev,request.user,again)!=s:raise ReviewConflict('读取期间原件、账号、来源或规则变化，请重新核查')
def response(value):
    r=reply(value);r['Cache-Control']='no-store';return r
def selected(rows,key):return registers.selected(rows,key)
def fields():return {ds:{f['name']:f['label'] for f in SCHEMAS[ds]['fields']} for ds in ('metrology_instruments','metrology_calibrations',*eng.TABLES)}

@api()
@transaction.atomic
def board(request):
    d,f,s,rev,cohort,rows=context(request);p=registers.page(request.GET);finish(request,d,f,s,rev)
    return response(dict(filters=f,receipt=s,summary=eng.summary(cohort),selected_summary=eng.summary(rows),rows=[eng.public(r) for r in rows[(p-1)*25:p*25]],total=len(rows),page=p,size=25,
        options=[dict(id=i['id'],name=i['name'],stage=i['stage']) for i in d.registry.data['metrology_instruments']],states=eng.STATES,due_states=eng.DUE,stages=reg.STAGES,
        excluded_archives=sum(i['stage']=='档案' for i in d.registry.data['metrology_instruments']) if f['archives']=='0' else 0,
        as_of=d.cutoff,known_as_of=d.known,data_as_of=analytics.AS_OF,can_archive=access.role(request.user) in ['admin','quality'],note=eng.NOTE,time_note=eng.TIME_NOTE))

@api()
@transaction.atomic
def detail(request,key):
    d,f,s,rev,cohort,rows=context(request,True);r=selected(rows,key)
    calids={h['id'] for g in d.registry.cal_groups[key] for h in g['history']};inspections=[d.inspections[k] for k in sorted(calids) if k in d.inspections]
    source=reg.unique_sources(r['sources']+[x for v in inspections for x in v['sources']]);finish(request,d,f,s,rev)
    return response(dict(row=eng.public(r),calibration_versions=registers.versions(d.registry.cal_groups[key],d.registry),inspections=inspections,
        sources=[x for x in source if access.allowed(request.user,x['dataset'])],receipt=s,filters=f,field_labels=fields(),note=eng.NOTE,time_note=eng.TIME_NOTE))

@api()
@transaction.atomic
def evidence(request,key):
    d,f,s,rev,cohort,rows=context(request,True);r=selected(rows,key);p=registers.page(request.GET)
    related={h['id'] for g in d.registry.cal_groups[key] for h in g['history']};sources=reg.unique_sources(r['sources']+[x for k in related if k in d.inspections for x in d.inspections[k]['sources']])
    sources=capture_sources({'sources':[x for x in sources if access.allowed(request.user,x['dataset'])]});finish(request,d,f,s,rev)
    return response(dict(rows=sources[(p-1)*40:p*40],total=len(sources),page=p,size=40,receipt=s,can_download_original=access.can_import(request.user)))

@api()
def template(request):
    out=io.StringIO();csv.writer(out).writerow(eng.HEADERS)
    return download_response(('\ufeff'+out.getvalue()).encode(),'校准证明_模拟单通道CSV表头.csv','text/csv; charset=utf-8')

@api()
@transaction.atomic
def original(request,key,calibration_id):
    d,f,s,rev,cohort,rows=context(request,True);selected(rows,key);v=d.inspections.get(calibration_id);cal=d.registry.idx['metrology_calibrations'].get(calibration_id)
    if not v or not cal or cal['instrument_id']!=key:raise Record.DoesNotExist()
    certificate=v['certificate']
    if not certificate or not certificate.get('file_id') or not v['file']:raise Record.DoesNotExist()
    from . import file_sharing,device_files
    file,permit=file_sharing.readable(request.user,certificate['file_id']);raw=device_files.contents(file)
    if file.file_hash!=certificate['file_sha256']:raise ReviewConflict('台账声明与归档摘要不同，下载暂停')
    finish(request,d,f,s,rev)
    AuditEvent.objects.create(action='metrology_certificate.original',actor=request.user.username,object_type='DeviceFile',object_id=str(file.pk),detail={'calibration_id':calibration_id,'receipt':s,'business_facts_changed':False})
    return download_response(raw,file.filename,'application/octet-stream')

FIELDS=[('id','仪器通道'),('calibration_label','当前校准登记'),('evidence_label','当前账号原件对应'),('due_label','登记到期队列'),('hours_to_expiry','距登记失效自然小时')]
@api()
@transaction.atomic
def export(request):
    d,f,s,rev,cohort,rows=context(request,True)
    out=[['校准证书与到期 · 全部合成模拟','业务截止',d.cutoff,'登记截止',d.known],['筛选',json.dumps(f,ensure_ascii=False)],['范围与原件读取依据',s],['说明',eng.NOTE+' '+eng.TIME_NOTE]]
    out.append([label for key,label in FIELDS]+['资产号','特性','单位','当前校准版本','登记失效起点','问题'])
    for r in rows:
        i=r['instrument'];c=r['calibration'] or {};out.append([r.get(k) for k,l in FIELDS]+[i['asset_code'],i['parameter'],i['unit'],c.get('id'),c.get('valid_until'),'；'.join(r['issues'])])
    finish(request,d,f,s,rev)
    AuditEvent.objects.create(action='metrology_certificate.export',actor=request.user.username,object_type='MetrologyCertificate',object_id='instrument-cohort',detail={'filters':f,'receipt':s,'rows':len(rows),'business_facts_changed':False})
    result=csv_reply(out,'metrology-certificate-instrument-cohort');result['Cache-Control']='no-store';return result
