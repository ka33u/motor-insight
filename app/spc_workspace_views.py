"""Personal SPC definitions, frozen point evidence, exports and current comparison."""
import hashlib,json
from pathlib import Path
from django.core.exceptions import PermissionDenied,ObjectDoesNotExist
from django.core import signing
from django.db import transaction
from django.http import FileResponse,HttpResponse
from . import spc_workspace as workspace,spc_views,spc_data,spc,access
from .models import SPCAnalysisView,SPCResultSnapshot,ImportRow,AuditEvent,Record
from .views import api,reply,body,archived_import_path,require
from .ingestion import fingerprint
from .quality_views import csv_reply
from .import_review import ReviewConflict

SALT='motor.spc.snapshot.read.v1'
COMPARE_SALT='motor.spc.snapshot.compare.v1'
MAX_AGE=600

def response(value):
    r=reply(value);r['Cache-Control']='no-store';return r

def params(request,keys=()):
    if set(request.GET)-{'page',*keys} or any(len(request.GET.getlist(k))!=1 for k in request.GET):raise ValueError('受控试验视角范围字段无效或重复')
    p=request.GET.get('page','1')
    if not p.isascii() or not p.isdecimal() or not 1<=int(p)<=10000:raise ValueError('页码须为1至10000的整数')
    return int(p)

def snapshot_stamp(s,user):
    return dict(id=str(s.pk),payload_hash=s.payload_hash,account=spc_data.account(user))

def checked_receipt(request,stamp,salt,required=False):
    given=request.GET.get('receipt')
    if required and not given:raise ValueError('请先读取当前快照或对照范围')
    if given:
        if len(given)>4096:raise ValueError('快照凭据过长')
        try:actual=signing.loads(given,salt=salt,max_age=MAX_AGE)
        except signing.BadSignature:raise ReviewConflict('快照凭据无效或已过期，请重新读取')
        if actual!=stamp:raise ReviewConflict('快照、当前资料或账号权限已变化，请重新读取')
    return given or signing.dumps(stamp,salt=salt,compress=True)

def frozen_context(request,key,required=False):
    s=workspace.get_snapshot(request.user,key);stamp=snapshot_stamp(s,request.user)
    token=checked_receipt(request,stamp,SALT,required);return s,stamp,token

def finish_snapshot(request,s,stamp):
    workspace.verify_snapshot(s)
    if snapshot_stamp(s,request.user)!=stamp:raise ReviewConflict('读取期间账号或快照权限变化，请重新读取')

def selected(s,key):
    p=next((p for p in s.payload['result']['points'] if p['id']==key),None)
    if p is None:raise Record.DoesNotExist()
    return p

@api(('GET','POST'))
@transaction.atomic
def views(request):
    if request.method=='POST':
        v,repeated=workspace.save_view(request,body(request));return response(dict(view=workspace.view_info(v,workspace.fresh(request.user)),repeated=repeated))
    params(request,('topic_id','archived'));u=workspace.fresh(request.user);q=SPCAnalysisView.objects.filter(owner=u).select_related('topic').order_by('-updated_at','id')
    archived=request.GET.get('archived','0')
    if archived not in {'0','1','all'}:raise ValueError('归档筛选不可用')
    if archived!='all':q=q.filter(archived=archived=='1')
    if request.GET.get('topic_id'):
        value=request.GET['topic_id']
        if not value.isascii() or not value.isdecimal() or int(value)<=0:raise ValueError('专题编号无效')
        workspace.topic(u,int(value));q=q.filter(topic_id=int(value))
    return response(dict(rows=[workspace.view_info(v,u) for v in q],total=q.count(),private=True,notice=workspace.NOTICE))

@api(('GET','POST'))
@transaction.atomic
def view(request,key):
    if request.method=='POST':v,repeated=workspace.save_view(request,body(request),key)
    else:params(request);v=workspace.get_view(request.user,key);repeated=False
    return response(dict(view=workspace.view_info(v,workspace.fresh(request.user)),repeated=repeated))

@api(('POST',))
@transaction.atomic
def archive(request,key):
    v=workspace.archive_view(request.user,key,body(request));return response(dict(view=workspace.view_info(v,workspace.fresh(request.user))))

