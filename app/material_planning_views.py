import json,hashlib
from datetime import date
from decimal import Decimal
from django.db import transaction
from django.utils import timezone
from . import material_planning as eng,material_impact,material_lot_allocation as lots,analytics,access
from .views import api,reply,body,require
from .models import AuditEvent,IssueDisposition
from .delivery_views import follow_info
from .trace_cases import capture_sources
from .quality_views import csv_reply
from .import_review import ReviewConflict

STATUSES=['待核对','待计划协调','待采购核对','演练已核查']
def lot_summary(d):
    if not d.lot_pool:return []
    out=[]
    for unit in sorted({r['unit'] for r in d.material_rows.values()}):
        rows=[r for r in d.material_rows.values() if r['unit']==unit];valid=[r for r in rows if r['initial_pool'] is not None]
        total=lambda key:sum((r[key] for r in valid),Decimal(0)) if valid else None
        out.append({'unit':unit,'known_materials':len(valid),'unknown_materials':len(rows)-len(valid),'usable_state_qty':total('usable_state_qty'),'date_candidate_qty':total('date_candidate_qty'),'date_excluded_usable_qty':total('date_excluded_usable_qty'),'initial_pool':total('initial_pool'),'simulated_allocated':total('simulated_allocated'),'remaining_pool':total('remaining_pool')})
    return out
def respond(value):
    r=reply(eng.clean(value));r['Cache-Control']='no-store';return r
def page(request,size=25):
    value=request.GET.get('page','1')
    if not value.isdecimal() or not 1<=int(value)<=100000:raise ValueError('页码无效')
    return int(value)
def context(request,need_receipt=False):
    f=eng.filters(request.GET);d,rev=eng.current(f);receipt=eng.receipt(f,rev)
    if request.GET.get('receipt') and request.GET['receipt']!=receipt:raise ReviewConflict('备料范围、数据或规则已变化，请重新运行；未沿用旧试配')
    if need_receipt and not request.GET.get('receipt'):raise ValueError('请从已查看的备料结果进入')
    return d,f,receipt,rev
def verify(f,rev,receipt):
    if list(analytics.revision())!=list(rev) or eng.receipt(f,rev)!=receipt:raise ReviewConflict('计算或读取期间来源/规则变化，请重新运行')
def brief(row,tab):
    out={k:v for k,v in row.items() if k not in (['links','sources'] if tab=='impact' else ['items','sources'] if tab=='orders' else ['allocations','demand_work_orders','unknown_work_orders'])}
    if tab=='materials':out.update(known_order_count=len(row['demand_work_orders']),unknown_order_count=len(row['unknown_work_orders']))
    return out
def can_follow(user):return access.role(user) in ['admin','analyst','operations','quality']
def object_key(kind,key):return f'material_planning:{kind}:{key}'
def object_detail(d,kind,key):
    if kind=='impact':return material_impact.OrderImpact(d).detail(key)
    obj=d.detail(kind,key)
    if kind=='orders':
        impact=material_impact.OrderImpact(d);links=[r for r in impact.rows if key in r['work_orders']]
        obj.update(order_links=[brief(r,'impact') for r in links],order_link_issues=next((r['issues'] for r in impact.unlinked if r['id']==key),[]))
        obj['sources']=eng.unique(obj['sources']+[s for r in links for s in r['sources']]+eng.refs('allocations',[a for a in d.data.get('allocations',[]) if a.get('work_order_id')==key]))
    return obj
def selected_rows(d,f):return material_impact.OrderImpact(d).rows if f['tab']=='impact' else d.rows(f['tab'])

