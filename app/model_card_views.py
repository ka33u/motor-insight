import json
from django.db import transaction
from django.core.exceptions import ValidationError
from . import model_cards as cards
from .models import AnalysisModelCard,AuditEvent
from .views import api,reply
def response(value):
 r=reply(value);r['Cache-Control']='no-store';return r
def params(request,allowed=()):
 if set(request.GET)-set(allowed) or any(len(request.GET.getlist(k))!=1 for k in request.GET):raise ValueError('口径卡范围字段未知或重复')
def body(request):
 if len(request.body)>50000:raise ValueError('口径卡请求过长')
 def pairs(items):
  d={}
  for k,v in items:
   if k in d:raise ValueError('口径卡字段重复')
   d[k]=v
  return d
 return json.loads(request.body.decode(),object_pairs_hook=pairs)
@api()
@transaction.atomic
def preview(request,model_id):
 params(request);return response(cards.preview(request.user,model_id))
@api(('GET','POST'))
@transaction.atomic
def collection(request):
 if request.method=='POST':
  params(request);card,revision,repeated=cards.save(request.user,body(request));return response(dict(card=cards.info(card,cards.fresh(request.user)),saved_revision=revision,repeated=repeated))
 params(request,('archived',));u=cards.fresh(request.user);q=AnalysisModelCard.objects.filter(owner=u).order_by('-updated_at','id');archived=request.GET.get('archived','0')
 if archived not in {'0','1','all'}:raise ValueError('归档筛选不可用')
 if archived!='all':q=q.filter(archived=archived=='1')
 rows=[];unavailable=0
 for card in q:
  try:rows.append(cards.info(card,u))
  except (cards.ObjectDoesNotExist,ValidationError):unavailable+=1
 return response(dict(rows=rows,total=len(rows),unavailable=unavailable,private=True,notice=cards.NOTICE))
@api(('GET','POST'))
@transaction.atomic
def detail(request,key):
 params(request)
 if request.method=='POST':
  card,revision,repeated=cards.save(request.user,body(request),key);return response(dict(card=cards.info(card,cards.fresh(request.user)),saved_revision=revision,repeated=repeated))
 card=cards.get_card(request.user,key);return response(dict(card=cards.info(card,cards.fresh(request.user))))
@api(('POST',))
@transaction.atomic
def archive(request,key):
 params(request);card,revision,repeated=cards.archive(request.user,key,body(request));return response(dict(card=cards.info(card,cards.fresh(request.user)),saved_revision=revision,repeated=repeated))
@api()
@transaction.atomic
def history(request,key):
 params(request);u=cards.fresh(request.user);card=cards.get_card(u,key);rows=[]
 for v in card.versions.order_by('revision'):rows.append(cards.info(card,u,v.revision))
 return response(dict(rows=rows,total=len(rows),notice='只保存个人说明和引用定义版本，不保留数据结果。'))
@api()
@transaction.atomic
def run(request,key):
 from . import model_card_results
 params(request);return response(model_card_results.run(request.user,key))
@api()
@transaction.atomic
def evidence(request,key):
 from . import model_card_results
 return response(model_card_results.evidence(request.user,key,request.GET))
@api()
@transaction.atomic
def export(request,key):
 params(request);u=cards.fresh(request.user);card=cards.get_card(u,key);value=dict(format='motor.model.definition-card.v1',card=cards.info(card,u),versions=[cards.info(card,u,v.revision) for v in card.versions.order_by('revision')],notice=cards.NOTICE)
 AuditEvent.objects.create(action='model_card.export',actor=u.username,object_type='AnalysisModelCard',object_id=str(card.pk),detail=dict(revision=card.revision,business_facts_changed=False))
 r=response(value);r['Content-Disposition']='attachment; filename="model-card-'+str(card.pk)+'.json"';return r
@api()
@transaction.atomic
def result_export(request,key):
 from . import model_card_exports as exports
 from .quality_views import csv_reply
 from django.http import HttpResponse
 import hashlib
 u,value,stamp,kind=exports.resolve(request.user,key,request.GET);doc=exports.document(u,value,stamp)
 name='model-card-current-result-'+str(key)
 r=csv_reply(exports.csv_rows(doc),name) if kind=='csv' else HttpResponse(exports.encoded(doc),content_type='application/json; charset=utf-8')
 r['Content-Disposition']='attachment; filename="'+name+'.'+kind+'"';r['Cache-Control']='no-store';r['X-Content-Type-Options']='nosniff'
 AuditEvent.objects.create(action='model_card.result_export',actor=u.username,object_type='AnalysisModelCard',object_id=str(key),detail=dict(revision=value['card']['current_revision'],format=kind,matched=value['result']['matched'],groups=doc['result']['groups'],exported_groups=len(doc['result']['rows']),population_digest=stamp['population'],complete_result_digest=doc['integrity']['complete_result_digest'],file_sha256=hashlib.sha256(r.content).hexdigest(),business_facts_changed=False))
 return r
