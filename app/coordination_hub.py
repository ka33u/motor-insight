"""Read-only index of saved follow-ups and account-assigned tasks.

Counts are records, not distinct incidents. Free-text owners are never resolved
to accounts. Source boards remain responsible for changing their own records.
"""
import hashlib
import importlib
import json
from collections import Counter, defaultdict
from datetime import timedelta
from pathlib import Path
from urllib.parse import urlencode

from django.core.exceptions import ObjectDoesNotExist, ValidationError
from django.db.models import Q, OuterRef, Subquery
from django.utils import timezone

from . import access, action_tasks, analytics
from .models import IssueDisposition, ActionTask, ActionTaskEvent, Record, AuditEvent
from .schema import SCHEMAS
from .import_review import ReviewConflict

NOTICE = ('每行是一条已保存的专题跟进或账号协调任务，不代表一个去重业务问题；同一对象的不同记录不自动合并。'
          '期限按当前跟进日期判断，业务事实仍为固定模拟快照。专题状态仅表示登记的核查进度，账号任务关闭沿用独立复核流程。')
BUCKETS = {'all':'全部记录','overdue':'未办结且逾期','today':'今日到期','next7':'未来7天到期','later':'7天以后到期',
           'no_due':'未设期限','done':'已记录复查或关闭','unknown':'状态待核对'}
RELATIONS = {'all':'全部可访问','assigned':'账号分派给我','review':'账号任务待我复核','updated':'由我最近记录'}
TYPES = {'all':'两类记录','note':'专题跟进','task':'账号协调任务'}

# prefix: label, route, status module, terminal state, access class, source kinds
REGISTRY = {
 'overview-issue':('首页业务观察','issues','issue_workspace','已核验','business',{'':None}),
 'delivery':('订单交付','delivery','delivery','已核验','business',{'':'order_lines'}),
 'quality':('质量与试验','quality','quality','演练已核验','business',{'':'units'}),
 'supply':('库存与物料','supply','supply','演练已核验','business',{'material':'materials','purchase':'purchase_lines'}),
 'asset':('设备与工装','assets','asset','演练已核验','business',{'equipment':'equipment','maintenance':'maintenance','tool':'tools'}),
 'ar':('应收与对账','receivables','receivable','演练已核验','money',{'opening':'ar_opening','invoice':'invoices'}),
 'ap':('应付与付款','payables','payable','演练已核对','money',{'invoices':'ap_invoices','payments':'ap_payments','plans':'ap_payment_plans','receipts':'receipts'}),
 'workforce':('人员与技能','workforce','workforce','演练已核验','personnel',{'':'employees'}),
 'energy':('能源与安环','energy','energy','演练已核验','business',{'meter':None,'ehs':'ehs'}),
 'service':('售后与产品反馈','service','service','演练已核验','business',{'':'service'}),
 'engineering':('研发与工艺','engineering','engineering','演练已核对','business',{'products':'products','projects':'projects','changes':'engineering_changes'}),
 'sales':('销售与报价','sales','sales','演练已核对','business',{'':'quotes'}),
 'manufacturing':('工序与流转','manufacturing','manufacturing','演练已核对','business',{'work_orders':'work_orders','batches':'batches','operations':'operations'}),
 'material_planning':('备料与试配','material-planning','material_planning','演练已核查','business',{'orders':'work_orders','materials':'materials','impact':'order_lines'}),
 'process-quality':('工艺参数与首件','process-quality','process_quality','演练已核对','business',{'':'process_check_plans'}),
 'logistics':('发运与签收','logistics','logistics','演练已核对','business',{'':'shipments'}),
 'target':('经营目标与偏差','targets','target','演练已复查','analyst',{'':'kpi_targets'}),
 'assembly-plan':('计划版本与兑现','assembly-plans','assembly_plan','演练已复查','business',{'':'work_orders'}),
}

def digest(x):
    return hashlib.sha256(json.dumps(x,ensure_ascii=False,sort_keys=True,default=str,separators=(',',':')).encode()).hexdigest()

