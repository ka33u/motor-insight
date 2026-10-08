"""Independent arithmetic and row-level checks for the setup reading HTTP rehearsal."""
from datetime import datetime
from decimal import Decimal, ROUND_CEILING


def oracle(left, right, report, inputs):
    if left['state'] != 'trial' or right['state'] != 'trial':
        assert report['state'] == 'paused' and report['summary'] is None and report['events'] == []
        return 0
    jobs = {r['id']: r for r in inputs['schedule_jobs']}
    options = {r['id']: r for r in inputs['schedule_options']}
    ids = []
    for policy, result in [('due', left), ('priority', right)]:
        tasks = [t for t in result['tasks'] if t['state'] == 'scheduled']
        events = {r['task_id']: r for r in report['events'] if r['policy'] == policy}
        ids.append({t['id'] for t in tasks})
        assert set(events) == ids[-1]
        counts, seconds = {}, {}
        for resource in {t['resource_id'] for t in tasks}:
            ordered = sorted((t for t in tasks if t['resource_id'] == resource), key=lambda t: (t['started'], t['id']))
            resource_seconds = 0
            for i, task in enumerate(ordered):
                previous = ordered[i-1] if i else None
                family = jobs[task['job_id']]['family']
                prior_family = jobs[previous['job_id']]['family'] if previous else None
                kind = 'initial' if not previous else 'same' if family == prior_family else 'change'
                duration = int((Decimal(str(options[task['option_id']]['setup_minutes']))*60).to_integral_value(rounding=ROUND_CEILING)) if kind != 'same' else 0
                counts[kind] = counts.get(kind, 0)+1
                seconds[kind] = seconds.get(kind, 0)+duration
                resource_seconds += duration
                e = events[task['id']]
                assert (e['kind'], e['setup_seconds'], e['setup_minutes']) == (kind, duration, duration/60)
                assert e['previous_task_id'] == (previous['id'] if previous else None)
                assert e['previous_job_id'] == (previous['job_id'] if previous else None)
                assert (e['previous_family'], e['family']) == (prior_family, family)
                assert all(e[k] == task[k] for k in ('job_id', 'resource_id', 'employee_id', 'option_id', 'started', 'process_started', 'finished'))
                assert (datetime.fromisoformat(task['process_started'])-datetime.fromisoformat(task['started'])).total_seconds() == duration
            row = next(r for r in report['resources'] if r['id'] == resource)[policy]
            assert row['setup_minutes'] == resource_seconds/60 and row['scheduled_tasks'] == len(ordered)
        column = report['columns'][policy]
        for kind in ('initial', 'same', 'change'):
            assert column[kind+'_tasks'] == counts.get(kind, 0)
            assert column[kind+'_minutes'] == seconds.get(kind, 0)/60
        assert column['setup_minutes'] == sum(seconds.values())/60
        assert column['finished'] == (max(t['finished'] for t in tasks) if len(tasks) == len(result['tasks']) and tasks else None)
        assert column['late_jobs'] == sum(j['state'] == 'late' for j in result['jobs'])
        assert column['blocked_jobs'] == sum(j['state'] == 'blocked' for j in result['jobs'])
    comparable = bool(ids[0]) and ids[0] == ids[1]
    assert report['summary']['same_scheduled_scope'] == comparable
    a, b = report['columns']['due'], report['columns']['priority']
    assert report['summary']['setup_delta_minutes'] == (b['setup_minutes']-a['setup_minutes'] if comparable else None)
    if a['finished'] and b['finished']:
        assert report['summary']['finish_delta_minutes'] == (datetime.fromisoformat(b['finished'])-datetime.fromisoformat(a['finished'])).total_seconds()/60
        assert report['summary']['late_jobs_delta'] == b['late_jobs']-a['late_jobs']
    else:
        assert report['summary']['finish_delta_minutes'] is None and report['summary']['late_jobs_delta'] is None
    return len(report['events'])
