"""Private immutable device originals with auditable session association, not quality release."""
import csv,io,json,hashlib,uuid,re
from pathlib import Path
from decimal import Decimal,InvalidOperation
from collections import Counter
from django.conf import settings
from django.db import transaction
from django.core.exceptions import ValidationError,PermissionDenied,ObjectDoesNotExist
from . import access,analytics
from .models import DeviceFile,DeviceFileReview,Record,AuditEvent
from .import_review import ReviewConflict
from .topic_workspace import digest,clean_text

HEADERS=['session_id','unit_id','work_order_id','product_id','equipment_id','tested','spec_version','measurement_id','spec_id','raw_value','raw_unit','value','unit','result']
MAX_BYTES=8*1024*1024
NOTICE='此归档与关联工作区仅归档人可操作；默认私有原件可另行向指定账号授予只读权限。文件归档、只读授权或关联确认不改变检测结论、质量放行和订单分配。标准CSV核对字段与当前导入事实；其他格式仅保留原件并记录人工关联依据，不声称已核验文件内容。'
def require(user):
    if access.role(user) not in ['admin','quality']:raise PermissionDenied('检测原件工作区仅对质量岗位及管理员开放')
def root():
    return Path(getattr(settings,'DEVICE_FILE_ROOT',settings.BASE_DIR/'data/device_files'))
def path(file):return root()/(str(file.pk)+'.bin')
def file_meta(f):return {k:getattr(f,k) for k in ['filename','kind','size','file_hash','note','parsed','owner_id','request_hash']}|{'request_id':str(f.request_id),'id':str(f.pk)}
def info(f):return {'id':str(f.pk),'filename':f.filename,'kind':f.kind,'size':f.size,'file_hash':f.file_hash,'note':f.note,'created_at':f.created_at,'parser':f.parsed['mode'],'parse_message':f.parsed['message']}
def contents(f):
    try:raw=path(f).read_bytes()
    except OSError:raise ReviewConflict('原件缺失，关联确认及下载暂停，请从备份核对')
    if len(raw)!=f.size or hashlib.sha256(raw).hexdigest()!=f.file_hash:raise ReviewConflict('原件摘要不一致，关联确认及下载暂停，请核对备份')
    return raw
def get(user,file_id,check_file=True):
    require(user);f=DeviceFile.objects.get(pk=file_id,owner=user)
    if digest(file_meta(f))!=f.metadata_hash:raise ReviewConflict('归档元数据完整性核验失败')
    if check_file:contents(f)
    return f

def parse(raw,kind):
    manual={'mode':'manual','message':'未进行结构化解析；关联仅依赖人工核对原件后填写的依据。','rows':[],'sessions':[],'errors':[]}
    if kind!='csv':return manual
    try:text=raw.decode('utf-8-sig');encoding='UTF-8'
    except UnicodeDecodeError:
        try:text=raw.decode('gb18030');encoding='GB18030'
        except UnicodeDecodeError:return {**manual,'message':'无法识别文本编码，按原件归档；不自动匹配。'}
    if '\x00' in text:raise ValidationError('CSV含二进制空字符，请检查文件格式')
    try:
        reader=csv.reader(io.StringIO(text),strict=True);headers=next(reader,None)
        if not headers or not {'session_id','unit_id','measurement_id'}&set(headers):return manual
        if len(headers)!=len(set(headers)) or set(headers)!=set(HEADERS):
            return {'mode':'invalid','message':'标准CSV表头缺列、重复或含未知列；请核对模板，原件保持不变。','rows':[],'sessions':[],'errors':['表头必须完整且唯一']}
        rows=[];errors=[]
        for line,values in enumerate(reader,2):
            if line>2001:raise ValidationError('标准CSV最多2000行，请按设备导出批次拆分归档')
            if not values:continue
            if len(rows)>=2000:raise ValidationError('标准CSV最多2000行，请按设备导出批次拆分归档')
            if len(values)!=len(headers):errors.append(f'第{line}行列数不正确');continue
            row={k:v.strip() for k,v in zip(headers,values)}
            if any(not v or len(v)>200 for v in row.values()):errors.append(f'第{line}行存在空字段或过长字段')
            row['line']=line;rows.append(row)
        sessions=sorted({r['session_id'] for r in rows if r['session_id']})
        if len(sessions)>50:raise ValidationError('单份CSV最多50个检测会话，请分批归档')
        if not rows:errors.append('没有检测结果行')
        return {'mode':'structured' if not errors else 'invalid','message':f'{encoding}标准CSV · {len(rows)}行 · {len(sessions)}个会话','rows':rows,'sessions':sessions,'errors':errors[:100]}
    except csv.Error:return {'mode':'invalid','message':'CSV结构损坏，原件保持不变；自动关联暂停。','rows':[],'sessions':[],'errors':['CSV解析失败']}

