"""Read-only, account-bound scope transfers between visible BI topics."""
import copy
import hashlib
from pathlib import Path
from django.contrib.auth import get_user_model
from django.core import signing
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from . import access, spc_data, topic_workspace as ws, topic_linkage, bi_scope
from .analysis_engine import validate_definition
from .import_review import ReviewConflict

PREVIEW_AGE = 600
JOURNEY_AGE = 7200
MODES = {'inherit': '完整继承', 'objects': '保留当前对象，重选日期与对照', 'new': '开始新范围'}
NOTICE = '仅传递已应用条件，各卡继续使用自身模型和当前已导入数据。日期选择业务对象，不重放历史状态，也不证明不同专题间的因果关系。'


def rules():
    names = ('topic_journey.py', 'topic_journey_views.py', 'topic_workspace.py',
             'topic_linkage.py', 'bi_scope.py', 'analysis_engine.py', 'access.py')
    return ws.digest({n: hashlib.sha256(Path(__file__).with_name(n).read_bytes()).hexdigest() for n in names})


def exact(value, keys):
    if not isinstance(value, dict) or set(value) != set(keys):
        raise ValidationError('探索参数不完整或包含未知字段')


def fresh(user):
    current = get_user_model().objects.get(pk=user.pk)
    if not access.role(current):
        raise PermissionDenied('账号或岗位权限已变化，请重新登录')
    return current


def defaults():
    return dict(scope={}, reference_scope=None, primary_label='当前范围', reference_label='对照范围')


def transformed(config, mode):
    if mode == 'inherit':
        return copy.deepcopy(config)
    result = defaults()
    if mode == 'objects':
        result['scope'] = {k: v for k, v in config['scope'].items() if k in ('family', 'customer_id')}
        if config.get('links'):
            result['links'] = copy.deepcopy(config['links'])
    return result


def inspect_card(user, card, config):
    if not card['available']:
        return dict(slot=card['slot'], name='当前不可访问', date_label='不可核对', ready=False, reasons=['当前不可访问'])
    errors = []
    for side, scope in (('当前', config['scope']), ('对照', config['reference_scope'])):
        for key in scope or {}:
            capability = 'date' if key in ('from', 'to') else key
            if not card['contract'].get(capability):
                errors.append(side + '范围不支持' + bi_scope.LABELS[key])
    try:
        model, _ = topic_linkage.effective(user, card['model'], config.get('links'))
        validate_definition(user, model['dataset'], model['definition'])
    except (ValidationError, ValueError, KeyError, TypeError) as error:
        errors.append('; '.join(error.messages) if isinstance(error, ValidationError) else str(error))
    return dict(slot=card['slot'], name=card['model']['name'], date_label=card['contract']['date_label'],
                ready=not errors, reasons=errors)


def date_roles(ctx):
    return sorted({c['contract']['date_label'] for c in ctx['cards'] if c['available'] and c['contract']['date']})


def prepare(user, source_id, data):
    exact(data, ('target_id', 'context_token', 'config'))
    if type(data['target_id']) is not int or data['target_id'] <= 0 or data['target_id'] == source_id:
        raise ValidationError('请选择另一个可访问的专题')
    source, target = ws.context(user, source_id), ws.context(user, data['target_id'])
    ws.require_context(source, data['context_token'])
    config = ws.config(data['config'])
    options = []
    has_dates = any(k in (s or {}) for s in (config['scope'], config['reference_scope']) for k in ('from', 'to'))
    for mode, label in MODES.items():
        proposed = transformed(config, mode)
        cards = [inspect_card(user, c, proposed) for c in target['cards']]
        reasons = []
        if mode != 'new':
            if not cards:
                reasons.append('目标专题尚无分析卡')
            if any(not c['ready'] for c in cards):
                reasons.append('目标至少一张卡无法完整应用条件，请核对逐卡说明')
        if mode == 'inherit' and has_dates:
            if (not source['cards'] or any(not c['available'] or not c['contract']['date'] for c in source['cards'])
                    or date_roles(source) != date_roles(target)):
                reasons.append('来源与目标日期角色不同或不可核对，不能直接沿用日期区间')
        if mode == 'objects' and not proposed['scope'] and not proposed.get('links'):
            reasons.append('当前没有可保留的产品族、客户或直接身份联动条件')
        removed = []
        if mode == 'objects':
            removed = ['当前范围的开始与结束日期', '整个对照范围', '两侧自定义名称（恢复默认）']
        if mode == 'new':
            removed = ['当前范围', '对照范围', '全部身份联动条件', '两侧自定义名称（恢复默认）']
        options.append(dict(mode=mode, label=label, allowed=not reasons, reasons=reasons,
                            config=proposed, cards=cards, removed=removed))
    result = dict(source=source['topic'], target=target['topic'], source_config=config,
                  source_date_roles=date_roles(source), target_date_roles=date_roles(target),
                  options=options, notice=NOTICE,
                  return_notice='返回原专题的临时分析，恢复跳转时已应用范围；个人视角与工作页布局不随跳转保存。')
    # Bind scope contracts as well as native model/metric version bindings. Never store business values.
    stamp = ws.digest(dict(account=spc_data.account(user), rules=rules(), source=source, target=target, result=result))
    return result, stamp, source, target


