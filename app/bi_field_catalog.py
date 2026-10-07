"""Read-only, permission-scoped documentation of existing BI field contracts.

Presentation metadata does not extend formula permissions or mutate schemas.
"""
import hashlib,json
from pathlib import Path
from copy import deepcopy
from functools import lru_cache
from django.core.exceptions import ValidationError,PermissionDenied
from . import access,derived_metrics as dm,analysis_scatter as scatter,bi_scope
from .semantic_schema import schemas
from .file_sharing import fresh,account_receipt
from .import_review import ReviewConflict

REVISION='bi-field-documentation-v1'
NOTICE='字段字典来自现有模拟数据契约，说明编码、类型、单位、关联及日期；不包含业务记录，不代表主数据已审定或真实U8/MES已接入。单位提示不扩大公式权限、不换算数据、不认证指标；参数、队列余额和不同单位的量不能因可聚合而直接合计。'
STATIC={('delivery_plans','qty'):('台','销售订单行分批交付的整机约定数量'),('shipments','qty'):('台','发货行中整机数量，客户签收数量另核'),('attendance','productive_hours'):('小时','人员日期台账中的生产工时'),('attendance','setup_hours'):('小时','人员日期台账中的换型工时'),('attendance','wait_hours'):('小时','人员日期台账中的等待工时'),('attendance','rework_hours'):('小时','人员日期台账中的返工工时'),('attendance','overtime_hours'):('小时','人员日期台账中的其中加班工时；不作为新增工时再相加')}
TYPES={'str':'文本/编码','int':'整数','float':'数值','bool':'是否','date':'日期','datetime':'时间'}

def digest(value):return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,default=str,separators=(',',':')).encode()).hexdigest()
def revision():return digest([REVISION,hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),hashlib.sha256(Path(scatter.__file__).read_bytes()).hexdigest(),hashlib.sha256(Path(dm.__file__).read_bytes()).hexdigest()])
def named_unit(unit):
 return _named_unit(tuple(sorted(unit[0].items())),unit[1])
@lru_cache(maxsize=128)
def _named_unit(dimensions,scale):
 unit=(dict(dimensions),scale)
 for key,value in dm.ATOMS.items():
  if value==unit:return key
 for a in dm.ATOMS:
  for b in dm.ATOMS:
   name=a+'/'+b
   if dm.parse_unit(name)==unit:return name
 return None

def unit_info(dataset,field,fields):
 f=fields[field]
 if f['type'] not in ('int','float'):return dict(kind='not_applicable',unit=None,unit_field=None,basis='文本、编码、日期和是否字段没有数值计量单位',formula_supported=False)
 uf=f.get('unit_field') or scatter.DYNAMIC.get(dataset,{}).get(field)
 if uf:
  if uf not in fields:return dict(kind='unknown',unit=None,unit_field=None,basis='计量单位字段在当前身份下不可核对',formula_supported=False)
  try:dm.field_unit(dataset,field,fields);supported=True
  except ValidationError:supported=False
  return dict(kind='row',unit=None,unit_field=uf,basis='按每条来源的单位字段核对；多个单位不混算、不自动换算',formula_supported=supported)
 try:
  unit=named_unit(dm.field_unit(dataset,field,fields))
  if unit:return dict(kind='fixed',unit=unit,unit_field=None,basis='现有派生计算字段单位约定',formula_supported=True)
 except ValidationError:pass
 if (dataset,field) in STATIC:unit,basis=STATIC[(dataset,field)]
 elif field in scatter.STATIC.get(dataset,{}):unit=scatter.STATIC[dataset][field];basis='现有散点分析字段单位说明'
 elif f.get('unit'):unit=f['unit'];basis='现有字段的显式单位'
 else:return dict(kind='unknown',unit=None,unit_field=None,basis='现有契约尚未声明可核对的单位，不凭字段名或样本值猜测',formula_supported=False)
 return dict(kind='fixed',unit=unit,unit_field=None,basis=basis,formula_supported=False)

def summability(dataset,f,u):
 if f['type'] not in ('int','float'):return '用于分组、筛选、去重或文本/日期最值；编码不作数量'
 if u['kind']=='unknown':return '单位尚未确认，不能把汇总值解释为业务总量'
 if u['kind']=='row':return '须确认同一单位及业务对象；先按单位筛选或分单位表格，禁止跨单位合计'
 if f['name'] in ['power_kw','voltage','poles','standard_hours','unit_price_cents','price_cents','unit_cost_cents','tariff_cents','hourly_cents']:return '配置参数、单价或标准值；简单合计通常不形成有效业务总量，均值也需声明记录权重'
 if dataset in ['bi_inventory','inventory_opening','inventory_counts'] or f['name'] in ['balance_cents','opening_balance_cents','opening_qty','balance_qty','available_qty']:return '状态/余额类字段先核对业务截止和对象去重；不能把多个时点余额直接相加'
 if f['name'].endswith('_cents'):return '同币种、价税和结账口径后按对象核对；不能把单据金额直接认定为收入或利润'
 if dataset=='attendance' and f['name']=='overtime_hours':return '其中加班属于工时的交叉说明，不与生产、换型、等待和返工工时再相加；人员与班次归属需核对'
 if 'hours' in f['name'] or 'minutes' in f['name']:return '区分登记工时、标准时间和自然历时；重叠事件、跨日及团队分摊须按具体模型核对'
 return '在同一来源粒度、对象归属与日期下核对；一对多连接及重复对象可能放大量值'

