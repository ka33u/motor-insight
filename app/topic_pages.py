"""Private versioned presentation over existing topics; no metric or fact writes."""
import copy,hashlib,json,re,uuid
from pathlib import Path
from django.contrib.auth import get_user_model
from django.core import signing
from django.core.exceptions import PermissionDenied,ValidationError
from django.db import transaction
from . import access,spc_data,topic_workspace as ws,topic_linkage
from .models import TopicPage,TopicPageVersion,TopicPageRequest,AuditEvent
from .import_review import ReviewConflict
SALT='motor.topic-page.definition.v1';AGE=600
NOTICE='个人页面编排只保存业务问题、分区、顺序、显示宽度、说明和导航，复用原专题与模型计算。布局版本不保存经营数值；结果快照另在原专题保存。说明不改变筛选、单位或指标口径，不形成审批或团队发布。'
ROLES={'result':'主结果','explain':'解释与比较','objects':'处理对象','evidence':'依据与口径','action':'下一步与复查'}
def digest(v):return ws.digest(v)
def rules():
 return digest({n:hashlib.sha256(Path(__file__).with_name(n).read_bytes()).hexdigest() for n in ('topic_pages.py','topic_page_views.py')})
def fresh(user):
 u=get_user_model().objects.get(pk=user.pk)
 if not access.role(u):raise PermissionDenied('当前账号不可使用专题页面')
 return u
def integer(v,label):
 if type(v) is not int or v<1:raise ValidationError(label+'须为正整数')
 return v
def text(v,label,limit,empty=False):
 if not isinstance(v,str) or len(v.strip())>limit or (not empty and not v.strip()) or any(ord(c)<32 and c not in '\n\t' for c in v):raise ValidationError(label+'长度或内容无效')
 return v.strip()
def exact(v,keys,label):
 if not isinstance(v,dict) or set(v)!=set(keys):raise ValidationError(label+'字段不完整或包含未知项')
def definition(v):
 exact(v,('topic_id','code','title','question','cadence','sections','navigation'),'页面定义')
 code=text(v['code'],'页面编码',80)
 if not re.fullmatch(r'[A-Z][A-Z0-9._-]{2,79}',code):raise ValidationError('页面编码须3—80位，以大写字母开头，使用大写字母、数字、点、下划线或短横线')
 d=dict(topic_id=integer(v['topic_id'],'专题编号'),code=code,title=text(v['title'],'页面标题',120),question=text(v['question'],'业务问题',500),cadence=text(v['cadence'],'使用节奏',200),sections=[],navigation=[])
 if not isinstance(v['sections'],list) or not 1<=len(v['sections'])<=8:raise ValidationError('页面需要1—8个分区')
 slots=[];ids=set();result_count=0
 for s in v['sections']:
  exact(s,('id','title','role','note','cards'),'分区');key=text(s['id'],'分区编码',40)
  if not re.fullmatch(r'[A-Z][A-Z0-9_]{0,39}',key) or key in ids:raise ValidationError('分区编码无效或重复')
  ids.add(key)
  if s['role'] not in ROLES:raise ValidationError('分区职责无效')
  if not isinstance(s['cards'],list) or not 1<=len(s['cards'])<=12:raise ValidationError('每个分区需要1—12张原专题卡片')
  section=dict(id=key,title=text(s['title'],'分区标题',80),role=s['role'],note=text(s['note'],'分区说明',1000,True),cards=[])
  for c in s['cards']:
   exact(c,('slot','span','title','note'),'卡片编排')
   if type(c['slot']) is not int or not 0<=c['slot']<12 or type(c['span']) is not int or c['span'] not in (1,2):raise ValidationError('卡片序号或显示宽度无效')
   slots.append(c['slot']);result_count+=s['role']=='result';section['cards'].append(dict(slot=c['slot'],span=c['span'],title=text(c['title'],'卡片阅读标题',100,True),note=text(c['note'],'卡片说明',1000,True)))
  d['sections'].append(section)
 if len(slots)!=len(set(slots)):raise ValidationError('原专题卡片不能重复安排')
 if result_count>3:raise ValidationError('主结果分区最多3张卡；其他内容可放解释或对象分区')
 if not isinstance(v['navigation'],list) or len(v['navigation'])>8:raise ValidationError('最多8个专题导航')
 targets=set()
 for n in v['navigation']:
  exact(n,('topic_id','label','mode'),'导航');key=integer(n['topic_id'],'目标专题')
  if key in targets or key==d['topic_id'] or n['mode'] not in ('inherit','new'):raise ValidationError('目标重复、指向本专题或导航模式无效')
  targets.add(key);d['navigation'].append(dict(topic_id=key,label=text(n['label'],'导航标签',80),mode=n['mode']))
 return d
