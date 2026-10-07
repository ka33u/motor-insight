import csv,io,json,re
from urllib.parse import quote
from django.db import transaction
from django.http import HttpResponse
from . import bi_field_catalog as fields
from .models import AuditEvent
from .views import api,reply

def params(request,extras):
 allowed={'dataset','q','kind','unit_state'}|set(extras)
 if set(request.GET)-allowed or any(len(request.GET.getlist(k))!=1 for k in request.GET):raise ValueError('字段查询参数不支持或重复')
 return {k:request.GET[k] for k in request.GET if k not in extras}

@api()
def board(request):
 conf=params(request,{'page'});value=request.GET.get('page','1')
 if not re.fullmatch(r'[1-9][0-9]{0,5}',value):raise ValueError('字段页码无效')
 return reply(fields.board(request.user,conf,int(value)))

@api()
@transaction.atomic
def export(request):
 conf=params(request,{'receipt','format'});fmt=request.GET.get('format','csv')
 if fmt not in ('csv','json') or not request.GET.get('receipt'):raise ValueError('导出须指定当前查询凭据及csv或json格式')
 d=fields.export_data(request.user,conf,request.GET['receipt'])
 if fmt=='json':r=HttpResponse(json.dumps(d,ensure_ascii=False,indent=2),content_type='application/json; charset=utf-8')
 else:
  stream=io.StringIO();writer=csv.writer(stream);writer.writerow(['BI字段契约','仅文档',fields.REVISION]);writer.writerow(['边界',fields.NOTICE]);writer.writerow(['筛选',json.dumps(d['filters'],ensure_ascii=False)])
  writer.writerow(['数据集','数据集编码','部门来源','来源粒度','字段','字段编码','类型','必填','主键','关联目标','单位状态','单位','单位字段','单位依据','派生公式支持','日期口径','缺失规则','汇总边界','编码规则'])
  for f in d['rows']:
   u=f['unit_info'];values=[f['dataset_label'],f['dataset'],f['department'],f['grain'],f['label'],f['name'],f['type_label'],f['required'],f['primary_key'],f['reference'],u['kind'],u['unit'],u['unit_field'],u['basis'],u['formula_supported'],f['date_contract']['date_label'],f['missing_rule'],f['aggregation_note'],f['identity_rule']]
   writer.writerow(["'"+v if isinstance(v,str) and re.match(r'^\s*[=+@\-\t\r]',v) else '' if v is None else v for v in values])
  r=HttpResponse('\ufeff'+stream.getvalue(),content_type='text/csv; charset=utf-8')
 AuditEvent.objects.create(action='bi_field_catalog.export',actor=request.user.username,object_type='BIFieldDocumentation',object_id=fields.REVISION,detail=dict(filters=d['filters'],receipt=d['receipt'],fields=d['total'],contains_business_values=False,business_facts_changed=False))
 r['Content-Disposition']="attachment; filename*=UTF-8''"+quote('BI字段契约说明.'+fmt);r['Cache-Control']='no-store';return r
