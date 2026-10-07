import json,statistics
from datetime import date
from django.db import transaction
from django.utils import timezone
from . import supply,analytics,access
from .views import api,reply,body,require
from .models import IssueDisposition,AuditEvent,Record
from .delivery_views import follow_info
from .quality_views import csv_reply
from .trace_cases import capture_sources

STATUSES=['待处理','核对中','催交中','待源系统复核','演练已核验']
def can_follow(user):return access.role(user) in ['admin','analyst','quality','operations']
def context(request):
    d=supply.current();f=supply.filters(request.GET);rows=supply.cohort(d,f);chosen=[r for r in rows if f['stage'] in r['flags']];return d,f,rows,chosen
def obj(kind,key):return supply.current().detail(kind,key)
def object_key(kind,key):return 'supply:'+kind+':'+key

@api()
def board(request):
    d,f,rows,chosen=context(request);page=max(1,int(request.GET.get('page','1')));stages=supply.STOCK_STAGES if f['tab']=='stock' else supply.PO_STAGES
    fields=['balance_qty','usable_state_qty'] if f['tab']=='stock' else ['qty','received_qty','approved_qty','putaway_qty','remaining_qty'];totals=[]
    for unit,rr in sorted(supply.group(rows,'unit').items()):
        totals.append({'unit':unit,'objects':len(rr),**{key:float(supply.total(rr,key)) if unit!='未知' and all(r[key] is not None for r in rr) else None for key in fields}})
    categories=[{'category':k,**supply.summary(rr,f['tab'])} for k,rr in sorted(supply.group(rows,'category').items())]
    if f['tab']=='stock':
        for row in categories:
            ratios=[r['usable_state_qty']/r['safety_qty'] for r in rows if r['category']==row['category'] and r['usable_state_qty'] is not None and r['safety_qty']>0]
            row.update(known_safety=len(ratios),minimum_multiple=min(ratios) if ratios else None,median_multiple=statistics.median(ratios) if ratios else None)
    suppliers=[]
    if f['tab']=='purchase':
        suppliers=[{'id':sid,'name':rr[0]['supplier'],**supply.summary(rr,'purchase')} for sid,rr in sorted(supply.group(rows,'supplier_id').items())]
    return reply({'global_issues':d.global_issues,'filters':f,'summary':supply.summary(rows,f['tab']),'unit_totals':totals,'categories':categories,'suppliers':suppliers,'stages':stages,'facets':{k:sum(k in r['flags'] for r in rows) for k in stages},'rows':[supply.clean(r) for r in chosen[(page-1)*25:page*25]],'total':len(chosen),'page':page,'size':25,'as_of':d.cutoff,'note':supply.NOTE,'options':{'categories':sorted({r['category'] for r in d.stock_rows}),'materials':[{'id':r['id'],'name':r['material']} for r in d.stock_rows],'suppliers':[{'id':k,'name':v['name']} for k,v in sorted(d.suppliers.items())]}})

@api()
def detail(request,kind,key):
    d=obj(kind,key);d['follow_up']=follow_info(IssueDisposition.objects.filter(key=object_key(kind,key)).first());d['data_revision']=list(analytics.revision());d['can_follow_up']=can_follow(request.user);d['as_of']=analytics.AS_OF;d['note']=supply.NOTE;return reply(d)

@api()
def evidence(request,kind,key):
    d=obj(kind,key);rows=capture_sources(d);page=max(1,int(request.GET.get('page','1')))
    return reply({'rows':rows[(page-1)*40:page*40],'total':len(rows),'page':page,'size':40,'can_download_original':access.can_import(request.user)})

