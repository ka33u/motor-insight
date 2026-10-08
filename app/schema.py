"""Versioned business data contracts. Money uses integer CNY cents.

Names are stable internal IDs; labels are the XLSX contract. References are
validated during staging against both committed and same-batch records.
"""
SCHEMAS = {}

def register(key, label, department, fields):
    cols=[]
    for token in fields.split(';'):
        parts=token.strip().split(':')
        name,title,kind=parts[:3]
        optional=kind.endswith('?');kind=kind.rstrip('?')
        cols.append(dict(name=name,label=title,type=kind,required=not optional,
                         reference=parts[3] if len(parts)>3 else None))
    SCHEMAS[key]=dict(key=key,label=label,department=department,version=1,
                      primary_key=cols[0]['name'],fields=cols)

register('departments','部门档案','01_基础档案','id:部门编码:str;name:部门名称:str;owner:负责人岗位:str')
register('employees','人员档案','01_基础档案','id:工号:str;name:姓名:str;department_id:部门编码:str:departments;role:岗位:str;skill_level:技能等级:str;hourly_cents:小时成本分:int;active:在职:bool')
register('customers','客户档案','01_基础档案','id:客户编码:str;name:客户名称:str;region:区域:str;industry:行业:str;payment_days:账期天数:int;owner_id:业务员工号:str:employees')
register('suppliers','供应商档案','01_基础档案','id:供应商编码:str;name:供应商名称:str;category:供货类别:str;region:区域:str;lead_days:交付周期天:int;qualified:合格供方:bool')
register('materials','物料档案','01_基础档案','id:物料编码:str;name:物料名称:str;category:类别:str;spec:规格:str;unit:单位:str;unit_cost_cents:参考单价分:int;supplier_id:首选供应商:str:suppliers;safety_qty:安全库存:float')
register('products','产品配置','01_基础档案','id:配置编码:str;model:电机型号:str;family:产品族:str;power_kw:功率kW:float;voltage:电压V:int;poles:极数:int;frame:机座号:str;mounting:安装方式:str;protection:防护等级:str;insulation:绝缘等级:str;bom_version:BOM版本:str;route_version:路线版本:str;drawing:图纸号:str;price_cents:参考售价分:int;standard_hours:标准工时h:float')
register('equipment','设备档案','01_基础档案','id:设备编码:str;name:设备名称:str;workshop:车间:str;process:工序:str;model:设备型号:str;commissioned:投用日期:date;status:状态:str;owner_id:责任工号:str:employees')
register('bom','BOM明细','02_研发工艺','id:BOM行号:str;product_id:配置编码:str:products;material_id:物料编码:str:materials;version:版本:str;qty:单位用量:float;scrap_allowance:损耗定额:float;effective:生效日期:date')
register('routes','工艺路线','02_研发工艺','id:路线行号:str;product_id:配置编码:str:products;version:版本:str;sequence:序号:int;process:工序:str;workshop:车间:str;minutes:标准分钟:float;mandatory:必经工序:bool')
register('projects','研发项目','02_研发工艺','id:项目编号:str;name:项目名称:str;product_id:配置编码:str:products;owner_id:负责工号:str:employees;planned_end:计划结束:date;actual_end:实际结束:date?;status:状态:str;budget_cents:预算分:int')
register('engineering_changes','技术变更','02_研发工艺','id:变更单号:str;product_id:配置编码:str:products;from_version:原版本:str;to_version:新版本:str;reason:变更原因:str;effective:生效日期:date;approved_by:批准工号:str:employees;status:状态:str')
register('quotes','销售报价','03_销售订单','id:报价单号:str;customer_id:客户编码:str:customers;product_id:配置编码:str:products;qty:数量:int;unit_price_cents:单价分:int;quote_date:报价日期:date;valid_until:有效截至:date;status:状态:str;reason:结果说明:str')
register('orders','销售订单','03_销售订单','id:销售订单号:str;customer_id:客户编码:str:customers;order_date:订单日期:date;owner_id:业务员工号:str:employees;currency:币种:str;status:订单状态:str;customer_po:客户采购单:str')
register('order_lines','订单明细','03_销售订单','id:订单行号:str;order_id:销售订单号:str:orders;product_id:配置编码:str:products;qty:订单数量:int;unit_price_cents:未税单价分:int;original_due:原承诺日期:date;due:现承诺日期:date;change_reason:变更原因:str?;custom_requirement:定制要求:str')
register('delivery_plans','交付计划','03_销售订单','id:交付计划号:str;order_line_id:订单行号:str:order_lines;qty:约定数量:int;due:承诺日期:date;version:版本:int')
register('work_orders','生产工单','04_计划生产','id:生产工单号:str;product_id:配置编码:str:products;planned_qty:计划数量:int;planned_start:计划开工:date;planned_end:计划完工:date;priority:优先级:str;status:工单状态:str;bom_version:BOM版本:str;route_version:路线版本:str')
register('allocations','工单订单分配','04_计划生产','id:分配编号:str;work_order_id:生产工单号:str:work_orders;order_line_id:订单行号:str:order_lines;qty:分配数量:int;effective:生效日期:date')
register('batches','生产批次','04_计划生产','id:批次号:str;work_order_id:生产工单号:str:work_orders;kind:半成品类型:str;qty:数量:int;created:建立时间:datetime;status:批次状态:str;container:周转箱号:str')
register('units','整机档案','04_计划生产','id:电机SN:str;work_order_id:生产工单号:str:work_orders;product_id:配置编码:str:products;assembly_at:装配时间:datetime;stator_batch:定子批次:str:batches;rotor_batch:转子批次:str:batches;status:整机状态:str')
register('operations','工序事件','04_计划生产','id:报工事件号:str;work_order_id:生产工单号:str:work_orders;object_type:对象类型:str;object_id:对象编号:str;process:工序:str;equipment_id:设备编码:str:equipment;employee_id:操作工号:str:employees;started:开始时间:datetime;finished:完成时间:datetime?;input_qty:投入数:int;good_qty:合格数:int;scrap_qty:报废数:int;rework_qty:返工数:int;status:事件状态:str')
register('purchase_lines','采购明细','05_采购供应','id:采购行号:str;supplier_id:供应商编码:str:suppliers;material_id:物料编码:str:materials;ordered:下单日期:date;due:承诺到货:date;qty:采购数量:float;unit_price_cents:单价分:int;status:状态:str')
register('receipts','采购到货','05_采购供应','id:到货单号:str;purchase_line_id:采购行号:str:purchase_lines;material_id:物料编码:str:materials;lot:来料批次:str;qty:到货数量:float;received:到货时间:datetime;certificate:材质证明号:str;status:待检状态:str')
register('inventory_opening','期初库存','06_仓储物流','id:期初记录号:str;material_id:物料编码:str:materials;lot:库存批次:str;location:库位:str;as_of:期初日期:date;qty:期初数量:float;unit_cost_cents:单位成本分:int;status:库存状态:str')
register('inventory_movements','库存流水','06_仓储物流','id:库存流水号:str;material_id:物料编码:str:materials;lot:库存批次:str;location:库位:str;occurred:发生时间:datetime;movement:业务类型:str;qty_signed:数量增减:float;work_order_id:生产工单号:str?:work_orders;reference:来源单号:str')
register('inventory_status_events','库存状态变更','06_仓储物流','id:状态变更单号:str;material_id:物料编码:str:materials;lot:库存批次:str;location:库位:str;occurred:变更时间:datetime;from_status:原状态:str;to_status:新状态:str;reason:变更原因:str;approver_id:批准工号:str:employees')
register('shipments','发货明细','06_仓储物流','id:发货行号:str;delivery_plan_id:交付计划号:str:delivery_plans;order_line_id:订单行号:str:order_lines;qty:发货数量:int;shipped:发货时间:datetime;signed:签收时间:datetime?;carrier:承运商:str;tracking:运单号:str')
register('shipment_units','装箱SN','06_仓储物流','id:装箱明细号:str;shipment_id:发货行号:str:shipments;unit_id:电机SN:str:units;package:包装箱号:str')
register('genealogy','批次装配谱系','07_质量追溯','id:关联编号:str;parent_type:来源类型:str;parent_id:来源编号:str;child_type:目标类型:str;child_id:目标编号:str;qty:消耗数量:float;unit:单位:str;occurred:关联时间:datetime;work_order_id:生产工单号:str:work_orders')
register('test_specs','检测规范','07_质量追溯','id:规范项目号:str;product_id:配置编码:str:products;version:规范版本:str;test_code:项目编码:str;test_name:项目名称:str;unit:单位:str;lsl:下限:float?;usl:上限:float?;mandatory:必检:bool;effective:生效日期:date;note:适用说明:str')
register('test_sessions','检测会话','07_质量追溯','id:检测会话号:str;unit_id:电机SN:str:units;attempt:检测次数:int;equipment_id:设备编码:str:equipment;operator_id:检测工号:str:employees;tested:检测时间:datetime;temperature_c:环境温度℃:float;spec_version:规范版本:str;complete:项目齐全:bool;result:检测结论:str;reason:检测原因:str;voided:是否作废:bool')
register('measurements','检测项目结果','07_质量追溯','id:结果编号:str;session_id:检测会话号:str:test_sessions;spec_id:规范项目号:str:test_specs;raw_value:原始数值:float;raw_unit:原始单位:str;value:标准数值:float;unit:标准单位:str;result:项目结论:str;file_reference:原始文件名:str')
register('incoming_inspections','来料检验','07_质量追溯','id:来料检验号:str;receipt_id:到货单号:str:receipts;sample_size:抽样数量:int;defect_count:不良样本数:int;inspected:检验时间:datetime;result:检验结论:str;inspector_id:检验工号:str:employees;disposition:处置方式:str')
register('nonconformities','不合格与整改','07_质量追溯','id:不合格单号:str;unit_id:电机SN:str?:units;work_order_id:生产工单号:str:work_orders;defect_code:缺陷编码:str;description:问题描述:str;found:发现时间:datetime;owner_id:责任工号:str:employees;due:整改期限:date;action:处置措施:str;status:状态:str;closed:复核关闭:datetime?')
register('releases','质量放行','07_质量追溯','id:放行单号:str;unit_id:电机SN:str:units;session_id:依据检测会话:str:test_sessions;released:放行时间:datetime;approver_id:批准工号:str:employees;status:放行状态:str')
register('maintenance','维修保养','08_设备工装','id:维修工单号:str;equipment_id:设备编码:str:equipment;kind:任务类型:str;reported:报修时间:datetime;started:维修开始:datetime?;finished:维修结束:datetime?;failure:故障原因:str;technician_id:维修工号:str:employees;cost_cents:维修费用分:int;status:状态:str')
register('downtime','设备停机','08_设备工装','id:停机事件号:str;equipment_id:设备编码:str:equipment;started:开始时间:datetime;finished:结束时间:datetime;reason:停机原因:str;work_order_id:关联工单:str?:work_orders')
register('tools','工装计量台账','08_设备工装','id:工装仪器号:str;name:名称:str;kind:类型:str;equipment_id:适用设备:str:equipment;uses:累计使用数:int;maintenance_limit:维护阈值:int;calibrated:校准日期:date;next_due:下次到期:date;status:状态:str')
register('attendance','班次工时','09_人事工时','id:工时记录号:str;employee_id:工号:str:employees;date:生产日期:date;shift:班次:str;productive_hours:生产小时:float;setup_hours:换型小时:float;wait_hours:等待小时:float;rework_hours:返工小时:float;overtime_hours:其中加班小时:float')
register('skills','技能授权','09_人事工时','id:授权编号:str;employee_id:工号:str:employees;process:适用工序:str;level:等级:str;approved:批准日期:date;expires:有效截至:date;status:授权状态:str')
register('costs','成本归集','10_财务成本','id:成本记录号:str;work_order_id:生产工单号:str:work_orders;category:成本类别:str;amount_cents:金额分:int;occurred:发生日期:date;basis:归集依据:str;status:结账状态:str')
register('invoices','应收发票','10_财务成本','id:发票内部号:str;shipment_id:发货行号:str:shipments;customer_id:客户编码:str:customers;issued:开票日期:date;due:到期日期:date;net_cents:未税金额分:int;tax_cents:税额分:int;status:状态:str')
register('payments','收款核销','10_财务成本','id:收款单号:str;invoice_id:发票内部号:str:invoices;paid:收款日期:date;amount_cents:核销金额分:int;method:收款方式:str')
register('ar_opening','期初应收明细','13_历史应收','id:期初应收行号:str;customer_id:客户编码:str:customers;document_no:原单据号:str;issued:原开票日期:date;due:到期日期:date;as_of:期初日期:date;currency:币种:str;original_gross_cents:原单含税金额分:int;opening_balance_cents:期初未核销分:int;note:期初说明:str')
register('ar_events','期初应收事件','13_历史应收','id:应收事件号:str;opening_id:期初应收行号:str:ar_opening;occurred:过账日期:date;kind:事件类型:str;delta_cents:余额增减分:int;document_no:凭据号:str;reverses_id:冲回原事件:str?;status:过账状态:str;reason:业务说明:str')
register('energy','能源读数','11_能源安环','id:计量记录号:str;meter:表计编号:str;workshop:车间:str;started:开始时间:datetime;ended:结束时间:datetime;kwh:用电kWh:float;tariff_cents:每kWh电价分:int;measurement:计量性质:str')
register('ehs','安环整改','11_能源安环','id:安环事件号:str;workshop:车间:str;kind:问题类型:str;description:问题描述:str;found:发现日期:date;due:整改期限:date;owner_id:责任工号:str:employees;status:状态:str;closed:关闭日期:date?')
register('service','售后服务','12_售后服务','id:售后单号:str;unit_id:电机SN:str:units;customer_id:客户编码:str:customers;reported:报修时间:datetime;failure:问题类别:str;environment:使用环境:str;response:首次响应:datetime;closed:关闭时间:datetime?;cost_cents:服务费用分:int;status:状态:str')
register('service_events','售后过程记录','14_售后过程','id:服务记录号:str;service_id:售后单号:str:service;occurred:发生时间:datetime;kind:记录类型:str;channel:联系渠道:str;owner_id:负责工号:str:employees;description:记录说明:str;source_kind:资料性质:str')
register('service_tasks','售后任务','14_售后过程','id:服务任务号:str;service_id:售后单号:str:service;created:建立时间:datetime;kind:任务类型:str;owner_id:负责工号:str:employees;due:约定完成时间:datetime;completed:完成时间:datetime?;status:任务状态:str;description:任务说明:str;result:执行结果:str?')
register('service_conditions','售后工况资料','14_售后过程','id:工况记录号:str;service_id:售后单号:str:service;recorded:记录时间:datetime;item:工况项目:str;value:客户提供数值:float?;unit:单位:str?;description:资料说明:str;source_kind:资料性质:str;status:核实状态:str;owner_id:记录工号:str:employees')
register('project_milestones','研发里程碑','15_研发工艺过程','id:里程碑编号:str;project_id:项目编号:str:projects;sequence:阶段序号:int;name:阶段名称:str;planned_start:计划开始:date;planned_end:计划完成:date;actual_start:实际开始:date?;actual_end:实际完成:date?;owner_id:责任工号:str:employees;status:台账状态:str;outcome:阶段说明:str;record_no:记录编号:str?')
register('change_actions','变更执行任务','15_研发工艺过程','id:执行任务号:str;change_id:变更单号:str:engineering_changes;kind:任务类型:str;owner_id:责任工号:str:employees;created:建立日期:date;due:约定完成:date;completed:完成日期:date?;status:台账状态:str;description:执行范围:str;result:执行说明:str?;record_no:记录编号:str?')
register('quote_details','报价商务资料','16_销售报价过程','id:商务资料号:str;quote_id:报价单号:str:quotes;owner_id:负责工号:str:employees;inquiry_date:收到询价日期:date;inquiry_no:询价编号:str;channel:询价渠道:str;currency:币种:str;tax_basis:报价价税口径:str;version:报价登记版本:str;outcome_date:结果确认日期:date?;requirement:技术商务要求:str')
register('quote_order_links','报价订单关联','16_销售报价过程','id:关联记录号:str;quote_id:报价单号:str:quotes;order_line_id:订单行号:str:order_lines;qty:对应数量:int;confirmed:确认日期:date;status:关联状态:str;reference:确认依据:str')
register('quote_tasks','报价跟进任务','16_销售报价过程','id:跟进任务号:str;quote_id:报价单号:str:quotes;owner_id:负责工号:str:employees;created:建立日期:date;kind:任务类型:str;due:约定完成日期:date;completed:完成日期:date?;status:任务状态:str;description:跟进事项:str;result:反馈说明:str?')