@api()
@transaction.atomic
def board(request):
    d,f,receipt,rev=context(request);p=page(request);impact=material_impact.OrderImpact(d) if f['tab']=='impact' else None;rows=impact.rows if impact else d.rows(f['tab']);chosen=[r for r in rows if f['stage'] in r['flags']]
    active=[w for w in d.ordered if not w['excluded']]
    data={'filters':f,'summary':d.summary(),'rows':[brief(r,f['tab']) for r in chosen[(p-1)*25:p*25]],'page':p,'size':25,'total':len(chosen),
          'stages':eng.STAGES[f['tab']],'facets':{k:sum(k in r['flags'] for r in rows) for k in eng.STAGES[f['tab']]},
          'queue':[{'id':w['id'],'sequence':w['sequence'],'state':w['state'],'planned_qty':w['planned_qty'],'product_id':w['product_id'],'short_materials':w['short_materials']} for w in active[:120]],'queue_total':len(active),
          'options':{'families':sorted({p['family'] for p in d.products.values()}),'products':[{'id':p['id'],'model':p['model']} for p in d.products.values()]},
          'global_issues':d.global_issues,'receipt':receipt,'as_of':d.cutoff,'note':eng.NOTE,'boundary':eng.BOUNDARY,'lot_policies':lots.POLICIES,'lot_note':lots.NOTE,'lot_summary':lot_summary(d)}
    if impact:data.update(impact_summary=impact.summary(),impact_note=material_impact.NOTE,unlinked_work_orders=impact.unlinked)
    verify(f,rev,receipt);return respond(data)

@api()
@transaction.atomic
def detail(request,kind,key):
    d,f,receipt,rev=context(request,True);obj=object_detail(d,kind,key);verify(f,rev,receipt)
    return respond({**obj,'receipt':receipt,'filters':f,'as_of':d.cutoff,'note':eng.NOTE,'boundary':eng.BOUNDARY,'lot_note':lots.NOTE,'lot_policy_label':lots.POLICIES[f['lot_policy']],'can_follow':can_follow(request.user),
                    'follow_up':follow_info(IssueDisposition.objects.filter(key=object_key(kind,key)).first())})

@api()
@transaction.atomic
def return_export(request,key):
    d,f,receipt,rev=context(request,True);obj=object_detail(d,'orders',key);report=obj['return_reconciliation']
    rows=[['生产领退料核对 · 合成模拟数据','工单',key,'截止',d.cutoff],['定义',report['version']],['说明',report['notice']],
          ['范围','当前工单全部需求物料和全部直接/反向关联退料；不按清单状态裁剪。未参与备料的完工/取消工单不计算BOM待领量。'],
          ['物料','单位','累计领料','可核对退料','净领料','模拟总需求','待领需求','领退料量可核对']]
    rows += [[x.get(k) for k in ('material_id','unit','gross_issued_qty','returned_qty','issued_qty','gross_required','remaining_required','issue_balance_known')] for x in obj['row']['items']]
    rows += [[],['退料流水','原领料','退料工单','原工单','物料','批次','退回库位','退料时点','原增减量','单位','关联可核对','问题']]
    rows += [[r['id'],r['issue_id'],r['work_order_id'],r['issue']['work_order_id'] if r['issue'] else None,r['material_id'],r['lot'],r['location'],r['occurred'],r['qty_signed'],r['unit'],r['verified'],'；'.join(r['issues'])] for r in report['rows']]
    originals={r['issue']['id']:r['issue'] for r in report['rows'] if r['issue']}
    rows += [[],['原领料流水','工单','物料','批次','库位','领料时点','原增减量','来源单号']]
    rows += [[r[k] for k in ('id','work_order_id','material_id','lot','location','occurred','qty_signed','reference')] for r in originals.values()]
    sources=capture_sources({'sources':[r for r in obj['sources'] if access.allowed(request.user,r['dataset'])]})
    rows += [[],['Excel来源对象','编号','文件','工作表','行','资料缺失']]
    rows += [[r.get(k) for k in ('dataset','key','filename','sheet','row','missing')] for r in sources]
    verify(f,rev,receipt)
    response=csv_reply(rows,'production-returns-'+hashlib.sha256(key.encode()).hexdigest()[:16]);response['Cache-Control']='no-store'
    AuditEvent.objects.create(action='material_returns.export',actor=request.user.username,object_type='MaterialPlanning',object_id=key,
                              detail=dict(filters=f,receipt=receipt,returns=len(report['rows']),file_sha256=hashlib.sha256(response.content).hexdigest(),business_facts_changed=False))
    return response

