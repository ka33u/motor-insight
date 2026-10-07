"""Scoped, pageable business observation queue; notes never alter source facts."""
import hashlib,json,uuid
from collections import Counter,defaultdict
from datetime import date
from pathlib import Path
from urllib.parse import urlencode
from django.core import signing
from django.core.exceptions import ObjectDoesNotExist,PermissionDenied
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from . import access,analytics,quality_board
from .file_sharing import fresh,account_receipt
from .models import Record,IssueDisposition,AuditEvent

STATUSES=['待处理','处理中','待源系统复核','已核验']
KINDS=['未检测','检测项目不全','终检不合格','合格待核验放行','合格已放行待发运','检测或放行证据待核对','逾期未交','工具校准到期','整改逾期']
SALT='motor.issue.workspace.v1';MAX_AGE=900
NOTICE='每行是一个已登记规则下的业务观察，不是已批准的故障或去重事件。跟进状态不改变检测、放行、发货或整改事实；不同问题可对应同一对象，不能相加为台数。业务截止固定为模拟快照，跟进期限按当前日期判断。'

class Stale(ValueError):pass
def digest(value):return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,default=str,separators=(',',':')).encode()).hexdigest()
def note_key(key):return 'overview-issue:'+hashlib.sha256(key.encode()).hexdigest()
def can_write(user):return access.role(user) in ['admin','analyst','quality','operations']
def route(page,**values):return '#'+page+'?'+urlencode(values)


def filters(p,extra=()):
    keys={'family','kind','status','severity','owner','q','focus'}
    if set(p)-keys-{'page','receipt'}-set(extra):raise ValueError('问题筛选含未知字段')
    if hasattr(p,'getlist') and any(len(p.getlist(k))!=1 for k in p):raise ValueError('问题筛选不能重复')
    f={k:p.get(k,'') for k in keys}
    if any(not isinstance(v,str) or len(v)>255 for v in f.values()):raise ValueError('问题筛选值无效或过长')
    f={k:v.strip() for k,v in f.items()}
    if f['kind'] and f['kind'] not in KINDS or f['status'] and f['status'] not in STATUSES or f['severity'] and f['severity'] not in ('高','待办'):raise ValueError('问题类别或状态无效')
    return f


def page(p):
    value=p.get('page','1')
    if isinstance(value,bool) or not str(value).isdigit() or not 1<=int(value)<=100000:raise ValueError('页码须为1—100000')
    return int(value)


def disposition(item,default_owner):
    if not item:return dict(status='待处理',owner=default_owner,note='',due_date=None,version=0,updated_by='',updated_at=None)
    return {k:getattr(item,k) for k in ('status','owner','note','due_date','version','updated_by','updated_at')}


