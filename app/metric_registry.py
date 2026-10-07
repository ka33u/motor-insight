"""Versioned metric contracts. Calculation uses the existing declarative engine.

Publication freezes a definition, not business facts. References always pin a
specific version; retirement or calculation-code drift pauses computation.
"""
import hashlib,json,re
from copy import deepcopy
from pathlib import Path
from django.core.exceptions import ValidationError,PermissionDenied
from django.db import transaction
from django.db.models import Max
from django.utils import timezone
from . import access,analytics,bi_scope
from .models import GovernedMetric,MetricVersion,AuditEvent,AnalysisModel,Topic
from .semantic_schema import schemas
from .import_review import ReviewConflict

STATUSES={'draft':'草稿','review':'待审核','published':'已发布','retired':'已停用'}
REVIEW_ROLES={'operations':'生产计划','quality':'质量','finance':'财务'}
TEXT_FIELDS={'name':150,'business_definition':1200,'purpose':1000,'business_owner':150,'clock':1000,'unit':40,'exclusions':1000,'comparison':1000,'change_reason':1000}
NOTICE='发布冻结指标定义和计算规则，不冻结业务数据。每次分析读取当前已导入事实；历史数值需另存快照。这里只在模拟环境演练发布，不能代替工厂业务负责人验收。'
NULL_RULE='计数按来源行；其他聚合忽略字段空值。比率仅使用分子与分母均非空的行，先合计再相除×100；零分母或无有效样本显示空值。'

def calculation_hash(dataset):
    schema=schemas().get(dataset)
    if not schema:raise ValidationError('指标数据集不存在')
    h=hashlib.sha256(json.dumps(schema,sort_keys=True,ensure_ascii=False).encode())
    # Conservative invalidation: shared calculation changes require re-review.
    for name in ['analysis_engine.py','analysis_quantiles.py','analysis_drill.py','analysis_pivot.py','analysis_scatter.py','derived_metrics.py','business_groups.py','semantic.py','analytics.py','production.py','bi_scope.py','metric_registry.py']:
        h.update((Path(__file__).parent/name).read_bytes())
    return h.hexdigest()

def raw_definition(payload):
    return {'dimension':'','grain':'value','metrics':[deepcopy(payload['measure'])],'filters':deepcopy(payload['filters']),'chart':'table','sort':'dimension'}

def validate_payload(user,dataset,payload):
    from .analysis_engine import validate_raw_definition
    if not isinstance(payload,dict) or set(payload)!=set(TEXT_FIELDS)|{'measure','filters','review_role'}:raise ValidationError('指标定义字段不完整或包含不支持字段')
    for key,limit in TEXT_FIELDS.items():
        if not isinstance(payload[key],str) or not 1<=len(payload[key].strip())<=limit:raise ValidationError('请完整填写指标定义、责任、时间、单位和边界说明')
    if payload['review_role'] not in REVIEW_ROLES:raise ValidationError('请选择业务审核岗位')
    m=payload['measure']
    if not isinstance(m,dict) or set(m)-{'agg','field','denominator','percentile'}:raise ValidationError('指标只支持受控聚合，不允许代码、SQL或嵌套指标')
    if m.get('agg')=='ratio' and payload['unit']!='%':raise ValidationError('当前比率结果按百分数返回，单位须为%')
    if not isinstance(payload['filters'],list) or len(payload['filters'])>5:raise ValidationError('指标固定范围最多5条条件')
    for f in payload['filters']:
        if not isinstance(f,dict) or set(f)!={'field','op','value'} or isinstance(f.get('value'),(dict,list)):raise ValidationError('固定条件只支持字段、运算符和单个值')
    validate_raw_definition(user,dataset,raw_definition(payload))
    return deepcopy(payload)

def can_edit(user,v):return access.can_edit(user) and (access.role(user)=='admin' or v.metric.owner==user.username)
def can_review(user,v):return access.role(user) in ['admin',v.payload['review_role']] and user.username not in v.contributors and user.username!=v.submitted_by
def can_read(user,v):
    try:validate_payload(user,v.metric.dataset,v.payload)
    except (ValidationError,KeyError,TypeError):return False
    return v.status in ['published','retired'] or access.can_edit(user) or access.role(user)==v.payload['review_role']

def receipt(v):
    return {'key':v.metric.key,'version':v.version,'name':v.payload['name'],'status':v.status,'unit':v.payload['unit'],'business_owner':v.payload['business_owner'],'clock':v.payload['clock'],'scope_date':bi_scope.contract(v.metric.dataset)['date_label'],'published_at':v.published_at,'reviewed_by':v.reviewed_by,'calculation_hash':v.calculation_hash,'notice':NOTICE}

