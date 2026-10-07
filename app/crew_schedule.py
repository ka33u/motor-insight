"""Deterministic, full-attendance worker/resource joint trial; no business writes."""
import hashlib
from collections import defaultdict
from datetime import timedelta,date
from decimal import Decimal
from pathlib import Path
from . import finite_schedule as resource
from .crew_schedule_schema import DATASETS
from .crew_schedule_contract import issues as row_issues
VERSION='CREW_RESOURCE_APPEND_1';MAX_ROWS=5000
NOTICE='独立合成联立假设；每任务一名操作员陪同完整换型和加工，设备与人员容量均为1。资格取当前技能登记与本方案窗口交集，不证明未来授权或历史作业资格。资源尾部与人员尾部共同安排，不回填空档，不证明最优；物料、模具、自动工序看护比例和正式派工未联立。'
def rule_hash():
 names=('crew_schedule.py','crew_schedule_data.py','crew_schedule_contract.py','crew_schedule_schema.py','access.py')
 return resource.digest(dict(resource_rules=resource.rule_hash(),crew={n:hashlib.sha256(Path(__file__).with_name(n).read_bytes()).hexdigest() for n in names}))
def fit(earliest,length,windows,blocks):
 """First continuous slot; all spans are half-open and blocks sorted."""
 for a,b,ids in sorted(windows):
  at=max(earliest,a)
  for x,y,_ in sorted(blocks):
   if at<y and at+length>x:at=y
  if at+length<=b:return at,ids
 return None
def spans(rows,start,end):
 return [(max(start,resource.time(w['started'])),min(end,resource.time(w['finished'])),w['id']) for w in rows if resource.time(w['finished'])>start and resource.time(w['started'])<end]
