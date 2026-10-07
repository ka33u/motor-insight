"""Personal fixed-study views and immutable, source-backed SPC trial receipts."""
import copy,hashlib,json,re,uuid
from pathlib import Path
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied,ValidationError
from django.db import transaction
from . import access,spc,spc_data,spc_views,topic_workspace
from .schema import SCHEMAS
from .models import SPCAnalysisView,SPCResultSnapshot,Topic,Record,AuditEvent
from .import_review import ReviewConflict

MAX_VIEWS=100
MAX_SNAPSHOTS=100
MAX_BYTES=20*1024*1024
PLAN_FIELDS=('id','product_id','spec_id','equipment_id','stage','protocol_version','method','measurement_method',
             'unit','started','expected_points','baseline_end','order_basis','conditions','measurement_system_ref')
RULE_FILES=('spc.py','spc_schema.py','spc_source_contract.py','spc_data.py')
NOTICE='个人视角保存试验身份、固定采样方案、规范、计算版本和显示条件，不保存当前结果。快照另行固定当时试算、观测及Excel来源。全部为合成候选分析，不构成MSA、稳定性认定、过程能力或业务批准。'
SNAPSHOT_NOTICE='此页为创建时的受控试验结果与来源，不随当前Record指针或模型更新。只固定这一试验，不是全库历史重放。原件读取按当前权限及存档完整性核对；快照本身不授予原件访问权。'

def fresh(user):
    u=get_user_model().objects.get(pk=user.pk);spc_data.account(u)
    if not access.allowed(u,'spc_studies') or not access.allowed(u,'spc_observations'):raise PermissionDenied('当前岗位不可读取受控采样资料')
    return u

def text(value,label,limit):
    if not isinstance(value,str) or not 1<=len(value.strip())<=limit:raise ValidationError(f'{label}须为1至{limit}字')
    return value.strip()

def code(value):
    if not isinstance(value,str) or not re.fullmatch(r'[A-Z][A-Z0-9._-]{2,79}',value):raise ValidationError('视角编码须为3至80位大写字母、数字、点、下划线或短横线，并以字母开头')
    return value

def display(value):
    if not isinstance(value,dict) or set(value)!={'show_spec','decimals'} or type(value['show_spec']) is not bool or type(value['decimals']) is not int or not 4<=value['decimals']<=8:
        raise ValidationError('显示条件须指定公差开关与4至8位小数；不修改采样基线或数值')
    return dict(value)

def topic(user,key):
    if key is None:return None
    if type(key) is not int or key<=0:raise ValidationError('专题编号无效')
    return topic_workspace.visible(user,Topic.objects.all()).get(pk=key)

def definition(context,appearance):
    r=context['result']
    return dict(format_version=1,study_contract={k:r['study'].get(k) for k in PLAN_FIELDS},
                spec_contract=copy.deepcopy(r['spec']),rule_hash=context['rule_hash'],rule_version=r['rule_version'],
                as_of=r['as_of'],display=display(appearance))

def verify_view(v):
    if spc.digest(v.definition)!=v.definition_hash or v.study_id!=v.definition.get('study_contract',{}).get('id'):
        raise ReviewConflict('保存视角的定义摘要不一致，请核对历史记录')

def get_view(user,key,lock=False):
    u=fresh(user);q=SPCAnalysisView.objects.select_for_update() if lock else SPCAnalysisView.objects
    v=q.select_related('topic').get(pk=key,owner_id=u.pk);verify_view(v);return v

def view_info(v,user):
    bound=None
    if v.topic_id:
        t=topic_workspace.visible(user,Topic.objects.all()).filter(pk=v.topic_id).first()
        bound=dict(id=t.pk,name=t.name,version=t.version,available=True) if t else dict(id=v.topic_id,available=False)
    return dict(id=str(v.pk),code=v.code,name=v.name,note=v.note,study_id=v.study_id,revision=v.revision,
                archived=v.archived,definition=v.definition,definition_hash=v.definition_hash,topic=bound,
                created_at=v.created_at,updated_at=v.updated_at,notice=NOTICE)

def drift(v,context):
    now=definition(context,v.definition['display'])
    return [key for key in ('study_contract','spec_contract','rule_hash','rule_version','as_of') if v.definition.get(key)!=now.get(key)]

