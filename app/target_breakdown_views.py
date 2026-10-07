import json
from django.db import transaction
from . import target_breakdown as b,access
from .views import api
from .target_views import response,receipt,check_receipt,page,guard
from .trace_cases import capture_sources
from .quality_views import csv_reply
from .models import AuditEvent

@api()
@transaction.atomic
def breakdown(request,key):
    guard(request);check_receipt(request);d=b.Breakdown(request.user,key).calculate(request.GET);p=page(request.GET);rows=d.pop('rows');return response({**d,'rows':rows[(p-1)*20:p*20],'chart_rows':rows[:10],'page':p,'size':20,'receipt':receipt()})

@api()
@transaction.atomic
def evidence(request,key):
    guard(request);check_receipt(request);d=b.Breakdown(request.user,key);rows,axis,path,label=d.evidence(request.GET);rows=sorted(rows,key=lambda r:str(r['id']));p=page(request.GET)
    return response({'rows':[access.sanitize(request.user,d.dataset,r) for r in rows[(p-1)*20:p*20]],'fields':access.permitted_fields(request.user,d.dataset),'page':p,'size':20,'total':len(rows),'axis':axis,'breadcrumbs':path,'group_label':label,'receipt':receipt()})

@api()
@transaction.atomic
def sources(request,key):
    guard(request);check_receipt(request);d=b.Breakdown(request.user,key);rows,axis,path,label=d.evidence(request.GET);obj=next((r for r in rows if r['id']==request.GET.get('object_id')),None)
    if obj is None:raise ValueError('对象不在所选目标和分组范围')
    refs=d.source_refs(obj,request.GET,axis);rows=capture_sources({'sources':refs});p=page(request.GET)
    return response({'rows':rows[(p-1)*40:p*40],'page':p,'size':40,'total':len(rows),'can_download_original':access.can_import(request.user),'receipt':receipt()})

FIELDS=[('label','分组'),('missing_kind','分组资料缺口'),('actual','实际值'),('source_rows','来源记录数'),('valid_rows','有效来源数'),('missing_rows','空缺来源数'),('share_pct','非负可加总实际构成百分数'),('difference','与当前上层实际差额'),('numerator','比率分子'),('denominator','比率分母')]
@api()
@transaction.atomic
def export(request,key):
    guard(request);check_receipt(request);d=b.Breakdown(request.user,key).calculate(request.GET);t=d['target']
    values=[['目标实际分组分析',key,t['name'],'模型版本',t['model_version'],'度量',t['measure'],'单位',t['unit']],['目标范围',t['period_start'],t['period_end'],t.get('date_label'),'状态',t['state']],['分组路径',json.dumps(d['breadcrumbs'],ensure_ascii=False),'当前维度',d['axis']['label'],'排序',d['sort']],['说明',d['note'],d['explanation'],'差额单位',d['difference_unit']],['计算依据',receipt(),'原目标实际',d['total']['actual'],'本层实际',d['parent']['actual'],'本层来源数',d['parent']['source_rows']],[label for _,label in FIELDS]+['分位数依据','计算提示']]
    values.extend([[r.get(f) for f,_ in FIELDS]+[json.dumps(r['quantile'],ensure_ascii=False) if r['quantile'] else '', '；'.join(r['notes'])] for r in d['rows']])
    AuditEvent.objects.create(action='target.breakdown.export',actor=request.user.username,object_type='TargetBreakdown',object_id=key,detail={'axis':d['axis'],'path':d['breadcrumbs'],'sort':d['sort'],'groups':d['groups'],'receipt':receipt(),'unit':t['unit']})
    out=csv_reply(values,'target-breakdown');out['Cache-Control']='no-store';return out
