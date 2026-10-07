"""Receipt-bound overview observations, full cohort export and follow-up notes."""
import json
from django.db import transaction
from . import issue_workspace as issues
from .models import AuditEvent
from .views import api,reply,body
from .quality_views import csv_reply

STATUSES=issues.STATUSES
def response(value,status=200):
    r=reply(value,status);r['Cache-Control']='no-store';return r

@api()
def board(request):
    d=issues.Workspace(request.user,issues.filters(request.GET));return response(d.board(issues.page(request.GET)))

@api()
def detail(request,key):
    d=issues.Workspace(request.user,issues.filters(request.GET));d.check(request.GET.get('receipt'))
    return response(d.detail(key,issues.page(request.GET)))

@api(('POST',))
def follow_up(request,key):return response(issues.follow(request.user,key,body(request)))

@api()
@transaction.atomic
def export(request):
    d=issues.Workspace(request.user,issues.filters(request.GET));d.check(request.GET.get('receipt'));rows=d.selected()
    values=[['模拟业务观察清单','业务截止',d.as_of,'跟进日期',d.today.isoformat(),'筛选',json.dumps(d.filters,ensure_ascii=False)],
        ['口径',issues.NOTICE],['范围统计',json.dumps(d.summary(rows),ensure_ascii=False)],
        ['观察编号','问题类别','对象表','业务对象','范围说明','等级','问题依据','跟进状态','责任岗位文字','跟进期限','跟进版本','最近记录人','最近记录时间','跟进依据','跟进逾期','来源缺口','来源表与编号','文件与工作表行号']]
    for r in rows:
        provenance=[]
        for ref in r['refs']:
            obj=d.records.get((ref['dataset'],ref['key']))
            if obj:
                sr=obj.source_row;provenance.append(dict(**ref,file=sr.batch.filename,sheet=sr.sheet,row=sr.row_number,batch=str(sr.batch_id),file_hash=sr.batch.file_hash))
        n=r['disposition'];values.append([r['key'],r['kind'],r['dataset'],r['object'],r['scope'],r['severity'],r['detail'],n['status'],n['owner'],n['due_date'],n['version'],n['updated_by'],n['updated_at'],n['note'],r['followup_overdue'],r['source_missing'],json.dumps(r['refs'],ensure_ascii=False),json.dumps(provenance,ensure_ascii=False)])
    AuditEvent.objects.create(action='issue_workspace.export',actor=request.user.username,object_type='OverviewIssueScope',object_id='cohort',detail=dict(scope=d.filters,summary=d.summary(rows),as_of=d.as_of,today=d.today.isoformat(),business_facts_changed=False))
    r=csv_reply(values,'overview-issue-cohort');r['Cache-Control']='no-store';return r
