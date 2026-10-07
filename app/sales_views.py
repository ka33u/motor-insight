import json
from collections import Counter
from datetime import date
from django.db import transaction
from django.utils import timezone
from . import sales as eng,access,analytics
from .views import api,reply,body,require
from .models import IssueDisposition,AuditEvent
from .delivery_views import follow_info
from .quality_views import csv_reply
from .trace_cases import capture_sources

STATUSES=['待客户反馈','待技术澄清','待关联核对','演练已核对']
def can_follow(user):return access.role(user) in ['admin','analyst','operations']
def response(request,data):
    r=reply(eng.safe(data,access.can_money(request.user)));r['Cache-Control']='no-store';return r
def context(request):
    f=eng.filters(request.GET);return eng.current(f),f

@api()
@transaction.atomic
def board(request):
    d,f=context(request);quotes=d.selected();rows=quotes if f['tab']=='quotes' else d.task_rows(quotes);selected=[r for r in rows if f['stage'] in r['flags']];page=max(1,int(request.GET.get('page',1)))
    status_counts=Counter(q['calculated_state'] for q in quotes);task_counts={}
    for task in d.task_rows(quotes):
        c=task_counts.setdefault(task['kind'],dict(kind=task['kind'],total=0,done=0,open=0,overdue=0,unknown=0));c['total']+=1;c['done']+=task['done'];c['open']+=task['open'];c['overdue']+=task['overdue'];c['unknown']+=bool(task['issues'])
    return response(request,{'filters':f,'summary':d.summary(quotes),'rows':selected[(page-1)*25:page*25],'total':len(selected),'page':page,'size':25,'stages':eng.STAGES[f['tab']],'facets':{k:sum(k in r['flags'] for r in rows) for k in eng.STAGES[f['tab']]},'status_counts':[{'status':k,'count':v} for k,v in status_counts.items()],'task_counts':list(task_counts.values()),'global_issues':d.global_issues,'as_of':d.cutoff,'note':eng.NOTE,'can_money':access.can_money(request.user),'options':{'families':sorted({r.get('family','') for r in d.data['products']}),'customers':[{'id':r['id'],'name':r['name']} for r in d.data['customers']],'owners':[{'id':k,'name':d.idx['employees'].get(k,{}).get('name','未匹配')} for k in sorted({r['owner_id'] for r in d.data['quote_details']}|{r['owner_id'] for r in d.data['quote_tasks']})],'statuses':eng.STATUS}})

@api()
@transaction.atomic
def detail(request,key):
    d,f=context(request);obj=d.detail(key)
    return response(request,{**obj,'filters':f,'as_of':d.cutoff,'note':eng.NOTE,'can_money':access.can_money(request.user),'can_follow_up':can_follow(request.user),'data_revision':list(analytics.revision()),'follow_up':follow_info(IssueDisposition.objects.filter(key=f'sales:{key}').first())})

@api()
@transaction.atomic
def evidence(request,key):
    d,_=context(request);obj=d.detail(key);rows=capture_sources({'sources':obj['sources']});page=max(1,int(request.GET.get('page',1)))
    return response(request,{'rows':rows[(page-1)*40:page*40],'total':len(rows),'page':page,'size':40,'can_download_original':access.can_import(request.user)})

