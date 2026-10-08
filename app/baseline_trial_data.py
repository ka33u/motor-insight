"""Same-snapshot baseline trial and complete registered issue-history population."""
from collections import defaultdict
from . import baseline_trial as engine, order_baseline_data, spc_data, finite_schedule

PLANNING_FIELDS = dict(employees=('id', 'active', 'name'), skills=('id', 'employee_id', 'process', 'approved', 'expires', 'status'),
                       routes=('id', 'product_id', 'version', 'process', 'branch', 'mandatory'),
                       route_dependencies=('id', 'product_id', 'from_route_id', 'to_route_id'),
                       production_resources=('id', 'process', 'capacity', 'max_batch_qty', 'effective', 'station'))
HISTORY_FIELDS = ('id', 'material_id', 'lot', 'location', 'occurred', 'movement', 'qty_signed', 'work_order_id', 'reference')


def load(key, policy='due'):
    original = order_baseline_data.load(key, policy)
    refs, records = defaultdict(dict), {}
    wanted = defaultdict(set)
    # Read actual records, not incomplete export projections or invented owners.
    for source in original['sources']:
        wanted[source['dataset']].add(source['key'])
    for ds, keys in sorted(wanted.items()):
        keys = sorted(keys)
        for at in range(0, len(keys), 200):
            for row in spc_data.queryset(ds).filter(business_key__in=keys[at:at+200]):
                refs[ds][row.business_key] = row.values
                records[ds, row.business_key] = row
    works = sorted({r['work_order_id'] for r in original['tables']['order_baseline_links']})
    rows = list(spc_data.queryset('inventory_movements').filter(values__work_order_id__in=works).order_by('business_key')[:engine.MAX_ROWS+1])
    if len(rows) > engine.MAX_ROWS:
        raise ValueError('相关工单领料流水超过受控规模；未截断试算')
    for row in rows:
        refs[row.dataset][row.business_key] = row.values
        records[row.dataset, row.business_key] = row
    manifest = {(s['dataset'], s['key']): s for s in original['sources']}
    manifest.update({k: spc_data.source(r) | {'source_row_id': r.source_row_id} for k, r in records.items()})
    sources = [manifest[k] for k in sorted(manifest)]
    from .analytics import AS_OF
    cutoff = AS_OF.isoformat(timespec='seconds') if hasattr(AS_OF, 'isoformat') else AS_OF
    result = engine.analyze(original['result'], original['tables'], original['parent'], refs, cutoff)
    history = [{f: r.get(f) for f in HISTORY_FIELDS} for _, r in sorted(refs['inventory_movements'].items())]
    planning = {ds: [{f: row.get(f) for f in fields} for _, row in sorted(refs[ds].items())] for ds, fields in PLANNING_FIELDS.items()}
    return dict(result=result, original=original, issue_history=history, planning_references=planning, sources=sources,
                source_hash=finite_schedule.digest(dict(baseline=original['source_hash'], cutoff=cutoff, sources=sources,
                                                       facts=[dict(dataset=ds, key=k, values=r.values) for (ds,k), r in sorted(records.items())])),
                rule_hash=engine.rule_hash())
