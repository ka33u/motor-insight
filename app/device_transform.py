"""Private, versioned CSV field transforms with source facts held immutable."""
import csv,hashlib,io,json,re,uuid
from datetime import datetime
from decimal import Decimal,InvalidOperation,localcontext
from pathlib import Path
from django.core.exceptions import ValidationError,PermissionDenied,ObjectDoesNotExist
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import transaction
from django.utils import timezone
from . import access,device_files as files,device_intake as intake
from .models import DeviceFile,DeviceTransformTemplate as Template,DeviceTransformVersion as Version,DeviceTransformReceipt as Receipt,AuditEvent
from .import_review import ReviewConflict
REVISION='device-csv-transform-20261006-v1'
NAMESPACE=uuid.UUID('4c73b1f9-02d1-40e2-8abc-028a28fccce0')
ENCODINGS=('utf-8-sig','gb18030');DELIMITERS=(',',';','\t');DATES=('iso','%Y/%m/%d %H:%M:%S','%Y-%m-%d %H:%M:%S')
CONVERSIONS={'mΩ→Ω':('mΩ','Ω','0.001'),'kΩ→Ω':('kΩ','Ω','1000'),'mA→A':('mA','A','0.001'),'mV→V':('mV','V','0.001'),'kV→V':('kV','V','1000'),'kW→W':('kW','W','1000'),'N·cm→N·m':('N·cm','N·m','0.01'),'ms→s':('ms','s','0.001'),'rpm→r/min':('rpm','r/min','1')}
NO_CONSTANT={'session_id','unit_id','measurement_id','raw_value','raw_unit','value','result'}
NOTICE='字段转换保留私有原件和原始读数，仅生成另存的标准CSV。内容与已导入记录一致不证明原件真实性、检测完整或合格；不建立关联、不新增检测、不修改订单或放行。'
def digest(v):return intake.digest(v)
def require(user):return intake.require(user)
def strict(body,keys):
 if not isinstance(body,dict) or set(body)!=set(keys):raise ValidationError('字段转换参数不完整或包含未知字段')
def text(value,label,limit):
 if not isinstance(value,str) or not value.strip() or len(value)>limit or any(ord(c)<32 for c in value):raise ValidationError(label+'无效')
 return value.strip()
def rules_hash():return digest([REVISION,files.HEADERS,CONVERSIONS,[hashlib.sha256(p.read_bytes()).hexdigest() for p in (Path(__file__),Path(files.__file__))]])
def definition(value):
 strict(value,{'encoding','delimiter','headers','fields','result_map','tested_format','conversions'})
 if value['encoding'] not in ENCODINGS or value['delimiter'] not in DELIMITERS or value['tested_format'] not in DATES:raise ValidationError('文本编码、分隔符或检测时间格式不支持')
 headers=value['headers']
 if not isinstance(headers,list) or not 1<=len(headers)<=40 or any(not isinstance(h,str) or not h.strip() or len(h)>80 or any(ord(c)<32 for c in h) for h in headers) or len(set(headers))!=len(headers):raise ValidationError('源表头必须1至40列，完整且唯一')
 fields=value['fields']
 if not isinstance(fields,dict) or set(fields)!=set(files.HEADERS):raise ValidationError('必须明确标准CSV全部14个字段')
 for name,rule in fields.items():
  if not isinstance(rule,dict) or set(rule) not in ({'column'},{'constant'}):raise ValidationError('字段只能选择源列或显式固定声明，不接受表达式')
  if 'column' in rule and rule['column'] not in headers:raise ValidationError('字段映射引用的源列不存在')
  if 'constant' in rule:
   if name in NO_CONSTANT:raise ValidationError('身份、原始读数和判定字段必须来自源列')
   if text(rule['constant'],'固定字段声明',200)!=rule['constant']:raise ValidationError('固定字段声明不能包含首尾空白')
 results=value['result_map']
 if not isinstance(results,dict) or len(results)>30:raise ValidationError('判定码映射无效')
 for key,target in results.items():
  if text(key,'源判定码',40)!=key or target not in ('合格','不合格','不完整'):raise ValidationError('判定码只映射到明确的已支持结论')
 selected=value['conversions']
 if not isinstance(selected,list) or any(not isinstance(k,str) for k in selected) or len(set(selected))!=len(selected) or any(k not in CONVERSIONS for k in selected) or len({CONVERSIONS[k][0] for k in selected})!=len(selected):raise ValidationError('单位转换必须选用已定义且不重复的同量纲规则')
 return json.loads(json.dumps(value))
