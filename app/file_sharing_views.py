from .views import api,body
from .device_file_views import reply,download_response
from . import file_sharing as sharing,device_files as files
from .models import AuditEvent

def no_query(request):
    if request.GET:raise ValueError('本接口不接收查询参数')

@api()
def listing(request):
    no_query(request);return reply(sharing.listing(request.user))
@api()
def manage(request,file_id):
    no_query(request);return reply(sharing.context(request.user,file_id))
@api(('POST',))
def preview(request,file_id):
    no_query(request);return reply(sharing.preview(request.user,file_id,body(request)))
@api(('POST',))
def commit(request,file_id):
    no_query(request);return reply(sharing.event_info(sharing.commit(request.user,file_id,body(request))))
@api()
def detail(request,file_id):
    no_query(request);return reply(sharing.detail(request.user,file_id))
@api()
def original(request,file_id):
    no_query(request);f,permit=sharing.readable(request.user,file_id);raw=files.contents(f)
    AuditEvent.objects.create(action='file_read.download',actor=request.user.username,object_type='DeviceFile',object_id=str(f.pk),
      detail=dict(file_hash=f.file_hash,size=f.size,permission_receipt=permit,business_facts_changed=False))
    return download_response(raw,f.filename)
