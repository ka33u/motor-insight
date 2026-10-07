"""Explicit dashboard scope contracts; unsupported filters fail closed."""
from collections import defaultdict
from datetime import date
from django.core.exceptions import ValidationError
from . import analytics, access
from .semantic_schema import schemas

LABELS={'family':'产品族','customer_id':'客户','from':'开始日期','to':'结束日期'}
DIRECT_PRODUCT={'quotes','order_lines','work_orders','units','bom','routes','test_specs','bi_order_lines','bi_work_orders','bi_units'}
UNIT_CONTEXT={'test_sessions','releases','nonconformities','service'}
WO_CONTEXT={'operations','costs','batches'}
LINE_CONTEXT={'delivery_plans','shipments'}
FAMILY_DATASETS=DIRECT_PRODUCT|UNIT_CONTEXT|WO_CONTEXT|LINE_CONTEXT|{'products','measurements'}
CUSTOMER_DATASETS={'orders','quotes','order_lines','units','work_orders','invoices','payments','bi_order_lines','bi_units','bi_work_orders','bi_receivables'}|UNIT_CONTEXT|WO_CONTEXT|LINE_CONTEXT|{'measurements'}
# Dates select object cohorts, never recreate a historical snapshot.
DATES={
 'orders':('order_date','下单日'),'quotes':('quote_date','报价日'),
 'order_lines':('@order_date','下单日'),'bi_order_lines':('order_date','下单日'),
 'work_orders':('planned_end','计划完工日'),'bi_work_orders':('planned_end','计划完工日'),
 'units':('assembly_at','装配日'),'bi_units':('assembly_at','装配日'),
 'test_sessions':('tested','检测发生日'),'measurements':('@tested','检测发生日'),
 'nonconformities':('found','问题发现日'),'releases':('released','放行日'),
 'delivery_plans':('due','承诺交付日'),'shipments':('shipped','发货日'),
 'operations':('started','工序开始日'),'costs':('occurred','成本发生日'),
 'invoices':('issued','开票日'),'bi_receivables':('issued','开票日'),'payments':('paid','回款日'),
 'purchase_lines':('ordered','采购日'),'bi_purchase':('ordered','采购日'),
 'receipts':('received','到货日'),'incoming_inspections':('inspected','来料检验日'),
 'inventory_movements':('occurred','库存移动日'),'inventory_status_events':('occurred','状态变更日'),
 'service':('reported','报修日'),'maintenance':('reported','报修日'),
 'downtime':('started','停机开始日'),'energy':('started','读数开始日'),
 'bi_equipment_day':('date','自然日（已拆跨日事件）'),'bi_energy_day':('date','自然日（已拆跨日读数）'),
 'bi_resource_day':('date','资源排班日（已拆跨日事件）'),'resource_calendars':('started','排班开始日'),'labor_entries':('started','作业开始日'),
}

def contract(dataset):
    return {'family':dataset in FAMILY_DATASETS,'customer_id':dataset in CUSTOMER_DATASETS,
            'date':dataset in DATES,'date_label':DATES.get(dataset,('', '无期间口径'))[1]}

def validate_scope(scope):
    if scope is None:return {}
    if not isinstance(scope,dict) or set(scope)-set(LABELS):raise ValidationError('专题筛选仅支持产品族、客户及日期范围')
    clean={}
    for key,value in scope.items():
        if value in (None,''):continue
        if not isinstance(value,str) or len(value)>150:raise ValidationError('专题筛选值格式不正确')
        if key in ['from','to']:
            try:
                if date.fromisoformat(value).isoformat()!=value:raise ValueError()
            except ValueError:raise ValidationError('日期必须为YYYY-MM-DD')
        clean[key]=value
    if clean.get('from','')>clean.get('to','9999-12-31'):raise ValidationError('开始日期不能晚于结束日期')
    return clean

def options(user):
    d=analytics.tables()
    return {'families':sorted({p['family'] for p in d['products']}),
            'customers':[{'id':c['id'],'name':c['name']} for c in d['customers']],
            'datasets':{key:contract(key) for key in schemas() if access.allowed(user,key)},
            'as_of':analytics.AS_OF,
            'note':'日期按各卡标注的业务日期筛选对象；对象状态仍截至模拟快照。库存余额不支持期间筛选，不能用最后变动日冒充历史库存。'}

def apply(dataset,rows,scope):
    scope=validate_scope(scope);meta=contract(dataset)
    unsupported=[LABELS[k] for k in scope if not meta['date' if k in ['from','to'] else k]]
    if unsupported:raise ValidationError('此卡无法应用'+ '、'.join(unsupported)+'筛选，已暂停计算；请重置该条件或更换有对应业务关系的模型')
    info={'filters':scope,'date_label':meta['date_label'],'as_of':analytics.AS_OF,'unknown_customer_rows':0,'matched':len(rows)}
    if not scope:return rows,info
    d=analytics.tables();indexes={key:{r['id']:r for r in d[key]} for key in ['products','orders','order_lines','work_orders','units','test_sessions','invoices']}
    assignments=defaultdict(set)
    for a in d['allocations']:
        if a['effective']<=analytics.AS_OF[:10]:assignments[a['work_order_id']].add(a['order_line_id'])

    def resolve(row):
        line=None;unit=None;wo=None;session=None;inv=None
        if dataset in ['order_lines','bi_order_lines']:line=indexes['order_lines'].get(row['id'])
        elif dataset in LINE_CONTEXT:line=indexes['order_lines'].get(row.get('order_line_id'))
        if dataset in ['units','bi_units']:unit=indexes['units'].get(row['id'])
        elif dataset in UNIT_CONTEXT:unit=indexes['units'].get(row.get('unit_id'))
        elif dataset=='measurements':
            session=indexes['test_sessions'].get(row.get('session_id'),{});unit=indexes['units'].get(session.get('unit_id'))
        if dataset in ['work_orders','bi_work_orders']:wo=indexes['work_orders'].get(row['id'])
        elif dataset in WO_CONTEXT:wo=indexes['work_orders'].get(row.get('work_order_id'))
        elif unit:wo=indexes['work_orders'].get(unit.get('work_order_id'))
        if dataset in ['invoices','bi_receivables']:inv=indexes['invoices'].get(row['id'])
        elif dataset=='payments':inv=indexes['invoices'].get(row.get('invoice_id'))
        product_id=row['id'] if dataset=='products' else row.get('product_id') or (unit or wo or line or {}).get('product_id')
        family=indexes['products'].get(product_id,{}).get('family')
        # A shared work order is not sufficient evidence of an individual SN's customer.
        if not line and wo:
            assigned=assignments[wo['id']]
            if len(assigned)==1:line=indexes['order_lines'].get(next(iter(assigned)))
        order=indexes['orders'].get((line or {}).get('order_id'),{})
        customer=row.get('customer_id') or (inv or {}).get('customer_id') or order.get('customer_id')
        field=DATES.get(dataset,('', ''))[0]
        when=order.get('order_date') if field=='@order_date' else (session or {}).get('tested') if field=='@tested' else row.get(field)
        return family,customer,str(when)[:10] if when else None

    result=[]
    for row in rows:
        family,customer,when=resolve(row)
        if 'family' in scope and family!=scope['family']:continue
        if 'from' in scope and (not when or when<scope['from']):continue
        if 'to' in scope and (not when or when>scope['to']):continue
        if 'customer_id' in scope:
            if not customer:info['unknown_customer_rows']+=1
            if customer!=scope['customer_id']:continue
        result.append(row)
    info['matched']=len(result)
    return result,info