def inspect_rows(user,file_id,encoding,delimiter):
 user=require(user);f=files.get(user,file_id)
 if f.kind!='csv' or encoding not in ENCODINGS or delimiter not in DELIMITERS:raise ValidationError('当前字段转换仅支持CSV及明确的编码和分隔符')
 try:
  raw=files.contents(f);content=raw.decode(encoding)
  if '\x00' in content:raise ValidationError('源CSV含二进制空字符')
  reader=csv.reader(io.StringIO(content),delimiter=delimiter,strict=True);headers=next(reader,None)
  if not headers or len(headers)>40 or len(set(headers))!=len(headers) or any(not h.strip() or len(h)>80 or any(ord(c)<32 for c in h) for h in headers):raise ValidationError('源CSV表头缺失、重复或无效')
  rows=[]
  for line,values in enumerate(reader,2):
   if line>2001:raise ValidationError('源CSV最多2000数据行，请拆分设备导出批次')
   if not values:continue
   if len(values)!=len(headers) or any(len(v)>200 for v in values):raise ValidationError('源CSV列数或单元格长度异常，第'+str(line)+'行')
   rows.append(dict(line=line,values=dict(zip(headers,values))))
  if not rows:raise ValidationError('源CSV没有数据行')
 except (UnicodeDecodeError,csv.Error):raise ValidationError('指定编码或分隔符无法读取源CSV，请保留原件并核对格式')
 return user,f,headers,rows
def inspection(user,body):
 strict(body,{'file_id','encoding','delimiter'});user,f,headers,rows=inspect_rows(user,body['file_id'],body['encoding'],body['delimiter'])
 return dict(file=public_file(f),metadata_hash=f.metadata_hash,headers=headers,rows=len(rows),sample=rows[:10],sample_limit=10,encoding=body['encoding'],delimiter=body['delimiter'],standard_fields=files.HEADERS,encodings=ENCODINGS,delimiters=DELIMITERS,tested_formats=DATES,conversions=CONVERSIONS,no_constant_fields=sorted(NO_CONSTANT),notice=NOTICE)
def public_file(f):
 value=files.info(f);value['created_at']=f.created_at.isoformat();return value
def finite(value):
 try:
  n=Decimal(value)
  if not n.is_finite() or n.copy_abs()>Decimal('1e30'):raise ValueError()
  return n
 except (InvalidOperation,ValueError):raise ValidationError('测量值必须是有限数值且绝对值不超过1e30')
def preview(user,file_id,spec):
 spec=definition(spec);user,f,headers,source_rows=inspect_rows(user,file_id,spec['encoding'],spec['delimiter'])
 if headers!=spec['headers']:raise ReviewConflict('源CSV表头或顺序与已核对模板不同')
 converted=[];lineage=[];errors=[];conversion_map={CONVERSIONS[k][0]:CONVERSIONS[k][1:] for k in spec['conversions']}
 for src in source_rows:
  row={name:(src['values'][rule['column']] if 'column' in rule else rule['constant']).strip() for name,rule in spec['fields'].items()};changes=[]
  try:
   if any(not v for v in row.values()):raise ValidationError('标准字段存在空值')
   finite(row['raw_value']);number=finite(row['value']);before=dict(value=row['value'],unit=row['unit'])
   if row['unit'] in conversion_map:
    target,factor=conversion_map[row['unit']]
    if not number.is_zero() and number.as_tuple().exponent < -200:raise ValidationError('单位转换结果超出200字符的数值文本范围')
    with localcontext() as ctx:ctx.prec=80;number=number*Decimal(factor)
    if number.is_zero():converted_number='0'
    else:
     tup=number.as_tuple();size=tup.sign+(len(tup.digits)+tup.exponent if tup.exponent>=0 else max(1,len(tup.digits)+tup.exponent)+1-tup.exponent)
     if size>200:raise ValidationError('单位转换结果超出200字符的数值文本范围')
     converted_number=format(number,'f')
    row['value']=converted_number;row['unit']=target;finite(row['value']);changes.append(dict(kind='unit',before=before,after=dict(value=row['value'],unit=row['unit']),factor=factor))
   if spec['result_map']:
    before_result=row['result']
    if before_result not in spec['result_map']:raise ValidationError('源判定码未在模板中定义')
    row['result']=spec['result_map'][before_result];changes.append(dict(kind='result',before=before_result,after=row['result']))
   before_time=row['tested'];at=datetime.fromisoformat(before_time) if spec['tested_format']=='iso' else datetime.strptime(before_time,spec['tested_format'])
   if at.tzinfo is not None or at.microsecond:raise ValidationError('检测时间须为明确的本地业务秒级时间，不支持隐式时区换算')
   row['tested']=at.isoformat(timespec='seconds')
   if row['tested']!=before_time:changes.append(dict(kind='time',before=before_time,after=row['tested'],timezone='Asia/Shanghai'))
  except (ValidationError,ValueError,InvalidOperation) as ex:errors.append(dict(line=src['line'],message='；'.join(ex.messages) if isinstance(ex,ValidationError) else '日期或数值格式无法按定义转换'))
  converted.append(row);lineage.append(dict(source_line=src['line'],source_values=src['values'],output_values=row,changes=changes))
 stream=io.StringIO();writer=csv.DictWriter(stream,files.HEADERS);writer.writeheader();writer.writerows(converted);raw=stream.getvalue().encode('utf-8-sig');parsed=files.parse(raw,'csv');checks=[]
 if parsed['mode']!='structured':errors.extend(dict(line=None,message=e) for e in parsed['errors'] or ['转换结果无法解析为标准CSV'])
 for session in parsed['sessions']:
  try:
   target=files.target(session);comparison=files.compare(parsed,target);checks.append(dict(session_id=session,target=target,target_hash=digest(target),comparison=comparison,matches_current=comparison['ok']))
  except (ObjectDoesNotExist,ValidationError):checks.append(dict(session_id=session,target=None,target_hash=None,comparison=None,matches_current=False,message='当前检测会话或关联基础资料缺失'))
 can=not errors and bool(checks) and all(c['matches_current'] for c in checks)
 payload=dict(revision=REVISION,owner_id=user.pk,role=access.role(user),source_file=public_file(f),source_metadata_hash=f.metadata_hash,definition=spec,rules_hash=rules_hash(),rows=len(converted),checks=checks,errors=errors,lineage=lineage,output_sha256=hashlib.sha256(raw).hexdigest(),output_size=len(raw),can_transform=can,notice=NOTICE)
 # created_at is display metadata. The binding uses immutable file identity,
 # content and all current target values rather than presentation timestamps.
 binding={**payload,'source_file':{k:v for k,v in payload['source_file'].items() if k!='created_at'}}
 payload['token']=digest(binding);return payload,raw