@api(('POST',))
@transaction.atomic
def follow_up(request,key):
    require(can_follow(request.user));d,f=context(request);obj=d.detail(key);p=body(request)
    if set(p)!={'status','version','owner','note','due_date','data_revision'}:raise ValueError('跟进字段不完整或存在未知字段')
    if type(p['version']) is not int or p['version']<0 or p['status'] not in STATUSES:raise ValueError('跟进状态或版本无效')
    if p['status']=='演练已核对':require(access.role(request.user) in ['admin','analyst'],'演练核对由经营分析师或管理员确认')
    for k,lo,hi in [('owner',1,150),('note',5,2000)]:
        if not isinstance(p[k],str) or not lo<=len(p[k].strip())<=hi:raise ValueError('请填写责任岗位和5至2000字的跟进依据')
    due=p['due_date'] or None
    if due and (not isinstance(due,str) or date.fromisoformat(due).isoformat()!=due):raise ValueError('期限须为YYYY-MM-DD')
    if p['data_revision']!=list(analytics.revision()):return reply({'error':'业务来源已变化，请重新读取'},409)
    objkey=f'sales:{key}';item=IssueDisposition.objects.select_for_update().filter(key=objkey).first();before=follow_info(item)
    if before['version']!=p['version']:return reply({'error':'跟进版本已变化，请重新读取'},409)
    values=dict(status=p['status'],owner=p['owner'].strip(),note=p['note'].strip(),due_date=due,version=p['version']+1,updated_by=request.user.username,updated_at=timezone.now())
    if item:
        if IssueDisposition.objects.filter(pk=item.pk,version=p['version']).update(**values)!=1:return reply({'error':'跟进版本冲突'},409)
        item.refresh_from_db()
    else:item=IssueDisposition.objects.create(key=objkey,**values)
    serial=lambda x:json.loads(json.dumps(x,ensure_ascii=False,default=str))
    AuditEvent.objects.create(action='sales.followup',actor=request.user.username,object_type='SalesCoordination',object_id=objkey,detail={'before':serial(before),'after':serial(follow_info(item)),'data_revision':p['data_revision'],'source_issues':obj['row']['issues'],'business_facts_changed':False})
    return response(request,{'follow_up':follow_info(item),'notice':'已保存独立协调记录，原报价、订单关联和任务状态未修改。'})

@api()
def history(request,key):
    d,_=context(request);d.detail(key)
    return response(request,{'rows':list(AuditEvent.objects.filter(object_type='SalesCoordination',object_id=f'sales:{key}').order_by('-id').values('actor','created_at','detail'))})

@api()
@transaction.atomic
def export(request):
    d,f=context(request);quotes=d.selected();rows=[eng.safe(r,access.can_money(request.user)) for r in (quotes if f['tab']=='quotes' else d.task_rows(quotes)) if f['stage'] in r['flags']]
    fields=[('id','报价单号'),('customer_id','客户编码'),('customer_name','客户名称'),('product_id','配置编码'),('owner_id','报价负责工号'),('quote_date','报价日期'),('valid_until','有效截至'),('calculated_state','截止状态'),('qty','报价数量'),('linked_qty','可核对关联数量'),('unlinked_qty','尚未关联数量'),('valid_links','有效关联行数'),('comparable_links','可比金额关联行数'),('quote_days','询价至报价自然日'),('overdue_tasks','逾期未完成任务数')] if f['tab']=='quotes' else [('id','跟进任务号'),('quote_id','报价单号'),('owner_id','任务负责工号'),('kind','任务类型'),('created','建立日期'),('due','约定完成'),('completed_as_of','截止完成'),('calculated_state','截止状态'),('description','跟进事项'),('result','反馈说明')]
    if f['tab']=='quotes' and access.can_money(request.user):fields += [('currency','报价币种'),('tax_basis','报价价税口径'),('unit_price_cents','报价单价分'),('order_value_cents','可比关联订单未税金额分'),('quote_reference_cents','同数量报价未税参考分'),('price_difference_cents','同数量价差分')]
    data=[['销售报价模拟工作台','截止',d.cutoff,'筛选',json.dumps(f,ensure_ascii=False)],['说明',eng.NOTE+'；可比金额仅含有效关联中的CNY未税、单价有效行，按对应数量核算。任务页继承报价日期队列。'],[label for _,label in fields]+['待核对事项']]+[[r.get(k) for k,_ in fields]+['；'.join(r['issues'])] for r in rows]
    AuditEvent.objects.create(action='sales.export',actor=request.user.username,object_type='SalesBoard',object_id=f['tab'],detail={'filters':f,'rows':len(rows)})
    result=csv_reply(data,'sales-'+f['tab']);result['Cache-Control']='no-store';return result
