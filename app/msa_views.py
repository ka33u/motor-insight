"""Source-bound trial boards, factor cells, complete CSV and point provenance."""
import hashlib,json
from pathlib import Path
from django.core import signing
from django.db import transaction
from . import msa,msa_data,spc_data,access,analytics
from .models import Record,AuditEvent
from .views import api,reply,require
from .import_review import ReviewConflict
from .quality_views import csv_reply
SALT='motor.msa.crossed.trial.v1';MAX_AGE=600;SIZE=25
def params(request,extra=()):
 if set(request.GET)-{'page',*extra} or any(len(request.GET.getlist(k))!=1 for k in request.GET):raise ValueError('测量系统试验范围字段无效或重复')
 v=request.GET.get('page','1')
 if not v.isascii() or not v.isdecimal() or not 1<=int(v)<=10000:raise ValueError('页码须为1至10000的整数')
 return int(v)
def account(user):
 for ds in ('msa_studies','msa_members','msa_observations'):require(access.allowed(user,ds),'岗位不能读取当前测量系统试验资料')
 return spc_data.account(user)
def stamp(d,user):return dict(study_id=d['result']['study']['id'],source_hash=d['source_hash'],rule_hash=d['rule_hash'],view_hash=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),as_of=analytics.AS_OF,account=account(user))
def context(request,key,required=False):
 account(request.user);d=msa_data.load(key);value=stamp(d,request.user);given=request.GET.get('receipt')
 if required and not given:raise ValueError('请先读取试验，获取完整来源凭据')
 if given:
  if len(given)>4096:raise ValueError('试验凭据过长')
  try:actual=signing.loads(given,salt=SALT,max_age=MAX_AGE)
  except signing.BadSignature:raise ReviewConflict('试验凭据无效或已过期，请重新读取')
  if actual!=value:raise ReviewConflict('试验、来源、规则或账号权限已变化，请重新读取')
 d.update(receipt=given or signing.dumps(value,salt=SALT,compress=True),stamp=value);return d
def finish(request,d):
 if stamp(d,request.user)!=d['stamp'] or msa.rule_hash()!=d['rule_hash']:raise ReviewConflict('读取期间计算依据或账号变化，请重新读取')
def response(d):
 r=reply(d);r['Cache-Control']='no-store';return r
def point(d,key):
 p=next((p for p in d['result']['points'] if p['id']==key),None)
 if p is None:raise Record.DoesNotExist()
 return p
@api()
@transaction.atomic
def studies(request):
 params(request);account(request.user);rows=list(spc_data.queryset('msa_studies').order_by('business_key')[:1001])
 if len(rows)>1000:raise ValueError('测量试验目录超过1000项，请先整理目录')
 return response(dict(rows=[dict(id=r.business_key,**{k:r.values.get(k) for k in ('name','product_id','instrument_id','part_count','operator_count','repeat_count','unit')}) for r in rows],as_of=analytics.AS_OF,synthetic=True,notice=msa.NOTICE))
@api()
@transaction.atomic
def board(request,key):
 page=params(request,('receipt',));d=context(request,key);r=d['result'];finish(request,d)
 return response(dict(**{k:v for k,v in r.items() if k!='points'},rows=r['points'][(page-1)*SIZE:page*SIZE],total=len(r['points']),page=page,size=SIZE,
  chart_points=[{k:p.get(k) for k in ('id','value','part_member_id','operator_member_id','repeat','run_order','eligible','unit','part_label','operator_label')} for p in r['points']],
  receipt=d['receipt'],receipt_seconds=MAX_AGE,source_hash=d['source_hash'],rule_hash=d['rule_hash'],product=access.sanitize(request.user,'products',d['product']) if d['product'] else None,synthetic=True))
@api()
@transaction.atomic
def detail(request,key,point_id):
 params(request,('receipt',));d=context(request,key,True);p=point(d,point_id);sources=msa_data.point_sources(d,p);finish(request,d)
 return response(dict(row=p,sources=sources,study=d['result']['study'],receipt=d['receipt'],can_download_original=access.can_import(request.user),notice=msa.NOTICE))
@api()
@transaction.atomic
def cell(request,key,part_id,operator_id):
 params(request,('receipt',));d=context(request,key,True);c=next((c for c in d['result']['matrix'] if c['part_id']==part_id and c['operator_id']==operator_id),None)
 if c is None:raise Record.DoesNotExist()
 selected=[p for p in d['result']['points'] if p['part_member_id']==part_id and p['operator_member_id']==operator_id];finish(request,d)
 return response(dict(cell=c,rows=selected,receipt=d['receipt'],notice='显示全部重复登记，不择优删行；缺少的轮次列明，不补零。'))
@api()
@transaction.atomic
def sources(request,key):
 page=params(request,('receipt',));d=context(request,key,True);finish(request,d)
 return response(dict(rows=d['sources'][(page-1)*40:page*40],total=len(d['sources']),page=page,size=40,receipt=d['receipt']))
@api()
@transaction.atomic
def export(request,key):
 params(request,('receipt',));d=context(request,key,True);r=d['result'];refs={(s['dataset'],s['key']):s for s in d['sources']}
 rows=[['合成测量系统试验',key,r['study']['name']],['计算版本',r['rule_version'],'业务截止',r['as_of']],['来源摘要',d['source_hash'],'规则摘要',d['rule_hash']],['方法',r['model_policy']],['说明',msa.NOTICE],
  ['观测号','登记序号','样件标签','样件SN','操作员标签','工号','重复轮次','原数值','原单位','字段可用','原因','实测时间','登记时间','来源依据','Excel文件','工作表','行号']]
 for p in r['points']:
  s=refs['msa_observations',p['id']];rows.append([p.get(k) for k in ('id','run_order','part_label','unit_id','operator_label','operator_id','repeat','value','unit','eligible')]+['；'.join(p['reasons'])]+[p.get(k) for k in ('measured','registered','reference')]+[s['filename'],s['sheet'],s['row']])
 finish(request,d);AuditEvent.objects.create(action='msa.export',actor=request.user.username,object_type='MSAStudy',object_id=key,detail=dict(rows=len(r['points']),source_hash=d['source_hash'],rule_hash=d['rule_hash'],business_facts_changed=False))
 response=csv_reply(rows,'msa-'+key);response['Cache-Control']='no-store';return response
