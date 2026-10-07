"""Generate synthetic material inputs for normal Excel ingestion, never SQL writes."""
import json
import os
import sys
from collections import defaultdict
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
import django
django.setup()
from app.models import Record
from app.schema import SCHEMAS
from app import joint_schedule as engine, crew_schedule_data
from app.joint_schedule_schema import DATASETS


def main():
    parents = {(k, p): crew_schedule_data.load(k, p) for k in ('CR-261002-001', 'CR-261002-004') for p in ('due', 'priority')}
    normal = parents['CR-261002-001', 'due']
    jobs = normal['base']['tables']['schedule_jobs']
    product_ids = {j['product_id'] for j in jobs}
    refs = {ds: {r.business_key: r.values for r in Record.objects.filter(dataset=ds)} for ds in ('products', 'materials', 'routes', 'production_resources', 'employees')}
    refs['bom'] = {r.business_key: r.values for r in Record.objects.filter(dataset='bom', values__product_id__in=sorted(product_ids))}
    route_by_process = {(r['product_id'], r['branch'], r['process']): r for r in refs['routes'].values() if r['product_id'] in product_ids}
    # Prefixes are the existing material catalogue classification, not new codes.
    process_by_prefix = {'01.01': '冲片', '01.02': '绕线嵌线', '02.01': '装配', '02.02': '机加工', '03.01': '浸漆固化', '03.02': '装配', '04.01': '绕线嵌线', '04.02': '转子铸铝'}
    all_tables = {ds: [] for ds in DATASETS}
    profiles = []
    names = ['完整共享供给', '共享硅钢不足', '全料次日下午到达', '期初与未来分批到料', '硅钢隔离不可预留', '料齐但人员窗口缺失', 'BOM绑定不完整核对', '需求单位不一致核对', '整批需求取整不符核对', '关键物料晚于试排范围']
    for n, name in enumerate(names, 1):
        key = f'MP-261002-{n:03}'
        crew_id = 'CR-261002-004' if n == 6 else 'CR-261002-001'
        study = dict(id=key, name=name, crew_study_id=crew_id, version='MATERIAL-ASSUME-V1', owner_id='E00001', scope='6个独立未来批次、50台；当前配置BOM，与历史订单库存无自动衔接。',
                     assumptions='共享供给独立自编；整批向上取整，工序首个成功任务准备开始时预留。按派序先占，不抢占、不自动释放；一人陪同换型加工。', reference=f'SIM-JOINT-MATERIAL-{n:03}')
        tables = {ds: [] for ds in DATASETS[1:]}
        bindings = {}
        for i, bom in enumerate(sorted(refs['bom'].values(), key=lambda b: b['id']), 1):
            if bom['version'] != refs['products'][bom['product_id']]['bom_version']:
                continue
            material = refs['materials'][bom['material_id']]
            branch = '整机' if bom['assembly_level'] == '装配件包' else bom['assembly_level']
            route = route_by_process[bom['product_id'], branch, process_by_prefix[material['id'][:5]]]
            binding = dict(id=f'{key}-B{i:03}', study_id=key, bom_id=bom['id'], route_id=route['id'], quantum=1 if material['unit'] == '件' else .001,
                           basis='自编工序预留假设；保留原BOM与路线编号。kg以0.001向上取整，件以1向上取整。')
            tables['joint_bindings'].append(binding)
            bindings[bom['id']] = binding
        total = defaultdict(Decimal)
        for job in jobs:
            for bom in sorted(refs['bom'].values(), key=lambda b: b['id']):
                if bom['product_id'] != job['product_id'] or bom['id'] not in bindings:
                    continue
                binding, material = bindings[bom['id']], refs['materials'][bom['material_id']]
                qty = engine.requirement(job['qty'], bom['qty'], bom['scrap_allowance'], binding['quantum'])
                tables['joint_demands'].append(dict(id=f'{key}-D{len(tables["joint_demands"])+1:03}', study_id=key, job_id=job['id'], binding_id=binding['id'], required_qty=float(qty), unit=material['unit'],
                                                   basis='自编整批需求：批量×BOM单耗×(1+损耗)，再按绑定步长向上取整；不是实际领料。'))
                total[material['id'], material['unit']] += qty
        shared = max((m for m, u in total if m.startswith('01.01')), key=lambda m: total[m, 'kg'])
        for i, ((mid, unit), qty) in enumerate(sorted(total.items()), 1):
            lot = dict(id=f'{key}-L{i:03}', study_id=key, material_id=mid, lot=f'SIM-JM-261002-{n:02}-{i:03}', unit=unit, qty=float(qty), unavailable_qty=0,
                       available_from='2026-10-02T08:00:00', status='可预留', kind='期初假设', reference=f'SIM-JM-SUPPLY-{n:02}-{i:03}',
                       basis='自编未来供给池；不代表账面库存、在途采购承诺、检验放行或库存写回。')
            if n == 2 and mid == shared:
                lot['qty'] = float((qty * Decimal('.4')).quantize(Decimal('.001')))
            if n == 3:
                lot.update(kind='未来到料假设', available_from='2026-10-03T13:00:00')
            if n == 4 and mid == shared:
                first = (qty * Decimal('.3')).quantize(Decimal('.001'))
                lot['qty'] = float(first)
                tables['joint_supplies'].append({**lot, 'id': lot['id']+'-NEXT', 'lot': lot['lot']+'-NEXT', 'qty': float(qty-first), 'kind': '未来到料假设', 'available_from': '2026-10-03T09:00:00'})
            if n == 5 and mid == shared:
                lot.update(status='隔离', unavailable_qty=1)
            if n == 10 and mid == shared:
                lot.update(kind='未来到料假设', available_from='2026-10-06T08:00:00')
            tables['joint_supplies'].append(lot)
        if n == 7:
            removed = tables['joint_bindings'].pop()
            tables['joint_demands'] = [d for d in tables['joint_demands'] if d['binding_id'] != removed['id']]
        if n == 8:
            tables['joint_demands'][0]['unit'] = '件'
        if n == 9:
            tables['joint_demands'][0]['required_qty'] += 1
        for field, ds in [('binding_count', 'joint_bindings'), ('demand_count', 'joint_demands'), ('supply_count', 'joint_supplies')]:
            study[field] = len(tables[ds])
        all_tables['joint_studies'].append(study)
        for ds, rows in tables.items():
            all_tables[ds].extend(rows)
        for policy in ('due', 'priority'):
            result = engine.analyze(study, tables, parents[crew_id, policy], refs)
            profiles.append(dict(id=key, name=name, policy=policy, state=result['state'], summary=result['summary'], issues=result['issues']))
            (ROOT/f'data/joint_schedule_board_{n:03}_{policy}.json').write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n')
    payload = dict(synthetic=True, schemas={k: SCHEMAS[k] for k in DATASETS}, tables=all_tables, profiles=profiles)
    (ROOT/'data/joint_schedule_scenario.json').write_text(json.dumps(payload, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps(dict(counts={ds: len(rows) for ds, rows in all_tables.items()}, profiles=profiles), ensure_ascii=False))


if __name__ == '__main__':
    main()