def read_receipt(value, salt, age):
    if not isinstance(value, str) or not 1 <= len(value) <= 12000:
        raise ValidationError('探索凭据无效')
    try:
        return signing.loads(value, salt=salt, max_age=age)
    except signing.BadSignature:
        raise ReviewConflict('探索凭据失效或已过期，请回到专题重新预览')


@transaction.atomic
def preview(user, source_id, data):
    user = fresh(user)
    result, stamp, _, _ = prepare(user, source_id, data)
    return dict(**result, receipt=signing.dumps(dict(stamp=stamp), salt='motor.journey.preview.v1'), expires_seconds=PREVIEW_AGE)


@transaction.atomic
def open_journey(user, source_id, data):
    exact(data, ('target_id', 'context_token', 'config', 'mode', 'receipt'))
    if not isinstance(data['mode'], str) or data['mode'] not in MODES:
        raise ValidationError('探索方式无效')
    user = fresh(user)
    original = {k: data[k] for k in ('target_id', 'context_token', 'config')}
    result, stamp, _, _ = prepare(user, source_id, original)
    if read_receipt(data['receipt'], 'motor.journey.preview.v1', PREVIEW_AGE) != dict(stamp=stamp):
        raise ReviewConflict('条件、定义或访问权限已变化，请重新预览')
    option = next(o for o in result['options'] if o['mode'] == data['mode'])
    if not option['allowed']:
        raise ValidationError('; '.join(option['reasons']))
    receipt = signing.dumps(dict(source_id=source_id, original=original, mode=data['mode'], stamp=stamp), salt='motor.journey.open.v1', compress=True)
    return dict(topic_id=data['target_id'], receipt=receipt, expires_seconds=JOURNEY_AGE, notice=NOTICE)


@transaction.atomic
def resolve(user, topic_id, data):
    exact(data, ('receipt', 'direction'))
    if data['direction'] not in ('forward', 'return'):
        raise ValidationError('探索方向无效')
    payload = read_receipt(data['receipt'], 'motor.journey.open.v1', JOURNEY_AGE)
    exact(payload, ('source_id', 'original', 'mode', 'stamp'))
    expected = payload['source_id'] if data['direction'] == 'return' else payload['original']['target_id']
    if topic_id != expected:
        raise ValidationError('当前专题与探索路径不一致')
    user = fresh(user)
    result, stamp, source, target = prepare(user, payload['source_id'], payload['original'])
    if stamp != payload['stamp']:
        raise ReviewConflict('探索路径中的定义、条件或权限已变化，请重新预览')
    option = next(o for o in result['options'] if o['mode'] == payload['mode'])
    if not option['allowed']:
        raise ReviewConflict('当前条件不再支持此探索方式')
    back = data['direction'] == 'return'
    return dict(topic_id=topic_id, config=result['source_config'] if back else option['config'],
                context_token=(source if back else target)['context_token'], source=result['source'],
                target=result['target'], mode=payload['mode'], mode_label=option['label'],
                direction=data['direction'], notice=NOTICE, return_notice=result['return_notice'])
