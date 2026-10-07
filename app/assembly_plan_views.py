import hashlib,json
from pathlib import Path
from collections import defaultdict
from django.db import transaction
from django.utils import timezone
from . import assembly_plans as p,analytics,access
from .views import api,reply,body,require
from .models import AuditEvent,IssueDisposition
from .delivery_views import follow_info
from .trace_cases import capture_sources
from .quality_views import csv_reply

STATES={'confirmed':'资料已确认','unconfirmed':'资料待核对','in_progress':'当日进行中','future':'尚未开始'}
STATUSES=['待核对','计划原因核查中','责任岗位协调中','待效果复查','演练已复查']
def response(data,status=200):
    r=reply(data,status);r['Cache-Control']='no-store';return r
def receipt():return hashlib.sha256(json.dumps([list(analytics.revision()),analytics.AS_OF,hashlib.sha256(Path(p.__file__).read_bytes()).hexdigest()],ensure_ascii=False).encode()).hexdigest()
def check(request):
    if request.GET.get('receipt')!=receipt():
        from .import_review import ReviewConflict
        raise ReviewConflict('计划、装配资料或计算已变化，请重新读取')
def page(params):
    x=int(params.get('page',1))
    if not 1<=x<=100000:raise ValueError('页码无效')
    return x
def writable(user):return access.role(user) in ['admin','analyst','operations']
def day_info(d):return {k:v for k,v in d.items() if k!='rows'}

@api()
@transaction.atomic
def board(request):
    d=p.Plans();f=p.params(request.GET);rows=d.selected(f);by_day=defaultdict(list)
    for r in rows:by_day[r['date']].append(r)
    days=[]
    for date_key,info in d.days.items():
        if (f['from'] and date_key<f['from']) or (f['to'] and date_key>f['to']):continue
        if not by_day[date_key] and (f['family'] or f['q'] or f['attention']):continue
        days.append({'date':date_key,'state':info['state'],'issues':info['issues'],'summary':p.summary(by_day[date_key]),'baseline_version':info['baseline']['version'] if info['baseline'] else None,'current_version':info['current']['version'] if info['current'] else None,'freeze_at':info['baseline']['freeze_at'] if info['baseline'] else None,'current_released':info['current']['released'] if info['current'] else None})
    n=page(request.GET);items=rows[(n-1)*25:n*25];notes={x.key:x for x in IssueDisposition.objects.filter(key__in=['assembly-plan:'+r['id'] for r in items])}
    return response({'filters':f,'rows':[{**p.safe(r),'follow_up':follow_info(notes.get('assembly-plan:'+r['id']))} for r in items],'days':days,'total':len(rows),'page':n,'size':25,'summary':p.summary(rows),'note':p.NOTE,'states':STATES,'as_of':d.cutoff,'receipt':receipt(),'families':sorted({r['family'] for r in d.rows.values()}),'global_issues':d.global_issues})

@api()
@transaction.atomic
def version_detail(request,date_key):
    d=p.Plans()
    if date_key not in d.days:raise ValueError('没有该日期的计划资料')
    info=d.days[date_key];f=p.params(request.GET);rows=d.selected(f,date_key)
    return response({'day':day_info(info),'rows':[p.safe(r) for r in rows],'summary':p.summary(rows),'receipt':receipt(),'note':p.NOTE,'states':STATES})

def get_row(key):
    r=p.Plans().rows.get(key)
    if r is None:raise ValueError('工单不在该装配日的记录范围')
    return r

@api()
@transaction.atomic
def detail(request,key):
    d=p.Plans();r=d.rows.get(key)
    if r is None:raise ValueError('工单不在该装配日的记录范围')
    revisions=[{**{k:v for k,v in h.items() if k!='lines'},'line':next((line for line in h['lines'] if line.get('work_order_id')==r['work_order_id']),None)} for h in d.days[r['date']]['versions']]
    return response({'row':p.safe(r),'revisions':revisions,'confirmation':d.days[r['date']]['confirmation'],'receipt':receipt(),'as_of':d.cutoff,'follow_up':follow_info(IssueDisposition.objects.filter(key='assembly-plan:'+key).first()),'can_follow':writable(request.user),'statuses':STATUSES,'states':STATES,'note':p.NOTE})