register('process_specs','工序参数规范','18_工序检验','id:规范项目号:str;product_id:配置编码:str:products;route_version:路线版本:str;process:工序:str;branch:工艺分支:str;version:规范版本:str;parameter:参数编码:str;name:参数名称:str;unit:单位:str;lsl:下限:float?;usl:上限:float?;mandatory:必检:bool;effective:生效日期:date;expires:失效日期:date?;basis:限值依据:str')
register('process_check_plans','工序应检计划','18_工序检验','id:应检计划号:str;operation_id:报工事件号:str:operations;stage:检验类型:str;due:应检时间:datetime;spec_version:规范版本:str;basis:计划依据:str')
register('process_checks','工序检验记录','18_工序检验','id:检验记录号:str;plan_id:应检计划号:str:process_check_plans;sample:样本标识:str;checked:检验时间:datetime;inspector_id:检验工号:str:employees;voided:是否作废:bool;reason:检验说明:str')
register('process_readings','工序参数实测','18_工序检验','id:测量记录号:str;check_id:检验记录号:str:process_checks;spec_id:规范项目号:str:process_specs;value:实测值:float;unit:实测单位:str;instrument:量具或采集点:str')

register('purchase_terms','采购价税约定','19_供应商应付','id:约定记录号:str;purchase_line_id:采购行号:str:purchase_lines;currency:币种:str;price_basis:采购单价口径:str;tax_bps:约定税率基点:int;confirmed:确认日期:date;reference:约定依据:str')
register('ap_invoices','供应商应付发票','19_供应商应付','id:应付发票号:str;supplier_id:供应商编码:str:suppliers;invoice_no:供应商发票号:str;currency:币种:str;issued:开票日期:date;posted:确认应付日期:date;due:到期日期:date;net_cents:未税金额分:int;tax_cents:税额分:int;status:登记状态:str;reference:确认依据:str')
register('ap_invoice_lines','应付发票明细','19_供应商应付','id:发票明细号:str;invoice_id:应付发票号:str:ap_invoices;receipt_id:到货单号:str:receipts;qty:开票数量:float;unit_price_cents:发票未税单价分:int;tax_bps:发票税率基点:int;net_cents:未税金额分:int;tax_cents:税额分:int;reference:核对依据:str')
register('ap_payments','供应商付款登记','19_供应商应付','id:付款登记号:str;supplier_id:供应商编码:str:suppliers;currency:币种:str;paid:付款日期:date;amount_cents:付款金额分:int;status:登记状态:str;document_no:付款凭据号:str;method:付款方式:str;reference:付款依据:str')
register('ap_payment_plans','供应商付款安排','19_供应商应付','id:付款安排号:str;invoice_id:应付发票号:str:ap_invoices;created:登记日期:date;planned:计划付款日期:date;amount_cents:安排金额分:int;status:安排状态:str;approved:批准日期:date?;owner_id:负责工号:str:employees;reference:安排依据:str')
register('ap_allocations','供应商付款核销','19_供应商应付','id:付款核销号:str;payment_id:付款登记号:str:ap_payments;invoice_id:应付发票号:str:ap_invoices;occurred:核销日期:date;amount_cents:核销金额分:int;status:核销状态:str;plan_id:执行付款安排号:str?:ap_payment_plans;reference:核销依据:str')
register('ap_adjustments','供应商应付调整','19_供应商应付','id:应付调整号:str;invoice_id:应付发票号:str:ap_invoices;occurred:过账日期:date;kind:调整类型:str;delta_cents:应付余额增减分:int;allocation_id:原付款核销号:str?:ap_allocations;status:登记状态:str;document_no:调整凭据号:str;reason:调整说明:str')

