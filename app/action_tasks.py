"""Evidence-backed coordination tasks; never edits imported business facts."""
import hashlib,json,uuid
from datetime import date
from django.contrib.auth.models import User
from django.core.exceptions import PermissionDenied,ValidationError
from django.db import transaction
from django.db.models import F,Q
from django.utils import timezone
from . import access
from .schema import SCHEMAS
from .models import ActionTask,ActionTaskEvent,ActionTaskLock,AuditEvent,Record
from .import_review import ReviewConflict

STATES={'reported':'待确认','confirmed':'已确认待分派','assigned':'待接手','working':'处理中','review':'待复核','closed':'已关闭'}
ACTIONS={'confirm':'确认问题','assign':'分派任务','start':'接手处理','submit':'提交复核','return':'退回处理','close':'复核关闭','transfer':'转交责任','reviewer':'调整复核人','deadline':'调整期限','comment':'补充记录','reopen':'重新打开'}
RULES={'DATA_MISSING':'资料或记录缺失','DATA_CONFLICT':'数据冲突或关联错误','DELIVERY':'交付协调','QUALITY':'质量核查','MATERIAL':'材料保障','PROCESS':'工艺与生产','ASSET':'设备工装计量','PERSONNEL':'人员技能工时','FINANCE':'资金成本对账','SERVICE':'客户售后','OTHER':'其他业务核查'}
CLASSES={'business':'普通业务','money':'含金额或财务','personnel':'含人员作业资料','restricted':'同时含金额与人员资料'}
CLASS_NEEDS={'business':set(),'money':{'money'},'personnel':{'personnel'},'restricted':{'money','personnel'}}
NOTICE='协调任务按实际操作时间跟进，原业务数据仍为固定模拟快照。关闭须由独立复核人核对提交证据；不自动补检、放行、发货、核销或改变源数据状态。相同来源对象与问题类别只保留一项任务，复发时重开。'

def digest(value):return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,default=str,separators=(',',':')).encode()).hexdigest()
def text(value,label,low=5,high=2000):
    if not isinstance(value,str) or not low<=len(value.strip())<=high:raise ValidationError(f'{label}须为{low}—{high}字')
    return value.strip()
def required(dataset):return ({'money'} if dataset in access.FINANCIAL else set())|({'personnel'} if dataset in access.PERSONNEL else set())
def class_allowed(user,classification):
    needs=CLASS_NEEDS.get(classification)
    return bool(access.role(user)) and needs is not None and ('money' not in needs or access.can_money(user)) and ('personnel' not in needs or access.allowed(user,'attendance'))
def can_write(user):return access.role(user) in ['admin','analyst','quality','operations','finance']
def allowed(user,task):return access.allowed(user,task.dataset) and class_allowed(user,task.classification)
def authorize(user,task):
    if not allowed(user,task):raise PermissionDenied('没有此任务及证据的访问权限')
def classification_ok(user,dataset,classification):
    if dataset not in SCHEMAS or not access.allowed(user,dataset) or not class_allowed(user,classification):raise PermissionDenied('来源或资料级别未授权')
    if not required(dataset)<=CLASS_NEEDS[classification]:raise ValidationError('资料级别必须覆盖来源中的财务或人员权限')
def stamp(record):return digest({'id':record.pk,'revision':record.revision,'hash':record.record_hash,'values':record.values,'source':record.source_row_id})
def source(user,dataset,key,classification,lock=False):
    classification_ok(user,dataset,classification)
    query=Record.objects.select_for_update() if lock else Record.objects
    r=query.select_related('source_row__batch').get(dataset=dataset,business_key=key)
    fields=[f for f in access.permitted_fields(user,dataset) if 'money' in CLASS_NEEDS[classification] or 'cents' not in f['name']]
    names={f['name'] for f in fields};sr=r.source_row
    return {'dataset':dataset,'dataset_label':SCHEMAS[dataset]['label'],'key':key,'revision':r.revision,'receipt':stamp(r),
            'fields':[{'name':f['name'],'label':f['label']} for f in fields],'values':{k:v for k,v in r.values.items() if k in names},
            'file':sr.batch.filename,'sheet':sr.sheet,'row':sr.row_number,'batch':str(sr.batch_id),'file_hash':sr.batch.file_hash}

