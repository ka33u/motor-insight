import json,hashlib
from pathlib import Path
from collections import defaultdict
from django.db import transaction
from django.utils import timezone
from . import targets as k,analytics,access,metric_registry
from .views import api,reply,body,require
from .models import AuditEvent,IssueDisposition,AnalysisModel,MetricVersion
from .delivery_views import follow_info
from .trace_cases import capture_sources
from .quality_views import csv_reply

STATUSES=['待核对','责任岗位分析中','措施跟进中','待效果复查','演练已复查']
def response(data,status=200):
    r=reply(data,status);r['Cache-Control']='no-store';return r
def receipt():
    return k.digest([list(analytics.revision()),analytics.AS_OF,list(AnalysisModel.objects.order_by('pk').values('id','version','dataset','definition','owner','is_public')),list(MetricVersion.objects.order_by('pk').values('id','status','revision','calculation_hash')),hashlib.sha256(Path(k.__file__).read_bytes()).hexdigest(),hashlib.sha256(Path(__file__).with_name('target_breakdown.py').read_bytes()).hexdigest(),[(ds,metric_registry.calculation_hash(ds)) for ds in sorted(set(AnalysisModel.objects.values_list('dataset',flat=True)))]] )
def page(p):
    n=int(p.get('page',1))
    if not 1<=n<=100000:raise ValueError('页码无效')
    return n
def guard(request):require(access.can_edit(request.user),'经营目标资料仅开放管理员和经营分析师')
def check_receipt(request):
    if request.GET.get('receipt')!=receipt():
        from .import_review import ReviewConflict
        raise ReviewConflict('目标、模型或事实已变化，请刷新工作台后重试')

@api()
@transaction.atomic
def board(request):
    d=k.Targets(request.user);f=k.params(request.GET);rows=d.selected(f);p=page(request.GET);items=rows[(p-1)*12:p*12];groups=defaultdict(list)
    for r in rows:groups[r['department']].append(r)
    return response({'filters':f,'states':k.STATES,'as_of':d.as_of,'note':k.NOTE,'receipt':receipt(),'summary':k.summary(rows),'rows':[k.safe(r) for r in items],'page':p,'size':12,'total':len(rows),'departments':[{'name':name,**k.summary(members)} for name,members in sorted(groups.items())],'department_options':sorted({r['department'] for r in d.rows.values()}),'global_issues':d.global_issues})

@api()
@transaction.atomic
def detail(request,key):
    d=k.Targets(request.user);r=d.detail(key)
    src=[{'dataset':'kpi_targets','key':key}]+[{'dataset':'kpi_target_checks','key':c['id']} for c in d.checks[key]]
    return response({'row':r,'as_of':d.as_of,'note':k.NOTE,'receipt':receipt(),'versions':[k.safe(d.rows[t['id']]) for t in sorted(d.series[r['series']],key=lambda t:t['version'])],'sources':capture_sources({'sources':src}),'follow_up':follow_info(IssueDisposition.objects.filter(key='target:'+key).first()),'statuses':STATUSES,'can_download_original':access.can_import(request.user)})

@api()
@transaction.atomic
def evidence(request,key):
    guard(request);check_receipt(request);d=k.Targets(request.user);r=d.detail(key)
    if r['state']=='blocked':raise ValueError('模型或目标规则待核对，暂不能展开实际来源')
    e=d.calculate(d.targets[key]);rows=sorted(e['rows'],key=lambda x:str(x['id']));p=page(request.GET)
    return response({'dataset':e['dataset'],'fields':access.permitted_fields(request.user,e['dataset']),'scope':e['scope'],'rows':[access.sanitize(request.user,e['dataset'],x) for x in rows[(p-1)*20:p*20]],'total':len(rows),'page':p,'size':20,'note':e['note']})

@api()
@transaction.atomic
def sources(request,key):
    guard(request);check_receipt(request);d=k.Targets(request.user);r=d.detail(key)
    if r['state']=='blocked':raise ValueError('规则待核对，暂不能展开实际来源')
    e=d.calculate(d.targets[key]);obj=next((x for x in e['rows'] if x['id']==request.GET.get('object_id')),None)
    if obj is None:raise ValueError('对象不在本目标范围')
    refs=obj.get('_sources') or [{'dataset':e['dataset'],'key':obj['id']}];refs=[x for x in refs if access.allowed(request.user,x['dataset'])]
    rows=capture_sources({'sources':refs});p=page(request.GET)
    return response({'rows':rows[(p-1)*40:p*40],'total':len(rows),'page':p,'size':40,'can_download_original':access.can_import(request.user)})