register('production_resources','独立资源位','01_基础档案','id:资源位编码:str;equipment_id:设备编码:str:equipment;process:适用工序:str;station:工位名称:str;employee_id:固定操作工号:str:employees;capacity:并行事件容量:int;max_batch_qty:单次最大台数:int;effective:生效日期:date;basis:容量依据:str')
register('route_dependencies','路线依赖','02_研发工艺','id:依赖编号:str;product_id:配置编码:str:products;from_route_id:前序路线行:str:routes;to_route_id:后序路线行:str:routes;lag_minutes:最小等待分钟:float;basis:约束依据:str')
register('resource_calendars','资源排班段','04_计划生产','id:排班段号:str;resource_id:资源位编码:str:production_resources;employee_id:排班工号:str:employees;started:排班开始:datetime;finished:排班结束:datetime;shift:班次:str;basis:排班依据:str')
register('labor_entries','作业工时明细','09_人事工时','id:工时明细号:str;operation_id:报工事件号:str:operations;employee_id:工号:str:employees;work_order_id:生产工单号:str:work_orders;started:开始时间:datetime;finished:结束时间:datetime;activity:作业类别:str;minutes:作业分钟:float;hourly_cents:小时成本分:int;amount_cents:人工成本分:int;basis:工时依据:str')

