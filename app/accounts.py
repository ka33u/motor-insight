"""Local account administration; existing business ownership remains immutable."""
import hashlib
import json
import re
from types import SimpleNamespace
from django.contrib.auth.models import User, Group
from django.contrib.auth.password_validation import validate_password, MinimumLengthValidator, CommonPasswordValidator, NumericPasswordValidator, UserAttributeSimilarityValidator
from django.core import signing
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import F, Q
from django.utils import timezone
from . import access
from .models import AccountAccessState, AccountChangeLock, AuditEvent, AnalysisModel, Topic
from .semantic_schema import schemas
from .import_review import ReviewConflict

NOTICE='一个账号配置一个内置业务角色。金额、人员字段及下载由服务端检查；当前未按工厂、部门或客户做行级隔离。角色或启停改变、强制退出后，旧登录在下次请求时失效；已下载文件和已显示内容无法收回。账号名固定，停用不删除模型、专题或历史。'
SESSION_KEY='motor_access_epoch'
STAMP_KEY='motor_access_stamp'
SALT='motor-account-preview-v1'

def digest(value):return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,default=str,separators=(',',':')).encode()).hexdigest()

def session_stamp(user):
    return digest({'id':user.pk,'active':user.is_active,'superuser':user.is_superuser,'groups':sorted(user.groups.values_list('name',flat=True))})

def bind_session(request,user):
    request.session[SESSION_KEY]=AccountAccessState.objects.filter(user=user).values_list('session_epoch',flat=True).first() or 0
    request.session[STAMP_KEY]=session_stamp(user)

def profile(user):
    state=AccountAccessState.objects.filter(user=user).first()
    names=sorted(user.groups.values_list('name',flat=True));known=[x for x in names if x in access.ROLES]
    effective=access.role(user)
    return {'id':user.pk,'username':user.username,'display_name':user.first_name,'is_active':user.is_active,
            'role':known[0] if len(known)==1 else ('viewer' if not known else None),'effective_role':effective,
            'role_label':access.ROLES.get(effective,'已停用' if not user.is_active else '角色冲突'),
            'assigned_roles':known,'unmanaged_groups':[x for x in names if x not in access.ROLES],
            'role_fallback':not known and not user.is_superuser,'is_superuser':user.is_superuser,
            'has_password':user.has_usable_password(),'revision':state.revision if state else 0,
            'session_epoch':state.session_epoch if state else 0,'last_login':user.last_login.isoformat() if user.last_login else None,
            'date_joined':user.date_joined.isoformat(),'updated_at':state.updated_at.isoformat() if state else None,
            'updated_by':state.updated_by if state else ''}

def current_receipt(user):
    p=profile(user)
    # Include credential changes in concurrency detection without exposing the stored hash.
    return digest({k:v for k,v in p.items() if k not in ['last_login','date_joined','updated_at']}|{'credential':digest(user.password)})

def as_role(role,username='',pk=None,active=True):
    return SimpleNamespace(username=username,pk=pk,id=pk,is_authenticated=True,is_active=active,is_superuser=False,
                           groups=SimpleNamespace(values_list=lambda *a,**kw:[role]))

def capabilities(user):
    r=access.role(user)
    return {'browse':r is not None,'money':access.can_money(user),'personnel':access.allowed(user,'attendance'),
            'edit_analysis':access.can_edit(user),'import':access.can_import(user),'coding':r=='admin',
            'audit_accounts':r=='admin','device_originals':r in ['admin','quality'],'shared_originals':r is not None,
            'business_followup':r in ['admin','analyst','operations','quality'],
            'finance_followup':r in ['admin','analyst','finance'],'coordination_tasks':r in ['admin','analyst','quality','operations','finance']}

CAPABILITY_LABELS={'browse':'普通业务查询与同权限导出','money':'金额字段与成本、应收数据','personnel':'考勤、技能及作业工时','edit_analysis':'创建分析模型、专题及分组','import':'Excel原件、导入与冲突审核','coding':'编码定义与发号','audit_accounts':'审计与账号管理','device_originals':'个人检测原件归档与关联','shared_originals':'按逐文件授权只读原件（不授予业务或关联权限）','business_followup':'业务异常协调（核验另按岗位）','finance_followup':'应收核对跟进','coordination_tasks':'建立协调任务（仍按资料级别与任务身份限制）'}