@api()
@transaction.atomic
def run(request,key):
    page=params(request,('receipt',));v=workspace.get_view(request.user,key);d=spc_views.context(request,v.study_id);workspace.require_current(v,d);spc_views.finish(request,d)
    return response(dict(**workspace.public_board(d['result'],page),view=workspace.view_info(v,workspace.fresh(request.user)),
                         source_hash=d['source_hash'],rule_hash=d['rule_hash'],receipt=d['receipt'],receipt_seconds=MAX_AGE,
                         mode='live_view',product=None,equipment=None))

@api(('GET','POST'))
@transaction.atomic
def snapshots(request):
    if request.method=='POST':
        s,repeated=workspace.create_snapshot(request,body(request));return response(dict(snapshot=workspace.snapshot_info(s),repeated=repeated))
    page=params(request,('view_id','topic_id'));u=workspace.fresh(request.user);q=SPCResultSnapshot.objects.filter(owner=u).order_by('-created_at','id')
    if request.GET.get('view_id'):
        v=workspace.get_view(u,request.GET['view_id']);q=q.filter(view=v)
    if request.GET.get('topic_id'):
        value=request.GET['topic_id']
        if not value.isascii() or not value.isdecimal():raise ValueError('专题编号无效')
        t=workspace.topic(u,int(value));q=q.filter(topic=t)
    rows=[]
    for s in q[(page-1)*20:page*20]:
        try:workspace.verify_snapshot(s);workspace.authorize_snapshot(u,s)
        except (ReviewConflict,PermissionDenied,ObjectDoesNotExist):
            rows.append(dict(id=str(s.pk),available=False,created_at=s.created_at));continue
        rows.append(dict(**workspace.snapshot_info(s),available=True))
    return response(dict(rows=rows,total=q.count(),page=page,size=20,private=True,notice=workspace.SNAPSHOT_NOTICE))

@api()
@transaction.atomic
def snapshot(request,key):
    page=params(request,('receipt',));s,stamp,token=frozen_context(request,key);finish_snapshot(request,s,stamp)
    r=s.payload['result']
    value=workspace.public_board(r,page)
    value.update(snapshot=workspace.snapshot_info(s),view=s.payload['view'],mode='snapshot',
                         receipt=token,receipt_seconds=MAX_AGE,source_hash=s.payload['source_hash'],rule_hash=s.payload['rule_hash'],
                         product=None,equipment=None,notice=workspace.SNAPSHOT_NOTICE+' '+r['notice'])
    return response(value)

@api()
@transaction.atomic
def snapshot_point(request,key,point_id):
    params(request,('receipt',));s,stamp,token=frozen_context(request,key,True);p=selected(s,point_id)
    context=dict(result=s.payload['result'],sources=s.payload['sources']);sources=spc_data.point_sources(context,p);finish_snapshot(request,s,stamp)
    return response(dict(row=p,sources=sources,study=s.payload['result']['study'],limits=s.payload['result']['limits'],
                         receipt=token,source_hash=s.payload['source_hash'],rule_hash=s.payload['rule_hash'],
                         can_download_original=access.can_import(workspace.fresh(request.user)),original_base='/api/spc-result-snapshots/'+str(s.pk)+'/original/',
                         snapshot=workspace.snapshot_info(s),notice=workspace.SNAPSHOT_NOTICE))

@api()
@transaction.atomic
def snapshot_sources(request,key):
    page=params(request,('receipt',));s,stamp,token=frozen_context(request,key,True);sources=s.payload['sources'];finish_snapshot(request,s,stamp)
    return response(dict(rows=sources[(page-1)*40:page*40],total=len(sources),page=page,size=40,receipt=token,can_download_original=access.can_import(workspace.fresh(request.user))))

