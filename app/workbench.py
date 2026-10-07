"""Per-account shortcuts resolved against current access, with no stored results."""
import re
import uuid
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied,ValidationError,ObjectDoesNotExist
from django.db import transaction
from .models import (PersonalWorkbench,WorkbenchEntry,AnalysisModel,Topic,TopicView,TopicPage,AnalysisModelCard,CodingRule,AuditEvent)
from . import access,spc_data,topic_workspace,topic_pages,model_cards
from .analysis_engine import validate_definition
from .views import visible
from .import_review import ReviewConflict
from .workbench_routes import ROUTES

KINDS={'module':'系统页面','model':'分析模型','topic':'分析专题','view':'个人视角','page':'个人专题页面','card':'个人口径卡','coding':'编码规则'}
LIMIT=100
NOTICE='收藏只保存本人导航、别名、分组与顺序。打开时重新核对访问和定义状态；结果、单位、范围和Excel来源由原页面提供。临时筛选不随入口保存，常用筛选请先另存个人专题视角。'


def fresh(user,lock=False):
    q=get_user_model().objects.select_for_update() if lock else get_user_model().objects
    u=q.get(pk=user.pk);spc_data.account(u);return u


def exact(data,fields):
    if not isinstance(data,dict) or set(data)!=set(fields):raise ValidationError('工作台请求字段不完整或包含未知字段')


def text(value,limit):
    if not isinstance(value,str) or len(value.strip())>limit or any(ord(c)<32 or ord(c)==127 for c in value):raise ValidationError('名称或分组格式无效、过长或含控制字符')
    return value.strip()


def target_key(kind,value):
    if kind not in KINDS or not isinstance(value,str):raise ValidationError('收藏类型或目标编号无效')
    if kind=='module':
        if value not in ROUTES:raise ValidationError('系统页面不在可选目录内')
    elif kind in ('page','card'):
        try:
            if str(uuid.UUID(value))!=value:raise ValueError()
        except (ValueError,AttributeError):raise ValidationError('目标编号须为规范UUID')
    elif not re.fullmatch('[1-9][0-9]{0,14}',value):raise ValidationError('目标编号须为正整数')
    return value


def module_allowed(user,key):
    role=access.role(user)
    if key in ('imports','audit','accounts'):return role=='admin'
    if key=='targets':return access.can_edit(user)
    if key in ('scenarios','receivables','payables'):return access.can_money(user)
    if key in ('workforce','crew-schedule','joint-schedule','order-baselines','launch-review'):return role in ('admin','analyst','operations')
    if key in ('device-files','device-intake','device-collection','device-transform'):return role in ('admin','quality')
    return bool(role)


def resolve(user,kind,target):
    """Only whitelisted internal routes. Never return inaccessible target labels."""
    target_key(kind,target);state='ready';note='打开当前定义与当前资料';version=None
    if kind=='module':
        if not module_allowed(user,target):raise PermissionDenied('目标当前不可用')
        label=ROUTES[target];route=target;params={}
    elif kind=='model':
        m=visible(user,AnalysisModel.objects.all()).get(pk=int(target));validate_definition(user,m.dataset,m.definition,allow_inactive=True)
        label=m.name;version=m.version;route='analysis';params={'model':target}
    elif kind=='topic':
        ctx=topic_workspace.context(user,int(target));label=ctx['topic']['name'];version=ctx['topic']['version'];route='topics';params={'id':target}
        if any(not c['available'] for c in ctx['cards']):state='review';note='部分卡片当前不可用，进入专题核对'
    elif kind=='view':
        v=TopicView.objects.get(pk=int(target),owner=user);ctx=topic_workspace.context(user,v.topic_id);info=topic_workspace.view_info(v,ctx)
        if v.archived:raise PermissionDenied('目标当前不可用')
        label=v.name;version=v.version;route='topics';params={'id':str(v.topic_id),'view':target}
        if info['stale'] or any(not c['available'] for c in ctx['cards']):state='review';note='视角定义或卡片待核对，原视角暂不能直接运行'
    elif kind=='page':
        p=TopicPage.objects.get(pk=target,owner=user)
        if p.archived:raise PermissionDenied('目标当前不可用')
        info=topic_pages.info(user,p);label=info['definition']['title'];version=info['version']
        if info['stale']:state='review';note='页面绑定待核对，打开定义页';route='topic-pages';params={'id':target}
        else:route='topics';params={'id':str(p.topic_id),'page':target}
    elif kind=='card':
        c=model_cards.get_card(user,target);info=model_cards.info(c,user)
        if c.archived:raise PermissionDenied('目标当前不可用')
        label=info['metadata']['name'];version=info['revision'];route='model-cards';params={'id':target}
        if info['definition_state']!='same' or info['review_due']:state='review';note='口径卡定义已变化或到了复查日'
    else:
        c=CodingRule.objects.get(pk=int(target));label=c.name;version=c.revision;route='coding';params={'id':target}
        if not c.enabled:state='review';note='规则已停用，打开版本与记录核对'
    return dict(kind=kind,target=target,label=label,state=state,note=note,version=version,route=route,params=params)