def permission_profile(user):
    effective=access.role(user)
    user=as_role(effective or 'viewer',user.username,user.pk,effective is not None)
    values=[]
    for key,s in schemas().items():
        visible=access.allowed(user,key)
        permitted=access.permitted_fields(user,key) if visible else []
        shown={f['name'] for f in permitted}
        hidden=[{'name':f['name'],'label':f['label']} for f in s['fields'] if f['name'] not in shown]
        values.append({'id':key,'label':s['label'],'allowed':visible,'visible_fields':len(permitted),'total_fields':len(s['fields']),'hidden_fields':hidden})
    return {'capabilities':capabilities(user),'datasets':values}

def roles():
    return [{'id':key,'label':label,**permission_profile(as_role(key))} for key,label in access.ROLES.items()]

def require_admin(user):
    if access.role(user)!='admin':raise PermissionDenied('账号与角色管理仅供平台管理员使用')

def locked_actor(actor):
    AccountChangeLock.objects.get_or_create(pk=1)
    AccountChangeLock.objects.filter(pk=1).update(revision=F('revision')+1)
    fresh=User.objects.get(pk=actor.pk)
    require_admin(fresh)
    return fresh

def reason(value):
    if not isinstance(value,str) or not 5<=len(value.strip())<=1000:raise ValidationError('请填写5至1000字的变更依据')
    return value.strip()

def changes(payload):
    if not isinstance(payload,dict) or set(payload)!={'display_name','role','is_active'}:raise ValidationError('只可修改显示名称、单个角色和启用状态')
    if not isinstance(payload['display_name'],str) or not 1<=len(payload['display_name'].strip())<=150:raise ValidationError('显示名称须为1至150字')
    if not isinstance(payload['role'],str) or payload['role'] not in access.ROLES:raise ValidationError('请选择一个内置角色')
    if type(payload['is_active']) is not bool:raise ValidationError('启用状态必须为布尔值')
    return {**payload,'display_name':payload['display_name'].strip()}

def guard(actor,user,p):
    if user.is_superuser:raise PermissionDenied('超级用户由部署管理员维护，此界面只读')
    if actor.pk==user.pk and (p['role']!='admin' or not p['is_active']):raise ValidationError('不能在此处停用自己或移除自己的管理员角色')
    if user.is_active and access.role(user)=='admin' and (p['role']!='admin' or not p['is_active']):
        others=User.objects.filter(is_active=True).exclude(pk=user.pk).filter(Q(is_superuser=True)|Q(groups__name='admin')).distinct()
        if not any(access.role(u)=='admin' and u.has_usable_password() for u in others):raise ValidationError('必须保留至少一个启用且可登录的管理员')

def owned_impact(user,proposed):
    from .analysis_engine import validate_definition
    rows=[];total=0
    for model in AnalysisModel.objects.filter(owner=user.username).order_by('id'):
        total+=1
        try:
            if not access.can_edit(proposed):raise ValidationError('该角色不能编辑分析模型')
            validate_definition(proposed,model.dataset,model.definition)
        except (ValidationError,ValueError,PermissionDenied) as ex:
            rows.append({'id':model.pk,'name':model.name,'reason':'; '.join(ex.messages) if isinstance(ex,ValidationError) else str(ex)})
    return {'owned_models':total,'affected_models':rows[:100],'affected_model_count':len(rows),'owned_topics':Topic.objects.filter(owner=user.username).count(),
            'note':'列出本人模型的编辑或定义权限影响；不执行模型。专题、个人视角、分组、附件和快照保留原归属，打开时仍按当时权限检查，不会自动转交。'}

def preview(actor,user,payload):
    require_admin(actor);p=changes(payload);guard(actor,user,p)
    proposed=as_role(p['role'],user.username,user.pk,p['is_active'])
    before=permission_profile(user);after=permission_profile(proposed)
    receipt=current_receipt(user)
    token=signing.dumps({'actor':actor.pk,'target':user.pk,'receipt':receipt,'changes':p},salt=SALT,compress=True)
    return {'before':profile(user),'changes':p,'before_permissions':before,'after_permissions':after,
            'impact':owned_impact(user,proposed),'preview_token':token,'expires_seconds':600,'notice':NOTICE}

