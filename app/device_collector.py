"""Two-sample local demo inbox collection with private, append-only receipts."""
import hashlib,json,os,stat,uuid
from collections import Counter
from contextlib import ExitStack,contextmanager
from datetime import datetime
from pathlib import Path,PurePosixPath,PureWindowsPath
from django.conf import settings
from django.core import signing
from django.core.exceptions import ValidationError,PermissionDenied
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import transaction
from django.utils import timezone
from . import access,device_intake as intake,device_files as files
from .models import Record,DeviceCollectionRun,DeviceCollectionEvent,DeviceFile,AuditEvent
from .import_review import ReviewConflict

REVISION='local-device-collection-20261006-v1'
SALT='motor.local.device.collector.v1';MAX_AGE=900;MAX_FILES=100;MAX_SELECTED=20
NAMESPACE=uuid.UUID('5f6bba58-c7f0-4c52-8a51-a67021b49896')
KINDS={'csv','txt','pdf','png','jpg','jpeg','xlsx'}
NOTICE='采集器只读取服务器配置的本地模拟收件目录，不读取Excel中的设备电脑路径。原件默认私有；采集或解析成功不建立订单关联，也不改变检测与放行。'
OUTCOMES={'archived':'已归档待核对','reused':'同内容原件已复用','archived_invalid':'已归档但解析待处理','reused_invalid':'复用原件解析待处理','source_changed':'文件或来源已变化，需重新观察','read_failed':'读取失败，可核对后重试','archive_failed':'归档失败，可核对后重试','pending':'尚无采集回执'}
def digest(obj):return intake.digest(obj)
def user_now(user):return intake.require(user)
def strict(body,keys):
 if not isinstance(body,dict) or set(body)!=set(keys):raise ValidationError('采集参数不完整或包含不支持的字段')
def stable_seconds():
 n=getattr(settings,'DEVICE_COLLECTION_STABLE_SECONDS',2)
 if type(n) is not int or not 1<=n<=60:raise ValidationError('本地采集稳定观察间隔配置无效')
 return n
def root():
 if not getattr(settings,'DEVICE_COLLECTION_ENABLED',False):raise PermissionDenied('本地模拟采集器尚未启用')
 p=Path(settings.DEVICE_COLLECTION_ROOT)
 if p.is_symlink():raise ValidationError('模拟收件根目录不能是符号链接')
 return p.resolve(strict=True)
def binding(user,source_id):
 user=user_now(user)
 if not isinstance(source_id,str) or not source_id or len(source_id)>100 or any(c not in 'ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-' for c in source_id):raise ValidationError('来源编码无效')
 if source_id not in getattr(settings,'DEVICE_COLLECTION_SOURCES',set()):raise PermissionDenied('此来源未配置本地模拟采集目录')
 r=Record.objects.select_related('source_row__batch').get(dataset='device_sources',business_key=source_id)
 if not r.values.get('active'):raise ValidationError('来源已停用')
 try:
  base=root();leaf=base/source_id
  if leaf.is_symlink():raise ValidationError('模拟来源目录不能是符号链接')
  identity=base.stat();local=leaf.stat()
 except OSError:raise ValidationError('本地模拟收件目录尚未准备好')
 if not leaf.is_dir():raise ValidationError('本地模拟来源必须是目录')
 context=dict(revision=REVISION,user_id=user.pk,role=access.role(user),source=intake.source(r),source_values=r.values,root=digest([str(base),identity.st_dev,identity.st_ino,local.st_dev,local.st_ino]),stable_seconds=stable_seconds())
 return user,base,leaf,r,digest(context)
def signature(s):return dict(device=s.st_dev,inode=s.st_ino,size=s.st_size,mtime_ns=s.st_mtime_ns,ctime_ns=s.st_ctime_ns)
def relative(path):
 if not isinstance(path,str) or not path or len(path)>700:raise ValidationError('文件相对路径无效')
 p=PurePosixPath(path);w=PureWindowsPath(path)
 if p.is_absolute() or w.root or w.drive or '..' in p.parts or '\\' in path:raise ValidationError('文件路径超出模拟来源目录')
 return p.parts