def extend(key,fields):
    temporary='_extension';register(temporary,'','',fields)
    SCHEMAS[key]['fields'].extend(SCHEMAS.pop(temporary)['fields']);SCHEMAS[key]['version']=2

extend('bom','assembly_level:装配层级:str?')
extend('routes','branch:工艺分支:str?')
extend('units','assembly_batch:装配件包批次:str?:batches')
extend('operations','resource_id:资源位编码:str?:production_resources')
extend('attendance','support_hours:间接支持小时:float?;scheduled_hours:排班小时:float?')

register('transport_dispatches','运输交接','20_发运签收','id:运输交接号:str;shipment_id:发货行号:str:shipments;handed:交接时间:datetime?;promised:约定到货时间:datetime?;route:运输线路:str;reference:交接凭据:str?')
register('transport_events','运输节点','20_发运签收','id:运输事件号:str;dispatch_id:运输交接号:str:transport_dispatches;occurred:节点时间:datetime;kind:节点类型:str;location:节点地点:str;note:节点说明:str;voided:是否作废:bool')
register('customer_receipts','客户签收凭据','20_发运签收','id:签收凭据号:str;dispatch_id:运输交接号:str:transport_dispatches;received:签收时间:datetime;document:签收文件编号:str?;receiver:接收岗位:str?;voided:是否作废:bool')
register('customer_receipt_units','客户签收SN','20_发运签收','id:签收明细号:str;receipt_id:签收凭据号:str:customer_receipts;unit_id:电机SN:str:units;outcome:接收结论:str;reason:结论说明:str')

