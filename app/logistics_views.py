import json,hashlib
from pathlib import Path
from collections import defaultdict
from django.db import transaction
from django.utils import timezone
from . import logistics as lg,analytics,access
from .views import api,reply,body,require
from .models import AuditEvent,IssueDisposition
from .delivery_views import follow_info
from .trace_cases import capture_sources
from .quality_views import csv_reply

STATUSES=['待核对','承运交接核对中','客户签收核对中','待业务复核','演练已核对']
def response(data,status=200):
    r=reply(data,status);r['Cache-Control']='no-store';return r
def receipt():return hashlib.sha256(json.dumps([list(analytics.revision()),analytics.AS_OF,hashlib.sha256(Path(lg.__file__).read_bytes()).hexdigest()],ensure_ascii=False).encode()).hexdigest()
def page(p):
    n=int(p.get('page',1))
    if not 1<=n<=100000:raise ValueError('页码无效')
    return n
def writable(user):return access.role(user) in ['admin','analyst','operations']

@api()
@transaction.atomic
def board(request):
    d=lg.current();f=lg.params(request.GET);rows=d.selected(f);p=page(request.GET);items=rows[(p-1)*25:p*25]
    notes={n.key:n for n in IssueDisposition.objects.filter(key__in=['logistics:'+r['id'] for r in items])}
    carriers=defaultdict(list)
    for r in rows:carriers[r['carrier']].append(r)
    return response({'filters':f,'stages':lg.STAGES,'as_of':d.cutoff,'note':lg.NOTE,'receipt':receipt(),'summary':lg.summary(rows),'rows':[{**lg.safe(r),'follow_up':follow_info(notes.get('logistics:'+r['id']))} for r in items],'page':p,'size':25,'total':len(rows),'carriers':[{'name':k,**lg.summary(v)} for k,v in sorted(carriers.items())],'carrier_options':sorted({r['carrier'] for r in d.rows.values()}),'customer_options':[{'id':r['id'],'name':r['name']} for r in sorted(d.maps.get('customers',{}).values(),key=lambda x:x['id'])],'global_issues':d.global_issues})

@api()
@transaction.atomic
def detail(request,key):
    r=lg.current().detail(key)
    return response({'row':r,'as_of':analytics.AS_OF,'note':lg.NOTE,'receipt':receipt(),'follow_up':follow_info(IssueDisposition.objects.filter(key='logistics:'+key).first()),'statuses':STATUSES,'can_follow':writable(request.user)})

@api()
@transaction.atomic
def evidence(request,key):
    if request.GET.get('receipt')!=receipt():return response({'error':'数据或计算已变化，请重新打开对象后核对来源'},409)
    r=lg.current().detail(key);rows=capture_sources({'sources':r['sources']});p=page(request.GET)
    return response({'rows':rows[(p-1)*40:p*40],'total':len(rows),'page':p,'size':40,'can_download_original':access.can_import(request.user)})

@api(('POST',))
@transaction.atomic
def follow_up(request,key):
    require(writable(request.user),'仅管理员、分析师和生产计划角色可登记发运协调')
    r=lg.current().detail(key);p=body(request)
    if set(p)!={'version','status','owner','due_date','note','receipt'}:raise ValueError('跟进字段不完整或包含未知字段')
    if p['receipt']!=receipt():return response({'error':'数据或计算已变化，请重新读取并核对'},409)
    if type(p['version']) is not int or p['version']<0 or p['status'] not in STATUSES:raise ValueError('跟进版本或状态不可用')
    for k,lo,hi in [('owner',1,150),('note',5,2000)]:
        if not isinstance(p[k],str) or not lo<=len(p[k].strip())<=hi:raise ValueError('请填写负责人和5至2000字跟进依据')
    due=p['due_date'] or None
    if due and not lg.day(due):raise ValueError('跟进日期无效')
    identity='logistics:'+key;item=IssueDisposition.objects.select_for_update().filter(key=identity).first();before=follow_info(item)
    if before['version']!=p['version']:return response({'error':'跟进已被更新，请重新读取'},409)
    values=dict(status=p['status'],owner=p['owner'].strip(),due_date=due,note=p['note'].strip(),version=p['version']+1,updated_by=request.user.username,updated_at=timezone.now())
    if item:
        if IssueDisposition.objects.filter(pk=item.pk,version=p['version']).update(**values)!=1:return response({'error':'跟进版本冲突'},409)
        item.refresh_from_db()
    else:item=IssueDisposition.objects.create(key=identity,**values)
    serial=lambda x:json.loads(json.dumps(x,ensure_ascii=False,default=str))
    AuditEvent.objects.create(action='logistics.followup',actor=request.user.username,object_type='LogisticsCoordination',object_id=identity,detail={'before':serial(before),'after':serial(follow_info(item)),'receipt':p['receipt'],'source_issues':r['issues'],'business_facts_changed':False})
    return response({'follow_up':follow_info(item),'notice':'已保存协调记录。签收、退货、库存和应收事实未变更。'})

@api()
def history(request,key):
    lg.current().detail(key)
    return response({'rows':list(AuditEvent.objects.filter(object_type='LogisticsCoordination',object_id='logistics:'+key).order_by('-id').values('actor','created_at','detail'))})

FIELDS=[('id','发货行号'),('order_line_id','订单行号'),('customer_id','客户编码'),('customer_name','客户名称'),('product_id','配置编码'),('carrier','承运商'),('tracking','运单号'),('shipped','发货时间'),('qty','发货台数'),('handed','交接时间'),('promised','到货承诺'),('accepted','接收SN数'),('refused','拒收SN数'),('pending','待签收SN数'),('full_received','全量接收时间'),('stage_label','签收状态'),('due','到期承诺'),('on_time','可核对按期足量接收'),('signed','原台账签收时间'),('legacy_check','原台账核对')]
@api()
@transaction.atomic
def export(request):
    if request.GET.get('receipt')!=receipt():return response({'error':'数据或计算已变化，请刷新工作台再导出'},409)
    d=lg.current();f=lg.params(request.GET);rows=d.selected(f)
    values=[['模拟发运签收','截止',d.cutoff,'筛选',json.dumps(f,ensure_ascii=False)],['说明',lg.NOTE],['计算依据',receipt(),'全局关联问题',len(d.global_issues)],['空值表示数量或时效不可核对，不能当作零；各汇总的未知范围独立展示'],[label for _,label in FIELDS]+['核对事项']]
    values.extend([[r.get(k) for k,_ in FIELDS]+['；'.join(r['issues'])] for r in rows])
    AuditEvent.objects.create(action='logistics.export',actor=request.user.username,object_type='LogisticsBoard',object_id='shipments',detail={'filters':f,'rows':len(rows),'receipt':receipt()})
    out=csv_reply(values,'shipment-receipts');out['Cache-Control']='no-store';return out