def require_current(v,context):
    if v.archived:raise ReviewConflict('视角已归档，历史快照仍可读取；当前试算须重新启用视角')
    changed=drift(v,context)
    if changed:raise ReviewConflict('试验、规范或计算依据与保存视角不同（'+', '.join(changed)+'），请核对并另存或更新版本')

def checked_context(request,key,receipt):
    if not isinstance(receipt,str) or not receipt:raise ValidationError('请先读取完整试验并提供当前来源凭据')
    # Existing source receipt validation is reused, not weakened for saved views.
    old=request.GET
    try:
        query=old.copy();query['receipt']=receipt;request.GET=query
        d=spc_views.context(request,key,True);spc_views.finish(request,d);return d
    finally:request.GET=old

def revision(value,v):
    if type(value) is not int or value!=v.revision:raise ReviewConflict('视角版本已变化，请重新读取后保存')

@transaction.atomic
def save_view(request,data,key=None):
    u=fresh(request.user)
    base={'code','name','note','study_id','receipt','display','topic_id'}
    required=base|({'revision'} if key else {'request_id'})
    if not isinstance(data,dict) or set(data)!=required:raise ValidationError('保存视角字段不完整或含不支持字段')
    rid=uuid.UUID(str(data['request_id'])) if not key else None
    request_hash=spc.digest(data)
    if rid:
        old=SPCAnalysisView.objects.filter(request_id=rid).first()
        if old:
            if old.owner_id!=u.pk or old.request_hash!=request_hash:raise ReviewConflict('申请号已用于其他视角内容')
            verify_view(old);return old,True
    name=text(data['name'],'视角名称',150);note=text(data['note'],'保存说明',1000)
    if len(note)<5:raise ValidationError('保存说明至少5字')
    identity=code(data['code']);study_id=text(data['study_id'],'试验编号',255);appearance=display(data['display']);t=topic(u,data['topic_id'])
    v=get_view(u,key,True) if key else None
    if v:revision(data['revision'],v)
    elif SPCAnalysisView.objects.filter(owner=u).count()>=MAX_VIEWS:raise ValidationError('本地演示每人最多100个视角，请先规划归档容量')
    if SPCAnalysisView.objects.filter(owner=u,code=identity).exclude(pk=v.pk if v else None).exists():raise ValidationError('本人已有此视角编码，请修改编码或更新原视角版本')
    d=checked_context(request,study_id,data['receipt']);conf=definition(d,appearance)
    before=view_info(v,u) if v else None
    if v:
        v.code=identity;v.name=name;v.note=note;v.study_id=study_id;v.topic=t;v.definition=conf;v.definition_hash=spc.digest(conf);v.revision+=1;v.save()
    else:v=SPCAnalysisView.objects.create(owner=u,topic=t,code=identity,name=name,note=note,study_id=study_id,
                                        definition=conf,definition_hash=spc.digest(conf),request_id=rid,request_hash=request_hash)
    # Audit failure rolls back both definition and version change.
    AuditEvent.objects.create(action='spc_view.update' if before else 'spc_view.create',actor=u.username,object_type='SPCAnalysisView',object_id=str(v.pk),
                              detail=dict(before=json.loads(json.dumps(before,default=str,ensure_ascii=False)) if before else None,
                                          after=json.loads(json.dumps(view_info(v,u),default=str,ensure_ascii=False)),business_facts_changed=False,human_business_approval=False))
    return v,False

@transaction.atomic
def archive_view(user,key,data):
    u=fresh(user);v=get_view(u,key,True)
    if not isinstance(data,dict) or set(data)!={'revision','archived'} or type(data['archived']) is not bool:raise ValidationError('归档操作须指定当前版本和布尔状态')
    revision(data['revision'],v)
    if v.archived==data['archived']:return v
    old=v.archived;v.archived=data['archived'];v.revision+=1;v.save(update_fields=['archived','revision','updated_at'])
    AuditEvent.objects.create(action='spc_view.archive',actor=u.username,object_type='SPCAnalysisView',object_id=str(v.pk),detail=dict(before=old,after=v.archived,revision=v.revision,business_facts_changed=False))
    return v

