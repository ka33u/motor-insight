"""Preview candidate model definitions against current facts before an atomic update."""
import copy
import hashlib
import json
import math
import uuid
from pathlib import Path
from django.contrib.auth import get_user_model
from django.core import signing
from django.core.exceptions import ValidationError, PermissionDenied
from django.core.serializers.json import DjangoJSONEncoder
from django.db import transaction
from . import access, analytics, analysis_engine as engine, bi_scope, bi_card_summary, topic_linkage, topic_workspace as ws, spc_data
from .models import AnalysisModel, AnalysisModelChange, Topic, TopicView, TopicPage, TopicSnapshot, AnalysisModelCard, Record, AuditEvent
from .views import model_info
from .import_review import ReviewConflict

AGE=600
NOTICE='在同一份当前资料上分别执行原定义与候选定义；试算差异是配置影响，不是经营改善或因果结论。预演不改模型或业务事实，保存模型不等于发布指标或业务批准。'
BASE_KEYS={'version','candidate','scope','links'}


def clean(value):
    return json.loads(json.dumps(value,ensure_ascii=False,cls=DjangoJSONEncoder,allow_nan=False))


def exact(value,keys):
    if not isinstance(value,dict) or set(value)!=set(keys):raise ValidationError('模型预演参数不完整或包含未知字段')


def fresh(user):
    user=get_user_model().objects.get(pk=user.pk)
    if not access.can_edit(user):raise PermissionDenied('当前岗位不能修改分析模型')
    return user


def owned(user,key,lock=False):
    query=AnalysisModel.objects.select_for_update() if lock else AnalysisModel.objects
    model=ws.visible(user,query.all()).get(pk=key)
    if model.owner!=user.username and access.role(user)!='admin':raise PermissionDenied('只能更新本人模型')
    engine.validate_definition(user,model.dataset,model.definition,allow_inactive=True)
    return model


def rules():
    return ws.digest({n:hashlib.sha256(Path(__file__).with_name(n).read_bytes()).hexdigest() for n in
        ('model_changes.py','model_change_views.py','analysis_engine.py','bi_card_summary.py','bi_scope.py','topic_linkage.py','access.py')})


def normalize(user,model,data):
    exact(data,BASE_KEYS)
    if type(data['version']) is not int or data['version']!=model.version:raise ReviewConflict('原模型已更新，请重新载入后预演')
    candidate=data['candidate'];exact(candidate,('name','dataset','definition','is_public'))
    if not isinstance(candidate['name'],str) or not 1<=len(candidate['name'].strip())<=150:raise ValidationError('模型名称需为1—150字')
    if type(candidate['is_public']) is not bool:raise ValidationError('请明确共享状态')
    if not isinstance(candidate['dataset'],str):raise ValidationError('数据集无效')
    engine.validate_definition(user,candidate['dataset'],candidate['definition'])
    if candidate['is_public'] and candidate['definition'].get('grouping_ref'):raise ValidationError('含个人业务分组的模型只能私有保存')
    if not isinstance(data['scope'],dict):raise ValidationError('试算范围须为对象')
    links=None if data['links'] is None else topic_linkage.validate(data['links'])
    return dict(version=model.version,candidate={**copy.deepcopy(candidate),'name':candidate['name'].strip()},scope=bi_scope.validate_scope(data['scope']),links=links)


def contains(binding,key):
    return any(c.get('model_id')==key for c in binding.get('cards',[]))


def scope_check(user,before,candidate,config):
    try:
        conf=ws.config(config)
        contract=bi_scope.contract(candidate['dataset'])
        for scope in (conf['scope'],conf['reference_scope']):
            for key in scope or {}:
                if not contract['date' if key in ('from','to') else key]:raise ValidationError('候选数据集不支持'+bi_scope.LABELS[key])
        topic_linkage.effective(user,candidate,conf.get('links'))
        if any(k in (scope or {}) for scope in (conf['scope'],conf['reference_scope']) for k in ('from','to')) and bi_scope.DATES.get(before['dataset'])!=bi_scope.DATES.get(candidate['dataset']):
            return '日期角色变化：'+bi_scope.contract(before['dataset'])['date_label']+' → '+contract['date_label']+'；同一日期值不能直接沿用，须重新核对'
        return '条件字段可应用，更新后仍须重新核对绑定'
    except (ValidationError,ValueError,KeyError,TypeError,ArithmeticError) as error:
        return bi_card_summary.message(error)


