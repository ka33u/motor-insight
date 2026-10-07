"""Rule drafting, dated activation, suspension and forward-only continuation."""
from datetime import timedelta
from django.db import transaction
from django.db.models import Max
from django.core.exceptions import ValidationError,PermissionDenied
from django.utils import timezone
from . import access,coding
from .models import CodingRule,CodingRuleVersion,CodeCounter,CodeAllocation,AuditEvent
from .import_review import ReviewConflict


def require_admin(user):
    if access.role(user)!='admin':raise PermissionDenied('编码定义、启停、发号及接续仅限管理员')

def revision(rule,value):
    if type(value) is not int or value!=rule.revision:raise ReviewConflict('规则已被其他操作更新，请刷新后核对')

def reason(value):
    if not isinstance(value,str) or not 5<=len(value.strip())<=1000:raise ValidationError('请填写5—1000字的变更或接续依据')
    return value.strip()

def version_info(v):
    return {'id':v.pk,'version':v.version,'payload':v.payload,'status':v.status,'effective_from':v.effective_from,
            'reason':v.reason,'origin':v.origin,'created_by':v.created_by,'created_at':v.created_at,
            'activated_by':v.activated_by,'activated_at':v.activated_at}

def versions(rule):
    rows=list(rule.versions.order_by('version'))
    if not rows and rule.version:rows=[coding.resolve(rule,timezone.localdate())]
    return rows

def info(rule,detail=False):
    today=timezone.localdate();all_versions=versions(rule)
    active=[v for v in all_versions if v.status=='active' and (v.effective_from is None or v.effective_from<=today)]
    current=max(active,key=lambda v:(v.effective_from or today.replace(year=1,month=1,day=1),v.version)) if active else None
    upcoming=[version_info(v) for v in all_versions if v.status=='active' and v.effective_from and v.effective_from>today]
    draft=next((version_info(v) for v in all_versions if v.status=='draft'),None)
    out={'id':rule.pk,'key':rule.key,'name':(current.payload['name'] if current else draft['payload']['name'] if draft else rule.name),
         'enabled':rule.enabled,'revision':rule.revision,'version':rule.version,'current':version_info(current) if current else None,
         'scheduled':upcoming,'draft':draft,'today':today,'allocation_count':rule.codeallocation_set.count(),'notice':coding.NOTICE}
    if detail:
        out['versions']=[version_info(v) for v in all_versions]
        out['counters']=list(rule.codecounter_set.order_by('-period').values('period','value'))
        out['legacy_unknown_dates']=rule.codeallocation_set.filter(business_date=None).count()
        out['history']=list(AuditEvent.objects.filter(object_type='CodingRule',object_id=str(rule.pk)).order_by('-id').values('id','action','actor','detail','created_at')[:50])
        timeline=sorted([v for v in all_versions if v.status=='active'],key=lambda v:(v.effective_from or today.replace(year=1,month=1,day=1),v.version))
        out['timeline']=[{'version':v.version,'from':v.effective_from,'through':timeline[i+1].effective_from-timedelta(days=1) if i+1<len(timeline) else None} for i,v in enumerate(timeline)]
    return out

def audit(user,action,rule,before,extra=None):
    import json
    after=info(rule)
    serial=lambda v:json.loads(json.dumps(v,ensure_ascii=False,default=str))
    AuditEvent.objects.create(action='coding.'+action,actor=user.username,object_type='CodingRule',object_id=str(rule.pk),
        detail={'before':serial(before),'after':serial(after),**serial(extra or {})})

def baseline(rule):
    if rule.version and not rule.versions.exists():coding.ensure_version(coding.resolve(rule,timezone.localdate()))

@transaction.atomic
def create(user,data):
    require_admin(user)
    if set(data)!={'key','payload','reason'}:raise ValidationError('新规则须包含固定规则键、完整定义和依据')
    payload=coding.validate_payload(data['key'],data['payload']);why=reason(data['reason'])
    r=CodingRule.objects.create(key=data['key'],version=0,enabled=True,**payload)
    CodingRuleVersion.objects.create(rule=r,version=1,payload=payload,reason=why,created_by=user.username)
    audit(user,'draft_create',r,None)
    return info(r,True)