def upload(user,file,request_id,note):
    require(user);rid=uuid.UUID(str(request_id));note=clean_text(note,'文件来源与用途',1000)
    if len(note)<5:raise ValidationError('文件来源与用途至少5字')
    filename=re.split(r'[/\\]',file.name)[-1]
    if not filename or len(filename)>240 or any(ord(c)<32 for c in filename):raise ValidationError('文件名无效')
    kind=Path(filename).suffix.lower().lstrip('.')
    if kind not in ['csv','txt','pdf','png','jpg','jpeg','xlsx']:raise ValidationError('仅接收CSV、TXT、PDF、PNG、JPG、XLSX检测原件')
    raw=file.read(MAX_BYTES+1)
    if not raw or len(raw)>MAX_BYTES:raise ValidationError('文件应非空且不超过8MB')
    signatures={'pdf':b'%PDF-','png':b'\x89PNG\r\n\x1a\n','jpg':b'\xff\xd8\xff','jpeg':b'\xff\xd8\xff','xlsx':b'PK\x03\x04'}
    if kind in signatures and not raw.startswith(signatures[kind]):raise ValidationError('文件开头与扩展名不匹配，请保留真实设备导出格式')
    sha=hashlib.sha256(raw).hexdigest();request_hash=digest([filename,kind,sha,note]);existing=DeviceFile.objects.filter(request_id=rid).first()
    if existing:
        if existing.owner_id!=user.pk or existing.request_hash!=request_hash:raise ReviewConflict('该申请号已用于其他文件内容')
        return get(user,existing.pk)
    if DeviceFile.objects.filter(owner=user).count()>=500:raise ValidationError('本地演示每人最多500份原件，请先规划归档容量')
    parsed=parse(raw,kind);f=DeviceFile(owner=user,request_id=rid,request_hash=request_hash,filename=filename,kind=kind,size=len(raw),file_hash=sha,note=note,parsed=parsed)
    f.metadata_hash=digest(file_meta(f));root().mkdir(parents=True,exist_ok=True)
    with path(f).open('xb') as out:out.write(raw)
    try:
        with transaction.atomic():
            f.save();AuditEvent.objects.create(action='device_file.archive',actor=user.username,object_type='DeviceFile',object_id=str(f.pk),detail={'filename':filename,'sha256':sha,'size':len(raw),'parser':parsed['mode'],'business_facts_changed':False})
    except Exception:
        path(f).unlink(missing_ok=True);raise
    return f

def source(r):
    row=r.source_row;b=row.batch
    return {'dataset':r.dataset,'key':r.business_key,'revision':r.revision,'hash':r.record_hash,'values':{k:v for k,v in r.values.items() if 'cents' not in k},'filename':b.filename,'batch_id':str(b.pk),'file_hash':b.file_hash,'sheet':row.sheet,'row':row.row_number}
def record(ds,key):return Record.objects.select_related('source_row__batch').get(dataset=ds,business_key=key)
def query(ds,**kw):return list(Record.objects.filter(dataset=ds,**kw).select_related('source_row__batch').order_by('business_key'))

