"""Authenticated shift-efficiency analysis; same input scope for detail and export."""
import csv,hashlib,io,json
from pathlib import Path
from django.core import signing
from django.db import transaction
from django.http import HttpResponse
from . import oee as engine,oee_data,spc_data,access
from .oee_schema import DATASETS
from .models import Record,AuditEvent
from .views import api,reply,require
from .import_review import ReviewConflict
SALT='motor.oee.current.v1';MAX_AGE=600
def params(request,allowed=()):
 if set(request.GET)-set(allowed) or any(len(request.GET.getlist(k))!=1 for k in request.GET):raise ValueError('效率范围字段无效或重复')
def account(user):
 for ds in (*DATASETS,'products','production_resources'):require(access.allowed(user,ds),'岗位不能读取当前效率采集')
 return spc_data.account(user)
def stamp(d,user):return dict(key=d['result']['study']['id'],source_hash=d['source_hash'],rule_hash=d['rule_hash'],result_hash=engine.digest(d['result']),account=account(user),view_hash=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
def context(request,key,required=False):
 account(request.user);d=oee_data.load(key);value=stamp(d,request.user);given=request.GET.get('receipt')
 if required and not given:raise ValueError('请先读取当前结果，再查看依据或导出')
 if given:
  if len(given)>4096:raise ValueError('效率凭据过长')
  try:actual=signing.loads(given,salt=SALT,max_age=MAX_AGE)
  except signing.BadSignature:raise ReviewConflict('效率凭据无效或过期，请重新读取')
  if actual!=value:raise ReviewConflict('采集、来源、规则或账号已变化，请重新读取')
 d.update(stamp=value,receipt=given or signing.dumps(value,salt=SALT,compress=True));return d
def finish(request,d):
 if stamp(d,request.user)!=d['stamp'] or engine.rule_hash()!=d['rule_hash']:raise ReviewConflict('读取期间效率依据或账号变化，请重新读取')
def response(value):
 r=reply(value);r['Cache-Control']='no-store';return r
@api()
@transaction.atomic
def studies(request):
 params(request);account(request.user);rows=list(spc_data.queryset('oee_studies').order_by('business_key')[:1001])
 if len(rows)>1000:raise ValueError('采集方案超过1000项，请先整理目录')
 return response(dict(rows=[r.values for r in rows],synthetic=True,notice=engine.NOTICE))
@api()
@transaction.atomic
def board(request,key):
 params(request,('receipt',));d=context(request,key);finish(request,d)
 return response(dict(**d['result'],receipt=d['receipt'],receipt_seconds=MAX_AGE,source_hash=d['source_hash'],rule_hash=d['rule_hash'],source_count=len(d['sources']),resource=d['resource'],products=d['products']))
@api()
@transaction.atomic
def sources(request,key):
 params(request,('receipt','page'));v=request.GET.get('page','1')
 if not v.isascii() or not v.isdecimal() or not 1<=int(v)<=10000:raise ValueError('来源页码须为1至10000整数')
 page=int(v);d=context(request,key,True);finish(request,d)
 return response(dict(rows=d['sources'][(page-1)*40:page*40],total=len(d['sources']),page=page,size=40,receipt=d['receipt'],can_download_original=access.can_import(request.user)))
@api()
@transaction.atomic
def detail(request,key,window_id):
 params(request,('receipt',));d=context(request,key,True);w=next((w for w in d['result']['windows'] if w['id']==window_id),None)
 if w is None:raise Record.DoesNotExist()
 refs={('oee_studies',key),('oee_windows',window_id),('production_resources',d['result']['study']['resource_id']),('products',w['product_id'])}
 refs.update(('oee_cycles',c['id']) for c in d['tables']['oee_cycles'] if c['product_id']==w['product_id'] and c['unit']==w['unit']);refs.update(('oee_outputs',k) for k in w['output_ids']);refs.update(('oee_events',k) for k in w['event_ids'])
 finish(request,d);return response(dict(row=w,outputs=[o for o in d['tables']['oee_outputs'] if o['window_id']==window_id],events=[e for e in d['result']['events'] if e['id'] in w['event_ids']],sources=[s for s in d['sources'] if (s['dataset'],s['key']) in refs],receipt=d['receipt'],can_download_original=access.can_import(request.user),notice='该窗口直接依据；声明闭合与全方案重叠核对还须查看全方案来源。报产登记时间不能证明单台加工时刻。'))
@api()
@transaction.atomic
def export(request,key):
 params(request,('receipt','format'));fmt=request.GET.get('format','csv')
 if fmt not in ('csv','json'):raise ValueError('支持CSV或JSON')
 d=context(request,key,True);r=d['result'];name='oee-'+engine.digest(key)[:16]
 if fmt=='json':
  doc=dict(format='motor-oee-current-v1',synthetic=True,result=r,inputs=d['tables'],resource=d['resource'],products=d['products'],sources=d['sources'],source_hash=d['source_hash'],rule_hash=d['rule_hash'],result_hash=engine.digest(r),notice=engine.NOTICE)
  file=HttpResponse(json.dumps(doc,ensure_ascii=False,indent=2,allow_nan=False)+'\n',content_type='application/json; charset=utf-8')
 else:
  rows=[['合成班次效率',key,r['study']['name']],['采集状态',r['state'],'业务截止',r['as_of']],['采集版本',r['study']['version'],'资源位',r['study']['resource_id']],['来源摘要',d['source_hash'],'规则摘要',d['rule_hash']],['暂停原因','；'.join(r['issues'])],['边界',engine.NOTICE],['混配置合计','理想良品秒数合计 / 计划生产秒数合计；不简单平均OEE，原始数量单位不同不合并'],['生产窗口号','产品配置','产出单位','计划开始','计划结束','计划秒数','停止秒数','运行秒数','理想秒每单位','总数量','首次良品','需返工','报废','未确认','可动率','性能率','质量率','窗口OEE','速度损失秒','质量损失秒']]
  for w in r['windows']:rows.append([w.get(k) for k in ('id','product_id','unit','started','finished','planned_seconds','stop_seconds','run_seconds','ideal_seconds_per_unit')]+[w['counts'][k] for k in ('total_qty','good_first_qty','rework_qty','scrap_qty','unknown_qty')]+[w.get(k) for k in ('availability','performance','quality','oee','speed_loss_seconds','quality_loss_seconds')])
  if r['summary']:
   rows.append(['合计口径',r['summary']['measure_label']]);rows.extend([k,v] for k,v in r['summary'].items() if not isinstance(v,dict))
  for ds,inputs in {'oee_studies':[r['study']],**d['tables']}.items():
   rows.append(['完整原始输入',ds]);headers=sorted({k for x in inputs for k in x});rows.append(headers);rows.extend([x.get(k) for k in headers] for x in inputs)
  rows.append(['完整来源','数据集','业务编号','修订','批次','文件','工作表','行号','记录摘要','原件摘要'])
  rows.extend(['来源']+[s.get(k) for k in ('dataset','key','revision','batch_id','filename','sheet','row','record_hash','file_hash')] for s in d['sources'])
  out=io.StringIO();writer=csv.writer(out);writer.writerows([["'"+v if isinstance(v,str) and v.lstrip().startswith(('=','+','-','@')) else v for v in row] for row in rows]);file=HttpResponse('\ufeff'+out.getvalue(),content_type='text/csv; charset=utf-8')
 finish(request,d);AuditEvent.objects.create(action='oee.export',actor=request.user.username,object_type='OEEStudy',object_id=key,detail=dict(format=fmt,state=r['state'],source_hash=d['source_hash'],rule_hash=d['rule_hash'],file_sha256=hashlib.sha256(file.content).hexdigest(),business_facts_changed=False));file['Content-Disposition']='attachment; filename="'+name+'.'+fmt+'"';file['Cache-Control']='no-store';return file