@contextmanager
def source_fd(base,source_id):
 flags=os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW
 with ExitStack() as stack:
  parent=os.open(base,flags);stack.callback(os.close,parent)
  leaf=os.open(source_id,flags,dir_fd=parent);stack.callback(os.close,leaf);yield leaf
def read(base,source_id,path):
 parts=relative(path)
 with source_fd(base,source_id) as start,ExitStack() as stack:
  parent=start
  for name in parts[:-1]:
   parent=os.open(name,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=parent);stack.callback(os.close,parent)
  fd=os.open(parts[-1],os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=parent);stack.callback(os.close,fd)
  before=os.fstat(fd)
  if not stat.S_ISREG(before.st_mode):raise ValidationError('不是普通文件')
  if before.st_size>files.MAX_BYTES:raise ValidationError('文件超过原件归档大小限制')
  data=bytearray()
  while len(data)<=files.MAX_BYTES:
   block=os.read(fd,min(65536,files.MAX_BYTES+1-len(data)))
   if not block:break
   data.extend(block)
  after=os.fstat(fd)
  if signature(before)!=signature(after) or len(data)!=before.st_size:raise ReviewConflict('读取期间文件变化，需重新观察')
  raw=bytes(data)
  return raw,dict(stat=signature(after),sha256=hashlib.sha256(raw).hexdigest())
def receipt_load(token):
 try:
  value=signing.loads(token,salt=SALT,max_age=MAX_AGE)
  if not isinstance(value,dict) or value.get('revision')!=REVISION or not isinstance(value.get('items'),list) or not isinstance(value.get('sampled_at'),str):raise ValueError()
  at=datetime.fromisoformat(value['sampled_at'])
  if at.tzinfo is None:raise ValueError()
  for item in value['items']:
   if not isinstance(item,dict) or not {'path','key','stat','sha256','eligible','kind','size'}<=set(item):raise ValueError()
   relative(item['path'])
  if len(value['items'])>MAX_FILES or len({i['key'] for i in value['items']})!=len(value['items']):raise ValueError()
  return value
 except (signing.BadSignature,ValueError,TypeError,KeyError):raise ReviewConflict('观察凭据失效，请重新观察')
def sampling(user,body):
 strict(body,{'source_id','prior_receipt'});user,base,leaf,r,context=binding(user,body['source_id']);at=timezone.now();prior=None
 if body['prior_receipt']:
  prior=receipt_load(body['prior_receipt'])
  if prior.get('context_hash')!=context:raise ReviewConflict('来源、目录或账号已变化，请重新观察')
  elapsed=(at-datetime.fromisoformat(prior['sampled_at'])).total_seconds()
  if elapsed<0:raise ReviewConflict('观察时间倒退，请重新观察')
 else:elapsed=0
 previous={x['path']:x for x in prior['items']} if prior else {};items=[];total=0
 with source_fd(base,r.business_key) as fd:
  for folder,dirs,names,parent in os.fwalk('.',dir_fd=fd,follow_symlinks=False):
   dirs.sort();names.sort()
   for name in list(dirs):
    if stat.S_ISLNK(os.stat(name,dir_fd=parent,follow_symlinks=False).st_mode):dirs.remove(name);names.append(name)
   if len(PurePosixPath(folder).parts)>5:raise ValidationError('模拟目录超过5层，请拆分来源；本次观察未完成')
   for name in names:
    if len(items)>=MAX_FILES:raise ValidationError('单次模拟目录观察最多100条，请拆分来源目录')
    path=(PurePosixPath(folder)/name).as_posix();kind=PurePosixPath(name).suffix.lstrip('.').lower();s=os.stat(name,dir_fd=parent,follow_symlinks=False)
    row=dict(path=path,filename=name,kind=kind,size=s.st_size,stat=signature(s),sha256=None,eligible=False,state='waiting',reason='需要两次内容与文件状态一致的观察')
    if stat.S_ISLNK(s.st_mode):row.update(state='blocked',reason='符号链接不采集')
    elif not stat.S_ISREG(s.st_mode):row.update(state='blocked',reason='非普通文件不采集')
    elif kind not in KINDS or name.startswith('.'):row.update(state='skipped',reason='临时或未支持格式不采集')
    elif s.st_size>files.MAX_BYTES:row.update(state='too_big',reason='超过8MB原件限制')
    elif not s.st_size:row.update(state='empty',reason='空文件暂不归档')
    elif total+s.st_size>40*1024*1024:row.update(state='budget',reason='本次已达到40MB读取额度，请拆分来源')
    else:
     try:
      raw,snap=read(base,r.business_key,path);total+=len(raw);row.update(stat=snap['stat'],sha256=snap['sha256']);old=previous.get(path)
      eligible=bool(old and old.get('sha256')==row['sha256'] and old['stat']==row['stat'] and elapsed>=stable_seconds() and at.timestamp()-row['stat']['mtime_ns']/1e9>=stable_seconds())
      if eligible:row.update(eligible=True,state='stable',reason='两次观察的内容、大小和文件状态一致')
     except (OSError,ValidationError,ValueError):row.update(state='read_failed',reason='文件读取失败或在读取期间变化，请核对后重新观察')
    row['key']=digest([r.business_key,path,row['sha256'],row['stat']]);items.append(row)
 items.sort(key=lambda x:x['path']);payload=dict(revision=REVISION,context_hash=context,source_id=r.business_key,sampled_at=at.isoformat(),items=items)
 return dict(**payload,receipt=signing.dumps(payload,salt=SALT,compress=True),source_provenance=intake.source(r),elapsed_seconds=round(elapsed,3),stable_seconds=stable_seconds(),read_bytes=total,summary=dict(Counter(x['state'] for x in items)),notice=NOTICE)
