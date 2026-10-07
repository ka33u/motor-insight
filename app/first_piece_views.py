"""Snapshot-bound first-piece board, direct evidence and auditable exports."""
import hashlib
import json
from pathlib import Path
from django.core import signing
from django.db import transaction
from django.http import HttpResponse
from . import first_piece as engine, first_piece_data as data, first_review, spc_data, access, metrology
from .models import Record, AuditEvent
from .views import api, reply, require
from .quality_views import csv_reply
from .import_review import ReviewConflict

SALT = 'motor.first-piece.v1'
FIELDS = ('q', 'state', 'process', 'study', 'review')


def params(request, extra=()):
    if set(request.GET)-set((*FIELDS, *extra)) or any(len(request.GET.getlist(k)) != 1 for k in request.GET):
        raise ValueError('首件筛选字段无效或重复')
    f = {k: request.GET.get(k, '') for k in FIELDS}
    if any(len(v) > 150 for v in f.values()) or f['state'] and f['state'] not in engine.STATES:
        raise ValueError('首件筛选内容无效')
    if f['review'] and f['review'] not in first_review.STATES:
        raise ValueError('复核状态无效')
    return f


def number(request, key='page'):
    v = request.GET.get(key, '1')
    if not v.isascii() or not v.isdecimal() or not 1 <= int(v) <= 10000:
        raise ValueError('页码须为1至10000整数')
    return int(v)


def stamp(d, user, f):
    return dict(account=spc_data.account(user), filters=f, source=d['source_hash'], rule=d['rule_hash'],
                result=metrology.digest(dict(result=d['result'], targets=d['targets'], reviews=d['reviews'])),
                view=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())


def context(request, f, required=False):
    if f['study']:
        require(access.allowed(request.user, 'launch_clearances'), '当前岗位不能读取投产试排依据')
    d = data.load(f['study'])
    expected = stamp(d, request.user, f)
    receipt = request.GET.get('receipt')
    if required and not receipt:
        raise ValueError('先读取首件证据，再查看明细或导出')
    if receipt:
        if len(receipt) > 4096:
            raise ValueError('读取凭据过长')
        try:
            actual = signing.loads(receipt, salt=SALT, max_age=600)
        except signing.BadSignature:
            raise ReviewConflict('读取凭据无效或已过期，请重新读取')
        if actual != expected:
            raise ReviewConflict('首件、计量、来源、规则、筛选或账号已变化，请重新读取')
    d['receipt'] = receipt or signing.dumps(expected, salt=SALT, compress=True)
    d['stamp'] = expected
    d['selected'] = [r for r in d['result']['rows'] if (not f['state'] or r['evidence_state'] == f['state'])
                     and (not f['review'] or d['reviews']['rows'][r['id']]['state'] == f['review'])
                     and (not f['process'] or r['process'] == f['process'])
                     and (not f['q'] or f['q'].casefold() in ' '.join(str(r.get(k) or '') for k in ('id', 'work_order_id', 'product_id', 'object_id', 'operation_id')).casefold())]
    return d


def review_summary(d):
    return {s: sum(d['reviews']['rows'][r['id']]['state'] == s for r in d['selected']) for s in first_review.STATES}


def review_rows(d, rows):
    return {r['id']: {k: v for k, v in d['reviews']['rows'][r['id']].items() if k not in ('history', 'sources')} for r in rows}


def review_matrix(d):
    matrix = {s: {v: 0 for v in first_review.STATES} for s in engine.STATES}
    for row in d['selected']:
        matrix[row['evidence_state']][d['reviews']['rows'][row['id']]['state']] += 1
    return matrix


def finish(request, d, f):
    if stamp(d, request.user, f) != d['stamp'] or engine.rule_hash() != d['rule_hash']:
        raise ReviewConflict('读取期间权限或规则变化，请重新读取')


def response(value):
    r = reply(value)
    r['Cache-Control'] = 'no-store'
    return r


@api()
@transaction.atomic
def board(request):
    f = params(request, ('page', 'receipt'))
    page = number(request)
    d = context(request, f)
    r = d['result']
    finish(request, d, f)
    return response(dict(rows=d['selected'][(page-1)*25:page*25], total=len(d['selected']), page=page, size=25,
                         summary=engine.summary(d['selected']), all_summary=r['summary'], filters=f,
                         reviews=review_rows(d, d['selected'][(page-1)*25:page*25]), review_summary=review_summary(d), review_labels=first_review.STATES,
                         review_matrix=review_matrix(d),
                         review_notice=first_review.NOTICE, unmatched_reviews=d['reviews']['unmatched'],
                         states=engine.STATES, processes=sorted({x['process'] for x in r['rows'] if x.get('process')}),
                         targets=d['targets'], receipt=d['receipt'], receipt_seconds=600, as_of=r['as_of'], notice=r['notice'],
                         source_hash=d['source_hash'], rule_hash=d['rule_hash'], synthetic=True,
                         can_targets=access.allowed(request.user, 'launch_clearances')))