def target(session_id):
    sources={}
    def add(r):sources[digest([r.dataset,r.business_key])]=source(r);return r.values
    s=add(record('test_sessions',session_id));u=add(record('units',s['unit_id']));w=add(record('work_orders',u['work_order_id']));p=add(record('products',u['product_id']));e=add(record('equipment',s['equipment_id']))
    measurements=[add(r) for r in query('measurements',values__session_id=session_id)]
    if len(measurements)>300:raise ValidationError('单次会话项目超过300项，请检查会话粒度')
    for key in {m['spec_id'] for m in measurements}:add(record('test_specs',key))
    candidate_lines=set();shipment_lines=set();messages=[]
    for r in query('allocations',values__work_order_id=w['id']):
        a=r.values
        if a['effective']<=analytics.DAY and a['qty']>0:add(r);candidate_lines.add(a['order_line_id'])
    for r in query('shipment_units',values__unit_id=u['id']):
        ship=record('shipments',r.values['shipment_id'])
        if ship.values['shipped']<=analytics.AS_OF:add(r);sh=add(ship);shipment_lines.add(sh['order_line_id'])
    for key in candidate_lines|shipment_lines:
        line=add(record('order_lines',key));add(record('orders',line['order_id']))
        if line['product_id']!=u['product_id']:messages.append('订单配置与SN不一致，订单关联待核对')
    if len(shipment_lines)==1 and not messages:
        ownership='装箱发货记录明确关联';order_lines=sorted(shipment_lines)
        if candidate_lines and not shipment_lines<=candidate_lines:messages.append('发货订单不在当前工单分配中，请核对')
    elif not shipment_lines and len(candidate_lines)==1 and not messages:ownership='工单唯一订单分配（间接推定）';order_lines=sorted(candidate_lines)
    else:ownership='SN订单归属待核对';order_lines=[]
    if len(shipment_lines)>1:messages.append('同一SN出现在多个订单发货中，不自动归属')
    if len(candidate_lines)>1 and not shipment_lines:messages.append('共用工单仅展示候选订单，不能一一归属')
    if s.get('voided'):messages.append('该检测会话已作废，文件仅作为历史证据')
    if s['tested']>analytics.AS_OF:messages.append('检测时间晚于当前业务快照，文件关联不纳入当前质量结果')
    if not s.get('complete'):messages.append('该会话原始记录为项目不齐全，文件一致不表示检测完整或合格')
    if w['product_id']!=u['product_id']:raise ValidationError('工单与SN配置不一致')
    return {'session_id':s['id'],'unit_id':u['id'],'work_order_id':w['id'],'product_id':p['id'],'equipment_id':e['id'],'tested':s['tested'],'spec_version':s['spec_version'],'result':s['result'],'voided':s.get('voided',False),'complete':s.get('complete',False),'measurements':[{k:m[k] for k in ['id','spec_id','raw_value','raw_unit','value','unit','result','file_reference']} for m in measurements],'order_lines':order_lines,'candidate_order_lines':sorted(candidate_lines|shipment_lines),'ownership':ownership,'messages':messages,'sources':sources,'as_of':analytics.AS_OF}

def equal_number(a,b):
    try:x,y=Decimal(str(a)),Decimal(str(b));return x.is_finite() and y.is_finite() and x==y
    except InvalidOperation:return False
def compare(parsed,t):
    rows=[r for r in parsed['rows'] if r['session_id']==t['session_id']];expected={m['id']:m for m in t['measurements']};issues=[];results=[]
    if not rows:issues.append('文件中没有此检测会话，不能用标准CSV关联其他对象')
    ids=[r['measurement_id'] for r in rows]
    if len(ids)!=len(set(ids)):issues.append('文件中结果编号重复')
    missing=sorted(set(expected)-set(ids));extra=sorted(set(ids)-set(expected))
    if missing:issues.append('文件缺少当前会话项目：'+'、'.join(missing[:20]))
    if extra:issues.append('文件存在当前会话未定义项目：'+'、'.join(extra[:20]))
    for row in rows:
        m=expected.get(row['measurement_id']);diff=[]
        expected_values={k:t[k] for k in HEADERS[:7]}
        if m:expected_values.update({k:m[k] for k in ['spec_id','raw_value','raw_unit','value','unit','result']});expected_values['measurement_id']=m['id']
        for k,v in expected_values.items():
            if not (equal_number(row[k],v) if k in ['raw_value','value'] else row[k]==str(v)):diff.append({'field':k,'file':row[k],'current':v})
        if diff:issues.append(f"第{row['line']}行有{len(diff)}项不一致")
        results.append({'line':row['line'],'measurement_id':row['measurement_id'],'differences':diff,'file_values':{k:row[k] for k in HEADERS}})
    return {'ok':not issues,'issues':issues,'rows':results,'row_count':len(rows),'expected_count':len(expected)}

def reviews(f):
    rows=list(f.reviews.order_by('version'));latest={}
    for r in rows:
        if digest(r.payload)!=r.payload_hash or any(r.payload.get(k)!=v for k,v in {'file_id':str(f.pk),'session_id':r.session_id,'action':r.action,'version':r.version,'request_id':str(r.request_id)}.items()):raise ReviewConflict('文件关联审核完整性核验失败')
        latest[r.session_id]=r
    return rows,latest
def public_review(r):return {'id':r.pk,'version':r.version,'session_id':r.session_id,'action':r.action,'created_at':r.created_at,'payload_hash':r.payload_hash,'payload':r.payload}