def template_meta(t):return dict(id=str(t.pk),owner_id=t.owner_id,code=t.code,name=t.name,revision=t.revision,current_version=t.current_version)
def version_meta(v):return dict(template_id=str(v.template_id),number=v.number,state=v.state,request_id=str(v.request_id),request_hash=v.request_hash,payload_hash=v.payload_hash,activated_request_id=str(v.activated_request_id) if v.activated_request_id else None,activated_request_hash=v.activated_request_hash,activated_by=v.activated_by,reason=v.reason)
def checked_template(t):
 if digest(template_meta(t))!=t.metadata_hash:raise ReviewConflict('字段模板登记完整性核对失败')
 return t
def get_version(user,version_id,active=False):
 user=require(user);v=Version.objects.select_related('template').get(pk=version_id,template__owner=user);checked_template(v.template)
 if digest(v.payload)!=v.payload_hash or digest(version_meta(v))!=v.lifecycle_hash or v.state not in ('draft','active','retired'):raise ReviewConflict('字段模板版本完整性核对失败')
 if active and (v.state!='active' or v.template.current_version!=v.number or v.payload['rules_hash']!=rules_hash()):raise ReviewConflict('此模板不是当前可用版本，请重新核对启用版本与转换规则')
 return user,v
def info(t):
 checked_template(t);versions=[]
 for v in t.versions.order_by('-number'):
  get_version(t.owner,v.pk);versions.append(dict(id=v.pk,number=v.number,state=v.state,payload=v.payload,payload_hash=v.payload_hash,rules_current=v.payload['rules_hash']==rules_hash(),reason=v.reason,activated_by=v.activated_by))
 return dict(**template_meta(t),metadata_hash=t.metadata_hash,versions=versions)