def candidates(user,classification):
    if not class_allowed(user,classification):raise PermissionDenied('资料级别未授权')
    return [{'id':u.pk,'username':u.username,'name':u.first_name or u.username,'role':access.ROLES.get(access.role(u))}
            for u in User.objects.filter(is_active=True).prefetch_related('groups').order_by('username') if can_write(u) and class_allowed(u,classification)]

def preview(user,dataset,key,classification):
    if not can_write(user):raise PermissionDenied('只读角色不能建立任务')
    s=source(user,dataset,text(key,'来源编号',1,255),classification)
    existing=ActionTask.objects.filter(dataset=dataset,business_key=key)
    return {'source':s,'existing':[brief(t,user) for t in existing if allowed(user,t)],'candidates':candidates(user,classification),'notice':NOTICE}

def state(task):
    return {'id':str(task.pk),'dataset':task.dataset,'business_key':task.business_key,'rule':task.rule,'classification':task.classification,
            'title':task.title,'description':task.description,'state':task.state,'creator_id':task.creator_id,'assignee_id':task.assignee_id,
            'reviewer_id':task.reviewer_id,'assignee_username':task.assignee.username if task.assignee else None,'reviewer_username':task.reviewer.username if task.reviewer else None,'due_date':task.due_date.isoformat() if task.due_date else None,'version':task.version,'cycle':task.cycle,
            'closed_at':task.closed_at.isoformat() if task.closed_at else None,'submission':task.submission}

def actions(user,t):
    if not can_write(user) or not allowed(user,t):return []
    manager=access.role(user)=='admin' or user.pk==t.creator_id;owner=user.pk==t.assignee_id;reviewer=user.pk==t.reviewer_id
    values=[]
    if manager and t.state=='reported':values+=['confirm']
    if manager and t.state=='confirmed':values+=['assign']
    if owner and t.state=='assigned':values+=['start']
    if owner and t.state=='working':values+=['submit']
    if reviewer and not owner and t.state=='review' and t.submission.get('submitted_by')!=user.pk:values+=['return','close']
    if manager and t.state in ['assigned','working']:values+=['transfer']
    if manager and t.state in ['assigned','working','review']:values+=['reviewer','deadline']
    if manager or owner or reviewer:
        values+=['comment']
        if t.state=='closed':values+=['reopen']
    return values

def brief(t,user):
    name=lambda person:None if person is None else {'id':person.pk,'username':person.username,'name':person.first_name or person.username,'active':bool(access.role(person))}
    out=state(t);out.pop('submission')
    return {**out,'dataset_label':SCHEMAS[t.dataset]['label'],'state_label':STATES[t.state],
            'creator':name(t.creator),'assignee':name(t.assignee),'reviewer':name(t.reviewer),
            'overdue':t.state!='closed' and t.due_date is not None and t.due_date<timezone.localdate(),
            'actions':actions(user,t),'updated_at':t.updated_at,'created_at':t.created_at}

def get(user,pk,lock=False):
    query=ActionTask.objects.select_for_update() if lock else ActionTask.objects
    t=query.select_related('creator','assignee','reviewer').get(pk=pk);authorize(user,t);return t

def detail(user,pk,page=1):
    if type(page) is not int or not 1<=page<=100000:raise ValidationError('历史页码无效')
    t=get(user,pk);history=t.events.filter(sequence__lte=t.version).select_related('actor').order_by('-sequence')
    try:current=source(user,t.dataset,t.business_key,t.classification)
    except Record.DoesNotExist:current=None
    return {'task':brief(t,user),'source_snapshot':t.source_snapshot,'current_source':current,
            'source_changed':current is None or current['receipt']!=t.source_snapshot['receipt'],
            'submission':t.submission,'candidates':candidates(user,t.classification) if can_write(user) else [],
            'history':[{'sequence':e.sequence,'action':e.action,'actor':e.actor.username,'note':e.note,'before':e.before,'after':e.after,'created_at':e.created_at} for e in history[(page-1)*30:page*30]],
            'history_total':history.count(),'history_page':page,'notice':NOTICE,'today':timezone.localdate()}

