"""Bounded arithmetic over grouped measures, with dimensional and null checks.

Expressions never execute Python. Only m0..m4, finite constants, parentheses
and + - * / are interpreted. Result units convert the canonical quantity.
"""
import ast
from decimal import Decimal, DecimalException, localcontext
from django.core.exceptions import ValidationError

NOTICE='派生指标先按同一筛选范围汇总，再计算公式；引用字段有缺失、分母为零或结果超出范围时留空。选择元/台时自动由分换元，选择%时自动乘100；公式中不需重复换算。派生指标为未发布的分析定义。'
# Canonical quantities: money in fen, time in minutes; unlike units never add.
ATOMS={u:({dimension:1},Decimal(scale)) for u,dimension,scale in [
 ('分','money','1'),('元','money','100'),('分钟','time','1'),('小时','time','60'),
 ('台','motor','1'),('工单','work_order','1'),('订单行','order_line','1'),
 ('计划行','plan_line','1'),('采购行','purchase_line','1'),('发票','invoice','1'),
 ('次','event','1'),('条','row','1'),('个','object','1'),('人','person','1'),
 ('配置','configuration','1'),('设备','equipment','1'),('资源位','resource','1'),
 ('批','lot','1'),('kg','mass','1'),('件','piece','1'),('kWh','energy','1')
]}
ATOMS.update({'倍':({},Decimal(1)),'%':({},Decimal('.01'))})
ROW_UNITS={'bi_order_lines':'订单行','bi_work_orders':'工单','bi_units':'台',
 'bi_purchase':'采购行','bi_receivables':'发票','units':'台','work_orders':'工单',
 'order_lines':'订单行','purchase_lines':'采购行','employees':'人','products':'配置',
 'equipment':'设备','production_resources':'资源位','operations':'次','test_sessions':'次'}
MOTOR_FIELDS={'qty','allocated_qty','produced_qty','shipped_qty','remaining_qty','overdue_qty',
 'planned_qty','first_tested_count','first_pass_count','released_qty','pending_qty',
 'complete_count','released_count','shipped_count'}
TIME_MINUTES={'scheduled_minutes','blocked_minutes','available_minutes','busy_minutes',
 'downtime_minutes','fault_minutes','duration_minutes','minutes'}

def fail(message):raise ValidationError(message)

def combine(left,right,sign=1):
    out=dict(left)
    for key,value in right.items():out[key]=out.get(key,0)+value*sign
    return {key:value for key,value in out.items() if value}

def parse_unit(text):
    if not isinstance(text,str) or len(text)>40:fail('请填写支持的结果单位')
    parts=text.split('/')
    if len(parts)>2 or any(not p for p in parts):fail('单位仅支持基本单位，或“元/台”等单层相除')
    units=[]
    for part in parts:
        if part not in ATOMS:fail('不支持的单位：'+part+'；请使用界面列出的单位')
        units.append(ATOMS[part])
    if len(units)==1:return units[0]
    return combine(units[0][0],units[1][0],-1),units[0][1]/units[1][1]

def field_unit(dataset,name,fields):
    f=fields.get(name,{})
    if f.get('unit_field'):return ({'field-unit:'+f['unit_field']:1},Decimal(1))
    if dataset=='bi_work_orders' and name=='unit_cost_cents':return parse_unit('分/台')
    if name.endswith('_cents') and not name.startswith(('unit_','price','tariff')):return parse_unit('分')
    if name in TIME_MINUTES:return parse_unit('分钟')
    if name in ['release_hours','hours']:return parse_unit('小时')
    if name=='kwh':return parse_unit('kWh')
    if dataset in ['bi_order_lines','bi_work_orders','bi_units'] and name in MOTOR_FIELDS:return parse_unit('台')
    if name in ['due_plan_count','on_time_plan_count']:return parse_unit('计划行')
    if name in ['due_line_count','on_time_line_count']:return parse_unit('采购行')
    if name in ['session_count','downtime_events','maintenance_count','event_count','readings']:return parse_unit('次')
    if name=='iqc_rejected_count':return parse_unit('批')
    if name=='occupancy_pct':return parse_unit('%')
    fail('此字段尚未配置派生计算的单位约定：'+f.get('label',str(name)))

def metric_unit(dataset,metric,fields):
    agg=metric['agg'];field=metric.get('field')
    if agg=='count':return parse_unit(ROW_UNITS.get(dataset,'条'))
    if agg=='distinct':
        unit=ROW_UNITS.get(dataset,'个') if field=='id' else {'employee_id':'人','unit_id':'台','work_order_id':'工单','product_id':'配置','equipment_id':'设备','resource_id':'资源位','lot':'批'}.get(field,'个')
        return parse_unit(unit)
    if fields[field]['type'] not in ['int','float']:fail('派生公式只能引用数值度量')
    first=field_unit(dataset,field,fields)
    if agg=='ratio':
        second=field_unit(dataset,metric['denominator'],fields)
        if first!=second:fail('派生公式引用的比率须具有相同分子分母单位')
        return parse_unit('%')
    return first