@api()
def ledger(request,lot_id):
    r=supply.current().lot_index.get(lot_id)
    if not r:raise Record.DoesNotExist()
    if set(request.GET)-{'page'}:raise ValueError('不支持的流水筛选')
    page=max(1,int(request.GET.get('page','1')));rr=r['_timeline']
    return reply({'lot':supply.clean(r),'opening':[supply.without_money(x) for x in r['_opening']],'rows':rr[(page-1)*40:page*40],'total':len(rr),'page':page,'size':40,'as_of':analytics.AS_OF,'note':'按发生时刻排序；状态事件数量为0。运行余额来自同一已导入期初和全部流水，分页不重新置零；有账据异常时仅供核对。'})

@api(('POST',))
def follow_up(request,kind,key):
    require(can_follow(request.user));d=obj(kind,key);p=body(request)
    if set(p)!={'status','owner','note','due_date','version','data_revision'}:raise ValueError('协调字段不完整或包含未知字段')
    if p['status'] not in STATUSES or type(p['version']) is not int or p['version']<0:raise ValueError('协调状态或版本不可用')
    if not isinstance(p['owner'],str) or not 1<=len(p['owner'].strip())<=150 or not isinstance(p['note'],str) or not 5<=len(p['note'].strip())<=2000:raise ValueError('请填写负责人及5至2000字依据')
    due=date.fromisoformat(p['due_date']) if p['due_date'] else None
    with transaction.atomic():
        if p['data_revision']!=list(analytics.revision()):return reply({'error':'来源已变化，请刷新核对'},409)
        item=IssueDisposition.objects.select_for_update().filter(key=object_key(kind,key)).first();before=follow_info(item)
        if before['version']!=p['version']:return reply({'error':'协调已被更新，请重新读取'},409)
        changed={'status':p['status'],'owner':p['owner'].strip(),'note':p['note'].strip(),'due_date':due,'version':before['version']+1,'updated_by':request.user.username,'updated_at':timezone.now()}
        if item:
            if IssueDisposition.objects.filter(pk=item.pk,version=p['version']).update(**changed)!=1:return reply({'error':'协调版本冲突'},409)
            item.refresh_from_db()
        else:item=IssueDisposition.objects.create(key=object_key(kind,key),**changed)
        serial=lambda x:json.loads(json.dumps(x,ensure_ascii=False,default=str))
        AuditEvent.objects.create(action='supply.followup',actor=request.user.username,object_type='SupplyCoordination',object_id=object_key(kind,key),detail={'before':serial(before),'after':serial(follow_info(item)),'source_issues':d['row']['issues'],'data_revision':p['data_revision'],'business_facts_changed':False})
    return reply({'follow_up':follow_info(item),'notice':'协调记录已保存；采购、检验、库存和冻结状态不受此操作影响。'})

@api()
def history(request,kind,key):
    obj(kind,key)
    return reply({'rows':list(AuditEvent.objects.filter(object_type='SupplyCoordination',object_id=object_key(kind,key)).order_by('-id').values('actor','detail','created_at'))})

@api()
def export(request):
    d,f,_,rows=context(request)
    fields=['id','material','category','unit','balance_qty','usable_state_qty','safety_qty','safety_gap','open_purchase_qty'] if f['tab']=='stock' else ['id','material_id','supplier','unit','due','qty','received_qty','approved_qty','putaway_qty','remaining_qty']
    labels=['物料编码','物料名称','类别','单位','账面余额','可用状态余额','安全库存','安全库存差额','采购未到'] if f['tab']=='stock' else ['采购行','物料编码','供应商','单位','承诺到货日','采购数量','已到货','检验批准','已入库','未到数量']
    data=[['模拟供应工作台','截止',d.cutoff,'筛选',json.dumps(f,ensure_ascii=False)],['说明',supply.NOTE],labels+['核对事项']]+[[r[k] for k in fields]+['；'.join(r['issues'])] for r in rows]
    AuditEvent.objects.create(action='supply.export',actor=request.user.username,object_type='SupplyBoard',object_id=f['tab'],detail={'filters':f,'rows':len(rows)})
    return csv_reply(data,'supply-'+f['tab'])
