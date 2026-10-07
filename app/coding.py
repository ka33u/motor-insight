"""Dated immutable coding definitions and transactional number reservation."""
import hashlib,json,re,uuid
from datetime import date,datetime
from types import SimpleNamespace
from django.db import transaction
from django.core.exceptions import ValidationError
from .models import CodingRule,CodingRuleVersion,CodeCounter,CodeAllocation,CodeIssueRequest,Record,AuditEvent
from .import_review import ReviewConflict

FORMATS={'','%Y%m%d','%y%m%d','%Y%m','%y%m','%Y'}
FIELDS=('name','prefix','date_format','width','separator','reset_period')
class PreviewExpired(ReviewConflict):
    """The request ID does not exist and its preview is no longer applicable."""

NOTICE='编号分配仅占号，不创建工单、物料或电机，不回写U8/MES。预览不占号；正式发号保留当次定义，停用和改版不回收旧号。'

def validate_rule(data):
    if not isinstance(data,dict):raise ValidationError('规则须为对象')
    if not isinstance(data.get('key'),str) or not re.fullmatch(r'[a-z][a-z0-9_]{1,39}',data['key']):raise ValidationError('规则键需2—40位小写字母、数字或下划线')
    if type(data.get('width',5)) is not int or not 1<=data.get('width',5)<=12:raise ValidationError('序号位数须为1—12的整数')
    if data.get('date_format','%Y%m%d') not in FORMATS:raise ValidationError('日期格式不可用')
    if data.get('reset_period','day') not in ['day','month','year','never']:raise ValidationError('重置周期不可用')
    fmt=data.get('date_format','%Y%m%d');period=data.get('reset_period','day')
    if period=='day' and '%d' not in fmt:raise ValidationError('每日重置必须在编号中包含年月日')
    if period=='month' and '%m' not in fmt:raise ValidationError('每月重置必须在编号中包含年月')
    if period=='year' and not fmt:raise ValidationError('每年重置必须在编号中包含年份')
    if not isinstance(data.get('name'),str) or not 1<=len(data['name'].strip())<=100:raise ValidationError('名称需1—100字')
    if not isinstance(data.get('prefix'),str) or not re.fullmatch(r'[A-Za-z0-9.]{1,30}',data['prefix']):raise ValidationError('前缀限1—30位字母、数字和点')
    if data.get('separator','-') not in ['-','.','']:raise ValidationError('分隔符限 -、. 或空')

def validate_payload(key,payload):
    if not isinstance(payload,dict) or set(payload)!=set(FIELDS):raise ValidationError('规则定义须完整包含名称、前缀、日期、位数、分隔符和重置周期')
    validate_rule({'key':key,**payload});return {k:payload[k].strip() if k in ['name','prefix'] else payload[k] for k in FIELDS}

def business_date(value):
    if isinstance(value,datetime):return value.date()
    if type(value) is date:return value
    if not isinstance(value,str):raise ValidationError('业务日期必须为YYYY-MM-DD')
    try:
        at=date.fromisoformat(value)
        if at.isoformat()!=value:raise ValueError()
        return at
    except ValueError:raise ValidationError('业务日期必须为YYYY-MM-DD')

def period_for(rule,at):return at.strftime({'day':'%Y%m%d','month':'%Y%m','year':'%Y','never':'ALL'}[rule.reset_period])

def render_code(rule,at,number):
    if not 1<=number<10**rule.width:raise ValidationError('本周期序号已超过位数容量，请增加位数建立新版本；不能回绕到旧号')
    return rule.separator.join(x for x in [rule.prefix,at.strftime(rule.date_format) if rule.date_format else '',str(number).zfill(rule.width)] if x)

def payload_for(rule):return {k:getattr(rule,k) for k in FIELDS}

def resolve(rule,at):
    versions=list(rule.versions.filter(status='active'))
    candidates=[v for v in versions if v.effective_from is None or v.effective_from<=at]
    if candidates:return max(candidates,key=lambda v:(v.effective_from or date.min,v.version))
    # Compatibility for programmatically seeded rules; previews remain read-only.
    if rule.version and not rule.versions.exists():
        return CodingRuleVersion(rule=rule,version=rule.version,payload=payload_for(rule),status='active',origin='legacy_snapshot',created_by='legacy_seed')
    raise ValidationError('该业务日期没有已生效版本，请先启用草稿或选择有效日期')

def ensure_version(v):
    if v.pk:return v
    v.save();return v

def digest(value):return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False,default=str).encode()).hexdigest()

def occupied(config,at):
    first=render_code(config,at,1);stem=first[:-config.width]
    pattern=re.compile(re.escape(stem)+r'[0-9]{'+str(config.width)+r'}\Z')
    maximum=0;matched=0;examples=[]
    for source,query in [('已导入业务主键',Record.objects.filter(business_key__startswith=stem).values_list('business_key',flat=True)),
                         ('已分配编号',CodeAllocation.objects.filter(code__startswith=stem).values_list('code',flat=True))]:
        values=list(query[:100001])
        if len(values)>100000:raise ValidationError('同前缀历史候选超过100000条，接续核对范围过大，请按更细日期或独立前缀配置')
        for code in values:
            if pattern.fullmatch(code):
                sequence=int(code[-config.width:]);maximum=max(maximum,sequence);matched+=1
                if len(examples)<8:examples.append({'code':code,'source':source})
    return {'max_sequence':maximum,'matching_records':matched,'examples':examples,'note':'按所选日期的完整格式匹配，序号最高值用于接续；匹配条数可包含同一编码的占号记录和已导入记录。'}