@transaction.atomic
def preview(user,file_id,session_id):
    f=get(user,file_id);session_id=clean_text(session_id,'检测会话号',150);all_reviews,latest=reviews(f);last=latest.get(session_id);version=all_reviews[-1].version if all_reviews else 0
    try:t=target(session_id);errors=[]
    except (ObjectDoesNotExist,ValidationError) as ex:t=None;errors=['会话或关联基础记录缺失，请检查Excel来源' if isinstance(ex,ObjectDoesNotExist) else ';'.join(ex.messages)]
    comparison=compare(f.parsed,t) if f.parsed['mode']=='structured' and t else None
    if f.parsed['mode']=='invalid':errors+=f.parsed['errors']
    can_confirm=bool(t) and not errors and (comparison is None or comparison['ok'])
    snapshot_hash=digest(t) if t else None
    body={'file_id':str(f.pk),'file_hash':f.file_hash,'metadata_hash':f.metadata_hash,'version':version,'session_id':session_id,'mode':f.parsed['mode'],'target':t,'comparison':comparison,'errors':errors,'can_confirm':can_confirm,'can_revoke':bool(last and last.action=='confirm'),'prior':public_review(last) if last else None,'source_changed':bool(last and last.action=='confirm' and last.payload['target_hash']!=snapshot_hash)}
    body['token']=digest(body);return body

@transaction.atomic
def review(user,file_id,data):
    require(user)
    if set(data)!={'request_id','session_id','action','reason','unit_id','token'}:raise ValidationError('关联审核参数不完整')
    rid=uuid.UUID(str(data['request_id']));request_hash=digest([str(file_id),data]);existing=DeviceFileReview.objects.filter(request_id=rid).select_related('file').first()
    if existing:
        if existing.file.owner_id!=user.pk or existing.request_hash!=request_hash:raise ReviewConflict('审核申请号已用于其他内容')
        get(user,existing.file_id);reviews(existing.file);return existing
    f=get(user,file_id);DeviceFile.objects.select_for_update().get(pk=f.pk)
    if f.reviews.count()>=200:raise ValidationError('本地演示每份文件最多200次审核，请规划长期审计归档')
    reason=clean_text(data['reason'],'核对依据',1000)
    if len(reason)<5:raise ValidationError('核对依据至少5字')
    check=preview(user,file_id,data['session_id'])
    if check['token']!=data['token']:raise ReviewConflict('文件、来源或关联版本已变化，请重新核对')
    action=data['action']
    if action not in ['confirm','revoke']:raise ValidationError('关联操作无效')
    if action=='confirm':
        if not check['can_confirm']:raise ValidationError('文件核对尚未通过，不能确认关联')
        if data['unit_id']!=check['target']['unit_id']:raise ValidationError('请准确填写要关联的电机SN')
    elif not check['can_revoke']:raise ValidationError('此会话没有可撤销的有效关联')
    t=check['target'] if action=='confirm' else check['prior']['payload']['target']
    p={'file_id':str(f.pk),'file_hash':f.file_hash,'session_id':data['session_id'],'action':action,'version':check['version']+1,'request_id':str(rid),'actor':user.username,'reason':reason,'mode':check['mode'],'target':t,'target_hash':digest(t),'comparison':check['comparison'],'previous_review_id':check['prior']['id'] if check['prior'] else None}
    r=DeviceFileReview.objects.create(file=f,session_id=data['session_id'],action=action,version=p['version'],request_id=rid,request_hash=request_hash,payload=p,payload_hash=digest(p))
    AuditEvent.objects.create(action='device_file.'+action,actor=user.username,object_type='DeviceFile',object_id=str(f.pk),detail={'review_id':r.pk,'session_id':r.session_id,'version':r.version,'payload_hash':r.payload_hash,'business_facts_changed':False})
    return r

def listing(user,q='',unit_id=''):
    require(user);q=clean_text(q,'搜索',150) if q else '';rows=[]
    for f in DeviceFile.objects.filter(owner=user).order_by('-created_at')[:500]:
        all_reviews,latest=reviews(f);active=[r for r in latest.values() if r.action=='confirm']
        units=sorted({r.payload['target']['unit_id'] for r in active})
        if unit_id and unit_id not in units:continue
        if q and q.lower() not in (f.filename+' '+f.note+' '+' '.join(f.parsed['sessions'])+' '+' '.join(units)).lower():continue
        rows.append({**info(f),'active_sessions':len(active),'units':units,'version':all_reviews[-1].version if all_reviews else 0})
    return {'rows':rows,'notice':NOTICE}
@transaction.atomic
def detail(user,file_id):
    f=get(user,file_id);all_reviews,latest=reviews(f)
    candidates=sorted(set(f.parsed['sessions'])|set(latest));checks=[]
    for sid in candidates:
        p=preview(user,file_id,sid)
        checks.append({'session_id':sid,'unit_id':p['target']['unit_id'] if p['target'] else None,'can_confirm':p['can_confirm'],'active':p['can_revoke'],'source_changed':p['source_changed'],'errors':p['errors']+(p['comparison']['issues'] if p['comparison'] else [])})
    return {**info(f),'parsed':{k:v for k,v in f.parsed.items() if k!='rows'},'checks':checks,'history':[public_review(r) for r in reversed(all_reviews)],'notice':NOTICE}
