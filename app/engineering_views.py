import json
from datetime import date
from django.db import transaction
from django.utils import timezone
from . import engineering as eng,access,analytics
from .views import api,reply,body,require
from .models import IssueDisposition,AuditEvent
from .delivery_views import follow_info
from .quality_views import csv_reply
from .trace_cases import capture_sources

STATUSES=['待资料补齐','待工艺复核','待执行反馈','演练已核对']
def can_follow(user):return access.role(user) in ['admin','analyst','quality','operations']
def response(request,data):
    r=reply(eng.safe(data,access.can_money(request.user)));r['Cache-Control']='no-store';return r
def context(request):
    f=eng.filters(request.GET);return eng.current(f),f

@api()
@transaction.atomic
def board(request):
    d,f=context(request);rows=d.selected();selected=[r for r in rows if f['stage'] in r['flags']];page=max(1,int(request.GET.get('page',1)))
    return response(request,{'filters':f,'summary':d.summary(rows),'breakdown':d.breakdown(rows),'rows':selected[(page-1)*25:page*25],'total':len(selected),'page':page,'size':25,'stages':eng.STAGES[f['tab']],'facets':{k:sum(k in r['flags'] for r in rows) for k in eng.STAGES[f['tab']]},'global_issues':d.global_issues,'as_of':d.cutoff,'note':eng.NOTE,'can_money':access.can_money(request.user),'options':{'families':sorted({r.get('family','') for r in d.data['products']}),'products':[{'id':r['id'],'model':r.get('model','')} for r in d.data['products']],'owners':[{'id':key,'name':d.idx['employees'].get(key,{}).get('name','未匹配')} for key in sorted({r.get('owner_id') for r in d.data['projects']}|{r.get('approved_by') for r in d.data['engineering_changes']}) if key]}})

@api()
@transaction.atomic
def detail(request,kind,key):
    d,f=context(request);obj=d.detail(kind,key)
    return response(request,{**obj,'filters':f,'as_of':d.cutoff,'note':eng.NOTE,'can_money':access.can_money(request.user),'can_follow_up':can_follow(request.user),'data_revision':list(analytics.revision()),'follow_up':follow_info(IssueDisposition.objects.filter(key=f'engineering:{kind}:{key}').first())})

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
    objkey=f'engineering:{kind}:{key}';item=IssueDisposition.objects.select_for_update().filter(key=objkey).first();before=follow_info(item)
    if before['version']!=p['version']:return reply({'error':'跟进版本已变化，请重新读取'},409)
    values=dict(status=p['status'],owner=p['owner'].strip(),note=p['note'].strip(),due_date=due,version=p['version']+1,updated_by=request.user.username,updated_at=timezone.now())
    if item:
        if IssueDisposition.objects.filter(pk=item.pk,version=p['version']).update(**values)!=1:return reply({'error':'跟进版本冲突'},409)
        item.refresh_from_db()
    else:item=IssueDisposition.objects.create(key=objkey,**values)
    serial=lambda x:json.loads(json.dumps(x,ensure_ascii=False,default=str))
    AuditEvent.objects.create(action='engineering.followup',actor=request.user.username,object_type='EngineeringCoordination',object_id=objkey,detail={'before':serial(before),'after':serial(follow_info(item)),'data_revision':p['data_revision'],'source_issues':obj['row']['issues'],'business_facts_changed':False})
    return response(request,{'follow_up':follow_info(item),'notice':'已保存独立协调记录，原项目、变更执行和产品批准状态未修改。'})

@api()
def history(request,kind,key):
    d,_=context(request);d.detail(kind,key)
    return response(request,{'rows':list(AuditEvent.objects.filter(object_type='EngineeringCoordination',object_id=f'engineering:{kind}:{key}').order_by('-id').values('actor','created_at','detail'))})

@api()
@transaction.atomic
def export(request):
    d,f=context(request);rows=[eng.safe(r,access.can_money(request.user)) for r in d.selected() if f['stage'] in r['flags']]
    fields={'products':[('id','配置编码'),('model','型号'),('family','产品族'),('bom_version','登记BOM版本'),('route_version','登记路线版本'),('bom_rows','截止生效BOM行'),('route_rows','当前路线行'),('work_orders','关联工单数'),('version_differences','工单版本不同数')],
      'projects':[('id','项目编号'),('name','项目名称'),('product_id','配置编码'),('owner_id','责任工号'),('planned_end','计划结束'),('closed_as_of','截止已有结束'),('calculated_state','截止状态'),('milestones','阶段数'),('completed_milestones','有完成记录阶段数'),('overdue_milestones','未完成逾期阶段数'),('days_overdue','项目逾期自然日')],
      'changes':[('id','变更单号'),('product_id','配置编码'),('from_version','原版本号'),('to_version','目标版本号'),('effective','登记生效日'),('status','原单批准标记'),('actions','执行任务数'),('completed_actions','有完成记录任务数'),('pending_actions','未完成任务数'),('overdue_actions','逾期未完成任务数'),('before_bom_rows','原号BOM明细数'),('after_bom_rows','目标号BOM明细数')]}[f['tab']]
    if f['tab']=='projects' and access.can_money(request.user):fields+=[('budget_cents','项目台账预算分')]
    data=[['研发工艺模拟工作台','截止',d.cutoff,'筛选',json.dumps(f,ensure_ascii=False)],['说明',eng.NOTE],[label for _,label in fields]+['待核对事项']]+[[r.get(k) for k,_ in fields]+['；'.join(r['issues'])] for r in rows]
    AuditEvent.objects.create(action='engineering.export',actor=request.user.username,object_type='EngineeringBoard',object_id=f['tab'],detail={'filters':f,'rows':len(rows)})
    result=csv_reply(data,'engineering-'+f['tab']);result['Cache-Control']='no-store';return result