def parse_formula(expression,size):
    if not isinstance(expression,str) or not 1<=len(expression)<=200:fail('公式需为1至200字')
    try:tree=ast.parse(expression,mode='eval')
    except (SyntaxError,RecursionError,ValueError):fail('公式格式不正确')
    nodes=list(ast.walk(tree))
    if len(nodes)>50:fail('公式过长，请拆分业务问题')
    permitted=(ast.Expression,ast.BinOp,ast.UnaryOp,ast.Add,ast.Sub,ast.Mult,ast.Div,ast.UAdd,ast.USub,ast.Name,ast.Load,ast.Constant)
    refs=set()
    for node in nodes:
        if not isinstance(node,permitted):fail('公式只支持度量编号m0…m4、数字、括号和 + - * /')
        if isinstance(node,ast.Name):
            if node.id not in {f'm{i}' for i in range(size)}:fail('公式引用了不存在的基础度量：'+node.id)
            refs.add(node.id)
        if isinstance(node,ast.Constant):
            if type(node.value) not in [int,float]:fail('公式常量必须是数字')
            value=Decimal(str(node.value))
            if not value.is_finite() or abs(value)>Decimal('1e9'):fail('公式常量超出允许范围')
    def depth(node):return 1+max((depth(n) for n in ast.iter_child_nodes(node)),default=0)
    if depth(tree)>12:fail('公式嵌套层级过深')
    if not refs:fail('派生公式至少引用一项基础度量')
    return tree.body,sorted(refs)

def dimensions(node,units):
    if isinstance(node,ast.Name):return units[node.id][0]
    if isinstance(node,ast.Constant):return {}
    if isinstance(node,ast.UnaryOp):return dimensions(node.operand,units)
    a,b=dimensions(node.left,units),dimensions(node.right,units)
    if isinstance(node.op,(ast.Add,ast.Sub)):
        if a!=b:fail('公式加减两侧的单位不同，不能相加减')
        return a
    return combine(a,b,-1 if isinstance(node.op,ast.Div) else 1)

def compile_definitions(dataset,definition,fields):
    items=definition.get('derived',[])
    if not isinstance(items,list) or len(items)>3:fail('最多3个派生指标')
    compiled=[]
    for index,item in enumerate(items):
        if not isinstance(item,dict) or set(item)!={'label','expression','unit'}:fail('派生指标须包含名称、公式与结果单位')
        if not isinstance(item['label'],str) or not 1<=len(item['label'].strip())<=80:fail('派生指标名称需为1至80字')
        node,refs=parse_formula(item['expression'],len(definition['metrics']))
        units={ref:metric_unit(dataset,definition['metrics'][int(ref[1:])],fields) for ref in refs}
        output_unit=parse_unit(item['unit'])
        if dimensions(node,units)!=output_unit[0]:fail('公式推导单位与结果单位不一致，请检查分子分母与单位')
        compiled.append(dict(key=f'd{index}',node=node,refs=refs,units=units,scale=output_unit[1],**item))
    return compiled

def interpret(node,values):
    if isinstance(node,ast.Name):return values[node.id]
    if isinstance(node,ast.Constant):return Decimal(str(node.value))
    if isinstance(node,ast.UnaryOp):
        v=interpret(node.operand,values);return -v if isinstance(node.op,ast.USub) else v
    a,b=interpret(node.left,values),interpret(node.right,values)
    if isinstance(node.op,ast.Add):value=a+b
    elif isinstance(node.op,ast.Sub):value=a-b
    elif isinstance(node.op,ast.Mult):value=a*b
    else:
        if b==0:raise ZeroDivisionError
        value=a/b
    if not value.is_finite() or abs(value)>Decimal('1e24'):raise OverflowError
    return value

def evaluate(compiled,raw,incomplete,invalid_resource=False):
    values={};notes=[]
    for item in compiled:
        reason=None;value=None
        if invalid_resource:reason='资源容量或时间证据异常'
        elif any(raw.get(r) is None or incomplete[r] for r in item['refs']):reason='引用度量存在缺失样本，未计算'
        else:
            try:
                with localcontext() as context:
                    context.prec=28
                    inputs={ref:Decimal(str(raw[ref]))*item['units'][ref][1] for ref in item['refs']}
                    value=interpret(item['node'],inputs)/item['scale']
                    if not value.is_finite() or abs(value)>Decimal('1e18'):raise OverflowError
                    value=int(value) if value==value.to_integral_value() else float(value)
            except ZeroDivisionError:reason='分母为零'
            except (DecimalException,OverflowError,ValueError):reason='计算数值超出允许范围'
        values[item['key']]=value if not reason else None
        if reason:notes.append({'metric':item['key'],'reason':reason})
    return values,notes

def describe(compiled):
    return [{'key':x['key'],'label':x['label']+' ('+x['unit']+')','unit':x['unit'],
             'expression':x['expression'],'dependencies':x['refs'],
             'input_scales':{r:str(x['units'][r][1]) for r in x['refs']},
             'output_scale':str(x['scale'])} for x in compiled]