@api()
@transaction.atomic
def evidence(request,kind,key):
    d,f,receipt,rev=context(request,True);obj=object_detail(d,kind,key);p=page(request);rows=capture_sources({'sources':[r for r in obj['sources'] if access.allowed(request.user,r['dataset'])]});verify(f,rev,receipt)
    return respond({'rows':rows[(p-1)*40:p*40],'total':len(rows),'page':p,'size':40,'can_download_original':access.can_import(request.user),'receipt':receipt})

def comparison(d,f,rev,receipt):
    alt={**f,'stock_policy':'all_usable' if f['stock_policy']=='protect_safety' else 'protect_safety'}
    other=eng.MaterialPlanning(d.data,alt,stock=d.stock);rows=[]
    for w in d.ordered:
        b=other.orders[w['id']]
        if w['state']!=b['state']:rows.append({'id':w['id'],'product_id':w['product_id'],'planned_qty':w['planned_qty'],'before':w['state'],'after':b['state'],'before_short':w['short_materials'],'after_short':b['short_materials']})
    verify(f,rev,receipt)
    out={'primary':d.summary(),'reference':other.summary(),'primary_policy':f['stock_policy'],'reference_policy':alt['stock_policy'],'rows':rows,'reference_filters':alt,'receipt':receipt,
            'note':'同一数据、工单队列与排序，只切换安全库存缓冲。整单试配存在队列竞争，释放更多库存不保证每张原可覆盖工单都保持可覆盖；这不是采购或投产批准。'}
    if f['tab']=='impact':
        a=material_impact.OrderImpact(d);b=material_impact.OrderImpact(other)
        out.update(primary_impact=a.summary(),reference_impact=b.summary(),order_changes=[{'id':r['id'],'customer':r['customer'],'remaining_qty':r['remaining_qty'],'before_short':r['short_link_qty'],'after_short':b.index[r['id']]['short_link_qty']} for r in a.rows if r['short_link_qty']!=b.index[r['id']]['short_link_qty']])
    return out

@api()
@transaction.atomic
def compare(request):
    d,f,receipt,rev=context(request,True);return respond(comparison(d,f,rev,receipt))

@api()
@transaction.atomic
def lot_compare(request):
    d,f,receipt,rev=context(request,True);results=[]
    for key,label in lots.POLICIES.items():
        alt={**f,'lot_policy':key};other=d if key==f['lot_policy'] else eng.MaterialPlanning(d.data,alt,stock=d.stock)
        changes=[{'id':w['id'],'product_id':w['product_id'],'planned_qty':w['planned_qty'],'before':w['state'],'after':other.orders[w['id']]['state']} for w in d.ordered if w['state']!=other.orders[w['id']]['state']]
        results.append({'key':key,'label':label,'summary':other.summary(),'lot_summary':lot_summary(other),'changes':changes})
    verify(f,rev,receipt)
    return respond({'primary_policy':f['lot_policy'],'results':results,'filters':f,'receipt':receipt,'as_of':d.cutoff,'note':'同一队列、工单顺序和安全库存策略，仅改变批次日期策略。全单试配会重新竞争库存，不能把结论变化当作实际产量或延期数量。账面策略不指定批次；日期策略排除未知资料，并按当前截止与计划开工中较晚一天核对有效期。','boundary':lots.NOTE})

