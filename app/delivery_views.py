"""Read-only business board plus separately audited coordination notes."""
import csv,io,json
from datetime import date
from django.db import transaction
from django.utils import timezone
from django.http import HttpResponse
from . import access,analytics,delivery
from .models import AuditEvent,IssueDisposition,Record
from .views import api,reply,body,require

STATUSES=['待处理','处理中','待源系统复核','已核验']

def follow_info(item=None):
    if item is None:return {'status':'待处理','owner':'','note':'','due_date':None,'version':0,'updated_by':'','updated_at':None}
    return {k:getattr(item,k) for k in ['status','owner','note','due_date','version','updated_by','updated_at']}

def get_line(line_id):
    found=next((r for r in delivery.rows() if r['id']==line_id),None)
    if found is None:raise Record.DoesNotExist()
    return found

def selected(request):
    f=delivery.filters(request.GET);rows=delivery.rows();chosen,facets=delivery.select(rows,f)
    return f,rows,chosen,facets

@api()
def board(request):
    f,rows,chosen,facets=selected(request)
    page=max(1,int(request.GET.get('page','1')));size=min(100,max(1,int(request.GET.get('size','30'))))
    items=chosen[(page-1)*size:page*size];notes={x.key:x for x in IssueDisposition.objects.filter(key__in=['delivery:'+r['id'] for r in items])}
    return reply({'rows':[{**delivery.public_row(r),'follow_up':follow_info(notes.get('delivery:'+r['id']))} for r in items], 'summary':delivery.summary(chosen),'facets':facets,'filters':f,'page':page,'size':size,'total':len(chosen),'as_of':analytics.AS_OF,'note':delivery.NOTE,'release_rule':delivery.RELEASE_RULE,'stages':delivery.STAGES,'options':{'families':sorted({r['family'] for r in rows}),'customers':[{'id':k,'name':v} for k,v in sorted({r['customer_id']:r['customer'] for r in rows}.items())]},'can_follow_up':access.role(request.user) in ['admin','analyst','quality','operations']})

@api()
def detail(request,line_id):
    row=get_line(line_id);stage=request.GET.get('unit_stage','all');page=max(1,int(request.GET.get('unit_page','1')))
    if set(request.GET)-{'unit_stage','unit_page'}:raise ValueError('不支持的订单明细筛选')
    if stage not in delivery.UNIT_STAGES:raise ValueError('SN状态筛选不可用')
    units=[u for u in row['_units'] if stage=='all' or u['stage']==stage];size=30
    visible=[{k:v for k,v in u.items() if not k.startswith('_')} for u in units[(page-1)*size:page*size]]
    return reply({'row':delivery.public_row(row),'plans':row['_plans'],'work_orders':row['_work_orders'],'shipments':row['_shipments'],'unit_rows':visible,'unit_total':len(units),'unit_page':page,'unit_size':size,'unit_stages':delivery.UNIT_STAGES,'unit_stage':stage,'sources':row['_sources'],'follow_up':follow_info(IssueDisposition.objects.filter(key='delivery:'+line_id).first()),'as_of':analytics.AS_OF,'release_rule':delivery.RELEASE_RULE,'note':delivery.NOTE,'can_follow_up':access.role(request.user) in ['admin','analyst','quality','operations']})

@api(('POST',))
def follow_up(request,line_id):
    require(access.role(request.user) in ['admin','analyst','quality','operations'])
    get_line(line_id);data=body(request)
    if set(data)-{'status','owner','note','due_date','version'}:raise ValueError('跟进字段不可用')
    if data.get('status') not in STATUSES:raise ValueError('跟进状态不可用')
    if type(data.get('version')) is not int or data['version']<0:raise ValueError('请提供当前跟进版本')
    for key,limit in [('owner',150),('note',2000)]:
        if not isinstance(data.get(key),str) or len(data[key].strip())>limit:raise ValueError('负责人或说明格式不正确')
    owner=data['owner'].strip();note=data['note'].strip()
    if not owner or len(note)<5:raise ValueError('请填写负责人和至少5字的跟进依据')
    when=data.get('due_date')
    if when in (None,''):when=None
    elif not isinstance(when,str) or date.fromisoformat(when).isoformat()!=when:raise ValueError('期限必须为YYYY-MM-DD')
    key='delivery:'+line_id
    with transaction.atomic():
        item=IssueDisposition.objects.select_for_update().filter(key=key).first();before=follow_info(item)
        if before['version']!=data['version']:return reply({'error':'跟进记录已被其他人更新，请重新读取后再保存。','code':'stale_followup'},409)
        changed={'status':data['status'],'owner':owner,'note':note,'due_date':when,'version':before['version']+1,'updated_by':request.user.username,'updated_at':timezone.now()}
        if item:
            if IssueDisposition.objects.filter(pk=item.pk,version=data['version']).update(**changed)!=1:return reply({'error':'跟进版本已变化，请刷新。'},409)
            item.refresh_from_db()
        else:item=IssueDisposition.objects.create(key=key,**changed)
        serial=lambda v:json.loads(json.dumps(v,default=str,ensure_ascii=False))
        AuditEvent.objects.create(action='delivery.followup',actor=request.user.username,object_type='OrderLine',object_id=line_id,detail={'before':serial(before),'after':serial(follow_info(item)),'business_facts_changed':False})
    return reply({'follow_up':follow_info(item),'notice':'仅保存协调跟进；未修改订单、检测、放行或发货事实。'})

@api()
def export(request):
    f,_,chosen,_=selected(request);out=io.StringIO();writer=csv.writer(out)
    safe=lambda v:("'"+v if isinstance(v,str) and v.startswith(('=','+','-','@','\t','\r')) else v)
    writer.writerow(['模拟交付工作台','截止',analytics.AS_OF,'筛选',json.dumps(f,ensure_ascii=False)])
    writer.writerow(['口径',delivery.NOTE]);writer.writerow(['放行检查',delivery.RELEASE_RULE])
    writer.writerow(['订单行','客户编码','客户','配置','原承诺日','现承诺日','订单台数','未交台数','逾期未交台数','明确归属装配台数','检测放行待处理台数','已放行未发台数','归属可核对','数据问题','下一动作'])
    for r in chosen:writer.writerow([safe(v) for v in [r['id'],r['customer_id'],r['customer'],r['product_id'],r['original_due'],r['due'],r['qty'],r['remaining_qty'],r['overdue_qty'],r['produced_qty'],r['quality_wait_qty'],r['stages']['ready'],'是' if r['ownership_ok'] else '否','；'.join(r['issues']),r['next_action']]])
    AuditEvent.objects.create(action='delivery.export',actor=request.user.username,object_type='DeliveryBoard',object_id='snapshot',detail={'filters':f,'rows':len(chosen),'as_of':analytics.AS_OF})
    response=HttpResponse('\ufeff'+out.getvalue(),content_type='text/csv; charset=utf-8');response['Content-Disposition']='attachment; filename="delivery-board.csv"';return response
