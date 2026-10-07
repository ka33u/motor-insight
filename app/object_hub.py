"""Typed identifier search and explicit, permission-scoped Excel references."""
import hashlib
import math
from pathlib import Path
from django.contrib.auth import get_user_model
from django.core import signing
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Q, Count, Case, When, Value, IntegerField
from . import access, analytics, spc_data, topic_workspace as ws
from .models import Record
from .schema import SCHEMAS
from .import_review import ReviewConflict

COMMON = {
    'orders': ('customer_po',), 'order_lines': (), 'work_orders': (),
    'products': ('model',), 'units': (), 'batches': ('container',),
    'wip_lots': ('container',), 'materials': ('name', 'spec'),
    'customers': ('name',), 'suppliers': ('name',), 'equipment': ('name', 'model'),
    'tools': ('name',), 'production_resources': ('station',), 'metrology_instruments': ('name',),
}
SIZE = 25
AGE = 600
NOTICE = '查找已导入的合成Excel记录，业务编号按原文本保留。同号不同表是不同对象；结果数量是记录数，不是产量或去重业务总量。'
RELATION_NOTE = '仅按已声明引用字段与完整业务编号相等连接，一行多个字段命中仍只列一次。不推断名称关系、多跳路径或实际材料使用；版本表包含已导入的历史、草稿和未来登记，不能据此判断当前批准或有效状态。'


def exact(value, keys):
    if not isinstance(value, dict) or set(value) != set(keys):
        raise ValidationError('对象查询字段不完整或包含未知项')


def fresh(user):
    user = get_user_model().objects.get(pk=user.pk)
    if not access.role(user):
        raise PermissionDenied('账号或岗位已变化，请重新登录')
    return user


def positive(value, label):
    if type(value) is not int or not 1 <= value <= 1000000:
        raise ValidationError(label+'须为有效正整数')
    return value


def permitted(user):
    return {key: access.permitted_fields(user, key) for key in SCHEMAS if access.allowed(user, key)}


def catalog(fields):
    return [dict(key=key, label=SCHEMAS[key]['label'], search_fields=[dict(name=f['name'], label=f['label']) for f in fields[key] if f['name'] in COMMON[key]]) for key in COMMON if key in fields]


def rules():
    return ws.digest({name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
                      for name in ('object_hub.py', 'object_hub_views.py', 'access.py', 'spc_data.py')})


def stamp(user, fields, operation, selection):
    return ws.digest(dict(account=spc_data.account(user), schemas=fields, rules=rules(),
                          revision=analytics.revision(), operation=operation, selection=selection))


def receipt(value):
    return signing.dumps(dict(stamp=value), salt='motor.object-hub.v1')


def check_receipt(token, expected):
    if not isinstance(token, str) or not 1 <= len(token) <= 1000:
        raise ValidationError('请提供本次对象查询凭据')
    try:
        value = signing.loads(token, salt='motor.object-hub.v1', max_age=AGE)
    except signing.BadSignature:
        raise ReviewConflict('对象查询凭据已失效，请重新读取')
    if value != dict(stamp=expected):
        raise ReviewConflict('对象、导入资料、字段或访问权限已变化，请重新读取')


def checked_source(record):
    return spc_data.source(record)


def brief(record, fields, query='', mode='contains'):
    source = checked_source(record)
    values = access_values(record, fields)
    names = COMMON.get(record.dataset, ())
    labels = {f['name']: f['label'] for f in fields[record.dataset]}
    description = [dict(field=name, label=labels[name], value=values[name]) for name in names if name in values and values[name] not in (None, '')]
    matched = []
    if query:
        if record.business_key == query:
            matched.append('编码精确匹配')
        elif record.business_key.lower().startswith(query.lower()):
            matched.append('编码前缀匹配')
        elif query.lower() in record.business_key.lower():
            matched.append('编码包含匹配')
        if mode == 'contains':
            matched += [d['label']+'包含匹配' for d in description if query.lower() in str(d['value']).lower()]
    return dict(record_id=record.pk, dataset=record.dataset, dataset_label=SCHEMAS[record.dataset]['label'],
                key=record.business_key, revision=record.revision, description=description,
                matched=matched, source=source)


def access_values(record, fields):
    return {f['name']: record.values.get(f['name']) for f in fields[record.dataset]}


def rows_for(fields):
    return Record.objects.filter(dataset__in=fields).select_related('source_row__batch')


def configuration(data, fields):
    exact(data, ('q', 'dataset', 'mode'))
    if not isinstance(data['q'], str) or len(data['q']) > 150 or any(ord(c) < 32 for c in data['q']):
        raise ValidationError('搜索内容最多150字，不能包含控制字符')
    if not isinstance(data['dataset'], str) or data['dataset'] and data['dataset'] not in {c['key'] for c in catalog(fields)}:
        raise ValidationError('此对象类型不可查')
    if data['mode'] not in ('exact', 'prefix', 'contains'):
        raise ValidationError('匹配方式不可用')
    return dict(q=data['q'].strip(), dataset=data['dataset'], mode=data['mode'])