@api()
@transaction.atomic
def original(request,key,row_id):
    params(request,('receipt',));s,stamp,token=frozen_context(request,key,True);u=workspace.fresh(request.user);require(access.can_import(u),'快照不授予Excel归档原件读取权')
    source=next((r for r in s.payload['sources'] if r['source_row_id']==row_id),None)
    if source is None:raise ImportRow.DoesNotExist()
    row=ImportRow.objects.select_related('batch').get(pk=row_id);batch=row.batch
    if fingerprint(row.normalized)!=source['record_hash'] or (row.dataset,row.business_key,row.record_hash,str(batch.pk),batch.file_hash,row.sheet,row.row_number)!=(source['dataset'],source['key'],source['record_hash'],source['batch_id'],source['file_hash'],source['sheet'],source['row']):
        raise ReviewConflict('快照声明的导入行或归档摘要已变化，原件下载暂停')
    path=archived_import_path(batch);raw=path.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=source['file_hash']:raise ReviewConflict('存档字节与快照声明不同')
    finish_snapshot(request,s,stamp)
    AuditEvent.objects.create(action='spc_snapshot.original',actor=u.username,object_type='SPCResultSnapshot',object_id=str(s.pk),detail=dict(source_row_id=row_id,payload_hash=s.payload_hash,business_facts_changed=False))
    # Send the exact checked bytes; a later path replacement cannot alter this response.
    r=HttpResponse(raw,content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    from urllib.parse import quote
    r['Content-Disposition']="attachment; filename*=UTF-8''"+quote(Path(source['filename']).name);r['Cache-Control']='no-store';return r

@api()
@transaction.atomic
def export(request,key):
    params(request,('receipt','format'));s,stamp,token=frozen_context(request,key,True);fmt=request.GET.get('format','csv')
    if fmt not in {'csv','json'}:raise ValueError('快照导出仅支持csv或json')
    if fmt=='json':
        r=HttpResponse(json.dumps(dict(snapshot=workspace.snapshot_info(s),payload=s.payload),ensure_ascii=False,default=str,indent=2),content_type='application/json; charset=utf-8')
        r['Content-Disposition']='attachment; filename="spc-snapshot-'+str(s.pk)+'.json"'
    else:
        result=s.payload['result'];out=[['受控试验冻结快照 · 全部合成模拟',str(s.pk),s.name],['来源摘要',s.payload['source_hash'],'计算摘要',s.payload['rule_hash']],
             ['视角',s.payload['view']['code'],'保存版本',s.payload['view']['revision'],'业务截止',result['as_of']],['说明',workspace.SNAPSHOT_NOTICE],
             ['观测号','序号','SN','分段','标准数值','单位','字段可用','相邻MR','I信号','MR信号','产品规范超限','待核对原因','文件','工作表','行号']]
        refs={(r['dataset'],r['key']):r for r in s.payload['sources']}
        for p in result['points']:
            source=refs[('spc_observations',p['id'])]
            out.append([p.get(k) for k in ('id','sequence','unit_id','segment','value','unit','eligible','mr','i_signal','mr_signal','spec_outside')]+['；'.join(p['reasons']),source['filename'],source['sheet'],source['row']])
        r=csv_reply(out,'spc-snapshot-'+str(s.pk))
    finish_snapshot(request,s,stamp)
    AuditEvent.objects.create(action='spc_snapshot.export',actor=request.user.username,object_type='SPCResultSnapshot',object_id=str(s.pk),detail=dict(format=fmt,payload_hash=s.payload_hash,observations=len(s.payload['result']['points']),business_facts_changed=False))
    r['Cache-Control']='no-store';return r

@api()
@transaction.atomic
def compare_current(request,key):
    page=params(request,('receipt',));s=workspace.get_snapshot(request.user,key)
    try:current=spc_data.load(s.payload['result']['study']['id'])
    except Record.DoesNotExist:return response(dict(state='source_missing',rows=[],total=0,pointwise_comparable=False,notice='当前试验来源已不可读取；冻结结果保留，不补零或猜测当前状态'))
    value=workspace.compare(s,current);stamp=dict(snapshot=snapshot_stamp(s,request.user),source_hash=current['source_hash'],rule_hash=current['rule_hash'])
    token=checked_receipt(request,stamp,COMPARE_SALT);value['rows']=value['rows'][(page-1)*25:page*25]
    value.update(page=page,size=25,receipt=token,receipt_seconds=MAX_AGE,snapshot=workspace.snapshot_info(s))
    if snapshot_stamp(s,request.user)!=stamp['snapshot']:raise ReviewConflict('对照期间账号或快照权限变化，请刷新')
    return response(value)
