"""Immutable personal classification recipes, independent of imported business facts."""
import hashlib,json,re,uuid
from copy import deepcopy
from decimal import Decimal,InvalidOperation
from functools import lru_cache
from collections import Counter
from django.core.exceptions import ValidationError,PermissionDenied
from django.db import transaction
from django.utils import timezone
from . import access,analytics
from .models import BusinessGrouping,BusinessGroupingVersion,AnalysisModel,AuditEvent
from .import_review import ReviewConflict

NOTICE='个人分析分组，尚未经业务认证。规则版本不可覆盖；模型固定引用选定版本，新版本不自动替换旧模型。未匹配、缺失和类型异常分别保留；不修改Excel业务记录。'
FALLBACKS=['未归类','未填写','值类型异常']

def digest(payload):return hashlib.sha256(json.dumps(payload,ensure_ascii=False,sort_keys=True).encode()).hexdigest()
def text(value,label,maximum=80):
    if not isinstance(value,str) or not 1<=len(value.strip())<=maximum:raise ValidationError(label+'长度或格式无效')
    return value.strip()
def number(value):
    if type(value) not in [int,float,str] or len(str(value))>40:raise ValidationError('边界须为有限数值')
    try:n=Decimal(str(value))
    except InvalidOperation:raise ValidationError('边界须为有限数值')
    if not n.is_finite() or abs(n)>Decimal('1e15'):raise ValidationError('边界须为绝对值不超过10^15的有限数值')
    return n

def validate(user,payload):
    if not isinstance(payload,dict) or set(payload)!={'name','dataset','field','mode','rules','note'}:raise ValidationError('分组定义字段不完整或包含未知字段')
    p=deepcopy(payload);p['name']=text(p['name'],'分组名称');p['note']=text(p['note'],'用途和依据',1000)
    if not isinstance(p['dataset'],str) or not access.allowed(user,p['dataset']):raise ValidationError('分组数据集不可访问')
    field=next((f for f in access.permitted_fields(user,p['dataset']) if f['name']==p['field']),None)
    if not field or field['type'] not in ['str','int','float']:raise ValidationError('请选择可访问的文本或数值字段')
    if p['mode'] not in ['enum','range']:raise ValidationError('分组模式无效')
    if (p['mode']=='enum' and field['type']!='str') or (p['mode']=='range' and field['type'] not in ['int','float']):raise ValidationError('枚举适用于文本字段，区间适用于数值字段')
    if field.get('unit_field') and p['mode']=='range':raise ValidationError('此字段随行变化计量单位，暂不允许直接分段；请先建立单位一致的数据模型')
    if not isinstance(p['rules'],list) or not 1<=len(p['rules'])<=30:raise ValidationError('每个版本需1至30组规则')
    labels=set(FALLBACKS);seen=set();intervals=[];value_count=0
    for rule in p['rules']:
        expected={'label','values'} if p['mode']=='enum' else {'label','lower','upper'}
        if not isinstance(rule,dict) or set(rule)!=expected:raise ValidationError('规则字段不完整或包含未知字段')
        rule['label']=text(rule['label'],'分组标签',60)
        if rule['label'] in labels:raise ValidationError('分组标签重复或使用了保留标签')
        labels.add(rule['label'])
        if p['mode']=='enum':
            if not isinstance(rule['values'],list) or not rule['values']:raise ValidationError('每个枚举分组至少填写一个原始值')
            for value in rule['values']:
                if not isinstance(value,str) or not value.strip() or len(value)>255:raise ValidationError('枚举值必须是非空文本且不超过255字')
                if value in seen:raise ValidationError('同一原始值不能重复或归入多个组')
                seen.add(value);value_count+=1
            if value_count>500:raise ValidationError('每个版本最多500个枚举值')
        else:
            lower=None if rule['lower'] is None else number(rule['lower']);upper=None if rule['upper'] is None else number(rule['upper'])
            if lower is not None and upper is not None and lower>=upper:raise ValidationError('下界必须小于上界')
            for a,b in intervals:
                if (upper is None or a is None or a<upper) and (b is None or lower is None or lower<b):raise ValidationError('区间重叠；统一使用含下界、不含上界')
            intervals.append((lower,upper));rule['lower']=str(lower) if lower is not None else None;rule['upper']=str(upper) if upper is not None else None
    return p

