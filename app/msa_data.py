"""Read current Excel-backed facts and immutable source-row identities."""
from . import msa,analytics,spc_data
from .models import Record
def load(key):
 records={}
 def rows(dataset,keys=None,field=None,value=None):
  q=spc_data.queryset(dataset)
  if keys is not None:q=q.filter(business_key__in=keys)
  if field:q=q.filter(**{'values__'+field:value})
  limit={'msa_members':100,'msa_observations':5000}.get(dataset)
  result=list(q[:limit+1] if limit else q)
  if limit and len(result)>limit:raise ValueError('试验成员或观测超过当前范围，请拆分试验')
  for r in result:records[dataset,r.business_key]=r
  return [r.values for r in result]
 study=spc_data.queryset('msa_studies').get(business_key=key);records['msa_studies',key]=study
 members=rows('msa_members',field='study_id',value=key);observations=rows('msa_observations',field='study_id',value=key)
 s=study.values;units=rows('units',{m.get('unit_id') for m in members if m.get('unit_id')});employees=rows('employees',{m.get('operator_id') for m in members if m.get('operator_id')}|{s['owner_id']})
 spec=rows('test_specs',{s['spec_id']});instrument=rows('metrology_instruments',{s['instrument_id']});product=rows('products',{s['product_id']})
 calibrations=rows('metrology_calibrations',field='instrument_id',value=s['instrument_id'])
 if instrument and instrument[0].get('equipment_id'):rows('equipment',{instrument[0]['equipment_id']})
 manifests=[spc_data.source(records[k])|{'source_row_id':records[k].source_row_id} for k in sorted(records)]
 result=msa.analyze(s,members,observations,spec[0] if spec else None,instrument[0] if instrument else None,{r['id']:r for r in units},{r['id']:r for r in employees},calibrations,analytics.AS_OF)
 if not product or s['owner_id'] not in {r['id'] for r in employees} or instrument and instrument[0].get('equipment_id') and ('equipment',instrument[0]['equipment_id']) not in records:
  result['issues'].append('配置、负责人员或仪器设备引用缺失，当前暂停试算');result['result']=None;result['state']='paused'
 facts=[dict(dataset=d,key=k,values=records[d,k].values) for d,k in sorted(records)]
 return dict(result=result,sources=manifests,source_hash=msa.digest(dict(facts=facts,sources=manifests)),rule_hash=msa.rule_hash(),product=product[0] if product else None)

def point_sources(context,point):
 s=context['result']['study'];member_ids={point.get('part_member_id'),point.get('operator_member_id')}
 wanted={('msa_studies',s['id']),('msa_observations',point['id']),('metrology_instruments',s['instrument_id']),('test_specs',s['spec_id']),('products',s['product_id']),('employees',s['owner_id'])}
 for member in context['result']['members']:
  if member['id'] in member_ids:
   wanted.add(('msa_members',member['id']))
   if member.get('unit_id'):wanted.add(('units',member['unit_id']))
   if member.get('operator_id'):wanted.add(('employees',member['operator_id']))
 c=context['result']['calibration']['selected']
 if c:wanted.add(('metrology_calibrations',c['id']))
 return [r for r in context['sources'] if (r['dataset'],r['key']) in wanted]