def dependencies(user,model,candidate):
    topics=[]
    visible_topics=list(ws.visible(user,Topic.objects.all()))
    visible_ids={t.pk for t in visible_topics}
    for topic in visible_topics:
        slots=[i for i,c in enumerate(topic.layout) if c.get('model_id')==model.pk]
        if slots:topics.append(dict(id=topic.pk,name=topic.name,version=topic.version,slots=slots))
    views=[]
    for view in TopicView.objects.filter(owner=user,topic_id__in=visible_ids):
        if contains(view.binding,model.pk) or any(t['id']==view.topic_id for t in topics):
            views.append(dict(id=view.pk,topic_id=view.topic_id,name=view.name,version=view.version,archived=view.archived,
                              binding=ws.digest(view.binding),config_hash=ws.digest(view.config),scope_check=scope_check(user,model_info(model),candidate,view.config)))
    cards=[]
    for card in AnalysisModelCard.objects.filter(owner=user).prefetch_related('versions'):
        version=next((v for v in card.versions.all() if v.revision==card.revision),None)
        if version and version.payload.get('binding',{}).get('source_model',{}).get('id')==model.pk:
            cards.append(dict(id=str(card.pk),code=card.code,revision=card.revision,archived=card.archived,payload_hash=version.payload_hash))
    pages=[]
    for page in TopicPage.objects.filter(owner=user,topic_id__in=visible_ids).prefetch_related('versions'):
        version=next((v for v in page.versions.all() if v.number==page.current_version),None)
        if not version:continue
        binding=version.payload.get('binding',{})
        direct=contains(binding.get('topic',{}),model.pk)
        navigation=any(contains(n.get('binding',{}),model.pk) for n in binding.get('navigation',[]))
        if direct or navigation:pages.append(dict(id=str(page.pk),code=page.code,version=page.current_version,revision=page.revision,archived=page.archived,
                                                relation='本页与导航' if direct and navigation else '本页' if direct else '导航目标',payload_hash=version.payload_hash))
    snapshots=[]
    for snapshot in TopicSnapshot.objects.filter(owner=user,topic_id__in=visible_ids):
        if contains(snapshot.payload.get('binding',{}),model.pk):
            snapshots.append(dict(id=str(snapshot.pk),name=snapshot.name,topic_id=snapshot.topic_id,payload_hash=snapshot.payload_hash))
    return dict(topics=topics,views=views,cards=cards,pages=pages,snapshots=snapshots,
                notice='只列当前可访问专题及本人保存的视角、口径卡、页面和快照，不列其他人的私有资料或数量。模型改版后已有绑定需重核；历史定义和结果快照保留，访问仍取决于当前权限。未覆盖其他系统、导出文件或手工引用。')


def differences(before,after):
    rows=[]
    for field in ('name','dataset','is_public'):
        if before[field]!=after[field]:rows.append(dict(path=field,before=before[field],after=after[field],before_present=True,after_present=True))
    for key in sorted(set(before['definition'])|set(after['definition'])):
        a,b=before['definition'],after['definition']
        if a.get(key)!=b.get(key) or (key in a)!=(key in b):rows.append(dict(path='definition.'+key,before=a.get(key),after=b.get(key),before_present=key in a,after_present=key in b))
    return rows


def evaluate(user,model,scope,links):
    try:
        effective,_=topic_linkage.effective(user,model,links)
        result=engine.run_analysis(user,effective['dataset'],effective['definition'],scope=scope)
        rows,_,_=engine.selected_rows(user,effective['dataset'],effective['definition'],scope)
        summary=bi_card_summary.build(user,effective,result,scope)
        return dict(ready=True,summary=summary,groups=result['groups'],returned_groups=len(result['rows']),truncated=result['truncated'],
                    dimension_label=result['dimension_label'],display_label=result['display_label'],display_metric=result['display_metric'],
                    sample_groups=result['rows'][:15],sample_note='最多展示前15个分组供预演核对；整范围摘要使用全部已筛选来源。',
                    grain=result['grain'],date_label=result['scope']['date_label']),rows
    except (ValidationError,ValueError,KeyError,TypeError,ArithmeticError) as error:
        return dict(ready=False,error=bi_card_summary.message(error)),None