def board(user,params):
    if set(params)-{'state','bucket','dataset','q','page'}:raise ValidationError('任务筛选字段不可用')
    status=params.get('state','');bucket=params.get('bucket','all');ds=params.get('dataset','');q=params.get('q','').strip();page=int(params.get('page',1))
    if status and status not in STATES or bucket not in ['all','mine','review','overdue'] or ds and ds not in SCHEMAS or len(q)>100 or not 1<=page<=100000:raise ValidationError('任务筛选无效')
    visible_ds=[ds for ds in SCHEMAS if access.allowed(user,ds)];classes=[c for c in CLASSES if class_allowed(user,c)]
    rows=ActionTask.objects.filter(dataset__in=visible_ds,classification__in=classes).select_related('creator','assignee','reviewer')
    if ds:rows=rows.filter(dataset=ds)
    if q:rows=rows.filter(Q(title__icontains=q)|Q(business_key__icontains=q)|Q(description__icontains=q))
    if bucket=='mine':rows=rows.filter(assignee=user)
    if bucket=='review':rows=rows.filter(reviewer=user,state='review')
    if bucket=='overdue':rows=rows.exclude(state='closed').filter(due_date__lt=timezone.localdate())
    counts={s:rows.filter(state=s).count() for s in STATES}
    if status:rows=rows.filter(state=status)
    rows=rows.order_by('-updated_at','id')
    return {'rows':[brief(t,user) for t in rows[(page-1)*25:page*25]],'total':rows.count(),'page':page,'size':25,'counts':counts,
            'states':STATES,'rules':RULES,'classes':{c:CLASSES[c] for c in classes},'datasets':[{'id':ds,'label':SCHEMAS[ds]['label']} for ds in visible_ds],
            'can_create':can_write(user),'notice':NOTICE,'today':timezone.localdate()}

def actor_locked(actor):
    ActionTaskLock.objects.get_or_create(pk=1);ActionTaskLock.objects.filter(pk=1).update(revision=F('revision')+1)
    user=User.objects.get(pk=actor.pk)
    if not can_write(user):raise PermissionDenied('当前账号不能维护协调任务')
    return user

def request_key(value):
    try:return uuid.UUID(str(value))
    except (ValueError,TypeError,AttributeError):raise ValidationError('请提供有效的操作请求编号')

def replay(user,rid,payload):
    e=ActionTaskEvent.objects.filter(actor=user,request_id=rid).select_related('task').first()
    if not e:return None
    authorize(user,e.task)
    if e.payload_hash!=digest(payload):raise ReviewConflict('同一请求编号不能用于不同操作')
    return {'task':brief(e.task,user),'replayed':True,'notice':'原请求已执行，显示当前任务状态。'}

def event(user,t,action,rid,payload,note,before):
    after=state(t)
    ActionTaskEvent.objects.create(task=t,sequence=t.version,actor=user,request_id=rid,payload_hash=digest(payload),action=action,note=note,before=before,after=after)
    AuditEvent.objects.create(action='action_task.'+action,actor=user.username,object_type='ActionTask',object_id=str(t.pk),detail={'before':before,'after':after,'note':note,'business_facts_changed':False})
    return {'task':brief(t,user),'replayed':False,'notice':'协调任务已保存；来源业务事实未修改。'}

@transaction.atomic
def create(user,data):
    user=actor_locked(user)
    if set(data)!={'request_id','dataset','key','rule','classification','title','description','source_receipt'}:raise ValidationError('建立任务参数不完整')
    rid=request_key(data['request_id']);payload={'action':'create','data':data};old=replay(user,rid,payload)
    if old:return old
    if data['rule'] not in RULES:raise ValidationError('请选择问题类别')
    s=source(user,data['dataset'],text(data['key'],'来源编号',1,255),data['classification'],True)
    if s['receipt']!=data['source_receipt']:raise ReviewConflict('来源已变化，请重新预览再登记')
    if ActionTask.objects.filter(dataset=s['dataset'],business_key=s['key'],rule=data['rule']).exists():raise ReviewConflict('相同来源对象与问题类别已有任务，请查阅已有任务；复发可重开原任务')
    t=ActionTask.objects.create(dataset=s['dataset'],business_key=s['key'],rule=data['rule'],classification=data['classification'],title=text(data['title'],'标题',3,150),description=text(data['description'],'问题说明'),creator=user,source_snapshot=s)
    return event(user,t,'create',rid,payload,t.description,{})

def person(user_id,t):
    if type(user_id) is not int:raise ValidationError('请选择责任账号')
    u=User.objects.get(pk=user_id)
    if not can_write(u) or not allowed(u,t):raise ValidationError('所选账号未启用、只读或无此任务资料权限')
    return u

