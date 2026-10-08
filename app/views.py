import csv,io,json,tempfile,hashlib
from copy import deepcopy
from datetime import datetime,timedelta
from decimal import Decimal,ROUND_HALF_UP
from functools import wraps
from pathlib import Path
from django.conf import settings
from django.contrib.auth import authenticate,login,logout
from django.core.exceptions import ValidationError,PermissionDenied,ObjectDoesNotExist
from django.db import transaction,IntegrityError,OperationalError
from django.db.models import Count,Q
from django.http import JsonResponse,HttpResponse,FileResponse
from django.shortcuts import render
from django.views.decorators.csrf import ensure_csrf_cookie
from .models import ImportBatch,ImportRow,Record,ImportDecision,AuditEvent,CodingRule,AnalysisModel,Topic,IssueDisposition
from .schema import SCHEMAS
from .semantic_schema import SEMANTIC_SCHEMAS,schemas
from . import semantic
from . import access,analytics,coding,bi_scope
from .ingestion import stage_file,commit_batch,convert,fingerprint
from .analysis_engine import run_analysis,validate_definition,selected_rows,group_key
from . import import_review
from . import import_mapping
from . import import_templates
from . import issue_workspace

def reply(value,status=200):return JsonResponse(value,safe=not isinstance(value,list),status=status,json_dumps_params={'ensure_ascii':False})
def body(request):
    try:
        data=json.loads(request.body or b'{}')
        if not isinstance(data,dict):raise ValueError('请求必须为JSON对象')
        return data
    except (ValueError,UnicodeDecodeError):raise ValueError('请求内容必须为JSON')
def require(condition,message='没有操作权限'):
    if not condition:raise PermissionDenied(message)

def api(methods=('GET',)):
    def deco(fn):
        @wraps(fn)
        def wrapped(request,*args,**kwargs):
            if request.method not in methods:return reply({'error':'请求方法不支持'},405)
            if not request.user.is_authenticated:return reply({'error':'请先登录'},401)
            try:
                require(access.role(request.user) is not None,'账号角色冲突，请联系管理员')
                return fn(request,*args,**kwargs)
            except import_review.ReviewConflict as ex:return reply({'error':str(ex),'code':'review_conflict'},409)
            except import_mapping.MappingStale as ex:return reply({'error':str(ex),'code':'mapping_stale'},409)
            except issue_workspace.Stale as ex:return reply({'error':str(ex),'code':'issue_scope_stale'},409)
            except PermissionDenied as ex:return reply({'error':str(ex)},403)
            except ObjectDoesNotExist:return reply({'error':'记录不存在'},404)
            except (ValueError,TypeError,ValidationError,KeyError) as ex:return reply({'error':'; '.join(ex.messages) if isinstance(ex,ValidationError) else str(ex)},400)
            except IntegrityError:return reply({'error':'唯一编号或并发更新冲突，请刷新后重试'},409)
            except OperationalError as ex:
                if 'locked' in str(ex).lower():return reply({'error':'当前有其他写入操作，请稍后刷新审核版本再重试'},409)
                raise
        return wrapped
    return deco

def user_info(user):return {'authenticated':user.is_authenticated,'username':user.username if user.is_authenticated else None,'role':access.role(user),'role_label':access.ROLES.get(access.role(user)),'can_edit':access.can_edit(user),'can_import':access.can_import(user),'can_money':access.can_money(user)}

