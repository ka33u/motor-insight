"""Current-data reading and owner-bound evidence for private model cards."""
import hashlib,json,re
from pathlib import Path
from django.core import signing
from django.core.exceptions import ValidationError
from django.core.serializers.json import DjangoJSONEncoder
from . import model_cards as cards,bi_card_summary,access,bi_field_catalog,analysis_engine
from .models import Record
from .import_review import ReviewConflict
SALT='motor.private-model-result.v1';MAX_AGE=600
NOTICE='当前资料按登记模型计算；整范围摘要从全部已筛选来源重算，不相加或平均分组结果。来源下钻须核对当前资料与权限；不保存当时业务结果。'
def digest(value):return hashlib.sha256(json.dumps(value,cls=DjangoJSONEncoder,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
def build(user,value):
 u=cards.fresh(user);c=value['card'];s=c['binding']['source_model'];r=value['result'];summary=bi_card_summary.build(u,s,r,None);contract=bi_field_catalog.dataset_contract(u,s['dataset']);fields={f['name']:f for f in contract['fields']}
 conditions=[dict(field=f['field'],label=fields[f['field']]['label'],op=f['op'],value=f['value']) for f in r['resolved_definition'].get('filters',[])]
 stamp=dict(card=c['id'],revision=c['current_revision'],payload_hash=c['payload_hash'],account=cards.spc_data.account(u),population=summary['population_digest'],summary=digest(summary),result=digest(r),rules=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
 value['reading']=dict(summary=summary,conditions=conditions,dataset_label=contract['label'],grain=r['grain'],scope=r['scope'],business_as_of=value['business_as_of'],chart=r['definition'].get('chart','bar'),display_key=r['display_metric'],display_label=r['display_label'],returned_groups=len(r['rows']),total_groups=r['groups'],truncated=r['truncated'],receipt=signing.dumps(stamp,salt=SALT,compress=True),receipt_seconds=MAX_AGE,notice=NOTICE)
 return value,stamp
def run(user,key):return build(user,cards.run(user,key))[0]
def evidence(user,key,query):
 allowed={'receipt','page','group','row','column','point'}
 if set(query)-allowed or any(len(query.getlist(k))!=1 for k in query):raise ValidationError('来源范围字段未知或重复')
 token=query.get('receipt','')
 if not isinstance(token,str) or not token or len(token)>4096:raise ValidationError('请先运行口径卡并取得结果范围凭据')
 try:signed=signing.loads(token,salt=SALT,max_age=MAX_AGE)
 except signing.BadSignature:raise ReviewConflict('结果来源凭据无效或已过期，请重新运行')
 u=cards.fresh(user);value,stamp=build(u,cards.run(u,key))
 if signed!=stamp:raise ReviewConflict('结果资料、模型定义、口径卡、计算依据或权限已变化，请重新运行')
 text=query.get('page','1')
 if not re.fullmatch(r'[1-9]\d{0,5}',text):raise ValidationError('来源页码须为正整数')
 page=int(text);r=value['result'];s=value['card']['binding']['source_model'];ds=s['dataset'];rows,_,_=analysis_engine.selected_rows(u,ds,s['definition'],None);selection={k:query[k] for k in ('group','row','column','point') if k in query};label='全部已筛选来源'
 if selection:
  if 'pivot' in r:
   if set(selection)!={'row','column'}:raise ValidationError('透视来源需完整行列身份；不能改用普通分组')
   from .analysis_pivot import select
   chosen={k:selection[k] or None for k in ('row','column')};rows=select(rows,r['resolved_definition'],chosen,r['pivot']);label='透视所选行列交集'
  elif 'scatter' in r:
   if set(selection)!={'point'}:raise ValidationError('散点来源需指定点身份')
   from .analysis_scatter import selection as choose
   p=choose(r,selection['point']);rows=[v for v in rows if analysis_engine.group_key(v,r['resolved_definition'])==p['dimension']];label=p['dimension']
  else:
   if set(selection)!={'group'} or selection['group'] not in {v['dimension'] for v in r['rows']}:raise ValidationError('来源分组不在本次返回结果中；未回退全部范围')
   rows=[v for v in rows if analysis_engine.group_key(v,r['resolved_definition'])==selection['group']];label=selection['group']
 total=len(rows);selected=sorted(rows,key=lambda v:str(v['id']))[(page-1)*30:page*30];provenance={}
 if ds not in analysis_engine.SEMANTIC_SCHEMAS:
  for record in Record.objects.filter(dataset=ds,business_key__in=[v['id'] for v in selected]).select_related('source_row__batch'):
   provenance[record.business_key]=dict(file=record.source_row.batch.filename,sheet=record.source_row.sheet,row=record.source_row.row_number)
 return dict(total=total,page=page,size=30,selection_label=label,dataset=ds,fields=access.permitted_fields(u,ds),rows=[dict(values=access.sanitize(u,ds,v),source=provenance.get(v['id']),references=[ref for ref in v.get('_sources',[]) if access.allowed(u,ref['dataset'])]) for v in selected],notice='来源按当前权限核对，与本次结果凭据一致；分页不改变选择范围。')
