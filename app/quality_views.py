import csv,io,json
from datetime import date
from django.db import transaction
from django.http import HttpResponse
from django.utils import timezone
from . import access,analytics,quality_board as quality
from .models import IssueDisposition,AuditEvent
from .trace_cases import capture_sources
from .delivery_views import follow_info
from .views import api,reply,body,require

STATUSES=['待处理','排查中','待复测','待质量复核','演练已核验']
def can_follow(user):return access.role(user) in ['admin','quality','operations','analyst']
def context(request,extra=()):
    f=quality.filters(request.GET,extra);data=quality.current();return data,f,quality.cohort(data.rows,f)
def selected_distribution(request):
    data,f,rows=context(request,['spec_id','sample','equipment_id','bin'])
    d=quality.distribution(data,rows,f['product_id'],request.GET.get('spec_id',''),request.GET.get('sample','first_complete'),request.GET.get('equipment_id',''))
    selected=request.GET.get('bin','');chosen=d['observations']
    if selected!='':
        selected=int(selected)
        if selected not in [b['index'] for b in d['bins']]:raise ValueError('分布区间已变化，请重新选择')
        chosen=[r for r in chosen if r['bin']==selected]
    return d,chosen,f,selected

@api()
def board(request):
    data,f,rows=context(request);chosen=quality.selected(rows,f['stage'],f['test_code'],f['item_state']);page=max(1,int(request.GET.get('page','1')));items=chosen[(page-1)*25:page*25]
    notes={n.key:n for n in IssueDisposition.objects.filter(key__in=['quality:'+r['id'] for r in items])}
    specs=[s for s in data.specs.values() if f['product_id'] and s['product_id']==f['product_id']]
    names={s.get('test_code',s['id']):s.get('test_name',s['id']) for s in data.specs.values()};defects=quality.defects(rows)
    devices=[]
    if f['product_id']:
        grouped={}
        for r in rows:
            first=data.session_index.get(r['first_complete_session'])
            if first:grouped.setdefault((first.get('equipment_id','未记录'),first['spec_version']),[]).append(r)
        devices=[{'equipment_id':k[0],'spec_version':k[1],**quality.summary(rr)} for k,rr in sorted(grouped.items())]
    return reply({'filters':f,'summary':quality.summary(rows),'facets':{k:len(quality.selected(rows,k)) for k in quality.STAGES},'rows':[{**quality.public(r),'follow_up':follow_info(notes.get('quality:'+r['id']))} for r in items],'total':len(chosen),'page':page,'size':25,'stages':quality.STAGES,'daily':[{**r,'day':r.pop('assembly_day')} for r in quality.aggregate([{**r,'assembly_day':r['assembly_at'][:10]} for r in rows],'assembly_day')],'defects':[{**r,'test_name':names.get(r['test_code'],r['test_code'])} for r in defects],'devices':devices,'test_columns':[{'code':k,'name':v} for k,v in sorted(names.items())],'options':{'families':sorted({r['family'] for r in data.rows}),'products':[{'id':p['id'],'label':p['id']+' · '+p.get('model',''),'family':p.get('family')} for p in data.products.values()],'specs':sorted(specs,key=lambda s:(s['version'],s.get('test_code',s['id'])))},'as_of':analytics.AS_OF,'data_revision':list(analytics.revision()),'note':quality.NOTE,'can_follow_up':can_follow(request.user),'can_verify':access.role(request.user) in ['admin','quality']})

@api()
def detail(request,unit_id):
    d=quality.current().detail(unit_id);d['follow_up']=follow_info(IssueDisposition.objects.filter(key='quality:'+unit_id).first());d['data_revision']=list(analytics.revision());d['can_follow_up']=can_follow(request.user);d['can_verify']=access.role(request.user) in ['admin','quality'];return reply(d)

@api()
def evidence(request,unit_id):
    d=quality.current().detail(unit_id);rows=capture_sources(d);page=max(1,int(request.GET.get('page','1')))
    return reply({'rows':rows[(page-1)*40:page*40],'total':len(rows),'page':page,'size':40,'can_download_original':access.can_import(request.user)})

@api()
def distribution(request):
    d,chosen,f,selected=selected_distribution(request);page=max(1,int(request.GET.get('page','1')))
    return reply({**{k:v for k,v in d.items() if k!='observations'},'rows':chosen[(page-1)*30:page*30],'total':len(chosen),'page':page,'size':30,'selected_bin':selected,'filters':f,'as_of':analytics.AS_OF})

