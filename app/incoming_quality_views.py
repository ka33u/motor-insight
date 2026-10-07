import hashlib,json
from pathlib import Path
from datetime import date
from django.conf import settings
from django.db import transaction
from . import incoming_quality as eng,analytics,access,supply
from .models import Record,AuditEvent
from .views import api,reply
from .import_review import ReviewConflict
from .trace_cases import capture_sources
from .quality_views import csv_reply

def filters(q):
    keys=['category','material_id','supplier_id','inspection_from','inspection_to','q','spec_id','mode','stage']
    if set(q)-set(keys+['page','receipt']):raise ValueError('来料特性筛选字段无效')
    if hasattr(q,'getlist') and any(len(q.getlist(k))!=1 for k in q):raise ValueError('筛选字段不可重复')
    f={k:q.get(k,'').strip() for k in keys};f.update(mode=q.get('mode','latest'),stage=q.get('stage','all'))
    if f['mode'] not in ['first','latest','all'] or f['stage'] not in eng.STATES or any(len(v)>150 for v in f.values()):raise ValueError('登记口径、状态或筛选无效')
    for k in ['inspection_from','inspection_to']:
        if f[k] and (date.fromisoformat(f[k]).isoformat()!=f[k] or f[k]>analytics.AS_OF[:10]):raise ValueError('原检验日期须为标准日期且不晚于截止')
    if f['inspection_from'] and f['inspection_to'] and f['inspection_from']>f['inspection_to']:raise ValueError('原检验日期倒序')
    return f
def page(q):
    v=q.get('page','1')
    if not v.isdecimal() or not 1<=int(v)<=100000:raise ValueError('页码无效')
    return int(v)
def stamp(f,rev,user):
    h=hashlib.sha256(json.dumps([f,list(rev),analytics.AS_OF,user.pk,access.role(user)],ensure_ascii=False,sort_keys=True).encode())
    for name in ['incoming_quality.py','incoming_quality_views.py','schema.py','supply.py']:h.update((Path(settings.BASE_DIR)/'app'/name).read_bytes())
    return h.hexdigest()
def response(d):
    r=reply(d);r['Cache-Control']='no-store';return r
def context(request,required=False):
    f=filters(request.GET);page(request.GET);rev=analytics.revision();d=eng.IncomingQuality();s=stamp(f,rev,request.user)
    for k in ['category','material_id','supplier_id']:
        if f[k] and f[k] not in {r[k] for r in d.rows}:raise ValueError('类别、物料或供应商不在原检验范围')
    if f['spec_id'] and f['spec_id'] not in d.idx['incoming_specs']:raise ValueError('规范项目不存在')
    supplied=request.GET.get('receipt')
    if required and not supplied:raise ValueError('请先读取来料特性范围')
    if supplied and supplied!=s:raise ReviewConflict('来料特性范围、来源、规则或账号变化，请重新读取')
    if list(rev)!=list(analytics.revision()):raise ReviewConflict('读取时来源变化，请重试')
    cohort=d.cohort(f);rows=sorted([r for r in cohort if f['stage'] in r['flags']],key=lambda r:(r['state'] not in ['attention','missing','pending','no_plan'],not r['disagreement'],r['inspected'],r['id']))
    return d,f,s,cohort,rows
def selected(rows,key):
    r=next((r for r in rows if r['id']==key),None)
    if not r:raise Record.DoesNotExist()
    return r