@transaction.atomic
def save_draft(user,rule_id,data):
    require_admin(user)
    if set(data)!={'revision','payload','reason'}:raise ValidationError('草稿须包含当前修订号、完整定义和依据')
    r=CodingRule.objects.select_for_update().get(pk=rule_id);revision(r,data['revision'])
    payload=coding.validate_payload(r.key,data['payload']);why=reason(data['reason']);baseline(r);before=info(r)
    draft=r.versions.filter(status='draft').first()
    if draft:
        draft.payload=payload;draft.reason=why;draft.save(update_fields=['payload','reason'])
    else:
        number=(r.versions.aggregate(n=Max('version'))['n'] or 0)+1
        draft=CodingRuleVersion.objects.create(rule=r,version=number,payload=payload,reason=why,created_by=user.username)
    r.revision+=1;r.save(update_fields=['revision']);audit(user,'draft_save',r,before,{'draft_version':draft.version})
    return info(r,True)

@transaction.atomic
def transition(user,rule_id,data):
    require_admin(user);r=CodingRule.objects.select_for_update().get(pk=rule_id);revision(r,data.get('revision'))
    action=data.get('action');why=reason(data.get('reason'));baseline(r);before=info(r);today=timezone.localdate()
    if action=='enabled':
        if set(data)!={'revision','action','enabled','reason'} or type(data['enabled']) is not bool:raise ValidationError('启停状态须为布尔值')
        if r.enabled==data['enabled']:raise ValidationError('规则已处于该状态')
        r.enabled=data['enabled']
    elif action in ['activate','cancel']:
        expected={'revision','action','version','reason'}|({'effective_from'} if action=='activate' else set())
        if set(data)!=expected or type(data['version']) is not int:raise ValidationError('版本操作参数不完整')
        v=r.versions.get(version=data['version'])
        if action=='activate':
            if v.status!='draft':raise ValidationError('只有草稿可以设定生效日期，已启用版本不可原地修改')
            at=coding.business_date(data['effective_from'])
            if at<today:raise ValidationError('新增版本不能追溯生效；生效日不得早于今天')
            latest=r.versions.filter(status='active',effective_from__isnull=False).aggregate(day=Max('effective_from'))['day']
            if latest and at<=latest:raise ValidationError('新版本生效日必须晚于已安排版本，不能覆盖既有日期区间')
            if r.codeallocation_set.filter(business_date__gte=at).exists():raise ValidationError('该日期及之后已有旧版本发号，请选择晚于已发业务日期的生效日')
            coding.validate_payload(r.key,v.payload)
            v.status='active';v.effective_from=at;v.reason=why;v.activated_by=user.username;v.activated_at=timezone.now();v.save()
            r.version=v.version
            for key,value in v.payload.items():setattr(r,key,value)
        else:
            if v.status=='active':
                if not v.effective_from or v.effective_from<=today:raise ValidationError('生效中的版本不能撤销；可停用规则或另建后续版本')
                if r.codeallocation_set.filter(rule_version=v.version).exists():raise ValidationError('此待生效版本已预发编号，不能撤销；请保留其历史或停用规则')
            elif v.status!='draft':raise ValidationError('该版本已撤销')
            v.status='cancelled';v.reason=why;v.save(update_fields=['status','reason'])
    else:raise ValidationError('不支持的规则操作')
    r.revision+=1;r.save();audit(user,action,r,before,{'reason':why})
    return info(r,True)

@transaction.atomic
def advance(user,rule_id,data):
    require_admin(user)
    if set(data)!={'revision','date','expected_counter','value','reason'}:raise ValidationError('接续请求须包含规则修订号、业务日期、当前序号、新序号和依据')
    r=CodingRule.objects.select_for_update().get(pk=rule_id);revision(r,data['revision']);why=reason(data['reason'])
    if not r.enabled:raise ValidationError('规则已停用，不能调整序列')
    p,_=coding.plan(r,data['date'],1,user.username)
    if type(data['expected_counter']) is not int or data['expected_counter']!=p['counter']:raise ReviewConflict('该周期序列已改变，请重新核对后接续')
    value=data['value']
    if type(value) is not int or not p['counter']<value<=p['capacity']:raise ValidationError('接续只能向前推进到位数容量内，不能回退或回收旧号')
    if value<p['history']['max_sequence']:raise ValidationError('接续序号不得小于已核实的历史最高序号')
    counter,_=CodeCounter.objects.get_or_create(rule=r,period=p['period']);before=info(r)
    counter.value=value;counter.save(update_fields=['value']);r.revision+=1;r.save(update_fields=['revision'])
    audit(user,'advance',r,before,{'period':p['period'],'from':p['counter'],'to':value,'reason':why,'history':p['history'],'business_date':str(p['business_date'])})
    return {'revision':r.revision,'period':p['period'],'counter':value,'next_sequence':value+1 if value<p['capacity'] else None,
            'notice':'仅向前接续序列，跳过号码不会回收；原始业务记录与已分配号码保持不变。'}