@api()
@transaction.atomic
def evidence(request,key):
    check(request);r=get_row(key);rows=capture_sources({'sources':r['sources']});n=page(request.GET)
    return response({'rows':rows[(n-1)*40:n*40],'total':len(rows),'page':n,'size':40,'can_download_original':access.can_import(request.user)})

@api()
@transaction.atomic
def units(request,key):
    check(request);r=get_row(key);n=page(request.GET);rows=sorted(r['units'],key=lambda x:x['id'])
    return response({'rows':[access.sanitize(request.user,'units',u) for u in rows[(n-1)*25:n*25]],'total':len(rows),'page':n,'size':25})

@api(('POST',))
@transaction.atomic
def follow_up(request,key):
    require(writable(request.user),'仅管理员、分析师和生产计划角色可登记计划协调')
    r=get_row(key);data=body(request)
    if set(data)!={'version','status','owner','due_date','note','receipt'}:raise ValueError('跟进字段无效')
    if data['receipt']!=receipt():return response({'error':'计划或装配资料已变化，请重新读取'},409)
    if type(data['version']) is not int or data['version']<0 or data['status'] not in STATUSES:raise ValueError('跟进版本或状态无效')
    for k,lo,hi in [('owner',1,150),('note',5,2000)]:
        if not isinstance(data[k],str) or not lo<=len(data[k].strip())<=hi:raise ValueError('请填写责任岗位和5至2000字核查依据')
    due=data['due_date'] or None
    if due and not p.day(due):raise ValueError('跟进日期无效')
    identity='assembly-plan:'+key;item=IssueDisposition.objects.select_for_update().filter(key=identity).first();before=follow_info(item)
    if before['version']!=data['version']:return response({'error':'跟进已被更新，请重新读取'},409)
    values=dict(status=data['status'],owner=data['owner'].strip(),due_date=due,note=data['note'].strip(),version=data['version']+1,updated_by=request.user.username,updated_at=timezone.now())
    if item:
        if IssueDisposition.objects.filter(pk=item.pk,version=data['version']).update(**values)!=1:return response({'error':'跟进版本冲突'},409)
        item.refresh_from_db()
    else:item=IssueDisposition.objects.create(key=identity,**values)
    serial=lambda x:json.loads(json.dumps(x,ensure_ascii=False,default=str))
    AuditEvent.objects.create(action='assembly_plan.followup',actor=request.user.username,object_type='AssemblyPlanCoordination',object_id=identity,detail={'before':serial(before),'after':serial(follow_info(item)),'receipt':data['receipt'],'business_facts_changed':False})
    return response({'follow_up':follow_info(item),'notice':'已保存计划协调；计划版本和装配事实未改写。'})

@api()
def history(request,key):
    get_row(key)
    return response({'rows':list(AuditEvent.objects.filter(object_type='AssemblyPlanCoordination',object_id='assembly-plan:'+key).order_by('-id').values('actor','created_at','detail'))})

FIELDS=[('date','装配日'),('work_order_id','生产工单号'),('product_id','配置编码'),('family','产品族'),('baseline_qty','冻结计划台数'),('current_qty','当前计划台数'),('observed_qty','已登记装配SN数'),('baseline_eligible','基线可核对'),('current_eligible','当前可核对'),('baseline_fulfilled','基线范围内已观察兑现台数'),('current_fulfilled','当前范围内已观察兑现台数'),('baseline_short','基线已观察欠量'),('current_extra','当前超计划及未排台数'),('adjustment','计划台数调整'),('changed','计划是否变化')]
@api()
@transaction.atomic
def export(request):
    check(request);d=p.Plans();f=p.params(request.GET);rows=d.selected(f)
    values=[['模拟装配计划兑现','业务截止',d.cutoff,'筛选',json.dumps(f,ensure_ascii=False)],['说明',p.NOTE],['计算依据',receipt(),'全局核对事项',len(d.global_issues)],['标为不可核对的行只能观察已登记资料；不能用其兑现台数计算最终兑现率'],[label for _,label in FIELDS]+['资料状态','核对事项']]
    values.extend([[r.get(k) for k,_ in FIELDS]+[STATES[r['state']],'；'.join(r['issues'])] for r in rows])
    AuditEvent.objects.create(action='assembly_plan.export',actor=request.user.username,object_type='AssemblyPlanBoard',object_id='assembly-plans',detail={'filters':f,'rows':len(rows),'receipt':receipt()})
    out=csv_reply(values,'assembly-plan-performance');out['Cache-Control']='no-store';return out
