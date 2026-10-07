import csv,io,json,re
from django.http import HttpResponse
from django.db import transaction
from . import device_collector as collector
from .models import AuditEvent
from .views import api,body,reply
def response(data):
 r=reply(data);r['Cache-Control']='no-store';return r
def no_query(request,extra=()):
 if set(request.GET)-set(extra) or any(len(request.GET.getlist(k))!=1 for k in request.GET):raise ValueError('采集查询参数不支持或重复')
@api()
def board(request):no_query(request);return response(collector.board(request.user))
@api(('POST',))
def preview(request):no_query(request);return response(collector.sampling(request.user,body(request)))
@api(('POST',))
def create(request):no_query(request);return response(collector.create(request.user,body(request)))
@api()
def detail(request,run_id):no_query(request);return response(collector.detail(request.user,run_id))
@api(('POST',))
def collect(request,run_id):no_query(request);return response(collector.collect(request.user,run_id,body(request)))
@api()
@transaction.atomic
def export(request,run_id):
 no_query(request,{'receipt'});d=collector.detail(request.user,run_id)
 if request.GET.get('receipt')!=d['receipt']:raise ValueError('采集回执或原件状态已变化，请重新读取后导出')
 stream=io.StringIO();writer=csv.writer(stream);writer.writerow(['本地模拟采集回执',str(run_id),d['manifest_hash']]);writer.writerow(['边界',collector.NOTICE]);writer.writerow(['结果统计',json.dumps(d['summary'],ensure_ascii=False)]);writer.writerow(['文件相对路径','声明稳定SHA256','稳定字节数','最新历史采集结果','回执版本','原件标识','当前原件完整性','最新操作时间','说明'])
 for r in d['rows']:
  p=r['latest'] or {};a=r['archive'] or {};values=[r['item']['path'],r['item']['sha256'],r['item']['size'],r['state_label'],r['version'],a.get('id'),a.get('current_integrity'),p.get('finished_at'),p.get('reason')]
  writer.writerow(["'"+v if isinstance(v,str) and re.match(r'^\s*[=+@\-\t\r]',v) else '' if v is None else v for v in values])
 AuditEvent.objects.create(action='device_collection.export',actor=request.user.username,object_type='DeviceCollectionRun',object_id=str(run_id),detail=dict(receipt=d['receipt'],summary=d['summary'],items=len(d['rows']),local_simulation=True,business_facts_changed=False))
 r=HttpResponse('\ufeff'+stream.getvalue(),content_type='text/csv; charset=utf-8');r['Content-Disposition']='attachment; filename="local-device-collection.csv"';r['Cache-Control']='no-store';return r
