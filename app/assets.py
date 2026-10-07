"""Equipment-time unions, repair cohorts and current tool-register checks.

Only committed Excel facts are read. No OEE, calibration validity or historical
equipment status is inferred from the latest master-register status.
"""
from collections import defaultdict
from datetime import date, datetime, timedelta
from . import analytics
from .models import Record

TABLES = ('equipment', 'downtime', 'maintenance', 'tools', 'production_resources', 'resource_calendars')
STAGES = {
    'equipment': {'all': '全部设备', 'stopped': '有停机记录', 'open': '维修未完成', 'tool': '工装需关注', 'attention': '数据待核对'},
    'maintenance': {'all': '全部维修', 'open': '未完成', 'completed': '已完成', 'attention': '数据待核对'},
    'tool': {'all': '全部工装', 'overdue': '台账已到期', 'today': '今日到期', 'soon': '30天内到期', 'usage': '达到使用阈值', 'status': '台账状态待处理', 'attention': '数据待核对'},
}
NOTE = '模拟Excel事实。停机按设备时间并集合并；维修按报修日期选队列，状态截至固定快照；工装是当前台账，无历史使用与校准事件。协调记录不改变维修、校准或设备运行状态。'


def dt(value):
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is not None:
        raise ValueError('时间需为工厂本地时间')
    return parsed


def merge(intervals):
    out = []
    for start, end in sorted(intervals):
        if end <= start:
            continue
        if out and start <= out[-1][1]:
            out[-1] = (out[-1][0], max(end, out[-1][1]))
        else:
            out.append((start, end))
    return out


def seconds(intervals):
    return sum((end-start).total_seconds() for start, end in merge(intervals))


def overlap(left, right):
    return merge([(max(a, c), min(b, d)) for a, b in merge(left) for c, d in merge(right) if max(a, c) < min(b, d)])


def clipped(start, end, lo, hi):
    a, b = max(start, lo), min(end, hi)
    return [(a, b)] if b > a else []


def filters(query):
    if set(query)-{'tab', 'from', 'to', 'workshop', 'equipment_id', 'q', 'stage', 'page'}:
        raise ValueError('不支持的设备筛选')
    tab = query.get('tab', 'equipment')
    if tab not in STAGES:
        raise ValueError('工作页不可用')
    f = {k: query.get(k, '') for k in ('workshop', 'equipment_id', 'q')}
    f.update(tab=tab, stage=query.get('stage', 'all'))
    if f['stage'] not in STAGES[tab] or len(f['q']) > 200:
        raise ValueError('清单条件不可用')
    if tab == 'tool':
        if query.get('from') or query.get('to'):
            raise ValueError('工装台账不支持历史日期筛选')
        f.update({'from': '', 'to': ''})
    else:
        a, b = query.get('from') or '2026-09-21', query.get('to') or analytics.DAY
        lo, hi = date.fromisoformat(a), date.fromisoformat(b)
        if lo.isoformat() != a or hi.isoformat() != b or lo > hi or b > analytics.DAY or (hi-lo).days > 365:
            raise ValueError('日期需为YYYY-MM-DD，起止有序且不超过模拟截止日，最多366天')
        f.update({'from': a, 'to': b})
    return f


def safe(row):
    return {k: v for k, v in row.items() if not k.startswith('_') and 'cents' not in k}


