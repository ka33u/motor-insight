"""Author synthetic multi-product assumptions; business facts still enter via XLSX.

Reads the already imported public CR-261002-001 sample. Never writes business rows.
"""
import json
from collections import defaultdict
from datetime import datetime, timedelta
from decimal import Decimal
from build_shared_material_scenario import ROOT, Record, SCHEMAS, DATASETS, RESOURCE, CREW, MATERIAL
from app import crew_schedule_data, finite_schedule, crew_schedule, joint_schedule

SP, CR, MP = 'SP-261016-001', 'CR-261016-001', 'MP-261016-001'
STAMP = '自编混合产品试排 V1；引用原合成编号。日历顺延14天，每任务仅选原候选中编码最小资源；不是实际派工。'


def shifted(value):
    return (datetime.fromisoformat(value)+timedelta(days=14)).isoformat(timespec='seconds')


def generate():
    old = crew_schedule_data.load('CR-261002-001')
    tables = {ds: [] for ds in DATASETS}
    refs = {ds: {r.business_key: r.values for r in Record.objects.filter(dataset=ds)}
            for ds in ('products', 'materials', 'bom', 'routes', 'route_dependencies', 'production_resources', 'employees', 'skills')}
    original = old['base']['tables']
    task_map = {}
    for n, source in enumerate(original['schedule_jobs'][:3], 1):
        jid = f'{SP}-B{n:03}'
        tasks = [t for t in original['schedule_tasks'] if t['job_id'] == source['id']]
        local = {t['id']: t['id'].replace(source['id'], jid) for t in tasks}
        task_map.update(local)
        tables['schedule_jobs'].append({**source, 'id': jid, 'study_id': SP,
            'released': '2026-10-16T08:00:00', 'due': ('2026-10-17T12:00:00', '2026-10-17T18:00:00', '2026-10-18T18:00:00')[n-1],
            'priority': (1, 3, 2)[n-1], 'reference': f'SIM-MIX-261016-B{n:03}'})
        for task in tasks:
            tables['schedule_tasks'].append({**task, 'id': local[task['id']], 'job_id': jid, 'basis': STAMP})
            option = min((o for o in original['schedule_options'] if o['task_id'] == task['id']), key=lambda o: o['resource_id'])
            tables['schedule_options'].append({**option, 'id': option['id'].replace(source['id'], jid),
                                              'task_id': local[task['id']], 'basis': STAMP})
        for edge in original['schedule_edges']:
            if edge['from_task_id'] in local:
                tables['schedule_edges'].append({**edge, 'id': f'{SP}-D{len(tables["schedule_edges"])+1:03}',
                    'study_id': SP, 'from_task_id': local[edge['from_task_id']], 'to_task_id': local[edge['to_task_id']], 'basis': STAMP})
    resources = {o['resource_id'] for o in tables['schedule_options']}
    for ds, suffix in [('schedule_windows', 'W'), ('schedule_blocks', 'X')]:
        for row in original[ds]:
            if row['resource_id'] in resources:
                tables[ds].append({**row, 'id': f'{SP}-{suffix}{len(tables[ds])+1:03}', 'study_id': SP,
                                  'started': shifted(row['started']), 'finished': shifted(row['finished']), 'basis': STAMP})
    study = {**old['base']['result']['study'], 'id': SP, 'name': '三品种换型与交期取舍', 'version': 'MIX-RESOURCE-V1',
        'baseline': '2026-10-16T08:00:00', 'horizon_end': '2026-10-19T18:00:00',
        'scope': 'CP.00008.A / CP.00015.A / CP.00022.A 三批6/8/10台，共24台；换型族A/B/A。',
        'assumptions': STAMP+'交期顺序B001/B002/B003；优先级顺序B001/B003/B002。首次上机也计换型。',
        'reference': 'SIM-MIX-RESOURCE-261016'}
    for field, ds in [('job_count', 'schedule_jobs'), ('task_count', 'schedule_tasks'), ('edge_count', 'schedule_edges'),
                      ('option_count', 'schedule_options'), ('window_count', 'schedule_windows'), ('block_count', 'schedule_blocks')]:
        study[field] = len(tables[ds])
    tables['schedule_studies'].append(study)
    originals = old['tables']
    credentials = {c['credential_id'] for c in originals['crew_candidates'] if c['task_id'] in task_map}
    credential_map = {k: f'{CR}-Q{i:03}' for i, k in enumerate(sorted(credentials), 1)}
    for row in originals['crew_credentials']:
        if row['id'] in credentials:
            tables['crew_credentials'].append({**row, 'id': credential_map[row['id']], 'study_id': CR,
                'valid_from': shifted(row['valid_from']), 'valid_until': shifted(row['valid_until']), 'basis': STAMP})
    for row in originals['crew_candidates']:
        if row['task_id'] in task_map:
            tables['crew_candidates'].append({**row, 'id': f'{CR}-C{len(tables["crew_candidates"])+1:03}', 'study_id': CR,
                'task_id': task_map[row['task_id']], 'credential_id': credential_map[row['credential_id']], 'basis': STAMP})
    employees = {refs['skills'][q['skill_id']]['employee_id'] for q in tables['crew_credentials']}
    for ds, suffix in [('crew_windows', 'W'), ('crew_blocks', 'X')]:
        for row in originals[ds]:
            if row['employee_id'] in employees:
                tables[ds].append({**row, 'id': f'{CR}-{suffix}{len(tables[ds])+1:03}', 'study_id': CR,
                                  'started': shifted(row['started']), 'finished': shifted(row['finished']), 'basis': STAMP})
    crew_study = {**old['result']['study'], 'id': CR, 'name': '三品种人机共用假设', 'resource_study_id': SP,
                  'version': 'MIX-CREW-V1', 'assumptions': STAMP+'沿用原技能依据，一人陪同整个换型与加工。', 'reference': 'SIM-MIX-CREW-261016'}
    for field, ds in [('credential_count', 'crew_credentials'), ('candidate_count', 'crew_candidates'),
                      ('window_count', 'crew_windows'), ('block_count', 'crew_blocks')]:
        crew_study[field] = len(tables[ds])
    tables['crew_studies'].append(crew_study)
    prefixes = {'01.01': '冲片', '01.02': '绕线嵌线', '02.01': '装配', '02.02': '机加工',
                '03.01': '浸漆固化', '03.02': '装配', '04.01': '绕线嵌线', '04.02': '转子铸铝'}
    totals = defaultdict(Decimal)
    for job in tables['schedule_jobs']:
        product = refs['products'][job['product_id']]
        boms = sorted((b for b in refs['bom'].values() if b['product_id'] == product['id'] and b['version'] == product['bom_version']), key=lambda b: b['id'])
        routes = {(r['branch'], r['process']): r for r in refs['routes'].values() if r['product_id'] == product['id'] and r['version'] == job['route_version']}
        for bom in boms:
            material = refs['materials'][bom['material_id']]
            route = routes['整机' if bom['assembly_level'] == '装配件包' else bom['assembly_level'], prefixes[material['id'][:5]]]
            quantum = 1 if material['unit'] == '件' else .001
            bid = f'{MP}-B{len(tables["joint_bindings"])+1:03}'
            tables['joint_bindings'].append(dict(id=bid, study_id=MP, bom_id=bom['id'], route_id=route['id'], quantum=quantum,
                basis='原合成BOM绑定原路线，kg取整步长0.001，件取整步长1。'))
            qty = joint_schedule.requirement(job['qty'], bom['qty'], bom['scrap_allowance'], quantum)
            tables['joint_demands'].append(dict(id=f'{MP}-D{len(tables["joint_demands"])+1:03}', study_id=MP,
                job_id=job['id'], binding_id=bid, required_qty=float(qty), unit=material['unit'],
                basis='独立模拟整批需求=批量×原BOM单耗×(1+损耗)，按绑定步长向上取整。'))
            totals[material['id'], material['unit']] += qty
    for i, ((mid, unit), qty) in enumerate(sorted(totals.items()), 1):
        tables['joint_supplies'].append(dict(id=f'{MP}-L{i:03}', study_id=MP, material_id=mid, lot=f'SIM-MIX-261016-{i:03}',
            unit=unit, qty=float(qty), unavailable_qty=0, available_from='2026-10-16T08:00:00', status='可预留', kind='期初假设',
            reference=f'SIM-MIX-SUPPLY-{i:03}', basis='三产品同物料同单位合池，供给恰好覆盖本情景全部需求；非真实库存。'))
    material_study = dict(id=MP, name='三品种换型与交期取舍·物料充足', crew_study_id=CR, version='MIX-MATERIAL-V1', owner_id='E00001',
        scope=study['scope'], assumptions='物料按原BOM足额供应；两策略读取相同输入，仅派序不同。优先级由人工假设给定，不是自动同族优化。', reference='SIM-MIX-MATERIAL-261016')
    for field, ds in [('binding_count', 'joint_bindings'), ('demand_count', 'joint_demands'), ('supply_count', 'joint_supplies')]:
        material_study[field] = len(tables[ds])
    tables['joint_studies'].append(material_study)
    profiles = []
    for policy in ('due', 'priority'):
        bt = {ds: tables[ds] for ds in RESOURCE[1:]}
        base = dict(tables=bt, result=finite_schedule.analyze(study, bt, refs, policy))
        ct = {ds: tables[ds] for ds in CREW[1:]}
        parent = dict(base=base, tables=ct, result=crew_schedule.analyze(crew_study, ct, base, refs))
        mt = {ds: tables[ds] for ds in MATERIAL[1:]}
        result = joint_schedule.analyze(material_study, mt, parent, refs)
        profiles.append(dict(policy=policy, state=result['state'], issues=result['issues'], summary=result['summary'], jobs=result['jobs'],
                             setup_minutes=sum(t['setup_minutes'] or 0 for t in result['tasks']),
                             setup_events=sum(bool(t['setup_minutes']) for t in result['tasks'])))
    return dict(synthetic=True, source='Read-only references to existing public synthetic XLSX',
                schemas={ds: SCHEMAS[ds] for ds in DATASETS}, tables=tables, profiles=profiles)


if __name__ == '__main__':
    payload = generate()
    (ROOT/'data/changeover_scenario.json').write_text(json.dumps(payload, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps(dict(counts={ds: len(rows) for ds, rows in payload['tables'].items()}, profiles=payload['profiles']), ensure_ascii=False))