def binding(user,d):
 ctx=ws.context(user,d['topic_id']);slots=[c['slot'] for s in d['sections'] for c in s['cards']]
 if set(slots)!=set(range(len(ctx['cards']))) or len(slots)!=len(ctx['cards']):raise ValidationError('页面须保留原专题全部卡片，各安排一次；不能隐藏不利或不可用卡片')
 targets=[dict(topic_id=n['topic_id'],binding=ws.context(user,n['topic_id'])['binding']) for n in d['navigation']]
 return dict(topic=ctx['binding'],navigation=targets,rules=rules()),ctx
def preview(user,v):
 u=fresh(user);d=definition(v);b,ctx=binding(u,d);p=dict(definition=d,binding=b,notice=NOTICE)
 stamp=dict(payload_hash=digest(p),account=spc_data.account(u))
 return dict(payload=p,payload_hash=stamp['payload_hash'],receipt=signing.dumps(stamp,salt=SALT+'.preview',compress=True),receipt_seconds=AGE,unavailable_cards=sum(not c['available'] for c in ctx['cards']),notice=NOTICE)
def checked(user,d,receipt):
 if not isinstance(receipt,str) or len(receipt)>4096:raise ValidationError('请先预览当前页面定义')
 try:s=signing.loads(receipt,salt=SALT+'.preview',max_age=AGE)
 except signing.BadSignature:raise ReviewConflict('页面预览凭据无效或过期，请重新预览')
 p=preview(user,d)
 if s!=dict(payload_hash=p['payload_hash'],account=spc_data.account(user)):raise ReviewConflict('专题、模型、页面内容、规则或权限变化，请重新预览')
 return p['payload']
def owned(user,key,lock=False):
 q=TopicPage.objects.select_for_update() if lock else TopicPage.objects
 return q.get(pk=key,owner=user)
def version(page,number=None):
 v=page.versions.get(number=number or page.current_version)
 if digest(v.payload)!=v.payload_hash:raise ReviewConflict('页面历史载荷摘要不一致，暂停读取')
 return v
def info(user,page,number=None):
 v=version(page,number);p=v.payload;b,ctx=binding(user,p['definition']);same=b==p['binding']
 return dict(id=str(page.pk),code=page.code,topic_id=page.topic_id,revision=page.revision,version=v.number,current_version=page.current_version,archived=page.archived,definition=copy.deepcopy(p['definition']),binding=copy.deepcopy(p['binding']),current_binding=b,payload_hash=v.payload_hash,stale=not same,ready=same and not page.archived,topic=ctx['topic'],notice=NOTICE)
def read_stamp(user,d):
 return dict(id=d['id'],revision=d['revision'],version=d['version'],current_version=d['current_version'],archived=d['archived'],payload_hash=d['payload_hash'],current_binding_hash=digest(d['current_binding']),account=spc_data.account(user),rules=rules())
def read(user,key,number=None):
 u=fresh(user);d=info(u,owned(u,key),number);d.update(receipt=signing.dumps(read_stamp(u,d),salt=SALT+'.read',compress=True),receipt_seconds=AGE);return d
def checked_read(user,key,number,receipt):
 u=fresh(user);d=info(u,owned(u,key),number)
 if not isinstance(receipt,str) or len(receipt)>4096:raise ValidationError('请先读取当前页面版本')
 try:s=signing.loads(receipt,salt=SALT+'.read',max_age=AGE)
 except signing.BadSignature:raise ReviewConflict('页面读取凭据无效或过期，请重新读取')
 if s!=read_stamp(u,d):raise ReviewConflict('页面版本、专题、规则或权限变化，请重新读取')
 return u,d
def request_key(value):
 try:return uuid.UUID(str(value))
 except (ValueError,TypeError,AttributeError):raise ValidationError('请提供有效操作编号')
def replay(user,key,h,action):
 r=TopicPageRequest.objects.filter(request_id=key).first()
 if not r:return None
 if r.owner_id!=user.pk or r.request_hash!=h or r.action!=action:raise ReviewConflict('操作编号已用于其他请求')
 info(user,owned(user,r.page_id));return {**r.response,'replayed':True}
