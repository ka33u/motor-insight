import json,math
from django.db import transaction
from django.db.models import Count
from django.utils import timezone
from . import data_health as health,access,analytics
from .views import api,reply,body,require
from .models import DataQualityScan,DataMonitorPolicy,Record,ImportBatch,ImportRow,AuditEvent
from .schema import SCHEMAS
from .quality_views import csv_reply
from .trace_cases import capture_sources

def response(value):
    r=reply(value);r['Cache-Control']='no-store';return r

def context(request):
    f=health.filters(request.GET);scan=DataQualityScan.objects.filter(pk=request.GET['scan']).first() if request.GET.get('scan') else DataQualityScan.objects.order_by('-created_at').first()
    if not scan:
        if request.GET.get('scan'):raise DataQualityScan.DoesNotExist()
        return None,f
    return health.project(scan,request.user),f

def summary(rows):
    return {'tables':len(rows),'records':sum(r['rows'] for r in rows),'issues':sum(r['issue_count'] for r in rows),'affected_rows':sum(r['affected_rows'] for r in rows),'empty':sum(not r['rows'] for r in rows),'no_target':sum(not r['freshness']['has_target'] for r in rows),'late':sum('late' in r['flags'] for r in rows),'required_cells':sum(r['required_cells'] for r in rows),'missing_required':sum(r['missing_required'] for r in rows)}

@api()
def board(request):
    d,f=context(request)
    if not d:return response({'scan':None,'can_run':access.can_edit(request.user),'can_import':access.can_import(request.user),'note':health.NOTE})
    rows=health.select(d['rows'],f);ids={r['dataset'] for r in rows};issues=[i for i in d['issues'] if i['dataset'] in ids and (not f['rule'] or i['rule']==f['rule'])];page=max(1,int(request.GET.get('page',1)))
    return response({**{k:v for k,v in d.items() if k not in ['rows','issues']},'scan':d['id'],'filters':f,'summary':summary(rows),'rows':[{k:v for k,v in r.items() if k!='fields'} for r in rows],'issue_rows':issues[(page-1)*25:page*25],'issue_total':len(issues),'page':page,'size':25,'stages':health.STAGES,'rules':health.RULES,'options':{'departments':sorted({r['department'] for r in d['rows']}),'datasets':[{'id':r['dataset'],'label':r['label']} for r in d['rows']]},'can_run':access.can_edit(request.user),'can_import':access.can_import(request.user)})

@api(('POST',))
def run(request):
    p=body(request)
    if set(p)!={'request_id'}:raise ValueError('请提供独立检查请求标识')
    scan=health.run(request.user,p['request_id']);return response({'id':str(scan.pk),'notice':'已保存基础检查快照，业务原始记录未修改。'})

@api()
def detail(request,ds):
    require(access.allowed(request.user,ds));d,f=context(request)
    if not d:raise ValueError('请先运行基础检查')
    row=next((r for r in d['rows'] if r['dataset']==ds),None)
    if not row:raise Record.DoesNotExist()
    fields={f['name']:f for f in access.permitted_fields(request.user,ds)};issues=[i for i in d['issues'] if i['dataset']==ds];page=max(1,int(request.GET.get('page',1)))
    return response({'row':row,'fields':[{**fields[k],**v} for k,v in row['fields'].items()],'issues':issues[(page-1)*25:page*25],'total':len(issues),'page':page,'size':25,'scan':d['id'],'stale':d['stale'],'checked_at':d['checked_at'],'as_of':d['as_of'],'can_edit':access.can_edit(request.user),'can_import':access.can_import(request.user),'note':d['note']})

@api()
def record(request,pk):
    obj=Record.objects.get(pk=pk);require(access.allowed(request.user,obj.dataset));d,f=context(request)
    if not d:raise ValueError('尚无检查快照')
    previous=[i for i in d['issues'] if i['record_id']==pk]
    if not previous:raise ValueError('此记录不在当前可见问题清单中')
    source=capture_sources({'sources':[{'dataset':obj.dataset,'key':obj.business_key}]})
    return response({'dataset':obj.dataset,'key':obj.business_key,'values':access.sanitize(request.user,obj.dataset,obj.values),'fields':access.permitted_fields(request.user,obj.dataset),'sources':source,'issues':previous,'changed_since_scan':any(i['record_hash']!=obj.record_hash for i in previous),'can_import':access.can_import(request.user)})

