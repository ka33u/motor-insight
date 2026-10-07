import json
from datetime import date
from django.db import transaction
from django.utils import timezone
from . import service_board as service, quality_board, access, analytics
from .views import api, reply, body, require
from .models import IssueDisposition, AuditEvent, Record
from .delivery_views import follow_info
from .quality_views import csv_reply
from .trace_cases import capture_sources

STATUSES=['待资料核对','待现场排查','待技术复核','演练已核验']
def can_follow(user):return access.role(user) in ['admin','analyst','operations','quality']
def response(request,value):
    r=reply(service.safe(value,access.can_money(request.user)));r['Cache-Control']='no-store';return r
def context(request):
    f=service.filters(request.GET);return service.current(f),f

@api()
@transaction.atomic
def board(request):
    d,f=context(request);rows=d.selected();selected=[r for r in rows if f['stage'] in r['flags']];page=max(1,int(request.GET.get('page',1)))
    return response(request,{'filters':f,'summary':d.summary(rows),'breakdown':d.breakdown(rows),'rows':selected[(page-1)*25:page*25],'total':len(selected),'page':page,'size':25,'cohort_cases':len(d.selected_cases()),
        'stages':service.STAGES[f['tab']],'facets':{k:sum(k in r['flags'] for r in rows) for k in service.STAGES[f['tab']]},'global_issues':d.global_issues,'as_of':d.cutoff,'note':service.NOTE,'can_money':access.can_money(request.user),
        'options':{'customers':[{'id':r['id'],'name':r['name']} for r in d.data['customers']], 'families':sorted({r.get('family','') for r in d.data['products']}),'products':[{'id':r['id'],'model':r.get('model','')} for r in d.data['products']],**{k:sorted({r['row'].get(field,'') for r in d.cases.values()}) for k,field in [('failures','failure'),('environments','environment')]}}})

def full_detail(d,key):
    obj={**d.detail(key)};uid=obj['row'].get('unit_id')
    if uid in d.idx['units']:
        try:q=quality_board.current().detail(uid)
        except Record.DoesNotExist:
            obj['quality']=None
            return obj
        obj['quality']={k:q[k] for k in ['unit','product','sessions','releases','shipments','nonconformities','as_of','notice']}
        obj['sources']=list({(x['dataset'],x['key']):x for x in obj['sources']+q['sources']}.values())
    else:obj['quality']=None
    return obj

@api()
@transaction.atomic
def detail(request,key):
    d,f=context(request);obj=full_detail(d,key)
    return response(request,{**obj,'filters':f,'as_of':d.cutoff,'note':service.NOTE,'data_revision':list(analytics.revision()),'can_money':access.can_money(request.user),'can_follow_up':can_follow(request.user),'follow_up':follow_info(IssueDisposition.objects.filter(key='service:'+key).first())})

@api()
@transaction.atomic
def evidence(request,key):
    d,_=context(request);rows=capture_sources(full_detail(d,key));page=max(1,int(request.GET.get('page',1)))
    return response(request,{'rows':rows[(page-1)*40:page*40],'total':len(rows),'page':page,'size':40,'can_download_original':access.can_import(request.user)})

@api(('POST',))
@transaction.atomic
def follow_up(request,key):
    require(can_follow(request.user));d,_=context(request);obj=d.detail(key);p=body(request)
    if set(p)!={'status','version','owner','note','due_date','data_revision'}:raise ValueError('跟进字段不完整或包含未知字段')
    if type(p['version']) is not int or p['version']<0 or p['status'] not in STATUSES:raise ValueError('跟进状态或版本无效')
    if p['status']=='演练已核验':require(access.role(request.user) in ['admin','quality'],'模拟核验由质量岗位或管理员确认')
    for k,lo,hi in [('owner',1,150),('note',5,2000)]:
        if not isinstance(p[k],str) or not lo<=len(p[k].strip())<=hi:raise ValueError('请填写负责人及5至2000字的核对依据')
    due=p['due_date'] or None
    if due and (not isinstance(due,str) or date.fromisoformat(due).isoformat()!=due):raise ValueError('期限须为YYYY-MM-DD')
    if p['data_revision']!=list(analytics.revision()):return reply({'error':'来源已变化，请重新读取'},409)
    objkey='service:'+key;item=IssueDisposition.objects.select_for_update().filter(key=objkey).first();before=follow_info(item)
    if p['version']!=before['version']:return reply({'error':'跟进版本冲突，请重新读取'},409)
    values=dict(status=p['status'],owner=p['owner'].strip(),note=p['note'].strip(),due_date=due,version=p['version']+1,updated_by=request.user.username,updated_at=timezone.now())
    if item:
        if IssueDisposition.objects.filter(pk=item.pk,version=p['version']).update(**values)!=1:return reply({'error':'跟进版本冲突'},409)
        item.refresh_from_db()
    else:item=IssueDisposition.objects.create(key=objkey,**values)
    serial=lambda x:json.loads(json.dumps(x,ensure_ascii=False,default=str))
    AuditEvent.objects.create(action='service.followup',actor=request.user.username,object_type='ServiceCoordination',object_id=objkey,detail={'before':serial(before),'after':serial(follow_info(item)),'data_revision':p['data_revision'],'source_issues':obj['row']['issues'],'business_facts_changed':False})
    return response(request,{'follow_up':follow_info(item),'notice':'已保存售后协调记录；未修改原服务单、任务完成、客户验收或质量责任。'})

@api()
def history(request,key):
    d,_=context(request);d.detail(key)
    return response(request,{'rows':list(AuditEvent.objects.filter(object_type='ServiceCoordination',object_id='service:'+key).order_by('-id').values('actor','created_at','detail'))})

@api()
@transaction.atomic
def export(request):
    d,f=context(request);rows=[service.safe(r,access.can_money(request.user)) for r in d.selected() if f['stage'] in r['flags']]
    fields=[('id','售后单号'),('unit_id','SN'),('customer_id','服务客户'),('product_id','产品配置'),('failure','问题类别'),('reported','报修时间'),('response_hours','首次响应自然小时'),('closed_hours','关闭自然小时'),('open_hours','截止未关闭自然小时'),('calculated_state','截止状态')]+([('cost_cents','台账服务费用分')] if access.can_money(request.user) else []) if f['tab']=='cases' else [('id','任务号'),('service_id','售后单号'),('unit_id','SN'),('kind','任务类型'),('owner_id','责任工号'),('created','建立时间'),('due','约定完成时间'),('completed_as_of','截止已完成时间'),('calculated_state','截止状态'),('overdue_hours','未完成逾期小时'),('description','任务说明')]
    data=[['售后模拟工作台','截止',d.cutoff,'筛选',json.dumps(f,ensure_ascii=False)],['说明',service.NOTE+' 费用是当前单据累计台账，不是按报修期发生的财务支出。'],[label for _,label in fields]+['清单状态','待核对事项']]
    data += [[r.get(k) for k,_ in fields]+['；'.join(service.STAGES[f['tab']][flag] for flag in r['flags'] if flag!='all'),'；'.join(r['issues'])] for r in rows]
    AuditEvent.objects.create(action='service.export',actor=request.user.username,object_type='ServiceBoard',object_id=f['tab'],detail={'filters':f,'rows':len(rows)})
    r=csv_reply(data,'service-'+f['tab']);r['Cache-Control']='no-store';return r
