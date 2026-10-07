import hashlib,json
from pathlib import Path
from datetime import date
from django.conf import settings
from django.db import transaction
from . import receipt_flow as eng,analytics,access,supply
from .views import api,reply
from .models import Record,AuditEvent
from .import_review import ReviewConflict
from .trace_cases import capture_sources
from .quality_views import csv_reply

def filters(q):
 if set(q)-{'category','material_id','supplier_id','received_from','received_to','q','stage','page','receipt'}:raise ValueError('来料流程筛选字段无效')
 if hasattr(q,'getlist') and any(len(q.getlist(k))!=1 for k in q):raise ValueError('筛选字段不可重复')
 f={k:q.get(k,'').strip() for k in ['category','material_id','supplier_id','received_from','received_to','q']};f['stage']=q.get('stage','all')
 if f['stage'] not in eng.STAGES or any(len(v)>120 for v in f.values()):raise ValueError('来料流程筛选无效')
 for k in ['received_from','received_to']:
  if f[k] and (date.fromisoformat(f[k]).isoformat()!=f[k] or f[k]>analytics.AS_OF[:10]):raise ValueError('到货日期须为标准日期且不晚于来源截止')
 if f['received_from'] and f['received_to'] and f['received_from']>f['received_to']:raise ValueError('到货起止日期倒序')
 return f
def page(q):
 v=q.get('page','1')
 if not v.isdecimal() or not 1<=int(v)<=100000:raise ValueError('页码无效')
 return int(v)
def receipt(f,rev,user):
 h=hashlib.sha256(json.dumps([f,list(rev),analytics.AS_OF,user.pk,access.role(user)],sort_keys=True,ensure_ascii=False).encode())
 for name in ['receipt_flow.py','receipt_flow_views.py','supply.py','schema.py']:h.update((Path(settings.BASE_DIR)/'app'/name).read_bytes())
 return h.hexdigest()
def respond(v):
 r=reply(v);r['Cache-Control']='no-store';return r
def context(request,required=False):
 f=filters(request.GET);page(request.GET);rev=analytics.revision();d=eng.ReceiptFlow();stamp=receipt(f,rev,request.user)
 for k in ['category','material_id','supplier_id']:
  if f[k] and f[k] not in {r[k] for r in d.rows}:raise ValueError('类别、物料或供应商不在到货范围')
 supplied=request.GET.get('receipt')
 if required and not supplied:raise ValueError('请先读取来料流程范围')
 if supplied and supplied!=stamp:raise ReviewConflict('来料范围、来源、规则或账号已变化，请重新读取')
 if list(rev)!=list(analytics.revision()):raise ReviewConflict('读取期间来源变化，请重试')
 cohort=d.cohort(f);rows=sorted([r for r in cohort if f['stage'] in r['flags']],key=lambda r:(r['state']=='complete',not bool(r['issues']),not bool(r['work_issues']),-(r['open_observation_hours'] or 0),r['id']))
 return d,f,stamp,cohort,rows
def selected(rows,key):
 r=next((r for r in rows if r['id']==key),None)
 if not r:raise Record.DoesNotExist()
 return r

@api()
@transaction.atomic
def board(request):
 d,f,stamp,cohort,rows=context(request);p=page(request.GET)
 return respond({'filters':f,'summary':eng.summary(cohort),'groups':[{'category':key,**eng.summary(rr)} for key,rr in sorted(supply.group(cohort,'category').items())],'rows':[eng.brief(r) for r in rows[(p-1)*25:p*25]],'total':len(rows),'page':p,'size':25,'facets':{k:sum(k in r['flags'] for r in cohort) for k in eng.STAGES},'stages':eng.STAGES,'options':{'categories':sorted({r['category'] for r in d.rows}),'materials':sorted({r['material_id']:r['material'] for r in d.rows}.items()),'suppliers':sorted({r['supplier_id']:r['supplier'] for r in d.rows}.items())},'receipt':stamp,'as_of':d.cutoff,'note':eng.NOTE,'boundary':eng.BOUNDARY,'global_issues':d.global_issues,'quantile_method':'每个已完成到货批次等权，按(n−1)×P线性插值；未闭合观察时长不进入完成分布。'})