register('kpi_targets','经营目标版本','21_经营目标','id:目标版本号:str;series:目标系列号:str;version:目标版本:int;supersedes_id:上一目标版本:str?:kpi_targets;name:目标名称:str;department:责任部门:str;owner:责任岗位:str;model_id:分析模型号:int;model_version:模型版本:int;model_signature:模型定义摘要:str;calculation_hash:计算规则摘要:str;measure:度量编号:str;unit:目标单位:str;period_start:期间开始:date;period_end:期间结束:date;family:产品族范围:str?;customer_id:客户范围:str?:customers;direction:达标方向:str;lower:目标下限:float?;upper:目标上限:float?;warning_margin:关注区间宽度:float;minimum_samples:最少来源记录:int;approved:目标确认时间:datetime?;status:目标状态:str;basis:目标依据:str;reason:版本说明:str')
register('kpi_target_checks','目标数据确认','21_经营目标','id:数据确认号:str;target_id:目标版本号:str:kpi_targets;through:资料覆盖截至:datetime;confirmed:确认时间:datetime;data_signature:范围事实摘要:str;status:完整性结论:str;owner:确认岗位:str;note:确认依据:str;voided:是否作废:bool')

register('assembly_plan_versions','装配计划版本','22_装配计划','id:计划版本号:str;series:计划系列号:str;version:版本:int;supersedes_id:上一版本:str?:assembly_plan_versions;production_date:装配日期:date;freeze_at:基线冻结时间:datetime;released:发布时间:datetime?;status:发布状态:str;owner:计划岗位:str;line_count:完整明细行数:int;reason:调整说明:str;basis:计划依据:str')
register('assembly_plan_lines','装配日计划明细','22_装配计划','id:计划明细号:str;version_id:计划版本号:str:assembly_plan_versions;work_order_id:生产工单号:str:work_orders;product_id:配置编码:str:products;qty:计划装配台数:int;reason:安排说明:str')
register('assembly_data_checks','装配资料确认','22_装配计划','id:资料确认号:str;production_date:装配日期:date;through:资料覆盖截至:datetime;confirmed:确认时间:datetime;data_signature:当日整机事实摘要:str;status:完整性结论:str;owner:确认岗位:str;note:确认依据:str;voided:是否作废:bool')

