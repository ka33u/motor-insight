"""Read a complete bounded material trial in its caller's database snapshot."""
from collections import defaultdict
from . import joint_schedule as engine, crew_schedule_data, finite_schedule, spc_data
from .joint_schedule_schema import DATASETS


def load(key, policy='due'):
    study = spc_data.queryset('joint_studies').get(business_key=key)
    parent = crew_schedule_data.load(study.values['crew_study_id'], policy)
    records, tables, wanted, refs = [study], {}, defaultdict(set), defaultdict(dict)
    wanted['employees'].add(study.values['owner_id'])
    for ds in DATASETS[1:]:
        rows = list(spc_data.queryset(ds).filter(values__study_id=key).order_by('business_key')[:engine.MAX_ROWS+1])
        if len(rows) > engine.MAX_ROWS:
            raise ValueError('物料输入超过受控规模，未截断计算')
        records.extend(rows)
        tables[ds] = [r.values for r in rows]
        for row in rows:
            if ds == 'joint_bindings':
                wanted['bom'].add(row.values['bom_id'])
                wanted['routes'].add(row.values['route_id'])
            if ds == 'joint_supplies':
                wanted['materials'].add(row.values['material_id'])
    for job in parent['base']['tables']['schedule_jobs']:
        wanted['products'].add(job['product_id'])
    for ds in ('routes', 'production_resources'):
        wanted[ds].update(s['key'] for s in parent['sources'] if s['dataset'] == ds and not s.get('missing'))

    def fetch(ds, keys):
        keys = sorted(keys)
        for at in range(0, len(keys), 200):
            rows = list(spc_data.queryset(ds).filter(business_key__in=keys[at:at+200]))
            records.extend(rows)
            refs[ds].update({r.business_key: r.values for r in rows})

    # Inspect all BOM lines of selected products so missing bindings cannot hide.
    bom_rows = list(spc_data.queryset('bom').filter(values__product_id__in=sorted(wanted['products'])).order_by('business_key')[:engine.MAX_ROWS+1])
    if len(bom_rows) > engine.MAX_ROWS:
        raise ValueError('相关BOM超过受控规模，未截断计算')
    records.extend(bom_rows)
    refs['bom'].update({r.business_key: r.values for r in bom_rows})
    fetch('bom', wanted['bom']-set(refs['bom']))
    for bom in refs['bom'].values():
        wanted['materials'].add(bom['material_id'])
    for ds in ('products', 'materials', 'routes', 'production_resources', 'employees'):
        fetch(ds, wanted[ds])
    missing = [dict(dataset=ds, key=k, missing=True) for ds, keys in wanted.items() for k in sorted(keys) if k not in refs[ds]]
    manifest = {(s['dataset'], s['key']): s for s in parent['sources']}
    manifest.update({(r.dataset, r.business_key): spc_data.source(r) | {'source_row_id': r.source_row_id} for r in records})
    manifest.update({(s['dataset'], s['key']): s for s in missing})
    sources = [manifest[k] for k in sorted(manifest)]
    unique = {(r.dataset, r.business_key): r for r in records}
    facts = [dict(dataset=ds, key=k, values=unique[ds, k].values) for ds, k in sorted(unique)]
    result = engine.analyze(study.values, tables, parent, refs)
    # Explicit public shape: raw source values may contain prices or personnel fields.
    public_fields = dict(bom=('id', 'product_id', 'material_id', 'version', 'qty', 'scrap_allowance', 'effective', 'assembly_level'),
                         products=('id', 'model', 'bom_version', 'route_version'), materials=('id', 'name', 'unit'),
                         routes=('id', 'product_id', 'version', 'process', 'branch'), production_resources=('id', 'process', 'capacity', 'max_batch_qty'))
    public_refs = {ds: [{f: row.get(f) for f in fields} for _, row in sorted(refs[ds].items())] for ds, fields in public_fields.items()}
    return dict(result=result, tables=tables, parent=parent, references=public_refs, sources=sources,
                source_hash=finite_schedule.digest(dict(crew_source_hash=parent['source_hash'], facts=facts, sources=sources)), rule_hash=engine.rule_hash())