@ensure_csrf_cookie
def index(request):
    digest=hashlib.sha256()
    for name in ["wip_trial.js","wip_readiness.js","return_stock.js","joint_occupancy.js","joint_batch_material.js","joint_compare.js","joint_compare.css","workbench.js","workbench.css","curing.js","curing.css","launch.js","launch.css","order_baseline.js","order_baseline.css","joint_schedule.js","joint_schedule.css","bi_decision_reading.js","oee.js","oee.css","topic_pages.js","topic_pages.css","crew_schedule.js","crew_schedule.css","finite_schedule.js","finite_schedule.css","model_card_exports.js","model_card_results.js","model_card_results.css","model_cards.js","msa.js","msa.css","spc_workspace.js","spc_workspace.css","spc.js","spc.css","credentials.js","credentials.css","topic_linkage.js","topic_linkage.css","device_transform.js","device_transform.css","device_collection.js","device_collection.css","device_intake.js","device_intake.css","bi_field_catalog.js","bi_field_catalog.css","bi_card_summary.js","bi_card_summary.css","issue_workspace.js","issue_workspace.css","import_mapping.js","import_mapping.css","metrology_evidence.js","metrology_evidence.css","metrology.js","metrology.css",'app.js','wip_flow.js','wip_comparison.js','wip_flow.css','file_sharing.js','material_certificates.js','material_certificates.css','incoming_quality.js','incoming_quality.css','receipt_flow.js','receipt_flow.css','purchase_commitments.js','purchase_commitments.css','material_lots.js','material_lots.css','inventory_age.js','inventory_age.css','stocktake.js','stocktake.css','material_supply.js','coordination_hub.js','coordination_hub.css','assembly_plans.js','assembly_plans.css','target_breakdown.js','targets.js','targets.css','logistics.js','logistics.css','quantiles.js','app.css','delivery.js','metrics.js','lineage.js','quality.js','supply.js','derived.js','coding.js','topics.js','topic_snapshots.js','cost_scenarios.js','device_files.js','assets.js','catalog_planning.js','catalog_planning.css','receivables.js','payables.js','groupings.js','workforce.js','energy.js','service.js','data_health.js','engineering.js','sales.js','manufacturing.js','process_quality.js','analysis_drill.js','analysis_pivot.js','material_planning.js','material_impact.js','accounts.js','pivot_comparison.js','action_tasks.js','quality_comparison.js','analysis_scatter.js']:digest.update((settings.BASE_DIR/'static'/name).read_bytes())
    version=digest.hexdigest()[:12]
    # ES module imports do not inherit the entry script's query string.
    imports={settings.STATIC_URL+p.name:settings.STATIC_URL+p.name+'?v='+version for p in (settings.BASE_DIR/'static').glob('*.js')}
    response=render(request,'index.html',{'demo':settings.DEBUG,'asset_version':version,'module_imports':json.dumps({'imports':imports})})
    response['Cache-Control']='no-cache'
    return response

@ensure_csrf_cookie
def auth(request):
    if request.method=='GET':return reply(user_info(request.user))
    if request.method!='POST':return reply({'error':'方法不支持'},405)
    try:data=body(request)
    except ValueError as ex:return reply({'error':str(ex)},400)
    if data.get('action')=='logout':logout(request);return reply(user_info(request.user))
    user=authenticate(request,username=data.get('username',''),password=data.get('password',''))
    if not user or access.role(user) is None:return reply({'error':'用户名、密码或账号状态不可用'},401)
    login(request,user)
    from .accounts import bind_session
    bind_session(request,user)
    AuditEvent.objects.create(action='auth.login',actor=user.username,object_type='User',object_id=str(user.pk))
    return reply(user_info(user))

@api()
def overview(request):
    from .overview_presentation import build
    presentation=build(request.user,request.GET)
    value=deepcopy(analytics.overview(request.GET.get('family','')))
    if not access.can_money(request.user):value.pop('finance',None)
    dispositions={i.key:{'status':i.status,'owner':i.owner,'note':i.note,'updated_by':i.updated_by} for i in IssueDisposition.objects.all()}
    for i in value['issues']:i['disposition']=dispositions.get(i['key'],{'status':'待处理','owner':i['owner'],'note':''})
    value['imports']={'batches':ImportBatch.objects.count(),'quarantined':ImportRow.objects.filter(status__in=['invalid','conflict']).count(),'last':ImportBatch.objects.order_by('-committed_at').values('committed_at','filename').first()}
    value['presentation']=presentation
    r=reply(value);r['Cache-Control']='no-store';return r