def population(before,after,left,right):
    if left is None or right is None:return dict(comparable=False,reason='至少一侧试算暂停，未计算对象差异')
    if before['dataset']!=after['dataset']:return dict(comparable=False,reason='新旧数据集的对象身份不同，不按相同文本编号强行配对')
    a,b={str(r['id']) for r in left},{str(r['id']) for r in right}
    if len(a)!=len(left) or len(b)!=len(right):return dict(comparable=False,reason='对象身份存在重复，差异集合暂停')
    return dict(comparable=True,before=len(a),after=len(b),shared=len(a&b),added=len(b-a),removed=len(a-b),
                reason='同一数据集内按对象主键比较；新增/移除表示配置改变后的纳入范围，不是业务新增或流失。')


def prepare(user,key,data):
    model=owned(user,key);conf=normalize(user,model,data);before=model_info(model)
    after={**before,**conf['candidate'],'version':model.version+1}
    changes=differences(before,after)
    if not changes:raise ValidationError('候选定义与当前模型相同，无需增加版本')
    left,left_rows=evaluate(user,before,conf['scope'],conf['links']);right,right_rows=evaluate(user,after,conf['scope'],conf['links'])
    impact=dependencies(user,model,after)
    result=clean(dict(before=before,candidate=after,scope=conf['scope'],links=conf['links'],changes=changes,
                      original_result=left,candidate_result=right,population=population(before,after,left_rows,right_rows),impact=impact,
                      as_of=analytics.AS_OF,notice=NOTICE,delta_note='两侧按各自定义独立试算，只并列数值、单位、分子分母与样本，不把不同模型结果相减为经营改善。'))
    stamp=ws.digest(dict(account=spc_data.account(user),rules=rules(),facts_revision=analytics.revision(),result=result,
                         populations=[ws.digest(sorted(rows,key=lambda r:str(r['id']))) if rows is not None else None for rows in (left_rows,right_rows)]))
    return result,stamp,conf,model,(left_rows,right_rows)


def checked_receipt(token,stamp):
    if not isinstance(token,str) or not 1<=len(token)<=1000:raise ValidationError('请先预演候选版本')
    try:value=signing.loads(token,salt='motor.model-change.v1',max_age=AGE)
    except signing.BadSignature:raise ReviewConflict('预演凭据无效或已过期，请重新试算')
    if value!=dict(stamp=stamp):raise ReviewConflict('定义、来源、依赖或账号权限变化，请重新预演')


@transaction.atomic
def preview(user,key,data):
    result,stamp,_,_,_=prepare(fresh(user),key,data)
    return dict(**result,receipt=signing.dumps(dict(stamp=stamp),salt='motor.model-change.v1'),receipt_seconds=AGE)


@transaction.atomic
def evidence(user,key,data):
    exact(data,BASE_KEYS|{'receipt','side','subset','page'})
    if data['side'] not in ('before','candidate') or data['subset'] not in ('all','shared','added','removed'):raise ValidationError('试算来源范围无效')
    if type(data['page']) is not int or not 1<=data['page']<=1000000:raise ValidationError('来源页码无效')
    user=fresh(user);result,stamp,_,_,populations=prepare(user,key,{k:data[k] for k in BASE_KEYS});checked_receipt(data['receipt'],stamp)
    side=0 if data['side']=='before' else 1;rows=populations[side]
    if rows is None:raise ValidationError('该侧试算暂停，没有可核对的来源范围')
    subset=data['subset']
    if subset!='all':
        if not result['population']['comparable']:raise ValidationError(result['population']['reason'])
        if (subset=='added' and side==0) or (subset=='removed' and side==1):raise ValidationError('新增只能查候选侧，移除只能查原侧')
        other={str(r['id']) for r in populations[1-side]}
        rows=[r for r in rows if (str(r['id']) in other)==(subset=='shared')]
    ds=result['before' if side==0 else 'candidate']['dataset'];total=len(rows);pages=max(1,math.ceil(total/25))
    if data['page']>pages:raise ValidationError('来源页码超出范围')
    selected=sorted(rows,key=lambda r:str(r['id']))[(data['page']-1)*25:data['page']*25]
    sources={r.business_key:spc_data.source(r) for r in Record.objects.filter(dataset=ds,business_key__in=[r['id'] for r in selected]).select_related('source_row__batch')}
    return dict(dataset=ds,fields=access.permitted_fields(user,ds),side=data['side'],subset=subset,total=total,page=data['page'],pages=pages,
                rows=[dict(values=access.sanitize(user,ds,row),source=sources.get(str(row['id'])),references=[ref for ref in row.get('_sources',[]) if access.allowed(user,ref['dataset'])]) for row in selected])


