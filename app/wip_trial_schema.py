"""Explicit Excel cutover assumptions for remaining-WIP scheduling."""
DATASETS=('wip_trial_studies','wip_trial_jobs','wip_trial_tasks','wip_trial_materials','wip_trial_supplies')


def register_wip_trial(register):
    register('wip_trial_studies','在制剩余试排方案','48_在制剩余试排',
        'id:在制方案号:str;name:方案名称:str;series:方案系列:str;version:版本:int;supersedes_id:前版本:str?:wip_trial_studies;joint_study_id:原联立方案:str:joint_studies;cutoff:进度截止:datetime;job_count:声明工单映射数:int;task_count:声明任务进度数:int;material_count:声明任务用料数:int;supply_count:声明余料行数:int;reference_hash:原始依据摘要:str;content_hash:完整声明摘要:str;owner_id:负责工号:str:employees;basis:边界与依据:str')
    register('wip_trial_jobs','在制工单批次映射','48_在制剩余试排',
        'id:工单映射号:str;study_id:在制方案号:str:wip_trial_studies;job_id:原试排批次:str:schedule_jobs;work_order_id:原工单:str:work_orders;basis:全工单映射依据:str')
    register('wip_trial_tasks','在制任务进度声明','48_在制剩余试排',
        'id:进度声明号:str;study_id:在制方案号:str:wip_trial_studies;task_id:原工序任务:str:schedule_tasks;state:任务进度状态:str;operation_id:原报工号:str?:operations;completed_qty:已完成数量:int;remaining_qty:剩余处理数量:int;remaining_minutes:剩余加工分钟:float;recovery_minutes:中断恢复准备分钟:float;resource_id:在加工资源位:str?:production_resources;employee_id:在加工工号:str?:employees;basis:数量工时与恢复依据:str')
    register('wip_trial_materials','在制任务剩余用料','48_在制剩余试排',
        'id:剩余用料声明号:str;study_id:在制方案号:str:wip_trial_studies;task_id:原工序任务:str:schedule_tasks;binding_id:原BOM工序绑定:str:joint_bindings;embedded_qty:剩余在制品已投入量:float;required_qty:尚需投入数量:float;unit:用料单位:str;basis:已投入量与剩余需求依据:str')
    register('wip_trial_supplies','在制试排余料池','48_在制剩余试排',
        'id:余料假设号:str;study_id:在制方案号:str:wip_trial_studies;material_id:物料编码:str:materials;lot:材料批号:str;location:盘点位置:str;unit:余料单位:str;qty:尚未耗用数量:float;unavailable_qty:其中不可投入量:float;available_from:可用假设起点:datetime;status:余料状态:str;kind:余料来源类型:str;owner_job_id:专属试排批次:str?:schedule_jobs;observed_at:盘点或承诺登记时点:datetime;reference:模拟盘点或到料依据:str;basis:余料可用假设说明:str')