def due(value):
    try:d=date.fromisoformat(value)
    except (ValueError,TypeError):raise ValidationError('期限须为YYYY-MM-DD')
    if d.isoformat()!=value:raise ValidationError('期限须为YYYY-MM-DD')
    return d

def evidence(user,t,refs):
    if not isinstance(refs,list) or not 1<=len(refs)<=10:raise ValidationError('提交复核需1—10项已导入的业务证据')
    items=[];seen=set()
    for ref in refs:
        if not isinstance(ref,dict) or set(ref)!={'dataset','key'}:raise ValidationError('证据需包含业务表及编号')
        key=text(ref['key'],'证据编号',1,255);ds=text(ref['dataset'],'证据业务表',1,64)
        if (ds,key) in seen:raise ValidationError('证据不可重复')
        seen.add((ds,key));items.append(source(user,ds,key,t.classification,True))
    return items

@transaction.atomic
def transition(user,pk,data):
    user=actor_locked(user)
    if not isinstance(data,dict) or not {'request_id','version','action','note'}<=set(data):raise ValidationError('操作需包含版本、请求编号及依据')
    action=data['action'];extras={'assign':{'assignee','reviewer','due_date'},'transfer':{'assignee','due_date'},'reviewer':{'reviewer'},'deadline':{'due_date'},'submit':{'evidence'}}.get(action,set())
    if set(data)!={'request_id','version','action','note'}|extras:raise ValidationError('操作参数不完整或有多余字段')
    rid=request_key(data['request_id']);payload={'id':str(pk),'data':data};old=replay(user,rid,payload)
    if old:return old
    t=get(user,pk,True)
    if type(data['version']) is not int or data['version']!=t.version:raise ReviewConflict('任务已被更新，请重新读取后操作')
    if action not in actions(user,t):raise PermissionDenied('当前状态或身份不允许此操作')
    note=text(data['note'],'操作依据');before=state(t)
    if action=='confirm':t.state='confirmed'
    elif action=='assign':
        t.assignee=person(data['assignee'],t);t.reviewer=person(data['reviewer'],t);t.due_date=due(data['due_date'])
        if t.assignee_id==t.reviewer_id:raise ValidationError('责任人和复核人须为不同账号')
        t.state='assigned'
    elif action=='start':t.state='working'
    elif action=='submit':
        if t.reviewer_id is None or t.reviewer_id==user.pk:raise ValidationError('请先由创建人或管理员指定独立复核人')
        person(t.reviewer_id,t)
        t.submission={'submitted_by':user.pk,'submitted_username':user.username,'submitted_at':timezone.now().isoformat(),'conclusion':note,'origin':source(user,t.dataset,t.business_key,t.classification,True),'evidence':evidence(user,t,data['evidence'])};t.state='review'
    elif action=='return':t.state='working'
    elif action=='close':
        for e in [t.submission.get('origin'),*t.submission.get('evidence',[])]:
            if not e:raise ValidationError('缺少提交时的来源证据，请退回重新提交')
            fresh=source(user,e['dataset'],e['key'],t.classification,True)
            if fresh['receipt']!=e['receipt']:raise ReviewConflict('提交后的证据已经变化，请退回重新提交，不能用旧证据关闭')
        if not t.submission.get('evidence'):raise ValidationError('没有完整的提交证据，不能关闭')
        t.state='closed';t.closed_at=timezone.now()
    elif action=='transfer':
        target=person(data['assignee'],t)
        if target.pk in (t.assignee_id,t.reviewer_id):raise ValidationError('新责任人须不同于原责任人和复核人')
        t.assignee=target;t.due_date=due(data['due_date']);t.state='assigned';t.submission={}
    elif action=='reviewer':
        target=person(data['reviewer'],t)
        if target.pk in (t.assignee_id,t.reviewer_id,t.submission.get('submitted_by')):raise ValidationError('复核人须更换为独立于处理人的账号')
        t.reviewer=target
    elif action=='deadline':
        target=due(data['due_date'])
        if target==t.due_date:raise ValidationError('期限未变化')
        t.due_date=target
    elif action=='reopen':
        t.state='confirmed';t.assignee=None;t.reviewer=None;t.due_date=None;t.submission={};t.closed_at=None;t.cycle+=1
    t.version+=1;t.save()
    return event(user,t,action,rid,payload,note,before)
