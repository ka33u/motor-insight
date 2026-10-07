"""Future material assumptions attached to an existing people/resource trial."""
DATASETS=('joint_studies','joint_bindings','joint_demands','joint_supplies')
def register_joint(register):
    register('joint_studies','物料人机联立方案','39_物料人机试排','id:联立方案号:str;name:方案名称:str;crew_study_id:人员资源方案:str:crew_studies;version:物料假设版本:str;binding_count:声明用料绑定数:int;demand_count:声明批次需求数:int;supply_count:声明供给批次数:int;owner_id:负责工号:str:employees;scope:方案范围:str;assumptions:约束假设:str;reference:方案依据号:str')
    register('joint_bindings','BOM用料工序绑定','39_物料人机试排','id:用料绑定号:str;study_id:联立方案号:str:joint_studies;bom_id:BOM行号:str:bom;route_id:预留工序行:str:routes;quantum:需求取整步长:float;basis:绑定假设依据:str')
    register('joint_demands','试排整批物料需求','39_物料人机试排','id:整批需求号:str;study_id:联立方案号:str:joint_studies;job_id:试排批次号:str:schedule_jobs;binding_id:用料绑定号:str:joint_bindings;required_qty:整批需求数量:float;unit:需求单位:str;basis:需求计算依据:str')
    register('joint_supplies','试排物料可用假设','39_物料人机试排','id:供给批次号:str;study_id:联立方案号:str:joint_studies;material_id:物料编码:str:materials;lot:模拟物料批号:str;unit:供给单位:str;qty:假设账面数量:float;unavailable_qty:其中不可预留数量:float;available_from:假设可用起点:datetime;status:物料假设状态:str;kind:供给假设类型:str;reference:供给依据号:str;basis:供给假设说明:str')
