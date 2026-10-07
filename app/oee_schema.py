"""Explicit, independently captured shift inputs; no inferred historical OEE."""
DATASETS=('oee_studies','oee_windows','oee_events','oee_cycles','oee_outputs')
def register_oee(register):
 register('oee_studies','班次效率方案','38_设备效率','id:效率方案号:str;name:方案名称:str;resource_id:独立资源位:str:production_resources;version:采集版本:str;capture_state:采集闭合状态:str;window_count:声明生产窗口数:int;event_count:声明停止事件数:int;cycle_count:声明理想节拍数:int;output_count:声明报产行数:int;scope:采集范围:str;assumptions:采集假设:str;reference:方案依据号:str')
 register('oee_windows','效率生产窗口','38_设备效率','id:生产窗口号:str;study_id:效率方案号:str:oee_studies;product_id:产品配置:str:products;started:计划生产开始:datetime;finished:计划生产结束:datetime;unit:产出单位:str;basis:窗口依据:str')
 register('oee_events','效率停止事件','38_设备效率','id:停止事件号:str;study_id:效率方案号:str:oee_studies;started:停止开始:datetime;finished:停止结束:datetime;kind:停止类别:str;reference:事件依据号:str;basis:事件说明:str')
 register('oee_cycles','配置理想节拍','38_设备效率','id:节拍依据号:str;study_id:效率方案号:str:oee_studies;product_id:产品配置:str:products;seconds_per_unit:理想秒每单位:float;unit:产出单位:str;method:节拍制定方法:str;basis:节拍依据:str')
 register('oee_outputs','班次产出分类','38_设备效率','id:报产行号:str;study_id:效率方案号:str:oee_studies;window_id:生产窗口号:str:oee_windows;reported:报产登记时间:datetime;unit:产出单位:str;total_qty:首次经过数量:int;good_first_qty:首次良品数:int;rework_qty:需返工数:int;scrap_qty:报废数:int;unknown_qty:分类未确认数:int;basis:报产依据:str')
