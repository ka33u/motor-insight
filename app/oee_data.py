"""Current inputs and original Excel row provenance, read in the caller's snapshot."""
from . import oee,spc_data,analytics
from .oee_schema import DATASETS
def load(key):
 study_record=spc_data.queryset('oee_studies').get(business_key=key);records=[study_record];tables={}
 for ds in DATASETS[1:]:
  rows=list(spc_data.queryset(ds).filter(values__study_id=key).order_by('business_key')[:10001]);records.extend(rows);tables[ds]=[r.values for r in rows]
  if len(rows)>10000:raise ValueError('独立效率方案每表最多10000行，请拆分完整采集范围')
 resource_record=spc_data.queryset('production_resources').filter(business_key=study_record.values['resource_id']).first()
 if resource_record:records.append(resource_record)
 keys={w['product_id'] for w in tables['oee_windows']};products={}
 ordered=sorted(keys)
 for offset in range(0,len(ordered),400):
  for row in spc_data.queryset('products').filter(business_key__in=ordered[offset:offset+400]).order_by('business_key'):
   records.append(row);products[row.business_key]={k:v for k,v in row.values.items() if k in ('id','name','model','family','power_kw','voltage_v','poles','frame','mount','ip','insulation','bom_version','route_version','drawing')}
 resource={k:v for k,v in resource_record.values.items() if k in ('id','equipment_id','process','station','capacity','max_batch_qty','effective','basis')} if resource_record else None
 sources=sorted([spc_data.source(r) for r in records],key=lambda s:(s['dataset'],s['key']))
 missing=[dict(dataset='products',key=k,missing=True) for k in sorted(keys-set(products))]
 if not resource:missing.append(dict(dataset='production_resources',key=study_record.values['resource_id'],missing=True))
 sources+=missing
 result=oee.analyze(study_record.values,tables,resource,products,analytics.AS_OF)
 return dict(result=result,tables=tables,resource=resource,products=products,sources=sources,source_hash=oee.digest(dict(facts=sorted([dict(dataset=r.dataset,key=r.business_key,values=r.values) for r in records],key=lambda r:(r['dataset'],r['key'])),sources=sources)),rule_hash=oee.rule_hash())
