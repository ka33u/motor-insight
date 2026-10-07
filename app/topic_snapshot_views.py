import csv,io,json,re
from urllib.parse import quote
from django.http import HttpResponse
from .views import api,reply,body
from . import topic_snapshots as snapshots

@api(('GET','POST'))
def collection(request,topic_id):
    if request.method=='GET':return reply(snapshots.listing(request.user,topic_id,int(request.GET.get('page',1))))
    return reply(snapshots.info(snapshots.create(request.user,topic_id,body(request))))

@api()
def detail(request,topic_id,snapshot_id):return reply(snapshots.detail(request.user,topic_id,snapshot_id))

@api(('POST',))
def evidence(request,topic_id,snapshot_id):return reply(snapshots.evidence(request.user,topic_id,snapshot_id,body(request)))

@api(('POST',))
def sources(request,topic_id,snapshot_id):return reply(snapshots.source_evidence(request.user,topic_id,snapshot_id,body(request)))

@api(('POST',))
def compare(request,topic_id,snapshot_id):return reply(snapshots.compare_current(request.user,topic_id,snapshot_id))

@api()
def export(request,topic_id,snapshot_id):
    s=snapshots.get(request.user,topic_id,snapshot_id)
    if request.GET.get('format')=='json':
        response=HttpResponse(json.dumps({**snapshots.info(s),'payload':s.payload},ensure_ascii=False,default=str,indent=2),content_type='application/json; charset=utf-8');suffix='json'
    else:
        stream=io.StringIO();w=csv.writer(stream)
        def safe(v):return "'"+v if isinstance(v,str) and re.match(r'^[\s]*[=+@\-\t\r]',v) else '' if v is None else v
        for row in snapshots.export_rows(s):w.writerow([safe(v) for v in row])
        response=HttpResponse('\ufeff'+stream.getvalue(),content_type='text/csv; charset=utf-8');suffix='csv'
    response['Content-Disposition']="attachment; filename*=UTF-8''"+quote(f'BI结果快照-{s.pk}.{suffix}')
    response['Cache-Control']='no-store';return response
