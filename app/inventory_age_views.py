import hashlib,json
from pathlib import Path
from django.conf import settings
from django.db import transaction
from . import inventory_age as eng,analytics,access
from .views import api,reply
from .import_review import ReviewConflict
from .models import AuditEvent
from .trace_cases import capture_sources
from .quality_views import csv_reply

def filters(q):
 if set(q)-{'category','material_id','unit','stage','q','order','page','receipt'}:raise ValueError('库龄筛选字段无效')
 if hasattr(q,'getlist') and any(len(q.getlist(k))!=1 for k in q):raise ValueError('筛选字段不可重复')
 f={k:q.get(k,'').strip() for k in ['category','material_id','unit','q']};f.update(stage=q.get('stage','all'),order=q.get('order','fifo'))
 if f['stage'] not in eng.STAGES or f['order'] not in ['fifo','fefo'] or any(len(v)>120 for v in f.values()):raise ValueError('库龄筛选无效')
 return f
def page(q):
 p=q.get('page','1')
 if not p.isdecimal() or not 1<=int(p)<=100000:raise ValueError('页码无效')
 return int(p)
def receipt(f,rev,user):
 h=hashlib.sha256(json.dumps([f,list(rev),analytics.AS_OF,user.pk,access.role(user)],sort_keys=True,ensure_ascii=False).encode())
 for name in ['inventory_age.py','inventory_age_views.py','supply.py','schema.py']:h.update((Path(settings.BASE_DIR)/'app'/name).read_bytes())
 return h.hexdigest()
def respond(value):
 r=reply(value);r['Cache-Control']='no-store';return r
def context(request,required=False):
 f=filters(request.GET);page(request.GET);rev=analytics.revision();d=eng.InventoryAge(order=f['order']);stamp=receipt(f,rev,request.user)
 for field in ['category','material_id','unit']:
  if f[field] and f[field] not in {r[field] for r in d.rows}:raise ValueError('物料、类别或单位不在当前库存范围内')
 supplied=request.GET.get('receipt')
 if required and not supplied:raise ValueError('请先查看库龄范围')
 if supplied and supplied!=stamp:raise ReviewConflict('库龄范围、账号、数据或规则已变化，请重新读取')
 if list(rev)!=list(analytics.revision()):raise ReviewConflict('读取期间来源发生变化，请重试')
 return d,f,stamp
def brief(r):return {k:v for k,v in r.items() if k not in ['date_history','policy_history','sources','ledger_timeline']}

@api()
@transaction.atomic
def board(request):
 d,f,stamp=context(request);rows=d.selected(f);p=page(request.GET)
 return respond({'filters':f,'summary':eng.summary(rows),'rows':[brief(r) for r in rows[(p-1)*25:p*25]],'total':len(rows),'page':p,'size':25,'stages':eng.STAGES,'materials':sorted({r['material_id']:r['material'] for r in d.rows}.items()),'categories':sorted({r['category'] for r in d.rows}),'units':sorted({r['unit'] for r in d.rows}),'receipt':stamp,'as_of':d.cutoff,'note':eng.NOTE,'boundary':eng.BOUNDARY,'global_issues':d.global_issues})

@api()
@transaction.atomic
def detail(request,key):
 d,f,stamp=context(request,True);return respond({**d.detail(key,f),'receipt':stamp,'filters':f,'as_of':d.cutoff,'note':eng.NOTE,'boundary':eng.BOUNDARY})

@api()
@transaction.atomic
def evidence(request,key):
 d,f,stamp=context(request,True);r=d.detail(key,f);p=page(request.GET);rows=capture_sources({'sources':[r for r in r['sources'] if access.allowed(request.user,r['dataset'])]})
 return respond({'rows':rows[(p-1)*40:p*40],'total':len(rows),'page':p,'size':40,'receipt':stamp,'can_download_original':access.can_import(request.user)})

FIELDS=[('material_id','物料编码'),('material','物料名称'),('lot','批次'),('location','库位'),('unit','单位'),('balance_qty','账面余额'),('quantity_valid','余额有效'),('state','库存状态'),('first_stock_date','首次入库登记'),('age_days','库龄天数'),('age_bucket','库龄区间'),('age_limit_days','超龄阈值天'),('overage','超龄候选'),('manufactured','制造日期'),('expires','有效截至'),('expiry_days','距有效截至天'),('expiry_state','有效期状态'),('last_outbound','已导入最近出库'),('observed_from','已导入观察起点'),('date_profile_id','日期登记依据'),('date_version','日期版本'),('policy_id','规则依据'),('policy_version','规则版本'),('reference_order','参考排序方式'),('reference_rank','同物料参考位次')]

@api()
@transaction.atomic
def export(request):
 d,f,stamp=context(request,True);rows=d.selected(f)
 out=[['库存库龄与有效期 · 合成模拟数据','范围',json.dumps(f,ensure_ascii=False),'来源截止',d.cutoff],['计算依据',stamp],['说明',eng.NOTE],['边界',eng.BOUNDARY],[label for _,label in FIELDS]+['核对事项']]
 out += [[r.get(k) for k,_ in FIELDS]+['；'.join(r['issues'])] for r in rows]
 AuditEvent.objects.create(action='inventory_age.export',actor=request.user.username,object_type='InventoryAge',object_id=f['material_id'] or 'all',detail={'filters':f,'receipt':stamp,'rows':len(rows),'business_facts_changed':False})
 return csv_reply(out,'inventory-age')