def classify(value,payload):
    if value is None or value=='':return '未填写'
    if payload['mode']=='enum':
        if not isinstance(value,str):return '值类型异常'
        return next((r['label'] for r in payload['rules'] if value in r['values']),'未归类')
    if type(value) not in [int,float,Decimal]:return '值类型异常'
    try:n=number(str(value))
    except ValidationError:return '值类型异常'
    return next((r['label'] for r in payload['rules'] if (r['lower'] is None or n>=Decimal(r['lower'])) and (r['upper'] is None or n<Decimal(r['upper']))),'未归类')

def checked(v):
    if v.payload_hash!=digest(v.payload):raise ReviewConflict('分组版本摘要不符，已暂停使用；请核对备份')
    return v
def ref(v):return {'id':str(v.grouping_id),'version':v.version,'hash':v.payload_hash}
def resolve(user,dataset,definition):
    r=definition.get('grouping_ref')
    if r is None:return None
    if not isinstance(r,dict) or set(r)!={'id','version','hash'} or type(r['version']) is not int or r['version']<1 or not isinstance(r['hash'],str):raise ValidationError('分组引用须指定ID、版本及摘要')
    try:gid=uuid.UUID(str(r['id']));v=BusinessGroupingVersion.objects.select_related('grouping').get(grouping_id=gid,version=r['version'])
    except (ValueError,TypeError,BusinessGroupingVersion.DoesNotExist):raise ValidationError('所选分组版本不存在')
    if v.grouping.owner!=user.username:raise ValidationError('只能引用自己的个人分组')
    checked(v);p=validate(user,v.payload)
    if r['hash']!=v.payload_hash:raise ValidationError('分组引用摘要不一致')
    if p['dataset']!=dataset or p['field']!=definition.get('dimension') or definition.get('grain','value')!='value':raise ValidationError('分组数据集、字段或日期归组与版本不一致')
    return {'code':v.grouping.code,'version':v.version,'name':p['name'],'payload':p,'hash':v.payload_hash,'notice':NOTICE}

@lru_cache(maxsize=512)
def cached_recipe(gid,version,sha):
    v=checked(BusinessGroupingVersion.objects.get(grouping_id=gid,version=version))
    if v.payload_hash!=sha:raise ValidationError('分组版本摘要不符')
    return v.payload
def recipe(definition):
    r=definition.get('grouping_ref');return cached_recipe(r['id'],r['version'],r['hash']) if r else None
def group(value,definition):return classify(value,recipe(definition))
def order(keys,definition):
    p=recipe(definition)
    if not p:return sorted(keys)
    labels=[r['label'] for r in p['rules']]+FALLBACKS
    return sorted(keys,key=lambda k:labels.index(k))

def version_info(v):
    checked(v);return {'ref':ref(v),'payload':v.payload,'created_by':v.created_by,'created_at':v.created_at}
def info(g):
    versions=list(g.versions.order_by('-version'))
    return {'id':str(g.pk),'code':g.code,'revision':g.revision,'archived':g.archived,'versions':[version_info(v) for v in versions],'updated_at':g.updated_at}
def impact(g):
    return [{'id':m.pk,'name':m.name,'version':m.version,'grouping_version':m.definition['grouping_ref']['version']} for m in AnalysisModel.objects.filter(owner=g.owner) if m.definition.get('grouping_ref',{}).get('id')==str(g.pk)]

