"""Credential maintenance, with fresh authority and atomic account/audit changes.

No credential material is placed in a preview, audit, URL or response. Existing
roles, active state and all business ownership remain unchanged.
"""
from django.contrib.auth.hashers import check_password
from django.contrib.auth.models import User
from django.core import signing
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import F
from django.views.decorators.debug import sensitive_variables

from . import access, accounts
from .import_review import ReviewConflict
from .models import AccountAccessState, AccountChangeLock, AuditEvent, AnalysisModel, Topic

SALT = 'motor-credential-maintenance-v1'
RULES = '12至128位；不能与现用口令相同；不能是常见、纯数字或与账号信息过于相似的口令。口令按原样使用，不自动去除空格。'
NOTICE = '保存后该账号的全部旧登录在下次请求时失效，须用新口令重新登录。角色、启停状态、模型、专题和私人原件归属保持不变；停用账号不会因此启用。'


def eligible(user):
    if user.is_superuser:
        raise PermissionDenied('部署超级用户由部署管理员维护口令')


def fresh_actor(actor, *, administrator=False):
    fresh = User.objects.get(pk=actor.pk)
    if access.role(fresh) is None:
        raise PermissionDenied('账号已停用或角色冲突，请重新登录')
    if administrator:
        accounts.require_admin(fresh)
    return fresh


def lock():
    # Same serialisation point as role/active/session administration.
    AccountChangeLock.objects.get_or_create(pk=1)
    AccountChangeLock.objects.filter(pk=1).update(revision=F('revision') + 1)


def token(actor, user, mode):
    return signing.dumps({'actor': actor.pk, 'target': user.pk, 'mode': mode,
                          'receipt': accounts.current_receipt(user)}, salt=SALT, compress=True)


def proposal(value, actor, user, mode):
    if not isinstance(value, str) or len(value) > 16000:
        raise ReviewConflict('口令核对凭据无效，请重新读取')
    try:
        data = signing.loads(value, salt=SALT, max_age=600)
    except (signing.BadSignature, TypeError, ValueError):
        raise ReviewConflict('口令核对已过期或无效，请重新读取')
    expected = {'actor': actor.pk, 'target': user.pk, 'mode': mode,
                'receipt': accounts.current_receipt(user)}
    if data != expected:
        raise ReviewConflict('账号设置或口令已变化，请重新核对；本申请未重复执行')


@sensitive_variables()
def password(user, value, confirmation):
    if not isinstance(value, str) or not isinstance(confirmation, str):
        raise ValidationError('请输入并再次确认新口令')
    if not 12 <= len(value) <= 128:
        raise ValidationError('新口令须为12至128位')
    if value != confirmation:
        raise ValidationError('两次输入的新口令不一致')
    if check_password(value, user.password):
        raise ValidationError('新口令不能与当前口令相同')
    accounts.validate_password(value, user, [accounts.MinimumLengthValidator(12),
        accounts.CommonPasswordValidator(), accounts.NumericPasswordValidator(),
        accounts.UserAttributeSimilarityValidator()])
    return value


def context(actor):
    actor = fresh_actor(actor)
    eligible(actor)
    return {'username': actor.username, 'context_token': token(actor, actor, 'self'),
            'expires_seconds': 600, 'rules': RULES, 'notice': NOTICE}


def reset_preview(actor, user_id, data):
    actor = fresh_actor(actor, administrator=True)
    if not isinstance(data, dict) or set(data) != {'receipt'}:
        raise ValidationError('请从当前账号详情核对重设对象')
    user = User.objects.get(pk=user_id)
    eligible(user)
    if actor.pk == user.pk:
        raise ValidationError('本人请使用修改口令，并验证当前口令')
    if data['receipt'] != accounts.current_receipt(user):
        raise ReviewConflict('账号详情已变化，请重新读取')
    p = accounts.profile(user)
    return {'target': {k: p[k] for k in ('id', 'username', 'display_name', 'is_active',
                         'role_label', 'revision', 'session_epoch', 'has_password')},
            'owned_models': AnalysisModel.objects.filter(owner=user.username).count(),
            'owned_topics': Topic.objects.filter(owner=user.username).count(),
            'preview_token': token(actor, user, 'admin'), 'expires_seconds': 600,
            'rules': RULES, 'notice': NOTICE, 'permissions_unchanged': True}


@sensitive_variables()
def apply(actor, user, value, action, why):
    before = accounts.profile(user)
    user.set_password(value)
    user.save(update_fields=['password'])
    state, _ = AccountAccessState.objects.get_or_create(user=user)
    # A credential change advances the login generation, not the permission
    # configuration revision. Existing file-read grants bind that revision.
    state.session_epoch += 1
    state.updated_by = actor.username
    state.save(update_fields=['session_epoch', 'updated_by', 'updated_at'])
    after = accounts.profile(user)
    AuditEvent.objects.create(action=action, actor=actor.username, object_type='UserAccess',
        object_id=str(user.pk), detail={'before': before, 'after': after, 'reason': why,
            'sessions_invalidated': True, 'credential_changed': True,
            'permissions_changed': False, 'business_facts_changed': False})
    return {'username': user.username, 'revision': state.revision,
            'session_epoch': state.session_epoch, 'notice': NOTICE}


@transaction.atomic
@sensitive_variables()
def change(actor, data):
    if not isinstance(data, dict) or set(data) != {'context_token', 'current_password', 'password', 'confirmation'}:
        raise ValidationError('本人修改须核对当前口令和两次新口令')
    lock()
    actor = fresh_actor(actor)
    user = User.objects.select_for_update().get(pk=actor.pk)
    eligible(user)
    proposal(data['context_token'], actor, user, 'self')
    old = data['current_password']
    if not isinstance(old, str) or not 1 <= len(old) <= 128 or not check_password(old, user.password):
        raise ValidationError('当前口令不正确，未保存')
    value = password(user, data['password'], data['confirmation'])
    result = apply(actor, user, value, 'account.password_change', '本人验证当前口令后修改登录口令')
    return {**result, 'signed_out': True}


@transaction.atomic
@sensitive_variables()
def reset(actor, user_id, data):
    lock()
    actor = fresh_actor(actor, administrator=True)
    if not isinstance(data, dict) or set(data) != {'preview_token', 'password', 'confirmation', 'reason'}:
        raise ValidationError('请先核对重设对象、两次新口令及重设依据')
    user = User.objects.select_for_update().get(pk=user_id)
    eligible(user)
    if actor.pk == user.pk:
        raise ValidationError('本人请使用修改口令，并验证当前口令')
    proposal(data['preview_token'], actor, user, 'admin')
    why = accounts.reason(data['reason'])
    value = password(user, data['password'], data['confirmation'])
    if value in why:
        raise ValidationError('重设依据应描述处理原因，不能包含新口令')
    return apply(actor, user, value, 'account.password_reset', why)
