"""Named, immutable mapping versions; use and lifecycle require fresh evidence."""
import copy,hashlib,re
from pathlib import Path
from django.core import signing
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Max
from django.utils import timezone
from . import access,import_mapping as m
from .schema import SCHEMAS
from .models import ImportTemplate,ImportTemplateVersion,ImportTemplateUse,AuditEvent

SALT='motor.import.template.v1'
NOTICE='模板启用仅允许使用所列映射；不证明记录、单位、业务批准或真实接口正确。样例检查仍不能替代完整行级校验。'


def text(value,label,limit):
    if not isinstance(value,str) or not value.strip() or len(value.strip())>limit:raise ValueError(label+'不能为空或过长')
    return value.strip()


def authorized(user):
    if not access.can_import(user):raise PermissionDenied('仅导入管理员可以使用模板库')


def integrity(v):
    if m.digest(v.payload)!=v.content_hash:raise m.MappingStale('模板版本内容摘要不一致，请核查模板历史')


def owner(user,t):
    if t.owner!=user.username:raise PermissionDenied('只有模板维护人可以新增版本或改变启用状态')


def revision(t,value):
    if type(value) is not int or value!=t.revision:raise m.MappingStale('模板已更新，请刷新版本和核对依据')


def header_contract(result):
    return [{'name':s['name'],'headers':s['headers']} for s in result['sheets'] if not s['metadata_sheet']]


def differences(saved,current):
    old={s['name']:s['headers'] for s in saved};new={s['name']:s['headers'] for s in current};rows=[]
    for name in old:
        if name not in new:rows.append(dict(sheet=name,kind='removed_sheet',blocking=True,detail='缺少原工作表'))
    for name in new:
        if name not in old:rows.append(dict(sheet=name,kind='added_sheet',blocking=True,detail='新增工作表，需明确映射或忽略'))
    for name in old:
        if name not in new:continue
        removed=[x for x in old[name] if x and x not in new[name]]
        added=[x for x in new[name] if x and x not in old[name]]
        if removed:rows.append(dict(sheet=name,kind='removed_columns',blocking=True,detail='缺少或改名：'+'、'.join(removed)))
        if added:rows.append(dict(sheet=name,kind='added_columns',blocking=True,detail='新增或改名：'+'、'.join(added)))
        if not removed and not added and old[name]!=new[name]:rows.append(dict(sheet=name,kind='reordered_columns',blocking=False,detail='列顺序或空白列位置改变；按列名重新定位'))
    if set(old)==set(new) and list(old)!=list(new):rows.append(dict(sheet='工作簿',kind='reordered_sheets',blocking=False,detail='工作表顺序改变；按页名定位'))
    return rows


def info(t,user,detail=False):
    rows=[]
    for v in t.versions.all():
        integrity(v)
        current_rules=v.payload['schema_hash']==m.digest(SCHEMAS) and v.payload['rules_hash']==m.rules_hash()
        row=dict(id=v.pk,number=v.number,state=v.state,content_hash=v.content_hash,reason=v.reason,
            created_by=v.created_by,created_at=v.created_at,activated_by=v.activated_by,activated_at=v.activated_at,
            rules_current=current_rules,can_use=v.state=='active' and t.current_version==v.number and current_rules)
        if detail:row['payload']=v.payload
        rows.append(row)
    return dict(id=str(t.pk),code=t.code,name=t.name,department=t.department,owner=t.owner,revision=t.revision,
        current_version=t.current_version,can_manage=t.owner==user.username,versions=rows,notice=NOTICE)


def audit(user,action,t,detail):
    AuditEvent.objects.create(action='import_template.'+action,actor=user.username,object_type='ImportTemplate',object_id=str(t.pk),
        detail={**detail,'revision':t.revision,'business_facts_changed':False,'business_approval':False})


