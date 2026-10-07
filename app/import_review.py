"""Explicit conflict decisions with optimistic concurrency and immutable evidence."""
from collections import Counter
from copy import deepcopy
from django.db import transaction
from django.utils import timezone
from .models import ImportBatch, ImportRow, Record, ImportDecision, AuditEvent, AnalysisModel, Topic
from .schema import SCHEMAS
from .semantic_schema import SEMANTIC_SCHEMAS
from .ingestion import convert, fingerprint
from .manufacturing_rules import issues as manufacturing_issues

class ReviewConflict(ValueError): pass

def source(row):
    return {'row_id':row.pk,'batch':str(row.batch_id),'filename':row.batch.filename,'sheet':row.sheet,'row_number':row.row_number}

def snapshot(record):
    return {'record_id':record.pk,'dataset':record.dataset,'key':record.business_key,'revision':record.revision,'hash':record.record_hash,'values':deepcopy(record.values),'source':source(record.source_row)}

def decision_info(decision):
    return {'id':decision.pk,'action':decision.action,'actor':decision.actor,'reason':decision.reason,'candidate_hash':decision.candidate_hash,'candidate_source':source(decision.row),'before':decision.before,'after':decision.after,'created_at':decision.created_at}

def summarize(batch):
    counts=dict(Counter(batch.rows.values_list('status',flat=True)));counts['total']=sum(counts.values());counts['unknown_sheets']=batch.summary.get('unknown_sheets',[])
    if batch.summary.get('skipped_sheets'):counts['skipped_sheets']=batch.summary['skipped_sheets']
    batch.summary=counts
    batch.status='staged' if counts.get('valid') else 'partial' if counts.get('invalid') or counts.get('conflict') else 'committed'
    if batch.status!='staged' and not batch.committed_at:batch.committed_at=timezone.now()
    batch.save(update_fields=['summary','status','committed_at'])

def validate_values(dataset, values, *, batch_id=None):
    if not isinstance(values,dict):raise ValueError('标准字段内容必须为对象')
    schema=SCHEMAS[dataset];known={f['name'] for f in schema['fields']}
    if set(values)-known:raise ValueError('含有未定义字段：'+','.join(sorted(set(values)-known)))
    result={f['name']:convert(values.get(f['name']),f) for f in schema['fields']}
    for f in schema['fields']:
        value=result[f['name']]
        if f['reference'] and value is not None:
            exists=Record.objects.filter(dataset=f['reference'],business_key=value).exists()
            if not exists and batch_id:
                exists=ImportRow.objects.filter(batch_id=batch_id,dataset=f['reference'],business_key=value,status='valid').exists()
            if not exists:raise ValueError(f'{f["label"]}的关联记录尚未入库'+('或通过本批校验' if batch_id else ''))
        if f['name'] in ['qty','planned_qty','input_qty','good_qty','scrap_qty','rework_qty','amount_cents','unit_price_cents'] and value is not None and value<0:
            raise ValueError(f'{f["label"]}不能为负数')
    errors=manufacturing_issues(dataset,result)
    if errors:raise ValueError('；'.join(x['message'] for x in errors))
    return result

def impact(dataset,key):
    direct=[]
    for name,schema in SCHEMAS.items():
        for f in schema['fields']:
            if f['reference']==dataset:
                count=Record.objects.filter(dataset=name,**{'values__'+f['name']:key}).count()
                if count:direct.append({'dataset':name,'label':schema['label'],'field':f['label'],'count':count})
    related={dataset}|{name for name,s in SEMANTIC_SCHEMAS.items() if dataset in s['sources']}
    models=list(AnalysisModel.objects.filter(dataset__in=related).values('id','name','dataset'));model_ids={m['id'] for m in models}
    topics=[{'id':t.pk,'name':t.name} for t in Topic.objects.all() if any(c.get('model_id') in model_ids for c in t.layout)]
    return {'direct_references':direct,'models':models,'topics':topics,'note':'直接引用按字段分别计数，同一记录可能出现多次；模型与专题为数据集级潜在影响，不能证明某个指标一定变化。多态批次关系、外部系统和业务审批需另行核对。'}

