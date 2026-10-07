"""Owner-issued, append-only file read grants. No business or association rights."""
import hashlib,re,uuid
from datetime import datetime,timezone as dtz
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError,PermissionDenied
from django.db import transaction
from django.utils import timezone
from . import access,accounts,device_files as files
from .models import DeviceFile,FileReadGrant,AuditEvent,AccountAccessState
from .topic_workspace import digest,clean_text
from .import_review import ReviewConflict

NOTICE='原件默认私有。归档人可向指定有效账号授予此文件的只读权限，可设到期时间或追加撤销；接收账号岗位配置变化后需重新授权。只读权限不包含原件转授权、检测关联、业务数据或质量批准。撤销停止后续读取，已下载或已显示的内容无法收回。'
FIELDS={'recipient_id','action','reason','expires_at'}
class GrantConflict(ReviewConflict):pass

def fresh(user):
    if not getattr(user,'is_authenticated',False):raise PermissionDenied('请先登录')
    u=User.objects.get(pk=user.pk)
    if access.role(u) is None:raise PermissionDenied('账号停用或角色冲突')
    return u

def account_receipt(u):
    state=AccountAccessState.objects.filter(user=u).first()
    return digest(dict(id=u.pk,active=u.is_active,role=access.role(u),superuser=u.is_superuser,
        groups=sorted(u.groups.values_list('name',flat=True)),revision=state.revision if state else 0))

def user_label(u):return dict(id=u.pk,username=u.username,display_name=u.first_name,role=access.role(u),role_label=access.ROLES.get(access.role(u),'停用或冲突'))

