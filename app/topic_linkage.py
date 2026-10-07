"""Explicit identity contracts for temporary topic-wide intersections.

Only declared direct identifiers are linked. Names, status labels, composite
groups, date buckets and personal grouping labels never imply a join.
"""
import hashlib,json
from copy import deepcopy
from pathlib import Path
from django.core.exceptions import ValidationError
from . import access,analysis_engine as engine
from .import_review import ReviewConflict

REVISION='topic-direct-linkage-v1'
NOTICE='联动条件同时与当前及对照范围取交集，保留各卡原筛选、日期及已发布指标口径。仅使用已声明的直接身份字段；无对应字段的卡片暂停，不按名称猜关系。点选不改模型或业务数据；可另存个人视角和结果快照。'
def mapping(field,datasets,masters=()):
    return {**{d:field for d in datasets.split()},**{d:'id' for d in masters}}
CONTRACTS={
 'configuration':dict(label='配置编码',fields=mapping('product_id','quotes order_lines work_orders units bom routes projects engineering_changes test_specs process_specs route_dependencies assembly_plan_lines wip_lots bi_order_lines bi_work_orders bi_units',('products',))),
 'work_order':dict(label='生产工单',fields=mapping('work_order_id','allocations batches units operations inventory_movements genealogy nonconformities downtime costs labor_entries assembly_plan_lines bi_units',('work_orders','bi_work_orders'))),
 'unit':dict(label='电机SN',fields=mapping('unit_id','shipment_units test_sessions nonconformities releases service customer_receipt_units wip_event_lines',('units','bi_units'))),
 'equipment':dict(label='设备编码',fields=mapping('equipment_id','operations test_sessions maintenance downtime tools production_resources metrology_instruments device_sources bi_equipment_day bi_resource_day',('equipment',))),
 'supplier':dict(label='供应商编码',fields=mapping('supplier_id','materials purchase_lines ap_invoices ap_payments material_certificates',('suppliers',))),
 'material':dict(label='物料编码',fields=mapping('material_id','bom purchase_lines receipts inventory_opening inventory_movements inventory_status_events stocktake_lines inventory_lot_dates inventory_age_policies incoming_specs material_certificates bi_inventory bi_purchase',('materials',))),
 'workshop':dict(label='车间',fields=mapping('workshop','equipment routes energy ehs wip_locations bi_equipment_day bi_resource_day bi_energy_day')),
}
def rules_hash():return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
def contract(user,dataset):
    fields={f['name']:f for f in access.permitted_fields(user,dataset)}
    return {k:dict(label=v['label'],field=v['fields'][dataset]) for k,v in CONTRACTS.items() if dataset in v['fields'] and fields.get(v['fields'][dataset],{}).get('type')=='str'}
def metadata():return dict(revision=REVISION,rules_hash=rules_hash(),notice=NOTICE,maximum_conditions=3)
def validate(value):
    if not isinstance(value,dict) or set(value)!={'revision','rules_hash','selections'}:raise ValidationError('联动条件须包含版本、规则依据及条件清单')
    if value['revision']!=REVISION or value['rules_hash']!=rules_hash():raise ReviewConflict('专题联动关系规则已变化，请移除旧联动条件并重新点选核对；未自动替换')
    selections=value['selections']
    if not isinstance(selections,list) or not 1<=len(selections)<=3:raise ValidationError('联动需有1—3个不同业务身份条件')
    result=[];seen=set()
    for item in selections:
        if not isinstance(item,dict) or set(item)!={'kind','value'} or not isinstance(item['kind'],str) or item['kind'] not in CONTRACTS:raise ValidationError('联动业务身份不可用')
        if item['kind'] in seen:raise ValidationError('同一业务身份只能保留一个联动值')
        if not isinstance(item['value'],str) or not 1<=len(item['value'])<=150 or item['value']!=item['value'].strip() or any(ord(c)<32 for c in item['value']):raise ValidationError('联动值须为不含控制字符的完整业务编码或车间值')
        seen.add(item['kind']);result.append(dict(item))
    return dict(revision=REVISION,rules_hash=rules_hash(),selections=sorted(result,key=lambda i:i['kind']))
def effective(user,model,links):
    if not links:return model,None
    allowed=contract(user,model['dataset']);definition=deepcopy(model['definition']);filters=definition.get('filters',[]);mapped=[]
    for selection in links['selections']:
        kind=selection['kind']
        if kind not in allowed:raise ValidationError('此卡无'+CONTRACTS[kind]['label']+'的直接身份字段，联动后暂停计算；请移除此条件或使用已声明对应关系的模型')
        field=allowed[kind]['field'];filters.append(dict(field=field,op='eq',value=selection['value']));mapped.append(dict(**selection,field=field,label=allowed[kind]['label']))
    definition['filters']=filters
    # Native validators preserve published fixed filters and their own limits.
    engine.validate_definition(user,model['dataset'],definition)
    return {**model,'definition':definition,'saved_definition':deepcopy(model['definition'])},dict(**metadata(),applies_to='both',mapped=mapped)
def choices(user,model,result,scope,side):
    definition=result['resolved_definition'];field=definition.get('dimension')
    if result.get('pivot') or definition.get('grouping_ref') or definition.get('grain','value')!='value':return []
    matching=[(k,c) for k,c in contract(user,model['dataset']).items() if c['field']==field]
    if len(matching)!=1:return []
    kind,c=matching[0];rows,_,_=engine.selected_rows(user,model['dataset'],model['definition'],scope)
    values={}
    for row in rows:values.setdefault(engine.group_key(row,definition),set()).add(row.get(field))
    out=[]
    for group in result['rows']:
        name=group['dimension'];actual=values.get(name,set())
        # A missing value and literal “未填写” may share a displayed group.
        if actual!={name}:continue
        if not 1<=len(name)<=150 or name!=name.strip() or any(ord(c)<32 for c in name):continue
        out.append(dict(group=name,kind=kind,value=name,label=c['label'],field=field,side=side))
    return out
