"""Independent staffing cases over the unchanged 50-unit resource input."""
import json,os,sys
from collections import defaultdict
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings')
import django;django.setup()
from app.models import Record
from app.schema import SCHEMAS
from app import crew_schedule,finite_schedule_data
from app.crew_schedule_schema import DATASETS
def main():
 refs={ds:{r.business_key:r.values for r in Record.objects.filter(dataset=ds)} for ds in ('employees','skills','routes','production_resources')};by_process=defaultdict(list)
 for s in sorted(refs['skills'].values(),key=lambda s:(s['employee_id'],s['id'])):
  if s['status']=='有效' and s['approved']<='2026-10-02'<=s['expires'] and refs['employees'][s['employee_id']]['active']:by_process[s['process']].append(s)
 bases={policy:finite_schedule_data.load('SP-261002-001',policy) for policy in ('due','priority')};base=bases['due'];processes=sorted({t['process'] for t in base['result']['tasks']});used=set();normal={}
 for process in processes:
  pool=[s for s in by_process[process] if s['employee_id'] not in used][:2];assert len(pool)==2,process;normal[process]=pool;used.update(s['employee_id'] for s in pool)
 tables={ds:[] for ds in DATASETS};profiles=[]
 names=['完整人员池','冲片叠压共享一人','冲片资格假设窗口过短','冲片未登记未来人员窗口','人员窗口重叠核对','候选资格工序不符核对']
 for number,name in enumerate(names,1):
  key=f'CR-261002-{number:03}';study=dict(id=key,name=name,resource_study_id='SP-261002-001',version='CREW-ASSUME-V1',owner_id='E00001',assumptions='每任务一人全程陪同换型与加工；可用时段与资格停止点均是假设。候选可替代资源固定员工档案参考；设备换型族跨班保持。物料、模具、多机照看与正式派工未联立。',reference=f'SIM-CREW-ASSUME-{number:03}');tables['crew_studies'].append(study);credentials={};people=set()
  for i,process in enumerate(processes,1):
   pool=normal[process]
   if number==2 and process in ('冲片','叠压'):pool=[next(s for s in by_process[process] if s['employee_id']=='E00021')]
   credentials[process]=[]
   for j,skill in enumerate(pool,1):
    cid=f'{key}-Q{i:02}-{j}';credentials[process].append(cid);people.add(skill['employee_id']);tables['crew_credentials'].append(dict(id=cid,study_id=key,skill_id=skill['id'],valid_from='2026-10-02T08:00:00',valid_until='2026-10-02T09:00:00' if number==3 and process=='冲片' else '2026-10-05T18:00:00',basis='资格取既有技能登记与本方案窗口交集。短窗口为刻意独立假设，不改技能台账、不声明真实撤权。'))
  index=0
  for task in sorted(base['result']['tasks'],key=lambda t:t['id']):
   for cid in credentials[task['process']]:
    index+=1
    if number==6 and index==1:cid=credentials[next(p for p in processes if p!=task['process'])][0]
    tables['crew_candidates'].append(dict(id=f'{key}-C{index:04}',study_id=key,task_id=task['id'],credential_id=cid,basis='本方案明确候选；同一工号跨设备和跨工序共同占用，员工不能重复计容量。'))
  chip_people={refs['skills'][c['skill_id']]['employee_id'] for c in tables['crew_credentials'] if c['study_id']==key and refs['skills'][c['skill_id']]['process']=='冲片'}
  for i,employee in enumerate(sorted(people),1):
   if number==4 and employee in chip_people:continue
   for day in range(2,6):
    for shift,(a,b) in enumerate([('08:00:00','12:00:00'),('13:00:00','18:00:00')],1):tables['crew_windows'].append(dict(id=f'{key}-W{i:02}-{day}-{shift}',study_id=key,employee_id=employee,started=f'2026-10-{day:02}T{a}',finished=f'2026-10-{day:02}T{b}',basis='独立未来人员窗口假设；不是历史出勤，也不确认实际未来排班。'))
  employee=sorted(chip_people)[0];tables['crew_blocks'].append(dict(id=key+'-X01',study_id=key,employee_id=employee,started='2026-10-02T09:00:00',finished='2026-10-02T10:00:00',reason='模拟人员培训不可用',basis='独立人员不可用假设，不改考勤或工时。'))
  if number==5:
   w=next(w for w in tables['crew_windows'] if w['study_id']==key);tables['crew_windows'].append({**w,'id':key+'-W99-OVERLAP','started':'2026-10-02T09:00:00','finished':'2026-10-02T11:00:00','basis':'刻意人员窗口重叠，保留用于整个方案暂停。'})
  local={ds:[r for r in rows if r.get('study_id')==key] for ds,rows in tables.items() if ds!='crew_studies'}
  for f,ds in [('credential_count','crew_credentials'),('candidate_count','crew_candidates'),('window_count','crew_windows'),('block_count','crew_blocks')]:study[f]=len(local[ds])
  for policy in bases:
   r=crew_schedule.analyze(study,local,bases[policy],refs);profiles.append(dict(id=key,name=name,policy=policy,state=r['state'],summary=r['summary'],issues=r['issues']));(ROOT/f'data/crew_schedule_board_{number:03}_{policy}.json').write_text(json.dumps(r,ensure_ascii=False,indent=2)+'\n')
 data=dict(synthetic=True,schemas={k:SCHEMAS[k] for k in DATASETS},tables=tables,profiles=profiles);(ROOT/'data/crew_schedule_scenario.json').write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n');print(json.dumps(dict(counts={ds:len(r) for ds,r in tables.items()},profiles=profiles),ensure_ascii=False))
if __name__=='__main__':main()
