"""Complete current capture and referenced original Excel rows, in one snapshot."""
from collections import defaultdict
from . import curing, spc_data, analytics
from .curing_schema import DATASETS

LIMITS=dict(cure_profiles=2000,cure_channels=10000,cure_runs=1000,cure_loads=10000,cure_samples=50000)


def load():
    tables={};records=[];refs=defaultdict(dict);missing=[]
    for ds in DATASETS:
        rows=list(spc_data.queryset(ds).order_by('business_key')[:LIMITS[ds]+1])
        if len(rows)>LIMITS[ds]:raise ValueError('固化当前采集超出完整读取上限：'+ds+'；请拆分采集范围，未截断试算')
        records+=rows;tables[ds]=[r.values for r in rows]
    def read(ds,keys):
        ordered=sorted(set(keys)-set(refs[ds]))
        for offset in range(0,len(ordered),400):
            rows=list(spc_data.queryset(ds).filter(business_key__in=ordered[offset:offset+400]).order_by('business_key'))
            records.extend(rows);refs[ds].update({r.business_key:r.values for r in rows})
        missing.extend(dict(dataset=ds,key=k,missing=True) for k in ordered if k not in refs[ds])
    read('operations',(r['operation_id'] for r in tables['cure_loads']))
    read('batches',(r['batch_id'] for r in tables['cure_loads']))
    read('work_orders',(r['work_order_id'] for r in refs['batches'].values()))
    read('products',[r['product_id'] for r in refs['work_orders'].values()]+[r['product_id'] for r in tables['cure_profiles']])
    read('production_resources',(r['resource_id'] for r in tables['cure_runs']))
    read('equipment',(r['equipment_id'] for r in tables['cure_runs']))
    for ds,field,keys in [('routes','product_id',list(refs['products'])),('allocations','work_order_id',list(refs['work_orders']))]:
        for offset in range(0,len(keys),400):
            rows=list(spc_data.queryset(ds).filter(**{'values__'+field+'__in':keys[offset:offset+400]}).order_by('business_key')[:20001])
            if len(rows)>20000:raise ValueError('固化关系超过完整读取上限：'+ds)
            records.extend(rows);refs[ds].update({r.business_key:r.values for r in rows})
    read('order_lines',(r['order_line_id'] for r in refs['allocations'].values()))
    sources=sorted([dict(**spc_data.source(r),record_id=r.pk) for r in records]+missing,key=lambda r:(r['dataset'],r['key']))
    result=curing.analyze(tables,refs,analytics.AS_OF)
    return dict(result=result,tables=tables,refs=dict(refs),sources=sources,
                source_hash=curing.digest(dict(facts=sorted([dict(dataset=r.dataset,key=r.business_key,values=r.values) for r in records],key=lambda r:(r['dataset'],r['key'])),sources=sources)),rule_hash=curing.rule_hash())