class Workspace:
    def __init__(self,user,f):
        self.user=fresh(user);self.filters=f;self.today=timezone.localdate();self.rows=[]
        raw=analytics.overview();self.families=raw['families']
        if f['family'] and f['family'] not in self.families:raise ValueError('产品族不存在，请重新选择')
        raw=analytics.overview(f['family']);self.as_of=raw['as_of']
        def add(key,kind,obj,ds,owner,detail,refs,scope=None,severity='高'):
            scope=scope or ('所选产品族' if f['family'] else '全部产品族')
            if access.allowed(self.user,ds):self.rows.append(dict(key=key,note_key=note_key(key),kind=kind,object=obj,dataset=ds,default_owner=owner,detail=detail,refs=refs,scope=scope,severity=severity))
        self.quality=quality_board.current()
        for r in self.quality.rows:
            if f['family'] and r['family']!=f['family']:continue
            evidence=None
            def quality_refs():
                nonlocal evidence
                if evidence is None:evidence=[x for x in self.quality.detail(r['id'])['sources'] if access.allowed(self.user,x['dataset'])]
                return evidence
            labels={'untested':'未检测','incomplete':'检测项目不全','failed':'终检不合格','release':'合格待核验放行','attention':'检测或放行证据待核对'}
            for flag,kind in labels.items():
                if flag in r['flags']:
                    add('quality-observation:'+flag+':'+r['id'],kind,r['id'],'units','质量试验',
                        '工单 '+r['work_order_id']+' · 配置 '+r['product_id']+' · '+('；'.join(r['issues']) if flag=='attention' else self.quality_note(flag)),quality_refs(),severity='待办' if flag=='untested' else '高')
            if r['release_valid'] and not r['shipped']:
                add('quality-observation:shipping:'+r['id'],'合格已放行待发运',r['id'],'units','计划 / 物流','质量页核对当前放行有效；截至快照未见有效发货对应装箱记录',quality_refs(),severity='待办')
        for p in raw['late_plans']:
            add('delivery-plan:'+p['id'],'逾期未交',p['line'],'order_lines','计划 / 销售',f"计划 {p['id']} · 剩余 {p['remaining']} 台 · 逾期 {p['days']} 天",
                [{'dataset':'order_lines','key':p['line']},{'dataset':'delivery_plans','key':p['id']}])
        for i in raw['issues']:
            if i['kind']=='校准到期':add('tool-expiry:'+i['object'],'工具校准到期',i['object'],'tools','设备计量',i['detail'],[{'dataset':'tools','key':i['object']}],scope='全厂工具台账，不随产品族分摊')
        units={r['id'] for r in self.quality.rows if not f['family'] or r['family']==f['family']}
        for n in analytics.tables()['nonconformities']:
            if n['unit_id'] in units and n['found']<=self.as_of and not n['closed'] and n['due']<self.as_of[:10]:
                add('ncr:'+n['id'],'整改逾期',n['unit_id'],'units','质量 / 工艺',n['id']+' · '+n['description'],[{'dataset':'units','key':n['unit_id']},{'dataset':'nonconformities','key':n['id']}])
        notes={x.key:x for x in IssueDisposition.objects.filter(key__in=[r['note_key'] for r in self.rows])}
        refs=defaultdict(set)
        for r in self.rows:
            for ref in r['refs']:refs[ref['dataset']].add(ref['key'])
        condition=Q(pk__in=[])
        for ds,keys in refs.items():condition|=Q(dataset=ds,business_key__in=keys)
        self.records={(r.dataset,r.business_key):r for r in Record.objects.filter(condition).select_related('source_row__batch')}
        for r in self.rows:
            r['disposition']=disposition(notes.get(r['note_key']),r['default_owner'])
            due=r['disposition']['due_date'];r['followup_overdue']=bool(due and due<self.today and r['disposition']['status']!='已核验')
            r['source_missing']=any((ref['dataset'],ref['key']) not in self.records for ref in r['refs'])
            r['object_href']=route('quality',q=r['object'],family=f['family']) if r['dataset']=='units' else route('delivery',line=r['object'],family=f['family']) if r['dataset']=='order_lines' else route('assets',tab='tool',q=r['object'])
            r['task_href']=route('action-tasks',dataset=r['dataset'],key=r['object'],rule='DELIVERY' if r['dataset']=='order_lines' else 'ASSET' if r['dataset']=='tools' else 'QUALITY',title=r['kind']+' · '+r['object'],description=r['detail']) if access.role(self.user)!='viewer' else ''
        self.rows.sort(key=lambda r:(0 if r['severity']=='高' else 1,KINDS.index(r['kind']),r['object'],r['key']))
        self.index={r['key']:r for r in self.rows}
        state=digest([self.as_of,self.today,f,account_receipt(self.user),analytics.revision(),self.rows,
            [(k,obj.record_hash,obj.revision,obj.values,obj.source_row_id,obj.source_row.batch.file_hash,obj.source_row.batch.filename,obj.source_row.sheet,obj.source_row.row_number) for k,obj in sorted(self.records.items())],
            [(p.name,hashlib.sha256(p.read_bytes()).hexdigest()) for p in (Path(__file__),Path(quality_board.__file__))]])
        self.stamp=dict(user_id=self.user.pk,account=account_receipt(self.user),scope=f,state=state)
        self.receipt=signing.dumps(self.stamp,salt=SALT,compress=True)

    @staticmethod
    def quality_note(flag):
        return {'untested':'截至快照没有有效检测会话','incomplete':'最新有效检测的适用必检项目不完整','failed':'最新有效完整检测重算不合格','release':'最新检测合格，但质量页的批准放行依据尚未通过核对'}[flag]

    def check(self,receipt):
        try:payload=signing.loads(receipt,salt=SALT,max_age=MAX_AGE)
        except (signing.BadSignature,ValueError,TypeError) as ex:raise Stale('问题范围核对依据已失效，请刷新清单') from ex
        if payload!=self.stamp:raise Stale('范围、问题、跟进、来源或权限已变化，请刷新清单')

    def selected(self):
        f=self.filters;rows=self.rows
        for field in ('kind','severity'):
            if f[field]:rows=[r for r in rows if r[field]==f[field]]
        if f['status']:rows=[r for r in rows if r['disposition']['status']==f['status']]
        if f['owner']:rows=[r for r in rows if r['disposition']['owner']==f['owner']]
        if f['q']:
            q=f['q'].casefold();rows=[r for r in rows if q in ' '.join(str(r[k]) for k in ('key','kind','object','detail','default_owner')).casefold() or q in ' '.join(str(r['disposition'][k]) for k in ('owner','note','status')).casefold()]
        return rows

    def get(self,key):
        row=next((r for r in self.selected() if r['key']==key),None)
        if not row:raise ObjectDoesNotExist()
        return row

    def board(self,n):
        rows=self.selected();focus=self.filters['focus'];found=next((i for i,r in enumerate(rows) if r['key']==focus),None)
        if focus and found is not None and n==1:n=found//30+1
        return dict(filters=self.filters,rows=rows[(n-1)*30:n*30],total=len(rows),page=n,size=30,receipt=self.receipt,
            as_of=self.as_of,today=self.today,synthetic=True,notice=NOTICE,can_follow_up=can_write(self.user),
            summary=self.summary(rows),kind_counts={k:sum(r['kind']==k for r in self.rows) for k in KINDS},
            options=dict(families=self.families,kinds=KINDS,statuses=STATUSES,owners=sorted({r['disposition']['owner'] for r in self.rows if r['disposition']['owner']})),focus_found=found is not None if focus else None)

    @staticmethod
    def summary(rows):
        return dict(observations=len(rows),distinct_objects=len({(r['dataset'],r['object']) for r in rows}),
            high=sum(r['severity']=='高' for r in rows),pending=sum(r['disposition']['status']!='已核验' for r in rows),
            followup_overdue=sum(r['followup_overdue'] for r in rows),source_missing=sum(r['source_missing'] for r in rows))

    def detail(self,key,n=1):
        r=self.get(key);sources=[]
        for ref in r['refs']:
            obj=self.records.get((ref['dataset'],ref['key']))
            if obj:
                sr=obj.source_row;sources.append(dict(dataset=obj.dataset,key=obj.business_key,revision=obj.revision,values=access.sanitize(self.user,obj.dataset,obj.values),fields=access.permitted_fields(self.user,obj.dataset),file=sr.batch.filename,sheet=sr.sheet,row=sr.row_number,batch=str(sr.batch_id),file_hash=sr.batch.file_hash))
        events=AuditEvent.objects.filter(action='issue_workspace.followup',object_type='OverviewIssue',object_id=r['note_key']).order_by('-id')
        return dict(row=r,sources=sources,history=list(events[(n-1)*20:n*20].values('id','actor','created_at','detail')),history_total=events.count(),page=n,size=20,filters=self.filters,receipt=self.receipt,
            as_of=self.as_of,today=self.today,can_follow_up=can_write(self.user),can_download_original=access.can_import(self.user),notice=NOTICE)


