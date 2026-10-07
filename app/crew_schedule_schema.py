"""Explicit future staffing constraints layered over a resource trial."""
DATASETS=('crew_studies','crew_credentials','crew_candidates','crew_windows','crew_blocks')
def register_crew(register):
 register('crew_studies','资源人员联立方案','37_资源人员试排','id:联立方案号:str;name:方案名称:str;resource_study_id:资源试排方案:str:schedule_studies;version:人员假设版本:str;credential_count:声明资格假设数:int;candidate_count:声明人员候选数:int;window_count:声明人员窗口数:int;block_count:声明人员不可用数:int;owner_id:负责工号:str:employees;assumptions:人员约束假设:str;reference:方案依据号:str')
 register('crew_credentials','试排资格窗口','37_资源人员试排','id:资格假设号:str;study_id:联立方案号:str:crew_studies;skill_id:技能登记依据:str:skills;valid_from:资格假设开始:datetime;valid_until:资格假设失效起点:datetime;basis:资格窗口假设依据:str')
 register('crew_candidates','试排人员候选','37_资源人员试排','id:人员候选号:str;study_id:联立方案号:str:crew_studies;task_id:试排任务号:str:schedule_tasks;credential_id:资格假设号:str:crew_credentials;basis:人员候选假设依据:str')
 register('crew_windows','试排人员窗口','37_资源人员试排','id:人员窗口号:str;study_id:联立方案号:str:crew_studies;employee_id:工号:str:employees;started:人员假设可用开始:datetime;finished:人员假设可用结束:datetime;basis:人员窗口假设依据:str')
 register('crew_blocks','试排人员不可用','37_资源人员试排','id:人员不可用号:str;study_id:联立方案号:str:crew_studies;employee_id:工号:str:employees;started:不可用开始:datetime;finished:不可用结束:datetime;reason:假设不可用原因:str;basis:不可用假设依据:str')