def frozen_sources(user,context):
    sources=[];fields={};wanted={}
    for s in context['sources']:
        if s.get('missing'):raise ValidationError('引用缺少来源事实，不能冻结完整试验；请先核对导入')
        wanted.setdefault(s['dataset'],[]).append(s['key'])
    records={}
    for ds,keys in sorted(wanted.items()):
        names=[f['name'] for f in access.permitted_fields(user,ds) if 'cents' not in f['name']];fields[ds]=names
        for start in range(0,len(keys),400):
            for r in spc_data.queryset(ds).filter(business_key__in=keys[start:start+400]):records[(ds,r.business_key)]=r
    for s in context['sources']:
        r=records.get((s['dataset'],s['key']))
        if r is None or spc_data.source(r)!=s:raise ReviewConflict('冻结期间来源引用变化，请重新读取完整试验')
        sources.append({**s,'record_id':r.pk,'source_row_id':r.source_row_id,
                        'values':{k:v for k,v in r.values.items() if k in fields[r.dataset]}})
    return sources,fields

def snapshot_receipt(s):
    return dict(id=str(s.pk),owner_id=s.owner_id,view_id=str(s.view_id),topic_id=s.topic_id,
                request_id=str(s.request_id),name=s.name,note=s.note,created_at=s.created_at.isoformat())

def verify_snapshot(s):
    if spc.digest(s.payload)!=s.payload_hash or s.payload.get('receipt')!=snapshot_receipt(s):raise ReviewConflict('受控试验快照完整性核验失败，已暂停读取')
    if s.payload.get('format_version')!=1:raise ReviewConflict('受控试验快照格式暂不支持')
    if s.payload.get('formal_qualification') is not False:raise ReviewConflict('快照适用性声明异常')

def authorize_snapshot(user,s):
    u=fresh(user)
    if s.owner_id!=u.pk:raise PermissionDenied('受控试验快照仅创建者读取')
    if s.topic_id:topic(u,s.topic_id)
    for ds,names in s.payload['fields'].items():
        if not access.allowed(u,ds) or not set(names)<={f['name'] for f in access.permitted_fields(u,ds)}:raise PermissionDenied('快照包含当前不可访问的来源字段')
    return u

def get_snapshot(user,key):
    u=fresh(user);s=SPCResultSnapshot.objects.get(pk=key,owner=u);verify_snapshot(s);authorize_snapshot(u,s);return s

def snapshot_info(s):
    r=s.payload['result'];v=s.payload['view']
    return dict(id=str(s.pk),view_id=str(s.view_id),topic_id=s.topic_id,name=s.name,note=s.note,created_at=s.created_at,
                payload_hash=s.payload_hash,view_code=v['code'],view_revision=v['revision'],study_id=r['study']['id'],
                state=r['state'],as_of=r['as_of'],observations=len(r['points']),source_count=len(s.payload['sources']),notice=SNAPSHOT_NOTICE)

@transaction.atomic
def create_snapshot(request,data):
    u=fresh(request.user)
    if not isinstance(data,dict) or set(data)!={'request_id','view_id','revision','receipt','name','note'}:raise ValidationError('保存快照字段不完整或含不支持字段')
    rid=uuid.UUID(str(data['request_id']));request_hash=spc.digest(data);old=SPCResultSnapshot.objects.filter(request_id=rid).first()
    if old:
        if old.owner_id!=u.pk or old.request_hash!=request_hash:raise ReviewConflict('申请号已用于其他快照内容')
        return get_snapshot(u,old.pk),True
    if SPCResultSnapshot.objects.filter(owner=u).count()>=MAX_SNAPSHOTS:raise ValidationError('本地演示每人最多100份受控试验快照')
    v=get_view(u,data['view_id'],True);revision(data['revision'],v)
    if v.topic_id:topic(u,v.topic_id)
    d=checked_context(request,v.study_id,data['receipt']);require_current(v,d)
    name=text(data['name'],'快照名称',120);note=text(data['note'],'快照说明',1000)
    if len(note)<5:raise ValidationError('快照说明至少5字')
    sources,fields=frozen_sources(u,d);rules={}
    for filename in RULE_FILES:
        raw=(Path(__file__).parent/filename).read_bytes();rules[filename]=dict(sha256=hashlib.sha256(raw).hexdigest(),text=raw.decode('utf-8'))
    combined=hashlib.sha256(b''.join(rules[n]['text'].encode() for n in RULE_FILES)).hexdigest()
    if combined!=d['rule_hash']:raise ReviewConflict('冻结期间计算规则变化，请重新读取')
    s=SPCResultSnapshot(owner=u,view=v,topic_id=v.topic_id,request_id=rid,request_hash=request_hash,name=name,note=note)
    payload=dict(format_version=1,receipt=snapshot_receipt(s),view=json.loads(json.dumps(view_info(v,u),default=str,ensure_ascii=False)),
                 result=copy.deepcopy(d['result']),sources=sources,fields=fields,rule_sources=rules,
                 source_hash=d['source_hash'],rule_hash=d['rule_hash'],formal_qualification=False,notice=SNAPSHOT_NOTICE)
    raw=json.dumps(payload,ensure_ascii=False,allow_nan=False,separators=(',',':')).encode()
    if len(raw)>MAX_BYTES:raise ValidationError('受控试验快照超过20MB，请拆分采样试验')
    spc_views.finish(request,d);s.payload=payload;s.payload_hash=spc.digest(payload);s.save()
    AuditEvent.objects.create(action='spc_snapshot.create',actor=u.username,object_type='SPCResultSnapshot',object_id=str(s.pk),
                              detail=dict(view_id=str(v.pk),view_revision=v.revision,topic_id=v.topic_id,payload_hash=s.payload_hash,
                                          observations=len(d['result']['points']),sources=len(sources),business_facts_changed=False,human_business_approval=False))
    return s,False

