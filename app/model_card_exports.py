"""Exports bound to the private card result already read by its owner."""
import hashlib,json,re
from collections import defaultdict
from copy import deepcopy
from pathlib import Path
from django.core import signing
from django.core.exceptions import ValidationError
from django.core.serializers.json import DjangoJSONEncoder
from . import model_cards as cards,model_card_results as reading,analysis_engine as engine
from . import access,derived_metrics,business_groups,bi_card_summary,bi_field_catalog
from .import_review import ReviewConflict

FORMAT='motor.private-model-current-result.v1'
NOTICE='个人口径卡当前结果 · 合成模拟资料。文件与已查看结果使用同一范围、定义和来源；全部分组从原始来源按既有算法重算，不平均均值、不相加比率或分位数。下载文件不是服务器结果快照；不能撤回已下载副本，不新增原件、分享或业务执行权限。'
def encoded(value):return json.dumps(value,cls=DjangoJSONEncoder,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False)
def resolve(user,key,query):
 if set(query)-{'receipt','format'} or any(len(query.getlist(k))!=1 for k in query):raise ValidationError('结果导出字段未知或重复；不接受另加筛选或分组')
 kind=query.get('format','csv')
 if kind not in {'csv','json'}:raise ValidationError('结果导出格式仅支持CSV或JSON')
 token=query.get('receipt','')
 if not isinstance(token,str) or not token or len(token)>4096:raise ValidationError('请先运行口径卡并取得本次结果范围凭据')
 try:signed=signing.loads(token,salt=reading.SALT,max_age=reading.MAX_AGE)
 except signing.BadSignature:raise ReviewConflict('本次结果凭据无效或已过期，请重新运行后导出')
 u=cards.fresh(user);value,stamp=reading.build(u,cards.run(u,key))
 if signed!=stamp:raise ReviewConflict('资料、口径卡、模型、计算规则或权限已变化，请重新运行后导出')
 return u,value,stamp,kind

def complete(user,value):
 """Expand only display truncation; reuse the existing arithmetic and ordering."""
 r=value['result'];full=deepcopy(r);ds=r['dataset'];definition=r['resolved_definition']
 source,scanned,_=engine.selected_rows(user,ds,definition,None)
 if len(source)!=r['matched'] or scanned!=r['scanned']:raise ReviewConflict('导出期间来源范围变化，请重新运行')
 fields={f['name']:deepcopy(f) for f in access.permitted_fields(user,ds)}
 groups=defaultdict(list)
 for row in source:groups[engine.group_key(row,definition)].append(row)
 if r['truncated']:
  if 'pivot' in r or 'scatter' in r:raise ValidationError('特殊图形超过既有完整性门槛；未截断导出')
  compiled=derived_metrics.compile_definitions(ds,definition,fields);rows=[];parts=[];notes=[]
  for key in business_groups.order(groups,definition):
   out,p,n=engine.aggregate_group(ds,definition,fields,compiled,groups[key],key);rows.append(out);parts.extend(p);notes.extend(n)
  if definition.get('sort') in ('asc','desc'):
   display=r['display_metric'];valid=sorted([x for x in rows if x[display] is not None],key=lambda x:x[display],reverse=definition['sort']=='desc');rows=valid+[x for x in rows if x[display] is None]
  shown={x['dimension'] for x in r['rows']}
  if len(rows)!=r['groups'] or rows[:1000]!=r['rows'] or [p for p in parts if p['dimension'] in shown]!=r['components'] or [n for n in notes if n['dimension'] in shown]!=r['derived_notes']:raise ReviewConflict('完整分组与已查看结果不能核对，请重新运行')
  full.update(rows=rows,components=parts,derived_notes=notes,truncated=False)
 for name,f in fields.items():
  unit=bi_field_catalog.unit_info(ds,name,fields)
  if unit['kind']=='row':f['unit_field']=unit['unit_field']
  elif unit['kind']=='fixed':f['unit']=unit['unit']
 units={}
 for row in full['rows']:
  item={};samples=groups.get(row['dimension'],[])
  if 'pivot' in r:
   from .analysis_pivot import select
   samples=select(source,definition,dict(row=row['row'],column=None),r['pivot'])
  for i,m in enumerate(definition['metrics']):
   try:item['m'+str(i)]=dict(unit=bi_card_summary.metric_unit(ds,m,fields,samples),reason='')
   except ValidationError as e:item['m'+str(i)]=dict(unit=None,reason='；'.join(e.messages))
  for i,d in enumerate(definition.get('derived',[])):item['d'+str(i)]=dict(unit=d['unit'],reason='')
  units[row['dimension']]=item
 return full,units