register('stocktake_runs','盘点单','23_库存盘点','id:盘点单号:str;kind:范围类型:str;location_prefix:库位范围前缀:str;book_at:账面截止时间:datetime;freeze_start:封库开始:datetime;freeze_end:封库结束:datetime;line_count:声明盘点行数:int;owner_id:负责工号:str:employees;status:登记状态:str;freeze_evidence:封库登记依据:str')
register('stocktake_lines','初盘记录','23_库存盘点','id:盘点行号:str;run_id:盘点单号:str:stocktake_runs;material_id:物料编码:str:materials;lot:物料批次号:str;location:库位:str;unit:盘点单位:str;initial_qty:初盘数量:float?;counted:初盘时间:datetime?;counter_id:初盘工号:str?:employees;note:盘点说明:str')
register('stocktake_recounts','复盘记录','23_库存盘点','id:复盘记录号:str;line_id:盘点行号:str:stocktake_lines;attempt:复盘轮次:int;qty:复盘数量:float;counted:复盘时间:datetime;counter_id:复盘工号:str:employees;voided:是否作废:bool;reason:复盘依据:str')
register('stocktake_dispositions','盘差处置登记','23_库存盘点','id:处置记录号:str;line_id:盘点行号:str:stocktake_lines;recount_id:依据复盘号:str?:stocktake_recounts;confirmed_qty:确认实盘数量:float;recorded:登记时间:datetime;owner_id:登记工号:str:employees;status:处置状态:str;method:处置方式:str;evidence:处置依据:str')

register('inventory_lot_dates','批次日期登记','24_库存批次资料','id:日期登记号:str;material_id:物料编码:str:materials;lot:物料批次号:str;version:资料版本:int;supersedes_id:上一资料版本:str?:inventory_lot_dates;registered:登记时间:datetime;manufactured:制造日期:date?;first_stock_date:首次入库登记日期:date?;expires:有效截至日期:date?;expiry_mode:有效期类型:str;document_no:日期依据号:str;owner_id:登记工号:str:employees;voided:是否作废:bool;note:资料说明:str')
register('inventory_age_policies','库存关注规则','24_库存批次资料','id:规则版本号:str;material_id:物料编码:str:materials;version:规则版本:int;supersedes_id:上一规则版本:str?:inventory_age_policies;effective_from:生效日期:date;registered:登记时间:datetime;age_limit_days:超龄关注天数:int?;warning_days:临期关注天数:int?;expiry_required:要求有效期资料:bool;owner_id:负责工号:str:employees;status:规则状态:str;reason:规则依据:str')

register('purchase_commitment_versions','采购承诺版本','25_采购承诺','id:承诺版本号:str;purchase_line_id:采购行号:str:purchase_lines;version:承诺版本:int;previous_id:上一承诺版本:str?:purchase_commitment_versions;status:登记状态:str;confirmed:供应商确认时间:datetime?;effective:生效时间:datetime;registered:登记时间:datetime;total_qty:完整承诺数量:float;line_count:声明分段行数:int;owner_id:采购工号:str:employees;reference:确认依据号:str;reason:变更说明:str')
register('purchase_commitment_lines','采购分段承诺','25_采购承诺','id:分段承诺号:str;version_id:承诺版本号:str:purchase_commitment_versions;sequence:交付段次:int;due:分段承诺到货日:date;qty:分段数量:float;reference:分段依据号:str;note:分段说明:str')

register('receipt_jobs','来料作业任务','26_来料流程','id:来料作业号:str;receipt_id:到货单号:str:receipts;stage:作业环节:str;created:建立时间:datetime;reference:任务依据号:str;note:任务说明:str')
register('receipt_job_versions','来料作业时段','26_来料流程','id:作业登记版本号:str;job_id:来料作业号:str:receipt_jobs;version:登记版本:int;previous_id:上一登记版本:str?:receipt_job_versions;status:登记状态:str;assigned:派工时间:datetime?;started:作业窗口开始:datetime?;finished:作业窗口结束:datetime?;inspection_id:来料检验号:str?:incoming_inspections;movement_id:库存流水号:str?:inventory_movements;registered:登记时间:datetime;owner_id:负责工号:str:employees;station:作业位置:str;reference:登记依据号:str;reason:登记说明:str')
register('incoming_specs','来料特性规范','27_来料特性','id:规范项目号:str;material_id:物料编码:str:materials;version:规范版本:str;parameter:特性编码:str;name:特性名称:str;unit:测量单位:str;lsl:下限:float?;usl:上限:float?;mandatory:必检:bool;effective:生效日期:date;expires:失效日期:date?;basis:限值依据:str')
register('incoming_check_plans','来料特性计划','27_来料特性','id:特性计划号:str;inspection_id:来料检验号:str:incoming_inspections;spec_version:规范版本:str;sample_count:计划样本数:int;created:建立时间:datetime;due:应检时间:datetime;owner_id:责任工号:str:employees;reference:计划依据:str;note:计划说明:str')
register('incoming_checks','来料特性登记','27_来料特性','id:特性登记号:str;plan_id:特性计划号:str:incoming_check_plans;checked:测量时间:datetime;registered:登记时间:datetime;inspector_id:检验工号:str:employees;voided:已作废:bool;reference:原始记录编号:str;reason:登记说明:str')
register('incoming_readings','来料特性实测','27_来料特性','id:测量记录号:str;check_id:特性登记号:str:incoming_checks;sample_no:样本序号:int;spec_id:规范项目号:str:incoming_specs;value:实测值:float;unit:实测单位:str;instrument:量具或采集点:str;file_reference:原始文件编号:str')