@transaction.atomic
def update(actor,user_id,payload):
    actor=locked_actor(actor)
    if not isinstance(payload,dict) or set(payload)!={'preview_token','reason'}:raise ValidationError('请先预览变更并填写依据')
    why=reason(payload['reason'])
    try:proposal=signing.loads(payload['preview_token'],salt=SALT,max_age=600)
    except (signing.BadSignature,TypeError):raise ReviewConflict('预览已过期或无效，请重新预览')
    user=User.objects.select_for_update().get(pk=user_id)
    if proposal['actor']!=actor.pk or proposal['target']!=user.pk or proposal['receipt']!=current_receipt(user):raise ReviewConflict('账号或权限已变化，请重新读取并预览')
    p=changes(proposal['changes']);guard(actor,user,p);before=profile(user)
    changed=(user.first_name!=p['display_name'] or user.is_active!=p['is_active'] or before['assigned_roles']!=[p['role']])
    if not changed:return {'user':before,'changed':False,'notice':'内容未变化，未新增修订或审计。'}
    permission_changed=user.is_active!=p['is_active'] or before['assigned_roles']!=[p['role']]
    user.first_name=p['display_name'];user.is_active=p['is_active'];user.save(update_fields=['first_name','is_active'])
    user.groups.remove(*Group.objects.filter(name__in=access.ROLES));group,_=Group.objects.get_or_create(name=p['role']);user.groups.add(group)
    state,_=AccountAccessState.objects.get_or_create(user=user)
    state.revision+=1;state.session_epoch+=int(permission_changed);state.updated_by=actor.username;state.save()
    after=profile(user)
    AuditEvent.objects.create(action='account.update',actor=actor.username,object_type='UserAccess',object_id=str(user.pk),detail={'before':before,'after':after,'reason':why,'sessions_invalidated':permission_changed,'business_facts_changed':False})
    return {'user':after,'changed':True,'notice':'已保存账号设置。'+('该账号已有登录在下次请求时失效。' if permission_changed else '显示名称已更新。')}

@transaction.atomic
def create(actor,payload):
    actor=locked_actor(actor)
    if not isinstance(payload,dict) or set(payload)!={'username','display_name','role','is_active','password','reason'}:raise ValidationError('账号创建字段不完整或包含不支持字段')
    why=reason(payload['reason']);p=changes({k:payload[k] for k in ['display_name','role','is_active']})
    username=payload['username'];password=payload['password']
    if not isinstance(username,str) or not re.fullmatch(r'[a-z][a-z0-9_.-]{2,63}',username):raise ValidationError('账号须以小写字母开头，3至64位，仅含小写字母、数字、点、下划线或短横线')
    if User.objects.filter(username__iexact=username).exists():raise ValidationError('账号名已存在；停用账号也不能重复使用')
    if not isinstance(password,str) or not 12<=len(password)<=128:raise ValidationError('初始口令须为12至128位')
    user=User(username=username,first_name=p['display_name'],is_active=p['is_active'],is_staff=False,is_superuser=False)
    validate_password(password,user,[MinimumLengthValidator(12),CommonPasswordValidator(),NumericPasswordValidator(),UserAttributeSimilarityValidator()])
    user.set_password(password);user.save();group,_=Group.objects.get_or_create(name=p['role']);user.groups.add(group)
    AccountAccessState.objects.create(user=user,revision=1,updated_by=actor.username)
    after=profile(user)
    AuditEvent.objects.create(action='account.create',actor=actor.username,object_type='UserAccess',object_id=str(user.pk),detail={'after':after,'reason':why,'business_facts_changed':False})
    return {'user':after,'notice':'账号已建立；初始口令不会再次展示或写入审计。请由管理员通过受控方式交接。'}

@transaction.atomic
def revoke(actor,user_id,payload):
    actor=locked_actor(actor)
    if not isinstance(payload,dict) or set(payload)!={'receipt','reason'}:raise ValidationError('请重新读取账号并填写退出依据')
    why=reason(payload['reason']);user=User.objects.select_for_update().get(pk=user_id)
    if user.is_superuser:raise PermissionDenied('超级用户由部署管理员维护')
    if payload['receipt']!=current_receipt(user):raise ReviewConflict('账号已变化，请重新读取')
    before=profile(user);state,_=AccountAccessState.objects.get_or_create(user=user)
    state.revision+=1;state.session_epoch+=1;state.updated_by=actor.username;state.save()
    after=profile(user)
    AuditEvent.objects.create(action='account.sessions_revoke',actor=actor.username,object_type='UserAccess',object_id=str(user.pk),detail={'before':before,'after':after,'reason':why,'business_facts_changed':False})
    return {'user':after,'notice':'该账号已有登录在下次请求时失效；允许重新验证口令登录。'}
