"""Planning-role, source-bound joint trial and complete assumption exports."""
import hashlib,json
from pathlib import Path
from django.core import signing
from django.db import transaction
from django.http import HttpResponse
from . import crew_schedule as engine,crew_schedule_data as data,finite_schedule,spc_data,access
from .crew_schedule_schema import DATASETS
from .models import Record,AuditEvent
from .views import api,reply,require
from .import_review import ReviewConflict
from .quality_views import csv_reply
SALT='motor.crew-resource.trial.v1';MAX_AGE=600
def params(request,allowed=()):
 if set(request.GET)-set(allowed) or any(len(request.GET.getlist(k))!=1 for k in request.GET):raise ValueError('联立试排范围字段无效或重复')
def account(user):
 for ds in (*DATASETS,'skills'):require(access.allowed(user,ds),'当前岗位不能读取人员资格和联立试排假设')
 return spc_data.account(user)
def stamp(d,user):return dict(study=d['result']['study']['id'],policy=d['result']['policy'],source_hash=d['source_hash'],rule_hash=d['rule_hash'],result_hash=finite_schedule.digest(d['result']),account=account(user),view_hash=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
def context(request,key,required=False):
 account(request.user);d=data.load(key,request.GET.get('policy','due'));value=stamp(d,request.user);given=request.GET.get('receipt')
 if required and not given:raise ValueError('请先读取当前联立试排，再查看来源或导出')
 if given:
  if len(given)>4096:raise ValueError('联立凭据过长')
  try:actual=signing.loads(given,salt=SALT,max_age=MAX_AGE)
  except signing.BadSignature:raise ReviewConflict('联立凭据无效或过期，请重新计算')
  if actual!=value:raise ReviewConflict('人员假设、资源、资格、策略、规则或账号已变化，请重新计算')
 d.update(stamp=value,receipt=given or signing.dumps(value,salt=SALT,compress=True));return d
def finish(request,d):
 if stamp(d,request.user)!=d['stamp'] or engine.rule_hash()!=d['rule_hash']:raise ReviewConflict('读取期间联立依据或权限变化，请重新计算')
def response(value):
 r=reply(value);r['Cache-Control']='no-store';return r
@api()
@transaction.atomic
def studies(request):
 params(request);account(request.user);rows=list(spc_data.queryset('crew_studies').order_by('business_key')[:1001])
 if len(rows)>1000:raise ValueError('联立目录超过1000项')
 return response(dict(rows=[r.values for r in rows],policies=finite_schedule.POLICIES,notice=engine.NOTICE,synthetic=True))
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
 return response(dict(rows=d['sources'][(page-1)*40:page*40],total=len(d['sources']),page=page,size=40,receipt=d['receipt'],can_download_original=access.can_import(request.user)))
@api()
@transaction.atomic
def detail(request,key,task_id):
 params(request,('policy','receipt'));d=context(request,key,True);t=next((t for t in d['result']['tasks'] if t['id']==task_id),None)
 if t is None:raise Record.DoesNotExist()
 refs={('crew_studies',key),('schedule_studies',d['result']['resource_study']['id']),('schedule_tasks',task_id),('schedule_jobs',t['job_id']),('routes',t['route_id']),('products',t['product_id'])}
 refs.update(('schedule_tasks',k) for k in t['predecessors']);qualification_ids=set();employee_ids=set()
 for c in d['tables']['crew_candidates']:
  if c['task_id']==task_id:refs.add(('crew_candidates',c['id']));qualification_ids.add(c['credential_id'])
 for c in d['result']['credentials']:
  if c['id'] in qualification_ids:refs.update({('crew_credentials',c['id']),('skills',c['skill_id']),('employees',c['employee_id'])});employee_ids.add(c['employee_id'])
 for ds in ('crew_windows','crew_blocks'):
  for w in d['tables'][ds]:
   if w['employee_id'] in employee_ids:refs.add((ds,w['id']))
 resource_ids={o['resource_id'] for o in d['base']['tables']['schedule_options'] if o['task_id']==task_id};refs.update(('production_resources',k) for k in resource_ids)
 for ds in ('schedule_windows','schedule_blocks','schedule_options'):
  for w in d['base']['tables'][ds]:
   if (ds=='schedule_options' and w['task_id']==task_id) or (ds!='schedule_options' and w['resource_id'] in resource_ids):refs.add((ds,w['id']))
 for e in d['base']['tables']['schedule_edges']:
  if e['to_task_id']==task_id:refs.update({('schedule_edges',e['id']),('route_dependencies',e['dependency_id'])})
 finish(request,d);return response(dict(row=t,sources=[s for s in d['sources'] if (s['dataset'],s['key']) in refs],receipt=d['receipt'],can_download_original=access.can_import(request.user),notice='直接任务、资格与双侧窗口依据；其他任务共同占用设备和人员，请同时核对全方案来源。'))
@api()
@transaction.atomic
def export(request,key):
 params(request,('policy','receipt','format'));fmt=request.GET.get('format','csv')
 if fmt not in ('csv','json'):raise ValueError('支持CSV或JSON')
 d=context(request,key,True);r=d['result'];name='crew-'+finite_schedule.digest(key)[:16]
 if fmt=='json':
  doc=dict(format='motor-crew-resource-trial-v1',synthetic=True,result=r,crew_inputs=dict(study=r['study'],**d['tables']),resource_inputs=dict(study=r['resource_study'],**d['base']['tables']),sources=d['sources'],source_hash=d['source_hash'],rule_hash=d['rule_hash'],result_hash=finite_schedule.digest(r),notice=engine.NOTICE)
  file=HttpResponse(json.dumps(doc,ensure_ascii=False,indent=2,allow_nan=False)+'\n',content_type='application/json; charset=utf-8');file['Content-Disposition']='attachment; filename="'+name+'.json"'
 else:
  refs={(s['dataset'],s['key']):s for s in d['sources']};rows=[['独立合成设备人员联立试排',key,r['study']['name']],['假设版本',r['study']['version'],'资源方案',r['resource_study']['id'],'策略',r['policy_name'],'状态',r['state']],['来源摘要',d['source_hash'],'规则摘要',d['rule_hash']],['边界',engine.NOTICE],['暂停原因','；'.join(r['issues'])],['任务号','批次','工序','分支','处理台数','状态','资源位','操作工号','技能依据','资格假设','人员候选','资源窗口','人员窗口','准备开始','加工开始','完成','加工分钟','换型分钟','共同等待分钟','同资源状态新增人员等待分钟','未排原因','前序任务','任务假设Excel','工作表','行号']]
  for t in r['tasks']:
   s=refs['schedule_tasks',t['id']];rows.append([t.get(k) for k in ('id','job_id','process','branch','qty','state','resource_id','employee_id','skill_id','credential_id','candidate_id','window_id','worker_window_id','started','process_started','finished','process_minutes','setup_minutes','wait_minutes','staff_additional_wait_minutes','reason')]+['；'.join(t['predecessors']),s['filename'],s['sheet'],s['row']])
  if r['state']=='paused':
   rows.extend([['暂停方案保留全部输入任务；排程、人员、完成和等待未计算'],['输入任务号','试排批次','路线行','批内份号','处理台数','假设每台分钟','任务假设Excel','工作表','行号']])
   for t in d['base']['tables']['schedule_tasks']:
    s=refs['schedule_tasks',t['id']];rows.append([t.get(k) for k in ('id','job_id','route_id','portion','lot_qty','unit_minutes')]+[s['filename'],s['sheet'],s['row']])
  rows.append(['数量按批次计一次；假设人员占用不是考勤、绩效或人工成本。JSON保留全部人员与资源假设、结果和来源；不授予原件权限。'])
  rows=[["'"+v if isinstance(v,str) and v.lstrip().startswith(('=','+','-','@')) and not v.startswith("'") else v for v in row] for row in rows];file=csv_reply(rows,name)
 finish(request,d);AuditEvent.objects.create(action='crew_schedule.export',actor=request.user.username,object_type='CrewStudy',object_id=key,detail=dict(format=fmt,policy=r['policy'],tasks=len(r['tasks']),input_tasks=len(d['base']['tables']['schedule_tasks']),state=r['state'],source_hash=d['source_hash'],rule_hash=d['rule_hash'],file_sha256=hashlib.sha256(file.content).hexdigest(),business_facts_changed=False));file['Cache-Control']='no-store';return file
