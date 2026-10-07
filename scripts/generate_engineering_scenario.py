"""Deterministic synthetic task detail; writes XLSX input JSON, never facts."""
import os,sys,json
from pathlib import Path
from datetime import date,timedelta
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings')
import django;django.setup()
from app.models import Record
from app.schema import SCHEMAS
from app.analytics import AS_OF
projects=list(Record.objects.filter(dataset='projects').order_by('business_key').values_list('values',flat=True))
changes=list(Record.objects.filter(dataset='engineering_changes').order_by('business_key').values_list('values',flat=True))
staff=sorted(r['id'] for r in Record.objects.filter(dataset='employees').values_list('values',flat=True) if r['department_id']=='D03' and r['active'])
tables={'project_milestones':[],'change_actions':[]}
names=['需求与安装条件核对','图纸与接口校核','BOM及工艺校核','样机试制记录','专项验证资料整理','转产交接记录']
for i,p in enumerate(projects,1):
    due=date.fromisoformat(p['planned_end']);end=date.fromisoformat(p['actual_end']) if p['actual_end'] else None
    done=6 if end else 3+(i%2)
    for j,name in enumerate(names,1):
        planned_start=due-timedelta(days=(6-j)*2+1);planned_end=due-timedelta(days=(6-j)*2)
        finished=(planned_end+timedelta(days=1 if j==6 else 0)) if j<=done else None
        started=planned_start if j<=done+1 else None
        tables['project_milestones'].append(dict(id=f'RDMS26-{i:03d}-{j:02d}',project_id=p['id'],sequence=j*10,name=name,planned_start=planned_start.isoformat(),planned_end=planned_end.isoformat(),actual_start=started.isoformat() if started else None,actual_end=finished.isoformat() if finished else None,owner_id=p['owner_id'] if j in [1,6] else staff[(i+j)%len(staff)],status='已完成' if finished else '进行中' if started else '未开始',outcome=('模拟阶段记录已整理，记录编号仅为台账索引，原始签核附件尚未接入' if finished else '等待专项验证结果及工艺确认资料' if j==5 else '尚未收到本阶段完成反馈'),record_no=f'RDJL26-{i:03d}-{j:02d}' if finished else None))
    if end:assert tables['project_milestones'][-1]['actual_end']==p['actual_end']
actions=[('旧版图纸回收','核对关联配置旧版接线盒安装图纸的发放和回收记录'),('工艺文件换版','核对BOM登记版本及工位作业指导书换版记录'),('首批版本核对','核对关联配置首批工单引用版本，不代替首件或检验批准'),('存量材料核查','核查接线盒及相关存量件适用性，旧料处置需另行批准')]
for i,c in enumerate(changes,1):
    effective=date.fromisoformat(c['effective'])
    for j,(kind,description) in enumerate(actions,1):
        created=effective-timedelta(days=5);due=effective+timedelta(days=j-2)
        completed=due+timedelta(days=int(i%3==0 and j==3)) if i<=3 or j<=2 else None
        tables['change_actions'].append(dict(id=f'ECNA26-{i:03d}-{j:02d}',change_id=c['id'],kind=kind,owner_id=staff[(i+j)%len(staff)],created=created.isoformat(),due=due.isoformat(),completed=completed.isoformat() if completed else None,status='已完成' if completed else '待反馈',description=description,result='模拟执行台账已登记，附件和现场实施仍需核对' if completed else None,record_no=f'ECNJL26-{i:03d}-{j:02d}' if completed else None))
out={'notice':'全部为合成模拟数据，补充现有研发项目的阶段记录和技术变更的执行任务。完成日期与记录编号仅表示台账登记，不代表原件已核实、产品获准投产或现场变更已生效。原项目、变更及生产记录保持不变。','as_of':AS_OF,'schema_version':1,'schemas':{k:SCHEMAS[k] for k in tables},'tables':tables}
(ROOT/'data/engineering_scenario.json').write_text(json.dumps(out,ensure_ascii=False,indent=2))
print(json.dumps({k:len(v) for k,v in tables.items()},ensure_ascii=False))