@transaction.atomic
def draft(user,body):
 strict(body,{'code','name','file_id','definition','request_id','expected_revision'});user=require(user);rid=uuid.UUID(str(body['request_id']));request_hash=digest(body)
 existing=Version.objects.filter(request_id=rid).select_related('template').first()
 if existing:
  get_version(user,existing.pk)
  if existing.request_hash!=request_hash:raise ReviewConflict('字段模板申请号已用于不同内容')
  return info(existing.template)
 code=text(body['code'],'模板编码',80);name=text(body['name'],'模板名称',160)
 if not re.fullmatch('[A-Z][A-Z0-9._-]{2,79}',code):raise ValidationError('模板编码须为3至80位大写字母、数字、点、下划线或连字符')
 t=Template.objects.select_for_update().filter(owner=user,code=code).first()
 if t:
  checked_template(t)
  if type(body['expected_revision']) is not int or body['expected_revision']!=t.revision or name!=t.name:raise ReviewConflict('字段模板版本或名称变化，请重新读取')
 else:
  if body['expected_revision'] is not None:raise ReviewConflict('新模板的预期版本必须为空')
  if Template.objects.filter(owner=user).count()>=100:raise ValidationError('本地演示每账号最多100份模板')
  t=Template(owner=user,code=code,name=name)
 p,raw=preview(user,body['file_id'],body['definition']);payload=dict(definition=p['definition'],sample_file_id=body['file_id'],sample_sha256=p['source_file']['file_hash'],sample_metadata_hash=p['source_metadata_hash'],review_token=p['token'],review=p,rules_hash=p['rules_hash'],notice=NOTICE)
 number=(t.versions.order_by('-number').values_list('number',flat=True).first() or 0)+1 if not t._state.adding else 1
 t.revision+=1;t.metadata_hash=digest(template_meta(t));t.save()
 v=Version(template=t,number=number,request_id=rid,request_hash=request_hash,payload=payload,payload_hash=digest(payload));v.lifecycle_hash=digest(version_meta(v));v.save()
 AuditEvent.objects.create(action='device_transform.draft',actor=user.username,object_type='DeviceTransformTemplate',object_id=str(t.pk),detail=dict(version_id=v.pk,payload_hash=v.payload_hash,sample_file_id=body['file_id'],private_configuration=True,business_facts_changed=False,business_approval=False))
 return info(t)
@transaction.atomic
def activate(user,version_id,body):
 strict(body,{'request_id','expected_revision','reason'});user,v=get_version(user,version_id);rid=uuid.UUID(str(body['request_id']));request_hash=digest([version_id,body]);prior=Version.objects.filter(activated_request_id=rid).first()
 if prior:
  if prior.pk!=v.pk or prior.activated_request_hash!=request_hash:raise ReviewConflict('启用申请号已用于其他操作')
  return info(v.template)
 t=checked_template(Template.objects.select_for_update().get(pk=v.template_id,owner=user))
 if type(body['expected_revision']) is not int or body['expected_revision']!=t.revision or v.state!='draft':raise ReviewConflict('模板登记或版本状态变化，请重新读取')
 reason=text(body['reason'],'配置核对说明',1000)
 if len(reason)<5:raise ValidationError('配置核对说明至少5字')
 p,_=preview(user,v.payload['sample_file_id'],v.payload['definition'])
 if not p['can_transform'] or p['token']!=v.payload['review_token'] or v.payload['rules_hash']!=rules_hash():raise ReviewConflict('样例、当前业务依据或转换规则已变化，需重新核对并创建新版本')
 for old in t.versions.filter(state='active'):
  get_version(user,old.pk);old.state='retired';old.lifecycle_hash=digest(version_meta(old));old.save()
 v.state='active';v.activated_request_id=rid;v.activated_request_hash=request_hash;v.activated_by=user.username;v.reason=reason;v.lifecycle_hash=digest(version_meta(v));v.save();t.current_version=v.number;t.revision+=1;t.metadata_hash=digest(template_meta(t));t.save()
 AuditEvent.objects.create(action='device_transform.activate',actor=user.username,object_type='DeviceTransformTemplate',object_id=str(t.pk),detail=dict(version_id=v.pk,payload_hash=v.payload_hash,private_configuration=True,business_facts_changed=False,business_approval=False))
 return info(t)
def receipt_meta(r):return dict(id=str(r.pk),owner_id=r.owner_id,source_file_id=str(r.source_file_id),output_file_id=str(r.output_file_id),template_version_id=r.template_version_id,request_id=str(r.request_id),request_hash=r.request_hash,payload=r.payload)
def current_file(user,file_id,expected):
 try:
  f=files.get(user,file_id)
  if f.file_hash!=expected:raise ReviewConflict('内容摘要不一致')
  return dict(id=str(f.pk),filename=f.filename,sha256=f.file_hash,size=f.size,current_integrity='ok',href='#device-files?id='+str(f.pk))
 except (ObjectDoesNotExist,ValidationError,ValueError,OSError):return dict(id=str(file_id),current_integrity='failed',message='当前原件内容或元数据异常，历史转换依据保留')