@transaction.atomic
def save(user,data,gid=None):
    if not access.can_edit(user):raise PermissionDenied('此身份不能维护业务分组')
    if set(data)!=({'payload','code'} if gid is None else {'payload','revision'}):raise ValidationError('保存字段不完整或含未知字段')
    p=validate(user,data['payload'])
    if gid:
        g=BusinessGrouping.objects.select_for_update().get(pk=gid,owner=user.username)
        if type(data['revision']) is not int or g.revision!=data['revision']:raise ReviewConflict('分组已更新，请重新打开')
        if g.archived:raise ValidationError('请先恢复已归档的分组')
        last=g.versions.order_by('-version').first();checked(last)
        if (p['dataset'],p['field'],p['mode'])!=(last.payload['dataset'],last.payload['field'],last.payload['mode']):raise ValidationError('同一分组的来源和模式固定；请选择新建分组')
        if p==last.payload:raise ValidationError('规则没有变化，无需新增版本')
        expected=g.revision
        if BusinessGrouping.objects.filter(pk=gid,revision=expected).update(revision=expected+1,updated_at=timezone.now())!=1:raise ReviewConflict('分组并发更新，请重新打开')
        g.refresh_from_db();version=last.version+1
    else:
        code=text(data['code'],'分组编码',64)
        if not re.fullmatch(r'[A-Z][A-Z0-9_.-]{2,63}',code):raise ValidationError('编码需3至64位大写字母、数字、点、横线或下划线')
        if BusinessGrouping.objects.filter(owner=user.username,code=code).exists():raise ValidationError('此个人分组编码已存在')
        if BusinessGrouping.objects.filter(owner=user.username).count()>=100:raise ValidationError('每人最多保留100个分组')
        g=BusinessGrouping.objects.create(owner=user.username,code=code);version=1
    v=BusinessGroupingVersion.objects.create(grouping=g,version=version,payload=p,payload_hash=digest(p),created_by=user.username)
    AuditEvent.objects.create(action='grouping.version',actor=user.username,object_type='BusinessGrouping',object_id=str(g.pk),detail={'version':v.version,'payload':p,'payload_hash':v.payload_hash,'business_facts_changed':False})
    return info(g)

@transaction.atomic
def archive(user,gid,data):
    if not access.can_edit(user):raise PermissionDenied('此身份不能维护业务分组')
    if set(data)!={'revision','archived'} or type(data['revision']) is not int or type(data['archived']) is not bool:raise ValidationError('归档参数无效')
    g=BusinessGrouping.objects.select_for_update().get(pk=gid,owner=user.username)
    if g.revision!=data['revision']:raise ReviewConflict('分组已更新，请重新读取')
    if g.archived==data['archived']:return info(g)
    if BusinessGrouping.objects.filter(pk=gid,revision=g.revision).update(archived=data['archived'],revision=g.revision+1,updated_at=timezone.now())!=1:raise ReviewConflict('分组并发更新')
    g.refresh_from_db();AuditEvent.objects.create(action='grouping.archive',actor=user.username,object_type='BusinessGrouping',object_id=str(g.pk),detail={'archived':g.archived,'revision':g.revision})
    return info(g)

def preview(user,payload):
    from .analysis_engine import selected_rows
    p=validate(user,payload)
    rows,scanned,scope=selected_rows(user,p['dataset'],{'dimension':p['field'],'metrics':[{'agg':'count'}],'chart':'table'})
    counts=Counter();samples={};values=Counter()
    for row in rows:
        value=row.get(p['field']);label=classify(value,p);counts[label]+=1
        if len(samples.setdefault(label,[]))<5:samples[label].append({'id':str(row['id']),'value':value})
        values[json.dumps(value,ensure_ascii=False)]+=1
    return {'payload':p,'total':len(rows),'data_revision':list(analytics.revision()),'rows':[{'label':label,'count':counts[label],'samples':samples.get(label,[])} for label in [r['label'] for r in p['rules']]+FALLBACKS],
        'values':[{'value':json.loads(k),'count':n} for k,n in values.most_common(100)],'distinct_values':len(values),'notice':NOTICE}