@api()
@transaction.atomic
def board(request):
    d,f,s,cohort,rows=context(request);p=page(request.GET);distribution=d.distribution(rows,f['spec_id'],f['mode']) if f['spec_id'] else None
    if distribution:
        values=distribution.pop('observations');excluded=distribution.pop('exclusions');distribution.update(rows=values[(p-1)*25:p*25],total=len(values),excluded_rows=excluded[:10],excluded_count=len(excluded))
    specs=[v for v in d.data.get('incoming_specs',[]) if not f['material_id'] or v['material_id']==f['material_id']]
    return response(dict(filters=f,summary=eng.summary(cohort),groups=[dict(category=k,**eng.summary(rr)) for k,rr in sorted(eng.group(cohort,'category').items())],rows=[eng.public(r) for r in rows[(p-1)*25:p*25]],total=len(rows),page=p,size=25,distribution=distribution,facets={k:sum(k in r['flags'] for r in cohort) for k in eng.STATES},stages=eng.STATES,options=dict(categories=sorted({r['category'] for r in d.rows}),materials=sorted({r['material_id']:r['material'] for r in d.rows}.items()),suppliers=sorted({r['supplier_id']:r['supplier'] for r in d.rows}.items()),specs=sorted(specs,key=lambda v:(v['material_id'],v['version'],v['parameter']))),receipt=s,as_of=d.cutoff,note=eng.NOTE,boundary=eng.BOUNDARY,global_issues=d.global_issues))

@api()
@transaction.atomic
def detail(request,key):
    d,f,s,cohort,rows=context(request,True);r=selected(rows,key);return response(r|dict(receipt=s,filters=f,as_of=d.cutoff,note=eng.NOTE,boundary=eng.BOUNDARY))

@api()
@transaction.atomic
def evidence(request,key):
    d,f,s,cohort,rows=context(request,True);r=selected(rows,key);p=page(request.GET);sources=capture_sources({'sources':[x for x in r['sources'] if access.allowed(request.user,x['dataset'])]})
    return response(dict(rows=sources[(p-1)*40:p*40],total=len(sources),page=p,size=40,receipt=s,can_download_original=access.can_import(request.user)))

FIELDS=[('id','原来料检验号'),('receipt_id','到货单号'),('purchase_line_id','采购行'),('material_id','物料'),('supplier_id','供应商'),('lot','批次'),('inspected','原检验登记时间'),('raw_sample_count','原抽样数'),('raw_defect_count','原不良样本数'),('raw_result','原批次结论'),('raw_disposition','原处置'),('plan_id','特性计划'),('spec_version','计划规范版本'),('state_label','最新特性状态'),('first_id','首登记'),('latest_id','最新登记'),('latest_defect_count','最新齐项时超限样本数'),('disagreement','与原不良样本数不同')]
VALUES=[('id','测量记录'),('inspection_id','原来料检验'),('receipt_id','到货单'),('check_id','特性登记'),('sample_no','样本序号'),('spec_id','规范项目'),('checked','测量时间'),('value','实测值'),('unit','单位'),('lsl','下限'),('usl','上限'),('out','超限'),('instrument','演示采集点'),('file_reference','模拟外部文件编号')]
def preface(f,s,cutoff):return [['来料特性 · 合成模拟','范围',json.dumps(f,ensure_ascii=False),'截止',cutoff],['计算依据',s],['说明',eng.NOTE],['边界',eng.BOUNDARY]]
def csv_response(rows,name):
    r=csv_reply(rows,name);r['Cache-Control']='no-store';return r

@api()
@transaction.atomic
def export(request):
    d,f,s,cohort,rows=context(request,True);out=preface(f,s,d.cutoff)+[[v for k,v in FIELDS]+['资料核对']]+[[r.get(k) for k,label in FIELDS]+['；'.join(r['issues'])] for r in rows]
    AuditEvent.objects.create(action='incoming_quality.export',actor=request.user.username,object_type='IncomingQuality',object_id='cohort',detail={'filters':f,'receipt':s,'rows':len(rows),'business_facts_changed':False});return csv_response(out,'incoming-characteristics')

@api()
@transaction.atomic
def measurement_export(request):
    d,f,s,cohort,rows=context(request,True)
    if not f['spec_id']:raise ValueError('请先选择一个规范项目')
    values=d.distribution(rows,f['spec_id'],f['mode']);out=preface(f,s,d.cutoff)+[[v for k,v in VALUES]]+[[r.get(k) for k,label in VALUES] for r in values['observations']]
    AuditEvent.objects.create(action='incoming_quality.measurement_export',actor=request.user.username,object_type='IncomingQuality',object_id=f['spec_id'],detail={'filters':f,'receipt':s,'rows':len(values['observations']),'excluded':len(values['exclusions']),'business_facts_changed':False});return csv_response(out,'incoming-characteristic-values')