def route(page, values=None):
    return '#'+page+('?' + urlencode(values) if values else '')

def permitted(user, level):
    return (access.can_edit(user) if level=='analyst' else access.allowed(user,'attendance') if level=='personnel'
            else access.can_money(user) if level=='money' else bool(access.role(user)))

def resolve(key):
    prefix,sep,remaining=key.partition(':');spec=REGISTRY.get(prefix)
    if not sep or not remaining or spec is None:return None
    label,page,module,terminal,level,kinds=spec
    if prefix=='overview-issue':
        from .issue_workspace import note_key,KINDS
        saved=AuditEvent.objects.filter(action='issue_workspace.followup',object_type='OverviewIssue',object_id=key).order_by('-id').first()
        if not saved or not isinstance(saved.detail,dict):return None
        d=saved.detail;source=d.get('source');scope=d.get('scope');raw=d.get('issue_key');kind=d.get('kind')
        if not isinstance(raw,str) or note_key(raw)!=key or kind not in KINDS or not isinstance(source,dict) or not isinstance(scope,dict):return None
        ds=source.get('dataset');obj=source.get('key');family=scope.get('family','')
        if ds not in ('units','order_lines','tools') or not isinstance(obj,str) or not 1<=len(obj)<=255 or not isinstance(family,str) or len(family)>255:return None
        return dict(prefix=prefix,label=label,route=route(page,{'family':family,'kind':kind,'focus':raw}),module=module,terminal=terminal,level=level,kind=kind,object=obj,dataset=ds,anchor=obj,audit_type='OverviewIssue',audit_key=key)
    if '' in kinds:kind='';obj=remaining
    else:
        kind,sep,obj=remaining.partition(':')
        if not sep or not obj or kind not in kinds:return None
    ds=kinds[kind];anchor=obj;params={'q':obj}
    if prefix=='assembly-plan':
        day,sep,anchor=obj.partition('~')
        from datetime import date
        try:
            if not sep or not anchor or date.fromisoformat(day).isoformat()!=day:return None
        except ValueError:return None
        params={'from':day,'to':day,'q':anchor}
    elif prefix=='delivery':params={'line':obj}
    elif prefix=='supply':params={'tab':'purchase' if kind=='purchase' else 'stock','q':obj}
    elif prefix=='ar':params={'kind':kind,'q':obj}
    elif prefix=='energy':params={'tab':'ehs','q':obj} if kind=='ehs' else {'tab':'meters','meter':obj}
    elif prefix=='material_planning':params={'tab':kind,'stage':'all','focus':kind+':'+obj}
    elif kind:params={'tab':kind,'q':obj,'stage':'all'}
    return dict(prefix=prefix,label=label,route=route(page,params),module=module,terminal=terminal,level=level,
                kind=kind,object=obj,dataset=ds,anchor=anchor,audit_type={'delivery':'OrderLine','quality':'QualityUnit',
                'supply':'SupplyCoordination','asset':'AssetCoordination','ar':'ReceivableCoordination','ap':'PayableCoordination',
                'workforce':'WorkforceCoordination','energy':'EnergyCoordination','service':'ServiceCoordination',
                'engineering':'EngineeringCoordination','sales':'SalesCoordination','manufacturing':'ManufacturingCoordination',
                'material_planning':'MaterialPlanningCoordination','process-quality':'ProcessQualityCoordination',
                'logistics':'LogisticsCoordination','target':'TargetCoordination','assembly-plan':'AssemblyPlanCoordination'}[prefix],
                audit_key=obj if prefix in ['delivery','quality'] else key)