def run_meta(run):return dict(id=str(run.pk),owner_id=run.owner_id,request_id=str(run.request_id),request_hash=run.request_hash,source_id=run.source_id,context_hash=run.context_hash,manifest=run.manifest)
def get(user,run_id):
 user=user_now(user);run=DeviceCollectionRun.objects.get(pk=run_id,owner=user)
 if digest(run_meta(run))!=run.manifest_hash:raise ReviewConflict('采集清单完整性核对失败')
 return user,run
@transaction.atomic
def create(user,body):
 strict(body,{'source_id','request_id','receipt','keys'});user=user_now(user);rid=uuid.UUID(str(body['request_id']))
 if not isinstance(body['keys'],list) or not body['keys'] or len(body['keys'])>MAX_SELECTED or any(not isinstance(k,str) for k in body['keys']) or len(set(body['keys']))!=len(body['keys']):raise ValidationError('请选择1至20个不同稳定文件')
 request_hash=digest({**body,'keys':sorted(body['keys'])});existing=DeviceCollectionRun.objects.filter(request_id=rid).first()
 if existing:
  if existing.owner_id!=user.pk or existing.request_hash!=request_hash:raise ReviewConflict('申请号已经用于其他采集清单')
  return detail(user,existing.pk)
 payload=receipt_load(body['receipt'])
 user,base,leaf,source,context=binding(user,body['source_id'])
 if datetime.fromisoformat(payload['sampled_at'])>timezone.now():raise ReviewConflict('观察时间倒退，请重新观察')
 if payload.get('context_hash')!=context or payload.get('source_id')!=body['source_id']:raise ReviewConflict('来源或账号与观察凭据不同，请重新观察')
 selected=[r for r in payload['items'] if r['key'] in body['keys']]
 if len(selected)!=len(body['keys']) or not all(r['eligible'] for r in selected):raise ValidationError('采集清单只能选择已完成两次稳定观察的文件')
 for item in selected:
  try:raw,current=read(base,body['source_id'],item['path'])
  except (OSError,ValidationError,ValueError):raise ReviewConflict('建立清单前文件已不可读或变化，请重新观察')
  if current['stat']!=item['stat'] or current['sha256']!=item['sha256']:raise ReviewConflict('建立清单前文件已变化，请重新观察')
 manifest=dict(revision=REVISION,sampled_at=payload['sampled_at'],registered_at=timezone.now().isoformat(),source=intake.source(source),items=selected,local_simulation=True,notice=NOTICE)
 run=DeviceCollectionRun(owner=user,request_id=rid,request_hash=request_hash,source_id=body['source_id'],context_hash=context,manifest=manifest);run.manifest_hash=digest(run_meta(run));run.save()
 AuditEvent.objects.create(action='device_collection.create',actor=user.username,object_type='DeviceCollectionRun',object_id=str(run.pk),detail=dict(manifest_hash=run.manifest_hash,items=len(selected),source_id=run.source_id,local_simulation=True,business_facts_changed=False))
 return detail(user,run.pk)
