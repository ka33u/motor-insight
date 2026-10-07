from .views import api,reply,body
from . import topic_workspace as workspace

@api()
def context(request,topic_id):
    ctx=workspace.context(request.user,topic_id)
    return reply({**ctx,'views':workspace.list_views(request.user,ctx,request.GET.get('archived')=='true')})

@api(('POST',))
def save(request,topic_id):return reply(workspace.save_view(request.user,topic_id,body(request)))

@api(('POST',))
def update(request,topic_id,view_id):return reply(workspace.save_view(request.user,topic_id,body(request),view_id))

@api(('POST',))
def archive(request,topic_id,view_id):return reply(workspace.archive_view(request.user,topic_id,view_id,body(request)))

@api(('POST',))
def run(request,topic_id):return reply(workspace.run(request.user,topic_id,body(request)))

@api(('POST',))
def evidence(request,topic_id):return reply(workspace.evidence(request.user,topic_id,body(request)))

@api()
def export(request,topic_id):
    import csv,io,json,re
    from urllib.parse import quote
    from django.core.exceptions import ValidationError
    from django.http import HttpResponse
    if set(request.GET)!={'context_token','facts_token','config','slot'} or len(request.GET['config'])>3000 or not re.fullmatch(r'[0-9]{1,2}',request.GET['slot']):raise ValidationError('导出范围参数无效')
    rows,model_id=workspace.export_rows(request.user,topic_id,{'context_token':request.GET['context_token'],'facts_token':request.GET['facts_token'],'config':json.loads(request.GET['config']),'slot':int(request.GET['slot'])})
    def safe(value):
        if value is None:return ''
        if isinstance(value,str) and re.match(r'^[\s]*[=+@\-\t\r]',value):return "'"+value
        return value
    stream=io.StringIO();writer=csv.writer(stream)
    for row in rows:writer.writerow([safe(v) for v in row])
    response=HttpResponse('\ufeff'+stream.getvalue(),content_type='text/csv; charset=utf-8')
    response['Content-Disposition']="attachment; filename*=UTF-8''"+quote(f'专题{topic_id}-模型{model_id}-已返回结果.csv')
    response['Cache-Control']='no-store';return response