LOT_FIELDS=[('sequence','全队列序号'),('work_order_id','工单号'),('product_id','配置编码'),('material_id','物料编码'),('material','物料名称'),('unit','单位'),('lot','批次'),('location','库位'),('qty','本单模拟用量'),('before','本单之前批次模拟池'),('after','本单之后批次模拟池'),('use_day','有效期核对至'),('first_stock_date','首次入库登记'),('expires','有效截至'),('reference_rank','同物料参考位次'),('retained','本次批次安全缓冲'),('date_profile_id','日期登记依据'),('date_version','日期版本'),('policy_id','关注规则依据'),('policy_version','规则版本')]
def lot_export_rows(d,f):
    selected=[r for r in selected_rows(d,f) if f['stage'] in r['flags']]
    work_ids={r['id'] for r in selected} if f['tab']=='orders' else {wid for r in selected for wid in r['work_orders']} if f['tab']=='impact' else set(d.orders)
    material_ids={r['id'] for r in selected} if f['tab']=='materials' else set(d.material_rows)
    return [{'sequence':w['sequence'],'work_order_id':w['id'],'product_id':w['product_id'],'material_id':item['material_id'],'material':item['material'],'unit':item['unit'],**p} for w in d.ordered if w['id'] in work_ids for item in w['items'] if item['material_id'] in material_ids for p in item.get('lot_allocations',[])]

@api()
@transaction.atomic
def lot_export(request):
    d,f,receipt,rev=context(request,True)
    if not d.lot_pool:raise ValueError('账面策略未指定批次；请先选择FIFO或FEFO日期推演')
    rows=lot_export_rows(d,f)
    data=[['备料批次计划 · 合成模拟数据','截止',d.cutoff,'范围及策略',json.dumps(f,ensure_ascii=False)],['说明',lots.NOTE],['范围边界','只导出当前清单关联的整单可覆盖工单及已拟配批次，缺料工单没有占用。订单影响视角按工单去重，批次计划未拆分到订单行。'],['计算依据',receipt],[label for _,label in LOT_FIELDS]]
    data += [[eng.clean(r).get(k) for k,_ in LOT_FIELDS] for r in rows]
    verify(f,rev,receipt);AuditEvent.objects.create(action='material_lots.export',actor=request.user.username,object_type='MaterialLotAllocation',object_id=f['tab'],detail={'filters':f,'receipt':receipt,'rows':len(rows),'business_facts_changed':False})
    response=csv_reply(data,'material-lots-'+f['tab']);response['Cache-Control']='no-store';return response

ORDER_FIELDS=[('sequence','全队列序号'),('id','工单号'),('product_id','配置编码'),('family','产品族'),('planned_start','计划开工'),('planned_end','计划完工'),('priority','优先级'),('planned_qty','计划台数'),('assembled_qty','已登记装配台数'),('bom_version','工单BOM版本'),('state','试配状态'),('material_count','需求物料种类'),('short_materials','队列位置缺口物料种类'),('unknown_materials','库存未知物料种类')]
MATERIAL_FIELDS=[('id','物料编码'),('material','物料名称'),('unit','单位'),('usable_state_qty','可用状态库存'),('safety_buffer','本次安全库存缓冲'),('initial_pool','试配池起点'),('net_demand','已知工单净需求'),('known_gap','已知需求余额缺口'),('simulated_allocated','整单试配占用'),('remaining_pool','试配后剩余池'),('open_purchase_qty','采购未到参考量'),('known_order_count','已知需求工单数'),('unknown_order_count','需求待核对工单数')]
IMPACT_FIELDS=[('id','订单行'),('order_id','订单'),('customer_id','客户编码'),('customer','客户'),('product_id','配置'),('due','现承诺日'),('qty','订单数量台'),('shipped_qty','登记发货台数'),('remaining_qty','未交台数'),('overdue_remaining_qty','按现承诺逾期未交台数'),('selected_allocated_qty','选中工单分配计划台数'),('short_link_qty','缺料工单关联计划台数'),('covered_link_qty','可覆盖工单关联计划台数'),('excluded_link_qty','完工取消工单关联计划台数'),('outside_link_qty','范围外工单分配计划台数'),('unallocated_qty','未分配工单台数'),('plan_after_due_count','选中工单计划晚于现承诺的工单数')]

