"""One-snapshot, bounded complete staffing inputs and resource reference."""
from collections import defaultdict
from . import crew_schedule as engine,finite_schedule_data,finite_schedule,spc_data
from .crew_schedule_schema import DATASETS
def load(key,policy='due'):
 study=spc_data.queryset('crew_studies').get(business_key=key);base=finite_schedule_data.load(study.values['resource_study_id'],policy);records=[study];tables={};wanted=defaultdict(set);wanted['employees'].add(study.values['owner_id'])
 for ds in DATASETS[1:]:
  rows=list(spc_data.queryset(ds).filter(values__study_id=key).order_by('business_key')[:engine.MAX_ROWS+1])
  if len(rows)>engine.MAX_ROWS:raise ValueError('人员假设超过受控规模，未截断计算')
  records.extend(rows);tables[ds]=[r.values for r in rows]
  for r in rows:
   if ds=='crew_credentials':wanted['skills'].add(r.values['skill_id'])
   if ds in ('crew_windows','crew_blocks'):wanted['employees'].add(r.values['employee_id'])
 refs=defaultdict(dict)
 def fetch(ds,keys):
  ordered=sorted(keys)
  for at in range(0,len(ordered),200):
   rows=list(spc_data.queryset(ds).filter(business_key__in=ordered[at:at+200]));records.extend(rows);refs[ds].update({r.business_key:r.values for r in rows})
 fetch('skills',wanted['skills'])
 for skill in refs['skills'].values():wanted['employees'].add(skill['employee_id'])
 fetch('employees',wanted['employees'])
 for ds in ('routes','production_resources'):
  keys={s['key'] for s in base['sources'] if s['dataset']==ds and not s.get('missing')};wanted[ds].update(keys);fetch(ds,keys)
 missing=[dict(dataset=ds,key=k,missing=True) for ds,keys in wanted.items() for k in sorted(keys) if k not in refs[ds]]
 manifest={(s['dataset'],s['key']):s for s in base['sources']}
 manifest.update({(r.dataset,r.business_key):spc_data.source(r)|{'source_row_id':r.source_row_id} for r in records});manifest.update({(s['dataset'],s['key']):s for s in missing});sources=[manifest[k] for k in sorted(manifest)]
 facts=sorted([dict(dataset=r.dataset,key=r.business_key,values=r.values) for r in records],key=lambda r:(r['dataset'],r['key']))
 result=engine.analyze(study.values,tables,base,refs)
 return dict(result=result,tables=tables,base=base,sources=sources,source_hash=finite_schedule.digest(dict(resource_source_hash=base['source_hash'],facts=facts,sources=sources)),rule_hash=engine.rule_hash())
