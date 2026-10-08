"""Typed local trial destinations; never persist a receipt or a calculation result."""
import importlib
import re
from django.core.exceptions import PermissionDenied, ValidationError
from .models import Record
from . import spc_data

FAMILIES = {
    'finite': ('finite-schedule', 'schedule_studies', '有限资源试排', 'finite_schedule_views'),
    'crew': ('crew-schedule', 'crew_studies', '人机联立试排', 'crew_schedule_views'),
    'joint': ('joint-schedule', 'joint_studies', '物料人机联立', 'joint_schedule_views'),
    'baseline': ('order-baselines', 'order_baselines', '订单与BOM基线', 'order_baseline_views'),
}
MODES = {'due': '应完成时间优先', 'priority': '批次优先级优先', 'compare': '两种派序对照',
         'trial-due': '冻结BOM试排 · 应完成时间优先', 'trial-priority': '冻结BOM试排 · 批次优先级优先'}
NOTICE = '只保存本库方案入口与阅读方式；打开时读取当前资料，未保存计算结果、临时凭据或局部筛选。可打开不表示方案可排或已批准。'


def modes(family):
    return ('due', 'priority', 'compare') if family == 'joint' else ('due', 'priority', 'trial-due', 'trial-priority') if family == 'baseline' else ('due', 'priority')


def parse(value):
    if not isinstance(value, str) or not re.fullmatch(r'[a-z]+:[1-9][0-9]{0,14}:[a-z-]+', value):
        raise ValidationError('方案收藏标识无效')
    family, record, mode = value.split(':')
    if family not in FAMILIES or mode not in modes(family):
        raise ValidationError('方案类型与阅读方式不匹配')
    return family, int(record), mode


def account(user, family):
    # Use the same dataset permission gate as the destination, without running a trial.
    importlib.import_module('app.'+FAMILIES[family][3]).account(user)


def resolve(user, target):
    family, key, mode = parse(target); account(user, family)
    route, dataset, label, _ = FAMILIES[family]
    record = Record.objects.select_related('source_row__batch').get(pk=key, dataset=dataset)
    spc_data.source(record)
    v = record.values
    if v.get('id') != record.business_key or not isinstance(v.get('name'), str) or not v['name'].strip() or type(v.get('version')) not in (str, int):
        raise ValidationError('方案登记身份、名称或声明版本待核对')
    params = dict(study=record.business_key)
    if mode == 'compare': params['view'] = 'compare'
    elif mode.startswith('trial-'): params.update(view='trial', policy=mode[6:])
    else: params['policy'] = mode
    return dict(kind='trial', target=target, label=f"{record.business_key} · {v['name']} · {label} · {MODES[mode]}",
                state='ready', note=f"方案声明版本 {v['version']}；{NOTICE}", version=record.revision, route=route, params=params)


def keys(user):
    out=[]; total=0
    for family, (_, dataset, _, _) in FAMILIES.items():
        try: account(user, family)
        except PermissionDenied: continue
        rows=Record.objects.filter(dataset=dataset).order_by('pk')
        total += rows.count()
        if total > 2000: raise ValidationError('当前可见方案超过2000份，请先整理目录；未截断选择')
        out.extend(f'{family}:{key}:{mode}' for key in rows.values_list('pk', flat=True) for mode in modes(family))
    return out


def lookup(user, data):
    if not isinstance(data, dict) or set(data) != {'route', 'study', 'policy', 'view'}:
        raise ValidationError('方案入口字段不完整或包含未知字段')
    family=next((k for k,v in FAMILIES.items() if v[0] == data['route']), None)
    if family is None: raise ValidationError('不是受支持的方案入口')
    account(user, family)
    study=data['study']; policy=data['policy']; view=data['view']
    if not isinstance(study, str) or not 1 <= len(study) <= 150 or any(ord(c)<32 or ord(c)==127 for c in study):
        raise ValidationError('请在页面中明确选择方案')
    if policy not in ('due', 'priority') or view not in ('', 'compare', 'trial'):
        raise ValidationError('方案策略或阅读方式无效')
    mode='compare' if family=='joint' and view=='compare' else 'trial-'+policy if family=='baseline' and view=='trial' else policy if view=='' else None
    if mode is None: raise ValidationError('当前方案不支持此阅读方式')
    record=Record.objects.get(dataset=FAMILIES[family][1], business_key=study)
    return resolve(user, f'{family}:{record.pk}:{mode}')
