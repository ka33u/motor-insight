import json
from datetime import date
from django.db import transaction
from django.utils import timezone
from . import process_quality as eng,access,analytics
from .models import AuditEvent,IssueDisposition
from .views import api,reply,body,require
from .delivery_views import follow_info
from .quality_views import csv_reply
from .trace_cases import capture_sources

STATUSES=['待补检验记录','待工艺核对','待质量复核','演练已核对']
def response(request,d):
    r=reply(eng.safe(d,access.can_money(request.user)));r['Cache-Control']='no-store';return r
def context(request):
    f=eng.filters(request.GET);return eng.current(f),f
def editable(user):return access.role(user) in ['admin','analyst','quality','operations']

@api()
@transaction.atomic
def board(request):
    d,f=context(request);allrows=d.selected();rows=d.selected(stage=True);page=max(1,int(request.GET.get('page',1)));parameters=d.parameters() if f['tab']=='parameters' else None
    if parameters:
        rows=parameters.pop('rows');parameters['total']=len(rows)
    return response(request,dict(filters=f,rows=rows[(page-1)*25:page*25],total=len(rows),page=page,size=25,summary=d.summary(allrows),breakdown=d.breakdown(allrows),parameters=parameters,facets={k:sum(k in r['flags'] for r in allrows) for k in eng.STATES},stages=eng.STATES,orphans=d.orphans,as_of=d.cutoff,note=eng.NOTE,options={key:sorted({str(r.get(field) or '') for r in (o['row'] for o in d.plans.values())}) for key,field in [('families','family'),('processes','process'),('branches','branch'),('equipment','equipment_id')]}))

@api()
@transaction.atomic
def detail(request,key):
    d,_=context(request);obj=d.detail(key)
    return response(request,{**obj,'as_of':d.cutoff,'note':eng.NOTE,'can_follow_up':editable(request.user),'data_revision':list(analytics.revision()),'follow_up':follow_info(IssueDisposition.objects.filter(key='process-quality:'+key).first())})

@api()
@transaction.atomic
def evidence(request,key):
    d,_=context(request);obj=d.detail(key);rows=capture_sources({'sources':obj['sources']});page=max(1,int(request.GET.get('page',1)))
    return response(request,dict(rows=rows[(page-1)*40:page*40],total=len(rows),page=page,size=40,can_download_original=access.can_import(request.user)))

@api(('POST',))
@transaction.atomic
def follow_up(request,key):
    require(editable(request.user));d,_=context(request);obj=d.detail(key);p=body(request)
    if set(p)!={'status','version','owner','note','due_date','data_revision'}:raise ValueError('跟进字段不完整或有未知字段')
    if type(p['version']) is not int or p['version']<0 or p['status'] not in STATUSES:raise ValueError('状态或版本无效')
    if p['status']=='演练已核对':require(access.role(request.user) in ['admin','quality'],'仅质量岗位或管理员可确认演练核对')
    for k,lo,hi in [('owner',1,150),('note',5,2000)]:
        if not isinstance(p[k],str) or not lo<=len(p[k].strip())<=hi:raise ValueError('填写责任岗位及5至2000字的核对依据')
    due=p['due_date'] or None
    if due and (not isinstance(due,str) or date.fromisoformat(due).isoformat()!=due):raise ValueError('期限须为YYYY-MM-DD')
    if p['data_revision']!=list(analytics.revision()):return reply({'error':'业务数据已变化，请重新读取'},409)
    identity='process-quality:'+key;item=IssueDisposition.objects.select_for_update().filter(key=identity).first();before=follow_info(item)
    if before['version']!=p['version']:return reply({'error':'协调版本已变化，请重新读取'},409)
    values=dict(status=p['status'],owner=p['owner'].strip(),note=p['note'].strip(),due_date=due,version=p['version']+1,updated_by=request.user.username,updated_at=timezone.now())
    if item:
        if IssueDisposition.objects.filter(pk=item.pk,version=p['version']).update(**values)!=1:return reply({'error':'协调版本冲突'},409)
        item.refresh_from_db()
    else:item=IssueDisposition.objects.create(key=identity,**values)
    serial=lambda x:json.loads(json.dumps(x,default=str,ensure_ascii=False))
    AuditEvent.objects.create(action='process_quality.followup',actor=request.user.username,object_type='ProcessQualityCoordination',object_id=identity,detail={'before':serial(before),'after':serial(follow_info(item)),'data_revision':p['data_revision'],'business_facts_changed':False,'source_issues':obj['row']['issues']})
    return response(request,{'follow_up':follow_info(item),'notice':'协调记录已保存；未修改实测、规范、报工或批准状态。'})

@api()
def history(request,key):
    d,_=context(request);d.detail(key)
    return response(request,{'rows':list(AuditEvent.objects.filter(object_type='ProcessQualityCoordination',object_id='process-quality:'+key).order_by('-id').values('actor','created_at','detail'))})

@api()
@transaction.atomic
def export(request):
    d,f=context(request)
    if f['tab']=='parameters':
        p=d.parameters();rows=p['rows'];fields=[('id','测量记录号'),('plan_id','应检计划号'),('check_id','检验记录号'),('checked','检验时间'),('kind','检验类型'),('sample','样本标识'),('object_id','对象编号'),('equipment_id','设备编码'),('spec_id','规范项目号'),('value','实测值'),('unit','单位'),('lsl','下限'),('usl','上限'),('out','是否超限'),('check_state','检验记录状态')]
    else:
        rows=d.selected(stage=True);fields=[('id','应检计划号'),('operation_id','报工事件号'),('work_order_id','工单号'),('object_id','对象编号'),('product_id','配置编码'),('process','工序'),('branch','分支'),('stage','检验类型'),('due','应检时间'),('spec_version','规范版本'),('state','当前核对状态'),('first_state','首次记录状态'),('latest_state','最新记录状态'),('checks','非作废检验次数')]
    data=[['工序检验模拟工作台','截止',d.cutoff,'筛选',json.dumps(f,ensure_ascii=False)],['说明',eng.NOTE],[label for _,label in fields]+['资料核对事项']]+[[r.get(k) for k,_ in fields]+['；'.join(r.get('issues',[]))] for r in rows]
    AuditEvent.objects.create(action='process_quality.export',actor=request.user.username,object_type='ProcessQualityBoard',object_id=f['tab'],detail={'filters':f,'rows':len(rows)})
    r=csv_reply(data,'process-quality-'+f['tab']);r['Cache-Control']='no-store';return r