def analyze(study,tables,base,refs):
 original=base['result'];policy=original['policy'];problems=[]
 def issue(v):
  if v not in problems:problems.append(v)
 if original['state']!='trial':problems.extend('资源方案：'+v for v in original['issues'])
 for ds in DATASETS:
  for r in [study] if ds=='crew_studies' else tables.get(ds,[]):
   for v in row_issues(ds,r):issue(r['id']+'：'+v['message'])
 for f,ds in [('credential_count','crew_credentials'),('candidate_count','crew_candidates'),('window_count','crew_windows'),('block_count','crew_blocks')]:
  if study.get(f)!=len(tables.get(ds,[])):issue('方案声明数量不一致：'+f)
 if any(len(v)>MAX_ROWS for v in tables.values()):issue('人员输入超出受控规模，不截断生成结果')
 if study['resource_study_id']!=original['study']['id']:issue('资源方案身份不一致')
 if study['owner_id'] not in refs['employees']:issue('负责人员来源缺失')
 def index(rows,label):
  v={r['id']:r for r in rows}
  if len(v)!=len(rows):issue(label+'编号重复')
  return v
 credentials=index(tables.get('crew_credentials',[]),'资格');raw_tasks=index(base['tables']['schedule_tasks'],'任务');raw_jobs=index(base['tables']['schedule_jobs'],'批次');routes=refs['routes'];resources=refs['production_resources'];people=refs['employees'];skills=refs['skills'];candidates=defaultdict(list);worker_windows=defaultdict(list);worker_blocks=defaultdict(list);qualified={};eligibility=[];pairs=set()
 for c in credentials.values():
  if c['study_id']!=study['id']:issue(c['id']+'：资格跨方案')
  s=skills.get(c['skill_id']);person=people.get(s.get('employee_id')) if s else None
  if not s or not person:issue(c['id']+'：技能登记或人员档案缺失');continue
  if type(person.get('active')) is not bool:issue(c['id']+'：在职标识无效');continue
  try:
   approved=date.fromisoformat(s['approved']);expires=date.fromisoformat(s['expires'])
   if approved.isoformat()!=s['approved'] or expires.isoformat()!=s['expires'] or expires<approved or not s.get('process'):raise ValueError()
  except (TypeError,ValueError,KeyError):issue(c['id']+'：技能登记日期或工序待核对');continue
  if s['status'] not in ['有效','暂停','撤销','已暂停','已撤销','已过期','待审批']:issue(c['id']+'：技能登记状态未知');continue
  left=max(resource.time(c['valid_from']),resource.time(s['approved']+'T00:00:00'));right=min(resource.time(c['valid_until']),resource.time(s['expires']+'T00:00:00')+timedelta(days=1))
  active=person['active'] and s['status']=='有效' and left<right
  qualified[c['id']]=dict(employee_id=s['employee_id'],skill_id=s['id'],process=s['process'],left=left,right=right,eligible=active)
  eligibility.append(dict(id=c['id'],employee_id=s['employee_id'],skill_id=s['id'],process=s['process'],registered_status=s['status'],registered_approved=s['approved'],registered_expires=s['expires'],assumed_from=c['valid_from'],assumed_until=c['valid_until'],effective_from=resource.stamp(left) if active else None,effective_until=resource.stamp(right) if active else None,eligible=active,reason='' if active else '当前人员/技能登记状态或资格假设交集不可用'))
 for c in tables.get('crew_candidates',[]):
  t=raw_tasks.get(c['task_id']);q=qualified.get(c['credential_id'])
  if c['study_id']!=study['id'] or not t or not q:issue(c['id']+'：跨方案、任务或资格缺失');continue
  if q['process']!=routes.get(t['route_id'],{}).get('process'):issue(c['id']+'：候选人员资格工序与任务不符')
  pair=(c['task_id'],q['employee_id'])
  if pair in pairs:issue(c['id']+'：同任务人员候选重复')
  pairs.add(pair);candidates[c['task_id']].append((c,q))
 for ds,group in [('crew_windows',worker_windows),('crew_blocks',worker_blocks)]:
  for w in tables.get(ds,[]):
   if w['study_id']!=study['id'] or w['employee_id'] not in people:issue(w['id']+'：窗口跨方案或工号缺失')
   group[w['employee_id']].append(w)
  for employee,rows in group.items():
   ordered=sorted(rows,key=lambda w:(w['started'],w['id']))
   if any(a['finished']>b['started'] for a,b in zip(ordered,ordered[1:])):issue(ds+'存在重叠：'+employee)
 result=dict(state='paused' if problems else 'trial',study=study,resource_study=original['study'],policy=policy,policy_name=original['policy_name'],rule_version=VERSION,notice=NOTICE,issues=problems,credentials=eligibility,tasks=[],jobs=[],resources=[],workers=[],summary=None,resource_reference=dict(summary=original['summary'],notice='相同资源输入的设备试排参考；没有人员约束。差值来自两个启发式输出，不是人员效率因果估计。'))
 if problems:return result
 start=resource.time(original['study']['baseline']);end=resource.time(original['study']['horizon_end']);rw=defaultdict(list);rb=defaultdict(list);before=defaultdict(list);after=defaultdict(list);options=defaultdict(list)
 for w in base['tables']['schedule_windows']:rw[w['resource_id']].append(w)
 for w in base['tables']['schedule_blocks']:rb[w['resource_id']].append(w)
 for e in base['tables']['schedule_edges']:before[e['to_task_id']].append(e);after[e['from_task_id']].append(e)
 for o in base['tables']['schedule_options']:options[o['task_id']].append(o)
 resource_spans={k:spans(v,start,end) for k,v in rw.items()};worker_spans={k:spans(v,start,end) for k,v in worker_windows.items()}
 resource_blocks={k:[(resource.time(w['started']),resource.time(w['finished']),w['id']) for w in v] for k,v in rb.items()};employee_blocks={k:[(resource.time(w['started']),resource.time(w['finished']),w['id']) for w in v] for k,v in worker_blocks.items()}
 resource_tails=defaultdict(lambda:start);worker_tails=defaultdict(lambda:start);families={};assigned={};degree={k:len(before[k]) for k in raw_tasks};queue=[k for k,v in degree.items() if v==0]
 def rank(k):
  j=raw_jobs[raw_tasks[k]['job_id']];return (j['due'],j['priority'],j['id'],k) if policy=='due' else (j['priority'],j['due'],j['id'],k)
 templates={t['id']:t for t in original['tasks']}
 while queue:
  queue.sort(key=rank);key=queue.pop(0);task=raw_tasks[key];job=raw_jobs[task['job_id']];ready=max([start,resource.time(job['released'])]+[resource.time(assigned[e['from_task_id']]['finished'])+timedelta(seconds=resource.seconds(e['lag_minutes'])) for e in before[key] if assigned[e['from_task_id']]['state']=='scheduled'])
  failed=[e['from_task_id'] for e in before[key] if assigned[e['from_task_id']]['state']!='scheduled'];choices=[];root_tasks=sorted({root for k in failed for root in assigned[k]['root_tasks']});duration=resource.seconds(Decimal(str(task['unit_minutes']))*task['lot_qty'])
  allowed_options=[o for o in options[key] if task['lot_qty']<=resources[o['resource_id']]['max_batch_qty']];allowed_people=[(c,q) for c,q in candidates[key] if q['eligible']]
  reason='前序未排入：'+'、'.join(failed) if failed else '没有符合批量的候选资源' if not allowed_options else '任务未登记人员候选' if not candidates[key] else '没有按人员/技能登记及资格假设可用的候选' if not allowed_people else '设备、人员与资格没有共同连续可用窗口'
  if not failed:
   for o in allowed_options:
    res=o['resource_id'];setup=resource.seconds(o['setup_minutes']) if families.get(res)!=job['family'] else 0;length=timedelta(seconds=setup+duration);resource_only=fit(max(ready,resource_tails[res]),length,resource_spans.get(res,[]),resource_blocks.get(res,[]))
    if not resource_only:continue
    for c,q in allowed_people:
     employee=q['employee_id'];joint=[]
     for a,b,resource_window in resource_spans.get(res,[]):
      for x,y,worker_window in worker_spans.get(employee,[]):
       left=max(a,x,q['left']);right=min(b,y,q['right'])
       if left<right:joint.append((left,right,(resource_window,worker_window)))
     slot=fit(max(ready,resource_tails[res],worker_tails[employee]),length,joint,resource_blocks.get(res,[])+employee_blocks.get(employee,[]))
     if slot:
      at,(resource_window,worker_window)=slot;choices.append((at+length,at,res,employee,o['id'],c['id'],q['skill_id'],c['credential_id'],resource_window,worker_window,setup,resource_only[0]))
  row={**templates[key],**dict(state='blocked',reason=reason,root_tasks=root_tasks or [key],dependency_ready=resource.stamp(ready),process_minutes=duration/60,resource_id=None,employee_id=None,skill_id=None,credential_id=None,candidate_id=None,option_id=None,window_id=None,worker_window_id=None,started=None,process_started=None,finished=None,setup_minutes=None,wait_minutes=None,resource_ready=None,staff_additional_wait_minutes=None)}
  if choices:
   finish,at,res,employee,option,candidate,skill,credential,resource_window,worker_window,setup,resource_ready=min(choices);row.update(state='scheduled',reason='',root_tasks=[],resource_id=res,employee_id=employee,skill_id=skill,credential_id=credential,candidate_id=candidate,option_id=option,window_id=resource_window,worker_window_id=worker_window,started=resource.stamp(at),process_started=resource.stamp(at+timedelta(seconds=setup)),finished=resource.stamp(finish),setup_minutes=setup/60,wait_minutes=(at-ready).total_seconds()/60,resource_ready=resource.stamp(resource_ready),staff_additional_wait_minutes=(at-resource_ready).total_seconds()/60);resource_tails[res]=finish;worker_tails[employee]=finish;families[res]=job['family']
  assigned[key]=row;result['tasks'].append(row)
  for e in after[key]:
   degree[e['to_task_id']]-=1
   if degree[e['to_task_id']]==0:queue.append(e['to_task_id'])
 references={j['id']:j for j in original['jobs']}
 for job in sorted(raw_jobs.values(),key=lambda j:j['id']):
  rows=[t for t in result['tasks'] if t['job_id']==job['id']];complete=all(t['state']=='scheduled' for t in rows);finish=max(t['finished'] for t in rows) if complete else None;previous=references[job['id']]['finished']
  result['jobs'].append(dict(id=job['id'],product_id=job['product_id'],qty=job['qty'],priority=job['priority'],due=job['due'],finished=finish,state='late' if finish and finish>job['due'] else 'scheduled' if finish else 'blocked',lateness_minutes=max(0,(resource.time(finish)-resource.time(job['due'])).total_seconds()/60) if finish else None,resource_reference_finished=previous,completion_delta_minutes=(resource.time(finish)-resource.time(previous)).total_seconds()/60 if finish and previous else None,task_count=len(rows),scheduled_count=sum(t['state']=='scheduled' for t in rows)))
 def capacity(k,windows,blocks):
  return sum((b-a).total_seconds()-sum(max(0,(min(b,y)-max(a,x)).total_seconds()) for x,y,_ in blocks.get(k,[])) for a,b,_ in windows.get(k,[]))/60
 for old in original['resources']:
  rows=[t for t in result['tasks'] if t['resource_id']==old['id']];busy=sum((resource.time(t['finished'])-resource.time(t['started'])).total_seconds()/60 for t in rows)
  result['resources'].append({**old,'busy_minutes':busy,'load_percent':100*busy/old['available_minutes'] if old['available_minutes'] else None,'task_count':len(rows)})
 for employee in sorted(set(worker_windows)|{q['employee_id'] for q in qualified.values()}):
  rows=[t for t in result['tasks'] if t['employee_id']==employee];available=capacity(employee,worker_spans,employee_blocks);busy=sum((resource.time(t['finished'])-resource.time(t['started'])).total_seconds()/60 for t in rows)
  result['workers'].append(dict(id=employee,name=people[employee]['name'],available_minutes=available,busy_minutes=busy,load_percent=busy/available*100 if available else None,task_count=len(rows),windows=[dict(id=i,started=resource.stamp(a),finished=resource.stamp(b)) for a,b,i in worker_spans.get(employee,[])],blocks=worker_blocks.get(employee,[])))
 result['summary']=dict(tasks=len(raw_tasks),scheduled_tasks=sum(t['state']=='scheduled' for t in result['tasks']),blocked_tasks=sum(t['state']=='blocked' for t in result['tasks']),jobs=len(raw_jobs),qty=sum(j['qty'] for j in raw_jobs.values()),complete_jobs=sum(j['state']!='blocked' for j in result['jobs']),late_jobs=sum(j['state']=='late' for j in result['jobs']),blocked_jobs=sum(j['state']=='blocked' for j in result['jobs']),staff_delayed_tasks=sum(t['staff_additional_wait_minutes'] is not None and t['staff_additional_wait_minutes']>0 for t in result['tasks']))
 return result
