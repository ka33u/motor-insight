import json
from datetime import date
from django.db import transaction
from django.utils import timezone
from . import workforce,access,analytics
from .views import api,reply,body,require
from .models import IssueDisposition,AuditEvent
from .delivery_views import follow_info
from .quality_views import csv_reply
from .trace_cases import capture_sources

STATUSES=['待核对','待补工时依据','待授权复核','待培训安排','演练已核验']
def permit(user):require(access.allowed(user,'attendance') and access.allowed(user,'skills'),'人员与技能工作台仅供具有人员数据权限的岗位使用')
def context(request):
    permit(request.user);f=workforce.filters(request.GET);return workforce.current(f),f
def response(data):
    r=reply(data);r['Cache-Control']='no-store';return r

@api()
@transaction.atomic
def board(request):
    d,f=context(request);rows=d.selected();chosen=[r for r in rows if f['stage'] in r['flags']];page=max(1,int(request.GET.get('page',1)));summary=d.summary(rows)
    return response({'filters':f,'summary':summary,'breakdown':d.breakdown(rows),'rows':chosen[(page-1)*25:page*25],'total':len(chosen),'page':page,'size':25,'stages':workforce.STAGES[f['tab']],
     'facets':{k:sum(k in r['flags'] for r in rows) for k in workforce.STAGES[f['tab']]},'as_of':d.cutoff,'note':workforce.NOTE,'global_issues':d.global_issues,
     'options':{'departments':[{'id':r['id'],'name':r['name']} for r in d.index['departments'].values()],'processes':sorted({r['process'] for r in d.grants.values()}|{r.get('process','') for r in d.index['production_resources'].values()})}})

@api()
@transaction.atomic
def detail(request,eid):
    d,f=context(request);p=d.detail(eid)
    return response({**p,'follow_up':follow_info(IssueDisposition.objects.filter(key='workforce:'+eid).first()),'data_revision':list(analytics.revision()),'filters':f,'as_of':d.cutoff,'note':workforce.NOTE})

@api()
@transaction.atomic
def evidence(request,eid):
    d,_=context(request);rows=capture_sources(d.detail(eid));page=max(1,int(request.GET.get('page',1)))
    return response({'rows':rows[(page-1)*40:page*40],'total':len(rows),'page':page,'size':40,'can_download_original':access.can_import(request.user)})

@api(('POST',))
@transaction.atomic
def follow_up(request,eid):
    d,_=context(request);obj=d.detail(eid);p=body(request)
    if set(p)!={'status','version','owner','note','due_date','data_revision'}:raise ValueError('跟进字段不完整或包含未知字段')
    if type(p['version']) is not int or p['version']<0 or p['status'] not in STATUSES:raise ValueError('跟进状态或版本无效')
    for k,lo,hi in [('owner',1,150),('note',5,2000)]:
        if not isinstance(p[k],str) or not lo<=len(p[k].strip())<=hi:raise ValueError('请填写负责人及5至2000字的核对依据')
    due=p['due_date'] or None
    if due and (not isinstance(due,str) or date.fromisoformat(due).isoformat()!=due):raise ValueError('期限格式须为YYYY-MM-DD')
    if p['data_revision']!=list(analytics.revision()):return reply({'error':'来源已变化，请重新读取'},409)
    key='workforce:'+eid;item=IssueDisposition.objects.select_for_update().filter(key=key).first();before=follow_info(item)
    if p['version']!=before['version']:return reply({'error':'跟进已被更新，请重新读取'},409)
    values=dict(status=p['status'],owner=p['owner'].strip(),note=p['note'].strip(),due_date=due,version=p['version']+1,updated_by=request.user.username,updated_at=timezone.now())
    if item:
        if IssueDisposition.objects.filter(pk=item.pk,version=p['version']).update(**values)!=1:return reply({'error':'跟进版本冲突'},409)
        item.refresh_from_db()
    else:item=IssueDisposition.objects.create(key=key,**values)
    serial=lambda x:json.loads(json.dumps(x,ensure_ascii=False,default=str))
    AuditEvent.objects.create(action='workforce.followup',actor=request.user.username,object_type='WorkforceCoordination',object_id=key,detail={'before':serial(before),'after':serial(follow_info(item)),'data_revision':p['data_revision'],'business_facts_changed':False,'source_issues':obj['row']['issues']})
    return response({'follow_up':follow_info(item),'notice':'已保存核对跟进；不会修改工时、授权、排班或人员状态。'})

@api()
def history(request,eid):
    d,_=context(request);d.detail(eid)
    return response({'rows':list(AuditEvent.objects.filter(object_type='WorkforceCoordination',object_id='workforce:'+eid).order_by('-id').values('actor','created_at','detail'))})

@api()
@transaction.atomic
def export(request):
    d,f=context(request);rows=[r for r in d.selected() if f['stage'] in r['flags']]
    fields=[('id','工号'),('name','姓名'),('department','部门'),('active','当前在职'),('days','有记录天数'),('total_hours','可核对班次小时'),('overtime_hours','其中加班小时'),('labor_hours','可核对作业明细小时'),('calendar_hours','资源排班去重小时'),('operation_count','报工事件数')] if f['tab']=='hours' else [('id','授权编号'),('employee_id','工号'),('name','姓名'),('department','部门'),('process','工序'),('level','台账等级'),('approved','批准日'),('expires','有效截至'),('status','台账状态'),('effective','当前台账日期有效'),('days_to_due','距到期天数')]
    data=[['人员与技能模拟工作台','截止',d.cutoff,'筛选',json.dumps(f,ensure_ascii=False)],['说明',workforce.NOTE],[label for _,label in fields]+['清单状态','待核对事项']]
    data += [[r.get(k) for k,_ in fields]+['；'.join(workforce.STAGES[f['tab']][x] for x in r['flags'] if x!='all'),'；'.join(r['issues'])] for r in rows]
    AuditEvent.objects.create(action='workforce.export',actor=request.user.username,object_type='WorkforceBoard',object_id=f['tab'],detail={'filters':f,'rows':len(rows)})
    r=csv_reply(data,'workforce-'+f['tab']);r['Cache-Control']='no-store';return r