@api(('POST',))
@transaction.atomic
def policy(request,ds):
    require(access.can_edit(request.user));require(ds in SCHEMAS and access.allowed(request.user,ds));p=body(request)
    if set(p)!={'version','owner','business_clock','max_business_lag_days','max_import_age_hours','note'}:raise ValueError('监测规则字段不完整或存在未知字段')
    if type(p['version']) is not int or p['version']<0:raise ValueError('规则版本无效')
    for k,lo,hi in [('owner',1,150),('note',5,2000)]:
        if not isinstance(p[k],str) or not lo<=len(p[k].strip())<=hi:raise ValueError('请填写负责人及5至2000字的配置依据')
    allowed={f['name'] for f in SCHEMAS[ds]['fields'] if f['type'] in ['date','datetime']}
    if not isinstance(p['business_clock'],str) or p['business_clock'] and p['business_clock'] not in allowed:raise ValueError('请选择该表实际的日期或时间字段')
    lag=p['max_business_lag_days'];hours=p['max_import_age_hours']
    if lag is not None and (type(lag) not in [int,float] or not math.isfinite(lag) or not 0<=lag<=3650 or not p['business_clock']):raise ValueError('业务滞后须为0至3650天，并指定观察字段')
    if hours is not None and (type(hours) is not int or not 1<=hours<=87600):raise ValueError('导入间隔须为1至87600小时的整数')
    item=DataMonitorPolicy.objects.select_for_update().filter(dataset=ds).first();before=health.policy_info(item,ds)
    if before['version']!=p['version']:return reply({'error':'规则版本已变化，请重新读取'},409)
    values={k:v.strip() if isinstance(v,str) else v for k,v in p.items() if k!='version'};values.update(version=p['version']+1,updated_by=request.user.username,updated_at=timezone.now())
    if item:
        if DataMonitorPolicy.objects.filter(pk=item.pk,version=p['version']).update(**values)!=1:return reply({'error':'规则版本冲突'},409)
        item.refresh_from_db()
    else:item=DataMonitorPolicy.objects.create(dataset=ds,**values)
    serial=lambda x:json.loads(json.dumps(x,ensure_ascii=False,default=str))
    AuditEvent.objects.create(action='data_health.policy',actor=request.user.username,object_type='DataMonitorPolicy',object_id=ds,detail={'before':serial(before),'after':serial(health.policy_info(item,ds)),'business_facts_changed':False})
    return response({'policy':health.policy_info(item,ds),'notice':'已保存监测约定；对当前检查快照应用新目标，未改变业务数据或发出通知。'})

@api()
def history(request,ds):
    require(access.allowed(request.user,ds));return response({'rows':list(AuditEvent.objects.filter(object_type='DataMonitorPolicy',object_id=ds).order_by('-id').values('actor','created_at','detail'))})

@api()
def imports(request):
    require(access.can_import(request.user));result=[]
    counts={(str(r['batch_id']),r['status']):r['n'] for r in ImportRow.objects.values('batch_id','status').annotate(n=Count('id'))}
    for b in ImportBatch.objects.exclude(status='superseded').order_by('-created_at'):
        result.append({'id':str(b.pk),'filename':b.filename,'status':b.status,'created_at':b.created_at,'committed_at':b.committed_at,'counts':{k:counts.get((str(b.pk),k),0) for k in ['valid','invalid','conflict','duplicate','committed','replaced','kept']},'unknown_sheets':b.summary.get('unknown_sheets',[])})
    return response({'rows':result,'notice':'当前导入队列，不是检查快照；历史替代批次不计待处理。待提交、失败、重复跳过和冲突分开。'})

@api()
def export(request):
    d,f=context(request)
    if not d:raise ValueError('请先运行基础检查')
    rows=health.select(d['rows'],f);ids={r['dataset'] for r in rows};issues=[i for i in d['issues'] if i['dataset'] in ids and (not f['rule'] or i['rule']==f['rule'])]
    kind=request.GET.get('kind','issues')
    if kind not in ['issues','tables']:raise ValueError('导出内容不可用')
    data=[['数据基础检查快照',d['id'],'检查时间',d['checked_at'],'筛选',json.dumps(f,ensure_ascii=False)],['说明',d['note'],'来源已变化',d['stale'],'系统观察时间',d['now'],'业务截止',d['as_of']]]
    if kind=='issues':
        data += [['源表','主键','规则','字段','说明']]+[[i['dataset'],i['key'],health.RULES[i['rule']],i['field'],i['message']] for i in issues]
    else:
        data += [['源表','名称','来源部门','检查记录数','基础问题数','受影响记录数','必填空值','已查必填单元格','负责人','观察字段','截至业务截止最大时点','距业务截止天数','业务最多滞后天数','最近有效提交','距导入小时','导入最多间隔小时','时效状态','规则版本']]
        data += [[r['dataset'],r['label'],r['department'],r['rows'],r['issue_count'],r['affected_rows'],r['missing_required'],r['required_cells'],r['policy']['owner'],r['policy']['business_clock'],r['freshness']['business_latest'],r['freshness']['business_lag_days'],r['policy']['max_business_lag_days'],r['freshness']['last_commit'],r['freshness']['import_age_hours'],r['policy']['max_import_age_hours'],';'.join(r['freshness']['flags']) or '未设目标',r['policy']['version']] for r in rows]
    AuditEvent.objects.create(action='data_health.export',actor=request.user.username,object_type='DataQualityScan',object_id=d['id'],detail={'filters':f,'kind':kind,'rows':len(issues) if kind=='issues' else len(rows)})
    r=csv_reply(data,'data-quality-'+kind);r['Cache-Control']='no-store';return r