def field_contract(dataset,f,fields,primary):
 u=unit_info(dataset,f['name'],fields);reference=f.get('reference');raw=dict(name=f['name'],label=f['label'],type=f['type'],type_label=TYPES[f['type']],required=f['required'],primary_key=f['name']==primary,reference=reference,unit_info=u)
 raw.update(identity_rule='按文本保留前导零、大小写及分隔符；不能转成数值发号' if f['type']=='str' and (raw['primary_key'] or reference) else '沿用现有字段类型，不自动改号或补默认值',missing_rule='来源契约要求填写；要求必填不等于现有数据已全部合格' if f['required'] else '允许缺失；分析按原聚合规则处理，不把空缺默认当成0',aggregation_note=summability(dataset,f,u),aggregations=['count','distinct',*(['min','max'] if f['type']!='bool' else []),*(['sum','avg','median','percentile','ratio'] if f['type'] in ['int','float'] else [])])
 return raw

def dataset_contract(user,key):
 allschemas=schemas()
 if key not in allschemas or not access.allowed(user,key):raise PermissionDenied('此数据集的字段契约不可访问')
 schema=allschemas[key];fields={f['name']:deepcopy(f) for f in access.permitted_fields(user,key)}
 for f in fields.values():
  if f.get('reference') and not access.allowed(user,f['reference']):f['reference']=None
 sourcekeys=[k for k in schema.get('sources',[]) if access.allowed(user,k)]
 return dict(key=key,label=schema['label'],department=schema['department'],schema_version=schema['version'],virtual=bool(schema.get('virtual')),grain=schema.get('grain','一行一条'+schema['label']+'来源记录；需按主键核对，不跨表直接相加'),primary_key=schema['primary_key'],date_contract=bi_scope.contract(key),note=schema.get('note','Excel来源按字段契约校验；引用关系只声明目标表，不证明连接基数和业务归属'),sources=[dict(key=k,label=allschemas[k]['label']) for k in sourcekeys],source_scope='只列当前账号可访问的来源表',fields=[field_contract(key,f,fields,schema['primary_key']) for f in fields.values()])

def config(data):
 if set(data)-{'dataset','q','kind','unit_state'}:raise ValidationError('字段查找只支持数据集、搜索、类型和单位状态')
 d={k:data.get(k,'') for k in ['dataset','q','kind','unit_state']}
 if any(not isinstance(v,str) for v in d.values()) or len(d['q'])>100 or len(d['dataset'])>80:raise ValidationError('字段筛选格式或长度无效')
 if d['kind'] not in ('','numeric','text','date','relationship'):raise ValidationError('字段类型筛选无效')
 if d['unit_state'] not in ('','fixed','row','unknown','not_applicable'):raise ValidationError('单位状态筛选无效')
 return {k:v.strip() for k,v in d.items()}

def build(user,filters):
 user=fresh(user);conf=config(filters);allcontracts=[dataset_contract(user,k) for k in schemas() if access.allowed(user,k)]
 if conf['dataset'] and conf['dataset'] not in {d['key'] for d in allcontracts}:raise PermissionDenied('此数据集的字段契约不可访问')
 rows=[]
 for d in allcontracts:
  if conf['dataset'] and d['key']!=conf['dataset']:continue
  for f in d['fields']:
   kind=conf['kind']
   if kind=='numeric' and f['type'] not in ('int','float') or kind=='text' and f['type'] not in ('str','bool') or kind=='date' and f['type'] not in ('date','datetime') or kind=='relationship' and not f['reference']:continue
   if conf['unit_state'] and f['unit_info']['kind']!=conf['unit_state']:continue
   if conf['q'] and conf['q'].casefold() not in ' '.join([d['key'],d['label'],d['department'],f['name'],f['label'],f['unit_info']['unit'] or '',f['reference'] or '']).casefold():continue
   rows.append(dict(dataset=d['key'],dataset_label=d['label'],department=d['department'],grain=d['grain'],schema_version=d['schema_version'],date_contract=d['date_contract'],**f))
 receipt=digest([revision(),account_receipt(user),conf,allcontracts])
 return dict(revision=REVISION,algorithm=revision(),filters=conf,receipt=receipt,notice=NOTICE,rows=rows,total=len(rows),datasets=[{k:d[k] for k in ['key','label','department','schema_version','virtual','grain','primary_key','date_contract','note','sources','source_scope']}|{'field_count':len(d['fields'])} for d in allcontracts],authorized_fields=sum(len(d['fields']) for d in allcontracts),unit_state_counts={k:sum(f['unit_info']['kind']==k for f in rows) for k in ['fixed','row','unknown','not_applicable']},contains_business_values=False)

def board(user,data,page=1):
 if type(page) is not int or not 1<=page<=100000:raise ValidationError('字段页码无效')
 d=build(user,data);d['rows']=d['rows'][(page-1)*25:page*25];d.update(page=page,size=25);return d

def export_data(user,data,receipt):
 d=build(user,data)
 if d['receipt']!=receipt:raise ReviewConflict('字段契约、范围、单位说明或账号权限已变化，请重新查询再导出')
 selected={f['dataset'] for f in d['rows']}|({d['filters']['dataset']} if d['filters']['dataset'] else set())
 d['datasets']=[s for s in d['datasets'] if s['key'] in selected]
 d['export_scope']='仅匹配字段及涉及的数据集元数据；授权字段总数为当前账号的全目录参照'
 return d
