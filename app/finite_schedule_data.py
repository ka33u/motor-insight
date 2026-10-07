"""Load complete trial inputs and referenced route/capacity facts in one snapshot."""
from collections import defaultdict
from . import finite_schedule as engine,spc_data
from .models import Record
from .finite_schedule_schema import DATASETS
def load(key,policy='due'):
 study=spc_data.queryset('schedule_studies').get(business_key=key);tables={};records=[study]
 jobs=list(spc_data.queryset('schedule_jobs').filter(values__study_id=key).order_by('business_key')[:engine.MAX_ROWS+1]);keys=[r.business_key for r in jobs]
 tasks=list(spc_data.queryset('schedule_tasks').filter(values__job_id__in=keys).order_by('business_key')[:engine.MAX_TASKS+1]);task_keys=[r.business_key for r in tasks]
 table_records={'schedule_jobs':jobs,'schedule_tasks':tasks}
 for ds in ('schedule_edges','schedule_windows','schedule_blocks'):
  table_records[ds]=list(spc_data.queryset(ds).filter(values__study_id=key).order_by('business_key')[:engine.MAX_ROWS+1])
 table_records['schedule_options']=list(spc_data.queryset('schedule_options').filter(values__task_id__in=task_keys).order_by('business_key')[:engine.MAX_ROWS+1])
 if len(tasks)>engine.MAX_TASKS or any(len(v)>engine.MAX_ROWS for v in table_records.values()):raise ValueError('输入超出受控试排规模，未截断生成结果')
 for ds,rows in table_records.items():tables[ds]=[r.values for r in rows];records.extend(rows)
 refs=defaultdict(dict);wanted=defaultdict(set);wanted['employees'].add(study.values['owner_id'])
 for r in jobs:wanted['products'].add(r.values['product_id'])
 for ds in ('schedule_options','schedule_windows','schedule_blocks'):
  for r in table_records[ds]:wanted['production_resources'].add(r.values['resource_id'])
 for ds in ('routes','route_dependencies'):
  rows=list(spc_data.queryset(ds).filter(values__product_id__in=sorted(wanted['products'])).order_by('business_key')[:engine.MAX_ROWS+1])
  if len(rows)>engine.MAX_ROWS:raise ValueError('路线资料超出受控规模')
  records.extend(rows);refs[ds]={r.business_key:r.values for r in rows}
 for ds,keys in sorted(wanted.items()):
  ordered=sorted(keys)
  for n in range(0,len(ordered),200):
   rows=list(spc_data.queryset(ds).filter(business_key__in=ordered[n:n+200]));records.extend(rows);refs[ds].update({r.business_key:r.values for r in rows})
 sources=sorted([spc_data.source(r)|{'source_row_id':r.source_row_id} for r in records]+[dict(dataset=ds,key=k,missing=True) for ds,keys in wanted.items() for k in sorted(keys) if k not in refs[ds]],key=lambda s:(s['dataset'],s['key']))
 facts=sorted([dict(dataset=r.dataset,key=r.business_key,values=r.values) for r in records],key=lambda r:(r['dataset'],r['key']))
 result=engine.analyze(study.values,tables,refs,policy)
 return dict(result=result,sources=sources,source_hash=engine.digest(dict(facts=facts,sources=sources)),rule_hash=engine.rule_hash(),tables=tables)
