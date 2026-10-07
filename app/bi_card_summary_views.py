"""Whole-population summaries have a separate export from truncated charts."""
import csv,io,json,re
from urllib.parse import quote
from django.db import transaction
from django.http import HttpResponse
from . import topic_workspace as ws,bi_card_summary as summary,topic_snapshots as snapshots
from .models import AuditEvent
from .views import api,reply
from .import_review import ReviewConflict

def csv_response(result,name):
    rows=[['整范围所选度量摘要','阅读时点',result['as_of'],'专题',result['topic']['name'],'专题版本',result['topic']['version']],
        ['口径',summary.NOTICE],['范围',json.dumps(result['config'],ensure_ascii=False)],
        ['卡位置','模型','模型版本','数据集','度量编号','度量名称','范围侧','结果','单位','计算状态','来源对象数','有效对象数','缺失对象数','分子','分母','日期口径','定义状态','发布指标','摘要算法','说明']]
    for card in result['cards']:
        if not card.get('scope_summary'):
            rows.append([card['slot'],'此卡未计算','','','','','','','','不可用','','','','','','','','','',card.get('error','旧快照未保存整范围摘要')]);continue
        for side in ('primary','reference'):
            s=card['scope_summary'].get(side)
            if not s:continue
            metric=s.get('metric_receipt');rows.append([card['slot'],card['model']['name'],s['model_version'],card['model']['dataset'],s['key'],s['label'],result['config']['primary_label' if side=='primary' else 'reference_label'],s['value'],s['unit'],s['state'],s['source_rows'],s['valid_rows'],s['missing_rows'],s['numerator'],s['denominator'],s['scope']['date_label'],s['definition_status'],(metric['key']+' v'+str(metric['version'])) if metric else '未发布分析定义',s['algorithm'],s['reason']])
        c=card['scope_summary'].get('comparison')
        if c:rows.append([card['slot'],card['model']['name'],'','','','','本次两侧差值',c['delta'],c['delta_unit'],'暂停' if c['blocked'] else '描述性差值','','','','','','','','','',c['reason']])
    stream=io.StringIO();writer=csv.writer(stream)
    for row in rows:writer.writerow(["'"+v if isinstance(v,str) and re.match(r'^[\s]*[=+@\-\t\r]',v) else '' if v is None else v for v in row])
    r=HttpResponse('\ufeff'+stream.getvalue(),content_type='text/csv; charset=utf-8');r['Content-Disposition']="attachment; filename*=UTF-8''"+quote(name+'.csv');r['Cache-Control']='no-store';return r

@api()
@transaction.atomic
def export(request,topic_id):
    if set(request.GET)!={'context_token','facts_token','config','summary_token'} or len(request.GET['config'])>3000 or any(len(request.GET.getlist(k))!=1 for k in request.GET):raise ValueError('摘要导出须提供当前完整范围与定义凭据')
    d=ws.run(request.user,topic_id,{'context_token':request.GET['context_token'],'config':json.loads(request.GET['config'])})
    if d['facts_token']!=request.GET['facts_token']:raise ReviewConflict('事实已变化，请刷新专题再导出摘要')
    if d['summary_token']!=request.GET['summary_token']:raise ReviewConflict('摘要范围、来源、算法或权限已变化，请刷新专题再导出')
    AuditEvent.objects.create(action='topic_scope_summary.export',actor=request.user.username,object_type='Topic',object_id=str(topic_id),detail=dict(config=d['config'],context_token=d['context_token'],facts_token=d['facts_token'],cards=len(d['cards']),business_facts_changed=False))
    return csv_response(d,'专题整范围摘要')

@api()
def frozen_export(request,topic_id,snapshot_id):
    if request.GET:raise ValueError('冻结摘要不能附加当前范围或其他筛选')
    s=snapshots.get(request.user,topic_id,snapshot_id)
    AuditEvent.objects.create(action='topic_scope_summary.frozen_export',actor=request.user.username,object_type='TopicSnapshot',object_id=str(s.pk),detail=dict(payload_hash=s.payload_hash,business_facts_changed=False))
    return csv_response(s.payload['result'],'已保存专题整范围摘要')
