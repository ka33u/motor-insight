import csv,io,json,re
from django.http import HttpResponse
from django.db import transaction
from .views import api,body,reply
from . import device_transform as engine
from .models import AuditEvent

def response(d):
 r=reply(d);r['Cache-Control']='no-store';return r
def no_query(request,allowed=()):
 if set(request.GET)-set(allowed) or any(len(request.GET.getlist(k))!=1 for k in request.GET):raise ValueError('字段转换查询参数不支持或重复')
@api()
def board(request):no_query(request);return response(engine.board(request.user))
@api(('POST',))
def inspect(request):no_query(request);return response(engine.inspection(request.user,body(request)))
@api(('POST',))
def preview(request):
 no_query(request);d=body(request);engine.strict(d,{'file_id','definition','version_id'})
 if d['version_id'] is not None:
  if d['definition'] is not None:raise ValueError('使用启用模板时不能覆盖其定义')
  _,v=engine.get_version(request.user,d['version_id'],active=True);definition=v.payload['definition']
 else:definition=d['definition']
 p,_=engine.preview(request.user,d['file_id'],definition);return response(p)
@api(('POST',))
def draft(request):no_query(request);return response(engine.draft(request.user,body(request)))
@api(('POST',))
def activate(request,version_id):no_query(request);return response(engine.activate(request.user,version_id,body(request)))
@api(('POST',))
def execute(request):no_query(request);return response(engine.execute(request.user,body(request)))
@api()
def detail(request,receipt_id):no_query(request);return response(engine.detail(request.user,receipt_id))
@api()
@transaction.atomic
def export(request,receipt_id):
 no_query(request,{'receipt'});d=engine.detail(request.user,receipt_id)
 if request.GET.get('receipt')!=d['receipt']:raise ValueError('转换回执、业务来源或原件状态已变化，请重新读取')
 p=d['payload']['preview'];out=io.StringIO();w=csv.writer(out);w.writerow(['私有字段转换回执',d['id'],d['payload_hash']]);w.writerow(['边界',engine.NOTICE]);w.writerow(['范围',p['rows'],p['source_file']['file_hash'],p['output_sha256'],d['payload']['template_code'],d['payload']['version']]);w.writerow(['原件行','结果编号','会话号','SN','原始值','原始单位','标准值','标准单位','逐行转换依据','当前业务依据是否未变'])
 checks={r['session_id']:r['current_target_unchanged'] for r in d['current_targets']}
 for row in p['lineage']:
  v=row['output_values'];values=[row['source_line'],v['measurement_id'],v['session_id'],v['unit_id'],v['raw_value'],v['raw_unit'],v['value'],v['unit'],json.dumps(row['changes'],ensure_ascii=False),checks.get(v['session_id'])]
  w.writerow(["'"+v if isinstance(v,str) and re.match(r'^\s*[=+@\-\t\r]',v) else v for v in values])
 AuditEvent.objects.create(action='device_transform.export',actor=request.user.username,object_type='DeviceTransformReceipt',object_id=str(receipt_id),detail=dict(receipt=d['receipt'],rows=p['rows'],business_facts_changed=False,association_confirmed=False))
 r=HttpResponse('\ufeff'+out.getvalue(),content_type='text/csv; charset=utf-8');r['Content-Disposition']='attachment; filename="device-transform-receipt.csv"';r['Cache-Control']='no-store';return r
