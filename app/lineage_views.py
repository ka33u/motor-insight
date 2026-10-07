import csv,io,json
from . import analytics,lineage,trace_cases,access
from .models import TraceCase,AuditEvent
from .views import api,reply,body

def snapshot_for(request):
    if request.GET.get('case_id'):
        case=TraceCase.objects.get(pk=request.GET['case_id']);return case.snapshot,case
    return lineage.current(request.GET.get('kind','material_lot'),request.GET.get('id',''),request.GET.get('material_id','')),None

def presentation(snapshot,query,case,user):
    units,filters=lineage.select(snapshot,query);page=max(1,int(query.get('page','1')));size=30
    data={k:v for k,v in snapshot.items() if k not in ['units','edges','sources','source_manifest']}
    data.update(units=units[(page-1)*size:page*size],unit_total=len(units),page=page,size=size,filters=filters,case=trace_cases.info(case) if case else None,edge_preview=snapshot['edges'][:60],edge_total=len(snapshot['edges']),source_count=len(snapshot.get('source_manifest',snapshot['sources'])),can_create=trace_cases.can_edit(user),can_edit_case=trace_cases.can_edit(user),can_close=access.role(user) in ['admin','quality'])
    return data

@api()
def search(request):return reply(lineage.graph(analytics.revision()).search(request.GET.get('kind','material_lot'),request.GET.get('q','')))

@api()
def board(request):
    snapshot,case=snapshot_for(request);return reply(presentation(snapshot,request.GET,case,request.user))

@api()
def evidence(request):
    snapshot,case=snapshot_for(request);page=max(1,int(request.GET.get('page','1')));source=snapshot.get('source_manifest',snapshot['sources'])
    q=request.GET.get('q','').strip().lower()
    if len(q)>150:raise ValueError('来源检索内容过长')
    source=[r for r in source if q in json.dumps(r,ensure_ascii=False).lower()];selected=source[(page-1)*40:page*40]
    if not case:selected=trace_cases.capture_sources({'sources':selected})
    return reply({'rows':selected,'total':len(source),'page':page,'size':40,'frozen':bool(case),'can_download_original':access.can_import(request.user)})

@api()
def unit_path(request,unit_id):
    snapshot,_=snapshot_for(request);row=next(r for r in snapshot['units'] if r['id']==unit_id) if any(r['id']==unit_id for r in snapshot['units']) else None
    if row is None:return reply({'error':'此SN不在当前反查范围'},404)
    index={e['id']:e for e in snapshot['edges']}
    return reply({'unit':row,'path':[index[k] for k in row['path']],'notice':'展示一条可达证据路径；汇合路径按SN去重，其他关联在谱系来源中保留。无谱系候选需人工补证，不能用同工单关系代替实际使用。'})

@api(('GET','POST'))
def cases(request):
    if request.method=='POST':
        c=trace_cases.create(request.user,body(request));return reply(trace_cases.info(c))
    rows=TraceCase.objects.order_by('-created_at')[:100]
    return reply({'rows':[{**trace_cases.info(c),'root':c.snapshot['root'],'summary':c.snapshot['summary']} for c in rows],'limit':100})

@api(('GET','POST'))
def case_detail(request,case_id):
    if request.method=='POST':return reply(trace_cases.info(trace_cases.update(request.user,case_id,body(request))))
    c=TraceCase.objects.get(pk=case_id)
    return reply({'case':trace_cases.info(c),'history':list(AuditEvent.objects.filter(object_type='TraceCase',object_id=str(c.pk)).order_by('-id').values('action','actor','created_at','detail'))})

@api()
def comparison(request,case_id):return reply(trace_cases.compare(TraceCase.objects.get(pk=case_id)))

@api()
def export(request):
    snapshot,case=snapshot_for(request);rows,filters=lineage.select(snapshot,request.GET);out=io.StringIO();w=csv.writer(out)
    safe=lambda v:"'"+v if isinstance(v,str) and v.startswith(('=','+','-','@','\t','\r')) else v
    w.writerow(['模拟批次影响范围','类型','保存快照' if case else '当前查询','排查编号',case.code if case else '', '快照指纹',case.snapshot_hash if case else trace_cases.digest(snapshot)])
    w.writerow(['对象',json.dumps(snapshot['root'],ensure_ascii=False),'截止',snapshot['as_of'],'筛选',json.dumps(filters,ensure_ascii=False)])
    w.writerow(['说明',lineage.NOTICE]);w.writerow(['SN','配置','产品族','工单','关联依据','检测结论','当前有效放行','已发货','发货行','订单行','客户','归属说明','待核对事项'])
    for r in rows:w.writerow([safe(v) for v in [r['id'],r['product_id'],r['family'],r['work_order_id'],r['relation'],r['quality'],'是' if r['release_valid'] else '待核验','是' if r['shipped'] else '否','；'.join(r['shipment_ids']),'；'.join(r['order_line_ids']),'；'.join(c['name'] for c in r['customers']),r['ownership'],'；'.join(r['issues'])]])
    AuditEvent.objects.create(action='lineage.export',actor=request.user.username,object_type='TraceCase' if case else 'Lineage',object_id=str(case.pk) if case else snapshot['root']['id'],detail={'root':snapshot['root'],'filters':filters,'rows':len(rows),'frozen':bool(case)})
    from django.http import HttpResponse
    r=HttpResponse('\ufeff'+out.getvalue(),content_type='text/csv; charset=utf-8');r['Content-Disposition']='attachment; filename="lineage-impact.csv"';return r