@transaction.atomic
def search(user, data):
    exact(data, ('filters', 'page', 'receipt'))
    user = fresh(user); fields = permitted(user)
    conf = configuration(data['filters'], fields); page = positive(data['page'], '页码')
    token = stamp(user, fields, 'search', conf)
    if page > 1 or data['receipt'] is not None:
        check_receipt(data['receipt'], token)
    query = conf['q']; condition = Q(pk__in=[])
    for ds in catalog(fields):
        lookup = {'exact': 'exact', 'prefix': 'istartswith', 'contains': 'icontains'}[conf['mode']]
        match = Q(**{'business_key__'+lookup: query})
        if conf['mode'] == 'contains':
            for field in ds['search_fields']:
                match |= Q(**{f'values__{field["name"]}__icontains': query})
        condition |= Q(dataset=ds['key']) & match
    found = rows_for(fields).filter(condition) if query else rows_for(fields).none()
    counts = {r['dataset']: r['n'] for r in found.values('dataset').annotate(n=Count('id'))}
    selected = found.filter(dataset=conf['dataset']) if conf['dataset'] else found
    total = counts.get(conf['dataset'], 0) if conf['dataset'] else sum(counts.values())
    pages = max(1, math.ceil(total/SIZE))
    if page > pages:
        raise ValidationError('结果页码超出范围，请回到第一页')
    selected = selected.annotate(rank=Case(When(business_key=query, then=Value(0)), When(business_key__istartswith=query, then=Value(1)), default=Value(2), output_field=IntegerField())).order_by('rank', 'dataset', 'business_key', 'pk')
    return dict(filters=conf, rows=[brief(r, fields, query, conf['mode']) for r in selected[(page-1)*SIZE:page*SIZE]],
                types=catalog(fields), counts=counts, total=total, total_all=sum(counts.values()),
                page=page, pages=pages, size=SIZE, receipt=receipt(token), notice=NOTICE,
                as_of=analytics.AS_OF, time_note='检索所有已导入登记，不按业务截止筛除未来、草稿或历史版本。状态解释请进入对应业务工作台。')


def reference_groups(fields, dataset):
    return {key: [f for f in columns if f.get('reference') == dataset] for key, columns in fields.items()
            if any(f.get('reference') == dataset for f in columns)}


def references_query(fields, dataset, columns, key):
    condition = Q(pk__in=[])
    for field in columns:
        condition |= Q(**{f'values__{field["name"]}': key})
    return rows_for(fields).filter(dataset=dataset).filter(condition)


def root(user, record_id):
    user = fresh(user); fields = permitted(user)
    record = rows_for(fields).get(pk=record_id)
    checked_source(record)
    token = stamp(user, fields, 'detail', dict(record_id=record.pk, source=checked_source(record)))
    return user, fields, record, token


@transaction.atomic
def detail(user, record_id):
    user, fields, record, token = root(user, record_id)
    values = access_values(record, fields); outgoing = []
    for field in fields[record.dataset]:
        ds, key = field.get('reference'), values.get(field['name'])
        if not ds or not key:
            continue
        item = dict(field=field['name'], label=field['label'], key=key)
        if ds not in fields:
            item.update(state='restricted', dataset_label='目标当前不可访问', record_id=None)
        else:
            target = rows_for(fields).filter(dataset=ds, business_key=key).first()
            if target:
                checked_source(target)
            item.update(state='found' if target else 'missing', dataset=ds, dataset_label=SCHEMAS[ds]['label'], record_id=target.pk if target else None)
        outgoing.append(item)
    inbound = []
    for ds, columns in reference_groups(fields, record.dataset).items():
        count = references_query(fields, ds, columns, record.business_key).count()
        if count:
            inbound.append(dict(dataset=ds, label=SCHEMAS[ds]['label'], count=count,
                                fields=[dict(name=f['name'],label=f['label']) for f in columns]))
    return dict(object=brief(record, fields), fields=[dict(name=f['name'], label=f['label'], type=f['type'], value=values[f['name']]) for f in fields[record.dataset]],
                outgoing=outgoing, inbound=inbound, receipt=receipt(token), notice=NOTICE,
                relation_note=RELATION_NOTE, can_download_excel=access.can_import(user), as_of=analytics.AS_OF)


@transaction.atomic
def related(user, record_id, data):
    exact(data, ('dataset', 'page', 'receipt'))
    user, fields, record, token = root(user, record_id)
    check_receipt(data['receipt'], token)
    groups = reference_groups(fields, record.dataset)
    if not isinstance(data['dataset'], str) or data['dataset'] not in groups:
        raise ValidationError('此表没有当前可访问的直接引用关系')
    ds = data['dataset']; columns = groups[ds]; page = positive(data['page'], '页码')
    found = references_query(fields, ds, columns, record.business_key).order_by('business_key', 'pk')
    count = found.count(); pages = max(1, math.ceil(count/SIZE))
    if page > pages:
        raise ValidationError('引用记录页码超出范围')
    rows = []
    for row in found[(page-1)*SIZE:page*SIZE]:
        item = brief(row, fields)
        item['matched_fields'] = [dict(name=f['name'], label=f['label']) for f in columns if row.values.get(f['name']) == record.business_key]
        rows.append(item)
    return dict(root_id=record.pk, dataset=ds, dataset_label=SCHEMAS[ds]['label'], total=count,
                rows=rows, page=page, pages=pages, size=SIZE, notice=RELATION_NOTE)
