import json
from datetime import date
from django.db import transaction
from django.utils import timezone
from . import energy_board as energy, access, analytics
from .views import api, reply, body, require
from .models import IssueDisposition, AuditEvent
from .delivery_views import follow_info
from .quality_views import csv_reply
from .trace_cases import capture_sources

STATUSES=['待计量核对','待现场核查','待源系统复核','演练已核验']
def can_follow(user):return access.role(user) in ['admin','analyst','operations','quality']
def response(request,value):
    r=reply(energy.safe(value,access.can_money(request.user)));r['Cache-Control']='no-store';return r
def context(request):
    f=energy.filters(request.GET);return energy.current(f),f

@api()
@transaction.atomic
def board(request):
    d,f=context(request);rows=d.selected();selected=[r for r in rows if f['stage'] in r['flags']];page=max(1,int(request.GET.get('page',1)))
    return response(request,{'filters':f,'summary':d.summary(rows),'breakdown':d.breakdown(rows),'rows':selected[(page-1)*25:page*25],'total':len(selected),'page':page,'size':25,
        'stages':energy.STAGES[f['tab']],'facets':{k:sum(k in r['flags'] for r in rows) for k in energy.STAGES[f['tab']]},'global_issues':d.global_issues,'as_of':d.cutoff,'note':energy.NOTE,'can_money':access.can_money(request.user),
        'options':{'workshops':sorted({r.get('workshop','') for ds in ['energy','ehs'] for r in d.data[ds]}),'meters':[{'id':k,'workshop':v['row']['workshop']} for k,v in d.meters.items()]}})

@api()
@transaction.atomic
def detail(request,kind,key):
    d,f=context(request);obj=d.detail(kind,key)
    return response(request,{**obj,'filters':f,'as_of':d.cutoff,'note':energy.NOTE,'data_revision':list(analytics.revision()),'can_money':access.can_money(request.user),'can_follow_up':kind!='assembly' and can_follow(request.user),'follow_up':follow_info(IssueDisposition.objects.filter(key='energy:'+kind+':'+key).first())})

@api()
@transaction.atomic
def evidence(request,kind,key):
    d,_=context(request);rows=capture_sources(d.detail(kind,key));page=max(1,int(request.GET.get('page',1)))
    return response(request,{'rows':rows[(page-1)*40:page*40],'total':len(rows),'page':page,'size':40,'can_download_original':access.can_import(request.user)})

@api(('POST',))
@transaction.atomic
def follow_up(request,kind,key):
    require(can_follow(request.user));require(kind in ['meter','ehs'],'仅可为表计或整改事项保存核对记录')
    d,_=context(request);obj=d.detail(kind,key);p=body(request)
    if set(p)!={'status','version','owner','note','due_date','data_revision'}:raise ValueError('跟进字段不完整或包含未知字段')
    if type(p['version']) is not int or p['version']<0 or p['status'] not in STATUSES:raise ValueError('跟进状态或版本无效')
    for k,lo,hi in [('owner',1,150),('note',5,2000)]:
        if not isinstance(p[k],str) or not lo<=len(p[k].strip())<=hi:raise ValueError('请填写负责人及5至2000字的核对依据')
    due=p['due_date'] or None
    if due and (not isinstance(due,str) or date.fromisoformat(due).isoformat()!=due):raise ValueError('期限须为YYYY-MM-DD')
    if p['data_revision']!=list(analytics.revision()):return reply({'error':'来源已变化，请重新读取'},409)
    objkey='energy:'+kind+':'+key;item=IssueDisposition.objects.select_for_update().filter(key=objkey).first();before=follow_info(item)
    if p['version']!=before['version']:return reply({'error':'跟进版本冲突，请重新读取'},409)
    values=dict(status=p['status'],owner=p['owner'].strip(),note=p['note'].strip(),due_date=due,version=p['version']+1,updated_by=request.user.username,updated_at=timezone.now())
    if item:
        if IssueDisposition.objects.filter(pk=item.pk,version=p['version']).update(**values)!=1:return reply({'error':'跟进版本冲突'},409)
        item.refresh_from_db()
    else:item=IssueDisposition.objects.create(key=objkey,**values)
    serial=lambda x:json.loads(json.dumps(x,ensure_ascii=False,default=str))
    AuditEvent.objects.create(action='energy.followup',actor=request.user.username,object_type='EnergyCoordination',object_id=objkey,detail={'before':serial(before),'after':serial(follow_info(item)),'data_revision':p['data_revision'],'source_issues':obj['row']['issues'],'business_facts_changed':False})
    return response(request,{'follow_up':follow_info(item),'notice':'已保存核对跟进；未修改电量、电价或安环复核关闭状态。'})

@api()
def history(request,kind,key):
    d,_=context(request);d.detail(kind,key)
    return response(request,{'rows':list(AuditEvent.objects.filter(object_type='EnergyCoordination',object_id='energy:'+kind+':'+key).order_by('-id').values('actor','created_at','detail'))})

@api()
@transaction.atomic
def export(request):
    d,f=context(request);rows=[energy.safe(r,access.can_money(request.user)) for r in d.selected() if f['stage'] in r['flags']]
    fields=[('id','表计'),('workshop','车间'),('readings','区间记录数'),('kwh','可核对kWh'),('covered_hours','记录覆盖小时'),('expected_hours','窗口小时'),('coverage_pct','时间覆盖%')]+([('cost_cents','按记录电价估算分')] if access.can_money(request.user) else []) if f['tab']=='meters' else [('id','安环事项'),('workshop','车间'),('kind','类型'),('description','事项说明'),('found','发现日期'),('due','整改期限'),('closed_as_of','截止已关闭日期'),('calculated_state','截止状态'),('owner_id','责任工号'),('open_days','未关闭天数'),('overdue_days','逾期天数'),('elapsed_days','关闭历时天数')]
    data=[['能源安环模拟工作台','截止',d.cutoff,'筛选',json.dumps(f,ensure_ascii=False)],['说明',energy.NOTE],[label for _,label in fields]+['清单状态','待核对事项']]
    data += [[r.get(k) for k,_ in fields]+['；'.join(energy.STAGES[f['tab']][flag] for flag in r['flags'] if flag!='all'),'；'.join(r['issues']+r.get('cost_issues',[]))] for r in rows]
    AuditEvent.objects.create(action='energy.export',actor=request.user.username,object_type='EnergyBoard',object_id=f['tab'],detail={'filters':f,'rows':len(rows)})
    r=csv_reply(data,'energy-'+f['tab']);r['Cache-Control']='no-store';return r
