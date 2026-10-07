"""Role-checked material/people/resource trial, source receipts and full exports."""
import hashlib
import json
from pathlib import Path
from django.core import signing
from django.db import transaction
from django.http import HttpResponse
from . import joint_schedule as engine, joint_schedule_data as data, finite_schedule, spc_data, access
from .joint_schedule_schema import DATASETS
from .models import Record, AuditEvent
from .views import api, reply, require
from .import_review import ReviewConflict
from .quality_views import csv_reply

SALT = 'motor.material-crew-resource.trial.v1'
MAX_AGE = 600


def params(request, allowed=()):
    if set(request.GET)-set(allowed) or any(len(request.GET.getlist(k)) != 1 for k in request.GET):
        raise ValueError('物料联立试排范围字段无效或重复')


def account(user):
    for ds in (*DATASETS, 'crew_studies', 'skills'):
        require(access.allowed(user, ds), '当前岗位不能读取物料、人员及设备联立试排')
    return spc_data.account(user)


def stamp(d, user):
    return dict(study=d['result']['study']['id'], policy=d['result']['policy'], source_hash=d['source_hash'], rule_hash=d['rule_hash'],
                result_hash=finite_schedule.digest(d['result']), account=account(user), view_hash=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())


def context(request, key, required=False):
    account(request.user)
    d = data.load(key, request.GET.get('policy', 'due'))
    value = stamp(d, request.user)
    given = request.GET.get('receipt')
    if required and not given:
        raise ValueError('请先读取当前物料联立试排，再查看明细、来源或导出')
    if given:
        if len(given) > 4096:
            raise ValueError('试排凭据过长')
        try:
            actual = signing.loads(given, salt=SALT, max_age=MAX_AGE)
        except signing.BadSignature:
            raise ReviewConflict('试排凭据无效或过期，请重新计算')
        if actual != value:
            raise ReviewConflict('物料、人机、BOM、策略、规则或账号已变化，请重新计算')
    d.update(stamp=value, receipt=given or signing.dumps(value, salt=SALT, compress=True))
    return d


def finish(request, d):
    if stamp(d, request.user) != d['stamp'] or engine.rule_hash() != d['rule_hash']:
        raise ReviewConflict('读取期间依据或权限变化，请重新计算')


def response(value):
    result = reply(value)
    result['Cache-Control'] = 'no-store'
    return result


@api()
@transaction.atomic
def studies(request):
    params(request)
    account(request.user)
    rows = list(spc_data.queryset('joint_studies').order_by('business_key')[:1001])
    if len(rows) > 1000:
        raise ValueError('物料联立目录超过1000项')
    return response(dict(rows=[r.values for r in rows], policies=finite_schedule.POLICIES, notice=engine.NOTICE, synthetic=True))


@api()
@transaction.atomic
def board(request, key):
    params(request, ('policy', 'receipt'))
    d = context(request, key)
    finish(request, d)
    return response(dict(**d['result'], receipt=d['receipt'], receipt_seconds=MAX_AGE, source_hash=d['source_hash'], rule_hash=d['rule_hash'], source_count=len(d['sources']), synthetic=True))


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
    row = next((t for t in d['result']['tasks'] if t['id'] == task_id), None)
    if row is None:
        raise Record.DoesNotExist()
    demands = [n for n in d['result']['demands'] if n['id'] in row['demand_ids']]
    allocations = [a for a in d['result']['reservations'] if a['demand_id'] in row['demand_ids']]
    materials = {n['material_id'] for n in demands}
    direct = {('joint_studies', key), ('crew_studies', d['result']['crew_study']['id']), ('schedule_studies', d['result']['resource_study']['id']),
              ('schedule_tasks', task_id), ('schedule_jobs', row['job_id']), ('products', row['product_id']), ('routes', row['route_id'])}
    direct.update(('schedule_tasks', k) for k in row['predecessors'])
    for n in demands:
        direct.update({('joint_demands', n['id']), ('joint_bindings', n['binding_id']), ('bom', n['bom_id']), ('materials', n['material_id'])})
    direct.update(('joint_supplies', s['id']) for s in d['tables']['joint_supplies'] if s['material_id'] in materials)
    for ds, field in [('production_resources', 'resource_id'), ('employees', 'employee_id'), ('skills', 'skill_id'), ('crew_credentials', 'credential_id'),
                      ('crew_candidates', 'candidate_id'), ('schedule_options', 'option_id'), ('schedule_windows', 'window_id'), ('crew_windows', 'worker_window_id')]:
        if row.get(field):
            direct.add((ds, row[field]))
    finish(request, d)
    return response(dict(row=row, demands=demands, reservations=allocations, sources=[s for s in d['sources'] if (s['dataset'], s['key']) in direct],
                         receipt=d['receipt'], can_download_original=access.can_import(request.user),
                         notice='显示该任务用料、共享候选供给、直接前序与选中人机依据。其他批次会竞争同一供给和人机，请同时核对全方案来源及完整导出。整批用料可能由同工序的其他份号预留。'))