register('material_certificates','材质证明台账','28_材质证明','id:证明台账号:str;number:材质证明号:str;supplier_id:供应商编码:str:suppliers;material_id:物料编码:str:materials;supplier_lot:供应批次:str;issued:签发日期:date;file_id:归档文件标识:str?;file_sha256:声明文件摘要:str?;property_count:声明特性行数:int;document_type:证明类型:str;basis:证明说明:str')
register('material_certificate_properties','证明特性声明','28_材质证明','id:证明特性号:str;certificate_id:证明台账号:str:material_certificates;parameter:特性编码:str;name:特性名称:str;value:声明实测值:float;unit:声明单位:str;method:声明检测方法:str;reference:声明项目依据:str')
register('receipt_certificate_links','到货证明关联','28_材质证明','id:关联登记号:str;receipt_id:到货单号:str:receipts;certificate_id:证明台账号:str:material_certificates;version:关联版本:int;previous_id:上版关联登记:str?:receipt_certificate_links;lot:厂内批次:str;supplier_lot:供应批次:str;recorded:关联登记时间:datetime;status:关联状态:str;owner_id:核对工号:str:employees;reference:关联依据:str;note:关联说明:str')

register('wip_locations','在制位置','29_在制流转','id:位置编码:str;name:位置名称:str;workshop:车间:str;process:关联工序:str?;kind:位置类别:str;note:位置说明:str')
register('wip_lots','周转批次','29_在制流转','id:周转批次号:str;product_id:配置编码:str:products;kind:半成品类型:str;created:建立时间:datetime;container:周转箱号:str;note:周转批次说明:str')
register('wip_openings','在制基准登记','29_在制流转','id:基准登记号:str;root_batch_id:原生产批次:str:batches;lot_id:周转批次号:str:wip_lots;location_id:位置编码:str:wip_locations;qty:基准件数:int;occurred:基准时间:datetime;recorded:登记时间:datetime;owner_id:登记工号:str:employees;reference:基准依据:str;note:登记说明:str')
register('wip_event_versions','流转完整版本','29_在制流转','id:流转版本号:str;series:流转事件号:str;version:版本:int;previous_id:上版流转版本:str?:wip_event_versions;occurred:发生时间:datetime;sequence:发生顺序:int;recorded:登记时间:datetime;status:登记状态:str;kind:流转类别:str;input_lots:输入周转批次清单:str;output_lots:输出周转批次清单:str;line_count:完整明细行数:int;sender_id:移交工号:str:employees;receiver_id:接收工号:str:employees;operation_id:报工事件号:str?:operations;reference:流转依据:str;note:版本说明:str')
register('wip_event_lines','流转份额明细','29_在制流转','id:流转明细号:str;event_id:流转版本号:str:wip_event_versions;side:出入方向:str;lot_id:周转批次号:str:wip_lots;location_id:位置编码:str:wip_locations;root_batch_id:原生产批次:str:batches;qty:份额件数:int;unit_id:耗用电机SN:str?:units;note:份额说明:str')

