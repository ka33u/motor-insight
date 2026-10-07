import json
from datetime import date
from django.db import transaction
from django.utils import timezone
from . import manufacturing as eng,access,analytics
from .views import api,reply,body,require
from .models import IssueDisposition,AuditEvent
from .delivery_views import follow_info
from .quality_views import csv_reply
from .trace_cases import capture_sources

STATUSES=['待报工核对','待计划核对','待现场确认','演练已核对']
def can_follow(user):return access.role(user) in ['admin','analyst','quality','operations']
def response(request,data):
    r=reply(eng.safe(data,access.can_money(request.user)));r['Cache-Control']='no-store';return r
def context(request):
    f=eng.filters(request.GET);return eng.current(f),f

@api()
@transaction.atomic
def board(request):
    d,f=context(request);rows=d.selected();selected=[r for r in rows if f['stage'] in r['flags']];page=max(1,int(request.GET.get('page',1)))
    return response(request,{'filters':f,'summary':d.summary(rows),'breakdown':d.breakdown(rows),'rows':selected[(page-1)*25:page*25],'total':len(selected),'page':page,'size':25,'stages':eng.STAGES[f['tab']],'facets':{k:sum(k in r['flags'] for r in rows) for k in eng.STAGES[f['tab']]},'global_issues':d.global_issues,'as_of':d.cutoff,'note':eng.NOTE,'can_money':access.can_money(request.user),'options':{'families':sorted({r.get('family','') for r in d.data['products']}),'processes':sorted({r.get('process','') for r in d.data['operations']}),'kinds':sorted({r['row']['kind'] for r in getattr(d,f['tab']).values()}) if f['tab']!='work_orders' else []}})

@api()
@transaction.atomic
def detail(request,kind,key):
    d,f=context(request);obj=d.detail(kind,key)
    return response(request,{**obj,'filters':f,'as_of':d.cutoff,'note':eng.NOTE,'can_money':access.can_money(request.user),'can_follow_up':can_follow(request.user),'data_revision':list(analytics.revision()),'follow_up':follow_info(IssueDisposition.objects.filter(key=f'manufacturing:{kind}:{key}').first())})

@api()
@transaction.atomic
def evidence(request,kind,key):
    d,_=context(request);obj=d.detail(kind,key);rows=capture_sources({'sources':obj['sources']});page=max(1,int(request.GET.get('page',1)))
    return response(request,{'rows':rows[(page-1)*40:page*40],'total':len(rows),'page':page,'size':40,'can_download_original':access.can_import(request.user)})

@api(('POST',))
@transaction.atomic
def follow_up(request,kind,key):
    require(can_follow(request.user));d,f=context(request);obj=d.detail(kind,key);p=body(request)
    if set(p)!={'status','version','owner','note','due_date','data_revision'}:raise ValueError('跟进字段不完整或存在未知字段')
    if type(p['version']) is not int or p['version']<0 or p['status'] not in STATUSES:raise ValueError('跟进状态或版本无效')
    if p['status']=='演练已核对':require(access.role(request.user) in ['admin','quality'],'演练核对由质量岗位或管理员确认')
    for k,lo,hi in [('owner',1,150),('note',5,2000)]:
        if not isinstance(p[k],str) or not lo<=len(p[k].strip())<=hi:raise ValueError('请填写责任岗位和5至2000字的跟进依据')
    due=p['due_date'] or None
    if due and (not isinstance(due,str) or date.fromisoformat(due).isoformat()!=due):raise ValueError('期限须为YYYY-MM-DD')
    if p['data_revision']!=list(analytics.revision()):return reply({'error':'业务来源已变化，请重新读取'},409)
    objkey=f'manufacturing:{kind}:{key}';item=IssueDisposition.objects.select_for_update().filter(key=objkey).first();before=follow_info(item)
    if before['version']!=p['version']:return reply({'error':'跟进版本已变化，请重新读取'},409)
    values=dict(status=p['status'],owner=p['owner'].strip(),note=p['note'].strip(),due_date=due,version=p['version']+1,updated_by=request.user.username,updated_at=timezone.now())
    if item:
        if IssueDisposition.objects.filter(pk=item.pk,version=p['version']).update(**values)!=1:return reply({'error':'跟进版本冲突'},409)
        item.refresh_from_db()
    else:item=IssueDisposition.objects.create(key=objkey,**values)
    serial=lambda x:json.loads(json.dumps(x,ensure_ascii=False,default=str))
    AuditEvent.objects.create(action='manufacturing.followup',actor=request.user.username,object_type='ManufacturingCoordination',object_id=objkey,detail={'before':serial(before),'after':serial(follow_info(item)),'data_revision':p['data_revision'],'source_issues':obj['row']['issues'],'business_facts_changed':False})
    return response(request,{'follow_up':follow_info(item),'notice':'已保存独立协调记录，工单、报工、批次与SN事实未修改。'})

@api()
def history(request,kind,key):
    d,_=context(request);d.detail(kind,key)
    return response(request,{'rows':list(AuditEvent.objects.filter(object_type='ManufacturingCoordination',object_id=f'manufacturing:{kind}:{key}').order_by('-id').values('actor','created_at','detail'))})

@api()
@transaction.atomic
def export(request):
    d,f=context(request);rows=[eng.safe(r,access.can_money(request.user)) for r in d.selected() if f['stage'] in r['flags']]
    fields={'work_orders':[('id','工单号'),('product_id','配置编码'),('planned_start','计划开工'),('planned_end','计划完工'),('date_valid','计划日期可核对'),('status','台账状态'),('planned_qty','计划台数'),('assembled_qty','已登记装配SN数'),('assembly_gap','计划减装配记录'),('events','报工事件数'),('valid_events','有效事件数'),('batches','批次数')],
      'batches':[('id','批次号'),('work_order_id','工单号'),('kind','分支类型'),('qty','批次数量'),('route_steps','分支路线步数'),('done_steps','有有效完成记录步数'),('assembly_refs','装配SN引用数'),('unreferenced_qty','末工序合格减装配引用'),('interval_minutes','已完成分支工序间隔分钟')],
      'operations':[('id','报工事件号'),('work_order_id','工单号'),('object_id','对象编号'),('kind','对象类型'),('process','工序'),('equipment_id','设备编码'),('resource_id','资源位'),('started','开始'),('completed_as_of','截止有效完成'),('calculated_state','核对状态'),('input_qty','登记投入数'),('output_as_of','截止可核对合格数'),('rework_qty','原记录返工子集数'),('elapsed_minutes','截止有效自然历时分钟')]}[f['tab']]
    data=[['制造流转模拟工作台','截止',d.cutoff,'筛选',json.dumps(f,ensure_ascii=False)],['说明',eng.NOTE],[label for _,label in fields]+['待核对事项']]+[[r.get(k) for k,_ in fields]+['；'.join(r['issues'])] for r in rows]
    AuditEvent.objects.create(action='manufacturing.export',actor=request.user.username,object_type='ManufacturingBoard',object_id=f['tab'],detail={'filters':f,'rows':len(rows)})
    result=csv_reply(data,'manufacturing-'+f['tab']);result['Cache-Control']='no-store';return result