def safe_target(user,kind,target):
    try:return resolve(user,kind,target)
    except (ObjectDoesNotExist,PermissionDenied,ValidationError,ReviewConflict,KeyError,TypeError,ValueError):
        return dict(kind=kind,target=target,label='目标当前不可用',state='unavailable',note='目标已撤销、移除、归档或当前权限/定义不支持；可移除收藏后重新选择',version=None,route=None,params={})


def board(user):
    u=fresh(user);w=PersonalWorkbench.objects.filter(owner=u).first();rows=[]
    if w:
        entries=list(w.entries.order_by('position','id')[:LIMIT+1])
        if len(entries)>LIMIT:raise ValidationError('工作台超过100项，请先整理')
        for e in entries:
            r=safe_target(u,e.kind,e.target);rows.append(dict(**r,id=str(e.pk),alias=e.alias,section=e.section,position=e.position,is_home=e.pk==w.home_entry))
    return dict(revision=w.revision if w else 0,home_mode=w.home_mode if w else 'overview',home_entry=str(w.home_entry) if w and w.home_entry else None,rows=rows,
                kinds=KINDS,limit=LIMIT,notice=NOTICE,personal_only=True)


def catalog(user,data):
    u=fresh(user);exact(data,('kind','q','page'));kind=data['kind'];term=text(data['q'],120)
    if kind not in KINDS or type(data['page']) is not int or not 1<=data['page']<=1000:raise ValidationError('目录类型或页码无效')
    if kind=='module':keys=list(ROUTES)
    else:
        q={'model':AnalysisModel,'topic':Topic,'view':TopicView,'page':TopicPage,'card':AnalysisModelCard,'coding':CodingRule}[kind].objects.all()
        if kind in ('model','topic'):q=visible(u,q)
        if kind in ('view','page','card'):q=q.filter(owner=u,archived=False)
        if q.count()>2000:raise ValidationError('当前可见目录超过2000项，请先整理目录；未截断选择')
        keys=[str(k) for k in q.order_by('pk').values_list('pk',flat=True)]
    rows=[]
    for key in keys:
        r=safe_target(u,kind,key)
        if r['state']=='unavailable':continue
        if term and term.casefold() not in (r['label']+' '+key).casefold():continue
        rows.append(r)
    rows.sort(key=lambda r:(r['label'],r['target']));p=data['page'];return dict(rows=rows[(p-1)*25:p*25],total=len(rows),page=p,size=25,kind=kind)


