import json
from django.db import transaction
from . import coordination_hub as hub
from .views import api, reply
from .quality_views import csv_reply
from .models import AuditEvent

def response(data):
    out=reply(data);out['Cache-Control']='no-store';return out

@api()
@transaction.atomic
def board(request):
    f=hub.params(request.GET);n=hub.page(request.GET);d=hub.Hub(request.user)
    return response(d.board(f,n))

@api()
@transaction.atomic
def detail(request,key):
    if set(request.GET)-{'receipt','page'}:raise ValueError('详情参数无效')
    d=hub.Hub(request.user);d.get(key);d.check(request.GET.get('receipt'));return response(d.detail(key,hub.page(request.GET)))

FIELDS=[('id','记录标识'),('type_label','记录类型'),('domain_label','来源专题'),('object_key','业务对象'),('title','标题'),
        ('status','原状态'),('owner','责任岗位或账号'),('owner_kind','责任类型'),('due_date','跟进期限'),('overdue_days','逾期天数'),
        ('updated_by','最近记录人'),('updated_at','最近记录时间'),('version','当前版本'),('note','当前跟进说明'),
        ('source_dataset','主体资料表'),('source_key','主体资料编号'),('source_revision','主体资料版本')]

@api()
@transaction.atomic
def export(request):
    f=hub.params(request.GET);d=hub.Hub(request.user);d.check(request.GET.get('receipt'));rows=d.selected(f)
    values=[['跟进汇总','跟进日期',d.today,'业务事实截止',hub.analytics.AS_OF],['范围',json.dumps(f,ensure_ascii=False),'读取依据',d.receipt],
            ['说明',hub.NOTICE],[label for _,label in FIELDS]+['期限分类','主体资料状态']]
    values += [[r.get(k) for k,_ in FIELDS]+[hub.BUCKETS[r['bucket']],r['source_state']] for r in rows]
    AuditEvent.objects.create(action='coordination_hub.export',actor=request.user.username,object_type='CoordinationHub',object_id='all',
                              detail={'filters':f,'rows':len(rows),'today':d.today.isoformat(),'receipt':d.receipt,'business_facts_changed':False})
    out=csv_reply(values,'coordination-followups');out['Cache-Control']='no-store';return out
