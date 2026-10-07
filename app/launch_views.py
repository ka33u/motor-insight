"""Source-bound pre-start review for the three planning roles."""
import hashlib
import json
from pathlib import Path
from django.core import signing
from django.db import transaction
from django.http import HttpResponse
from . import launch as engine, launch_data as data, spc_data, access
from .launch_contract import signature
from .launch_schema import DATASETS
from .joint_schedule_views import export_document as trial_document
from .models import Record, AuditEvent
from .views import api, reply, require
from .quality_views import csv_reply
from .import_review import ReviewConflict

SALT = 'motor.launch.review.v1'
MAX_AGE = 600


def params(request, allowed=()):
    if set(request.GET)-set(allowed) or any(len(request.GET.getlist(k)) != 1 for k in request.GET):
        raise ValueError('投产条件范围字段无效或重复')


def account(user):
    for ds in (*DATASETS, 'joint_studies', 'skills'):
        require(access.allowed(user, ds), '当前岗位不能读取人员试排和投产依据')
    return spc_data.account(user)


def stamp(d, user):
    return dict(key=d['result']['study']['id'], policy=d['result']['policy'], source_hash=d['source_hash'], rule_hash=d['rule_hash'], result_hash=signature(d['result']),
                account=account(user), view_hash=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())


def context(request, key, required=False):
    account(request.user)
    d = data.load(key, request.GET.get('policy', 'due'))
    value = stamp(d, request.user)
    given = request.GET.get('receipt')
    if required and not given:
        raise ValueError('请先读取当前基线核对，再查看明细、来源或导出')
    if given:
        if len(given) > 4096:
            raise ValueError('基线凭据过长')
        try:
            actual = signing.loads(given, salt=SALT, max_age=MAX_AGE)
        except signing.BadSignature:
            raise ReviewConflict('基线凭据无效或过期，请重新读取')
        if actual != value:
            raise ReviewConflict('基线、工装、文件、质量条件、试排、规则或账号已变化，请重新读取')
    d.update(stamp=value, receipt=given or signing.dumps(value, salt=SALT, compress=True))
    return d


def finish(request, d):
    if stamp(d, request.user) != d['stamp'] or engine.rule_hash() != d['rule_hash']:
        raise ReviewConflict('读取期间基线依据或权限变化，请重新读取')


def response(value):
    result = reply(value)
    result['Cache-Control'] = 'no-store'
    return result


@api()
@transaction.atomic
def studies(request):
    from .finite_schedule import POLICIES
    params(request)
    account(request.user)
    rows = list(spc_data.queryset('launch_studies').order_by('business_key')[:1001])
    if len(rows) > 1000:
        raise ValueError('基线目录超过1000项')
    return response(dict(rows=[r.values for r in rows], policies=POLICIES, notice=engine.NOTICE, synthetic=True))


@api()
@transaction.atomic
def board(request, key):
    params(request, ('policy', 'receipt'))
    d = context(request, key)
    finish(request, d)
    return response(dict(**d['result'], receipt=d['receipt'], source_hash=d['source_hash'], rule_hash=d['rule_hash'], source_count=len(d['sources']), receipt_seconds=MAX_AGE, synthetic=True))


@api()
@transaction.atomic
def sources(request, key):
    params(request, ('policy', 'receipt', 'page'))
    value = request.GET.get('page', '1')
    if not value.isascii() or not value.isdecimal() or not 1 <= int(value) <= 10000:
        raise ValueError('来源页码须为1至10000整数')
    page = int(value)
    d = context(request, key, True)
    finish(request, d)
    return response(dict(rows=d['sources'][(page-1)*40:page*40], total=len(d['sources']), page=page, size=40, receipt=d['receipt'], can_download_original=access.can_import(request.user)))