def detail(batch_id,row_id):
    row=ImportRow.objects.select_related('batch').get(pk=row_id,batch_id=batch_id)
    current=Record.objects.select_related('source_row__batch').filter(dataset=row.dataset,business_key=row.business_key).first()
    decision=ImportDecision.objects.filter(row=row).first()
    old=decision.before if decision else snapshot(current) if current else None
    fields=[{'name':f['name'],'label':f['label'],'before':old['values'].get(f['name']) if old else None,'after':row.normalized.get(f['name']),'changed':old is None or old['values'].get(f['name'])!=row.normalized.get(f['name'])} for f in SCHEMAS[row.dataset]['fields']]
    actionable=row.status=='conflict' and row.batch.status in ['staged','partial'] and current is not None and decision is None
    return {'id':row.pk,'dataset':row.dataset,'dataset_label':SCHEMAS[row.dataset]['label'],'key':row.business_key,'status':row.status,'batch_status':row.batch.status,'candidate':{'values':row.normalized,'hash':row.record_hash,'source':source(row)},'current':snapshot(current) if current else None,'comparison_base':old,'fields':fields,'decision':decision_info(decision) if decision else None,'can_review':actionable,'impact':impact(row.dataset,row.business_key),
            'message':'审核已完成，展示当时的版本差异。' if decision else '旧值来自当前正式记录；批准替换将立即更新正式数据并增加版本。' if actionable else '没有可审核的正式记录。若是同一批次内的候选冲突，请先提交校验通过行，再返回审核；也可修复来源内容。'}

def decide(batch_id,row_id,actor,data):
    action=data.get('action');reason=data.get('reason','')
    if action not in ['keep','replace']:raise ValueError('请选择保留正式记录或批准替换')
    if not isinstance(reason,str) or not 5<=len(reason.strip())<=1000:raise ValueError('请填写5至1000字的审核依据')
    reason=reason.strip();token=data.get('expected',{})
    if not isinstance(token,dict) or set(token)!={'record_id','revision','hash','candidate_hash'}:raise ValueError('审核版本信息不完整，请重新查看差异')
    if type(token['record_id']) is not int or type(token['revision']) is not int or not all(isinstance(token[k],str) and len(token[k])==64 for k in ['hash','candidate_hash']):raise ValueError('审核版本格式不正确')
    with transaction.atomic():
        batch=ImportBatch.objects.select_for_update().get(pk=batch_id)
        row=ImportRow.objects.select_for_update().get(pk=row_id,batch=batch)
        prior=ImportDecision.objects.filter(row=row).first()
        if prior:
            original={k:prior.before[k] for k in ['record_id','revision','hash']};original['candidate_hash']=prior.candidate_hash
            if prior.action==action and prior.actor==actor and prior.reason==reason and token==original:return prior,True
            raise ReviewConflict('此行已由他人或先前操作完成审核，请刷新查看结果')
        if batch.status not in ['staged','partial'] or row.status!='conflict':raise ReviewConflict('当前批次或行状态不允许冲突审核，请刷新')
        if row.record_hash!=token['candidate_hash']:raise ReviewConflict('待导入内容已被修复，请重新查看差异后审核')
        current=Record.objects.select_for_update().select_related('source_row__batch').filter(dataset=row.dataset,business_key=row.business_key).first()
        if current is None:raise ReviewConflict('对应正式记录已不存在，请重新校验此行')
        before=snapshot(current)
        if any(token[k]!=before[k] for k in ['record_id','revision','hash']):raise ReviewConflict('正式记录已更新，旧审核页面不能覆盖新版本；请重新查看差异')
        if action=='replace':
            values=validate_values(row.dataset,row.normalized)
            if values[SCHEMAS[row.dataset]['primary_key']]!=current.business_key:raise ValueError('替换不能改变业务主键，请使用更正来源流程')
            if fingerprint(values)!=row.record_hash:raise ReviewConflict('候选字段或规范发生变化，请重新校验来源行')
            if current.record_hash==row.record_hash:raise ReviewConflict('内容已与正式记录一致，无需替换；请保留正式记录')
            # CAS protects SQLite as well as databases with SELECT FOR UPDATE.
            changed=Record.objects.filter(pk=current.pk,revision=token['revision'],record_hash=token['hash']).update(values=values,record_hash=row.record_hash,source_row=row,revision=current.revision+1,updated_at=timezone.now())
            if changed!=1:raise ReviewConflict('审核提交期间版本发生变化，请刷新')
            current.refresh_from_db();after=snapshot(current);row.status='replaced'
        else:after=deepcopy(before);row.status='kept'
        decision=ImportDecision.objects.create(row=row,action=action,actor=actor,reason=reason,candidate_hash=row.record_hash,before=before,after=after)
        row.issues=[];row.save(update_fields=['status','issues']);summarize(batch)
        AuditEvent.objects.create(action='import.conflict.'+action,actor=actor,object_type='ImportDecision',object_id=str(decision.pk),detail={'dataset':row.dataset,'business_key':row.business_key,'candidate_source':source(row),'reason':reason,'before':before,'after':after})
        return decision,False