class AssetData:
    def __init__(self, tables, f, cutoff=None):
        self.cutoff = cutoff or analytics.AS_OF
        self.now = dt(self.cutoff)
        self.day = self.now.date()
        self.f = f
        self.lo = dt((f['from'] or self.day.isoformat())+'T00:00:00')
        self.hi = min(dt((f['to'] or self.day.isoformat())+'T00:00:00')+timedelta(days=1), self.now)
        self.tables = tables
        self.equipment = {r['id']: r for r in tables['equipment']}
        self.resources = {r['id']: r for r in tables['production_resources']}
        self.global_issues = []
        self.grouped = {}
        for dataset in ('downtime', 'maintenance', 'tools', 'production_resources', 'resource_calendars'):
            grouped = defaultdict(list)
            for r in tables[dataset]:
                eid = r.get('equipment_id') if dataset != 'resource_calendars' else self.resources.get(r.get('resource_id'), {}).get('equipment_id')
                if eid not in self.equipment:
                    self.global_issues.append({'dataset': dataset, 'id': r['id'], 'message': '缺少设备或资源关联，未纳入设备汇总'})
                else:
                    grouped[eid].append(r)
            self.grouped[dataset] = grouped
        self.maintenance = {r['id']: self.repair(r) for eid in self.equipment for r in self.grouped['maintenance'][eid] if r['reported'] <= self.cutoff}
        self.tools = {r['id']: self.tool(r) for eid in self.equipment for r in self.grouped['tools'][eid]}
        self.rows = [self.machine(e) for e in self.equipment.values()]
        self.index = {r['id']: r for r in self.rows}

    def identity(self, row):
        e = self.equipment[row['equipment_id']]
        return {'equipment': e['name'], 'workshop': e['workshop'], 'process': e['process']}

    def repair(self, raw):
        r = {**safe(raw), **self.identity(raw)}
        issues = []
        reported = dt(raw['reported'])
        start = dt(raw['started']) if raw.get('started') else None
        end = dt(raw['finished']) if raw.get('finished') else None
        if start and start < reported:
            issues.append('维修开始早于报修')
        if end and (not start or end < start):
            issues.append('维修结束缺少有效开始时间')
        start_now = start if start and start <= self.now else None
        end_now = end if end and end <= self.now else None
        if (raw.get('status') == '已完成') != bool(end_now):
            issues.append('台账状态与截止时点完成时间不一致')
        r.update(issues=issues, response_hours=None, elapsed_hours=None, open_hours=None,
                 calculated_state='待核对' if issues else '已完成' if end_now else '未完成',
                 started_as_of=start_now.isoformat() if start_now else None,
                 finished_as_of=end_now.isoformat() if end_now else None)
        if not issues:
            r['response_hours'] = (start_now-reported).total_seconds()/3600 if start_now else None
            r['elapsed_hours'] = (end_now-reported).total_seconds()/3600 if end_now else None
            r['open_hours'] = (self.now-reported).total_seconds()/3600 if not end_now else None
        r['flags'] = ['all']+(['attention'] if issues else ['completed'] if end_now else ['open'])
        return r

    def tool(self, raw):
        r = {**safe(raw), **self.identity(raw)}
        issues = []
        calibrated, due = date.fromisoformat(raw['calibrated']), date.fromisoformat(raw['next_due'])
        if calibrated > self.day or due < calibrated:
            issues.append('台账校准/到期日期需核对')
        for k in ('uses', 'maintenance_limit'):
            if type(raw[k]) is not int or raw[k] < 0:
                issues.append('使用次数或维护阈值必须为非负整数')
        flags = ['all']
        days = (due-self.day).days
        if not issues:
            flags += ['overdue'] if days < 0 else ['today'] if days == 0 else ['soon'] if days <= 30 else []
            if raw['maintenance_limit'] > 0 and raw['uses'] >= raw['maintenance_limit']:
                flags.append('usage')
        if raw.get('status') != '有效':
            flags.append('status')
        if issues:
            flags.append('attention')
        r.update(issues=issues, flags=flags, days_to_due=None if issues else days,
                 usage_ratio=raw['uses']/raw['maintenance_limit']*100 if not issues and raw['maintenance_limit'] > 0 else None)
        return r

    def machine(self, raw):
        r = {**safe(raw), 'equipment_id': raw['id'], 'equipment': raw['name']}
        eid = raw['id']
        issues, intervals, events, calendars, calendar_rows, refs = [], [], [], [], [], []
        stop_invalid = calendar_invalid = False
        for ds in ('downtime', 'resource_calendars'):
            for x in self.grouped[ds][eid]:
                a, b = dt(x['started']), dt(x['finished'])
                if b <= a:
                    if self.lo <= a < self.hi:
                        issues.append(x['id']+'：时间区间倒置或为零')
                        stop_invalid |= ds == 'downtime'
                        calendar_invalid |= ds == 'resource_calendars'
                        refs.append({'dataset': ds, 'key': x['id']})
                    continue
                parts = clipped(a, b, self.lo, self.hi)
                if not parts:
                    continue
                refs.append({'dataset': ds, 'key': x['id']})
                if ds == 'downtime':
                    intervals += parts
                    events.append({**safe(x), 'window_start': parts[0][0].isoformat(), 'window_end': parts[0][1].isoformat(), 'window_minutes': seconds(parts)/60})
                else:
                    resource = self.resources[x['resource_id']]
                    refs.append({'dataset': 'production_resources', 'key': resource['id']})
                    if resource.get('effective', '0001-01-01') > x['started'][:10]:
                        issues.append(x['id']+'：排班早于资源生效')
                        calendar_invalid = True
                    calendars += parts
                    calendar_rows.append({**safe(x), 'window_start': parts[0][0].isoformat(), 'window_end': parts[0][1].isoformat()})
        merged = merge(intervals)
        union_seconds = seconds(merged)
        overlap_seconds = sum((b-a).total_seconds() for a, b in intervals)-union_seconds
        if overlap_seconds:
            issues.append('停机记录存在重叠，汇总已按设备时间去重；原因重叠单列')
        scheduled = seconds(calendars) if calendars and not calendar_invalid else None
        paired = seconds(overlap(merged, calendars)) if scheduled is not None and not stop_invalid else None
        repairs = [x for x in self.maintenance.values() if x['equipment_id'] == eid]
        tools = [x for x in self.tools.values() if x['equipment_id'] == eid]
        refs += [{'dataset': 'maintenance', 'key': x['id']} for x in repairs]+[{'dataset': 'tools', 'key': x['id']} for x in tools]
        # Reason intervals partition the merged equipment time; mixed labels are explicit.
        reasons = defaultdict(float)
        points = sorted({p for pair in merged for p in pair} | {dt(x[k]) for x in events for k in ('window_start', 'window_end')})
        for a, b in zip(points, points[1:]):
            names = {x.get('reason') or '未记录原因' for x in events if dt(x['window_start']) < b and dt(x['window_end']) > a}
            if names:
                reasons[next(iter(names)) if len(names) == 1 else '多原因重叠待核对'] += (b-a).total_seconds()/3600
        flags = ['all']
        if events: flags.append('stopped')
        if any('open' in x['flags'] for x in repairs): flags.append('open')
        if any(len(x['flags']) > 1 for x in tools): flags.append('tool')
        if issues or any(x['issues'] for x in repairs+tools): flags.append('attention')
        r.update(issues=issues, flags=flags, stop_hours=None if stop_invalid else union_seconds/3600,
                 scheduled_hours=scheduled/3600 if scheduled is not None else None,
                 scheduled_stop_hours=paired/3600 if paired is not None else None,
                 stop_ratio=paired/scheduled*100 if paired is not None and scheduled else None,
                 overlap_minutes=overlap_seconds/60, downtime_events=len(events),
                 open_repairs=sum('open' in x['flags'] for x in repairs),
                 repair_issues=sum(bool(x['issues']) for x in repairs),
                 tool_attention=sum(len(x['flags']) > 1 for x in tools),
                 _intervals=merged, _reasons=dict(reasons), _events=events, _calendars=calendar_rows,
                 _repairs=repairs, _tools=tools, _refs=refs)
        return r

    def selected(self):
        f = self.f
        rows = self.rows if f['tab'] == 'equipment' else list(self.tools.values()) if f['tab'] == 'tool' else [r for r in self.maintenance.values() if f['from'] <= r['reported'][:10] <= f['to']]
        return sorted([r for r in rows if (not f['workshop'] or r['workshop'] == f['workshop']) and
                       (not f['equipment_id'] or r['equipment_id'] == f['equipment_id']) and
                       (not f['q'] or f['q'].casefold() in ' '.join(str(r.get(k, '')) for k in ('id', 'name', 'equipment', 'equipment_id', 'failure', 'kind')).casefold())], key=lambda r: r['id'])

    def detail(self, kind, key):
        index = {'equipment': self.index, 'maintenance': self.maintenance, 'tool': self.tools}.get(kind)
        if index is None or key not in index:
            raise Record.DoesNotExist()
        r = index[key]
        refs = [{'dataset': 'equipment', 'key': r['equipment_id']}]
        if kind == 'equipment':
            refs += r['_refs']
        else:
            refs.append({'dataset': 'tools' if kind == 'tool' else 'maintenance', 'key': key})
        return {'row': safe(r), 'events': r.get('_events', []), 'calendars': r.get('_calendars', []),
                'repairs': r.get('_repairs', []), 'tools': r.get('_tools', []),
                'sources': [{'dataset': ds, 'key': pk} for ds, pk in sorted({(x['dataset'], x['key']) for x in refs})]}


