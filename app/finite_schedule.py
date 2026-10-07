"""Deterministic append-only finite-resource trial, with no fact writes."""
from collections import defaultdict
from datetime import timedelta
from decimal import Decimal,ROUND_CEILING
import hashlib,json
from pathlib import Path
from .finite_schedule_contract import time,issues as row_issues
from .finite_schedule_schema import DATASETS
POLICIES={'due':'应完成时间优先','priority':'批次优先级优先'}
VERSION='FINITE_APPEND_1'
NOTICE='独立合成假设；单资源容量，输入中明确批段与单台任务，单个任务在试排时不再拆分，换型与加工不跨窗口。日历按厂内墙上时间解释。仅试排，不派工、不写回工单，不证明最优。人员共享、技能有效期、物料齐套、模具与能耗尚未联立约束。'
MAX_TASKS=400;MAX_ROWS=5000
def digest(v):return hashlib.sha256(json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
def rule_hash():
 return digest({n:hashlib.sha256(Path(__file__).with_name(n).read_bytes()).hexdigest() for n in ('finite_schedule.py','finite_schedule_contract.py','finite_schedule_schema.py','finite_schedule_data.py')})
def seconds(minutes):return int((Decimal(str(minutes))*60).to_integral_value(rounding=ROUND_CEILING))
def stamp(t):return t.isoformat(timespec='seconds')
def analyze(study,tables,refs,policy='due'):
 if policy not in POLICIES:raise ValueError('试排策略无效')
 problems=[]
 def problem(s):
  if s not in problems:problems.append(s)
 for ds in DATASETS:
  for r in ([study] if ds=='schedule_studies' else tables.get(ds,[])):
   for i in row_issues(ds,r):problem(r['id']+'：'+i['field']+' '+i['message'])
 jobs=tables.get('schedule_jobs',[]);tasks=tables.get('schedule_tasks',[]);edges=tables.get('schedule_edges',[]);options=tables.get('schedule_options',[])
 windows=tables.get('schedule_windows',[]);blocks=tables.get('schedule_blocks',[])
 for field,rows in [('job_count',jobs),('task_count',tasks),('edge_count',edges),('option_count',options),('window_count',windows),('block_count',blocks)]:
  if study.get(field)!=len(rows):problem('方案声明数量不一致：'+field)
 if not jobs or not tasks:problem('方案缺少完整批次或工序任务')
 if len(tasks)>MAX_TASKS or any(len(v)>MAX_ROWS for v in tables.values()):problem('试排超过受控规模，不截断任务')
 def index(rows,name):
  result={r['id']:r for r in rows}
  if len(result)!=len(rows):problem(name+'编号重复')
  return result
 ji=index(jobs,'批次');ti=index(tasks,'任务');resources=refs.get('production_resources',{});routes=refs.get('routes',{});deps=refs.get('route_dependencies',{})
 by_job=defaultdict(list);before=defaultdict(list);after=defaultdict(list);by_option=defaultdict(list);by_window=defaultdict(list);by_block=defaultdict(list)
 for j in jobs:
  if j['study_id']!=study['id']:problem(j['id']+'：跨方案批次')
  if j['product_id'] not in refs.get('products',{}):problem(j['id']+'：配置来源缺失')
 for t in tasks:
  j=ji.get(t['job_id']);r=routes.get(t['route_id']);by_job[t['job_id']].append(t)
  if not j:problem(t['id']+'：所属批次缺失');continue
  if not r or r['product_id']!=j['product_id'] or r['version']!=j['route_version']:problem(t['id']+'：路线与配置或版本不符')
 for j in jobs:
  actual=[t['route_id'] for t in by_job[j['id']]]
  required=[r['id'] for r in routes.values() if r['product_id']==j['product_id'] and r['version']==j['route_version'] and r['mandatory']]
  if len(actual)!=j['task_count'] or not required or not set(required)<=set(actual):problem(j['id']+'：声明工序数或必需工序不完整')
  portions=[(t['route_id'],t['portion']) for t in by_job[j['id']]]
  if len(set(portions))!=len(portions):problem(j['id']+'：同路线批内份号重复')
  for route_id in set(actual):
   if sum(t['lot_qty'] for t in by_job[j['id']] if t['route_id']==route_id)!=j['qty']:problem(j['id']+'：每条路线的任务台数合计须等于独立批次台数')
 pairs=set();edge_jobs=defaultdict(list)
 for e in edges:
  a=ti.get(e['from_task_id']);b=ti.get(e['to_task_id']);dep=deps.get(e['dependency_id']);pair=(e['from_task_id'],e['to_task_id'])
  if e['study_id']!=study['id'] or not a or not b or a['job_id']!=b['job_id']:problem(e['id']+'：依赖跨批次或任务缺失');continue
  if pair in pairs:problem(e['id']+'：依赖重复')
  pairs.add(pair);before[b['id']].append(e);after[a['id']].append(e);edge_jobs[a['job_id']].append(e)
  if not dep or dep['from_route_id']!=a['route_id'] or dep['to_route_id']!=b['route_id']:problem(e['id']+'：依赖与路线依据不一致')
  if a['portion']!='BULK' and b['portion']!='BULK' and a['portion']!=b['portion']:problem(e['id']+'：单台后段依赖的批内份号不一致')
 for j in jobs:
  required={(r['from_route_id'],r['to_route_id']) for r in deps.values() if r['product_id']==j['product_id'] and r['from_route_id'] in {t['route_id'] for t in by_job[j['id']]} and r['to_route_id'] in {t['route_id'] for t in by_job[j['id']]}}
  actual={(ti[e['from_task_id']]['route_id'],ti[e['to_task_id']]['route_id']) for e in edge_jobs[j['id']]}
  if len(edge_jobs[j['id']])!=j['edge_count'] or actual!=required:problem(j['id']+'：声明依赖数或路线依赖不完整')
  for t in by_job[j['id']]:
   needed_before={a for a,b in required if b==t['route_id']};needed_after={b for a,b in required if a==t['route_id']}
   actual_before={ti[e['from_task_id']]['route_id'] for e in before[t['id']]};actual_after={ti[e['to_task_id']]['route_id'] for e in after[t['id']]}
   if actual_before!=needed_before or actual_after!=needed_after:problem(t['id']+'：批内任务前后工序不完整')
 option_pairs=set()
 for o in options:
  t=ti.get(o['task_id']);r=resources.get(o['resource_id']);p=(o['task_id'],o['resource_id']);by_option[o['task_id']].append(o)
  if p in option_pairs:problem(o['id']+'：候选资源重复')
  option_pairs.add(p)
  if not t or not r or r['capacity']!=1 or routes.get(t['route_id'],{}).get('process')!=r['process']:problem(o['id']+'：候选资源缺失、工序不符或容量不为1')
  elif r['max_batch_qty']<=0 or r['effective']>study['baseline'][:10]:problem(o['id']+'：资源台数容量或生效日期不可用')
 for ds,rows,target in [('资源窗口',windows,by_window),('不可用窗口',blocks,by_block)]:
  for w in rows:
   if w['study_id']!=study['id'] or w['resource_id'] not in resources:problem(w['id']+'：跨方案或资源缺失')
   target[w['resource_id']].append(w)
  for key,group in target.items():
   ordered=sorted(group,key=lambda w:(w['started'],w['id']))
   if any(a['finished']>b['started'] for a,b in zip(ordered,ordered[1:])):problem(ds+'重叠：'+key)
 if study.get('owner_id') not in refs.get('employees',{}):problem('负责人员来源缺失')
 # Topology is checked independently of dispatch priority.
 degree={t['id']:len(before[t['id']]) for t in tasks};queue=sorted(k for k,v in degree.items() if v==0);visited=[]
 while queue:
  k=queue.pop(0);visited.append(k)
  for e in after[k]:
   degree[e['to_task_id']]-=1
   if degree[e['to_task_id']]==0:queue.append(e['to_task_id']);queue.sort()
 if len(visited)!=len(tasks):problem('依赖存在环路；所有试排暂停')
 result=dict(state='paused' if problems else 'trial',study=study,policy=policy,policy_name=POLICIES[policy],rule_version=VERSION,notice=NOTICE,issues=problems,tasks=[],jobs=[],resources=[],summary=None)
 if problems:return result
 start=time(study['baseline']);end=time(study['horizon_end'])
 if end-start>timedelta(days=90):raise ValueError('试排窗口最多90天')
 wins={k:[(max(start,time(w['started'])),min(end,time(w['finished'])),w['id']) for w in sorted(v,key=lambda w:(w['started'],w['id'])) if time(w['finished'])>start and time(w['started'])<end] for k,v in by_window.items()}
 blocked={k:[(time(w['started']),time(w['finished']),w['id']) for w in sorted(v,key=lambda w:(w['started'],w['id']))] for k,v in by_block.items()}
 tails={k:start for k in resources};families={};assigned={};degree={k:len(before[k]) for k in ti};queue=[k for k,v in degree.items() if v==0]
 def rank(k):
  j=ji[ti[k]['job_id']];return (j['due'],j['priority'],j['id'],k) if policy=='due' else (j['priority'],j['due'],j['id'],k)
 while queue:
  queue.sort(key=rank);key=queue.pop(0);t=ti[key];j=ji[t['job_id']];r=routes[t['route_id']]
  base=max(start,time(j['released']));ready=max([base]+[time(assigned[e['from_task_id']]['finished'])+timedelta(seconds=seconds(e['lag_minutes'])) for e in before[key] if assigned[e['from_task_id']]['state']=='scheduled'])
  failures=[e['from_task_id'] for e in before[key] if assigned[e['from_task_id']]['state']!='scheduled'];duration=seconds(Decimal(str(t['unit_minutes']))*t['lot_qty']);candidates=[]
  roots=sorted({root for k in failures for root in assigned[k]['root_tasks']})
  if failures:reason='前序未排入：'+'、'.join(failures)
  else:
   viable=[o for o in by_option[key] if t['lot_qty']<=resources[o['resource_id']]['max_batch_qty']]
   reason='没有登记候选资源' if not by_option[key] else '批量超过所有候选资源容量' if not viable else '候选资源的连续可用窗口不足'
   for o in viable:
    resource=o['resource_id'];setup=seconds(o['setup_minutes']) if families.get(resource)!=j['family'] else 0;length=timedelta(seconds=setup+duration)
    for left,right,window in wins.get(resource,[]):
     at=max(ready,tails[resource],left)
     for a,b,_ in blocked.get(resource,[]):
      if at<b and at+length>a:at=b
     if at+length<=right:
      candidates.append((at+length,at,resource,o['id'],window,setup));break
  row=dict(id=key,job_id=j['id'],product_id=j['product_id'],route_id=r['id'],process=r['process'],branch=r['branch'],qty=t['lot_qty'],portion=t['portion'],family=j['family'],release=stamp(base),dependency_ready=stamp(ready),predecessors=[e['from_task_id'] for e in before[key]],process_minutes=duration/60,state='blocked',reason=reason,root_tasks=roots or [key],resource_id=None,option_id=None,window_id=None,started=None,process_started=None,finished=None,setup_minutes=None,wait_minutes=None)
  if candidates:
   finish,at,resource,option,window,setup=min(candidates);row.update(state='scheduled',reason='',root_tasks=[],resource_id=resource,option_id=option,window_id=window,started=stamp(at),process_started=stamp(at+timedelta(seconds=setup)),finished=stamp(finish),setup_minutes=setup/60,wait_minutes=(at-ready).total_seconds()/60);tails[resource]=finish;families[resource]=j['family']
  assigned[key]=row;result['tasks'].append(row)
  for e in after[key]:
   degree[e['to_task_id']]-=1
   if degree[e['to_task_id']]==0:queue.append(e['to_task_id'])
 for j in sorted(jobs,key=lambda j:j['id']):
  rows=[assigned[t['id']] for t in by_job[j['id']]];complete=all(r['state']=='scheduled' for r in rows);finish=max(r['finished'] for r in rows) if complete else None
  result['jobs'].append(dict(id=j['id'],product_id=j['product_id'],qty=j['qty'],due=j['due'],priority=j['priority'],state='late' if complete and finish>j['due'] else 'scheduled' if complete else 'blocked',finished=finish,lateness_minutes=max(0,(time(finish)-time(j['due'])).total_seconds()/60) if finish else None,task_count=len(rows),scheduled_count=sum(r['state']=='scheduled' for r in rows)))
 for key in sorted(by_window):
  available=0
  for a,b,_ in wins.get(key,[]):
   available+=(b-a).total_seconds()
   available-=sum(max(0,(min(b,d)-max(a,c)).total_seconds()) for c,d,_ in blocked.get(key,[]))
  rows=[r for r in result['tasks'] if r['resource_id']==key];busy=sum((time(r['finished'])-time(r['started'])).total_seconds() for r in rows)
  result['resources'].append(dict(id=key,station=resources[key]['station'],process=resources[key]['process'],available_minutes=available/60,busy_minutes=busy/60,load_percent=busy/available*100 if available else None,task_count=len(rows),windows=[dict(id=i,started=stamp(a),finished=stamp(b)) for a,b,i in wins.get(key,[])],blocks=[w for w in blocks if w['resource_id']==key]))
 result['summary']=dict(tasks=len(tasks),scheduled_tasks=sum(r['state']=='scheduled' for r in result['tasks']),blocked_tasks=sum(r['state']=='blocked' for r in result['tasks']),jobs=len(jobs),qty=sum(j['qty'] for j in jobs),complete_jobs=sum(j['state']!='blocked' for j in result['jobs']),late_jobs=sum(j['state']=='late' for j in result['jobs']),blocked_jobs=sum(j['state']=='blocked' for j in result['jobs']))
 return result