def export_document(d):
    r = d['result']
    return dict(format='motor-material-crew-resource-trial-v1', synthetic=True, result=r,
                material_inputs=dict(study=r['study'], **d['tables']), crew_inputs=dict(study=r['crew_study'], **d['parent']['tables']),
                resource_inputs=dict(study=r['resource_study'], **d['parent']['base']['tables']), references=d['references'], sources=d['sources'],
                source_hash=d['source_hash'], rule_hash=d['rule_hash'], result_hash=finite_schedule.digest(r), notice=engine.NOTICE)


@api()
@transaction.atomic
def export(request, key):
    params(request, ('policy', 'receipt', 'format'))
    fmt = request.GET.get('format', 'csv')
    if fmt not in ('csv', 'json'):
        raise ValueError('支持CSV或JSON')
    d = context(request, key, True)
    doc = export_document(d)
    r = d['result']
    name = 'joint-' + finite_schedule.digest(key)[:16]
    if fmt == 'json':
        file = HttpResponse(json.dumps(doc, ensure_ascii=False, indent=2, allow_nan=False)+'\n', content_type='application/json; charset=utf-8')
        file['Content-Disposition'] = 'attachment; filename="'+name+'.json"'
    else:
        # Long-form sections preserve complete inputs even when calculation is paused.
        rows = [['物料设备人员联立试排', key, r['study']['name']], ['状态', r['state'], '策略', r['policy_name']], ['边界', engine.NOTICE],
                ['暂停原因', '；'.join(r['issues'])], ['来源摘要', d['source_hash'], '规则摘要', d['rule_hash']],
                ['以下分区保留全部假设及结果；数量为物料各自单位，不可将kg与件相加。暂停方案未计算，不代表零需求或零延误。']]

        def section(label, records):
            rows.append([label])
            if not records:
                rows.append(['无记录'])
                return
            fields = list(dict.fromkeys(k for record in records for k in record))
            rows.append(fields)
            for record in records:
                rows.append([json.dumps(record.get(f), ensure_ascii=False, allow_nan=False) if isinstance(record.get(f), (dict, list)) else record.get(f) for f in fields])

        for ds in ('jobs', 'tasks', 'demands', 'reservations', 'lots', 'balances', 'resources', 'workers', 'credentials'):
            section('结果/'+ds, r[ds])
        for group in ('material_inputs', 'crew_inputs', 'resource_inputs', 'references'):
            for ds, records in doc[group].items():
                section(group+'/'+ds, [records] if isinstance(records, dict) else records)
        section('全部来源', d['sources'])
        rows = [["'"+v if isinstance(v, str) and v.lstrip().startswith(('=', '+', '-', '@')) and not v.startswith("'") else v for v in row] for row in rows]
        file = csv_reply(rows, name)
    finish(request, d)
    AuditEvent.objects.create(action='joint_schedule.export', actor=request.user.username, object_type='JointStudy', object_id=key,
                              detail=dict(format=fmt, policy=r['policy'], tasks=len(r['tasks']), input_tasks=len(d['parent']['base']['tables']['schedule_tasks']),
                                          reservations=len(r['reservations']), state=r['state'], source_hash=d['source_hash'], rule_hash=d['rule_hash'],
                                          file_sha256=hashlib.sha256(file.content).hexdigest(), business_facts_changed=False))
    file['Cache-Control'] = 'no-store'
    return file
