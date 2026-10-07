"""Read-only BI scope for original and current procurement promises."""
import hashlib,json
from pathlib import Path
from django.conf import settings
from django.db import transaction
from . import purchase_commitments as eng,analytics,access,supply
from .views import api,reply
from .import_review import ReviewConflict
from .models import AuditEvent,Record
from .trace_cases import capture_sources
from .quality_views import csv_reply

def filters(q):
 if set(q)-{'category','material_id','supplier_id','stage','q','page','receipt'}:raise ValueError('承诺筛选字段无效')
 if hasattr(q,'getlist') and any(len(q.getlist(k))!=1 for k in q):raise ValueError('筛选字段不可重复')
 f={k:q.get(k,'').strip() for k in ['category','material_id','supplier_id','q']};f['stage']=q.get('stage','all')
 if f['stage'] not in eng.STAGES or any(len(v)>120 for v in f.values()):raise ValueError('承诺筛选无效')
 return f
def page(q):
 p=q.get('page','1')
 if not p.isdecimal() or not 1<=int(p)<=100000:raise ValueError('页码无效')
 return int(p)
def receipt(f,rev,user):
 h=hashlib.sha256(json.dumps([f,list(rev),analytics.AS_OF,user.pk,access.role(user)],sort_keys=True,ensure_ascii=False).encode())
 for name in ['purchase_commitments.py','purchase_commitment_views.py','supply.py','schema.py']:h.update((Path(settings.BASE_DIR)/'app'/name).read_bytes())
 return h.hexdigest()
def respond(v):
 r=reply(v);r['Cache-Control']='no-store';return r
def context(request,required=False):
 f=filters(request.GET);page(request.GET);rev=analytics.revision();d=eng.Commitments();stamp=receipt(f,rev,request.user)
 for k in ['category','material_id','supplier_id']:
  if f[k] and f[k] not in {r[k] for r in d.rows}:raise ValueError('物料、类别或供应商不在当前采购范围')
 supplied=request.GET.get('receipt')
 if required and not supplied:raise ValueError('请先查看采购承诺范围')
 if supplied and supplied!=stamp:raise ReviewConflict('采购范围、账号、来源或规则已变化，请重新读取')
 if list(rev)!=list(analytics.revision()):raise ReviewConflict('读取期间来源发生变化，请重试')
 cohort=d.cohort(f);rows=sorted([r for r in cohort if f['stage'] in r['flags']],key=lambda r:(not bool(r['issues']),not ('overdue' in r['flags']),r['id']))
 return d,f,stamp,cohort,rows
def selected(rows,key):
 r=next((r for r in rows if r['id']==key),None)
 if not r:raise Record.DoesNotExist()
 return r

@api()
@transaction.atomic
def board(request):
 d,f,stamp,cohort,rows=context(request);p=page(request.GET)
 groups=supply.group(cohort,'supplier_id')
 return respond({'filters':f,'summary':eng.summary(cohort),'unit_totals':eng.unit_totals(cohort),'stages':eng.STAGES,'facets':{k:sum(k in r['flags'] for r in cohort) for k in eng.STAGES},'rows':[eng.brief(r) for r in rows[(p-1)*25:p*25]],'total':len(rows),'page':p,'size':25,'suppliers':[{'id':key,'name':rr[0]['supplier'],**eng.summary(rr)} for key,rr in sorted(groups.items())],'options':{'categories':sorted({r['category'] for r in d.rows}),'materials':sorted({r['material_id']:r['material'] for r in d.rows}.items()),'suppliers':sorted({r['supplier_id']:r['supplier'] for r in d.rows}.items())},'receipt':stamp,'as_of':d.cutoff,'note':eng.NOTE,'boundary':eng.BOUNDARY,'global_issues':d.global_issues})

@api()
@transaction.atomic
def detail(request,key):
 d,f,stamp,cohort,rows=context(request,True);r=selected(rows,key)
 return respond({**r,'receipts':d.supply.detail('purchase',key)['receipts'],'receipt':stamp,'filters':f,'as_of':d.cutoff,'note':eng.NOTE,'boundary':eng.BOUNDARY})

@api()
@transaction.atomic
def evidence(request,key):
 d,f,stamp,cohort,rows=context(request,True);r=selected(rows,key);p=page(request.GET)
 sources=capture_sources({'sources':[x for x in r['sources'] if access.allowed(request.user,x['dataset'])]})
 return respond({'rows':sources[(p-1)*40:p*40],'total':len(sources),'page':p,'size':40,'receipt':stamp,'can_download_original':access.can_import(request.user)})

FIELDS=[('id','采购行'),('material_id','物料'),('supplier_id','供应商'),('unit','单位'),('qty','采购数量'),('original_due','原承诺到货日'),('original_due_sample','原承诺到期分母'),('original_on_time_full','原承诺按期足量分子'),('version_id','当前选中版本'),('version','版本号'),('valid','当前承诺有效'),('first_due','当前首段承诺日'),('last_due','当前末段承诺日'),('changed','承诺变更'),('late_change','原逾期后改期'),('received_qty','实到'),('approved_qty','检验批准'),('putaway_qty','实际入库'),('remaining_qty','未到'),('overdue_unreceived','已知当前分段逾期未到')]
SEGMENTS=[('id','分段号'),('sequence','段次'),('due','当前分段承诺日'),('qty','分段数量'),('arrived_qty','分析分配到货量'),('on_time_qty','承诺日内分析分配量'),('remaining_qty','未到'),('due_sample','已到期分母'),('on_time_full','按期足量分子'),('overdue_unreceived','逾期未到')]

@api()
@transaction.atomic
def export(request):
 d,f,stamp,cohort,rows=context(request,True)
 out=[['采购承诺与履约 · 合成模拟数据','范围',json.dumps(f,ensure_ascii=False),'来源截止',d.cutoff],['计算依据',stamp],['说明',eng.NOTE],['边界',eng.BOUNDARY],[label for _,label in FIELDS]+['核对事项']]
 out += [[r.get(k) for k,_ in FIELDS]+['；'.join(r['issues'])] for r in rows]
 AuditEvent.objects.create(action='purchase_commitments.export',actor=request.user.username,object_type='PurchaseCommitments',object_id=f['supplier_id'] or 'all',detail={'filters':f,'receipt':stamp,'rows':len(rows),'business_facts_changed':False})
 return csv_reply(out,'purchase-commitments')

@api()
@transaction.atomic
def export_segments(request):
 d,f,stamp,cohort,rows=context(request,True)
 out=[['当前分段承诺 · 合成模拟数据','范围',json.dumps(f,ensure_ascii=False),'来源截止',d.cutoff],['计算依据',stamp],['说明',eng.NOTE],['边界',eng.BOUNDARY],['采购行','单位','当前版本','承诺有效']+[label for _,label in SEGMENTS]+['核对事项']]
 count=0
 for r in rows:
  segments=r['segments'] if r['valid'] else [{}]
  for s in segments:
   out.append([r['id'],r['unit'],r['version_id'],r['valid']]+[s.get(k) for k,_ in SEGMENTS]+['；'.join(r['issues'])]);count+=1
 AuditEvent.objects.create(action='purchase_commitments.segments_export',actor=request.user.username,object_type='PurchaseCommitments',object_id=f['supplier_id'] or 'all',detail={'filters':f,'receipt':stamp,'rows':count,'objects':len(rows),'business_facts_changed':False})
 return csv_reply(out,'purchase-commitment-segments')