@api()
@transaction.atomic
def detail(request, key):
    f = params(request, ('receipt', 'page'))
    page = number(request)
    d = context(request, f, True)
    if key not in {r['id'] for r in d['selected']}:
        raise Record.DoesNotExist()
    obj = d['result']['details'][key]
    review = d['reviews']['rows'][key]
    keys = {(s['dataset'], s['key']) for s in obj['sources']+review['sources']}
    found = {(s['dataset'], s['key']): s for s in d['sources'] if (s['dataset'], s['key']) in keys}
    sources = [found.get(k, dict(dataset=k[0], key=k[1], missing=True)) for k in sorted(keys)]
    finish(request, d, f)
    return response(dict(**{k: v for k, v in obj.items() if k != 'sources'}, sources=sources[(page-1)*40:page*40],
                         source_total=len(sources), page=page, receipt=d['receipt'], notice=engine.NOTICE,
                         review=review, review_notice=first_review.NOTICE,
                         calibration_labels=d['result']['calibration_labels'], impact_labels=d['result']['impact_labels']))


@api()
@transaction.atomic
def export(request):
    f = params(request, ('receipt', 'format'))
    fmt = request.GET.get('format', 'csv')
    if fmt not in ('csv', 'json'):
        raise ValueError('支持CSV或JSON')
    d = context(request, f, True)
    rows = d['selected']
    document = dict(format='motor-first-piece-v1', synthetic=True, as_of=d['result']['as_of'], filters=f,
                    rows=rows, summary=engine.summary(rows), targets=d['targets'],
                    reviews={r['id']: d['reviews']['rows'][r['id']] for r in rows}, review_summary=review_summary(d), review_notice=first_review.NOTICE,
                    review_matrix=review_matrix(d),
                    unmatched_reviews=d['reviews']['unmatched'],
                    details=[d['result']['details'][r['id']] for r in rows],
                    sources=d['sources'], source_scope='完整受控计算范围；各计划直接引用见details.sources',
                    source_hash=d['source_hash'], rule_hash=d['rule_hash'], notice=engine.NOTICE)
    if fmt == 'json':
        result = HttpResponse(json.dumps(document, ensure_ascii=False, indent=2, allow_nan=False)+'\n', content_type='application/json; charset=utf-8')
        result['Content-Disposition'] = 'attachment; filename="first-piece.json"'
    else:
        content = [['首件证据工作台', d['result']['as_of']], ['边界', engine.NOTICE], ['筛选', json.dumps(f, ensure_ascii=False)], ['来源摘要', d['source_hash']],
                   ['计划', '工单', '对象', '工序', '分支', '最新检验', '最新实测状态', '首件证据状态', '超限项', '漏项', '计量待核对项', '审批边界']]
        fields = ('id', 'work_order_id', 'object_id', 'process', 'branch', 'latest_id', 'latest_state', 'evidence_label', 'latest_out', 'latest_missing', 'meter_attention', 'approval')
        content += [[r.get(k) for k in fields] for r in rows]
        content += [['复核登记核对', first_review.NOTICE], ['计划', '复核状态', '生效复核', '登记结论', '复核工号', '复核时点', '文件编号', '待核对原因']]
        for r in rows:
            review = d['reviews']['rows'][r['id']]
            selected = review['selected'] or {}
            content.append([r['id'], review['label'], selected.get('id'), selected.get('decision'), selected.get('reviewer_id'), selected.get('reviewed'), selected.get('reference'), '；'.join(review['reasons'])])
        if d['targets']:
            content += [['投产工单候选首件', d['targets']['notice']], ['质量条件', '工单', '路线', '状态', '候选计划', '原因']]
            content += [[r['id'], r['work_order_id'], r['route_id'], r['state'], '；'.join(r['plan_ids']), r['reason']] for r in d['targets']['rows']]
        content = [["'"+v if isinstance(v, str) and v.lstrip().startswith(('=', '+', '-', '@')) else v for v in r] for r in content]
        result = csv_reply(content, 'first-piece')
    finish(request, d, f)
    AuditEvent.objects.create(action='first_piece.export', actor=request.user.username, object_type='FirstPieceEvidence', object_id='current',
                              detail=dict(format=fmt, filters=f, rows=len(rows), source_hash=d['source_hash'], rule_hash=d['rule_hash'],
                                          file_sha256=hashlib.sha256(result.content).hexdigest(), business_facts_changed=False))
    result['Cache-Control'] = 'no-store'
    return result
