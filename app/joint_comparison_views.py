"""Same-snapshot, role-bound comparison. POST context and complete auditable exports."""
import csv,hashlib,io,json
from pathlib import Path
from django.contrib.auth import get_user_model
from django.core import signing
from django.db import transaction
from . import joint_comparison as comparison,joint_schedule_data as data,joint_schedule_views as original,finite_schedule as finite,joint_batch_material
from .views import api,body,reply
from .models import AuditEvent,Record
from .import_review import ReviewConflict
SALT='motor.joint-policy-comparison.v1';AGE=600

def rules():
    return finite.digest(dict(files={name:hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest() for name in ('joint_comparison.py','joint_comparison_views.py')},batch_material=joint_batch_material.definition_hash()))

def request_data(request,extra=(),required=False):
    if request.GET:raise ValueError('对照条件须放在JSON正文')
    def unique(pairs):
        value={}
        for k,v in pairs:
            if k in value:raise ValueError('对照请求有重复字段')
            value[k]=v
        return value
    try:json.loads(request.body or b'{}',object_pairs_hook=unique)
    except (UnicodeDecodeError,json.JSONDecodeError):raise ValueError('对照请求须为JSON')
    v=body(request)
    if set(v)-{'receipt',*extra} or (required and 'receipt' not in v):raise ValueError('请先读取对照，或移除未知字段')
    if 'receipt' in v and (not isinstance(v['receipt'],str) or not v['receipt']):raise ValueError('对照凭据须为非空文本')
    return v

def load(user,key,receipt=None):
    user=get_user_model().objects.get(pk=user.pk);account=original.account(user)
    left=data.load(key,'due');right=data.load(key,'priority');comparison.same_inputs(left,right);result=comparison.compare(left['result'],right['result'])
    result['batch_materials']=joint_batch_material.build(left['result'],right['result'])
    stamp=dict(key=key,account=account,source_hash=left['source_hash'],rule_hash=left['rule_hash'],comparison_rules=rules(),left=finite.digest(left['result']),right=finite.digest(right['result']),result=finite.digest(result))
    if receipt is not None:
        if not isinstance(receipt,str) or len(receipt)>4096:raise ValueError('对照凭据无效')
        try:given=signing.loads(receipt,salt=SALT,max_age=AGE)
        except signing.BadSignature:raise ReviewConflict('对照凭据无效或过期，请重新读取')
        if given!=stamp:raise ReviewConflict('物料、人机、规则或账号已变化，请重新读取对照')
    if original.account(get_user_model().objects.get(pk=user.pk))!=account:raise ReviewConflict('账号已变化，请重新读取')
    return dict(result=result,left=left,right=right,stamp=stamp,receipt=receipt or signing.dumps(stamp,salt=SALT,compress=True))

def response(v):
    r=reply(v);r['Cache-Control']='no-store';return r

def finish(d,user):
    if rules()!=d['stamp']['comparison_rules'] or original.engine.rule_hash()!=d['stamp']['rule_hash'] or original.account(get_user_model().objects.get(pk=user.pk))!=d['stamp']['account']:
        raise ReviewConflict('读取期间规则或账号变化，请重新读取对照')

@api(('POST',))
@transaction.atomic
def board(request,key):
    v=request_data(request);d=load(request.user,key,v.get('receipt'))
    # Original board receipts preserve both policy results when navigating back.
    user=get_user_model().objects.get(pk=request.user.pk)
    tickets={policy:signing.dumps(original.stamp(d[side],user),salt=original.SALT,compress=True) for policy,side in [('due','left'),('priority','right')]}
    finish(d,request.user)
    return response(dict(**d['result'],receipt=d['receipt'],receipt_seconds=AGE,policy_receipts=tickets,source_count=len(d['left']['sources']),source_hash=d['stamp']['source_hash'],rule_hash=d['stamp']['rule_hash']))