def summary(rows, tab):
    out = {'objects': len(rows), **{k: sum(k in r['flags'] for r in rows) for k in STAGES[tab] if k != 'all'}}
    if tab == 'equipment':
        paired = [r for r in rows if r['scheduled_stop_hours'] is not None and r['scheduled_hours']]
        den = sum(r['scheduled_hours'] for r in paired)
        num = sum(r['scheduled_stop_hours'] for r in paired)
        out.update(stop_hours=sum(r['stop_hours'] for r in rows) if all(r['stop_hours'] is not None for r in rows) else None,
                   scheduled_hours=den, scheduled_stop_hours=num, paired_equipment=len(paired), stop_ratio=num/den*100 if den else None,
                   overlap_minutes=sum(r['overlap_minutes'] for r in rows))
    elif tab == 'maintenance':
        complete = [r['elapsed_hours'] for r in rows if r['elapsed_hours'] is not None]
        responses = [r['response_hours'] for r in rows if r['response_hours'] is not None]
        out.update(completed_samples=len(complete), response_samples=len(responses),
                   mean_elapsed_hours=sum(complete)/len(complete) if complete else None,
                   mean_response_hours=sum(responses)/len(responses) if responses else None,
                   max_open_hours=max((r['open_hours'] for r in rows if r['open_hours'] is not None), default=None))
    return out


def breakdown(data, rows):
    if not rows:
        return {'groups': []} if data.f['tab'] != 'equipment' else {'reasons': [], 'daily': []}
    if data.f['tab'] != 'equipment':
        groups = defaultdict(list)
        for r in rows: groups[r['kind']].append(r)
        return {'groups': [{'label': k, **summary(v, data.f['tab'])} for k, v in sorted(groups.items())]}
    reasons, daily = defaultdict(float), []
    valid = all(r['stop_hours'] is not None for r in rows)
    for r in rows:
        for key, value in r['_reasons'].items(): reasons[key] += value
    day = data.lo
    while day < data.hi:
        end = min(day+timedelta(days=1), data.hi)
        total = sum(seconds([p for a, b in r['_intervals'] for p in clipped(a, b, day, end)])/3600 for r in rows)
        daily.append({'day': day.date().isoformat(), 'hours': total if valid else None})
        day = end
    return {'reasons': [{'label': k, 'hours': v if valid else None} for k, v in sorted(reasons.items(), key=lambda p: (-p[1], p[0]))], 'daily': daily}


def current(f):
    return AssetData(analytics.tables(), f)
