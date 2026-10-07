"""Governed, read-only business grains exposed to the configurable BI engine."""
SEMANTIC_SCHEMAS={}

def register(key,label,grain,sources,fields,note):
    parsed=[]
    for token in fields.split(';'):
        name,title,kind=token.split(':');optional=kind.endswith('?')
        parsed.append({'name':name,'label':title,'type':kind.rstrip('?'),'required':not optional,'reference':None})
    SEMANTIC_SCHEMAS[key]={'key':key,'label':label,'department':'BI_跨表业务模型','version':1,'primary_key':'id','fields':parsed,'virtual':True,'grain':grain,'sources':sources,'note':note}

register('bi_order_lines','订单交付分析','一行一个销售订单行',['orders','order_lines','customers','products','delivery_plans','allocations','work_orders','units','shipments'],
 'id:订单行号:str;order_id:销售订单号:str;customer:客户:str;region:区域:str;product_id:配置编码:str;family:产品族:str;power_kw:功率kW:float;order_date:下单日期:date;due:现承诺日期:date;qty:订单台数:int;allocated_qty:工单分配台数:int;produced_qty:可明确归属的装配台数:int?;shipped_qty:已发货台数:int;remaining_qty:未交台数:int;overdue_qty:逾期未交台数:int;due_plan_count:到期计划行数:int;on_time_plan_count:按期足量计划行数:int;order_net_cents:订单未税金额分:int;custom_requirement:定制要求:str;attribution:生产归属状态:str',
 '交付计划、发货和生产分别预聚合后关联，避免一对多相乘。一个工单分给多个订单行时，未建立SN归属前装配量为空，不按比例虚分台数。日期型承诺当日仍可履约，次日起纳入到期计划分母并计算逾期；承诺日当天发货计为按期。')
register('bi_work_orders','工单产质成本分析','一行一个生产工单',['work_orders','products','units','test_sessions','measurements','releases','costs'],
 'id:生产工单号:str;product_id:配置编码:str;family:产品族:str;planned_end:计划完工日:date;planned_qty:计划台数:int;produced_qty:装配台数:int;first_tested_count:首次完整检测台数:int;first_pass_count:首次完整检测合格台数:int;released_qty:批准放行台数:int;pending_qty:未完成装配台数:int;total_cost_cents:暂估总成本分:int;material_cost_cents:材料成本分:int;unit_cost_cents:暂估每台成本分:float?;status:工单状态:str',
 '质量以SN去重，复测不覆盖首检。成本全部为模拟未结账归集；未产出的工单不计算单位成本。')
register('bi_units','整机质量与交付分析','一行一个电机SN',['units','work_orders','products','allocations','orders','customers','test_sessions','test_specs','measurements','releases','shipment_units','shipments'],
 'id:电机SN:str;work_order_id:生产工单号:str;product_id:配置编码:str;family:产品族:str;power_kw:功率kW:float;voltage:电压V:int;customer:明确归属客户:str?;assembly_at:装配时间:datetime;stator_batch:定子批次:str;rotor_batch:转子批次:str;session_count:有效检测会话数:int;first_tested_count:首次完整检测计数:int;first_pass_count:首次完整检测合格计数:int;complete_count:完整检测计数:int;latest_result:最新检测结论:str;first_equipment:首次完整检测台:str?;released_count:批准放行计数:int;shipped_count:发货计数:int;release_hours:装配至放行小时:float?;status:整机状态:str',
 '计数字段均为0/1，可用比率聚合计算FPY和覆盖率；缺失检测不是不合格。客户只在工单分配唯一明确时归属。')
register('bi_inventory','库存余额与状态分析','一行一个物料×批次×库位',['materials','inventory_opening','inventory_movements','inventory_status_events'],
 'id:库存对象:str;material_id:物料编码:str;material:物料名称:str;category:类别:str;lot:库存批次:str;location:库位:str;unit:计量单位:str;opening_qty:期初数量:float;inbound_qty:累计入库数量:float;outbound_qty:累计出库数量:float;balance_qty:账面结存数量:float;available_qty:可用数量:float;state:当前库存状态:str;reference_value_cents:参考库存金额分:int;last_movement:最近变动时间:datetime?',
 '按截止时点重放库存状态事件。参考库存金额采用期初/物料参考单价，不等同于U8实际成本计价。不同计量单位的数量禁止混合汇总。')
