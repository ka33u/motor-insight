"""Read-only, role/source-bound conditional baseline BOM trial."""
import csv
import hashlib
import io
import json
from django.contrib.auth import get_user_model
from django.core import signing
from django.db import transaction
from . import baseline_trial as engine, baseline_trial_data as data, finite_schedule as finite, order_baseline_views as baseline_views
from .joint_schedule_views import export_document as current_document
from .views import api, body, reply
from .models import AuditEvent, Record
from .import_review import ReviewConflict

SALT = 'motor.baseline-bom-conditional.v1'
AGE = 600


def request_data(request, extra=(), required=False):
    if request.GET:
        raise ValueError('试算条件须放在JSON正文')
    def unique(pairs):
        value = {}
        for k, v in pairs:
            if k in value:
                raise ValueError('试算请求有重复字段')
            value[k] = v
        return value
    try:
        json.loads(request.body or b'{}', object_pairs_hook=unique)
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise ValueError('试算请求须为JSON')
    value = body(request)
    if set(value)-{'receipt', 'policy', *extra} or (required and 'receipt' not in value):
        raise ValueError('请先读取基线试算，或移除未知字段')
    if value.get('policy', 'due') not in finite.POLICIES:
        raise ValueError('试排策略无效')
    if 'receipt' in value and (not isinstance(value['receipt'], str) or not value['receipt'] or len(value['receipt']) > 4096):
        raise ValueError('试算凭据无效')
    return value


def load(user, key, value):
    user = get_user_model().objects.get(pk=user.pk)
    account = baseline_views.account(user)
    d = data.load(key, value.get('policy', 'due'))
    stamp = dict(key=key, policy=d['result']['policy'], source_hash=d['source_hash'], rule_hash=d['rule_hash'], result_hash=finite.digest(d['result']), account=account)
    receipt = value.get('receipt')
    if receipt:
        try:
            given = signing.loads(receipt, salt=SALT, max_age=AGE)
        except signing.BadSignature:
            raise ReviewConflict('试算凭据无效或过期，请重新读取')
        if given != stamp:
            raise ReviewConflict('基线、领料、订单、人机、策略、规则或账号变化，请重新读取试算')
    return dict(**d, stamp=stamp, receipt=receipt or signing.dumps(stamp, salt=SALT, compress=True))


def finish(d, user):
    if engine.rule_hash() != d['rule_hash'] or baseline_views.account(get_user_model().objects.get(pk=user.pk)) != d['stamp']['account']:
        raise ReviewConflict('读取期间规则或账号变化，请重新读取试算')


def response(value):
    r = reply(value)
    r['Cache-Control'] = 'no-store'
    return r


@api(('POST',))
@transaction.atomic
def board(request, key):
    d = load(request.user, key, request_data(request))
    finish(d, request.user)
    return response(dict(**d['result'], receipt=d['receipt'], receipt_seconds=AGE, source_count=len(d['sources']), source_hash=d['source_hash'], rule_hash=d['rule_hash'], synthetic=True))


@api(('POST',))
@transaction.atomic
def sources(request, key):
    value = request_data(request, ('page',), True)
    page = value.get('page', 1)
    if type(page) is not int or not 1 <= page <= 10000:
        raise ValueError('来源页码须为1至10000整数')
    d = load(request.user, key, value)
    finish(d, request.user)
    return response(dict(rows=d['sources'][(page-1)*40:page*40], total=len(d['sources']), page=page, size=40))


@api(('POST',))
@transaction.atomic
def detail(request, key, task):
    d = load(request.user, key, request_data(request, required=True))
    r = d['result']['trial']
    row = next((r for r in r['tasks'] if r['id'] == task), None) if r else None
    if row is None:
        raise Record.DoesNotExist()
    demands = [n for n in r['demands'] if n['id'] in row['demand_ids']]
    # Whole-plan sources include competing jobs, all issue-history rows and
    # missing references. Direct requirements preserve their snapshot row IDs.
    finish(d, request.user)
    return response(dict(task=row, demands=demands, reservations=[a for a in r['reservations'] if a['demand_id'] in row['demand_ids']], sources=d['sources'],
                         notice='需求来自冻结快照推导；整批用料可由同工序其他份号触发。来源包含全方案竞争及登记历史，不能只看选中任务证明可执行。'))


def document(d):
    original = d['original']
    return dict(format='motor-baseline-bom-conditional-v1', synthetic=True, result=d['result'],
                baseline_inputs=dict(study=original['result']['study'], **original['tables']), baseline_references=original['references'],
                planning_references=d['planning_references'], baseline_review=original['result'], current_trial=current_document(original['parent']), registered_issue_history=d['issue_history'],
                sources=d['sources'], source_hash=d['source_hash'], rule_hash=d['rule_hash'], result_hash=finite.digest(d['result']), notice=engine.NOTICE)


@api(('POST',))
@transaction.atomic
def export(request, key):
    value = request_data(request, ('format',), True)
    fmt = value.get('format', 'json')
    if fmt not in ('csv', 'json'):
        raise ValueError('支持CSV或JSON')
    d = load(request.user, key, value)
    doc = document(d)
    if fmt == 'json':
        text = json.dumps(doc, ensure_ascii=False, indent=2, allow_nan=False)+'\n'
    else:
        stream = io.StringIO()
        writer = csv.writer(stream)
        def cell(value):
            s = json.dumps(value, ensure_ascii=False, allow_nan=False) if isinstance(value, (dict, list)) else '' if value is None else str(value)
            return "'"+s if s.lstrip().startswith(('=', '+', '-', '@')) else s
        def section(name, rows):
            writer.writerow([name])
            fields = list(dict.fromkeys(f for row in rows for f in row))
            writer.writerow(fields or ['无记录；不代表零需求或已完成'])
            for row in rows:
                writer.writerow([cell(row.get(f)) for f in fields])
        section('基线假设试排', [dict(study=key, name=d['result']['study']['name'], state=d['result']['state'], history_verified=False, notice=engine.NOTICE,
                                  source_hash=d['source_hash'], rule_hash=d['rule_hash'])])
        for name in ('result', 'baseline_review'):
            section(name, [doc[name]])
        for name in ('baseline_inputs', 'baseline_references', 'planning_references'):
            for ds, rows in doc[name].items():
                section(name+'/'+ds, rows if isinstance(rows, list) else [rows])
        section('current_trial/result', [doc['current_trial']['result']])
        for name in ('material_inputs', 'crew_inputs', 'resource_inputs', 'references'):
            for ds, rows in doc['current_trial'][name].items():
                section('current_trial/'+name+'/'+ds, rows if isinstance(rows, list) else [rows])
        section('registered_issue_history', d['issue_history'])
        section('sources', d['sources'])
        text = '\ufeff'+stream.getvalue()
    finish(d, request.user)
    AuditEvent.objects.create(action='baseline_trial.export', actor=request.user.username, object_type='OrderBaseline', object_id=key,
                              detail=dict(format=fmt, policy=d['result']['policy'], source_hash=d['source_hash'], rule_hash=d['rule_hash'],
                                          file_sha256=hashlib.sha256(text.encode()).hexdigest(), business_facts_changed=False))
    return response(dict(filename='baseline-trial-'+finite.digest(key)[:16]+'.'+fmt, mime='application/json' if fmt == 'json' else 'text/csv', text=text))
