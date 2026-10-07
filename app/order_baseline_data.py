"""Bounded, complete order-baseline references in the caller's transaction."""
from collections import defaultdict
from . import order_baseline as engine, joint_schedule_data, spc_data
from .order_baseline_schema import DATASETS
from .order_baseline_contract import FIELDS, project, signature


def load(key, policy='due'):
    study = spc_data.queryset('order_baselines').get(business_key=key)
    parent = joint_schedule_data.load(study.values['joint_study_id'], policy)
    records, tables, refs, wanted = [study], {}, defaultdict(dict), defaultdict(set)

    def add(ds, query):
        rows = list(query.order_by('business_key')[:engine.MAX_ROWS+1])
        if len(rows) > engine.MAX_ROWS:
            raise ValueError('订单基线相关来源超出受控规模，未截断计算：'+ds)
        records.extend(rows)
        refs[ds].update({r.business_key: r.values for r in rows})
        return rows

    def fetch(ds, keys):
        keys = sorted(keys)
        for offset in range(0, len(keys), 200):
            add(ds, spc_data.queryset(ds).filter(business_key__in=keys[offset:offset+200]))

    for ds in DATASETS[1:]:
        rows = add(ds, spc_data.queryset(ds).filter(values__baseline_id=key))
        tables[ds] = [r.values for r in rows]
    add('order_baselines', spc_data.queryset('order_baselines').filter(values__series=study.values['series']))
    wanted['employees'].add(study.values['owner_id'])
    for link in tables['order_baseline_links']:
        for ds, field in [('order_lines', 'order_line_id'), ('orders', 'order_id'), ('work_orders', 'work_order_id'), ('products', 'product_id'), ('allocations', 'allocation_id')]:
            wanted[ds].add(link[field])
    for row in tables['order_baseline_bom']:
        for ds, field in [('bom', 'source_bom_id'), ('materials', 'material_id'), ('routes', 'route_id')]:
            wanted[ds].add(row[field])
    for ds, keys in list(wanted.items()):
        fetch(ds, keys)
    # Entire relevant BOM/allocation populations expose omissions and additions.
    add('bom', spc_data.queryset('bom').filter(values__product_id__in=sorted(wanted['products'])))
    add('allocations', spc_data.queryset('allocations').filter(values__work_order_id__in=sorted(wanted['work_orders'])))
    for ds in ('units', 'operations'):
        add(ds, spc_data.queryset(ds).filter(values__work_order_id__in=sorted(wanted['work_orders'])))
    add('shipments', spc_data.queryset('shipments').filter(values__order_line_id__in=sorted(wanted['order_lines'])))
    missing = [dict(dataset=ds, key=k, missing=True) for ds, keys in wanted.items() for k in sorted(keys) if k not in refs[ds]]
    manifest = {(s['dataset'], s['key']): s for s in parent['sources']}
    manifest.update({(r.dataset, r.business_key): spc_data.source(r) | {'source_row_id': r.source_row_id} for r in records})
    manifest.update({(s['dataset'], s['key']): s for s in missing})
    sources = [manifest[k] for k in sorted(manifest)]
    unique = {(r.dataset, r.business_key): r for r in records}
    facts = [dict(dataset=ds, key=k, values=unique[ds, k].values) for ds, k in sorted(unique)]
    from .analytics import AS_OF
    result = engine.analyze(study.values, tables, parent, refs, AS_OF.isoformat(timespec='seconds') if hasattr(AS_OF, 'isoformat') else AS_OF)
    public = {ds: [project(ds, row) for _, row in sorted(refs[ds].items())] for ds in FIELDS}
    for ds, fields in dict(orders=('id', 'customer_id', 'order_date', 'status'), units=('id', 'work_order_id', 'assembly_at'),
                           operations=('id', 'work_order_id', 'started', 'process', 'status'), shipments=('id', 'order_line_id', 'qty', 'shipped')).items():
        public[ds] = [{field: row.get(field) for field in fields} for _, row in sorted(refs[ds].items())]
    return dict(result=result, tables=tables, parent=parent, references=public, sources=sources,
                source_hash=signature(dict(parent_source_hash=parent['source_hash'], facts=facts, sources=sources)), rule_hash=engine.rule_hash())