def expiry(value):
    if value=='':return None
    if not isinstance(value,str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z',value):raise ValidationError('授权截止须为UTC秒级时间或空字符串')
    try:return datetime.strptime(value,'%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=dtz.utc)
    except ValueError:raise ValidationError('授权截止日期无效')

def history(f):
    rows=list(f.read_grants.select_related('recipient','actor').order_by('version'));last=None;latest={}
    for n,r in enumerate(rows,1):
        expected=dict(file_id=str(f.pk),file_hash=f.file_hash,metadata_hash=f.metadata_hash,
          recipient_id=r.recipient_id,actor_id=r.actor_id,action=r.action,version=n,request_id=str(r.request_id),
          previous_id=last.pk if last else None,previous_hash=last.payload_hash if last else None)
        if r.version!=n or r.actor_id!=f.owner_id or r.action not in ['grant','revoke'] or digest(r.payload)!=r.payload_hash or any(r.payload.get(k)!=v for k,v in expected.items()):
            raise GrantConflict('原件授权历史完整性异常，协作读取暂停')
        if not isinstance(r.payload.get('recipient_stamp'),str) or not isinstance(r.payload.get('recipient'),dict) or r.payload['recipient'].get('id')!=r.recipient_id:raise GrantConflict('原件授权身份依据不完整')
        try:expiry(r.payload.get('expires_at'))
        except ValidationError:raise GrantConflict('原件授权时间依据异常')
        latest[r.recipient_id]=r;last=r
    return rows,latest

def grant_state(event,u,now=None):
    if event.action=='revoke':return 'revoked'
    if access.role(u) is None or account_receipt(u)!=event.payload['recipient_stamp']:return 'account_changed'
    until=expiry(event.payload['expires_at'])
    if until is not None and until<=(now or timezone.now()):return 'expired'
    return 'active'

def readable(user,file_id,check_file=True):
    """Return the file and permission receipt; preserve default-private owner API."""
    u=fresh(user);f=DeviceFile.objects.select_related('owner').get(pk=file_id)
    if f.owner_id==u.pk:
        f=files.get(u,f.pk,check_file=check_file)
        return f,'owner:'+account_receipt(u)
    # No metadata or global grant history is revealed to an unrelated account.
    if not f.read_grants.filter(recipient_id=u.pk).exists():raise DeviceFile.DoesNotExist
    _,latest=history(f);event=latest.get(u.pk)
    if event is None or grant_state(event,u)!='active':raise DeviceFile.DoesNotExist
    if digest(files.file_meta(f))!=f.metadata_hash:raise ReviewConflict('归档元数据完整性核验失败')
    if check_file:files.contents(f)
    return f,'grant:'+event.payload_hash+':'+account_receipt(u)

def observed(f):
    try:raw=files.path(f).read_bytes()
    except OSError:return 'missing',False
    sha=hashlib.sha256(raw).hexdigest()
    return sha,len(raw)==f.size and sha==f.file_hash

def owner(user,file_id):
    u=fresh(user);return u,files.get(u,file_id,check_file=False)

def receipt(u,f,rows,recipient=None):
    actual,valid=observed(f)
    return digest(dict(actor=u.pk,actor_stamp=account_receipt(u),file_id=str(f.pk),metadata=f.metadata_hash,
      observed=actual,version=rows[-1].version if rows else 0,last_hash=rows[-1].payload_hash if rows else None,
      recipient_stamp=account_receipt(recipient) if recipient else None))

def changes(data):
    if not isinstance(data,dict) or set(data)!=FIELDS:raise ValidationError('请填写指定账号、操作、依据及截止时间')
    if type(data['recipient_id']) is not int or data['recipient_id']<=0:raise ValidationError('接收账号标识无效')
    if data['action'] not in ['grant','revoke']:raise ValidationError('原件授权操作无效')
    reason=clean_text(data['reason'],'授权或撤销依据',1000)
    if len(reason)<5:raise ValidationError('授权或撤销依据至少5字')
    until=expiry(data['expires_at'])
    if data['action']=='revoke' and until is not None:raise ValidationError('撤销不设置截止时间')
    return {**data,'reason':reason}

def event_info(r):return dict(id=r.pk,version=r.version,action=r.action,created_at=r.created_at,payload_hash=r.payload_hash,payload=r.payload)

@transaction.atomic
def context(user,file_id):
    u,f=owner(user,file_id);rows,latest=history(f);actual,valid=observed(f)
    recipients=[user_label(x) for x in User.objects.filter(is_active=True).exclude(pk=u.pk).order_by('username') if access.role(x) is not None]
    return dict(file=files.info(f),notice=NOTICE,version=rows[-1].version if rows else 0,
      original_valid=valid,original_observed=actual,recipients=recipients,
      grants=[event_info(r)|{'state':grant_state(r,r.recipient)} for r in latest.values()],
      history=[event_info(r) for r in reversed(rows)])

@transaction.atomic
def preview(user,file_id,data):
    u,f=owner(user,file_id);d=changes(data);target=User.objects.get(pk=d['recipient_id']);rows,latest=history(f)
    if u.pk==target.pk:raise ValidationError('归档人已有原件权限，不向自己授权')
    old=latest.get(target.pk);actual,valid=observed(f)
    if d['action']=='grant':
        if access.role(target) is None:raise ValidationError('接收账号已停用或岗位冲突')
        if not valid:raise ReviewConflict('原件缺失或摘要异常，新增授权暂停')
        until=expiry(d['expires_at'])
        if until is not None and until<=timezone.now():raise ValidationError('授权截止必须晚于当前时间')
    elif not old or old.action!='grant':raise ValidationError('此账号没有可撤销的授权记录')
    return dict(file=files.info(f),recipient=user_label(target),change=d,
      prior=event_info(old) if old else None,notice=NOTICE,
      token=digest([receipt(u,f,rows,target),d]),version=rows[-1].version if rows else 0)

@transaction.atomic
def commit(user,file_id,data):
    u,f=owner(user,file_id)
    if not isinstance(data,dict) or set(data)!=FIELDS|{'request_id','token'}:raise ValidationError('授权确认参数不完整')
    if not isinstance(data['token'],str):raise ValidationError('授权核对凭据无效')
    rid=uuid.UUID(str(data['request_id']));request_hash=digest([str(f.pk),data])
    existing=FileReadGrant.objects.filter(request_id=rid).first()
    if existing:
        if existing.actor_id!=u.pk or existing.file_id!=f.pk or existing.request_hash!=request_hash:raise ReviewConflict('授权申请号已用于其他内容')
        history(f);return existing
    DeviceFile.objects.select_for_update().get(pk=f.pk)
    d={k:data[k] for k in FIELDS};p=preview(u,f.pk,d)
    if p['token']!=data['token']:raise ReviewConflict('原件、授权历史或账号岗位已变化，请重新核对')
    target=User.objects.get(pk=d['recipient_id']);rows,_=history(f);last=rows[-1] if rows else None
    payload=dict(file_id=str(f.pk),file_hash=f.file_hash,metadata_hash=f.metadata_hash,
      recipient_id=target.pk,recipient=user_label(target),recipient_stamp=account_receipt(target),
      actor_id=u.pk,actor=user_label(u),action=p['change']['action'],version=p['version']+1,
      reason=p['change']['reason'],expires_at=p['change']['expires_at'],request_id=str(rid),
      previous_id=last.pk if last else None,previous_hash=last.payload_hash if last else None,
      recorded_at=timezone.now().isoformat(),business_facts_changed=False,association_rights=False)
    event=FileReadGrant.objects.create(file=f,recipient=target,actor=u,version=payload['version'],action=payload['action'],
      request_id=rid,request_hash=request_hash,payload=payload,payload_hash=digest(payload))
    AuditEvent.objects.create(action='file_read.'+event.action,actor=u.username,object_type='DeviceFile',object_id=str(f.pk),
      detail=dict(event_id=event.pk,version=event.version,recipient_id=target.pk,payload_hash=event.payload_hash,business_facts_changed=False,association_rights=False))
    return event

def listing(user):
    u=fresh(user);ids=list(FileReadGrant.objects.filter(recipient=u).values_list('file_id',flat=True).distinct());rows=[]
    for key in ids:
        try:f,permit=readable(u,key,check_file=False)
        except DeviceFile.DoesNotExist:continue
        except ReviewConflict:continue  # Damaged authorization does not disclose the private original.
        _,latest=history(f);e=latest[u.pk]
        rows.append(dict(file=files.info(f),owner=user_label(f.owner),granted_at=e.created_at,expires_at=e.payload['expires_at'],permission_receipt=permit))
    return dict(rows=sorted(rows,key=lambda r:(str(r['granted_at']),r['file']['id']),reverse=True),notice=NOTICE)

def detail(user,file_id):
    u=fresh(user);f,permit=readable(u,file_id)
    if f.owner_id==u.pk:return dict(file=files.info(f),owner=user_label(f.owner),owner_access=True,notice=NOTICE,permission_receipt=permit)
    _,latest=history(f);e=latest[u.pk]
    return dict(file=files.info(f),owner=user_label(f.owner),owner_access=False,grant=event_info(e),notice=NOTICE,permission_receipt=permit)