@transaction.atomic
def change(user,data):
    u=fresh(user,True)
    if not isinstance(data,dict):raise ValidationError('工作台请求须为对象')
    action=data.get('action');fields={'add':('kind','target','alias','section'),'edit':('id','alias','section'),'remove':('id',),'order':('ids',),'home':('id',)}
    if action not in fields:raise ValidationError('工作台操作无效')
    exact(data,('action','revision',*fields[action]));w=PersonalWorkbench.objects.filter(owner=u).first()
    if type(data['revision']) is not int or data['revision']!=(w.revision if w else 0):raise ReviewConflict('工作台已变化，请刷新后再操作')
    if w is None:w=PersonalWorkbench.objects.create(owner=u)
    before=dict(home_mode=w.home_mode,home_entry=str(w.home_entry) if w.home_entry else None,rows=list(w.entries.order_by('position','id').values('id','kind','target','alias','section','position')))
    if action=='add':
        kind=data['kind'];target=target_key(kind,data['target']);resolve(u,kind,target)
        if w.entries.count()>=LIMIT:raise ValidationError('每人最多100项收藏')
        if w.entries.filter(kind=kind,target=target).exists():raise ReviewConflict('此目标已经收藏，请编辑原收藏')
        WorkbenchEntry.objects.create(workbench=w,kind=kind,target=target,alias=text(data['alias'],80),section=text(data['section'],40),position=w.entries.count())
    elif action=='order':
        values=data['ids'];ids=[str(e.pk) for e in w.entries.all()]
        if not isinstance(values,list) or any(not isinstance(v,str) for v in values) or len(values)!=len(ids) or len(set(values))!=len(values) or set(values)!=set(ids):raise ValidationError('排序须完整且不重复地包含本人全部收藏')
        for pos,key in enumerate(values):w.entries.filter(pk=key).update(position=pos)
    elif action=='home' and data['id'] in (None,'workbench'):
        w.home_entry=None;w.home_mode='workbench' if data['id']=='workbench' else 'overview'
    else:
        try:key=uuid.UUID(data['id'])
        except (ValueError,TypeError,AttributeError):raise ValidationError('收藏编号无效')
        e=w.entries.get(pk=key)
        if action=='edit':e.alias=text(data['alias'],80);e.section=text(data['section'],40);e.save()
        elif action=='remove':
            if w.home_entry==e.pk:w.home_entry=None;w.home_mode='overview'
            e.delete()
            for pos,other in enumerate(w.entries.order_by('position','id')):w.entries.filter(pk=other.pk).update(position=pos)
        else:
            r=resolve(u,e.kind,e.target)
            if r['state']!='ready':raise ValidationError('该目标需要核对，暂不能设为登录入口')
            w.home_entry=e.pk;w.home_mode='favorite'
    w.revision+=1;w.save()
    # Audit only the personal configuration, without source models or saved filters.
    before['rows']=[{**r,'id':str(r['id'])} for r in before['rows']]
    AuditEvent.objects.create(action='workbench.'+action,actor=u.username,object_type='PersonalWorkbench',object_id=str(u.pk),detail=dict(revision=w.revision,before=before,request=data,business_facts_changed=False))
    return board(u)


def open_entry(user,data):
    u=fresh(user);exact(data,('id','revision'));w=PersonalWorkbench.objects.get(owner=u)
    if type(data['revision']) is not int or w.revision!=data['revision']:raise ReviewConflict('工作台已变化，请刷新后打开')
    try:key=uuid.UUID(data['id'])
    except (ValueError,TypeError,AttributeError):raise ValidationError('收藏编号无效')
    e=w.entries.get(pk=key);r=safe_target(u,e.kind,e.target)
    if r['state']=='unavailable':raise ReviewConflict('目标当前不可用，请刷新工作台重新选择')
    return dict(**r,revision=w.revision,id=str(e.pk))


def start(user):
    u=fresh(user);w=PersonalWorkbench.objects.filter(owner=u).first()
    if not w or w.home_mode=='overview':return dict(route='overview',params={},configured=False,reason='')
    if w.home_mode=='workbench':return dict(route='workbench',params={},configured=True,reason='')
    e=w.entries.filter(pk=w.home_entry).first();r=safe_target(u,e.kind,e.target) if e else None
    if not r or r['state']!='ready':return dict(route='workbench',params={},configured=True,reason='登录入口当前不可用或需要核对，请在工作台调整')
    return dict(route=r['route'],params=r['params'],configured=True,reason='')
