"""Private model codes, explicit metadata and immutable definition references."""
import copy,hashlib,json,re,uuid
from datetime import date
from pathlib import Path
from django.core import signing
from django.core.serializers.json import DjangoJSONEncoder
from django.core.exceptions import ValidationError,ObjectDoesNotExist,PermissionDenied
from django.db import transaction
from django.contrib.auth import get_user_model
from .models import AnalysisModel,AnalysisModelCard,AnalysisModelCardVersion,AuditEvent
from . import access,spc_data,analytics,metric_registry,business_groups,semantic_schema
from .analysis_engine import validate_definition,run_analysis
from .views import visible,model_info
from .import_review import ReviewConflict
SALT='motor.model.card.capture.v1';MAX_AGE=600;MAX_CARDS=100
FIELDS={'code','name','question','reader','object_grain','time_scope','limitations','review_on','model_id','receipt'}
NOTICE='个人模型口径卡保存编码、业务说明和当时定义版本，不保存业务结果或历史数据。模型、引用指标/分组或计算依据改变时须重新核对；不是正式指标认证或业务批准。'
def digest(value):return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
def rules():
 files=('model_cards.py','analysis_engine.py','analysis_drill.py','analysis_pivot.py','analysis_scatter.py','analysis_quantiles.py','derived_metrics.py','business_groups.py','metric_registry.py','semantic.py','bi_scope.py')
 return hashlib.sha256(b''.join((Path(__file__).parent/name).read_bytes() for name in files)).hexdigest()
def fresh(user):
 u=get_user_model().objects.get(pk=user.pk);spc_data.account(u);return u
def integer(value,label):
 if type(value) is not int or value<=0:raise ValidationError(label+'须为正整数')
 return value
def text(v,label,maxlen):
 if not isinstance(v,str) or not 1<=len(v.strip())<=maxlen:raise ValidationError(label+'需填写且不能超长')
 return v.strip()
def metadata(data):
 code=data['code']
 if not isinstance(code,str) or not re.fullmatch(r'[A-Z][A-Z0-9._-]{2,79}',code):raise ValidationError('模型编码须3至80位大写字母、数字、点、下划线或短横线，以字母开头')
 out={'code':code}
 for field,label,limit in [('name','口径卡名称',150),('question','业务问题',500),('reader','使用岗位',200),('object_grain','对象粒度说明',500),('time_scope','时间范围说明',500),('limitations','解释边界',2000)]:out[field]=text(data[field],label,limit)
 v=data['review_on']
 if v is not None:
  if not isinstance(v,str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}',v):raise ValidationError('复查日期须为完整日期或留空')
  date.fromisoformat(v)
 out['review_on']=v;return out
def capture(user,key):
 integer(key,'分析模型编号');m=visible(user,AnalysisModel.objects.all()).get(pk=key)
 validate_definition(user,m.dataset,m.definition,allow_inactive=True)
 resolved,metric=metric_registry.resolve(user,m.dataset,m.definition,allow_inactive=True)
 grouping=business_groups.resolve(user,m.dataset,resolved)
 schema=semantic_schema.schemas()[m.dataset]
 binding=dict(source_model=copy.deepcopy(model_info(m)),resolved_definition=copy.deepcopy(resolved),metric=copy.deepcopy(metric),grouping=copy.deepcopy(grouping),
  dataset_contract=dict(key=m.dataset,label=schema['label'],grain=schema.get('grain','一行一条原始来源记录'),virtual=bool(schema.get('virtual'))),rules_hash=rules())
 # Published metric timestamps must have the same representation before hashing,
 # after JSONField persistence and when comparing with the current definition.
 return json.loads(json.dumps(binding,cls=DjangoJSONEncoder,ensure_ascii=False,allow_nan=False))
def preview(user,key):
 u=fresh(user);c=capture(u,key);stamp=dict(model_id=key,binding_hash=digest(c),account=spc_data.account(u));return dict(binding=c,binding_hash=stamp['binding_hash'],receipt=signing.dumps(stamp,salt=SALT,compress=True),receipt_seconds=MAX_AGE,notice=NOTICE)
def checked(user,key,receipt):
 if not isinstance(receipt,str) or not receipt or len(receipt)>4096:raise ValidationError('请先读取当前模型定义并取得核对凭据')
 try:s=signing.loads(receipt,salt=SALT,max_age=MAX_AGE)
 except signing.BadSignature:raise ReviewConflict('模型定义凭据无效或已过期，请重新读取')
 c=capture(user,key)
 if s!=dict(model_id=key,binding_hash=digest(c),account=spc_data.account(user)):raise ReviewConflict('模型定义、引用依据、计算版本或权限已变化，请重新读取')
 return c
def version(card,number=None):
 v=card.versions.get(revision=number or card.revision)
 if digest(v.payload)!=v.payload_hash:raise ReviewConflict('口径卡版本摘要待核对')
 if v.revision==card.revision and (v.payload['metadata']['code']!=card.code or v.payload['archived']!=card.archived):raise ReviewConflict('口径卡当前指针与版本不同')
 return v
def readable(user,payload):
 s=payload['binding']['source_model'];m=visible(user,AnalysisModel.objects.all()).filter(pk=s['id']).first()
 if m is None:raise AnalysisModelCard.DoesNotExist()
 validate_definition(user,s['dataset'],s['definition'],allow_inactive=True)
 validate_definition(user,m.dataset,m.definition,allow_inactive=True)
 return m