@api()
@transaction.atomic
def detail(request, key, task_id):
    params(request, ('policy', 'receipt'))
    d = context(request, key, True)
    row = next((r for r in d['result']['tasks'] if r['id'] == task_id), None)
    if row is None:
        raise Record.DoesNotExist()
    keys = {('launch_studies', key), ('schedule_tasks', task_id), ('routes', row['route_id']),
            ('work_orders', row['work_order_id']), ('order_lines', row['order_line_id'])}
    if row['resource_id']:
        keys.add(('production_resources', row['resource_id']))
    evidence_ids = {v for gate in row['gates'] for v in gate['evidence_ids']}
    keys.update(('launch_requirements', gate['requirement_id']) for gate in row['gates'])
    for ds, records in d['tables'].items():
        for record in records:
            if record['id'] in evidence_ids:
                keys.add((ds, record['id']))
                if record.get('tool_id'): keys.add(('tools', record['tool_id']))
    finish(request, d)
    return response(dict(row=row, sources=[s for s in d['sources'] if (s['dataset'], s['key']) in keys], receipt=d['receipt'], can_download_original=access.can_import(request.user),
                         notice='本任务直接登记依据；同一工装的跨任务预占、累计次数及上游阻断须结合整方案来源和完整导出核对。'))



@api()
@transaction.atomic
def export(request, key):
    params(request, ('policy', 'receipt', 'format'))
    fmt = request.GET.get('format', 'csv')
    if fmt not in ('csv', 'json'):
        raise ValueError('支持CSV或JSON')
    d = context(request, key, True)
    r = d['result']
    name = 'launch-review-'+signature(key)[:16]
    if fmt == 'json':
        document = dict(format='motor-launch-review-v1', synthetic=True, result=r, launch_inputs=dict(study=r['study'], **d['tables']), references=d['references'],
                        order_baseline=dict(result=d['parent']['result'], inputs=d['parent']['tables'], references=d['parent']['references']), trial=trial_document(d['parent']['parent']), sources=d['sources'], source_hash=d['source_hash'], rule_hash=d['rule_hash'], result_hash=signature(r), notice=engine.NOTICE)
        file = HttpResponse(json.dumps(document, ensure_ascii=False, indent=2, allow_nan=False)+'\n', content_type='application/json; charset=utf-8')
        file['Content-Disposition'] = 'attachment; filename="'+name+'.json"'
    else:
        rows = [['投产条件基线核对', key, r['study']['name']], ['状态', r['state'], '策略', r['policy_name']], ['边界', engine.NOTICE], ['暂停原因', '；'.join(r['issues'])],
                 ['来源摘要', d['source_hash'], '规则摘要', d['rule_hash']], ['CSV包含投产条件输入、结果和来源；完整人机物料试排假设见JSON。']]
        for label, records in [('基线定义', [r['study']]), *d['tables'].items(), *[(k, r[k]) for k in ('tasks', 'jobs', 'tools')], ('全部来源', d['sources'])]:
            rows.append([label])
            if records:
                fields = list(dict.fromkeys(k for row in records for k in row))
                rows.append(fields)
                for row in records:
                    rows.append([json.dumps(row.get(f), ensure_ascii=False, allow_nan=False) if isinstance(row.get(f), (dict, list)) else row.get(f) for f in fields])
            else:
                rows.append(['无记录；暂停时不代表已完成或零需求'])
        rows = [["'"+v if isinstance(v, str) and v.lstrip().startswith(('=', '+', '-', '@')) and not v.startswith("'") else v for v in row] for row in rows]
        file = csv_reply(rows, name)
    finish(request, d)
    AuditEvent.objects.create(action='launch.export', actor=request.user.username, object_type='LaunchStudy', object_id=key,
                              detail=dict(format=fmt, policy=r['policy'], state=r['state'], source_hash=d['source_hash'], rule_hash=d['rule_hash'],
                                          file_sha256=hashlib.sha256(file.content).hexdigest(), business_facts_changed=False))
    file['Cache-Control'] = 'no-store'
    return file
