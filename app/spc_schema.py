"""Controlled synthetic studies are separate from production acceptance tests."""
DATASETS=('spc_studies','spc_observations','spc_events')


def register_spc(register):
    register('spc_studies','受控采样试验','34_过程稳定性',
        'id:采样试验号:str;name:试验名称:str;product_id:配置编码:str:products;spec_id:规范项目号:str:test_specs;equipment_id:设备编码:str:equipment;stage:采样工序:str;protocol_version:采样方案版本:str;method:分析方法:str;measurement_method:试验方法版本:str;unit:标准单位:str;started:试验开始:datetime;finished:试验结束:datetime?;status:采集状态:str;expected_points:计划采样点数:int;baseline_end:基线末序号:int;order_basis:顺序依据:str;owner_id:负责工号:str:employees;measurement_system_ref:测量系统依据:str?;conditions:测量条件:str;purpose:试验用途:str;note:试验说明:str')
    register('spc_observations','受控采样观测','34_过程稳定性',
        'id:采样观测号:str;study_id:采样试验号:str:spc_studies;sequence:采样序号:int;unit_id:单台SN:str:units;measured:实际测量时间:datetime?;registered:登记时间:datetime;value:标准数值:float?;unit:标准单位:str;replicate:样件重复次数:int;method_version:方法版本:str;temperature_c:环境温度C:float?;state:观测状态:str;operator_id:采样工号:str:employees;reference:来源依据号:str;note:观测说明:str')
    register('spc_events','采样过程事件','34_过程稳定性',
        'id:采样事件号:str;study_id:采样试验号:str:spc_studies;sequence:对应采样序号:int;occurred:事件时间:datetime;registered:登记时间:datetime;category:事件类别:str;description:事件内容:str;operator_id:登记工号:str:employees;reference:事件依据号:str')