def get_card(user,key,lock=False):
 u=fresh(user);q=AnalysisModelCard.objects.select_for_update() if lock else AnalysisModelCard.objects;c=q.get(pk=key,owner=u);readable(u,version(c).payload);return c
def info(card,user,number=None):
 v=version(card,number);payload=v.payload;readable(user,payload);current=capture(user,payload['binding']['source_model']['id'])
 same=current==payload['binding'];review=payload['metadata']['review_on'];today=analytics.AS_OF[:10]
 return dict(id=str(card.pk),owner=user.username,current_revision=card.revision,revision=v.revision,metadata=payload['metadata'],binding=payload['binding'],payload_hash=v.payload_hash,
  archived=payload['archived'],current_archived=card.archived,definition_state='same' if same else 'changed',review_due=bool(review and review<=today),review_as_of=today,created_at=v.created_at,
  current_model=dict(id=current['source_model']['id'],name=current['source_model']['name'],version=current['source_model']['version'],dataset=current['source_model']['dataset']),notice=NOTICE)
@transaction.atomic
def save(user,data,key=None):
 u=fresh(user);needed=FIELDS|{'request_id'}|({'revision'} if key else set())
 if not isinstance(data,dict) or set(data)!=needed:raise ValidationError('口径卡字段不完整或含未知字段')
 rid=uuid.UUID(str(data['request_id']));h=digest(data);old=AnalysisModelCardVersion.objects.filter(request_id=rid).select_related('card').first()
 if old:
  if old.card.owner_id!=u.pk or old.request_hash!=h or key and str(old.card_id)!=str(key):raise ReviewConflict('申请号已用于其他内容')
  readable(u,old.payload);return old.card,old.revision,True
 meta=metadata(data);binding=checked(u,integer(data['model_id'],'模型编号'),data['receipt']);card=get_card(u,key,True) if key else None
 if card:
  if type(data['revision']) is not int or data['revision']!=card.revision:raise ReviewConflict('口径卡版本已变化，请重新读取')
  if card.archived:raise ReviewConflict('口径卡已归档，请先重新启用')
 else:
  if AnalysisModelCard.objects.filter(owner=u).count()>=MAX_CARDS:raise ValidationError('当前演示每人最多100张口径卡')
 if AnalysisModelCard.objects.filter(owner=u,code=meta['code']).exclude(pk=card.pk if card else None).exists():raise ValidationError('本人已有此模型编码，请更新原卡或使用其他编码')
 if card:card.code=meta['code'];card.revision+=1;card.save()
 else:card=AnalysisModelCard.objects.create(owner=u,code=meta['code'])
 payload=dict(metadata=meta,binding=binding,archived=False)
 AnalysisModelCardVersion.objects.create(card=card,revision=card.revision,payload=payload,payload_hash=digest(payload),request_id=rid,request_hash=h)
 AuditEvent.objects.create(action='model_card.update' if key else 'model_card.create',actor=u.username,object_type='AnalysisModelCard',object_id=str(card.pk),detail=dict(revision=card.revision,payload_hash=digest(payload),model_id=data['model_id'],business_facts_changed=False,shared_model_changed=False))
 return card,card.revision,False
@transaction.atomic
def archive(user,key,data):
 u=fresh(user)
 if not isinstance(data,dict) or set(data)!={'request_id','revision','archived'} or type(data['archived']) is not bool:raise ValidationError('归档需申请号、当前版本与布尔状态')
 rid=uuid.UUID(str(data['request_id']));h=digest(dict(card_id=str(key),**data));old=AnalysisModelCardVersion.objects.filter(request_id=rid).select_related('card').first()
 if old:
  if old.card.owner_id!=u.pk or str(old.card_id)!=str(key) or old.request_hash!=h:raise ReviewConflict('申请号已用于其他内容')
  readable(u,old.payload);return old.card,old.revision,True
 card=get_card(u,key,True)
 if type(data['revision']) is not int or data['revision']!=card.revision:raise ReviewConflict('口径卡版本已变化，请重新读取')
 payload=copy.deepcopy(version(card).payload);payload['archived']=data['archived'];card.archived=data['archived'];card.revision+=1;card.save(update_fields=['archived','revision','updated_at'])
 AnalysisModelCardVersion.objects.create(card=card,revision=card.revision,payload=payload,payload_hash=digest(payload),request_id=rid,request_hash=h)
 AuditEvent.objects.create(action='model_card.archive',actor=u.username,object_type='AnalysisModelCard',object_id=str(card.pk),detail=dict(revision=card.revision,archived=card.archived,business_facts_changed=False))
 return card,card.revision,False
def run(user,key):
 u=fresh(user);card=get_card(u,key);payload=version(card).payload;binding=payload['binding'];s=binding['source_model']
 if card.archived:raise ReviewConflict('口径卡已归档，当前分析暂停')
 if capture(u,s['id'])!=binding:raise ReviewConflict('当前模型或所引依据与登记版本不同，请先核对再更新口径卡')
 # This is a current-data execution, never a captured historic result.
 result=run_analysis(u,s['dataset'],s['definition'])
 if capture(fresh(u),s['id'])!=binding:raise ReviewConflict('分析期间模型或计算依据变化，请重新读取')
 return dict(card=info(card,u),result=result,result_mode='current_data',business_as_of=analytics.AS_OF,notice='按登记定义读取当前合成数据；未保存结果或原始数据快照。')
