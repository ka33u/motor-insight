import hashlib,json,csv,io
from pathlib import Path
from datetime import date
from django.conf import settings
from django.db import transaction
from . import material_certificates as eng,analytics,access,device_files
from .models import Record,AuditEvent
from .views import api,reply
from .trace_cases import capture_sources
from .import_review import ReviewConflict
from .quality_views import csv_reply
from .device_file_views import download_response

def filters(q):
    keys=['category','material_id','supplier_id','received_from','received_to','q','stage']
    if set(q)-set(keys+['page','receipt']):raise ValueError('证明范围字段无效')
    if hasattr(q,'getlist') and any(len(q.getlist(k))!=1 for k in q):raise ValueError('范围字段不可重复')
    f={k:q.get(k,'').strip() for k in keys};f['stage']=q.get('stage','all')
    if f['stage'] not in eng.STATES or any(len(v)>150 for v in f.values()):raise ValueError('证明状态或范围无效')
    for k in ['received_from','received_to']:
        if f[k] and (date.fromisoformat(f[k]).isoformat()!=f[k] or f[k]>analytics.AS_OF[:10]):raise ValueError('到货日期须为标准日期且不晚于业务截止')
    if f['received_from'] and f['received_to'] and f['received_from']>f['received_to']:raise ValueError('到货日期倒序')
    return f
def page(q):
    v=q.get('page','1')
    if not v.isdecimal() or not 1<=int(v)<=100000:raise ValueError('证明页码无效')
    return int(v)
def stamp(f,rev,user,d):
    file_observations=[(r['id'],r['state'],r['file_observation'],r.get('file')) for r in d.rows]
    h=hashlib.sha256(json.dumps([f,list(rev),analytics.AS_OF,user.pk,access.role(user),file_observations],ensure_ascii=False,sort_keys=True).encode())
    for name in ['material_certificates.py','material_certificate_views.py','schema.py','device_files.py']:h.update((Path(settings.BASE_DIR)/'app'/name).read_bytes())
    return h.hexdigest()
def response(d):
    r=reply(d);r['Cache-Control']='no-store';return r
def context(request,required=False):
    device_files.require(request.user);f=filters(request.GET);page(request.GET);rev=analytics.revision();d=eng.Certificates(resolve=eng.resolver(request.user));s=stamp(f,rev,request.user,d)
    for k in ['category','material_id','supplier_id']:
        if f[k] and f[k] not in {r[k] for r in d.rows}:raise ValueError('类别、物料或供应商不在到货范围')
    supplied=request.GET.get('receipt')
    if required and not supplied:raise ValueError('请先读取证明范围')
    if supplied and supplied!=s:raise ReviewConflict('范围、来源、账号、原件状态或规则变化，请重新读取')
    if list(rev)!=list(analytics.revision()):raise ReviewConflict('读取时来源发生变化，请重试')
    cohort=d.cohort(f);rows=sorted([r for r in cohort if f['stage']=='all' or f['stage']==r['state']],key=lambda r:(r['state']=='consistent',r['received'],r['id']))
    return d,f,s,cohort,rows
def selected(rows,key):
    row=next((r for r in rows if r['id']==key),None)
    if not row:raise Record.DoesNotExist()
    return row
@api()
@transaction.atomic
def board(request):
    d,f,s,cohort,rows=context(request);p=page(request.GET)
    return response(dict(filters=f,receipt=s,as_of=d.cutoff,summary=eng.summary(cohort),groups=[dict(category=k,**eng.summary(rr)) for k,rr in sorted(eng.group(cohort,'category').items())],rows=[eng.public(r) for r in rows[(p-1)*25:p*25]],page=p,size=25,total=len(rows),stages=eng.STATES,facets={k:len(cohort) if k=='all' else sum(r['state']==k for r in cohort) for k in eng.STATES},options=dict(categories=sorted({r['category'] for r in d.rows}),materials=sorted({r['material_id']:r['material'] for r in d.rows}.items()),suppliers=sorted({r['supplier_id']:r['supplier'] for r in d.rows}.items())),note=eng.NOTE,boundary=eng.BOUNDARY,global_issues=d.global_issues))
@api()
@transaction.atomic
def detail(request,key):
    d,f,s,cohort,rows=context(request,True);return response(selected(rows,key)|dict(receipt=s,filters=f,as_of=d.cutoff,note=eng.NOTE,boundary=eng.BOUNDARY))
@api()
@transaction.atomic
def evidence(request,key):
    d,f,s,cohort,rows=context(request,True);r=selected(rows,key);p=page(request.GET);sources=capture_sources({'sources':[v for v in r['sources'] if access.allowed(request.user,v['dataset'])]})
    return response(dict(rows=sources[(p-1)*40:p*40],total=len(sources),page=p,size=40,receipt=s,can_download_original=access.can_import(request.user)))
FIELDS=[('id','到货单'),('received','到货时间'),('purchase_line_id','采购行'),('material_id','物料'),('supplier_id','供应商'),('lot','厂内批次'),('raw_certificate_number','原到货证明号'),('raw_receipt_status','原到货状态'),('link_id','当前关联'),('certificate_id','证明台账'),('supplier_lot','供应批次'),('issued','签发日期'),('state_label','当前账号证明核对状态')]
@api()
def template(request):
    device_files.require(request.user);out=io.StringIO();csv.writer(out).writerow(eng.HEADERS)
    return download_response(('\ufeff'+out.getvalue()).encode(),'材质证明_模拟标准CSV表头.csv','text/csv; charset=utf-8')
@api()
@transaction.atomic
def export(request):
    d,f,s,cohort,rows=context(request,True);out=[['到货材质证明 · 合成模拟','范围',json.dumps(f,ensure_ascii=False),'业务截止',d.cutoff],['本次范围与原件读取依据',s],['说明',eng.NOTE],['边界',eng.BOUNDARY],[label for key,label in FIELDS]+['可访问归档文件','归档摘要','核对问题']]+[[r.get(k) for k,label in FIELDS]+[(r['file'] or {}).get('filename'),(r['file'] or {}).get('file_hash'),'；'.join(r['issues'])] for r in rows]
    AuditEvent.objects.create(action='material_certificate.export',actor=request.user.username,object_type='MaterialCertificate',object_id='cohort',detail={'filters':f,'receipt':s,'rows':len(rows),'business_facts_changed':False})
    response=csv_reply(out,'receipt-certificates');response['Cache-Control']='no-store';return response