def resolve(user,dataset,definition,allow_inactive=False):
    ref=definition.get('metric_ref')
    if ref is None:return deepcopy(definition),None
    if not isinstance(ref,dict) or set(ref)!={'key','version'} or not isinstance(ref['key'],str) or type(ref['version']) is not int or ref['version']<1:raise ValidationError('指标引用必须指定编码和正整数版本')
    if definition.get('metrics'):raise ValidationError('引用发布指标时不能同时覆盖其计算字段')
    if definition.get('derived'):raise ValidationError('发布指标引用不支持追加未审核派生公式，请另建临时分析模型')
    try:v=MetricVersion.objects.select_related('metric').get(metric__key=ref['key'],version=ref['version'])
    except MetricVersion.DoesNotExist:raise ValidationError('引用的指标版本不存在')
    if v.metric.dataset!=dataset:raise ValidationError('指标与分析数据集不一致')
    validate_payload(user,dataset,v.payload)
    if v.status not in ['published','retired']:raise ValidationError('草稿或待审核指标不能用于正式分析')
    if not allow_inactive:
        if v.status=='retired':raise ValidationError(f'指标 {v.metric.key} v{v.version} 已停用，分析暂停；请明确选择其他已发布版本')
        if v.calculation_hash!=calculation_hash(dataset):raise ValidationError('指标底层计算规则已变化，请建立新版本并复核后使用；未自动替换原口径')
    normalized=deepcopy(definition);normalized.pop('metric_ref');normalized['metrics']=[{**v.payload['measure'],'label':v.payload['name']+' ('+v.payload['unit']+')'}]
    extra=normalized.get('filters',[])
    if not isinstance(extra,list) or len(extra)>5:raise ValidationError('引用指标后最多追加5条分析范围条件')
    normalized['filters']=deepcopy(v.payload['filters'])+extra
    return normalized,receipt(v)

def snapshot(v):
    return {'id':v.pk,'key':v.metric.key,'dataset':v.metric.dataset,'owner':v.metric.owner,'version':v.version,'revision':v.revision,'status':v.status,'payload':v.payload,'calculation_hash':v.calculation_hash,'contributors':v.contributors,'submitted_by':v.submitted_by,'reviewed_by':v.reviewed_by,'review_note':v.review_note,'evidence':v.evidence,'published_at':v.published_at,'retired_at':v.retired_at,'updated_at':v.updated_at}

def audit(user,action,v,before):
    serial=lambda x:json.loads(json.dumps(x,ensure_ascii=False,default=str))
    AuditEvent.objects.create(action='metric.'+action,actor=user.username,object_type='MetricVersion',object_id=str(v.pk),detail={'before':serial(before),'after':serial(snapshot(v))})

def impact(user,v):
    models=[]
    for m in AnalysisModel.objects.filter(dataset=v.metric.dataset):
        if m.definition.get('metric_ref')=={'key':v.metric.key,'version':v.version}:
            # Report counts globally, identities only within existing visibility.
            models.append(m)
    visible=[m for m in models if access.role(user)=='admin' or m.owner==user.username or m.is_public]
    ids={m.pk for m in models};topics=[t for t in Topic.objects.all() if any(c.get('model_id') in ids for c in t.layout)]
    return {'model_count':len(models),'models':[{'id':m.pk,'name':m.name} for m in visible],'topic_count':len(topics),'topics':[{'id':t.pk,'name':t.name} for t in topics if access.role(user)=='admin' or t.owner==user.username or t.is_public]}

def info(user,v,details=False):
    d=snapshot(v);d.update(status_label=STATUSES[v.status],can_edit=can_edit(user,v),can_review=can_review(user,v),can_retire=access.role(user) in ['admin',v.payload['review_role']],rules_current=v.calculation_hash==calculation_hash(v.metric.dataset),null_rule=NULL_RULE,notice=NOTICE,grain=schemas()[v.metric.dataset].get('grain','一行一条来源记录'))
    d['scope_date']=bi_scope.contract(v.metric.dataset)['date_label']
    if details:d['impact']=impact(user,v)
    else:d.pop('evidence')
    return d

def visible_history(user,events):
    result=[]
    for event in events:
        event=deepcopy(event)
        for side in ['before','after']:
            previous=event['detail'].get(side)
            if not previous:continue
            try:validate_payload(user,previous['dataset'],previous['payload'])
            except (ValidationError,KeyError,TypeError):event['detail'][side]={'restricted':True,'note':'此历史定义涉及当前身份无权访问的字段或数据集'}
        result.append(event)
    return result

def evaluate(user,v):
    from .analysis_engine import run_analysis
    validate_payload(user,v.metric.dataset,v.payload)
    r=run_analysis(user,v.metric.dataset,raw_definition(v.payload))
    return {**({'quantile_notice':r['quantile_notice']} if r.get('quantile_notice') else {}),'as_of':r['as_of'],'record_revision':list(analytics.revision()),'matched':r['matched'],'rows':r['rows'],'components':r['components'],'labels':r['labels'],'grain':r['grain'],'note':r['note'],'calculation_hash':calculation_hash(v.metric.dataset),'simulated':True}

