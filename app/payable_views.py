import json,hashlib
from pathlib import Path
from collections import defaultdict
from django.db import transaction
from django.utils import timezone
from . import payables as ap,analytics,access
from .views import api,reply,body,require
from .models import AuditEvent,IssueDisposition
from .delivery_views import follow_info
from .trace_cases import capture_sources
from .quality_views import csv_reply

STATUSES=['待核对','供应商对账中','待采购确认','待财务复核','演练已核对']
def response(data,status=200):
    r=reply(data,status);r['Cache-Control']='no-store';return r
def receipt():return hashlib.sha256(json.dumps([list(analytics.revision()),analytics.DAY,hashlib.sha256(Path(ap.__file__).read_bytes()).hexdigest()],ensure_ascii=False).encode()).hexdigest()
def context(request):
    require(access.can_money(request.user),'当前身份没有财务数据权限')
    return ap.current()
def page(params):
    v=params.get('page',1)
    if isinstance(v,bool):raise ValueError('页码无效')
    n=int(v)
    if not 1<=n<=100000:raise ValueError('页码无效')
    return n
def refs(obj):return capture_sources({'sources':[x for x in obj['sources'] if x.get('key')]})

@api()
@transaction.atomic
def board(request):
    d=context(request);f=ap.params(request.GET);rows=d.selected(f);p=page(request.GET);items=rows[(p-1)*25:p*25]
    notes={n.key:n for n in IssueDisposition.objects.filter(key__in=['ap:'+f['tab']+':'+r['id'] for r in items])}
    suppliers=defaultdict(list)
    for r in rows:suppliers[r['supplier_id']].append(r)
    groups=[{'id':k,'name':v[0]['supplier_name'],**ap.summary(v,f['tab'])} for k,v in sorted(suppliers.items(),key=lambda x:str(x[0]))]
    schedule=[]
    if f['tab']=='plans':
        bydate=defaultdict(list)
        for r in rows:
            if r['remaining_cents'] is not None and r['remaining_cents']>0:bydate[r['planned']].append(r)
        schedule=[{'date':k,'rows':len(v),'remaining_cents':sum(r['remaining_cents'] for r in v),'overdue':k<d.cutoff} for k,v in sorted(bydate.items())]
    summary=ap.summary(rows,f['tab']);summary['complete']=summary['complete'] and not d.global_issues
    aging=[]
    if f['tab']=='invoices':
        for key,label in ap.BUCKETS.items():
            members=[r for r in rows if r['bucket']==key]
            aging.append({'key':key,'label':label,**ap.summary(members,'invoices')})
    return response({'filters':f,'tabs':ap.TABS,'stages':ap.STAGES,'buckets':ap.BUCKETS,'as_of':d.cutoff,'note':ap.NOTE,'receipt':receipt(),'summary':summary,
                     'rows':[{**ap.safe(r),'follow_up':follow_info(notes.get('ap:'+f['tab']+':'+r['id']))} for r in items],'page':p,'size':25,'total':len(rows),
                     'facets':{k:sum(k=='all' or r.get('stage')==k for r in d.selected(f,ignore_stage=True)) for k in ap.STAGES},'suppliers':groups,'schedule':schedule,
                     'aging':aging,'global_issues':d.global_issues,'supplier_options':[{'id':k,'name':v['name']} for k,v in sorted(d.maps['suppliers'].items())]})

@api()
@transaction.atomic
def detail(request,kind,key):
    d=context(request);r=d.detail(kind,key)
    return response({'row':r,'as_of':d.cutoff,'note':ap.NOTE,'receipt':receipt(),'follow_up':follow_info(IssueDisposition.objects.filter(key='ap:'+kind+':'+key).first()),'statuses':STATUSES})

@api()
@transaction.atomic
def evidence(request,kind,key):
    d=context(request)
    if request.GET.get('receipt')!=receipt():return response({'error':'数据或计算已变化，请重新打开对象后核对来源'},409)
    r=d.detail(kind,key);rows=refs(r);p=page(request.GET)
    return response({'rows':rows[(p-1)*40:p*40],'total':len(rows),'page':p,'size':40,'can_download_original':access.can_import(request.user)})

