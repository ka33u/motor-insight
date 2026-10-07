"""Bounded reads; instrument-use histories stay whole across identity changes."""
from collections import defaultdict
from . import first_piece as engine, spc_data, analytics, metrology
from .models import Record

LIMIT = 50000


def load(study_id=''):
    records = {}
    tables = defaultdict(list)

    def take(ds, query=None):
        qs = spc_data.queryset(ds)
        if query is not None:
            qs = qs.filter(**query)
        rows = list(qs.order_by('business_key')[:LIMIT+1])
        for r in rows:
            records[ds, r.business_key] = r
        if len(rows) > LIMIT or len(records) > LIMIT:
            raise ValueError('首件依据超过50000条受控规模，请拆分范围；未截断计算')
        return rows

    def keyed(ds, keys):
        keys = sorted(k for k in set(keys) if k)
        for start in range(0, len(keys), 300):
            take(ds, {'business_key__in': keys[start:start+300]})

    for ds in ('process_specs', 'process_check_plans', 'process_checks', 'process_readings',
               'metrology_instruments', 'metrology_rules', 'metrology_calibrations', 'metrology_notices', 'metrology_reviews'):
        take(ds)
    # Include every version of a series that ever named a process reading, even
    # if a later row changes stage or removes the process reference.
    series = set(Record.objects.filter(dataset='metrology_uses').exclude(values__process_reading_id=None).values_list('values__series', flat=True).distinct()[:LIMIT+1])
    if len(series) > LIMIT:
        raise ValueError('仪器使用系列超过受控规模；未截断计算')
    keys = sorted(k for k in series if k)
    for start in range(0, len(keys), 300):
        take('metrology_uses', {'values__series__in': keys[start:start+300]})
    vals = lambda ds: [r.values for (name, _), r in records.items() if name == ds]
    keyed('operations', (r.get('operation_id') for r in vals('process_check_plans')))
    ops = vals('operations')
    keyed('work_orders', (r.get('work_order_id') for r in ops))
    keyed('batches', (r.get('object_id') for r in ops if r.get('object_type') != '整机'))
    keyed('units', (r.get('object_id') for r in ops if r.get('object_type') == '整机'))
    keyed('equipment', (r.get('equipment_id') for r in ops))
    keyed('employees', (r.get('inspector_id') for r in vals('process_checks')))
    study = None
    if study_id:
        row = spc_data.queryset('launch_studies').get(business_key=study_id)
        records['launch_studies', study_id] = row
        study = row.values
        clearances = take('launch_clearances', {'values__study_id': study_id})
        keyed('work_orders', (r.values.get('work_order_id') for r in clearances))
        keyed('routes', (r.values.get('route_id') for r in clearances))
    products = sorted({r.get('product_id') for r in vals('work_orders') if r.get('product_id')})
    keyed('products', products)
    for start in range(0, len(products), 300):
        take('routes', {'values__product_id__in': products[start:start+300]})
    sources = []
    for (ds, key), r in sorted(records.items()):
        tables[ds].append(r.values)
        sources.append(spc_data.source(r))
    facts = [dict(dataset=ds, key=k, values=r.values) for (ds, k), r in sorted(records.items())]
    result = engine.analyze(tables, analytics.AS_OF)
    target = engine.targets(tables, result, study, analytics.AS_OF) if study else None
    return dict(result=result, targets=target, sources=sources,
                source_hash=metrology.digest(dict(facts=facts, sources=sources)), rule_hash=engine.rule_hash())