@api(('POST',))
def follow_up(request,unit_id):
    require(can_follow(request.user));unit=quality.current().unit_index.get(unit_id)
    if unit is None:from .models import Record;raise Record.DoesNotExist()
    payload=body(request)
    if set(payload)!={'version','status','owner','note','due_date','data_revision'}:raise ValueError('协调字段不完整或包含不可编辑字段')
    if payload['status'] not in STATUSES:raise ValueError('协调状态不可用')
    if payload['status']=='演练已核验':require(access.role(request.user) in ['admin','quality'],'模拟核验由质量岗位或管理员确认')
    if type(payload['version']) is not int or payload['version']<0:raise ValueError('请提供当前协调版本')
    for field,limit in [('owner',150),('note',2000)]:
        if not isinstance(payload[field],str) or not 1<=len(payload[field].strip())<=limit:raise ValueError('请填写有效负责人和说明')
    if len(payload['note'].strip())<5:raise ValueError('说明至少5字')
    due=payload['due_date'] or None
    if due and (not isinstance(due,str) or date.fromisoformat(due).isoformat()!=due):raise ValueError('期限格式应为YYYY-MM-DD')
    with transaction.atomic():
        if payload['data_revision']!=list(analytics.revision()):return reply({'error':'检测来源已变化，请重新读取后跟进'},409)
        item=IssueDisposition.objects.select_for_update().filter(key='quality:'+unit_id).first();before=follow_info(item)
        if before['version']!=payload['version']:return reply({'error':'协调记录已更新，请重新读取'},409)
        changed={'status':payload['status'],'owner':payload['owner'].strip(),'note':payload['note'].strip(),'due_date':due,'version':before['version']+1,'updated_by':request.user.username,'updated_at':timezone.now()}
        if item:
            if IssueDisposition.objects.filter(pk=item.pk,version=payload['version']).update(**changed)!=1:return reply({'error':'协调版本已变化，请重新读取'},409)
            item.refresh_from_db()
        else:item=IssueDisposition.objects.create(key='quality:'+unit_id,**changed)
        serial=lambda v:json.loads(json.dumps(v,ensure_ascii=False,default=str))
        AuditEvent.objects.create(action='quality.followup',actor=request.user.username,object_type='QualityUnit',object_id=unit_id,detail={'before':serial(before),'after':serial(follow_info(item)),'latest_session':unit['latest_session'],'data_revision':payload['data_revision'],'business_facts_changed':False})
    return reply({'follow_up':follow_info(item),'notice':'已保存模拟协调记录；检测、质量放行和不合格单事实保持不变。'})

@api()
def history(request,unit_id):
    quality.current().detail(unit_id)
    return reply({'rows':list(AuditEvent.objects.filter(object_type='QualityUnit',object_id=unit_id).order_by('-id').values('actor','action','detail','created_at'))})

def csv_reply(rows,name):
    out=io.StringIO();writer=csv.writer(out)
    for row in rows:writer.writerow(["'"+v if isinstance(v,str) and v.startswith(('=','+','-','@','\t','\r')) else v for v in row])
    response=HttpResponse('\ufeff'+out.getvalue(),content_type='text/csv; charset=utf-8');response['Content-Disposition']='attachment; filename="'+name+'.csv"';return response

@api()
def export(request):
    _,f,rows=context(request);chosen=quality.selected(rows,f['stage'],f['test_code'],f['item_state'])
    data=[['模拟质量工作台','截止',analytics.AS_OF,'筛选',json.dumps(f,ensure_ascii=False)],['定义',quality.NOTE],['SN','配置','工单','装配时间','首次检测','首次完整检测','最新有效检测','有效会话数','作废会话数','放行关系满足检查','已发货','待核对事项']]
    data.extend([[r['id'],r['product_id'],r['work_order_id'],r['assembly_at'],r['first_result'],r['first_complete_result'],r['latest_result'],r['session_count'],r['voided_count'],'是' if r['release_valid'] else '待核验','是' if r['shipped'] else '否','；'.join(r['issues'])] for r in chosen])
    AuditEvent.objects.create(action='quality.export',actor=request.user.username,object_type='QualityBoard',object_id='cohort',detail={'filters':f,'rows':len(chosen)})
    return csv_reply(data,'quality-cohort')

@api()
def distribution_export(request):
    d,chosen,f,selected=selected_distribution(request)
    data=[['模拟同配置分布','截止',analytics.AS_OF,'筛选',json.dumps(f,ensure_ascii=False)],['项目',d['spec']['id'],'样本口径',d['sample_label'],'设备',d['equipment_id'],'区间',selected],['说明',d['notice']],['样本规则',d['sample_note']],['SN','会话号','项目结果号','规范项目号','检测时间','检测设备','环境温度℃','标准数值','单位','项目判定']]
    data.extend([[r[k] for k in ['unit_id','session_id','id','spec_id','tested','equipment_id','temperature_c','value','unit','result']] for r in chosen])
    AuditEvent.objects.create(action='quality.distribution_export',actor=request.user.username,object_type='QualityBoard',object_id=d['spec']['id'],detail={'filters':f,'sample':d['sample'],'equipment':d['equipment_id'],'bin':selected,'rows':len(chosen)})
    return csv_reply(data,'quality-distribution')