def plan(rule,at,count,actor):
    if type(count) is not int or not 1<=count<=100:raise ValidationError('单次申请1—100个整数编号')
    at=business_date(at);v=resolve(rule,at);config=SimpleNamespace(**validate_payload(rule.key,v.payload))
    period=period_for(config,at);counter=CodeCounter.objects.filter(rule=rule,period=period).first();start=counter.value if counter else 0
    capacity=10**config.width-1
    codes=[render_code(config,at,start+i+1) for i in range(count)] if start+count<=capacity else []
    historical=occupied(config,at)
    errors=[]
    if not rule.enabled:errors.append('规则已停用，不能发号')
    if start+count>capacity:errors.append('本周期剩余位数容量不足，请建立更宽的规则版本')
    if historical['max_sequence']>start:errors.append('已存在更高历史序号，请先核对并接续序列，不能直接回填较小编号')
    duplicate_alloc=list(CodeAllocation.objects.filter(code__in=codes).values_list('code',flat=True))
    duplicate_record=list(Record.objects.filter(business_key__in=codes).values_list('business_key',flat=True))
    collisions=sorted(set(duplicate_alloc+duplicate_record))
    if collisions:errors.append('候选号与已分配编号或已导入业务主键重合')
    snapshot={'version':v.version,'payload':v.payload,'effective_from':v.effective_from,'origin':v.origin}
    token=digest({'rule_id':rule.pk,'revision':rule.revision,'enabled':rule.enabled,'at':at,'count':count,'start':start,'definition':snapshot,'codes':codes,'errors':errors,'actor':actor})
    return {'rule_id':rule.pk,'revision':rule.revision,'business_date':at,'period':period,'counter':start,'count':count,'capacity':capacity,
            'remaining':max(0,capacity-start),'codes':codes,'definition':snapshot,'history':historical,'collisions':collisions,
            'valid':not errors,'errors':errors,'preview_token':token,'notice':NOTICE},v

def preview(rule_id,at,count,actor):
    p,_=plan(CodingRule.objects.get(pk=rule_id),at,count,actor);return p

def reserve(rule,p,v,actor,request=None):
    if not p['valid']:raise ValidationError(p['errors'])
    v=ensure_version(v)
    counter,_=CodeCounter.objects.get_or_create(rule=rule,period=p['period'])
    # The parent lock serializes issuers, including when this period is new.
    counter.value=p['counter']+p['count'];counter.save(update_fields=['value'])
    snapshot=json.loads(json.dumps(p['definition'],default=str,ensure_ascii=False))
    CodeAllocation.objects.bulk_create([CodeAllocation(code=code,rule=rule,rule_version=v.version,allocated_by=actor,
        business_date=p['business_date'],period=p['period'],sequence=p['counter']+index+1,definition=snapshot,request=request)
        for index,code in enumerate(p['codes'])])
    AuditEvent.objects.create(action='coding.allocate',actor=actor,object_type='CodingRule',object_id=str(rule.pk),detail={
        'period':p['period'],'version':v.version,'codes':p['codes'],'business_date':str(p['business_date']),
        'request_id':str(request.pk) if request else None,'definition':snapshot,'counter_before':p['counter'],'counter_after':counter.value})
    return p['codes']

def allocate(rule_id,at,count,actor,preview=False):
    """Internal use: trace-case creation already owns an atomic/idempotent request."""
    with transaction.atomic():
        rule=CodingRule.objects.select_for_update().get(pk=rule_id)
        p,v=plan(rule,at,count,actor)
        if not p['valid']:raise ValidationError(p['errors'])
        return p['codes'] if preview else reserve(rule,p,v,actor)

@transaction.atomic
def issue(rule_id,data,actor):
    if set(data)!={'date','count','preview','preview_token','request_id','purpose'} or data['preview'] is not False:raise ValidationError('正式申请须包含日期、数量、预览凭据、请求号和用途')
    try:rid=uuid.UUID(str(data['request_id']))
    except (ValueError,TypeError,AttributeError):raise ValidationError('发号请求号格式不正确')
    if not isinstance(data['purpose'],str) or not 5<=len(data['purpose'].strip())<=300:raise ValidationError('请填写5—300字的发号用途')
    if not isinstance(data['preview_token'],str) or not re.fullmatch('[a-f0-9]{64}',data['preview_token']):raise ValidationError('请先取得有效预览')
    rule=CodingRule.objects.select_for_update().get(pk=rule_id)
    fingerprint=digest({'rule_id':rule_id,'actor':actor,'data':data})
    prior=CodeIssueRequest.objects.filter(pk=rid).first()
    if prior:
        if prior.payload_hash!=fingerprint or prior.actor!=actor:raise ReviewConflict('此请求号已用于另一组申请参数，请重新预览')
        return {'codes':prior.codes,'request_id':str(prior.pk),'version':prior.rule_version.version,'business_date':prior.business_date,'replayed':True,'preview':False,'allocation_count':rule.codeallocation_set.count(),'notice':NOTICE}
    p,v=plan(rule,data['date'],data['count'],actor)
    if p['preview_token']!=data['preview_token']:raise PreviewExpired('规则、序列或历史占号已变化，原预览失效；请重新预览后申请')
    if not p['valid']:raise ValidationError(p['errors'])
    v=ensure_version(v)
    request=CodeIssueRequest.objects.create(id=rid,rule=rule,rule_version=v,payload_hash=fingerprint,actor=actor,purpose=data['purpose'].strip(),business_date=p['business_date'],codes=p['codes'])
    reserve(rule,p,v,actor,request)
    return {'codes':request.codes,'request_id':str(request.pk),'version':v.version,'business_date':request.business_date,'replayed':False,'preview':False,'allocation_count':rule.codeallocation_set.count(),'notice':NOTICE}