register('metrology_instruments','仪器通道档案','30_计量校准','id:仪器通道号:str;asset_code:仪器资产号:str;name:仪器通道名称:str;stage:使用环节:str;parameter:测量特性编码:str;unit:登记单位:str;source_alias:原采集点名称:str;equipment_id:对应设备:str?:equipment;tool_id:原计量台账号:str?:tools;active_from:启用时间:datetime;retired:停用时间:datetime?;owner_id:负责工号:str:employees;note:档案说明:str')
register('metrology_rules','计量适用要求','30_计量校准','id:要求版本号:str;series:要求系列号:str;version:版本:int;previous_id:上一要求版本:str?:metrology_rules;status:登记状态:str;stage:使用环节:str;parameter:测量特性编码:str;unit:适用单位:str;required:要求校准登记:bool;effective:生效时间:datetime;expires:失效时间:datetime?;registered:登记时间:datetime;owner_id:负责工号:str:employees;reference:要求依据号:str;note:要求说明:str')
register('metrology_calibrations','校准完整登记','30_计量校准','id:校准版本号:str;series:校准系列号:str;version:版本:int;previous_id:上一校准版本:str?:metrology_calibrations;status:登记状态:str;instrument_id:仪器通道号:str:metrology_instruments;performed:校准实施时间:datetime;valid_from:登记有效起点:datetime;valid_until:登记失效起点:datetime;result:登记范围结论:str;parameter:校准特性编码:str;unit:校准单位:str;certificate_no:声明证书号:str;laboratory:登记校准单位:str;registered:登记时间:datetime;owner_id:登记工号:str:employees;reference:登记依据号:str;note:校准说明:str')
register('metrology_uses','检测仪器使用','30_计量校准','id:使用版本号:str;series:使用系列号:str;version:版本:int;previous_id:上一使用版本:str?:metrology_uses;status:登记状态:str;stage:测量环节:str;measurement_id:终检测量号:str?:measurements;incoming_reading_id:来料测量号:str?:incoming_readings;process_reading_id:工序测量号:str?:process_readings;instrument_id:仪器通道号:str?:metrology_instruments;measured:实际测量时间:datetime;registered:使用登记时间:datetime;owner_id:登记工号:str:employees;reference:使用对应依据号:str;note:使用说明:str')
register('metrology_notices','失准影响登记','30_计量校准','id:影响版本号:str;series:影响系列号:str;version:版本:int;previous_id:上一影响版本:str?:metrology_notices;status:登记状态:str;instrument_id:仪器通道号:str:metrology_instruments;calibration_id:触发校准版本:str?:metrology_calibrations;kind:发现问题:str;discovered:发现时间:datetime;lower_mode:影响起点类型:str;impact_from:影响起点:datetime?;impact_until:影响终点:datetime;registered:影响登记时间:datetime;owner_id:核查负责工号:str:employees;reference:影响依据号:str;note:影响范围说明:str')
register('metrology_reviews','影响核查登记','30_计量校准','id:核查版本号:str;series:核查系列号:str;version:版本:int;previous_id:上一核查版本:str?:metrology_reviews;status:登记状态:str;notice_id:依据影响版本:str:metrology_notices;use_id:依据使用版本:str:metrology_uses;calibration_id:依据校准版本:str?:metrology_calibrations;source_digest:测量资料摘要:str;result:核查登记结果:str;registered:核查登记时间:datetime;owner_id:核查工号:str:employees;reference:核查依据号:str;note:核查说明:str')

register('metrology_certificates','校准证明台账','31_计量原件','id:证明台账号:str;certificate_no:声明证书号:str;instrument_id:声明仪器通道:str:metrology_instruments;parameter:声明特性:str;unit:声明单位:str;performed:声明校准时间:datetime;valid_from:声明有效起点:datetime;valid_until:声明失效起点:datetime;result:声明范围结论:str;laboratory:声明校准单位:str;issued:声明签发时间:datetime;file_id:归档原件标识:str?;file_sha256:声明文件摘要:str?;owner_id:台账工号:str:employees;reference:声明依据号:str;note:台账说明:str')
register('metrology_certificate_links','校准原件关联','31_计量原件','id:关联版本号:str;series:关联系列号:str;version:版本:int;previous_id:上一关联版本:str?:metrology_certificate_links;status:登记状态:str;calibration_id:依据校准版本:str:metrology_calibrations;certificate_id:证明台账号:str?:metrology_certificates;registered:关联登记时间:datetime;owner_id:关联工号:str:employees;reference:关联依据号:str;note:关联说明:str')

def schema_summary():
    return [dict(key=s['key'],label=s['label'],department=s['department'],version=s['version'],
                 fields=len(s['fields'])) for s in SCHEMAS.values()]

# Directory and scan declarations are source observations, never a live PC scan.
register('device_sources','设备文件来源','33_设备采集清单','id:来源编号:str;equipment_id:设备编码:str:equipment;host_label:设备电脑别名:str;directory:声明目录:str;format:预期格式:str;scan_interval_hours:复查间隔小时:int;registered:登记时间:datetime;owner_id:负责工号:str:employees;active:启用:bool;note:来源说明:str')
register('device_scan_runs','设备扫描登记','33_设备采集清单','id:扫描批次号:str;source_id:来源编号:str:device_sources;started:扫描开始:datetime;finished:扫描结束:datetime?;status:扫描结论:str;reported_count:声明发现数:int?;operator_id:登记工号:str:employees;note:扫描说明:str')
register('device_file_observations','设备文件发现','33_设备采集清单','id:发现记录号:str;scan_id:扫描批次号:str:device_scan_runs;relative_path:相对路径:str;filename:文件名:str;size_bytes:声明字节数:int?;sha256:声明SHA256:str?;modified:声明修改时间:datetime?;discovered:发现登记时间:datetime;read_state:读取状态:str;format:声明格式:str;session_hint:会话线索:str?;unit_hint:SN线索:str?;note:发现说明:str')

# Controlled studies add source facts without rewriting production acceptance.
from .spc_schema import register_spc
register_spc(register)

from .msa_schema import register_msa
register_msa(register)

from .finite_schedule_schema import register_schedule
register_schedule(register)

from .crew_schedule_schema import register_crew
register_crew(register)

from .oee_schema import register_oee
register_oee(register)

from .joint_schedule_schema import register_joint
register_joint(register)

from .order_baseline_schema import register_order_baseline
register_order_baseline(register)

from .launch_schema import register_launch
register_launch(register)

from .first_review_schema import register as register_first_review
register_first_review(register)

from .curing_schema import register_curing
register_curing(register)

from .wip_trial_schema import register_wip_trial
register_wip_trial(register)