@api()
def production_board(request):
    from .production import blocks
    from collections import defaultdict
    d=analytics.tables();facts=semantic.rows('bi_resource_day')
    dates=sorted({r['date'] for r in facts});processes=sorted({r['process'] for r in facts})
    selected=request.GET.get('date','2026-09-21' if '2026-09-21' in dates else (dates[-1] if dates else ''))
    process=request.GET.get('process','装配')
    if selected and selected not in dates:raise ValueError('该日没有已导入的资源排班数据')
    if process and process not in processes:raise ValueError('未知工序')
    chosen=[r for r in facts if r['date']==selected and (not process or r['process']==process)]
    ids={r['resource_id'] for r in chosen};opids=set();events=defaultdict(list);windows=defaultdict(list)
    for r in d['operations']:
        if r.get('resource_id') in ids and r['started'][:10]<=selected<=r['finished'][:10]:
            events[r['resource_id']].append(access.sanitize(request.user,'operations',r));opids.add(r['id'])
    for r in d.get('resource_calendars',[]):
        if r['resource_id'] in ids and r['started'][:10]<=selected<=r['finished'][:10]:windows[r['resource_id']].append({'id':r['id'],'started':r['started'],'finished':r['finished']})
    blocked=blocks(d,analytics.AS_OF);rows=[]
    for fact in chosen:
        stop=[{'dataset':key,'id':r['id'],'started':a.isoformat(timespec='seconds'),'finished':b.isoformat(timespec='seconds'),'label':r.get('reason') or r.get('failure')} for a,b,key,r in blocked[fact['equipment_id']] if a.date().isoformat()<=selected<=b.date().isoformat()]
        rows.append({**access.sanitize(request.user,'bi_resource_day',fact),'events':sorted(events[fact['resource_id']],key=lambda r:r['started']),'windows':windows[fact['resource_id']],'blocks':stop})
    totals={k:round(sum(r[k] for r in chosen),4) for k in ['scheduled_minutes','blocked_minutes','available_minutes','busy_minutes','event_count']}
    totals['occupancy_pct']=round(totals['busy_minutes']/totals['available_minutes']*100,2) if totals['available_minutes']>0 and all(r['integrity']=='可计算' for r in chosen) else None
    labor=None
    if access.allowed(request.user,'labor_entries'):
        groups=defaultdict(lambda:{'minutes':0,'amount_cents':0,'entries':0})
        for r in d.get('labor_entries',[]):
            if r['operation_id'] not in opids:continue
            origin=datetime.fromisoformat(r['started']);finish=datetime.fromisoformat(r['finished']);daystart=datetime.fromisoformat(selected);dayend=daystart+timedelta(days=1)
            start=max(origin,daystart);stop=min(finish,dayend,datetime.fromisoformat(analytics.AS_OF))
            if start>=stop:continue
            seconds=Decimal(str((finish-origin).total_seconds()))
            # Differences of cumulative rounded allocations preserve every cent
            # across adjacent days instead of rounding independent fractions.
            allocation=lambda when:int((Decimal(r['amount_cents'])*Decimal(str((when-origin).total_seconds()))/seconds).quantize(Decimal('1'),rounding=ROUND_HALF_UP))
            a=groups[r['activity']];a['minutes']+=(stop-start).total_seconds()/60;a['amount_cents']+=allocation(stop)-allocation(start);a['entries']+=1
        labor=[{'activity':key,'hours':round(r['minutes']/60,4),'entries':r['entries'],**({'amount_cents':r['amount_cents']} if access.can_money(request.user) else {})} for key,r in sorted(groups.items())]
    return reply({'dates':dates,'processes':processes,'date':selected,'process':process,'rows':rows,'totals':totals,'labor':labor,'note':SEMANTIC_SCHEMAS['bi_resource_day']['note'],'as_of':analytics.AS_OF})

@api()
def datasets(request):
    counts={r['dataset']:r['n'] for r in Record.objects.values('dataset').annotate(n=Count('id'))}
    return reply([{**s,'fields':access.permitted_fields(request.user,key),'count':len(semantic.rows(key)) if key in SEMANTIC_SCHEMAS else counts.get(key,0)} for key,s in schemas().items() if access.allowed(request.user,key)])

@api()
def records(request,dataset):
    if dataset in SEMANTIC_SCHEMAS:return semantic_records(request,dataset)
    require(access.allowed(request.user,dataset));q=Record.objects.filter(dataset=dataset)
    search=request.GET.get('q','').strip();sort=request.GET.get('sort',SCHEMAS[dataset]['primary_key']);direction=request.GET.get('direction','asc')
    permitted={f['name'] for f in access.permitted_fields(request.user,dataset)}
    if sort not in permitted:raise ValueError('排序字段不可用')
    if search:
        condition=Q(business_key__icontains=search)
        for field in permitted:condition|=Q(**{f'values__{field}__icontains':search})
        q=q.filter(condition)
    total=q.count();page=max(1,int(request.GET.get('page',1)));size=min(100,max(1,int(request.GET.get('size',30))))
    q=q.order_by(('-' if direction=='desc' else '')+'values__'+sort,'pk')
    rows=list(q[(page-1)*size:page*size].select_related('source_row__batch'))
    return reply({'total':total,'page':page,'size':size,'fields':access.permitted_fields(request.user,dataset),'rows':[{'id':r.id,'key':r.business_key,'values':access.sanitize(request.user,dataset,r.values),'revision':r.revision,'source':{'batch':str(r.source_row.batch_id),'file':r.source_row.batch.filename,'sheet':r.source_row.sheet,'row':r.source_row.row_number}} for r in rows]})

