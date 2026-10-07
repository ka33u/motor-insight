import json
from . import action_tasks as tasks
from .views import api,reply,body
from .quality_views import csv_reply
from .models import AuditEvent
from django.core.exceptions import ValidationError
from django.db import transaction

@api(('GET','POST'))
def collection(request):
    return reply(tasks.create(request.user,body(request)) if request.method=='POST' else tasks.board(request.user,request.GET))

@api()
def preview(request):
    if set(request.GET)!={'dataset','key','classification'}:raise ValidationError('请选择来源、编号与资料级别')
    return reply(tasks.preview(request.user,**dict(request.GET.items())))

@api()
def detail(request,task_id):
    if set(request.GET)-{'page'}:raise ValidationError('历史筛选不可用')
    return reply(tasks.detail(request.user,task_id,int(request.GET.get('page',1))))

@api(('POST',))
def transition(request,task_id):return reply(tasks.transition(request.user,task_id,body(request)))

@api()
@transaction.atomic
def export(request,task_id):
    t=tasks.get(request.user,task_id)
    rows=[['协调任务','标识','版本','轮次','状态','来源业务表','来源编号','问题类别','资料级别','说明'],
          [t.title,str(t.pk),t.version,t.cycle,tasks.STATES[t.state],t.dataset,t.business_key,tasks.RULES[t.rule],tasks.CLASSES[t.classification],tasks.NOTICE],
          ['序号','操作','操作者','时间','依据','原状态','新状态','责任账号ID','复核账号ID','期限','当次提交结论','当次提交证据（含版本及Excel行）']]
    for e in t.events.select_related('actor').order_by('sequence'):
        s=e.after.get('submission',{})
        rows.append([e.sequence,tasks.ACTIONS.get(e.action,'登记任务'),e.actor.username,e.created_at.isoformat(),e.note,
                     tasks.STATES.get(e.before.get('state'),''),tasks.STATES[e.after['state']],e.after['assignee_id'],e.after['reviewer_id'],
                     e.after['due_date'],s.get('conclusion',''),json.dumps({'提交时来源':s.get('origin'),'支持证据':s.get('evidence',[])},ensure_ascii=False)])
    AuditEvent.objects.create(action='action_task.export',actor=request.user.username,object_type='ActionTask',object_id=str(t.pk),detail={'version':t.version,'events':len(rows)-3})
    return csv_reply(rows,'coordination-task')