def public_board(result,page):
    points=result['points']
    return dict(**{k:v for k,v in result.items() if k!='points'},rows=points[(page-1)*25:page*25],total=len(points),page=page,size=25,
                chart_points=[{k:p.get(k) for k in ('id','sequence','value','segment','eligible','mr','i_signal','mr_signal','spec_outside')} for p in points],synthetic=True)

def compare(s,current):
    old=s.payload['result'];now=current['result'];v=s.payload['view']['definition'];conf=definition(current,v['display'])
    changed=[k for k in ('study_contract','spec_contract','rule_hash','rule_version') if v.get(k)!=conf.get(k)]
    a={p['id']:p for p in old['points']};b={p['id']:p for p in now['points']};rows=[]
    source_before={(r['dataset'],r['key']):r for r in s.payload['sources']};source_after={(r['dataset'],r['key']):r for r in current['sources']}
    baseline_changed=False
    value_fields=('sequence','unit_id','value','unit','state','replicate','method_version','measured','registered','operator_id','temperature_c','reference','note')
    derived=('eligible','reasons','mr','i_signal','mr_signal','spec_outside')
    for key in sorted(set(a)|set(b),key=lambda k:((a.get(k) or b[k]).get('sequence') or 0,k)):
        previous=a.get(key);present=b.get(key);kinds=[]
        if previous is None:kinds.append('added')
        elif present is None:kinds.append('missing_current')
        else:
            if any(previous.get(k)!=present.get(k) for k in value_fields):kinds.append('observation_changed')
            if any(previous.get(k)!=present.get(k) for k in derived):kinds.append('calculation_changed')
        origin=source_before.get(('spc_observations',key));latest=source_after.get(('spc_observations',key))
        if origin and latest and any(origin.get(k)!=latest.get(k) for k in ('revision','record_hash','batch_id','file_hash','sheet','row')):kinds.append('source_version_changed')
        if kinds:
            if any(p and p.get('segment')=='baseline' for p in (previous,present)):baseline_changed=True
            rows.append(dict(id=key,kinds=kinds,before=previous,current=present))
    return dict(state='definitions_changed' if changed else 'baseline_evidence_changed' if baseline_changed else 'data_changed' if rows else 'same_observations',
                definition_changes=changed,baseline_evidence_changed=baseline_changed,
                limits_before=old['limits'],limits_current=now['limits'],limits_changed=old['limits']!=now['limits'],
                coverage_before=old['coverage'],coverage_current=now['coverage'],signal_counts_before=old['signal_counts'],signal_counts_current=now['signal_counts'],
                old_as_of=old['as_of'],current_as_of=now['as_of'],source_changed=s.payload['source_hash']!=current['source_hash'],
                rows=rows,total=len(rows),pointwise_comparable=not changed,causal_claim=False,
                notice='对照创建时与当前同一试验的资料、来源版本及规则。定义变化时不作同口径数值差异判断；基线资料有更正时保留两组控制限。变化不能推断为生产改善、因果关系或质量批准。')