@api()
@transaction.atomic
def export(request):
    d,f,receipt,rev=context(request,True);rows=[r for r in selected_rows(d,f) if f['stage'] in r['flags']];fields=IMPACT_FIELDS if f['tab']=='impact' else ORDER_FIELDS if f['tab']=='orders' else MATERIAL_FIELDS
    if d.lot_pool and f['tab']=='materials':fields=MATERIAL_FIELDS+[('date_candidate_qty','日期候选量'),('date_excluded_usable_qty','可用状态量中未纳入日期候选')]
    values=[]
    for r in rows:
        row=eng.clean({**r,**brief(r,f['tab'])});values.append([eng.STAGES['orders'].get(row.get(k),row.get(k)) if k=='state' else row.get(k) for k,_ in fields]+['；'.join(row['issues'])])
    data=[['备料共享库存试配 · 合成模拟数据','截止',d.cutoff,'范围及策略',json.dumps(f,ensure_ascii=False)],['说明',eng.NOTE+(material_impact.NOTE if f['tab']=='impact' else '')],['使用边界',eng.BOUNDARY],['计算依据',receipt],[v for _,v in fields]+['资料问题']]+values
    verify(f,rev,receipt);AuditEvent.objects.create(action='material_planning.export',actor=request.user.username,object_type='MaterialPlanning',object_id=f['tab'],detail={'filters':f,'receipt':receipt,'rows':len(rows),'business_facts_changed':False})
    r=csv_reply(data,'material-planning-'+f['tab']);r['Cache-Control']='no-store';return r

@api(('POST',))
@transaction.atomic
def follow_up(request,kind,key):
    require(can_follow(request.user));d,f,receipt,rev=context(request,True);obj=object_detail(d,kind,key);p=body(request)
    if set(p)!={'status','owner','note','due_date','version'}:raise ValueError('请提供完整协调字段')
    if p['status'] not in STATUSES or type(p['version']) is not int or p['version']<0:raise ValueError('协调状态或版本无效')
    for k,lo,hi in [('owner',1,150),('note',5,2000)]:
        if not isinstance(p[k],str) or not lo<=len(p[k].strip())<=hi:raise ValueError('请填写岗位及5至2000字协调依据')
    due=p['due_date'] or None
    if due and (not isinstance(due,str) or date.fromisoformat(due).isoformat()!=due):raise ValueError('期限格式无效')
    item=IssueDisposition.objects.select_for_update().filter(key=object_key(kind,key)).first();before=follow_info(item)
    if before['version']!=p['version']:raise ReviewConflict('协调记录已有新版本，请重新读取')
    values=dict(status=p['status'],owner=p['owner'].strip(),note=p['note'].strip(),due_date=due,version=p['version']+1,updated_by=request.user.username,updated_at=timezone.now())
    verify(f,rev,receipt)
    if item:
        if IssueDisposition.objects.filter(pk=item.pk,version=p['version']).update(**values)!=1:raise ReviewConflict('协调版本冲突')
        item.refresh_from_db()
    else:item=IssueDisposition.objects.create(key=object_key(kind,key),**values)
    serial=lambda v:json.loads(json.dumps(v,ensure_ascii=False,default=str))
    AuditEvent.objects.create(action='material_planning.followup',actor=request.user.username,object_type='MaterialPlanningCoordination',object_id=object_key(kind,key),detail={'before':serial(before),'after':serial(follow_info(item)),'filters':f,'receipt':receipt,'state':obj['row'].get('state'),'business_facts_changed':False})
    return respond({'follow_up':follow_info(item),'notice':'协调已保存，未预留库存、生成采购或改变工单状态。'})

@api()
def history(request,kind,key):
    d,f,receipt,rev=context(request,True);object_detail(d,kind,key);verify(f,rev,receipt)
    return respond({'rows':list(AuditEvent.objects.filter(object_type='MaterialPlanningCoordination',object_id=object_key(kind,key)).order_by('-id').values('actor','created_at','detail'))})
