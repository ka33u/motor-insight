"""Read-only return/lot investigation with scoped, versioned exports."""
import hashlib
from django.db import transaction
from . import return_stock as eng,analytics,access
from .models import AuditEvent,Record
from .views import api,reply
from .import_review import ReviewConflict
from .quality_views import csv_reply
from .trace_cases import capture_sources


def respond(value):
    r=reply(value);r['Cache-Control']='no-store';return r


def page(request):
    p=request.GET.get('page','1')
    if not p.isdecimal() or not 1<=int(p)<=100000:raise ValueError('页码无效')
    return int(p)


def context(request,required=False):
    f=eng.filters(request.GET);d,revision=eng.current();receipt=eng.receipt(f,revision)
    if required and not request.GET.get('receipt'):raise ValueError('请从已查看的退料库存结果进入')
    if request.GET.get('receipt') and request.GET['receipt']!=receipt:raise ReviewConflict('退料库存范围、来源或规则已变化，请刷新')
    return d,f,revision,receipt


def verify(f,revision,receipt):
    if list(analytics.revision())!=list(revision) or eng.receipt(f,revision)!=receipt:raise ReviewConflict('读取期间来源或规则变化，请刷新')


def selected_detail(d,f,key):
    if key not in {r['id'] for r in d.selected(f)}:raise Record.DoesNotExist()
    return d.details[key]


def sources(user,rows):
    return capture_sources({'sources':[r for r in rows if access.allowed(user,r['dataset'])]})


@api()
@transaction.atomic
def board(request):
    d,f,revision,receipt=context(request);p=page(request);rows=d.cohort(f);chosen=d.selected(f)
    result=dict(filters=f,version=eng.VERSION,as_of=d.cutoff,note=eng.NOTE,state_note=eng.STATE_NOTE,
        summary=d.summary(rows),matrix=d.matrix(rows),units=d.units(rows),
        stages=eng.STAGES,facets={k:sum(k in r['flags'] for r in rows) for k in eng.STAGES},
        rows=chosen[(p-1)*25:p*25],page=p,size=25,total=len(chosen),receipt=receipt)
    verify(f,revision,receipt);return respond(result)


@api()
@transaction.atomic
def detail(request,key):
    d,f,revision,receipt=context(request,True);obj=selected_detail(d,f,key)
    result=dict(obj,receipt=receipt,as_of=d.cutoff,version=eng.VERSION,note=eng.NOTE,state_note=eng.STATE_NOTE)
    verify(f,revision,receipt);return respond(result)


@api()
@transaction.atomic
def evidence(request,key):
    d,f,revision,receipt=context(request,True);obj=selected_detail(d,f,key);p=page(request)
    rows=sources(request.user,obj['sources']);verify(f,revision,receipt)
    return respond(dict(rows=rows[(p-1)*40:p*40],page=p,size=40,total=len(rows),receipt=receipt,can_download_original=access.can_import(request.user)))


@api()
@transaction.atomic
def export(request):
    d,f,revision,receipt=context(request,True);selected=d.selected(f);lots=d.unique_lots(selected)
    rows=[['退料与库存状态核对 · 合成模拟数据','规则',eng.VERSION,'截至',d.cutoff],['说明',eng.NOTE],['状态核对',eng.STATE_NOTE],
          ['范围',str(f)],['退料流水','原领料','退料工单','原工单','物料','批次','库位','发生时间','原退料增减量','单位','单据可核对','退料时状态','当前状态','证据问题']]
    fields=('id','issue_id','work_order_id','original_work_order_id','material_id','lot','location','occurred','qty_signed','unit','document_verified','arrival_state','current_state')
    rows += [[r[k] for k in fields]+['；'.join(r['issues'])] for r in selected]
    rows += [[],['目标库位去重余额，不分摊给单笔退料'],['库位身份','物料','批次','库位','单位','登记状态','可核对状态','账面余额','可用状态余额','问题']]
    fields=('id','material_id','lot','location','unit','recorded_state','state','balance_qty','usable_state_qty')
    rows += [[r[k] for k in fields]+['；'.join(r['issues'])] for r in lots]
    all_sources=eng.supply.unique_refs([s for r in selected for s in d.details[r['id']]['sources']])
    provenance=sources(request.user,all_sources)
    rows += [[],['来源对象','编号','Excel文件','工作表','行号','缺失']]
    rows += [[r.get(k) for k in ('dataset','key','filename','sheet','row','missing')] for r in provenance]
    verify(f,revision,receipt);response=csv_reply(rows,'return-stock-'+receipt[:16]);response['Cache-Control']='no-store'
    AuditEvent.objects.create(action='return_stock.export',actor=request.user.username,object_type='ReturnStock',object_id=receipt,
        detail=dict(filters=f,returns=len(selected),target_lots=len(lots),file_sha256=hashlib.sha256(response.content).hexdigest(),business_facts_changed=False))
    return response