@transaction.atomic
def follow(user,key,data):
    user=fresh(user)
    if not can_write(user):raise PermissionDenied('此岗位只能读取问题观察，不能登记跟进')
    if set(data)!={'scope','receipt','version','status','owner','note','due_date','request_id'}:raise ValueError('跟进参数不完整或有未知字段')
    if not isinstance(data['scope'],dict) or set(data['scope'])!={'family','kind','status','severity','owner','q','focus'}:raise ValueError('请提供本次完整问题范围')
    try:rid=str(uuid.UUID(data['request_id']))
    except (ValueError,TypeError,AttributeError) as ex:raise ValueError('操作编号无效') from ex
    if type(data['version']) is not int or data['version']<0 or data['status'] not in STATUSES:raise ValueError('版本或跟进状态无效')
    for field,limit in [('owner',150),('note',2000)]:
        if not isinstance(data[field],str) or not data[field].strip() or len(data[field].strip())>limit:raise ValueError('责任岗位和跟进依据不能为空或过长')
    if len(data['note'].strip())<5:raise ValueError('跟进依据至少5字')
    when=data['due_date']
    if when in ('',None):when=None
    elif not isinstance(when,str) or date.fromisoformat(when).isoformat()!=when:raise ValueError('期限须为YYYY-MM-DD或空')
    else:when=date.fromisoformat(when)
    payload_hash=digest([key,data,account_receipt(user)])
    previous=AuditEvent.objects.filter(action='issue_workspace.followup',actor=user.username,detail__request_id=rid).first()
    if previous:
        if previous.detail['payload_hash']!=payload_hash:raise Stale('同一操作编号已用于其他内容')
        return dict(saved=previous.detail['after'],repeated=True,notice='该请求已登记；返回当次结果，不重复更新。当前状态需刷新核对。')
    d=Workspace(user,filters(data['scope']));d.check(data['receipt']);r=d.get(key)
    item=IssueDisposition.objects.select_for_update().filter(key=r['note_key']).first();before=disposition(item,r['default_owner'])
    if before['version']!=data['version']:raise Stale('跟进版本已变化，请重新读取')
    changed=dict(status=data['status'],owner=data['owner'].strip(),note=data['note'].strip(),due_date=when,version=before['version']+1,updated_by=user.username,updated_at=timezone.now())
    if item:
        if IssueDisposition.objects.filter(pk=item.pk,version=data['version']).update(**changed)!=1:raise Stale('跟进版本已变化，请重新读取')
        item.refresh_from_db()
    else:item=IssueDisposition.objects.create(key=r['note_key'],**changed)
    after=disposition(item,r['default_owner'])
    AuditEvent.objects.create(action='issue_workspace.followup',actor=user.username,object_type='OverviewIssue',object_id=r['note_key'],
        detail=dict(request_id=rid,payload_hash=payload_hash,before=json.loads(json.dumps(before,default=str)),after=json.loads(json.dumps(after,default=str)),
            issue_key=key,kind=r['kind'],source={'dataset':r['dataset'],'key':r['object']},scope=d.filters,
            business_facts_changed=False,business_approval=False))
    return dict(saved=after,repeated=False,notice='已保存问题跟进；检测、放行、发货和整改事实未改变。')
