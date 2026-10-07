"""Build detailed independent trial assumptions from existing route identities."""
import os,sys,json
from collections import defaultdict
from datetime import datetime,timedelta
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings')
import django;django.setup()
from app.models import Record
from app.schema import SCHEMAS
from app.finite_schedule_schema import DATASETS
from app import finite_schedule
def main():
 refs={ds:{r.business_key:r.values for r in Record.objects.filter(dataset=ds)} for ds in ('products','employees','routes','route_dependencies','production_resources')}
 resources=defaultdict(list)
 for r in sorted(refs['production_resources'].values(),key=lambda r:r['id']):resources[r['process']].append(r)
 tables={ds:[] for ds in DATASETS};profiles=[];owner=sorted(refs['employees'])[0]
 names=['四日资源窗口','交期收紧','半日窗口不足','装配候选资源缺失','依赖环路核对','可用窗口重叠核对']
 for number,name in enumerate(names,1):
  key=f'SP-261002-{number:03}';end='2026-10-02T12:00:00' if number==3 else '2026-10-05T18:00:00'
  study=dict(id=key,name=name,version='SP-ASSUME-V1',baseline='2026-10-02T08:00:00',horizon_end=end,owner_id=owner,scope='独立合成试排批次；与真实工单未完量无关，不叠加到历史产量。',assumptions='资源容量1；前段批量、装配起逐台；输入明确拆分，试排不再拆分单任务。首次与跨换型族12分钟；未来窗口与交期为假设，物料、人员共享与模具暂未联立。',reference=f'SIM-APS-ASSUME-{number:03}')
  tables['schedule_studies'].append(study);used=set()
  for n,product in enumerate([8,15,22,29,36,43],1):
   product_id=f'CP.{product:05}.A';routes=sorted([r for r in refs['routes'].values() if r['product_id']==product_id],key=lambda r:r['id']);deps=sorted([r for r in refs['route_dependencies'].values() if r['product_id']==product_id],key=lambda r:r['id'])
   job_id=f'{key}-B{n:03}';qty=[6,8,10,6,8,12][n-1]
   due='2026-10-02T12:00:00' if number==2 else f'2026-10-{3 if n<4 else 4:02}T18:00:00'
   job=dict(id=job_id,study_id=key,product_id=product_id,route_version=routes[0]['version'],qty=qty,released='2026-10-02T08:00:00',due=due,priority=7-n,family='FRAME-A' if n%2 else 'FRAME-B',task_count=len(routes),edge_count=len(deps),reference=f'SIM-BATCH-{number:03}-{n:03}')
   tables['schedule_jobs'].append(job);task_ids=defaultdict(list)
   for i,r in enumerate(routes,1):
    unit_stage=r['process'] in ('装配','终检','包装')
    for portion in range(1,qty+1) if unit_stage else [0]:
     tid=f'{job_id}-T{i:02}-P{portion:03}';task_ids[r['id']].append(tid);tables['schedule_tasks'].append(dict(id=tid,job_id=job_id,route_id=r['id'],portion=f'U{portion:03}' if unit_stage else 'BULK',lot_qty=1 if unit_stage else qty,unit_minutes=r['minutes'],basis='既有合成路线分钟作为独立假设。装配、终检、包装逐台；批内份号不是实际电机SN。'))
     for opt,res in enumerate(resources[r['process']][:2],1):
      used.add(res['id'])
      if number==4 and n==1 and r['process']=='装配' and portion==1:continue
      tables['schedule_options'].append(dict(id=f'{tid}-R{opt}',task_id=tid,resource_id=res['id'],setup_minutes=12.0,basis='独立资源位按单容量演练；首次与跨族完整换型12分钟，同族0分钟。'))
   edge_number=0
   for dep in deps:
    upstream=task_ids[dep['from_route_id']];downstream=task_ids[dep['to_route_id']]
    pairs=list(zip(upstream,downstream)) if len(upstream)==len(downstream) else [(a,b) for a in upstream for b in downstream]
    for a,b in pairs:
     edge_number+=1;tables['schedule_edges'].append(dict(id=f'{job_id}-D{edge_number:03}',study_id=key,from_task_id=a,to_task_id=b,dependency_id=dep['id'],lag_minutes=dep['lag_minutes'],basis='前段批量完整后单台装配；整机后段按同一份号衔接，采用既有合成转运等待。'))
   job['task_count']=sum(len(v) for v in task_ids.values());job['edge_count']=edge_number
   if number==5 and n==1:
    dep=deps[0];tables['schedule_edges'].append(dict(id=f'{job_id}-D999',study_id=key,from_task_id=task_ids[dep['to_route_id']][0],to_task_id=task_ids[dep['from_route_id']][0],dependency_id=dep['id'],lag_minutes=5.0,basis='刻意反向依赖异常；保留资料，用于环路暂停核对。'));job['edge_count']+=1
  for n,res in enumerate(sorted(used),1):
   for day in range(2,6):
    for shift,(a,b) in enumerate([('08:00:00','12:00:00'),('13:00:00','18:00:00')],1):tables['schedule_windows'].append(dict(id=f'{key}-W{n:02}-{day}-{shift}',study_id=key,resource_id=res,started=f'2026-10-{day:02}T{a}',finished=f'2026-10-{day:02}T{b}',basis='独立模拟未来可用窗口；不沿用历史排班，不确认人员和物料。'))
   if n%6==1:tables['schedule_blocks'].append(dict(id=f'{key}-X{n:02}',study_id=key,resource_id=res,started='2026-10-02T09:00:00',finished='2026-10-02T10:00:00',reason='模拟保养占用',basis='本次假设的不可用窗口，非真实维修派单。'))
  if number==6:
   first=next(w for w in tables['schedule_windows'] if w['study_id']==key);tables['schedule_windows'].append({**first,'id':f'{key}-W99-OVERLAP','started':'2026-10-02T09:00:00','finished':'2026-10-02T11:00:00','basis':'刻意重叠窗口异常；整个方案暂停。'})
  local={ds:[r for r in rows if (r.get('study_id')==key or r.get('job_id','').startswith(key+'-') or r.get('task_id','').startswith(key+'-'))] for ds,rows in tables.items() if ds!='schedule_studies'}
  for field,ds in [('job_count','schedule_jobs'),('task_count','schedule_tasks'),('edge_count','schedule_edges'),('option_count','schedule_options'),('window_count','schedule_windows'),('block_count','schedule_blocks')]:study[field]=len(local[ds])
  for policy in finite_schedule.POLICIES:
   result=finite_schedule.analyze(study,local,refs,policy);profiles.append(dict(id=key,name=name,policy=policy,state=result['state'],summary=result['summary'],issues=result['issues']))
   path=ROOT/f'data/finite_schedule_board_{number:03}_{policy}.json';path.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
 data=dict(synthetic=True,schemas={k:SCHEMAS[k] for k in DATASETS},tables=tables,profiles=profiles)
 (ROOT/'data/finite_schedule_scenario.json').write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n')
 print(json.dumps(dict(counts={ds:len(rows) for ds,rows in tables.items()},profiles=profiles),ensure_ascii=False))
if __name__=='__main__':main()