@api()
def record_export(request,dataset):
    require(access.allowed(request.user,dataset));fields=access.permitted_fields(request.user,dataset)
    out=io.StringIO();writer=csv.writer(out);writer.writerow([f['label'] for f in fields])
    def safe(v):return "'"+v if isinstance(v,str) and v.startswith(('=','+','-','@','\t','\r')) else v
    source=semantic.rows(dataset) if dataset in SEMANTIC_SCHEMAS else Record.objects.filter(dataset=dataset).values_list('values',flat=True).iterator(chunk_size=2000)
    for values in source:writer.writerow([safe(values.get(f['name'])) for f in fields])
    AuditEvent.objects.create(action='data.export',actor=request.user.username,object_type='Dataset',object_id=dataset,detail={'format':'csv','fields':[f['name'] for f in fields]})
    response=HttpResponse('\ufeff'+out.getvalue(),content_type='text/csv; charset=utf-8');response['Content-Disposition']=f'attachment; filename="{dataset}.csv"';return response

def semantic_records(request,dataset):
    require(access.allowed(request.user,dataset));schema=SEMANTIC_SCHEMAS[dataset];fields=access.permitted_fields(request.user,dataset)
    permitted={f['name'] for f in fields};sort=request.GET.get('sort','id')
    if sort not in permitted:raise ValueError('排序字段不可用')
    search=request.GET.get('q','').strip().lower();source=semantic.rows(dataset)
    if search:source=[r for r in source if any(search in str(r.get(f,'')).lower() for f in permitted)]
    source=sorted(source,key=lambda r:(r.get(sort) is not None,r.get(sort) if r.get(sort) is not None else ''),reverse=request.GET.get('direction')=='desc')
    total=len(source);page=max(1,int(request.GET.get('page',1)));size=min(100,max(1,int(request.GET.get('size',30))))
    rows=[]
    for i,r in enumerate(source[(page-1)*size:page*size],(page-1)*size+1):
        sources=[s for s in r['_sources'] if access.allowed(request.user,s['dataset'])]
        rows.append({'id':i,'key':r['id'],'values':access.sanitize(request.user,dataset,r),'revision':schema['version'],'source':{'kind':'semantic','file':schema['label'],'sheet':schema['grain'],'row':None,'batch':None,'references':sources,'note':schema['note']}})
    return reply({'total':total,'page':page,'size':size,'fields':fields,'rows':rows,'grain':schema['grain'],'note':schema['note']})

def batch_info(batch):
    result={'id':str(batch.pk),'filename':batch.filename,'status':batch.status,'summary':batch.summary,'created_at':batch.created_at,'committed_at':batch.committed_at,'mapping':batch.mapping}
    history=import_templates.batch_history(batch)
    if history:result['template_uses']=history
    return result

@api(('GET','POST'))
def imports(request):
    require(access.can_import(request.user))
    if request.method=='GET':return reply([batch_info(b) for b in ImportBatch.objects.prefetch_related('template_uses__version__template').order_by('-created_at')[:100]])
    upload=request.FILES.get('file')
    if not upload:raise ValueError('请选择Excel文件')
    if not upload.name.lower().endswith('.xlsx'):raise ValueError('只接受 .xlsx 文件')
    if upload.size>50*1024*1024:raise ValueError('文件超过50MB')
    mapping=import_mapping.parse_mapping(request.POST.get('mapping','{}'))
    mapping_review=None
    with tempfile.NamedTemporaryFile(suffix='.xlsx') as temp:
        for chunk in upload.chunks():temp.write(chunk)
        temp.flush()
        with transaction.atomic():
            if request.POST.get('inspection_receipt'):
                mapping_review=import_mapping.verify_receipt(request.POST['inspection_receipt'],temp.name,upload.name,mapping,request.user)
            template_receipt=request.POST.get('template_receipt')
            if template_receipt:
                if not mapping_review:raise ValueError('使用模板需同时提供本次文件的映射核对依据')
                version,template_review=import_templates.verify(request.user,template_receipt,temp.name,upload.name,mapping,'use')
            batch,repeated=stage_file(temp.name,upload.name,mapping)
            if template_receipt:import_templates.record_use(request.user,batch,version,template_review,template_receipt,repeated)
    if mapping_review:
        AuditEvent.objects.create(action='import.mapping_verified',actor=request.user.username,object_type='ImportBatch',object_id=str(batch.pk),
            detail={**mapping_review,'review_state':'headers_only','repeated_batch':repeated,'full_row_validation':'existing_batch_not_rechecked' if repeated else 'new_batch_staged','business_approval':False})
    AuditEvent.objects.create(action='import.upload',actor=request.user.username,object_type='ImportBatch',object_id=str(batch.pk))
    return reply({**batch_info(batch),'repeated':repeated})