@transaction.atomic
def save(user,path,filename,mapping,receipt,data):
    authorized(user)
    m.verify_receipt(receipt,path,filename,mapping,user)
    result=m.inspect(path,user,mapping,strict=True,filename=filename)
    if not result['can_stage']:raise ValueError('当前映射尚未通过表头核对')
    reason=text(data.get('reason'),'版本依据',1000)
    payload=dict(mapping=copy.deepcopy(mapping),headers=header_contract(result),schema_hash=result['schema_hash'],rules_hash=result['rules_hash'],
        declared_schemas={s['key']:s for s in result['schemas'] if any(c.get('dataset')==s['key'] for c in mapping.values())},
        example_filename=filename,example_sha256=result['sha256'])
    content_hash=m.digest(payload)
    if data.get('template_id'):
        if set(data)!={'template_id','revision','reason'}:raise ValueError('新增版本参数不完整')
        t=ImportTemplate.objects.select_for_update().get(pk=data['template_id']);owner(user,t);revision(t,data['revision'])
        same=t.versions.filter(content_hash=content_hash).first()
        if same:return dict(template=info(t,user,True),version_id=same.pk,repeated=True)
        number=(t.versions.aggregate(n=Max('number'))['n'] or 0)+1
        t.revision+=1;t.save(update_fields=['revision'])
    else:
        if set(data)!={'code','name','department','reason'}:raise ValueError('新建模板参数不完整')
        code=text(data.get('code'),'模板编码',40)
        if not re.fullmatch(r'[A-Z][A-Z0-9_-]{2,39}',code):raise ValueError('模板编码需3—40位大写字母、数字、下划线或短横线，且以字母开头')
        name=text(data.get('name'),'模板名称',100);department=text(data.get('department'),'来源部门',80)
        existing=ImportTemplate.objects.select_for_update().filter(code=code).first()
        if existing:
            owner(user,existing)
            same=existing.versions.filter(content_hash=content_hash).first()
            if existing.name==name and existing.department==department and same:return dict(template=info(existing,user,True),version_id=same.pk,repeated=True)
            raise m.MappingStale('模板编码已存在；请选择现有模板并创建新版本')
        t=ImportTemplate.objects.create(code=code,name=name,department=department,owner=user.username);number=1
    v=ImportTemplateVersion.objects.create(template=t,number=number,payload=payload,content_hash=content_hash,reason=reason,created_by=user.username)
    audit(user,'draft',t,dict(version_id=v.pk,number=number,content_hash=content_hash,example_sha256=result['sha256']))
    return dict(template=info(t,user,True),version_id=v.pk,repeated=False)


def receipt_payload(v,user,result,purpose):
    return dict(user_id=user.pk,role=access.role(user),template_id=str(v.template_id),template_revision=v.template.revision,
        version_id=v.pk,version_number=v.number,version_state=v.state,content_hash=v.content_hash,purpose=purpose,
        sha256=result['sha256'],filename=result['filename'],schema_hash=result['schema_hash'],rules_hash=result['rules_hash'],mapping_hash=m.digest(v.payload['mapping']))


def preview(user,path,filename,version_id,purpose):
    authorized(user)
    if purpose not in ('use','activate'):raise ValueError('模板核对用途不可用')
    v=ImportTemplateVersion.objects.select_related('template').get(pk=version_id);integrity(v)
    if purpose=='activate':owner(user,v.template)
    try:result=m.inspect(path,user,v.payload['mapping'],strict=True,filename=filename)
    except ValueError:
        # Missing source sheets can invalidate the saved mapping shape. Still
        # read the actual headers, so the user can inspect an explicit drift.
        result=m.inspect(path,user,strict=False,filename=filename);result['can_stage']=False
        result['issues'].append('模板映射与当前工作簿不兼容，请逐字段核对并保存新版本')
    drift=differences(v.payload['headers'],header_contract(result))
    rules_current=v.payload['schema_hash']==result['schema_hash'] and v.payload['rules_hash']==result['rules_hash']
    active=v.state=='active' and v.template.current_version==v.number
    permitted=purpose=='activate' and v.state in ('draft','retired') or purpose=='use' and active
    can_apply=bool(result['can_stage'] and rules_current and permitted and not any(x['blocking'] for x in drift))
    result.update(template=info(v.template,user),template_version_id=v.pk,template_mapping=v.payload['mapping'],
        drift=drift,rules_current=rules_current,template_can_apply=can_apply,template_purpose=purpose,notice=NOTICE)
    if not rules_current:result['issues'].append('模板保存时的字段或校验规则已变化，需重新核对并创建版本')
    if not permitted:result['issues'].append('当前版本尚未启用、已被替代，或不适用于此操作')
    if can_apply:result['template_receipt']=signing.dumps(receipt_payload(v,user,result,purpose),salt=SALT,compress=True)
    else:result.pop('receipt',None)
    return result


