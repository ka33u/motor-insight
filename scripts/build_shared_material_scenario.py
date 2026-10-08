"""Prepare synthetic XLSX input; read existing public reference facts, never write them.

Run after the original 43 public workbooks have been normally imported.
The JSON is an authoring intermediate, not an alternative business import path.
"""
import json
import os
import sys
from collections import defaultdict
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
import django
django.setup()
from app.models import Record
from app.schema import SCHEMAS
from app import finite_schedule, crew_schedule, crew_schedule_data, joint_schedule
from app.finite_schedule_schema import DATASETS as RESOURCE
from app.crew_schedule_schema import DATASETS as CREW
from app.joint_schedule_schema import DATASETS as MATERIAL

SP, CR = 'SP-261009-001', 'CR-261009-001'
DATASETS = (*RESOURCE, *CREW, *MATERIAL)
STAMP = '自编跨批次假设 V1；沿用既有合成档案编号，不代表正式计划或人员授权。'


def shifted(value):
    return (datetime.fromisoformat(value) + timedelta(days=7)).isoformat(timespec='seconds')


def generate():
    old = crew_schedule_data.load('CR-261002-001')
    source_job = old['base']['tables']['schedule_jobs'][0]
    assert (source_job['id'], source_job['product_id'], source_job['qty']) == ('SP-261002-001-B001', 'CP.00008.A', 6)
    tables = {ds: [] for ds in DATASETS}
    refs = {ds: {r.business_key: r.values for r in Record.objects.filter(dataset=ds)}
            for ds in ('products', 'materials', 'bom', 'routes', 'route_dependencies', 'production_resources', 'employees', 'skills')}
    original = old['base']['tables']
    task_maps = []
    for n in (1, 2):
        jid = f'{SP}-B{n:03}'
        task_map = {t['id']: t['id'].replace(source_job['id'], jid)
                    for t in original['schedule_tasks'] if t['job_id'] == source_job['id']}
        task_maps.append(task_map)
        tables['schedule_jobs'].append({**source_job, 'id': jid, 'study_id': SP,
            'released': '2026-10-09T08:00:00', 'due': f'2026-10-{9+n:02}T18:00:00',
            'priority': 3-n, 'reference': f'SIM-SHARED-261009-B{n:03}'})
        for task in original['schedule_tasks']:
            if task['id'] in task_map:
                tables['schedule_tasks'].append({**task, 'id': task_map[task['id']], 'job_id': jid, 'basis': STAMP})
        for edge in original['schedule_edges']:
            if edge['from_task_id'] in task_map:
                tables['schedule_edges'].append({**edge, 'id': f'{jid}-D{sum(e["from_task_id"].startswith(jid) for e in tables["schedule_edges"])+1:03}',
                    'study_id': SP, 'from_task_id': task_map[edge['from_task_id']], 'to_task_id': task_map[edge['to_task_id']], 'basis': STAMP})
        for option in original['schedule_options']:
            if option['task_id'] in task_map:
                tables['schedule_options'].append({**option, 'id': option['id'].replace(source_job['id'], jid),
                    'task_id': task_map[option['task_id']], 'basis': STAMP})
    resource_ids = {o['resource_id'] for o in tables['schedule_options']}
    for ds, suffix in [('schedule_windows', 'W'), ('schedule_blocks', 'X')]:
        for row in original[ds]:
            if row['resource_id'] in resource_ids:
                tables[ds].append({**row, 'id': f'{SP}-{suffix}{len(tables[ds])+1:03}', 'study_id': SP,
                    'started': shifted(row['started']), 'finished': shifted(row['finished']), 'basis': STAMP})
    study = {**old['base']['result']['study'], 'id': SP, 'name': '同型号双批次共享物料对照',
        'version': 'SHARED-BATCH-V1', 'baseline': '2026-10-09T08:00:00', 'horizon_end': '2026-10-12T18:00:00',
        'scope': 'CP.00008.A 两个独立模拟批次，各6台，共12台；B001交期较早，B002优先级较高。',
        'assumptions': '原合成样例B001路线与单耗；工作窗口顺延7天。两个批次共享相同设备及人员候选，不新增并行容量。',
        'reference': 'SIM-SHARED-RESOURCE-261009'}
    for field, ds in [('job_count', 'schedule_jobs'), ('task_count', 'schedule_tasks'), ('edge_count', 'schedule_edges'), ('option_count', 'schedule_options'), ('window_count', 'schedule_windows'), ('block_count', 'schedule_blocks')]:
        study[field] = len(tables[ds])
    tables['schedule_studies'].append(study)

    originals = old['tables']
    credentials = {c['credential_id'] for c in originals['crew_candidates'] if c['task_id'] in task_maps[0]}
    credential_map = {k: f'{CR}-Q{i:03}' for i, k in enumerate(sorted(credentials), 1)}
    for row in originals['crew_credentials']:
        if row['id'] in credentials:
            tables['crew_credentials'].append({**row, 'id': credential_map[row['id']], 'study_id': CR,
                'valid_from': shifted(row['valid_from']), 'valid_until': shifted(row['valid_until']), 'basis': STAMP})
    for task_map in task_maps:
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
    crew_study = {**old['result']['study'], 'id': CR, 'name': '同型号双批次人员假设', 'resource_study_id': SP,
        'version': 'SHARED-CREW-V1', 'assumptions': STAMP+'一人陪同换型与加工；两个批次共用原候选人员。', 'reference': 'SIM-SHARED-CREW-261009'}
    for field, ds in [('credential_count', 'crew_credentials'), ('candidate_count', 'crew_candidates'), ('window_count', 'crew_windows'), ('block_count', 'crew_blocks')]:
        crew_study[field] = len(tables[ds])
    tables['crew_studies'].append(crew_study)

    product = refs['products'][source_job['product_id']]
    boms = sorted((b for b in refs['bom'].values() if b['product_id'] == product['id'] and b['version'] == product['bom_version']), key=lambda b: b['id'])
    routes = {(r['branch'], r['process']): r for r in refs['routes'].values() if r['product_id'] == product['id'] and r['version'] == source_job['route_version']}
    process_by_prefix = {'01.01': '冲片', '01.02': '绕线嵌线', '02.01': '装配', '02.02': '机加工', '03.01': '浸漆固化', '03.02': '装配', '04.01': '绕线嵌线', '04.02': '转子铸铝'}
    target = next(b['material_id'] for b in boms if b['material_id'].startswith('01.01'))
    for n, name in [(1, '双批次共享硅钢·仅够一批'), (2, '双批次共享硅钢·充足对照')]:
        key = f'MP-261009-{n:03}'
        total = defaultdict(Decimal)
        for i, bom in enumerate(boms, 1):
            material = refs['materials'][bom['material_id']]
            route = routes['整机' if bom['assembly_level'] == '装配件包' else bom['assembly_level'], process_by_prefix[material['id'][:5]]]
            quantum = 1 if material['unit'] == '件' else .001
            bid = f'{key}-B{i:03}'
            tables['joint_bindings'].append(dict(id=bid, study_id=key, bom_id=bom['id'], route_id=route['id'], quantum=quantum,
                basis='当前合成BOM行绑定原路线；kg向上取整至0.001，件向上取整至1。'))
            for j, job in enumerate(tables['schedule_jobs'], 1):
                qty = joint_schedule.requirement(job['qty'], bom['qty'], bom['scrap_allowance'], quantum)
                tables['joint_demands'].append(dict(id=f'{key}-D{i:03}-{j}', study_id=key, job_id=job['id'], binding_id=bid,
                    required_qty=float(qty), unit=material['unit'], basis='自编整批需求：批量×BOM单耗×(1+损耗)，按绑定步长向上取整；不是实际领料。'))
                total[material['id'], material['unit']] += qty
        for i, ((mid, unit), qty) in enumerate(sorted(total.items()), 1):
            amount = qty / 2 if n == 1 and mid == target else qty
            tables['joint_supplies'].append(dict(id=f'{key}-L{i:03}', study_id=key, material_id=mid, lot=f'SIM-SHARED-261009-{n:02}-{i:03}',
                unit=unit, qty=float(amount), unavailable_qty=0, available_from='2026-10-09T08:00:00', status='可预留', kind='期初假设',
                reference=f'SIM-SHARED-SUPPLY-{n:02}-{i:03}', basis='两个批次共享一池；案例之间独立。硅钢仅够一批/充足为对照变量，其余物料均够两批；非账面库存。'))
        material_study = dict(id=key, name=name, crew_study_id=CR, version='SHARED-MATERIAL-V1', owner_id='E00001',
            scope='CP.00008.A 两批各6台，共12台；同物料同单位供给跨批次共用。两案例独立，不累加供给。',
            assumptions='B001交期较早、B002优先级较高；唯一对照变量为硅钢供给量。按派序先占、无抢占、无自动释放。',
            reference=f'SIM-SHARED-MATERIAL-{n:03}')
        for field, ds in [('binding_count', 'joint_bindings'), ('demand_count', 'joint_demands'), ('supply_count', 'joint_supplies')]:
            material_study[field] = sum(r['study_id'] == key for r in tables[ds])
        tables['joint_studies'].append(material_study)
    profiles = []
    for policy in ('due', 'priority'):
        base_tables = {ds: tables[ds] for ds in RESOURCE[1:]}
        base = dict(tables=base_tables, result=finite_schedule.analyze(study, base_tables, refs, policy))
        crew_tables = {ds: tables[ds] for ds in CREW[1:]}
        parent = dict(base=base, tables=crew_tables, result=crew_schedule.analyze(crew_study, crew_tables, base, refs))
        for ms in tables['joint_studies']:
            mt = {ds: [r for r in tables[ds] if r['study_id'] == ms['id']] for ds in MATERIAL[1:]}
            result = joint_schedule.analyze(ms, mt, parent, refs)
            profiles.append(dict(id=ms['id'], policy=policy, state=result['state'], issues=result['issues'], summary=result['summary'],
                                 jobs=result['jobs'], balances=[b for b in result['balances'] if b['material_id'] == target]))
    return dict(synthetic=True, source='Existing public XLSX facts; read-only generation', schemas={ds: SCHEMAS[ds] for ds in DATASETS},
                tables=tables, target_material=target, profiles=profiles)


if __name__ == '__main__':
    payload = generate()
    target = ROOT/'data/shared_material_scenario.json'
    target.parent.mkdir(exist_ok=True)
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps(dict(counts={ds: len(rows) for ds, rows in payload['tables'].items()}, target=payload['target_material'], profiles=payload['profiles']), ensure_ascii=False))
