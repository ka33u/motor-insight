import csv,io,json
from urllib.parse import quote
from django.http import HttpResponse
from django.db import transaction
from .views import api,reply as base_reply,body
from .models import AuditEvent
from . import device_files as files

def reply(value,status=200):
    r=base_reply(value,status);r['Cache-Control']='no-store';return r

@api()
def listing(request):return reply(files.listing(request.user,request.GET.get('q',''),request.GET.get('unit_id','')))
@api(('POST',))
def upload(request):
    if set(request.FILES)!={'file'} or set(request.POST)!={'request_id','note'}:raise ValueError('请提供一份原件、申请号及来源说明')
    return reply(files.info(files.upload(request.user,request.FILES['file'],request.POST['request_id'],request.POST['note'])))
@api()
def detail(request,file_id):return reply(files.detail(request.user,file_id))
@api(('POST',))
def preview(request,file_id):
    d=body(request)
    if set(d)!={'session_id'}:raise ValueError('请提供检测会话号')
    return reply(files.preview(request.user,file_id,d['session_id']))
@api(('POST',))
def review(request,file_id):return reply(files.public_review(files.review(request.user,file_id,body(request))))
def download_response(raw,name,content_type='application/octet-stream'):
    r=HttpResponse(raw,content_type=content_type);r['Content-Disposition']="attachment; filename*=UTF-8''"+quote(name);r['Cache-Control']='no-store';r['X-Content-Type-Options']='nosniff';r['Content-Security-Policy']="default-src 'none'; sandbox";return r
@api()
def original(request,file_id):
    f=files.get(request.user,file_id);raw=files.contents(f)
    AuditEvent.objects.create(action='device_file.download',actor=request.user.username,object_type='DeviceFile',object_id=str(f.pk),detail={'file_hash':f.file_hash,'size':f.size})
    return download_response(raw,f.filename)
@api()
@transaction.atomic
def export(request,file_id):
    d=files.detail(request.user,file_id)
    d['current_previews']=[files.preview(request.user,file_id,c['session_id']) for c in d['checks']]
    d['export_note']='history为保存时的不可覆盖审核证据；current_previews为本次导出时核对当前事实的结果，两者分别保留。原件字节请另行下载并核验file_hash。'
    AuditEvent.objects.create(action='device_file.export',actor=request.user.username,object_type='DeviceFile',object_id=str(file_id),detail={'file_hash':d['file_hash'],'reviews':len(d['history'])})
    return download_response(json.dumps(d,ensure_ascii=False,indent=2,default=str).encode(),f'检测文件关联证据-{file_id}.json','application/json; charset=utf-8')
@api()
def template(request):
    files.require(request.user);out=io.StringIO();csv.writer(out).writerow(files.HEADERS)
    return download_response(('\ufeff'+out.getvalue()).encode(),'检测设备导出_标准表头.csv','text/csv; charset=utf-8')
