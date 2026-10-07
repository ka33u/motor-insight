"""Complete bounded reads, including competing tools and fixed parent schedules."""
from collections import defaultdict
from . import launch as engine, order_baseline_data, spc_data
from .launch_schema import DATASETS
from .launch_contract import signature


def load(key, policy='due'):
    study = spc_data.queryset('launch_studies').get(business_key=key)
    parent = order_baseline_data.load(study.values['baseline_id'], policy)
    records, tables, refs, wanted = [study], {}, defaultdict(dict), defaultdict(set)
    wanted['employees'].add(study.values['owner_id'])
    for ds in DATASETS[1:]:
        rows = list(spc_data.queryset(ds).filter(values__study_id=key).order_by('business_key')[:engine.MAX_ROWS+1])
        if len(rows) > engine.MAX_ROWS:
            raise ValueError('投产条件超过受控规模，未截断计算')
        records.extend(rows)
        tables[ds] = [r.values for r in rows]
        for row in tables[ds]:
            for field, target in [('owner_id', 'employees'), ('tool_id', 'tools')]:
                if row.get(field): wanted[target].add(row[field])
    wanted['production_resources'].update(r['resource_id'] for r in parent['parent']['parent']['base']['tables']['schedule_options'])
    for ds, keys in wanted.items():
        keys = sorted(keys)
        for start in range(0, len(keys), 200):
            rows = list(spc_data.queryset(ds).filter(business_key__in=keys[start:start+200]))
            records.extend(rows)
            refs[ds].update({r.business_key: r.values for r in rows})
    manifest = {(s['dataset'], s['key']): s for s in parent['sources']}
    manifest.update({(r.dataset, r.business_key): spc_data.source(r) | {'source_row_id': r.source_row_id} for r in records})
    manifest.update({(ds, key): dict(dataset=ds, key=key, missing=True) for ds, keys in wanted.items() for key in keys if key not in refs[ds]})
    sources = [manifest[key] for key in sorted(manifest)]
    facts = sorted([dict(dataset=r.dataset, key=r.business_key, values=r.values) for r in records], key=lambda r: (r['dataset'], r['key']))
    from .analytics import AS_OF
    result = engine.analyze(study.values, tables, parent, refs, AS_OF.isoformat(timespec='seconds') if hasattr(AS_OF, 'isoformat') else AS_OF)
    fields = dict(tools=('id', 'name', 'kind', 'equipment_id', 'uses', 'maintenance_limit', 'calibrated', 'next_due', 'status'),
                  production_resources=('id', 'equipment_id', 'process'), employees=('id', 'name'))
    public = {ds: [{f: r.get(f) for f in names} for _, r in sorted(refs[ds].items())] for ds, names in fields.items()}
    return dict(result=result, tables=tables, parent=parent, references=public, sources=sources,
                source_hash=signature(dict(parent_source_hash=parent['source_hash'], facts=facts, sources=sources)), rule_hash=engine.rule_hash())