register('bi_purchase','采购到货与来料质量分析','一行一个采购明细行',['purchase_lines','suppliers','materials','receipts','incoming_inspections'],
 'id:采购行号:str;supplier:供应商:str;material_id:物料编码:str;material:物料名称:str;category:物料类别:str;unit:计量单位:str;ordered:采购日期:date;due:承诺到货日:date;ordered_qty:采购数量:float;received_qty:已到货数量:float;accepted_qty:批准接收数量:float;remaining_qty:未到数量:float;overdue_qty:逾期未到数量:float;due_line_count:到期采购行计数:int;on_time_line_count:按期足量到货计数:int;iqc_rejected_count:来料不合格批次数:int;status:采购状态:str',
 '抽样不良数不视为整批不良件数；批准接收数量依据批次检验和处置状态。未到货计入到期交付分母。')
register('bi_receivables','应收账龄与回款分析','一行一个应收发票内部号',['invoices','payments','customers','shipments'],
 'id:发票内部号:str;customer:客户:str;region:区域:str;issued:开票日期:date;due:到期日期:date;net_cents:未税金额分:int;tax_cents:税额分:int;gross_cents:含税金额分:int;paid_cents:已核销金额分:int;balance_cents:未核销余额分:int;overdue_cents:逾期余额分:int;overdue_days:逾期天数:int;aging_bucket:账龄区间:str;status:票据状态:str',
 '按同一截止日归集已开票和已核销记录，账龄以到期日计算。发票不是会计确认收入，当前尚未纳入贷项、红字冲销。')
register('bi_equipment_day','设备停机日分析','一行一个设备×日期',['equipment','downtime','maintenance'],
 'id:设备日期对象:str;equipment_id:设备编码:str;equipment:设备名称:str;workshop:车间:str;process:工序:str;date:日期:date;downtime_events:停机事件数:int;downtime_minutes:去重停机分钟:float;fault_minutes:故障停机分钟:float;maintenance_count:维修任务数:int;maintenance_cost_cents:维修费用分:int',
 '跨日事件按自然日切开；重叠停机区间取并集。未配置排班与理想节拍时不输出OEE、利用率或MTBF。')
register('bi_resource_day','资源排班占用分析','一行一个独立资源位×日期',['production_resources','resource_calendars','operations','downtime','maintenance'],
 'id:资源日期对象:str;resource_id:资源位编码:str;equipment_id:设备编码:str;equipment:设备名称:str;station:资源位名称:str;process:工序:str;workshop:车间:str;date:日期:date;scheduled_minutes:排班分钟:float;blocked_minutes:排班内停机分钟:float;available_minutes:可用分钟:float;busy_minutes:作业分钟:float;event_count:工序事件数:int;occupancy_pct:排班占用率百分数:float?;integrity:计算状态:str',
 '排班占用率=作业分钟÷（排班分钟－排班内停机并集分钟）。每个资源位容量为1，设备停机作用于其全部资源位；跨资源应按分子分母合计计算。日历外作业、容量不明或重叠冲突时比率为空。仅反映模拟作业占用，不代表OEE。')
register('bi_energy_day','车间能源日分析','一行一个车间×日期',['energy'],
 'id:车间日期对象:str;workshop:车间:str;date:日期:date;readings:有效读数段数:int;kwh:用电量kWh:float;energy_cost_cents:按模拟电价费用分:int',
 '依分表读数和模拟分时电价计费。跨日区间按持续时间分摊；不能把车间总电量直接当作某产品的实际能耗。')

for key,fields in {'bi_inventory':['opening_qty','inbound_qty','outbound_qty','balance_qty','available_qty'],'bi_purchase':['ordered_qty','received_qty','accepted_qty','remaining_qty','overdue_qty']}.items():
    for field in SEMANTIC_SCHEMAS[key]['fields']:
        if field['name'] in fields:field['unit_field']='unit'

def schemas():
    from .schema import SCHEMAS
    return {**SCHEMAS,**SEMANTIC_SCHEMAS}
