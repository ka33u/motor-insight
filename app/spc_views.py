"""Read-only trial charts, account-bound source evidence, and complete CSV."""
import hashlib,json
from pathlib import Path
from django.core import signing
from django.db import transaction
from . import analytics,access,spc,spc_data
from .models import Record,AuditEvent
from .views import api,reply
from .import_review import ReviewConflict
from .quality_views import csv_reply

MAX_AGE=600
SALT='motor.spc.fixed-study.v1'
SIZE=25

def params(request,extra=()):
    if set(request.GET)-{'page',*extra}:raise ValueError('采样范围字段无效')
    if any(len(request.GET.getlist(k))!=1 for k in request.GET):raise ValueError('采样范围不可重复')
    value=request.GET.get('page','1')
    if not value.isascii() or not value.isdecimal() or not 1<=int(value)<=10000:raise ValueError('页码须为1至10000的整数')
    return int(value)

def response(value):
    out=reply(value);out['Cache-Control']='no-store';return out

def stamp(context,user):
    h=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    return dict(study_id=context['result']['study']['id'],source_hash=context['source_hash'],
                rule_hash=context['rule_hash'],view_hash=h,as_of=analytics.AS_OF,account=spc_data.account(user))

def context(request,key,required=False):
    d=spc_data.load(key);expected=stamp(d,request.user);given=request.GET.get('receipt')
    if required and not given:raise ValueError('请先读取当前固定试验以获取来源凭据')
    if given:
        if len(given)>4096:raise ValueError('采样凭据过长')
        try:actual=signing.loads(given,salt=SALT,max_age=MAX_AGE)
        except signing.BadSignature:raise ReviewConflict('采样凭据无效或已过期，请重新读取试验')
        if actual!=expected:raise ReviewConflict('试验、来源、规则或账号权限已变化，请重新读取')
    receipt=given or signing.dumps(expected,salt=SALT,compress=True)
    d['receipt']=receipt;d['stamp']=expected
    return d

def finish(request,d):
    if stamp(d,request.user)!=d['stamp']:raise ReviewConflict('读取期间规则或账号权限变化，请重新读取试验')

def selected(d,point_id):
    point=next((p for p in d['result']['points'] if p['id']==point_id),None)
    if point is None:raise Record.DoesNotExist()
    return point

@api()
@transaction.atomic
def studies(request):
    params(request);spc_data.account(request.user)
    rows=list(spc_data.queryset('spc_studies').order_by('business_key')[:1001])
    if len(rows)>1000:raise ValueError('试验目录超过1000项，请先调整目录范围')
    return response(dict(rows=[dict(id=r.business_key,**{k:r.values.get(k) for k in ('name','product_id','equipment_id','unit','expected_points','baseline_end','order_basis')}) for r in rows],
                         as_of=analytics.AS_OF,synthetic=True,notice=spc.NOTICE))

@api()
@transaction.atomic
def board(request,key):
    page=params(request,('receipt',));d=context(request,key);result=d['result'];points=result['points'];finish(request,d)
    return response(dict(**{k:v for k,v in result.items() if k!='points'},
                         rows=points[(page-1)*SIZE:page*SIZE],total=len(points),page=page,size=SIZE,
                         chart_points=[{k:p.get(k) for k in ('id','sequence','value','segment','eligible','mr','i_signal','mr_signal','spec_outside')} for p in points],
                         product=access.sanitize(request.user,'products',d['product']) if d['product'] else None,
                         equipment=access.sanitize(request.user,'equipment',d['equipment']) if d['equipment'] else None,
                         receipt=d['receipt'],receipt_seconds=MAX_AGE,
                         source_hash=d['source_hash'],rule_hash=d['rule_hash'],synthetic=True))

@api()
@transaction.atomic
def detail(request,key,point_id):
    params(request,('receipt',));d=context(request,key,True);point=selected(d,point_id);finish(request,d)
    return response(dict(row=point,sources=spc_data.point_sources(d,point),study=d['result']['study'],limits=d['result']['limits'],
                         receipt=d['receipt'],source_hash=d['source_hash'],rule_hash=d['rule_hash'],
                         can_download_original=access.can_import(request.user),notice=spc.NOTICE))

@api()
@transaction.atomic
def evidence(request,key):
    page=params(request,('receipt',));d=context(request,key,True);finish(request,d)
    return response(dict(rows=d['sources'][(page-1)*40:page*40],total=len(d['sources']),page=page,size=40,
                         receipt=d['receipt'],can_download_original=access.can_import(request.user)))

@api()
@transaction.atomic
def export(request,key):
    params(request,('receipt',));d=context(request,key,True);r=d['result'];limits=r['limits'] or {}
    out=[['过程稳定性 · 全部合成模拟','固定试验',key,'业务截止',r['as_of']],
         ['资料摘要',d['source_hash'],'模型摘要',d['rule_hash']],['固定基线末序号',r['baseline_policy']['baseline_end'],'页面翻页不改变基线或导出范围'],
         ['候选状态',r['state'],'暂停原因','；'.join(r['issues'])],['说明',spc.NOTICE],
         ['基线中心',limits.get('center'),'I下控限',limits.get('i_lcl'),'I上控限',limits.get('i_ucl'),'MR上控限',limits.get('mr_ucl')],
         ['产品下限',r['spec'].get('lsl'),'产品上限',r['spec'].get('usl'),'产品限值与控制限含义不同'],
         ['观测号','序号','SN','分段','测量时间','登记时间','标准数值','单位','观测状态','观测字段检查通过','字段待核对原因','相邻移动极差','I规则信号','MR规则信号','产品规范超限','方法版本','模拟温度C','来源依据','Excel文件','工作表','行号']]
    sources={(s['dataset'],s['key']):s for s in d['sources']}
    for p in r['points']:
        s=sources[('spc_observations',p['id'])]
        out.append([p.get(k) for k in ('id','sequence','unit_id','segment','measured','registered','value','unit','state','eligible')]+
                   ['；'.join(p['reasons'])]+[p.get(k) for k in ('mr','i_signal','mr_signal','spec_outside','method_version','temperature_c','reference')]+[s['filename'],s['sheet'],s['row']])
    finish(request,d)
    AuditEvent.objects.create(action='spc.export',actor=request.user.username,object_type='SPCStudy',object_id=key,
                              detail=dict(source_hash=d['source_hash'],rule_hash=d['rule_hash'],rows=len(r['points']),fixed_baseline=r['baseline_policy'],business_facts_changed=False))
    out=csv_reply(out,'spc-'+key);out['Cache-Control']='no-store';return out
