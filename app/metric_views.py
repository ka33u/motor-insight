from django.core.exceptions import PermissionDenied
from . import metric_registry as registry,access
from .models import MetricVersion,AuditEvent
from .views import api,reply,body

def readable(request,version_id):
    v=MetricVersion.objects.select_related('metric').get(pk=version_id)
    if not registry.can_read(request.user,v):raise PermissionDenied('没有该指标版本的访问权限')
    return v

@api(('GET','POST'))
def collection(request):
    if request.method=='POST':return reply(registry.info(request.user,registry.create(request.user,body(request)),True))
    items=[registry.info(request.user,v) for v in MetricVersion.objects.select_related('metric').order_by('metric__key','-version') if registry.can_read(request.user,v)]
    return reply({'versions':items,'statuses':registry.STATUSES,'review_roles':registry.REVIEW_ROLES,'can_create':access.can_edit(request.user),'notice':registry.NOTICE,'null_rule':registry.NULL_RULE})

@api(('GET','POST'))
def version(request,version_id):
    if request.method=='POST':return reply(registry.info(request.user,registry.transition(request.user,version_id,body(request)),True))
    v=readable(request,version_id);d=registry.info(request.user,v,True)
    d['history']=registry.visible_history(request.user,list(AuditEvent.objects.filter(object_type='MetricVersion',object_id=str(v.pk)).order_by('-id').values('action','actor','created_at','detail')))
    return reply(d)

@api(('POST',))
def preview(request,version_id):
    v=readable(request,version_id)
    return reply({'version':registry.info(request.user,v), 'result':registry.evaluate(request.user,v)})