@api(('POST',))
@transaction.atomic
def follow_up(request,kind,key):
    d=context(request);r=d.detail(kind,key);p=body(request)
    if set(p)!={'version','status','owner','due_date','note','receipt'}:raise ValueError('跟进字段不完整或包含未知字段')
    if p['receipt']!=receipt():return response({'error':'数据或计算已变化，请重新读取并核对'},409)
    if type(p['version']) is not int or p['version']<0 or p['status'] not in STATUSES:raise ValueError('跟进版本或状态不可用')
    for k,lo,hi in [('owner',1,150),('note',5,2000)]:
        if not isinstance(p[k],str) or not lo<=len(p[k].strip())<=hi:raise ValueError('请填写负责人和5至2000字跟进依据')
    due=p['due_date'] or None
    if due and not ap.day(due):raise ValueError('跟进日期无效')
    identity='ap:'+kind+':'+key;item=IssueDisposition.objects.select_for_update().filter(key=identity).first();before=follow_info(item)
    if before['version']!=p['version']:return response({'error':'跟进已被更新，请重新读取'},409)
    values=dict(status=p['status'],owner=p['owner'].strip(),due_date=due,note=p['note'].strip(),version=p['version']+1,updated_by=request.user.username,updated_at=timezone.now())
    if item:
        if IssueDisposition.objects.filter(pk=item.pk,version=p['version']).update(**values)!=1:return response({'error':'跟进版本冲突'},409)
        item.refresh_from_db()
    else:item=IssueDisposition.objects.create(key=identity,**values)
    serial=lambda x:json.loads(json.dumps(x,ensure_ascii=False,default=str))
    AuditEvent.objects.create(action='payable.followup',actor=request.user.username,object_type='PayableCoordination',object_id=identity,detail={'before':serial(before),'after':serial(follow_info(item)),'receipt':p['receipt'],'source_issues':r['issues'],'business_facts_changed':False})
    return response({'follow_up':follow_info(item),'notice':'已保存对账跟进。付款、核销、计划审批及应付事实保持原样。'})

@api()
def history(request,kind,key):
    context(request).detail(kind,key)
    return response({'rows':list(AuditEvent.objects.filter(object_type='PayableCoordination',object_id='ap:'+kind+':'+key).order_by('-id').values('actor','created_at','detail'))})

FIELDS={
 'invoices':[('id','应付发票号'),('invoice_no','供应商发票号'),('supplier_id','供应商编码'),('supplier_name','供应商名称'),('currency','币种'),('issued','开票日'),('posted','确认日'),('due','到期日'),('gross_cents','发票含税额分'),('allocated_cents','付款核销分'),('reversal_cents','核销冲回分'),('credit_cents','贷项冲减分'),('balance_cents','已核对余额分'),('stage_label','计算状态'),('overdue_days','逾期天数')],
 'payments':[('id','付款登记号'),('supplier_id','供应商编码'),('supplier_name','供应商名称'),('currency','币种'),('paid','付款日期'),('amount_cents','付款登记金额分'),('status','登记状态'),('net_allocation_cents','已核对净核销分'),('unallocated_cents','已核对未核销分'),('document_no','付款凭据号')],
 'plans':[('id','安排号'),('invoice_id','应付发票号'),('supplier_id','供应商编码'),('supplier_name','供应商名称'),('created','登记日期'),('approved','批准日期'),('planned','计划日期'),('amount_cents','原安排金额分'),('status','安排状态'),('executed_cents','净执行核销分'),('remaining_cents','可核对未执行分'),('late','计划逾期未执行')],
 'receipts':[('id','到货单号'),('purchase_line_id','采购行号'),('supplier_id','供应商编码'),('supplier_name','供应商名称'),('material_id','物料编码'),('unit','单位'),('received','到货时间'),('qty','到货数量'),('billed_qty','已确认开票数量'),('unbilled_qty','未开票数量差'),('reference_net_cents','按约定未税参考额分'),('status','到货登记状态')],
}
@api()
@transaction.atomic
def export(request):
    d=context(request);f=ap.params(request.GET)
    if request.GET.get('receipt')!=receipt():return response({'error':'数据或计算已变化，请刷新工作台再导出'},409)
    rows=d.selected(f);fields=FIELDS[f['tab']]
    values=[['模拟供应商应付',ap.TABS[f['tab']],'截止业务日',d.cutoff,'筛选',json.dumps(f,ensure_ascii=False)],['说明',ap.NOTE],['计算依据',receipt(),'全局未关联事项',len(d.global_issues)],
            [label for _,label in fields]+['余额或安排核对事项','采购到货对账事项','未计入原因']]
    values.extend([[r.get(k) for k,_ in fields]+['；'.join(r['issues']),'；'.join(r.get('match_issues',[])),r.get('exclusion','')] for r in rows])
    AuditEvent.objects.create(action='payable.export',actor=request.user.username,object_type='PayableBoard',object_id=f['tab'],detail={'filters':f,'rows':len(rows),'receipt':receipt()})
    out=csv_reply(values,'payables-'+f['tab']);out['Cache-Control']='no-store';return out