def events(run):
 result={};history=[];items={i['key']:i for i in run.manifest['items']}
 for event in run.events.order_by('item_key','version'):
  if digest(event.payload)!=event.payload_hash or any(event.payload.get(k)!=v for k,v in dict(run_id=str(run.pk),item_key=event.item_key,version=event.version,request_id=str(event.request_id),request_hash=event.request_hash).items()):raise ReviewConflict('采集回执完整性核对失败')
  item=items.get(event.item_key);prior=result.get(event.item_key)
  if not item or event.version!=(prior.version+1 if prior else 1):raise ReviewConflict('采集回执对象或版本序列不完整')
  p=event.payload
  if p.get('state') not in OUTCOMES or p['state']=='pending' or any(p.get(k)!=v for k,v in dict(source_id=run.source_id,relative_path=item['path'],source_sha256=item['sha256'],source_size=item['size'],local_simulation=True,business_facts_changed=False).items()):raise ReviewConflict('采集回执与原稳定清单不同')
  success=p['state'] in ('archived','reused','archived_invalid','reused_invalid')
  if success!=bool(p.get('file_id')) or (prior and prior.payload['state'] in ('archived','reused','archived_invalid','reused_invalid')):raise ReviewConflict('采集回执归档状态不一致')
  result[event.item_key]=event;history.append(event)
 return result,history
def detail(user,run_id):
 user,run=get(user,run_id);latest,history=events(run);rows=[];checks={}
 for item in run.manifest['items']:
  e=latest.get(item['key']);p=e.payload if e else {};file_id=p.get('file_id');archive=None
  if file_id:
   if file_id not in checks:
    try:
     f=files.get(user,file_id);checks[file_id]=dict(id=str(f.pk),filename=f.filename,sha256=f.file_hash,size=f.size,parser=f.parsed['mode'],current_integrity='ok',href='#device-files?id='+str(f.pk))
    except (OSError,ValidationError,ValueError,DeviceFile.DoesNotExist):checks[file_id]=dict(id=file_id,current_integrity='failed',message='当前归档内容或元数据异常；历史采集回执保留')
   archive=checks[file_id]
   if archive.get('current_integrity')=='ok' and (archive['sha256']!=item['sha256'] or archive['size']!=item['size']):raise ReviewConflict('归档回执与稳定文件指纹不一致')
  state=p.get('state','pending');rows.append(dict(item=item,state=state,state_label=OUTCOMES[state],version=e.version if e else 0,latest=p or None,archive=archive))
 receipt=digest([REVISION,run.manifest_hash,[e.payload_hash for e in history],checks,user.pk,access.role(user)])
 return dict(id=str(run.pk),source_id=run.source_id,manifest=run.manifest,manifest_hash=run.manifest_hash,receipt=receipt,rows=rows,summary=dict(Counter(r['state'] for r in rows)),history=[e.payload for e in history],notice=NOTICE)