def verify(user,receipt,path,filename,mapping,purpose):
    authorized(user)
    try:payload=signing.loads(receipt,salt=SALT,max_age=m.MAX_AGE)
    except (signing.BadSignature,ValueError,TypeError) as ex:raise m.MappingStale('模板核对依据已失效，请重新核对当前文件') from ex
    if not isinstance(payload,dict) or type(payload.get('version_id')) is not int:raise m.MappingStale('模板核对依据不可用')
    t=ImportTemplate.objects.select_for_update().get(pk=payload.get('template_id'))
    v=ImportTemplateVersion.objects.get(pk=payload['version_id'],template=t);v.template=t;integrity(v)
    if purpose=='activate':owner(user,t)
    expected=receipt_payload(v,user,dict(sha256=hashlib.sha256(Path(path).read_bytes()).hexdigest(),filename=filename,
        schema_hash=m.digest(SCHEMAS),rules_hash=m.rules_hash()),purpose)
    if payload!=expected or m.digest(mapping)!=payload['mapping_hash']:raise m.MappingStale('模板、账号、文件、映射或规则已变化，请重新核对')
    if purpose=='use' and (v.state!='active' or t.current_version!=v.number):raise m.MappingStale('该模板版本已不再启用')
    if purpose=='activate' and v.state not in ('draft','retired'):raise m.MappingStale('只有草稿或停用版本可重新核对启用')
    return v,payload


@transaction.atomic
def activate(user,path,filename,receipt,data):
    if set(data)!={'revision','reason'}:raise ValueError('启用参数不完整')
    try:p=signing.loads(receipt,salt=SALT,max_age=m.MAX_AGE)
    except (signing.BadSignature,ValueError,TypeError) as ex:raise m.MappingStale('模板核对依据失效') from ex
    if not isinstance(p,dict) or type(p.get('version_id')) is not int:raise m.MappingStale('模板依据不可用')
    mapping=ImportTemplateVersion.objects.get(pk=p['version_id']).payload['mapping']
    v,payload=verify(user,receipt,path,filename,mapping,'activate');t=v.template;revision(t,data['revision'])
    reason=text(data.get('reason'),'启用依据',1000)
    previous=t.current_version
    t.versions.filter(state='active').exclude(pk=v.pk).update(state='retired')
    v.state='active';v.activated_by=user.username;v.activated_at=timezone.now();v.save(update_fields=['state','activated_by','activated_at'])
    t.current_version=v.number;t.revision+=1;t.save(update_fields=['current_version','revision'])
    audit(user,'activate',t,dict(version_id=v.pk,number=v.number,previous_version=previous,reason=reason,header_review=payload))
    return info(t,user,True)


@transaction.atomic
def retire(user,template_id,data):
    authorized(user)
    if set(data)!={'revision','reason'}:raise ValueError('停用参数不完整')
    t=ImportTemplate.objects.select_for_update().get(pk=template_id);owner(user,t);revision(t,data['revision'])
    reason=text(data.get('reason'),'停用依据',1000)
    if not t.current_version:raise m.MappingStale('模板当前没有启用版本')
    old=t.current_version;t.versions.filter(number=old,state='active').update(state='retired')
    t.current_version=0;t.revision+=1;t.save(update_fields=['current_version','revision'])
    audit(user,'retire',t,dict(number=old,reason=reason))
    return info(t,user,True)


def record_use(user,batch,v,payload,receipt,repeated):
    use,created=ImportTemplateUse.objects.get_or_create(batch=batch,version=v,receipt_hash=hashlib.sha256(receipt.encode()).hexdigest(),
        defaults=dict(actor=user.username,evidence={**payload,'repeated_batch':repeated,'review_state':'headers_only','business_approval':False}))
    if created:audit(user,'use',v.template,dict(use_id=use.pk,batch_id=str(batch.pk),version_id=v.pk,number=v.number,repeated_batch=repeated))


def batch_history(batch):
    return [dict(id=u.pk,template_id=str(u.version.template_id),code=u.version.template.code,name=u.version.template.name,
        version=u.version.number,version_id=u.version_id,content_hash=u.version.content_hash,actor=u.actor,
        created_at=u.created_at,evidence=u.evidence) for u in batch.template_uses.all()]


def record_recheck(user,original,batch):
    for old in original.template_uses.select_related('version__template'):
        evidence=dict(kind='historical_template_reference',source_use_id=old.pk,source_batch_id=str(original.pk),
            original_content_hash=old.version.content_hash,current_rules_hash=m.rules_hash(),
            fresh_template_activation=False,business_approval=False,review_state='full_recheck_using_original_mapping')
        use=ImportTemplateUse.objects.create(batch=batch,version=old.version,actor=user.username,evidence=evidence,
            receipt_hash=hashlib.sha256(('recheck:'+str(old.pk)+':'+str(batch.pk)).encode()).hexdigest())
        audit(user,'recheck_reference',old.version.template,dict(use_id=use.pk,batch_id=str(batch.pk),source_use_id=old.pk,source_batch_id=str(original.pk)))
