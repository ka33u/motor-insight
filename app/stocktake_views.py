import hashlib,json
from pathlib import Path
from django.conf import settings
from django.db import transaction
from . import stocktake as eng,analytics,access
from .views import api,reply
from .import_review import ReviewConflict
from .models import AuditEvent
from .trace_cases import capture_sources
from .quality_views import csv_reply

def filters(q):
    if set(q)-{'run','unit','stage','q','page','receipt'}:raise ValueError('盘点筛选字段无效')
    if hasattr(q,'getlist') and any(len(q.getlist(k))!=1 for k in q):raise ValueError('筛选字段不可重复')
    f={k:q.get(k,'').strip() for k in ['run','unit','q']};f['stage']=q.get('stage','all')
    if f['stage'] not in eng.STAGES or any(len(v)>120 for v in f.values()):raise ValueError('盘点筛选无效')
    return f
def page(q):
    p=q.get('page','1')
    if not p.isdecimal() or not 1<=int(p)<=100000:raise ValueError('页码无效')
    return int(p)
def receipt(f,rev,user):
    h=hashlib.sha256(json.dumps([f,list(rev),analytics.AS_OF,user.pk,access.role(user)],sort_keys=True,ensure_ascii=False).encode())
    for name in ['stocktake.py','stocktake_views.py','supply.py','schema.py']:h.update((Path(settings.BASE_DIR)/'app'/name).read_bytes())
    return h.hexdigest()
def respond(value):
    r=reply(value);r['Cache-Control']='no-store';return r
def context(request,required=False):
    f=filters(request.GET);page(request.GET);rev=analytics.revision();d=eng.Stocktakes();stamp=receipt(f,rev,request.user)
    if f['run'] and f['run'] not in {r['id'] for r in d.runs}:raise ValueError('盘点单不在有效截止范围内')
    if f['unit'] and f['unit'] not in {r['unit'] for r in d.rows}:raise ValueError('单位无效')
    supplied=request.GET.get('receipt')
    if required and not supplied:raise ValueError('请先查看盘点范围')
    if supplied and supplied!=stamp:raise ReviewConflict('盘点范围、账号、数据或规则已变化，请重新读取')
    if list(rev)!=list(analytics.revision()):raise ReviewConflict('读取期间来源发生变化，请重试')
    return d,f,stamp
def brief(r):return {k:v for k,v in r.items() if k not in ['recounts','dispositions','sources','ledger_timeline','period_movements']}

@api()
@transaction.atomic
def board(request):
    d,f,stamp=context(request);rows=d.selected(f);p=page(request.GET)
    return respond({'filters':f,'summary':eng.summary(rows),'rows':[brief(r) for r in rows[(p-1)*25:p*25]],'total':len(rows),'page':p,'size':25,'stages':eng.STAGES,'runs':[{k:v for k,v in r.items() if k not in ['rows','unplanned_lots']}|{'unplanned_count':len(r['unplanned_lots'])} for r in d.runs],'units':sorted({r['unit'] for r in d.rows}),'receipt':stamp,'as_of':d.cutoff,'note':eng.NOTE,'boundary':eng.BOUNDARY,'global_issues':d.global_issues})

@api()
@transaction.atomic
def detail(request,key):
    d,f,stamp=context(request,True);return respond({**d.detail(key,f),'receipt':stamp,'filters':f,'as_of':d.cutoff,'note':eng.NOTE,'boundary':eng.BOUNDARY})

@api()
@transaction.atomic
def evidence(request,key):
    d,f,stamp=context(request,True);row=d.detail(key,f);p=page(request.GET);rows=capture_sources({'sources':[r for r in row['sources'] if access.allowed(request.user,r['dataset'])]})
    return respond({'rows':rows[(p-1)*40:p*40],'total':len(rows),'page':p,'size':40,'receipt':stamp,'can_download_original':access.can_import(request.user)})

FIELDS=[('run_id','盘点单'),('id','盘点行'),('material_id','物料编码'),('material','物料名称'),('lot','批次'),('location','库位'),('unit','单位'),('book_at','账面截止'),('book_qty','账面量'),('initial_qty','初盘量'),('effective_qty','有效实盘量'),('initial_delta','初盘差额'),('variance','最终盘差'),('basis_id','实盘依据'),('recount_count','有效复盘次数'),('eligible','账实可比'),('disposition_state','处置登记状态'),('confirmed','当前依据已确认')]

@api()
@transaction.atomic
def export(request):
    d,f,stamp=context(request,True);rows=d.selected(f)
    out=[['库存盘点与账实核对 · 合成模拟数据','范围',json.dumps(f,ensure_ascii=False),'来源截止',d.cutoff],['计算依据',stamp],['说明',eng.NOTE],['边界',eng.BOUNDARY],[label for _,label in FIELDS]+['账实核对事项','处置核对事项']]
    out += [[r.get(k) for k,_ in FIELDS]+['；'.join(r['issues']),'；'.join(r['disposition_issues'])] for r in rows]
    AuditEvent.objects.create(action='stocktake.export',actor=request.user.username,object_type='Stocktake',object_id=f['run'] or 'all',detail={'filters':f,'receipt':stamp,'rows':len(rows),'business_facts_changed':False})
    return csv_reply(out,'stocktake')
