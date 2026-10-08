"""Versioned, read-only work-order evidence for preparing WIP replanning."""
import hashlib
import json
from django.db import transaction
from . import wip_readiness as eng, analytics, access, supply
from .models import AuditEvent, Record
from .views import api, reply
from .import_review import ReviewConflict
from .trace_cases import capture_sources
from .quality_views import csv_reply


def respond(value):
    r=reply(value);r['Cache-Control']='no-store';return r


def page(request):
    p=request.GET.get('page','1')
    if not p.isdecimal() or not 1<=int(p)<=100000:raise ValueError('页码无效')
    return int(p)


def context(request,required=False):
    f=eng.filters(request.GET);d,rev=eng.current();receipt=eng.receipt(f,rev)
    if required and not request.GET.get('receipt'):raise ValueError('请从已查看的在制核对结果进入')
    if request.GET.get('receipt') and request.GET['receipt']!=receipt:raise ReviewConflict('在制核对范围、来源或规则已变化，请刷新')
    return d,f,rev,receipt


def verify(f,rev,receipt):
    if tuple(analytics.revision())!=tuple(rev) or eng.receipt(f,rev)!=receipt:raise ReviewConflict('读取期间依据变化，请刷新')


def selected(d,f,key):
    if key not in {r['id'] for r in d.selected(f)}:raise Record.DoesNotExist()
    return d.details[key]


def provenance(user,refs):
    return capture_sources({'sources':[r for r in refs if access.allowed(user,r['dataset'])]})


@api()
@transaction.atomic
def board(request):
    d,f,rev,receipt=context(request);p=page(request);cohort=d.cohort(f);rows=d.selected(f)
    result=dict(version=eng.VERSION,as_of=d.cutoff,known_as_of=d.cutoff,filters=f,receipt=receipt,note=eng.NOTE,boundary=eng.BOUNDARY,
        time_note=eng.wip_flow.TIME_NOTE,summary=d.summary(cohort),matrix=d.matrix(cohort),stages=eng.STAGES,
        facets={k:sum(k in r['flags'] for r in cohort) for k in eng.STAGES},rows=rows[(p-1)*25:p*25],total=len(rows),page=p,size=25)
    verify(f,rev,receipt);return respond(result)


@api()
@transaction.atomic
def detail(request,key):
    d,f,rev,receipt=context(request,True);obj=selected(d,f,key)
    result=dict(obj,version=eng.VERSION,as_of=d.cutoff,receipt=receipt,note=eng.NOTE,boundary=eng.BOUNDARY,time_note=eng.wip_flow.TIME_NOTE)
    verify(f,rev,receipt);return respond(result)


@api()
@transaction.atomic
def evidence(request,key):
    d,f,rev,receipt=context(request,True);obj=selected(d,f,key);p=page(request)
    rows=provenance(request.user,obj['sources']);verify(f,rev,receipt)
    return respond(dict(rows=rows[(p-1)*40:p*40],total=len(rows),page=p,size=40,receipt=receipt,can_download_original=access.can_import(request.user)))


@api()
@transaction.atomic
def export(request):
    d,f,rev,receipt=context(request,True);rows=d.selected(f);details=[d.details[r['id']] for r in rows]
    out=[['在制重排准备核对 · 全部合成模拟','定义',eng.VERSION,'业务和登记截止',d.cutoff],['阅读定义',eng.NOTE],
        ['计算边界',eng.BOUNDARY],['时间边界',eng.wip_flow.TIME_NOTE],['范围',json.dumps(f,ensure_ascii=False),'依据',receipt],
        ['工单','配置','登记状态','计划台数','BOM版本','已结束报工笔数','未结束报工笔数','时间待核对笔数','未来报工笔数','截止前同配置装配SN','装配依据待核对SN','整单待领未计算','剩余工序量','剩余工时','剩余工序耗料','试排状态']]
    fields=('id','product_id','status','planned_qty','bom_version','ended_reports','open_reports','unknown_reports','future_reports','assembled_sn','unknown_sn','material_uncomputed','remaining_task_qty','remaining_task_minutes','remaining_material_qty','scheduling_state')
    out += [[r[k] for k in fields] for r in rows]
    out += [[],['工单','分支','原批次数','可核对批次数','完整在制件数','已知部分在制件数','未知批次数']]
    out += [[r['id']]+[g[k] for k in ('kind','roots','verified_roots','wip_qty','known_wip_qty','unknown_roots')] for r in rows for g in r['wip_groups']]
    out += [[],['工单','原批次','分支','核对状态','有效基准件数','可核对在制件数','有效前缀耗用件数','有效前缀报废件数','未核定余量','问题']]
    out += [[d['row']['id']]+[r.get(k) for k in ('id','kind','state','baseline_qty','wip_qty','prefix_consumed_qty','prefix_scrap_qty','unknown_remainder')]+['；'.join(r['issues'])] for d in details for r in d['roots']]
    out += [[],['工单','原批次','周转批次','位置','位置类别','分支','本原批次份额件数','整箱件数（重复展示不可累加）']]
    out += [[d['row']['id']]+[r.get(k) for k in ('root_id','lot_id','location_id','location_kind','kind','qty','whole_lot_qty')] for d in details for r in d['positions']]
    out += [[],['工单','报工','对象类型','对象','工序名称','设备','资源位','工号','开始','结束','原投入','原良品','原报废','原返工','原状态','截止时分类','已确认路线工序','当前路线同名候选（未确认）']]
    out += [[d['row']['id']]+[r.get(k) for k in eng.OP_FIELDS if k!='work_order_id']+[r['time_state'],r['route_id'],','.join(t['id'] for t in r['route_candidates'])] for d in details for r in d['operations']]
    out += [[],['工单','SN','配置','装配时间','定子批次','转子批次']]
    out += [[d['row']['id']]+[r.get(k) for k in ('id','product_id','assembly_at','stator_batch','rotor_batch')] for d in details for r in d['units']]
    out += [[],['工单','物料','名称','单位','整单定额需求','累计领料','关联退料','净领料','整单待领','物料问题','物料提示']]
    out += [[d['row']['id']]+[('；'.join(r[k]) if isinstance(r[k],list) else r[k]) for k in eng.MATERIAL_FIELDS] for d in details for r in d['materials']]
    out += [[],['工单','证据问题或待补依据']]
    out += [[d['row']['id'],v] for d in details for v in d['material_issues']+d['wip_global_issues']+[r['id']+'：'+'；'.join(r['issues']) for r in d['roots'] if r['issues']]+[g['owner']+'：'+g['need'] for g in d['gaps']]]
    sources=provenance(request.user,supply.unique_refs([s for d in details for s in d['sources']]))
    out += [[],['来源对象','编号','Excel文件','工作表','行号','缺失']]+[[r.get(k) for k in ('dataset','key','filename','sheet','row','missing')] for r in sources]
    verify(f,rev,receipt);response=csv_reply(out,'wip-readiness-'+receipt[:16]);response['Cache-Control']='no-store'
    AuditEvent.objects.create(action='wip_readiness.export',actor=request.user.username,object_type='WipReadiness',object_id=receipt,
        detail=dict(filters=f,work_orders=len(rows),source_rows=len(sources),file_sha256=hashlib.sha256(response.content).hexdigest(),business_facts_changed=False))
    return response