@api()
@transaction.atomic
def detail(request,key):
 d,f,stamp,cohort,rows=context(request,True);r=selected(rows,key)
 return respond({**r,'receipt':stamp,'filters':f,'as_of':d.cutoff,'note':eng.NOTE,'boundary':eng.BOUNDARY})

@api()
@transaction.atomic
def evidence(request,key):
 d,f,stamp,cohort,rows=context(request,True);r=selected(rows,key);p=page(request.GET);sources=capture_sources({'sources':[x for x in r['sources'] if access.allowed(request.user,x['dataset'])]})
 return respond({'rows':sources[(p-1)*40:p*40],'total':len(sources),'page':p,'size':40,'receipt':stamp,'can_download_original':access.can_import(request.user)})

FIELDS=[('id','到货单'),('purchase_line_id','采购行'),('material_id','物料'),('supplier_id','供应商'),('lot','批次'),('unit','单位'),('received','到货时间'),('qty','批次实收量'),('state_label','当前节点状态'),('first_inspected','首次检验登记'),('full_stock_at','整批入库完成'),('inspection_hours','到货至首检登记小时'),('stock_hours','到货至整批入库小时'),('observation_from','未闭合观察起点'),('open_observation_hours','未闭合观察小时'),('putaway_qty','实际入库量'),('unposted_qty','实收未入库量')]
PARTS=['total_hours','before_start_hours','work_hours','gap_hours']
PART_LABELS=['总历时','窗口前历时','作业段并集历时','窗口内未覆盖历时']

@api()
@transaction.atomic
def export(request):
 d,f,stamp,cohort,rows=context(request,True)
 out=[['来料节点与历时 · 合成模拟数据','范围',json.dumps(f,ensure_ascii=False),'来源截止',d.cutoff],['计算依据',stamp],['说明',eng.NOTE],['边界',eng.BOUNDARY],[label for _,label in FIELDS]+[prefix+label+'小时' for prefix in ['首检分解：','入库分解：'] for label in PART_LABELS]+['实物核对','作业登记核对']]
 out += [[r.get(k) for k,_ in FIELDS]+[r[part][k] if r[part]['known'] else None for part in ['inspection_decomposition','putaway_decomposition'] for k in PARTS]+['；'.join(r['issues']),'；'.join(r['work_issues'])] for r in rows]
 AuditEvent.objects.create(action='receipt_flow.export',actor=request.user.username,object_type='ReceiptFlow',object_id=f['material_id'] or 'all',detail={'filters':f,'receipt':stamp,'rows':len(rows),'business_facts_changed':False})
 return csv_reply(out,'receipt-flow')

@api()
@transaction.atomic
def export_jobs(request):
 d,f,stamp,cohort,rows=context(request,True)
 fields=['id','job_id','version','status','assigned','started','finished','inspection_id','movement_id','registered','owner_id','station']
 out=[['当前来料作业版本 · 合成模拟数据','范围',json.dumps(f,ensure_ascii=False),'来源截止',d.cutoff],['计算依据',stamp],['说明',eng.NOTE],['边界',eng.BOUNDARY],['到货单','作业号','环节','有效']+fields+['完整窗口小时','未结束观察小时','作业核对']];count=0
 for r in rows:
  for j in r['jobs']:
   if j['created']>d.cutoff:continue
   v=j['selected'] or {};out.append([r['id'],j['id'],j['stage'],j['valid']]+[v.get(k) for k in fields]+[j['work_hours'],j['open_work_hours'],'；'.join(j['issues'])]);count+=1
 AuditEvent.objects.create(action='receipt_flow.jobs_export',actor=request.user.username,object_type='ReceiptFlow',object_id=f['material_id'] or 'all',detail={'filters':f,'receipt':stamp,'rows':count,'business_facts_changed':False})
 return csv_reply(out,'receipt-flow-jobs')