@api()
def import_detail(request,batch_id):
    require(access.can_import(request.user));batch=ImportBatch.objects.get(pk=batch_id);q=batch.rows.all()
    if request.GET.get('status'):q=q.filter(status=request.GET['status'])
    total=q.count();page=max(1,int(request.GET.get('page',1)))
    return reply({**batch_info(batch),'row_total':total,'page':page,'rows':list(q.order_by('sheet','row_number')[(page-1)*30:page*30].values('id','sheet','row_number','dataset','business_key','normalized','record_hash','status','issues'))})

def archived_import_path(batch):
    path=Path(batch.file_path).resolve();path.relative_to((settings.BASE_DIR/'data/imports').resolve())
    if not path.is_file():raise ObjectDoesNotExist()
    if hashlib.sha256(path.read_bytes()).hexdigest()!=batch.file_hash:raise ValueError('存档原件哈希校验失败，不能作为审核或重新校验依据')
    return path

@api()
def import_file(request,batch_id):
    require(access.can_import(request.user));batch=ImportBatch.objects.get(pk=batch_id);path=archived_import_path(batch)
    AuditEvent.objects.create(action='import.source_download',actor=request.user.username,object_type='ImportBatch',object_id=str(batch.pk))
    return FileResponse(path.open('rb'),as_attachment=True,filename=Path(batch.filename).name,content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')

@api(('POST',))
def import_recheck(request,batch_id):
    require(access.can_import(request.user));original=ImportBatch.objects.get(pk=batch_id)
    batch,_=stage_file(archived_import_path(original),filename=original.filename,mapping=original.mapping,force_recheck=True)
    import_templates.record_recheck(request.user,original,batch)
    AuditEvent.objects.create(action='import.recheck',actor=request.user.username,object_type='ImportBatch',object_id=str(batch.pk),detail={'original_batch':str(original.pk),'formal_records_unchanged':True})
    return reply(batch_info(batch))

@api(('GET','POST'))
def import_conflict_review(request,batch_id,row_id):
    require(access.can_import(request.user))
    if request.method=='GET':return reply(import_review.detail(batch_id,row_id))
    decision,repeated=import_review.decide(batch_id,row_id,request.user.username,body(request))
    return reply({'decision':import_review.decision_info(decision),'repeated':repeated,'batch':batch_info(ImportBatch.objects.get(pk=batch_id))})

@api()
def record_history(request,record_id):
    require(access.can_import(request.user));record=Record.objects.select_related('source_row__batch').get(pk=record_id)
    changes=ImportDecision.objects.filter(row__dataset=record.dataset,row__business_key=record.business_key).select_related('row__batch').order_by('-created_at')
    total=changes.count();page=max(1,int(request.GET.get('page',1)))
    return reply({'current':import_review.snapshot(record),'total':total,'page':page,'changes':[import_review.decision_info(c) for c in changes[(page-1)*20:page*20]],'note':'每次替换增加正式记录版本。历史审核按业务编号保留；模拟数据重建后的记录身份可能不同，历史不被删除。'})

@api(('POST',))
def import_commit(request,batch_id):
    require(access.can_import(request.user));batch=commit_batch(batch_id)
    AuditEvent.objects.create(action='import.approve',actor=request.user.username,object_type='ImportBatch',object_id=str(batch_id))
    return reply(batch_info(batch))

@api(('POST',))
def import_repair(request,batch_id,row_id):
    require(access.can_import(request.user));data=body(request)
    with transaction.atomic():
        batch=ImportBatch.objects.select_for_update().get(pk=batch_id)
        row=ImportRow.objects.select_for_update().get(pk=row_id,batch=batch)
        if batch.status not in ['staged','partial']:raise import_review.ReviewConflict('该历史批次不能修复，请重新上传来源')
        if row.status not in ['invalid','conflict']:raise ValueError('仅可修复隔离中的记录')
        if data.get('expected_row_hash')!=row.record_hash:raise import_review.ReviewConflict('此行内容已变化，请返回批次重新打开后修复')
        schema=SCHEMAS[row.dataset];values=import_review.validate_values(row.dataset,data.get('values',{}),batch_id=batch_id)
        key=values[schema['primary_key']];rh=fingerprint(values);existing=Record.objects.filter(dataset=row.dataset,business_key=key).first()
        sibling=None if existing else ImportRow.objects.filter(batch=batch,dataset=row.dataset,business_key=key,status__in=['valid','committed','replaced']).exclude(pk=row.pk).first()
        prior=existing or sibling
        before=row.normalized;row.normalized=values;row.business_key=key;row.record_hash=rh;row.status=('duplicate' if prior.record_hash==rh else 'conflict') if prior else 'valid';row.issues=[{'message':'相同业务编号有不同内容，请进入差异审核'}] if row.status=='conflict' else [];row.save()
        import_review.summarize(batch)
        AuditEvent.objects.create(action='import.repair',actor=request.user.username,object_type='ImportRow',object_id=str(row_id),detail={'before':before,'after':values,'original_raw_retained':True})
    return reply({'status':row.status,'batch':batch_info(batch)})

@api()
def trace(request,unit_id):
    value=analytics.trace(unit_id)
    for key,dataset in [('unit','units'),('product','products'),('work_order','work_orders')]:value[key]=access.sanitize(request.user,dataset,value[key])
    for key in ['order_lines','customers','service']:
        value[key]=[access.sanitize(request.user,key,r) for r in value[key]]
    return reply(value)

@api(('POST',))
@transaction.atomic
def analyze(request):
    data=body(request);return reply(run_analysis(request.user,data['dataset'],data['definition'],data.get('scope')))

@api()
def scope_options(request):return reply(bi_scope.options(request.user))

@api(('POST',))
def analysis_evidence(request):
    data=body(request);dataset=data['dataset'];definition=data['definition']
    if definition.get('chart')=='pivot':raise ValueError('透视来源请使用行列选择入口')
    rows,scanned,scope=selected_rows(request.user,dataset,definition,data.get('scope'))
    if 'group' in data:rows=[r for r in rows if group_key(r,definition)==str(data['group'])]
    total=len(rows);page=max(1,int(data.get('page',1)));selected=sorted(rows,key=lambda r:str(r['id']))[(page-1)*30:page*30]
    provenance={}
    if dataset not in SEMANTIC_SCHEMAS:
        for record in Record.objects.filter(dataset=dataset,business_key__in=[r['id'] for r in selected]).select_related('source_row__batch'):
            provenance[record.business_key]={'file':record.source_row.batch.filename,'sheet':record.source_row.sheet,'row':record.source_row.row_number}
    return reply({'total':total,'page':page,'size':30,'scope':scope,'fields':access.permitted_fields(request.user,dataset),
      'rows':[{'values':access.sanitize(request.user,dataset,r),'source':provenance.get(r['id']),
               'references':[ref for ref in r.get('_sources',[]) if access.allowed(request.user,ref['dataset'])]} for r in selected]})

def visible(user,query):return query if access.role(user)=='admin' else query.filter(Q(owner=user.username)|Q(is_public=True))
def model_info(m):return {'id':m.pk,'name':m.name,'dataset':m.dataset,'definition':m.definition,'version':m.version,'owner':m.owner,'is_public':m.is_public}

@api(('GET','POST'))
def analysis_models(request):
    if request.method=='GET':
        permitted=[]
        for m in visible(request.user,AnalysisModel.objects.all()):
            try:validate_definition(request.user,m.dataset,m.definition,allow_inactive=True)
            except ValidationError:continue
            permitted.append(model_info(m))
        return reply(permitted)
    require(access.can_edit(request.user));data=body(request)
    if data.get('id'):return reply({'error':'模型更新需先预演定义、试算和依赖影响，请使用模型变更入口','code':'model_change_preview_required'},409)
    validate_definition(request.user,data['dataset'],data['definition'])
    if data['definition'].get('grouping_ref') and data.get('is_public'):raise ValueError('个人业务分组模型暂只允许私有保存；共享分组尚未开放')
    if not str(data.get('name','')).strip():raise ValueError('请输入模型名称')
    with transaction.atomic():
        m=AnalysisModel(owner=request.user.username);before=None
        m.name=str(data['name'])[:150];m.dataset=data['dataset'];m.definition=data['definition'];m.is_public=bool(data.get('is_public'));m.save()
        AuditEvent.objects.create(action='model.save',actor=request.user.username,object_type='AnalysisModel',object_id=str(m.pk),detail={'before':before,'after':model_info(m)})
    return reply(model_info(m))

@api(('GET','POST'))
def topics(request):
    if request.method=='GET':return reply(list(visible(request.user,Topic.objects.all()).values()))
    require(access.can_edit(request.user));data=body(request);layout=data.get('layout',[])
    if not data.get('name','').strip():raise ValueError('请输入专题名称')
    if not isinstance(layout,list) or len(layout)>12:raise ValueError('一个专题最多12张分析卡片')
    for c in layout:
        m=visible(request.user,AnalysisModel.objects.all()).get(pk=c['model_id']);validate_definition(request.user,m.dataset,m.definition)
        if c.get('span',1) not in [1,2]:raise ValueError('卡片宽度必须为1或2')
    with transaction.atomic():
        if data.get('id'):
            t=Topic.objects.select_for_update().get(pk=data['id']);require(t.owner==request.user.username or access.role(request.user)=='admin')
            if t.version!=data.get('version'):return reply({'error':'专题已更新，请刷新后编辑'},409)
            t.version+=1
        else:t=Topic(owner=request.user.username)
        t.name=data['name'][:150];t.description=data.get('description','')[:2000];t.layout=layout;t.is_public=bool(data.get('is_public'));t.save()
        AuditEvent.objects.create(action='topic.save',actor=request.user.username,object_type='Topic',object_id=str(t.pk),detail={'version':t.version,'layout':layout})
    return reply({'id':t.pk,'version':t.version})

@api(('POST',))
def issue_update(request):
    require(access.role(request.user) in ['admin','analyst','quality','operations'])
    return reply({'error':'旧版处置入口已停用，请打开问题清单重新读取当前范围与版本后登记跟进','code':'issue_followup_requires_receipt'},409)

@api()
def catalog(request):
    path=settings.BASE_DIR/'data/bi_design.json'
    return reply(json.loads(path.read_text()) if path.exists() else {'domains':[],'metrics':[],'roles':[]})

@api(methods=('POST',))
def catalog_design_export(request):
    from .bi_design_drafts import parse_input,build_draft
    if set(request.POST)-{'csrfmiddlewaretoken','draft_input'} or len(request.POST.getlist('draft_input'))!=1:
        raise ValueError('设计导出请求不可用')
    definition=build_draft(json.loads((settings.BASE_DIR/'data/bi_design.json').read_text()),parse_input(request.POST['draft_input']))
    content=json.dumps(definition,ensure_ascii=False,indent=2).encode('utf-8')
    response=FileResponse(io.BytesIO(content),as_attachment=True,filename='BI设计草稿_'+definition['code']+'.json',content_type='application/json; charset=utf-8')
    response['Cache-Control']='no-store'
    return response

@api()
def catalog_document(request):
    path=settings.BASE_DIR/'outputs/BI需求与呈现方案.html'
    if not path.exists():raise Record.DoesNotExist()
    return FileResponse(path.open('rb'),as_attachment=request.path.endswith('/download'),filename=path.name,content_type='text/html; charset=utf-8')

@api()
def audit(request):
    require(access.role(request.user)=='admin');return reply(list(AuditEvent.objects.order_by('-created_at').values()[:100]))

@api()
def source_files(request):
    require(access.can_import(request.user));paths=sorted((settings.BASE_DIR/'outputs').glob('*/*.xlsx'))
    return reply([{'name':p.name,'size':p.stat().st_size} for p in paths])

@api()
def source_download(request,filename):
    require(access.can_import(request.user));paths=list((settings.BASE_DIR/'outputs').glob('*/*.xlsx'));p=next((p for p in paths if p.name==filename),None)
    if not p:raise Record.DoesNotExist()
    return FileResponse(p.open('rb'),as_attachment=True,filename=p.name)
