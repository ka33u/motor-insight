"""Source-bound WIP remainder trial, complete provenance and safe exports."""
import hashlib,json
from pathlib import Path
from django.contrib.auth import get_user_model
from django.core import signing
from django.db import transaction
from django.http import HttpResponse
from . import wip_trial as engine,wip_trial_data as data,finite_schedule as finite,spc_data,access,analytics
from .wip_trial_schema import DATASETS
from .models import Record,AuditEvent
from .views import api,reply,require
from .import_review import ReviewConflict
from .quality_views import csv_reply

SALT='motor.wip-remainder.v1';AGE=600


def account(user):
    fresh=get_user_model().objects.get(pk=user.pk)
    for ds in (*DATASETS,'joint_studies','skills'):require(access.allowed(fresh,ds),'当前岗位不能读取在制物料及人员试排')
    return spc_data.account(fresh)


def params(request,allowed=()):
    if set(request.GET)-set(allowed) or any(len(request.GET.getlist(k))!=1 for k in request.GET):raise ValueError('在制试排范围字段无效或重复')


def stamp(d,user):
    return dict(study=d['result']['study']['id'],policy=d['result']['policy'],source_hash=d['source_hash'],rule_hash=d['rule_hash'],
        result_hash=finite.digest(d['result']),account=account(user),view_hash=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),as_of=analytics.AS_OF)


def context(request,key,required=False):
    account(request.user);d=data.load(key,request.GET.get('policy','due'));value=stamp(d,request.user);given=request.GET.get('receipt')
    if required and not given:raise ValueError('请先读取当前在制试排，再查看明细、来源或导出')
    if given:
        if len(given)>4096:raise ValueError('试排凭据过长')
        try:actual=signing.loads(given,salt=SALT,max_age=AGE)
        except signing.BadSignature:raise ReviewConflict('试排凭据无效或过期，请重新计算')
        if actual!=value:raise ReviewConflict('报工、余料、人机、版本、规则或账号变化，请重新计算')
    d.update(stamp=value,receipt=given or signing.dumps(value,salt=SALT,compress=True));return d


def finish(request,d):
    if stamp(d,request.user)!=d['stamp'] or engine.rule_hash()!=d['rule_hash']:raise ReviewConflict('读取期间规则或权限变化，请重新计算')


def response(value):
    r=reply(value);r['Cache-Control']='no-store';return r


@api()
@transaction.atomic
def studies(request):
    params(request);account(request.user);rows=list(spc_data.queryset('wip_trial_studies').order_by('values__series','-values__version','business_key')[:1001])
    if len(rows)>1000:raise ValueError('方案超过1000项，未截断')
    latest={}
    for r in rows:latest[r.values['series']]=max(latest.get(r.values['series'],0),r.values['version'])
    return response(dict(rows=[r.values|dict(is_latest=r.values['version']==latest[r.values['series']]) for r in rows],policies=finite.POLICIES,notice=engine.NOTICE,synthetic=True))


@api()
@transaction.atomic
def board(request,key):
    params(request,('policy','receipt'));d=context(request,key);finish(request,d)
    return response(dict(**d['result'],receipt=d['receipt'],receipt_seconds=AGE,source_hash=d['source_hash'],rule_hash=d['rule_hash'],source_count=len(d['sources']),parent_reference=d['parent_reference'],work_orders=d['tables']['wip_trial_jobs'],synthetic=True))


@api()
@transaction.atomic
def sources(request,key):
    params(request,('policy','receipt','page'));p=request.GET.get('page','1')
    if not p.isascii() or not p.isdecimal() or not 1<=int(p)<=10000:raise ValueError('来源页码须为1至10000整数')
    p=int(p);d=context(request,key,True);finish(request,d)
    return response(dict(rows=d['sources'][(p-1)*40:p*40],total=len(d['sources']),size=40,page=p,receipt=d['receipt'],can_download_original=access.can_import(request.user)))


@api()
@transaction.atomic
def detail(request,key,task_id):
    params(request,('policy','receipt'));d=context(request,key,True);r=d['result'];row=next((x for x in r['tasks'] if x['id']==task_id),None)
    if row is None:raise Record.DoesNotExist()
    demands=[x for x in r['demands'] if x['task_id']==task_id];mids={x['material_id'] for x in demands}
    progress=next(x for x in d['tables']['wip_trial_tasks'] if x['task_id']==task_id)
    finish(request,d)
    return response(dict(row=row,progress=progress,operation=next((x for x in d['references']['operations'] if x['id']==row['operation_id']),None),
        demands=demands,reservations=[x for x in r['reservations'] if x['task_id']==task_id],lots=[x for x in r['lots'] if x['material_id'] in mids],
        receipt=d['receipt'],notice='明细保留原报工、剩余用料和预留。余料为全方案共享或专属池，不能再次加到需求上；请连同全方案来源核对竞争关系。'))


def document(d):
    return dict(format='motor-wip-remainder-trial-v1',synthetic=True,as_of=analytics.AS_OF,result=d['result'],
        inputs=dict(study=d['result']['study'],**d['tables']),parent_inputs=d['parent_inputs'],references=d['references'],version_history=d['version_history'],
        parent_reference=d['parent_reference'],sources=d['sources'],source_hash=d['source_hash'],rule_hash=d['rule_hash'],result_hash=finite.digest(d['result']),notice=engine.NOTICE)


@api()
@transaction.atomic
def export(request,key):
    params(request,('policy','receipt','format'));fmt=request.GET.get('format','json')
    if fmt not in ('csv','json'):raise ValueError('支持CSV或JSON')
    d=context(request,key,True);doc=document(d);name='wip-remainder-'+finite.digest(key)[:16]
    if fmt=='json':
        file=HttpResponse(json.dumps(doc,ensure_ascii=False,indent=2,allow_nan=False)+'\n',content_type='application/json; charset=utf-8')
        file['Content-Disposition']='attachment; filename="'+name+'.json"'
    else:
        rows=[['在制剩余试排 · 合成模拟',key],['边界',engine.NOTICE],['结果状态',d['result']['state']],['原始依据',d['source_hash']],['规则',d['rule_hash']]]
        def section(label,items):
            rows.append([]);rows.append([label]);fields=list(dict.fromkeys(k for r in items for k in r));rows.append(fields or ['无行，不能推定为零或已完成'])
            for r in items:rows.append([json.dumps(r[k],ensure_ascii=False,allow_nan=False) if isinstance(r.get(k),(dict,list)) else r.get(k) for k in fields])
        section('完整结果',[doc['result']])
        for name_,tables in [('输入',doc['inputs']),('原始试排输入',doc['parent_inputs']),('依据',doc['references'])]:
            for ds,items in tables.items():section(name_+'/'+ds,items if isinstance(items,list) else [items])
        section('版本历史',doc['version_history']);section('来源',d['sources']);file=csv_reply(rows,name)
    finish(request,d)
    AuditEvent.objects.create(action='wip_trial.export',actor=request.user.username,object_type='WipRemainderTrial',object_id=key,
        detail=dict(format=fmt,policy=d['result']['policy'],source_hash=d['source_hash'],rule_hash=d['rule_hash'],file_sha256=hashlib.sha256(file.content).hexdigest(),business_facts_changed=False))
    file['Cache-Control']='no-store';return file
