import json
from django.db import transaction
from .views import api
from . import material_planning_views as prep,material_supply as eng,access
from .quality_views import csv_reply
from .models import AuditEvent
from .trace_cases import capture_sources
from .import_review import ReviewConflict

FIELDS=[('id','采购行'),('supplier_id','供应商编码'),('supplier','供应商'),('ordered','下单日'),('due','承诺到货日'),('status','原采购状态'),('qty','采购数量'),*eng.STAGES.items()]

def context(request,key,require_flow=False):
    if any(len(request.GET.getlist(k))!=1 for k in request.GET):raise ValueError('筛选字段不可重复')
    supplied=request.GET.get('flow_receipt');q=request.GET.copy();q.pop('flow_receipt',None)
    original=request.GET
    try:
        request.GET=q;d,f,receipt,rev=prep.context(request,True)
    finally:request.GET=original
    flow=eng.digest(receipt,request.user,key)
    if require_flow and not supplied:raise ValueError('请先查看供应进度')
    if supplied and supplied!=flow:raise ReviewConflict('供应进度范围、账号或规则已变化，请重新打开')
    data=eng.build(d,key);data.update(receipt=receipt,flow_receipt=flow)
    prep.verify(f,rev,receipt)
    return data

@api()
@transaction.atomic
def board(request,key):return prep.respond(context(request,key))

@api()
@transaction.atomic
def evidence(request,key):
    data=context(request,key,True);p=prep.page(request);refs=[r for r in data['sources'] if access.allowed(request.user,r['dataset'])];rows=capture_sources({'sources':refs})
    return prep.respond({'rows':rows[(p-1)*40:p*40],'total':len(rows),'page':p,'size':40,'can_download_original':access.can_import(request.user),'flow_receipt':data['flow_receipt']})

@api()
@transaction.atomic
def export(request,key):
    d=context(request,key,True);m=d['material'];data=[['物料供应进度 · 合成模拟数据','物料',key,'单位',m['unit'],'截止',d['as_of']],['范围',json.dumps(d['filters'],ensure_ascii=False),'供应计算依据',d['flow_receipt']],['说明',d['note'],d['boundary']],[label for _,label in FIELDS]+['纳入数量核对','资料问题']]
    data += [[p.get(k) for k,_ in FIELDS]+['是' if p['valid'] else '取消排除' if p['cancelled'] and not p['issues'] else '待核对','；'.join(p['issues'])] for p in d['purchases']]
    AuditEvent.objects.create(action='material_supply.export',actor=request.user.username,object_type='MaterialSupply',object_id=key,detail={'filters':d['filters'],'receipt':d['flow_receipt'],'rows':len(d['purchases']),'business_facts_changed':False})
    response=csv_reply(data,'material-supply-'+key);response['Cache-Control']='no-store';return response