def collect(user,run_id,body):
 strict(body,{'request_id','versions'});user,run=get(user,run_id);rid=uuid.UUID(str(body['request_id']));versions=body['versions']
 if not isinstance(versions,dict) or not 1<=len(versions)<=MAX_SELECTED or any(type(v) is not int or v<0 for v in versions.values()):raise ValidationError('采集对象与回执版本无效')
 items={i['key']:i for i in run.manifest['items']}
 if set(versions)-set(items):raise ValidationError('采集对象不在原稳定清单')
 request_hash=digest([str(run.pk),str(rid),versions]);existing=list(run.events.filter(request_id=rid))
 if any(e.request_hash!=request_hash for e in existing):raise ReviewConflict('重试申请号已用于其他内容')
 for key,expected in sorted(versions.items()):
  # A retry of the same request can finish remaining items after interruption.
  prior=run.events.filter(item_key=key,request_id=rid).first()
  if prior:
   events(run);continue
  latest,history=events(run);last=latest.get(key)
  if (last.version if last else 0)!=expected:raise ReviewConflict('采集回执版本已变化，请重新读取')
  if last and last.payload['state'] in ('archived','reused','archived_invalid','reused_invalid'):raise ValidationError('此文件已有成功归档回执，请核对原件或重新建立观察')
  item=items[key];state='archive_failed';reason='';archive=None
  try:
   try:user,base,leaf,source,context=binding(user,run.source_id)
   except ValidationError:raise ReviewConflict('来源或本地目录已变化')
   if context!=run.context_hash:raise ReviewConflict('来源或本地目录已变化')
   raw,current=read(base,run.source_id,item['path'])
   if current['stat']!=item['stat'] or current['sha256']!=item['sha256']:raise ReviewConflict('文件内容或状态已变化')
  except PermissionDenied:raise
  except (ReviewConflict,Record.DoesNotExist):state='source_changed';reason='来源或文件变化，原稳定清单不再适用，请重新观察'
  except (OSError,ValidationError):state='read_failed';reason='当前无法读取原稳定文件，请核对目录及文件后重试'
  else:
   try:
    same=DeviceFile.objects.filter(owner=user,file_hash=current['sha256'],size=len(raw),kind=item['kind']).order_by('created_at').first()
    if same:archive=files.get(user,same.pk);state='reused'
    else:
     archive_request=uuid.uuid5(NAMESPACE,f'{user.pk}:{current["sha256"]}:{item["kind"]}')
     archive=files.upload(user,SimpleUploadedFile('采集_'+current['sha256'][:16]+'.'+item['kind'],raw),archive_request,'本地模拟设备资料采集，SHA256：'+current['sha256']);state='archived'
    if archive.parsed['mode']=='invalid':state+='_invalid'
   except (OSError,ValidationError,ValueError):state='archive_failed';reason='私有归档失败，请核对格式、容量或现有存档完整性'
  payload=dict(run_id=str(run.pk),item_key=key,version=expected+1,request_id=str(rid),request_hash=request_hash,state=state,reason=reason,actor=user.username,finished_at=timezone.now().isoformat(),source_id=run.source_id,relative_path=item['path'],source_sha256=item['sha256'],source_size=item['size'],file_id=str(archive.pk) if archive else None,parser=archive.parsed['mode'] if archive else None,local_simulation=True,business_facts_changed=False)
  with transaction.atomic():
   current=DeviceCollectionRun.objects.select_for_update().get(pk=run.pk,owner=user);recent=current.events.filter(item_key=key).order_by('-version').first()
   if (recent.version if recent else 0)!=expected:raise ReviewConflict('回执写入时版本变化，重新读取后核对存档')
   event=DeviceCollectionEvent.objects.create(run=current,item_key=key,version=expected+1,request_id=rid,request_hash=request_hash,payload=payload,payload_hash=digest(payload))
   AuditEvent.objects.create(action='device_collection.attempt',actor=user.username,object_type='DeviceCollectionRun',object_id=str(run.pk),detail=dict(event_id=event.pk,payload_hash=event.payload_hash,item_key=key,version=event.version,state=state,file_id=payload['file_id'],local_simulation=True,business_facts_changed=False))
 return detail(user,run.pk)
def board(user):
 user=user_now(user);sources=[]
 for r in Record.objects.filter(dataset='device_sources').select_related('source_row__batch').order_by('business_key'):
  configured=r.business_key in getattr(settings,'DEVICE_COLLECTION_SOURCES',set())
  sources.append(dict(id=r.business_key,equipment_id=r.values.get('equipment_id'),host_label=r.values.get('host_label'),owner_id=r.values.get('owner_id'),active=r.values.get('active'),configured=configured,provenance=intake.source(r)))
 runs=[];owned=DeviceCollectionRun.objects.filter(owner=user).order_by('-created_at')
 for r in owned[:100]:
  if digest(run_meta(r))!=r.manifest_hash:raise ReviewConflict('采集清单完整性核对失败')
  runs.append(dict(id=str(r.pk),source_id=r.source_id,items=len(r.manifest['items']),created_at=r.manifest['registered_at'],manifest_hash=r.manifest_hash))
 return dict(owner_id=user.pk,sources=sources,runs=runs,total_runs=owned.count(),runs_limit=100,notice=NOTICE,enabled=bool(getattr(settings,'DEVICE_COLLECTION_ENABLED',False)),stable_seconds=stable_seconds(),outcomes=OUTCOMES)