def readable_change(user,change):
    if ws.digest(change.payload)!=change.payload_hash:raise ReviewConflict('变更历史摘要待核对')
    for side in ('before','after'):
        value=change.payload[side];engine.validate_definition(user,value['dataset'],value['definition'],allow_inactive=True)


@transaction.atomic
def commit(user,key,data):
    exact(data,BASE_KEYS|{'receipt','reason','request_id','acknowledged'})
    user=fresh(user);model=owned(user,key,True)
    if data['acknowledged'] is not True:raise ValidationError('请明确已核对候选定义、试算和影响范围')
    if not isinstance(data['reason'],str) or not 5<=len(data['reason'].strip())<=1000:raise ValidationError('请填写5—1000字变更依据')
    request_id=uuid.UUID(str(data['request_id']));request_hash=ws.digest(data)
    old=AnalysisModelChange.objects.filter(pk=request_id).first()
    if old:
        if old.actor_id!=user.pk or old.model_id!=key or old.request_hash!=request_hash:raise ReviewConflict('申请号已用于其他模型或内容')
        readable_change(user,old)
        return dict(model=model_info(model),applied_version=old.to_version,change_id=str(old.pk),repeated=True)
    result,stamp,conf,_,_=prepare(user,key,{k:data[k] for k in BASE_KEYS});checked_receipt(data['receipt'],stamp)
    before=model_info(model)
    for field,value in conf['candidate'].items():setattr(model,field,value)
    model.version+=1;model.save();after=model_info(model)
    payload=clean(dict(before=before,after=after,scope=conf['scope'],links=conf['links'],reason=data['reason'].strip(),
                       preview_hash=stamp,impact_hash=ws.digest(result['impact']),rules_hash=rules(),business_results_saved=False))
    change=AnalysisModelChange.objects.create(request_id=request_id,actor=user,model=model,from_version=before['version'],to_version=model.version,
                                              request_hash=request_hash,payload=payload,payload_hash=ws.digest(payload))
    AuditEvent.objects.create(action='model.change',actor=user.username,object_type='AnalysisModel',object_id=str(model.pk),
                              detail=dict(change_id=str(change.pk),from_version=before['version'],to_version=model.version,payload_hash=change.payload_hash,business_facts_changed=False))
    return dict(model=after,applied_version=model.version,change_id=str(change.pk),repeated=False)


@transaction.atomic
def history(user,key,page=1):
    user=fresh(user);model=owned(user,key)
    if type(page) is not int or page<1:raise ValidationError('历史页码无效')
    query=AnalysisModelChange.objects.filter(model=model).select_related('actor').order_by('to_version')
    total=query.count();pages=max(1,math.ceil(total/25))
    if page>pages:raise ValidationError('历史页码超出范围')
    rows=[]
    for change in query[(page-1)*25:page*25]:
        try:
            readable_change(user,change)
            row=dict(id=str(change.pk),from_version=change.from_version,to_version=change.to_version,actor=change.actor.username,
                     created_at=change.created_at,payload=change.payload,changes=differences(change.payload['before'],change.payload['after']))
        except (ValidationError,PermissionDenied):row=dict(from_version=change.from_version,to_version=change.to_version,restricted=True)
        rows.append(row)
    first=query.first()
    return dict(model=model_info(model),rows=rows,total=total,page=page,pages=pages,first_recorded_version=first.from_version if first else model.version,
                notice='仅保存启用预演流程后的变更；此前版本不补造。记录保留新旧定义、核对范围及依据摘要，不保存历史试算数字，也不自动恢复旧版。')