@api(('POST',))
@transaction.atomic
def follow_up(request,key):
    d=k.Targets(request.user);r=d.detail(key);p=body(request)
    if set(p)!={'version','status','owner','due_date','note','receipt'}:raise ValueError('跟进字段不完整或包含未知字段')
    if p['receipt']!=receipt():return response({'error':'目标、模型或事实已变化，请刷新核对'},409)
    if type(p['version']) is not int or p['version']<0 or p['status'] not in STATUSES:raise ValueError('跟进版本或状态不可用')
    for field,lo,hi in [('owner',1,150),('note',5,2000)]:
        if not isinstance(p[field],str) or not lo<=len(p[field].strip())<=hi:raise ValueError('请填写负责人和5至2000字复查依据')
    due=p['due_date'] or None
    if due and not k.day(due):raise ValueError('日期无效')
    identity='target:'+key;item=IssueDisposition.objects.select_for_update().filter(key=identity).first();before=follow_info(item)
    if before['version']!=p['version']:return response({'error':'协调记录已更新，请重新读取'},409)
    values=dict(status=p['status'],owner=p['owner'].strip(),due_date=due,note=p['note'].strip(),version=p['version']+1,updated_by=request.user.username,updated_at=timezone.now())
    if item:
        if IssueDisposition.objects.filter(pk=item.pk,version=p['version']).update(**values)!=1:return response({'error':'协调版本冲突'},409)
        item.refresh_from_db()
    else:item=IssueDisposition.objects.create(key=identity,**values)
    serial=lambda x:json.loads(json.dumps(x,ensure_ascii=False,default=str))
    AuditEvent.objects.create(action='target.followup',actor=request.user.username,object_type='TargetCoordination',object_id=identity,detail={'before':serial(before),'after':serial(follow_info(item)),'receipt':p['receipt'],'observed_state':r['state'],'data_signature':r['data_signature'],'target_or_facts_changed':False})
    return response({'follow_up':follow_info(item),'notice':'已保存偏差跟进；目标版本、数据确认和实际事实保持原样。'})

@api()
def history(request,key):
    k.Targets(request.user).detail(key)
    return response({'rows':list(AuditEvent.objects.filter(object_type='TargetCoordination',object_id='target:'+key).order_by('-id').values('actor','created_at','detail'))})

FIELDS=[('id','目标版本号'),('series','目标系列'),('version','版本'),('name','名称'),('department','部门'),('owner','责任岗位'),('period_start','期间开始'),('period_end','期间结束'),('family','产品族'),('customer_id','客户'),('date_label','期间日期口径'),('model_id','模型号'),('model_version','模型版本'),('measure','度量'),('unit','单位'),('direction','达标方向'),('lower','下限'),('upper','上限'),('warning_margin','关注区间宽度'),('actual','实际值'),('delta','差额'),('delta_unit','差额单位'),('attainment','越高越好目标完成百分数'),('matched','来源记录数'),('coverage_ok','资料确认匹配'),('retroactive','期后确认或调整'),('approved','目标确认时间'),('state','状态编码'),('basis','目标依据')]
@api()
@transaction.atomic
def export(request):
    guard(request);check_receipt(request);d=k.Targets(request.user);f=k.params(request.GET);rows=d.selected(f)
    values=[['模拟经营目标','截止',d.as_of,'筛选',json.dumps(f,ensure_ascii=False)],['说明',k.NOTE],['计算依据',receipt()],['差额为实际减阈值；区间内差额0。非最终状态仅供观察，空值不能当作零。'],[label for _,label in FIELDS]+['状态','核对事项']]
    values.extend([[r.get(field) for field,_ in FIELDS]+[k.STATES[r['state']],'；'.join(r['issues'])] for r in rows])
    AuditEvent.objects.create(action='target.export',actor=request.user.username,object_type='TargetBoard',object_id='targets',detail={'filters':f,'rows':len(rows),'receipt':receipt()})
    out=csv_reply(values,'operating-targets');out['Cache-Control']='no-store';return out