def params(p):
    allowed={'domain','owner','type','bucket','relation','q','page','receipt'}
    if set(p)-allowed:raise ValidationError('不支持的跟进汇总筛选')
    if hasattr(p,'getlist') and any(len(p.getlist(k))!=1 for k in p):raise ValidationError('筛选条件不可重复')
    f={k:p.get(k,'') for k in ['domain','owner','q']}
    f.update({k:p.get(k,'all') or 'all' for k in ['type','bucket','relation']})
    if any(not isinstance(v,str) or len(v)>200 for v in f.values()):raise ValidationError('筛选内容无效或过长')
    f={k:v.strip() for k,v in f.items()}
    if f['type'] not in TYPES or f['bucket'] not in BUCKETS or f['relation'] not in RELATIONS:raise ValidationError('筛选选项无效')
    if f['domain'] and f['domain'] not in {*REGISTRY,'action-tasks','unmapped'}:raise ValidationError('来源专题无效')
    return f

def page(p):
    value=p.get('page','1')
    if isinstance(value,bool) or str(value).strip()!=str(value) or not str(value).isdigit():raise ValidationError('页码无效')
    n=int(value)
    if not 1<=n<=100000:raise ValidationError('页码无效')
    return n

def summary(rows):
    c=Counter(r['bucket'] for r in rows)
    return {'total':len(rows),'open':sum(r['phase']=='open' for r in rows),
            'note_reviewed':sum(r['type']=='note' and r['phase']=='done' for r in rows),
            'task_closed':sum(r['type']=='task' and r['phase']=='done' for r in rows),
            **{key:c[key] for key in BUCKETS if key!='all'},
            'source_attention':sum(r['source_state'] in ['missing','unmapped'] for r in rows)}

