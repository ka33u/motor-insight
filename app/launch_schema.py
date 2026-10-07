"""Synthetic pre-start evidence, scoped to one existing order baseline."""
DATASETS = ('launch_studies', 'launch_requirements', 'launch_tool_fits', 'launch_documents', 'launch_clearances', 'launch_tool_blocks')


def register_launch(register):
    group = '41_投产条件'
    register('launch_studies', '投产条件方案', group, 'id:核对方案:str;name:方案名称:str;baseline_id:订单基线:str:order_baselines;assessed_at:资料截止:datetime;requirement_count:声明条件行数:int;fit_count:声明工装配套数:int;document_count:声明文件数:int;clearance_count:声明质量条件数:int;block_count:声明工装占用数:int;content_hash:输入内容摘要:str;owner_id:负责工号:str:employees;basis:核对依据:str')
    register('launch_requirements', '任务条件矩阵', group, 'id:条件行号:str;study_id:核对方案:str:launch_studies;job_id:试排批次:str:schedule_jobs;route_id:工序行:str:routes;kind:条件类别:str;applicable:是否需要:bool;subject:对象编号或配套组:str?;version:要求版本:str?;uses_per_unit:每台使用次数:int;reason:需要或不适用依据:str')
    common = 'registered:登记时点:datetime;valid_from:生效起点:datetime;valid_until:失效起点:datetime;owner_id:登记工号:str:employees;reference:资料编号:str;note:登记说明:str'
    register('launch_tool_fits', '工装配套登记', group, 'id:配套登记号:str;study_id:核对方案:str:launch_studies;group:配套组:str;tool_id:工装编号:str:tools;product_id:适用配置:str:products;route_id:适用工序:str:routes;version:配套版本:str;status:配套状态:str;'+common)
    register('launch_documents', '工艺文件登记', group, 'id:文件登记号:str;study_id:核对方案:str:launch_studies;document_no:文件编号:str;product_id:适用配置:str:products;route_id:适用工序:str:routes;version:文件版本:str;status:文件状态:str;'+common)
    register('launch_clearances', '开工质量条件', group, 'id:质量条件号:str;study_id:核对方案:str:launch_studies;work_order_id:生产工单:str:work_orders;route_id:适用工序:str:routes;version:条件版本:str;status:登记结论:str;'+common)
    register('launch_tool_blocks', '工装预占停用', group, 'id:工装占用号:str;study_id:核对方案:str:launch_studies;tool_id:工装编号:str:tools;started:占用开始:datetime;ended:占用结束:datetime;registered:登记时点:datetime;owner_id:登记工号:str:employees;reason:占用原因:str')
