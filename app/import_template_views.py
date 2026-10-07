import json,tempfile
from contextlib import contextmanager
from . import import_templates as templates,import_mapping as mapping
from .models import ImportTemplate,AuditEvent
from .views import api,reply,body


def definition(request):
    raw=request.POST.get('definition','{}')
    if len(raw)>12000:raise ValueError('模板定义过长')
    def unique(items):
        result={}
        for k,v in items:
            if k in result:raise ValueError('模板定义含重复参数')
            result[k]=v
        return result
    data=json.loads(raw,object_pairs_hook=unique)
    if not isinstance(data,dict):raise ValueError('模板定义须为对象')
    return data


@contextmanager
def upload(request):
    file=request.FILES.get('file')
    if not file or not file.name.lower().endswith('.xlsx') or file.size>50*1024*1024:raise ValueError('请选择不超过50MB的.xlsx文件')
    with tempfile.NamedTemporaryFile(suffix='.xlsx') as temp:
        for chunk in file.chunks():temp.write(chunk)
        temp.flush();yield temp.name,file.name


@api(('GET','POST'))
def collection(request):
    templates.authorized(request.user)
    if request.method=='GET':
        return reply([templates.info(t,request.user) for t in ImportTemplate.objects.prefetch_related('versions').order_by('code')])
    with upload(request) as (path,filename):
        result=templates.save(request.user,path,filename,mapping.parse_mapping(request.POST.get('mapping','{}')),
            request.POST.get('inspection_receipt',''),definition(request))
    return reply(result)


@api()
def detail(request,template_id):
    templates.authorized(request.user)
    t=ImportTemplate.objects.prefetch_related('versions').get(pk=template_id)
    result=templates.info(t,request.user,True)
    page=max(1,int(request.GET.get('page',1)));events=AuditEvent.objects.filter(object_type='ImportTemplate',object_id=str(t.pk),action__startswith='import_template.').order_by('-id')
    result['history']=dict(page=page,total=events.count(),size=30,rows=list(events[(page-1)*30:page*30].values('id','action','actor','detail','created_at')))
    return reply(result)


@api(('POST',))
def preview(request):
    templates.authorized(request.user)
    version_id=request.POST.get('version_id','')
    if not version_id.isdigit():raise ValueError('请选择模板版本')
    with upload(request) as (path,filename):result=templates.preview(request.user,path,filename,int(version_id),request.POST.get('purpose','use'))
    return reply(result)


@api(('POST',))
def activate(request):
    templates.authorized(request.user)
    with upload(request) as (path,filename):result=templates.activate(request.user,path,filename,request.POST.get('template_receipt',''),definition(request))
    return reply(result)


@api(('POST',))
def retire(request,template_id):
    return reply(templates.retire(request.user,template_id,body(request)))