class Hub:
    def __init__(self,user,today=None):
        self.user=user;self.today=today or timezone.localdate();self.rows=[];self.objects={};self.records={}
        for item in IssueDisposition.objects.order_by('pk'):
            spec=resolve(item.key)
            if spec is None:
                if access.role(user)!='admin':continue
                spec=dict(prefix='unmapped',label='来源待映射',object=item.key,dataset=None,anchor=None,route='',audit_type=None,audit_key=None)
                phase='unknown'
            else:
                if not permitted(user,spec['level']) or spec['dataset'] and not access.allowed(user,spec['dataset']):continue
                states=importlib.import_module('.'+spec['module']+'_views',__package__).STATUSES
                phase='unknown' if item.status not in states else 'done' if item.status==spec['terminal'] else 'open'
            r=dict(id='note:'+str(item.pk),key=item.key,type='note',type_label='专题跟进',domain=spec['prefix'],domain_label=spec['label'],
                   object_key=spec['object'],title=spec['label']+' · '+spec['object'],status=item.status,phase=phase,
                   owner=item.owner,owner_kind='岗位文字',assignee_id=None,reviewer_id=None,state=None,
                   due_date=item.due_date,version=item.version,updated_by=item.updated_by,updated_at=item.updated_at,
                   note=item.note,source_dataset=spec['dataset'],source_key=spec['anchor'],href=spec['route'],
                   _spec=spec,_model=item)
            if spec['prefix']=='material_planning':
                # Searching one work order would recalculate a different shared
                # inventory queue. Restore the saved scope and only focus its row.
                from .material_planning import filters as material_filters
                saved=AuditEvent.objects.filter(object_type=spec['audit_type'],object_id=item.key,action='material_planning.followup').order_by('-id').first()
                r['source_context']='返回完整队列的当前试配；原筛选未留存。'
                if saved and isinstance(saved.detail.get('filters'),dict):
                    try:
                        restored=material_filters(saved.detail['filters'])
                        restored['tab']=spec['kind'];restored['stage']='all';restored['focus']=spec['kind']+':'+spec['object']
                        r['href']=route('material-planning',restored)
                        r['source_context']='返回时恢复跟进记录中的备料队列、库存与批次日期策略；使用当前资料重新试算，不是历史结果快照。'
                    except (ValueError,TypeError,KeyError):r['source_context']='原备料筛选无法恢复，入口使用完整默认队列；请核对后再解释当前结果。'
            if spec['prefix']=='overview-issue':r['source_context']='恢复保存的产品族与问题类别并定位当前观察；业务资料已变化时观察可能不再出现，历史跟进仍保留。'
            self.rows.append(r)
        latest_actor=ActionTaskEvent.objects.filter(task_id=OuterRef('pk')).order_by('-sequence').values('actor__username')[:1]
        for t in ActionTask.objects.select_related('assignee','reviewer','creator').annotate(last_actor=Subquery(latest_actor)).order_by('pk'):
            if not action_tasks.allowed(user,t):continue
            self.rows.append(dict(id='task:'+str(t.pk),key=str(t.pk),type='task',type_label='账号协调任务',domain='action-tasks',domain_label='账号协调任务',
                 object_key=t.business_key,title=t.title,status=action_tasks.STATES.get(t.state,'未知状态'),
                 phase='unknown' if t.state not in action_tasks.STATES else 'done' if t.state=='closed' else 'open',
                 owner=t.assignee.username if t.assignee else '',owner_kind='账号',assignee_id=t.assignee_id,reviewer_id=t.reviewer_id,state=t.state,
                 due_date=t.due_date,version=t.version,updated_by=t.last_actor or t.creator.username,updated_at=t.updated_at,
                 note=t.description,source_dataset=t.dataset,source_key=t.business_key,href=route('action-tasks',{'id':str(t.pk)}),
                 _spec=None,_model=t))
        refs={(r['source_dataset'],r['source_key']) for r in self.rows if r['source_dataset'] and r['source_key']}
        # One exact composite predicate prevents cross-dataset ID matches.
        condition=Q(pk__in=[]);by_dataset=defaultdict(set)
        for ds,key in refs:by_dataset[ds].add(key)
        for ds,keys in by_dataset.items():condition|=Q(dataset=ds,business_key__in=keys)
        self.records={(r.dataset,r.business_key):r for r in Record.objects.filter(condition).select_related('source_row__batch')}
        for r in self.rows:
            record=self.records.get((r['source_dataset'],r['source_key']))
            r['source_state']='unmapped' if r['domain']=='unmapped' else 'derived' if not r['source_dataset'] else 'present' if record else 'missing'
            r['source_revision']=record.revision if record else None
            r['source_hash']=digest([record.record_hash,record.values,record.source_row_id,record.source_row.batch.file_hash,
                                      record.source_row.sheet,record.source_row.row_number]) if record else None
            r['source_label']=SCHEMAS.get(r['source_dataset'],{}).get('label','派生对象')
            r['source_href']=route('data',{'dataset':r['source_dataset'],'q':r['source_key']}) if r['source_dataset'] else ''
            due=r['due_date'];phase=r['phase'];days=(self.today-due).days if due else None
            r['bucket']='done' if phase=='done' else 'unknown' if phase=='unknown' else 'no_due' if due is None else 'overdue' if days>0 else 'today' if days==0 else 'next7' if days>=-7 else 'later'
            r['overdue_days']=days if r['bucket']=='overdue' else None
            r['assigned_to_me']=r['type']=='task' and r['assignee_id']==user.pk
            r['review_for_me']=r['type']=='task' and r['reviewer_id']==user.pk and r['state']=='review'
            r['updated_by_me']=r['updated_by']==user.username
            r['due_date']=due.isoformat() if due else None
            r['updated_at']=r['updated_at'].isoformat()
            self.objects[r['id']]=r
        ranks={key:i for i,key in enumerate(['overdue','today','next7','later','no_due','unknown','done'])}
        self.rows.sort(key=lambda r:(ranks[r['bucket']],r['due_date'] or '9999-12-31',r['updated_at'],r['id']))
        self.receipt=digest([self.today,analytics.AS_OF,user.pk,access.role(user),hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),[self.safe(r) for r in self.rows]])

    @staticmethod
    def safe(r):return {k:v for k,v in r.items() if not k.startswith('_')}

    def check(self,value):
        if value!=self.receipt:raise ReviewConflict('跟进、来源、权限或跟进日期已变化，请重新读取汇总')

    def get(self,key):
        if key not in self.objects:raise ObjectDoesNotExist()
        return self.objects[key]

    def selected(self,f):
        rows=self.rows
        for field in ['domain','owner','type','bucket']:
            value=f[field]
            if value and not (field in ['type','bucket'] and value=='all'):rows=[r for r in rows if r[field]==value]
        if f['relation']!='all':rows=[r for r in rows if r[{'assigned':'assigned_to_me','review':'review_for_me','updated':'updated_by_me'}[f['relation']]]]
        if f['q']:
            q=f['q'].casefold();rows=[r for r in rows if q in ' '.join(str(r[k]) for k in ['title','key','object_key','owner','note','status','domain_label']).casefold()]
        return rows

    def board(self,f,n):
        rows=self.selected(f);by_domain=defaultdict(list)
        for r in rows:by_domain[(r['domain'],r['domain_label'])].append(r)
        return {'filters':f,'rows':[self.safe(r) for r in rows[(n-1)*25:n*25]],'summary':summary(rows),'total':len(rows),'page':n,'size':25,
                'domains':[dict(id=k,label=v) for k,v in sorted({(r['domain'],r['domain_label']) for r in self.rows})],
                'owners':sorted({r['owner'] for r in self.rows if r['owner']}),
                'groups':[{'id':k[0],'label':k[1],**summary(v)} for k,v in sorted(by_domain.items())],
                'today':self.today,'business_as_of':analytics.AS_OF,'receipt':self.receipt,'notice':NOTICE,'buckets':BUCKETS,'types':TYPES,'relations':RELATIONS}

    def detail(self,key,n):
        r=self.get(key);spec=r['_spec'];record=self.records.get((r['source_dataset'],r['source_key']));source=None
        if record:
            sr=record.source_row
            source={'dataset':record.dataset,'key':record.business_key,'revision':record.revision,'fields':access.permitted_fields(self.user,record.dataset),
                    'values':access.sanitize(self.user,record.dataset,record.values),'file':sr.batch.filename,'sheet':sr.sheet,'row':sr.row_number,'batch':str(sr.batch_id)}
        if r['type']=='note' and spec.get('audit_type'):
            query=AuditEvent.objects.filter(object_type=spec['audit_type'],object_id=spec['audit_key'],action__endswith='.followup').order_by('-id')
            fields=['status','owner','note','due_date','version']
            history=[{'actor':x.actor,'at':x.created_at,'action':'更新专题跟进','before':{k:v for k,v in x.detail.get('before',{}).items() if k in fields},
                      'after':{k:v for k,v in x.detail.get('after',{}).items() if k in fields}} for x in query[(n-1)*20:n*20]]
            total=query.count()
        elif r['type']=='task':
            query=r['_model'].events.select_related('actor').order_by('-sequence');total=query.count()
            history=[{'actor':e.actor.username,'at':e.created_at,'action':action_tasks.ACTIONS.get(e.action,'登记任务'),
                      'before':{'状态':action_tasks.STATES.get(e.before.get('state'),'—')},
                      'after':{'状态':action_tasks.STATES.get(e.after.get('state'),'—'),'依据':e.note,'版本':e.sequence}} for e in query[(n-1)*20:n*20]]
        else:history=[];total=0
        related=[self.safe(x) for x in self.rows if x['id']!=key and r['source_dataset'] and (x['source_dataset'],x['source_key'])==(r['source_dataset'],r['source_key'])]
        return {'row':self.safe(r),'source':source,'history':history,'history_total':total,'page':n,'size':20,'related':related,
                'today':self.today,'business_as_of':analytics.AS_OF,'receipt':self.receipt,'can_download_original':access.can_import(self.user),
                'notice':'来源显示当前主体档案及Excel行，不能代替完整专题证据链或当时快照；详情和修改继续使用来源专题。岗位文字不等于账号分派。'}