def document(user,value,stamp):
 full,units=complete(user,value);context=deepcopy(value['reading']);context.pop('receipt');context.pop('receipt_seconds')
 context.update(exported_groups=len(full['rows']),complete_group_result=True)
 return dict(format=FORMAT,result_mode='current_data',card=deepcopy(value['card']),reading=context,result=full,group_units=units,field_contract=bi_field_catalog.dataset_contract(user,full['dataset']),
  integrity=dict(population_digest=stamp['population'],viewed_result_digest=stamp['result'],summary_digest=stamp['summary'],complete_result_digest=reading.digest(full),export_rule_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()),notice=NOTICE)

def safe_cell(value):
 if isinstance(value,str) and (re.match(r'^[\s\ufeff]*[=+\-@]',value) or value.startswith(('\t','\r','\n'))):return "'"+value
 return value

def csv_rows(doc):
 c=doc['card'];m=c['metadata'];d=doc['reading'];r=doc['result'];s=d['summary']
 rows=[['个人模型当前结果 · 合成模拟数据'],['格式',FORMAT],['个人模型编码',m['code'],'口径卡版本',c['current_revision'],'模型版本',c['binding']['source_model']['version']],
  ['业务问题',m['question']],['使用岗位',m['reader']],['本人粒度说明',m['object_grain']],['本人时间说明',m['time_scope']],['解释边界',m['limitations']],
  ['实际数据集',r['dataset'],'名称',d['dataset_label']],['实际粒度',d['grain'],'业务截止',d['business_as_of'],'日期角色',d['scope']['date_label']],
  ['实际范围',encoded(r['scope'])],['实际字段条件',encoded(d['conditions'])],['原登记定义',encoded(c['binding']['source_model']['definition'])],['实际计算定义',encoded(r['resolved_definition'])],
  ['发布指标',encoded(r['metric_receipt'])],['固定分组',encoded(r['grouping_receipt'])],['字段与单位契约',encoded(doc['field_contract'])],
  ['主结果',s['label'],'数值',s['value'],'单位',s['unit'],'状态',s['state']],['来源',s['source_rows'],'有效',s['valid_rows'],'缺失',s['missing_rows']],
  ['分子',s['numerator'],'分母',s['denominator']],['分位数与样本',encoded(s['quantile'])],['主结果解释',s['reason']],
  ['页面返回分组',d['returned_groups'],'全部分组',d['total_groups'],'导出分组',d['exported_groups']],['度量定义',encoded(r['measures'])],['说明',NOTICE],[]]
 if 'pivot' in r:
  from .analysis_pivot import export_rows
  rows+=export_rows(r)
 elif 'scatter' in r:
  from .analysis_scatter import export_rows
  rows+=export_rows(r)
 else:
  from .analysis_quantiles import evidence
  rows.append([r['dimension_label'],*[x['label'] for x in r['measures']],'来源行数','单位核对','比率分子分母','分位样本与说明','派生计算说明'])
  for row in r['rows']:
   key=row['dimension'];rows.append([key,*[row[x['key']] for x in r['measures']],row['row_count'],encoded(doc['group_units'].get(key,{})),encoded([p for p in r['components'] if p['dimension']==key]),evidence(row),encoded([n for n in r['derived_notes'] if n['dimension']==key])])
 rows+=[[],['来源与计算摘要',encoded(doc['integrity'])]]
 return [[safe_cell(cell) for cell in row] for row in rows]