@transaction.atomic
def create(user,data):
    if not access.can_edit(user):raise PermissionDenied('当前身份不能编写指标')
    if set(data)!={'key','dataset','payload'} or not isinstance(data['key'],str) or not re.fullmatch(r'[A-Z][A-Z0-9_]{2,63}',data['key']):raise ValidationError('指标编码需3—64位大写字母、数字或下划线，以字母开头')
    payload=validate_payload(user,data['dataset'],data['payload'])
    metric=GovernedMetric.objects.create(key=data['key'],dataset=data['dataset'],owner=user.username)
    v=MetricVersion.objects.create(metric=metric,version=1,payload=payload,calculation_hash=calculation_hash(metric.dataset),contributors=[user.username]);audit(user,'create',v,None);return v

@transaction.atomic
def transition(user,version_id,data):
    v=MetricVersion.objects.select_for_update().select_related('metric').get(pk=version_id)
    if not can_read(user,v):raise PermissionDenied('没有该指标定义的访问权限')
    if set(data)-{'action','revision','payload','reason'}:raise ValidationError('包含不支持的操作字段')
    if type(data.get('revision')) is not int or data['revision']!=v.revision:raise ReviewConflict('指标版本已被更新，请重新读取后操作')
    action=data.get('action');before=snapshot(v)
    if action=='fork':
        if not can_edit(user,v):raise PermissionDenied('只有编写人或管理员可以建立新版本')
        if v.status not in ['published','retired']:raise ValidationError('请先完成当前草稿的审核')
        GovernedMetric.objects.select_for_update().get(pk=v.metric_id)
        if v.metric.versions.filter(status__in=['draft','review']).exists():raise ReviewConflict('该指标已有草稿或待审核版本，请继续处理现有版本')
        payload=deepcopy(v.payload);payload['change_reason']='从v'+str(v.version)+'建立新版本；请补充变更依据。'
        new=MetricVersion.objects.create(metric=v.metric,version=v.metric.versions.aggregate(n=Max('version'))['n']+1,payload=payload,calculation_hash=calculation_hash(v.metric.dataset),contributors=[user.username]);audit(user,'fork',new,before);return new
    if action in ['save','submit','withdraw']:
        if not can_edit(user,v):raise PermissionDenied('只有编写人或管理员可以维护指标草稿')
        if action=='save':
            if v.status!='draft':raise ValidationError('只有草稿可以修改；发布版本须另建新版本')
            v.payload=validate_payload(user,v.metric.dataset,data.get('payload'));v.calculation_hash=calculation_hash(v.metric.dataset)
            v.contributors=sorted(set(v.contributors+[user.username]));v.evidence={}
        elif action=='submit':
            if v.status!='draft':raise ValidationError('只有草稿可以提交')
            if v.calculation_hash!=calculation_hash(v.metric.dataset):raise ValidationError('底层规则变化，请先保存并重新核对草稿')
            v.evidence=evaluate(user,v)
            if not v.evidence['matched']:raise ValidationError('当前没有符合固定范围的模拟样例，请补齐数据或修正条件后提交')
            v.status='review';v.submitted_by=user.username;v.reviewed_by='';v.review_note=''
        else:
            if v.status!='review':raise ValidationError('只有待审核版本可以撤回')
            v.status='draft'
    elif action in ['publish','reject','retire']:
        reason=data.get('reason','')
        if not isinstance(reason,str) or not 5<=len(reason.strip())<=1500:raise ValidationError('请填写5至1500字的审核或停用依据')
        if action=='retire':
            if access.role(user) not in ['admin',v.payload['review_role']]:raise PermissionDenied('需要指定业务审核岗位或管理员停用')
            if v.status!='published':raise ValidationError('只有已发布版本可以停用')
            v.status='retired';v.retired_at=timezone.now()
        else:
            if not can_review(user,v):raise PermissionDenied('审核需由指定业务岗位或管理员执行，且不能与编写/提交人为同一账号')
            if v.status!='review':raise ValidationError('只有待审核版本可以审核')
            if action=='publish':
                if v.calculation_hash!=calculation_hash(v.metric.dataset):raise ValidationError('计算规则已变更，请退回修改后重新提交')
                if v.evidence.get('record_revision')!=list(analytics.revision()):raise ReviewConflict('数据在提交后发生变化，请退回并重新计算审核样例')
                validate_payload(user,v.metric.dataset,v.payload);v.status='published';v.published_at=timezone.now()
            else:v.status='draft'
        v.reviewed_by=user.username;v.review_note=reason.strip()
    else:raise ValidationError('未知指标操作')
    v.revision+=1;v.save();audit(user,action,v,before);return v
