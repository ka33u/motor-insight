import json
from django.db import transaction
from django.http import HttpResponse
from .views import api,reply,body
from . import topic_pages as pages
from .models import TopicPage,AuditEvent

def params(request,keys=()):
 if set(request.GET)-set(keys) or any(len(request.GET.getlist(k))!=1 for k in request.GET):raise ValueError('页面读取参数无效或重复')
def number(request):
 v=request.GET.get('version')
 if v is None:return None
 if not v.isascii() or not v.isdecimal() or not 1<=int(v)<=200:raise ValueError('页面版本须为1至200整数')
 return int(v)
def response(d):
 r=reply(d);r['Cache-Control']='no-store';return r
@api(('GET','POST'))
@transaction.atomic
def collection(request):
 if request.method=='POST':return response(pages.save(request.user,body(request)))
 params(request);u=pages.fresh(request.user);rows=[]
 for p in TopicPage.objects.filter(owner=u).order_by('-updated_at','id'):
  v=pages.version(p);d=v.payload['definition'];rows.append(dict(id=str(p.pk),code=p.code,title=d['title'],topic_id=p.topic_id,revision=p.revision,version=p.current_version,archived=p.archived))
 return response(dict(rows=rows,notice=pages.NOTICE,personal_only=True))
@api(('POST',))
@transaction.atomic
def preview(request):return response(pages.preview(request.user,body(request)))
@api(('GET','POST'))
@transaction.atomic
def detail(request,key):
 if request.method=='POST':return response(pages.save(request.user,body(request),key))
 params(request,('version',));return response(pages.read(request.user,key,number(request)))
@api()
@transaction.atomic
def history(request,key):
 params(request);u=pages.fresh(request.user);p=pages.owned(u,key);pages.info(u,p)
 return response(dict(rows=[dict(number=v.number,payload_hash=v.payload_hash,reason=v.payload['reason'],created_at=v.created_at) for v in p.versions.order_by('-number')],id=str(p.pk)))
@api(('POST',))
def archive(request,key):return response(pages.archive(request.user,key,body(request)))
@api(('POST',))
@transaction.atomic
def navigate(request,key):return response(pages.navigation(request.user,key,body(request)))
@api()
@transaction.atomic
def export(request,key):
 params(request,('version','receipt'));u,d=pages.checked_read(request.user,key,number(request),request.GET.get('receipt'))
 doc=dict(format='motor.private-topic-page.v1',id=d['id'],code=d['code'],version=d['version'],current_version=d['current_version'],revision=d['revision'],archived=d['archived'],stale=d['stale'],definition=d['definition'],binding=d['binding'],payload_hash=d['payload_hash'],notice=pages.NOTICE,contains_business_values=False)
 r=HttpResponse(json.dumps(doc,ensure_ascii=False,indent=2,allow_nan=False)+'\n',content_type='application/json; charset=utf-8');r['Content-Disposition']='attachment; filename="page-'+d['id']+'-v'+str(d['version'])+'.json"';r['Cache-Control']='no-store'
 AuditEvent.objects.create(action='topic_page.export',actor=u.username,object_type='TopicPage',object_id=d['id'],detail=dict(version=d['version'],payload_hash=d['payload_hash'],contains_business_values=False,business_facts_changed=False));return r
