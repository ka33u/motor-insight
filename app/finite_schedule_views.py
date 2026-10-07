"""Read-only trials with current-scope provenance and complete result exports."""
import hashlib,json
from pathlib import Path
from django.core import signing
from django.db import transaction
from django.http import HttpResponse
from . import finite_schedule as engine,finite_schedule_data as data,spc_data,access
from .finite_schedule_schema import DATASETS
from .models import Record,AuditEvent
from .views import api,reply,require
from .import_review import ReviewConflict
from .quality_views import csv_reply
SALT='motor.finite-resource.trial.v1';MAX_AGE=600
def params(request,allowed=()):
 if set(request.GET)-set(allowed) or any(len(request.GET.getlist(k))!=1 for k in request.GET):raise ValueError('试排范围字段无效或重复')
def account(user):
 for ds in DATASETS:require(access.allowed(user,ds),'岗位不能读取当前试排资料')
 return spc_data.account(user)
def stamp(d,user):return dict(study=d['result']['study']['id'],policy=d['result']['policy'],source_hash=d['source_hash'],rule_hash=d['rule_hash'],result_hash=engine.digest(d['result']),account=account(user),view_hash=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
def context(request,key,required=False):
 account(request.user);d=data.load(key,request.GET.get('policy','due'));value=stamp(d,request.user);given=request.GET.get('receipt')
 if required and not given:raise ValueError('请先读取试排结果，再查看来源或导出')
 if given:
  if len(given)>4096:raise ValueError('试排凭据过长')
  try:actual=signing.loads(given,salt=SALT,max_age=MAX_AGE)
  except signing.BadSignature:raise ReviewConflict('试排凭据无效或过期，请重新计算')
  if actual!=value:raise ReviewConflict('假设、来源、规则、策略或账号已变化，请重新计算')
 d.update(stamp=value,receipt=given or signing.dumps(value,salt=SALT,compress=True));return d
def finish(request,d):
 if stamp(d,request.user)!=d['stamp'] or engine.rule_hash()!=d['rule_hash']:raise ReviewConflict('读取期间试排依据或账号变化，请重新计算')
def response(value):
 r=reply(value);r['Cache-Control']='no-store';return r
@api()
@transaction.atomic
def studies(request):
 params(request);account(request.user);rows=list(spc_data.queryset('schedule_studies').order_by('business_key')[:1001])
 if len(rows)>1000:raise ValueError('方案目录超过1000项，请先整理目录')
 return response(dict(rows=[r.values for r in rows],policies=engine.POLICIES,synthetic=True,notice=engine.NOTICE))
@api()
@transaction.atomic
def board(request,key):
 params(request,('policy','receipt'));d=context(request,key);finish(request,d)
 return response(dict(**d['result'],receipt=d['receipt'],receipt_seconds=MAX_AGE,source_hash=d['source_hash'],rule_hash=d['rule_hash'],source_count=len(d['sources']),synthetic=True))
@api()
@transaction.atomic
def sources(request,key):
 params(request,('policy','receipt','page'));v=request.GET.get('page','1')
 if not v.isascii() or not v.isdecimal() or not 1<=int(v)<=10000:raise ValueError('来源页码须为1至10000整数')
 page=int(v);d=context(request,key,True);finish(request,d)
 return response(dict(rows=d['sources'][(page-1)*40:page*40],page=page,size=40,total=len(d['sources']),receipt=d['receipt'],can_download_original=access.can_import(request.user)))
@api()
@transaction.atomic
def detail(request,key,task_id):
 params(request,('policy','receipt'));d=context(request,key,True);r=next((t for t in d['result']['tasks'] if t['id']==task_id),None)
 if r is None:raise Record.DoesNotExist()
 refs={('schedule_studies',key),('schedule_jobs',r['job_id']),('schedule_tasks',r['id']),('routes',r['route_id']),('products',r['product_id'])}
 refs.update(('schedule_tasks',k) for k in r['predecessors'])
 for o in d['tables']['schedule_options']:
  if o['task_id']==task_id:refs.update({('schedule_options',o['id']),('production_resources',o['resource_id'])})
 for e in d['tables']['schedule_edges']:
  if e['to_task_id']==task_id:refs.update({('schedule_edges',e['id']),('route_dependencies',e['dependency_id'])})
 for ds in ('schedule_windows','schedule_blocks'):
  for w in d['tables'][ds]:
   if ('production_resources',w['resource_id']) in refs:refs.add((ds,w['id']))
 finish(request,d);return response(dict(row=r,predecessors=[t for t in d['result']['tasks'] if t['id'] in r['predecessors']],sources=[s for s in d['sources'] if (s['dataset'],s['key']) in refs],notice='当前任务的直接依据；完整试排还依赖其他任务的资源竞争，请同时核对全方案来源。',receipt=d['receipt'],can_download_original=access.can_import(request.user)))
@api()
@transaction.atomic
def export(request,key):
 params(request,('policy','receipt','format'));fmt=request.GET.get('format','csv')
 if fmt not in ('csv','json'):raise ValueError('支持CSV或JSON')
 d=context(request,key,True);r=d['result'];document=dict(format='motor-finite-resource-trial-v1',synthetic=True,result=r,inputs=dict(study=r['study'],**d['tables']),sources=d['sources'],source_hash=d['source_hash'],rule_hash=d['rule_hash'],result_hash=engine.digest(r),notice=engine.NOTICE)
 if fmt=='json':
  response_file=HttpResponse(json.dumps(document,ensure_ascii=False,indent=2,allow_nan=False)+'\n',content_type='application/json; charset=utf-8');response_file['Content-Disposition']='attachment; filename="finite-'+engine.digest(key)[:16]+'.json"'
 else:
  refs={(s['dataset'],s['key']):s for s in d['sources']};rows=[['独立合成有限资源试排',key,r['study']['name']],['假设版本',r['study']['version'],'策略',r['policy_name'],'状态',r['state']],['来源摘要',d['source_hash'],'规则摘要',d['rule_hash']],['边界',engine.NOTICE],['暂停原因','；'.join(r['issues'])],['任务号','试排批次','配置','工序','分支','独立模拟台数','状态','资源位','准备开始','加工开始','完成','加工分钟','换型分钟','资源与日历等待分钟','未排入原因','前序任务','假设Excel','工作表','行号']]
  for t in r['tasks']:
   s=refs['schedule_tasks',t['id']];rows.append([t.get(k) for k in ('id','job_id','product_id','process','branch','qty','state','resource_id','started','process_started','finished','process_minutes','setup_minutes','wait_minutes','reason')]+['；'.join(t['predecessors']),s['filename'],s['sheet'],s['row']])
  if r['state']=='paused':
   rows.extend([['暂停方案：以下保留全部输入任务，排程、完成、等待与负载未计算'],['输入任务号','试排批次','路线行','批内份号','任务处理台数','假设每台分钟','工时假设依据','假设Excel','工作表','行号']])
   for t in d['tables']['schedule_tasks']:
    s=refs['schedule_tasks',t['id']];rows.append([t.get(k) for k in ('id','job_id','route_id','portion','lot_qty','unit_minutes','basis')]+[s['filename'],s['sheet'],s['row']])
  rows.append(['批次口径：台数按独立批次计一次，不累加各工序台数；CSV列出全部任务，JSON同时保存完整批次、资源和来源。'])
  rows=[["'"+v if isinstance(v,str) and v.lstrip().startswith(('=','+','-','@')) and not v.startswith("'") else v for v in row] for row in rows]
  response_file=csv_reply(rows,'finite-'+engine.digest(key)[:16])
 finish(request,d);AuditEvent.objects.create(action='finite_schedule.export',actor=request.user.username,object_type='ScheduleStudy',object_id=key,detail=dict(format=fmt,policy=r['policy'],tasks=len(r['tasks']),input_tasks=len(d['tables']['schedule_tasks']),state=r['state'],source_hash=d['source_hash'],rule_hash=d['rule_hash'],file_sha256=hashlib.sha256(response_file.content).hexdigest(),business_facts_changed=False))
 response_file['Cache-Control']='no-store';return response_file