def detail(user,receipt_id):
 user=require(user);r=Receipt.objects.get(pk=receipt_id,owner=user)
 if digest(receipt_meta(r))!=r.payload_hash:raise ReviewConflict('转换回执完整性核对失败')
 user,v=get_version(user,r.template_version_id);source=current_file(user,r.source_file_id,r.payload['preview']['source_file']['file_hash']);output=current_file(user,r.output_file_id,r.payload['preview']['output_sha256']);checks=[]
 for old in r.payload['preview']['checks']:
  try:current=files.target(old['session_id']);match=digest(current)==old['target_hash']
  except (ObjectDoesNotExist,ValidationError):match=False
  checks.append(dict(session_id=old['session_id'],current_target_unchanged=match))
 result=dict(id=str(r.pk),template=dict(id=str(v.template_id),code=v.template.code,number=v.number,state=v.state,payload_hash=v.payload_hash,rules_current=v.payload['rules_hash']==rules_hash()),payload=r.payload,payload_hash=r.payload_hash,source=source,output=output,current_targets=checks,notice=NOTICE);result['receipt']=digest([r.payload_hash,source,output,checks,user.pk,access.role(user)]);return result

def execute(user,body):
 strict(body,{'file_id','version_id','request_id','preview_token'});user=require(user);rid=uuid.UUID(str(body['request_id']));request_hash=digest(body);prior=Receipt.objects.filter(request_id=rid).first()
 if prior:
  if prior.owner_id!=user.pk or prior.request_hash!=request_hash:raise ReviewConflict('转换申请号已用于其他内容')
  return detail(user,prior.pk)
 user,v=get_version(user,body['version_id'],active=True);p,raw=preview(user,body['file_id'],v.payload['definition'])
 if p['token']!=body['preview_token'] or not p['can_transform']:raise ReviewConflict('文件、模板或当前业务核对依据变化，请重新预览')
 source=files.get(user,body['file_id']);out_hash=p['output_sha256'];archive_request=uuid.uuid5(NAMESPACE,f'{user.pk}:{source.pk}:{v.payload_hash}:{out_hash}');output=files.upload(user,SimpleUploadedFile('转换_'+str(source.pk)[:8]+'_'+out_hash[:16]+'.csv',raw),archive_request,'私有原件字段转换；源原件 '+str(source.pk)+'；模板 '+v.template.code+' v'+str(v.number)+'；不改变业务事实')
 with transaction.atomic():
  t=checked_template(Template.objects.select_for_update().get(pk=v.template_id,owner=user));get_version(user,v.pk,active=True)
  again,_=preview(user,source.pk,v.payload['definition'])
  if again['token']!=p['token']:raise ReviewConflict('归档后业务核对依据变化，请重新预览；原件归档保留')
  payload=dict(revision=REVISION,registered_at=timezone.now().isoformat(),actor=user.username,template_id=str(t.pk),template_code=t.code,version=v.number,version_payload_hash=v.payload_hash,preview=p,source_file_id=str(source.pk),output_file_id=str(output.pk),business_facts_changed=False,association_confirmed=False,notice=NOTICE)
  r=Receipt(owner=user,source_file=source,output_file=output,template_version=v,request_id=rid,request_hash=request_hash,payload=payload);r.payload_hash=digest(receipt_meta(r));r.save()
  AuditEvent.objects.create(action='device_transform.execute',actor=user.username,object_type='DeviceTransformReceipt',object_id=str(r.pk),detail=dict(payload_hash=r.payload_hash,source_file_id=str(source.pk),output_file_id=str(output.pk),version_id=v.pk,business_facts_changed=False,association_confirmed=False))
 return detail(user,r.pk)
def board(user):
 user=require(user);templates=[info(t) for t in Template.objects.filter(owner=user).order_by('code')];owned=Receipt.objects.filter(owner=user).order_by('-created_at');rows=[]
 for r in owned[:100]:
  if digest(receipt_meta(r))!=r.payload_hash:raise ReviewConflict('转换回执完整性核对失败')
  rows.append(dict(id=str(r.pk),source_file_id=str(r.source_file_id),output_file_id=str(r.output_file_id),created_at=r.payload['registered_at'],template_code=r.payload['template_code'],version=r.payload['version']))
 candidates=DeviceFile.objects.filter(owner=user,kind='csv').order_by('-created_at');return dict(owner_id=user.pk,templates=templates,receipts=rows,total_receipts=owned.count(),receipt_limit=100,files=[public_file(f) for f in candidates[:100]],total_csv_files=candidates.count(),files_limit=100,standard_fields=files.HEADERS,conversions=CONVERSIONS,encodings=ENCODINGS,delimiters=DELIMITERS,tested_formats=DATES,no_constant_fields=sorted(NO_CONSTANT),notice=NOTICE)
