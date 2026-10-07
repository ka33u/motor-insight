import json
from datetime import date
from django.db import transaction
from django.utils import timezone
from . import receivables,analytics,access
from .views import api,reply,body,require
from .models import IssueDisposition,AuditEvent
from .delivery_views import follow_info
from .quality_views import csv_reply
from .trace_cases import capture_sources

STATUSES=['待处理','对账中','待客户确认','催收跟进中','待源系统复核','演练已核验']

def response(data):
    r=reply(data);r['Cache-Control']='no-store';return r

def context(request):
    require(access.can_money(request.user),'当前身份没有财务数据权限')
    return receivables.current(),receivables.filters(request.GET)

@api()
@transaction.atomic
def board(request):
    d,f=context(request);rows=d.selected(f);base=d.selected(f,ignore_stage=True)
    page=max(1,int(request.GET.get('page',1)));items=rows[(page-1)*25:page*25]
    notes={n.key:n for n in IssueDisposition.objects.filter(key__in=['ar:'+r['key'] for r in items])}
    s=receivables.summary(rows);s['complete']=s['complete'] and not d.global_issues
    return response({'filters':f,'summary':s,**receivables.breakdown(rows),'rows':[{**receivables.safe(r),'follow_up':follow_info(notes.get('ar:'+r['key']))} for r in items],
        'total':len(rows),'page':page,'size':25,'as_of':d.cutoff,'note':receivables.NOTE,'global_issues':d.global_issues,'stages':receivables.STAGES,'buckets':receivables.BUCKETS,'kinds':receivables.KINDS,
        'facets':{k:sum(k=='all' or r['stage']==k for r in base) for k in receivables.STAGES},
        'customer_options':[{'id':k,'name':v['name']} for k,v in sorted(d.maps['customers'].items())]})

@api()
@transaction.atomic
def detail(request,kind,key):
    d,f=context(request);obj=d.detail(kind,key)
    obj.update(follow_up=follow_info(IssueDisposition.objects.filter(key='ar:'+kind+':'+key).first()),statuses=STATUSES,data_revision=list(analytics.revision()),as_of=d.cutoff,note=receivables.NOTE)
    return response(obj)

@api()
@transaction.atomic
def evidence(request,kind,key):
    d,_=context(request);rows=capture_sources(d.detail(kind,key));page=max(1,int(request.GET.get('page',1)))
    return response({'rows':rows[(page-1)*40:page*40],'total':len(rows),'page':page,'size':40,'can_download_original':access.can_import(request.user)})

@api(('POST',))
@transaction.atomic
def follow_up(request,kind,key):
    d,_=context(request);obj=d.detail(kind,key);p=body(request)
    if set(p)!={'version','status','owner','due_date','note','data_revision'}:raise ValueError('跟进字段不完整或含未知字段')
    if type(p['version']) is not int or p['version']<0 or p['status'] not in STATUSES:raise ValueError('跟进版本或状态不可用')
    for name,lo,hi in [('owner',1,150),('note',5,2000)]:
        if not isinstance(p[name],str) or not lo<=len(p[name].strip())<=hi:raise ValueError('请填写负责人及5至2000字跟进依据')
    due=p['due_date'] or None
    if due and (not isinstance(due,str) or date.fromisoformat(due).isoformat()!=due):raise ValueError('期限格式应为YYYY-MM-DD')
    if p['data_revision']!=list(analytics.revision()):return reply({'error':'来源已变化，请重新读取并核对'},409)
    object_key='ar:'+kind+':'+key;item=IssueDisposition.objects.select_for_update().filter(key=object_key).first();before=follow_info(item)
    if before['version']!=p['version']:return reply({'error':'跟进记录已更新，请重新读取'},409)
    values=dict(status=p['status'],owner=p['owner'].strip(),due_date=due,note=p['note'].strip(),version=p['version']+1,updated_by=request.user.username,updated_at=timezone.now())
    if item:
        if IssueDisposition.objects.filter(pk=item.pk,version=p['version']).update(**values)!=1:return reply({'error':'跟进版本冲突，请重新读取'},409)
        item.refresh_from_db()
    else:item=IssueDisposition.objects.create(key=object_key,**values)
    serial=lambda value:json.loads(json.dumps(value,ensure_ascii=False,default=str))
    AuditEvent.objects.create(action='receivable.followup',actor=request.user.username,object_type='ReceivableCoordination',object_id=object_key,
        detail={'before':serial(before),'after':serial(follow_info(item)),'data_revision':p['data_revision'],'source_issues':obj['row']['issues'],'business_facts_changed':False})
    return response({'follow_up':follow_info(item),'notice':'已保存催收/对账跟进；不改变收款、核销、发票或财务结账事实。'})

@api()
def history(request,kind,key):
    d,_=context(request);d.detail(kind,key)
    return response({'rows':list(AuditEvent.objects.filter(object_type='ReceivableCoordination',object_id='ar:'+kind+':'+key).order_by('-id').values('actor','created_at','detail'))})

@api()
@transaction.atomic
def export(request):
    d,f=context(request);rows=d.selected(f)
    fields=[('id','应收对象号'),('kind_label','来源类型'),('document_no','原单据号'),('customer_id','客户编码'),('customer_name','客户名称'),('currency','原币种'),('issued','原开票日期'),('basis_date','余额起点日'),('due','到期日'),('basis_cents','余额起点金额分'),('receipt_cents','已核销收款分'),('reversal_cents','核销冲回分'),('net_receipt_cents','净核销收款分'),('credit_cents','贷项冲减分'),('balance_cents','已核对余额分'),('overdue_days','逾期天数'),('bucket_label','账龄'),('status_label','计算状态')]
    valid=lambda r:r['balance_cents'] is not None
    money_fields={'basis_cents','receipt_cents','reversal_cents','net_receipt_cents','credit_cents'}
    data=[['模拟应收核对','截止业务日',d.cutoff,'筛选',json.dumps(f,ensure_ascii=False)],['说明',receivables.NOTE],
          ['全局未关联记录',len(d.global_issues),'待核对或未来对象的汇总金额留空'],[label for _,label in fields]+['核对事项']]
    data += [[None if k in money_fields and not valid(r) else r.get(k) for k,_ in fields]+['；'.join(r['issues'])] for r in rows]
    AuditEvent.objects.create(action='receivable.export',actor=request.user.username,object_type='ReceivableBoard',object_id='current',detail={'filters':f,'rows':len(rows),'as_of':d.cutoff})
    res=csv_reply(data,'receivables');res['Cache-Control']='no-store';return res
