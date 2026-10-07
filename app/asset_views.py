import json
from datetime import date
from django.db import transaction
from django.utils import timezone
from . import assets, analytics, access
from .views import api, reply, body, require
from .models import IssueDisposition, AuditEvent
from .delivery_views import follow_info
from .quality_views import csv_reply
from .trace_cases import capture_sources

STATUSES = ['待处理', '排查中', '待备件协调', '待校准核对', '待源系统复核', '演练已核验']


def can_follow(user):
    return access.role(user) in ['admin', 'analyst', 'operations', 'quality']


def context(request):
    f = assets.filters(request.GET)
    return assets.current(f), f


def response(value):
    r = reply(value)
    r['Cache-Control'] = 'no-store'
    return r


@api()
@transaction.atomic
def board(request):
    d, f = context(request)
    rows = d.selected()
    selected = [r for r in rows if f['stage'] in r['flags']]
    page = max(1, int(request.GET.get('page', 1)))
    items = selected[(page-1)*25:page*25]
    notes = {n.key: n for n in IssueDisposition.objects.filter(key__in=['asset:'+f['tab']+':'+r['id'] for r in items])}
    return response({'filters': f, 'summary': assets.summary(rows, f['tab']), **assets.breakdown(d, rows),
                     'rows': [{**assets.safe(r), 'follow_up': follow_info(notes.get('asset:'+f['tab']+':'+r['id']))} for r in items],
                     'total': len(selected), 'page': page, 'size': 25, 'stages': assets.STAGES[f['tab']],
                     'facets': {k: sum(k in r['flags'] for r in rows) for k in assets.STAGES[f['tab']]},
                     'global_issues': d.global_issues, 'as_of': d.cutoff, 'note': assets.NOTE,
                     'options': {'workshops': sorted({r['workshop'] for r in d.rows}),
                                 'equipment': [{'id': r['id'], 'name': r['name']} for r in d.rows]}})


@api()
@transaction.atomic
def detail(request, kind, key):
    d, f = context(request)
    obj = d.detail(kind, key)
    obj.update(follow_up=follow_info(IssueDisposition.objects.filter(key='asset:'+kind+':'+key).first()),
               data_revision=list(analytics.revision()), can_follow_up=can_follow(request.user),
               as_of=d.cutoff, filters=f, note=assets.NOTE)
    return response(obj)


@api()
@transaction.atomic
def evidence(request, kind, key):
    d, f = context(request)
    obj = d.detail(kind, key)
    rows = capture_sources(obj)
    page = max(1, int(request.GET.get('page', 1)))
    return response({'rows': rows[(page-1)*40:page*40], 'total': len(rows), 'page': page, 'size': 40,
                     'can_download_original': access.can_import(request.user)})


@api(('POST',))
@transaction.atomic
def follow_up(request, kind, key):
    require(can_follow(request.user))
    d, f = context(request)
    obj = d.detail(kind, key)
    p = body(request)
    if set(p) != {'version', 'status', 'owner', 'due_date', 'note', 'data_revision'}:
        raise ValueError('协调字段不完整或含未知字段')
    if type(p['version']) is not int or p['version'] < 0 or p['status'] not in STATUSES:
        raise ValueError('协调版本或状态不可用')
    for name, lo, hi in [('owner', 1, 150), ('note', 5, 2000)]:
        if not isinstance(p[name], str) or not lo <= len(p[name].strip()) <= hi:
            raise ValueError('请填写负责人及5至2000字跟进依据')
    due = p['due_date'] or None
    if due and (not isinstance(due, str) or date.fromisoformat(due).isoformat() != due):
        raise ValueError('期限格式应为YYYY-MM-DD')
    if p['data_revision'] != list(analytics.revision()):
        return reply({'error': '来源已变化，请重新读取并核对'}, 409)
    obj_key = 'asset:'+kind+':'+key
    item = IssueDisposition.objects.select_for_update().filter(key=obj_key).first()
    before = follow_info(item)
    if before['version'] != p['version']:
        return reply({'error': '协调记录已更新，请重新读取'}, 409)
    changed = {'status': p['status'], 'owner': p['owner'].strip(), 'note': p['note'].strip(),
               'due_date': due, 'version': p['version']+1, 'updated_by': request.user.username, 'updated_at': timezone.now()}
    if item:
        if IssueDisposition.objects.filter(pk=item.pk, version=p['version']).update(**changed) != 1:
            return reply({'error': '协调版本冲突，请重新读取'}, 409)
        item.refresh_from_db()
    else:
        item = IssueDisposition.objects.create(key=obj_key, **changed)
    serial = lambda x: json.loads(json.dumps(x, ensure_ascii=False, default=str))
    AuditEvent.objects.create(action='asset.followup', actor=request.user.username, object_type='AssetCoordination', object_id=obj_key,
                              detail={'before': serial(before), 'after': serial(follow_info(item)), 'source_issues': obj['row']['issues'],
                                      'data_revision': p['data_revision'], 'business_facts_changed': False})
    return response({'follow_up': follow_info(item), 'notice': '已保存协调记录；不改变维修完成、校准或设备状态。'})


@api()
def history(request, kind, key):
    d, _ = context(request)
    d.detail(kind, key)
    return response({'rows': list(AuditEvent.objects.filter(object_type='AssetCoordination', object_id='asset:'+kind+':'+key).order_by('-id').values('actor', 'detail', 'created_at'))})


@api()
@transaction.atomic
def export(request):
    d, f = context(request)
    rows = [r for r in d.selected() if f['stage'] in r['flags']]
    fields = {
        'equipment': [('id', '设备编码'), ('name', '设备名称'), ('workshop', '车间'), ('status', '台账状态'), ('stop_hours', '期间记录停机小时'), ('scheduled_hours', '去重排班小时'), ('scheduled_stop_hours', '排班内停机小时'), ('stop_ratio', '排班内停机占比%'), ('open_repairs', '截止未完成维修数'), ('tool_attention', '工装关注数')],
        'maintenance': [('id', '维修单'), ('equipment_id', '设备编码'), ('kind', '任务类型'), ('reported', '报修时间'), ('started_as_of', '截止已开始时间'), ('finished_as_of', '截止已完成时间'), ('calculated_state', '截止状态'), ('response_hours', '报修至开始小时'), ('elapsed_hours', '报修至完成小时'), ('open_hours', '未完成已等待小时')],
        'tool': [('id', '工装编号'), ('name', '名称'), ('equipment_id', '设备编码'), ('kind', '类型'), ('calibrated', '台账校准日期'), ('next_due', '台账到期日'), ('days_to_due', '距离到期天数'), ('uses', '累计使用数'), ('maintenance_limit', '维护阈值'), ('usage_ratio', '使用数与阈值比%'), ('status', '台账状态')],
    }[f['tab']]
    data = [['模拟设备与工装', '状态截止', d.cutoff, '筛选', json.dumps(f, ensure_ascii=False)], ['说明', assets.NOTE],
            [label for _, label in fields]+['关注类型', '核对事项']]
    data += [[r.get(k) for k, _ in fields]+['；'.join(assets.STAGES[f['tab']][x] for x in r['flags'] if x != 'all'), '；'.join(r['issues'])] for r in rows]
    AuditEvent.objects.create(action='asset.export', actor=request.user.username, object_type='AssetBoard', object_id=f['tab'], detail={'filters': f, 'rows': len(rows)})
    res = csv_reply(data, 'assets-'+f['tab'])
    res['Cache-Control'] = 'no-store'
    return res
