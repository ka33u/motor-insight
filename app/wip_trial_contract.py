"""Typed cutover rows, immutable versions and nonfinancial reference signatures."""
import re
from .finite_schedule_contract import time
from .joint_schedule_contract import number
from .order_baseline_contract import signature

STATES=('未开始','已完成','加工中','中断待续')
KINDS=('线边盘点','仓库余料','未来到料')
REFERENCE_FIELDS={
    'work_orders':('id','product_id','planned_qty','bom_version','route_version','status','planned_start','planned_end'),
    'operations':('id','work_order_id','object_type','object_id','process','equipment_id','resource_id','employee_id','started','finished','input_qty','good_qty','scrap_qty','rework_qty','status'),
    'batches':('id','work_order_id','kind','qty','created','status'),
    'units':('id','work_order_id','product_id','assembly_at','stator_batch','rotor_batch','status'),
    'products':('id','bom_version','route_version'),
    'bom':('id','product_id','material_id','version','qty','scrap_allowance','effective','assembly_level'),
    'routes':('id','product_id','version','process','branch','mandatory'),
    'materials':('id','unit'),
    'route_dependencies':('id','product_id','from_route_id','to_route_id','lag_minutes','basis'),
    'employees':('id','active'),
    'production_resources':('id','equipment_id','process','capacity','max_batch_qty','effective'),
    'skills':('id','employee_id','process','approved','expires','status'),
}


def references_hash(parent_tables,refs,cutover):
    tables={ds:sorted(rows,key=lambda r:r['id']) for ds,rows in parent_tables.items()}
    works={r['work_order_id'] for r in cutover['wip_trial_jobs']}
    ops=[r for r in refs.get('operations',{}).values() if r.get('work_order_id') in works]
    pids={r['product_id'] for r in parent_tables['schedule_jobs']}
    bom=[r for r in refs.get('bom',{}).values() if r.get('product_id') in pids]
    skills={r['skill_id'] for r in parent_tables['crew_credentials']}
    people={r['owner_id'] for ds in ('schedule_studies','crew_studies','joint_studies') for r in parent_tables[ds]}
    people|={r['employee_id'] for r in parent_tables['crew_windows']+parent_tables['crew_blocks']}
    people|={refs['skills'][k]['employee_id'] for k in skills if k in refs.get('skills',{})}
    people|={r['employee_id'] for r in ops if r.get('employee_id')}
    ids=dict(work_orders=works,operations={r['id'] for r in ops},products=pids,bom={r['id'] for r in bom},
        routes={r['route_id'] for r in parent_tables['schedule_tasks']},
        route_dependencies={r['dependency_id'] for r in parent_tables['schedule_edges']},
        materials={r['material_id'] for r in bom}|{r['material_id'] for r in cutover['wip_trial_supplies']},
        employees=people,skills=skills,
        production_resources={r['resource_id'] for r in parent_tables['schedule_options']}|{r['resource_id'] for r in ops if r.get('resource_id')},
        batches={r['id'] for r in refs.get('batches',{}).values() if r.get('work_order_id') in works},
        units={r['id'] for r in refs.get('units',{}).values() if r.get('work_order_id') in works})
    projected={ds:[{k:refs[ds][key].get(k) for k in fields} for key in sorted(ids[ds]) if key in refs.get(ds,{})]
               for ds,fields in REFERENCE_FIELDS.items()}
    return signature(dict(tables=tables,references=projected))


def bundle_hash(study,tables):
    return signature(dict(study={k:v for k,v in study.items() if k!='content_hash'},
        tables={ds:sorted(rows,key=lambda r:r['id']) for ds,rows in tables.items()}))


def issues(dataset,row):
    out=[]
    def add(field,message):out.append(dict(code='WIP_TRIAL_SOURCE',field=field,message=message))
    for field in ('version','job_count','task_count','material_count','supply_count','completed_qty','remaining_qty'):
        if field in row and (type(row[field]) is not int or row[field]<(1 if field=='version' else 0)):
            add(field,'版本须为正整数；数量及声明行数须为非负整数')
    for field in ('remaining_minutes','recovery_minutes','embedded_qty','required_qty','qty','unavailable_qty'):
        if field in row:
            try:number(row[field])
            except (ValueError,TypeError):add(field,'数量和分钟须为有限非负数')
    for field in ('cutoff','available_from','observed_at'):
        if field in row:
            try:time(row[field])
            except (ValueError,TypeError):add(field,'使用厂内YYYY-MM-DDTHH:MM:SS时间')
    for field in ('reference_hash','content_hash'):
        if field in row and (not isinstance(row[field],str) or not re.fullmatch('[0-9a-f]{64}',row[field])):
            add(field,'摘要须为64位小写十六进制')
    if dataset=='wip_trial_tasks' and row.get('state') not in STATES:add('state','任务进度状态无效')
    if dataset=='wip_trial_supplies':
        if row.get('kind') not in KINDS:add('kind','余料来源类型无效')
        if row.get('status') not in ('可投入','隔离'):add('status','余料状态须为可投入或隔离')
        try:
            if number(row['unavailable_qty'])>number(row['qty']):add('unavailable_qty','不可投入量不能超过尚未耗用量')
        except (ValueError,TypeError,KeyError):pass
    return out
