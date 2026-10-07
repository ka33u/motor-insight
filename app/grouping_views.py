from django.db import transaction
from django.core.exceptions import ValidationError
from .views import api,reply,body,require
from . import business_groups as groups,access
from .models import BusinessGrouping

@api(('GET','POST'))
@transaction.atomic
def collection(request):
    if request.method=='POST':return reply(groups.save(request.user,body(request)))
    rows=[]
    for g in BusinessGrouping.objects.filter(owner=request.user.username).order_by('-updated_at'):
        try:
            for v in g.versions.all():groups.validate(request.user,v.payload)
            rows.append(groups.info(g))
        except ValidationError:continue
    return reply({'rows':rows,'notice':groups.NOTICE,'can_edit':access.can_edit(request.user)})

@api(('GET','POST'))
@transaction.atomic
def detail(request,gid):
    g=BusinessGrouping.objects.get(pk=gid,owner=request.user.username)
    if request.method=='POST':return reply(groups.save(request.user,body(request),gid))
    for v in g.versions.all():groups.validate(request.user,v.payload)
    return reply({**groups.info(g),'impact':groups.impact(g)})

@api(('POST',))
def preview(request):
    require(access.can_edit(request.user));return reply(groups.preview(request.user,body(request)))

@api(('POST',))
def archive(request,gid):return reply(groups.archive(request.user,gid,body(request)))
