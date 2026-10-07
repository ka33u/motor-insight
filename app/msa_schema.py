"""Explicit crossed-study sources, independent of production test disposition."""
DATASETS=('msa_studies','msa_members','msa_observations')
def register_msa(register):
 register('msa_studies','测量系统试验','35_测量系统',
  'id:测量试验号:str;name:试验名称:str;product_id:配置编码:str:products;spec_id:规范项目号:str:test_specs;instrument_id:仪器通道号:str:metrology_instruments;protocol_version:试验方案版本:str;design:试验设计:str;model:分析模型:str;measurement_method:测量方法版本:str;unit:标准单位:str;part_count:计划样件数:int;operator_count:计划操作员数:int;repeat_count:计划重复数:int;started:试验开始:datetime;finished:试验结束:datetime?;status:采集状态:str;randomization:顺序与盲测依据:str;owner_id:负责工号:str:employees;conditions:测量条件:str;purpose:试验用途:str;note:试验说明:str')
 register('msa_members','测量试验样件与人员','35_测量系统',
  'id:试验成员号:str;study_id:测量试验号:str:msa_studies;kind:成员类别:str;unit_id:样件SN:str?:units;operator_id:操作工号:str?:employees;blind_label:盲测标签:str;reference:成员依据号:str;note:成员说明:str')
 register('msa_observations','测量重复观测','35_测量系统',
  'id:测量观测号:str;study_id:测量试验号:str:msa_studies;part_member_id:样件成员号:str:msa_members;operator_member_id:操作员成员号:str:msa_members;repeat:重复轮次:int;run_order:实际登记序号:int;measured:实际测量时间:datetime?;registered:登记时间:datetime;value:标准数值:float?;unit:标准单位:str;method_version:方法版本:str;temperature_c:环境温度C:float?;state:观测状态:str;reference:测量依据号:str;note:观测说明:str')