@transaction.atomic
def save(user,data,key=None):
 u=fresh(user);fields={'request_id','definition','receipt','reason'}|({'revision'} if key else set());exact(data,fields,'保存请求');d=definition(data['definition']);reason=text(data['reason'],'保存依据',1000)
 if len(reason)<5:raise ValidationError('保存依据至少5字')
 request_id=request_key(data['request_id']);action='update' if key else 'create';h=digest(dict(action=action,page=str(key) if key else None,definition=d,reason=reason,revision=data.get('revision')))
 old=replay(u,request_id,h,action)
 if old:return old
 payload=checked(u,d,data['receipt']);payload['reason']=reason
 if key:
  page=owned(u,key,True)
  if type(data['revision']) is not int or data['revision']!=page.revision:raise ReviewConflict('页面已更新，请重新读取')
  if page.archived:raise ValidationError('请先恢复已归档页面')
  if (page.code,page.topic_id)!=(d['code'],d['topic_id']):raise ValidationError('页面编码和原专题身份固定；不同身份请另建页面')
  if page.current_version>=200:raise ValidationError('每个页面最多200个历史版本')
  page.revision+=1;page.current_version+=1
 else:
  if TopicPage.objects.filter(owner=u).count()>=200:raise ValidationError('每人最多200个页面，含归档')
  if TopicPage.objects.filter(owner=u,code=d['code']).exists():raise ReviewConflict('本人页面编码已登记，请编辑原页面或使用另一编码')
  page=TopicPage(owner=u,topic_id=d['topic_id'],code=d['code'])
 page.save();v=TopicPageVersion.objects.create(page=page,number=page.current_version,payload=payload,payload_hash=digest(payload));response=dict(id=str(page.pk),revision=page.revision,version=v.number,code=page.code)
 TopicPageRequest.objects.create(request_id=request_id,owner=u,page=page,action=action,request_hash=h,response=response);AuditEvent.objects.create(action='topic_page.'+action,actor=u.username,object_type='TopicPage',object_id=str(page.pk),detail=dict(version=v.number,revision=page.revision,payload_hash=v.payload_hash,reason=reason,business_facts_changed=False))
 return {**response,'replayed':False}
@transaction.atomic
def archive(user,key,data):
 u=fresh(user);exact(data,('request_id','revision','archived','reason'),'归档请求')
 if type(data['archived']) is not bool:raise ValidationError('归档状态须明确为布尔值')
 reason=text(data['reason'],'归档依据',1000)
 if len(reason)<5:raise ValidationError('归档依据至少5字')
 request_id=request_key(data['request_id']);h=digest(dict(page=str(key),**{k:v for k,v in data.items() if k!='request_id'}));action='archive' if data['archived'] else 'restore';old=replay(u,request_id,h,action)
 if old:return old
 page=owned(u,key,True);info(u,page)
 if type(data['revision']) is not int or data['revision']!=page.revision:raise ReviewConflict('页面已更新，请重新读取')
 if page.archived==data['archived']:raise ValidationError('页面已处于该状态')
 page.archived=data['archived'];page.revision+=1;page.save();response=dict(id=str(page.pk),revision=page.revision,version=page.current_version,archived=page.archived)
 TopicPageRequest.objects.create(request_id=request_id,owner=u,page=page,action=action,request_hash=h,response=response);AuditEvent.objects.create(action='topic_page.'+action,actor=u.username,object_type='TopicPage',object_id=str(page.pk),detail=dict(**response,reason=reason,business_facts_changed=False));return {**response,'replayed':False}
def navigation(user,key,data):
 exact(data,('version','receipt','index','config'),'导航请求');u,d=checked_read(user,key,integer(data['version'],'页面版本'),data['receipt'])
 if not d['ready']:raise ReviewConflict('页面已归档或绑定定义变化，请核对后再使用')
 if type(data['index']) is not int or not 0<=data['index']<len(d['definition']['navigation']):raise ValidationError('导航序号无效')
 n=d['definition']['navigation'][data['index']];ctx=ws.context(u,n['topic_id'])
 if n['mode']=='new':config=dict(scope={},reference_scope=None,primary_label='当前范围',reference_label='对照范围')
 else:
  config=ws.config(data['config']);fields=set(config['scope'])|set(config['reference_scope'] or {})
  for c in ctx['cards']:
   if not c['available']:raise PermissionDenied('目标专题有不可访问卡片，无法完整继承条件')
   if any(not c['contract']['date' if f in ('from','to') else f] for f in fields):raise ReviewConflict('目标专题有卡片不支持本次范围，请选择开始新范围的导航')
   if config.get('links') and any(s['kind'] not in c['link_contract'] for s in config['links']['selections']):raise ReviewConflict('目标专题有卡片不支持身份联动，请选择开始新范围的导航')
  if fields&{'from','to'}:
   source=ws.context(u,d['topic_id']);clocks=lambda v:{c['contract']['date_label'] for c in v['cards'] if c['available']}
   if clocks(source)!=clocks(ctx):raise ReviewConflict('两个专题的日期角色不同，请开始新范围并重新选择日期')
 return dict(topic_id=n['topic_id'],context_token=ctx['context_token'],config=config,mode=n['mode'],notice='继承全部当前/对照范围及身份条件；原指标定义仍由目标专题决定。' if n['mode']=='inherit' else '明确开始目标专题的新范围：日期、对照和身份条件重置。')