@api(('POST',))
@transaction.atomic
def sources(request,key):
    v=request_data(request,('page',),True);page=v.get('page',1)
    if type(page) is not int or not 1<=page<=10000:raise ValueError('来源页码须为1至10000整数')
    d=load(request.user,key,v['receipt']);rows=d['left']['sources']
    finish(d,request.user)
    return response(dict(rows=rows[(page-1)*40:page*40],total=len(rows),page=page,size=40))

@api(('POST',))
@transaction.atomic
def detail(request,key,task):
    v=request_data(request,required=True);d=load(request.user,key,v['receipt']);row=next((r for r in d['result']['tasks'] if r['id']==task),None)
    if row is None:raise Record.DoesNotExist()
    sides={}
    for side in ('left','right'):
        r=d[side]['result'];ids=set(row[side]['demand_ids'])
        sides[side]=dict(demands=[n for n in r['demands'] if n['id'] in ids],reservations=[a for a in r['reservations'] if a['demand_id'] in ids])
    finish(d,request.user)
    return response(dict(task=row,**sides,notice='每列包含该任务关联整批需求的全部预留；实际触发任务可能是同工序其他份号。完整来源覆盖整方案的共享竞争。'))

def document(d):
    return dict(format='motor-joint-policy-comparison-v1',synthetic=True,comparison=d['result'],left=original.export_document(d['left']),right=original.export_document(d['right']),comparison_rules=d['stamp']['comparison_rules'])

@api(('POST',))
@transaction.atomic
def export(request,key):
    v=request_data(request,('format',),True);fmt=v.get('format','json')
    if fmt not in ('json','csv'):raise ValueError('支持CSV或JSON')
    d=load(request.user,key,v['receipt']);doc=document(d)
    if fmt=='json':text=json.dumps(doc,ensure_ascii=False,indent=2,allow_nan=False)+'\n'
    else:
        stream=io.StringIO();writer=csv.writer(stream)
        def cell(x):
            s=json.dumps(x,ensure_ascii=False,allow_nan=False) if isinstance(x,(dict,list)) else '' if x is None else str(x)
            return "'"+s if s.lstrip().startswith(('=','+','-','@')) else s
        def section(name,rows):
            writer.writerow([name]);fields=list(dict.fromkeys(f for r in rows for f in r))
            writer.writerow(fields or ['无记录'])
            for r in rows:writer.writerow([cell(r.get(f)) for f in fields])
        section('对照范围',[dict(study=key,notice=comparison.NOTICE,state=d['result']['state'],source_hash=d['stamp']['source_hash'],rule_hash=d['stamp']['rule_hash'],comparison_rules=d['stamp']['comparison_rules'])])
        for name in ('summary','columns','jobs','tasks','materials','allocations','transitions'):
            value=d['result'][name];section('对照/'+name,value if isinstance(value,list) else [value] if value is not None else [])
        batch_materials=d['result']['batch_materials']
        section('批次获料/定义',[{k:batch_materials[k] for k in ('version','notice','state')}])
        section('批次获料/汇总',[batch_materials['summary']] if batch_materials['summary'] is not None else [])
        for name in ('materials','rows'):section('批次获料/'+name,batch_materials[name])
        for side in ('left','right'):
            section(side+'/结果',[doc[side]['result']])
            for group in ('material_inputs','crew_inputs','resource_inputs','references'):
                for name,rows in doc[side][group].items():section(side+'/'+group+'/'+name,rows if isinstance(rows,list) else [rows])
        section('两列共同来源',d['left']['sources']);text=stream.getvalue()
    finish(d,request.user)
    AuditEvent.objects.create(action='joint_comparison.export',actor=request.user.username,object_type='JointStudy',object_id=key,
                              detail=dict(format=fmt,source_hash=d['stamp']['source_hash'],comparison_rules=d['stamp']['comparison_rules'],file_sha256=hashlib.sha256(text.encode()).hexdigest(),business_facts_changed=False))
    return response(dict(filename='joint-compare-'+finite.digest(key)[:16]+'.'+fmt,mime='application/json' if fmt=='json' else 'text/csv',text=text))
