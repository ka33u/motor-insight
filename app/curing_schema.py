"""Discrete synthetic furnace capture; no inferred production release."""
DATASETS = ('cure_profiles', 'cure_channels', 'cure_runs', 'cure_loads', 'cure_samples')


def register_curing(register):
    register('cure_profiles','固化曲线规范','43_固化曲线','id:规范版本号:str;program_code:程序编码:str;program_version:程序版本:str;product_id:产品配置:str:products;route_version:路线版本:str;effective:生效时间:datetime;expires:失效时间:datetime?;min_hold_minutes:最少连续保温分钟:float;max_gap_minutes:最长采样间隔分钟:float;basis:模拟条件依据:str')
    register('cure_channels','固化规范通道','43_固化曲线','id:通道规范号:str;profile_id:规范版本号:str:cure_profiles;channel_code:通道编码:str;position:传感器位置:str;sensor_kind:传感器类型:str;hold_lsl:保温下限℃:float;hold_usl:保温上限℃:float;max_temp_c:全过程温度上限℃:float;basis:模拟条件说明:str')
    register('cure_runs','固化炉次采集','43_固化曲线','id:炉次号:str;equipment_id:设备编码:str:equipment;resource_id:独立资源位:str:production_resources;program_code:程序编码:str;program_version:程序版本:str;started:曲线起点:datetime;finished:曲线终点:datetime?;registered:采集登记时间:datetime;capture_state:采集闭合状态:str;load_count:声明装载行数:int;sample_count:声明采样行数:int;channel_count:声明采集通道数:int;operator_id:登记工号:str:employees;voided:是否作废:bool;reference:采集依据号:str;note:采集说明:str')
    register('cure_loads','固化装炉批次','43_固化曲线','id:装炉行号:str;run_id:炉次号:str:cure_runs;operation_id:报工事件号:str:operations;batch_id:生产批次:str:batches;qty:本炉装载数量:int;unit:装载单位:str;position:装载位置:str;note:对应说明:str')
    register('cure_samples','固化温度采样','43_固化曲线','id:采样号:str;run_id:炉次号:str:cure_runs;channel_code:通道编码:str;sequence:通道内采样序号:int;measured:采样时间:datetime;value:原始温度:float?;unit:原始单位:str;quality:采样状态:str;reference:原始导出行号:str;note:采样说明:str')
