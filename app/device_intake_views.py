import csv,io,json,re
from django.http import HttpResponse
from django.db import transaction
from . import device_intake as intake
from .models import AuditEvent
from .views import api,reply

def response(data):
 r=reply(data);r['Cache-Control']='no-store';return r
@api()
def board(request):return response(intake.Workspace(request.user,request.GET).board(intake.page(request.GET)))
@api()
def detail(request,key):
 d=intake.Workspace(request.user,request.GET);d.check(request.GET.get('receipt'));return response(d.detail(key))
@api()
@transaction.atomic
def export(request):
 d=intake.Workspace(request.user,request.GET);d.check(request.GET.get('receipt'));rows=d.selected();stream=io.StringIO();writer=csv.writer(stream)
 writer.writerow(['设备文件发现清单',intake.REVISION,'清单截止',d.filters['as_of']]);writer.writerow(['边界',intake.NOTICE]);writer.writerow(['筛选与统计',json.dumps(dict(filters=d.filters,summary=d.summary(rows)),ensure_ascii=False)])
 writer.writerow(['发现记录','设备来源','扫描批次','设备','相对路径','文件名','声明字节数','声明SHA256','声明修改时间','发现登记时间','读取状态','采集核对状态','扫描状态','同内容发现数','会话线索','SN线索','待核对说明','本人匹配归档数','来源Excel','来源工作表','来源行号'])
 for r in rows:
  values=[r['key'],r['source_id'],r['scan_id'],r['equipment_id'],r['relative_path'],r['filename'],r['size_bytes'],r['sha256'],r['modified'],r['discovered'],r['read_state'],r['state_label'],r['scan_state_label'],r['same_content_observations'],r['session_hint'],r['unit_hint'],'；'.join(r['issues']),len(r['archives']),r['provenance']['filename'],r['provenance']['sheet'],r['provenance']['row']]
  writer.writerow(["'"+v if isinstance(v,str) and re.match(r'^\s*[=+@\-\t\r]',v) else '' if v is None else v for v in values])
 AuditEvent.objects.create(action='device_intake.export',actor=request.user.username,object_type='DeviceDiscoveryScope',object_id=intake.REVISION,detail=dict(filters=d.filters,receipt=d.receipt,summary=d.summary(rows),synthetic=True,business_facts_changed=False,live_collection=False))
 r=HttpResponse('\ufeff'+stream.getvalue(),content_type='text/csv; charset=utf-8');r['Content-Disposition']='attachment; filename="device-discovery.csv"';r['Cache-Control']='no-store';return r
