"""Capture explicit synthetic order/BOM snapshots as Excel input, not live edits."""
import json
import os
import sys
from collections import defaultdict
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
import django
django.setup()
from app.models import Record
from app.schema import SCHEMAS
from app import order_baseline as engine, joint_schedule_data
from app.order_baseline_contract import bundle_hash, source_hash, signature
from app.order_baseline_schema import DATASETS


def main():
    refs = defaultdict(dict)
    for ds in ('order_lines', 'orders', 'work_orders', 'allocations', 'products', 'bom', 'materials', 'routes', 'employees'):
        refs[ds] = {r.business_key: r.values for r in Record.objects.filter(dataset=ds)}
    work_ids = {f'MO2609-{n:06}' for n in range(289, 295)}
    selected_allocations = [a for a in refs['allocations'].values() if a['work_order_id'] in work_ids]
    orders = {a['order_line_id'] for a in selected_allocations}
    for ds, field, keys in [('units', 'work_order_id', work_ids), ('operations', 'work_order_id', work_ids), ('shipments', 'order_line_id', orders)]:
        refs[ds] = {r.business_key: r.values for r in Record.objects.filter(dataset=ds, **{'values__'+field+'__in': sorted(keys)})}
    assert not refs['units'] and not refs['operations']
    parents = {(n, p): joint_schedule_data.load(f'MP-261002-{n:03}', p) for n in (1, 2, 3, 6) for p in ('due', 'priority')}
    base = parents[1, 'due']
    jobs = base['parent']['base']['tables']['schedule_jobs']
    all_tables = {ds: [] for ds in DATASETS}
    names = ['六条订单的部分安排基线', '晚到料方案的第二版基线', '缺料方案仍保留订单缺口', '缺人员窗口不形成订单完成', '快照内容摘要不符核对', '完整BOM遗漏一行核对', '批次重复映射核对', '合成旧单耗与当前需求差异', '物料单位快照差异核对', '版本链缺少前版核对']
    for n, name in enumerate(names, 1):
        key = f'OB-261001-{n:03}'
        joint_number = {2: 3, 3: 2, 4: 6}.get(n, 1)
        study = dict(id=key, name=name, series='OBS-261001-001' if n == 2 else f'OBS-261001-{n:03}', version=2 if n in (2, 10) else 1,
                     supersedes_id='OB-261001-001' if n == 2 else None, joint_study_id=f'MP-261002-{joint_number:03}', baseline_at='2026-10-01T18:00:00',
                     owner_id='E00001', basis='自编版本化快照；从现有模拟档案核对未开工订单135台，独立安排50台；不改客户交期，不证明历史批准。')
        tables = {ds: [] for ds in DATASETS[1:]}
        bindings = {b['bom_id']: b for b in base['tables']['joint_bindings']}
        for i, job in enumerate(sorted(jobs, key=lambda j: j['id']), 1):
            allocation = next(a for a in selected_allocations if refs['work_orders'][a['work_order_id']]['product_id'] == job['product_id'])
            work, order = refs['work_orders'][allocation['work_order_id']], refs['order_lines'][allocation['order_line_id']]
            product = refs['products'][job['product_id']]
            link = dict(id=f'{key}-L{i:03}', baseline_id=key, job_id=job['id'], allocation_id=allocation['id'], order_line_id=order['id'], order_id=order['order_id'], work_order_id=work['id'], product_id=job['product_id'],
                        plan_qty=job['qty'], order_qty=order['qty'], allocation_qty=allocation['qty'], work_order_qty=work['planned_qty'], original_due=order['original_due'], due=order['due'],
                        bom_version=work['bom_version'], route_version=work['route_version'], work_status=work['status'], allocation_effective=allocation['effective'],
                        product_bom_version=product['bom_version'], product_route_version=product['route_version'], order_hash=source_hash('order_lines', order), work_hash=source_hash('work_orders', work),
                        allocation_hash=source_hash('allocations', allocation), product_hash=source_hash('products', product), note='模拟追赶安排：只安排工单部分数量。完成该批次不代表订单剩余需求全部完成。')
            bom = sorted([b for b in refs['bom'].values() if b['product_id'] == job['product_id'] and b['version'] == work['bom_version']], key=lambda b: b['id'])
            own = []
            for j, b in enumerate(bom, 1):
                binding = bindings[b['id']]
                material, route = refs['materials'][b['material_id']], refs['routes'][binding['route_id']]
                row = dict(id=f'{key}-B{i:03}-{j:02}', baseline_id=key, link_id=link['id'], source_bom_id=b['id'], material_id=material['id'], unit=material['unit'], version=b['version'], branch=b['assembly_level'],
                           unit_qty=float(b['qty']), scrap_allowance=float(b['scrap_allowance']), effective=b['effective'], quantum=float(binding['quantum']), route_id=route['id'], process=route['process'],
                           route_mandatory=route['mandatory'], bom_hash=source_hash('bom', b), route_hash=source_hash('routes', route), material_hash=source_hash('materials', material),
                           note='模拟BOM快照保留来源编号和摘要；不证明该文件于基线时点已经生成或批准。')
                if n == 8 and i == 1 and j == 1:
                    row['unit_qty'] = round(row['unit_qty']*.9, 3)
                    row['bom_hash'] = source_hash('bom', engine.frozen_bom(row, link))
                    row['note'] = '刻意构造历史单耗差异，不声称该单耗曾在原系统发布；应提示与当前来源及试排需求不一致。'
                if n == 9 and i == 1 and j == 1:
                    row['unit'] = 'g'
                    row['material_hash'] = source_hash('materials', dict(id=row['material_id'], unit='g'))
                    row['note'] = '刻意单位差异，不能把kg和g直接相加或自动换算；保留为待核对。'
                own.append(row)
            link['bom_count'] = len(own)
            link['bom_set_hash'] = signature(sorted([engine.frozen_bom(r, link) for r in own], key=lambda r: r['id']))
            tables['order_baseline_links'].append(link)
            tables['order_baseline_bom'].extend(own)
        study.update(link_count=len(tables['order_baseline_links']), bom_count=len(tables['order_baseline_bom']))
        if n == 6:
            tables['order_baseline_bom'].pop()
        if n == 7:
            tables['order_baseline_links'][-1]['job_id'] = tables['order_baseline_links'][0]['job_id']
        study['content_hash'] = '0'*64 if n == 5 else bundle_hash(study, tables)
        all_tables['order_baselines'].append(study)
        for ds, rows in tables.items():
            all_tables[ds].extend(rows)
    refs['order_baselines'] = {s['id']: s for s in all_tables['order_baselines']}
    profiles = []
    for study in all_tables['order_baselines']:
        local = {ds: [r for r in all_tables[ds] if r['baseline_id'] == study['id']] for ds in DATASETS[1:]}
        joint_number = int(study['joint_study_id'][-3:])
        for policy in ('due', 'priority'):
            result = engine.analyze(study, local, parents[joint_number, policy], refs, '2026-10-01T18:00:00')
            profiles.append(dict(id=study['id'], policy=policy, state=result['state'], summary=result['summary'], issues=result['issues'], warnings=result['warnings']))
            (ROOT/f'data/order_baseline_board_{study["id"][-3:]}_{policy}.json').write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n')
    payload = dict(synthetic=True, schemas={ds: SCHEMAS[ds] for ds in DATASETS}, tables=all_tables, profiles=profiles)
    (ROOT/'data/order_baseline_scenario.json').write_text(json.dumps(payload, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps(dict(counts={ds: len(rows) for ds, rows in all_tables.items()}, profiles=profiles), ensure_ascii=False))


if __name__ == '__main__':
    main()
