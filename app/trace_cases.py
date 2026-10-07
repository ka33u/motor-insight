"""Immutable investigation snapshots plus mutable, audited coordination notes."""
import hashlib,json,uuid
from datetime import date
from collections import defaultdict
from django.db import transaction
from django.utils import timezone
from django.core.exceptions import PermissionDenied,ValidationError
from . import analytics,lineage,access,coding
from .models import TraceCase,Record,AuditEvent,CodingRule
from .import_review import ReviewConflict

STATUSES=['排查中','待业务核验','演练已结案']
def digest(value):return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),default=str).encode()).hexdigest()
def can_edit(user):return access.role(user) in ['admin','analyst','quality','operations']
def info(c):return {k:getattr(c,k) for k in ['id','code','title','owner','due_date','status','note','version','snapshot_hash','created_by','updated_by','created_at','updated_at']}
def validate(data):
    for field,limit in [('title',150),('owner',150),('note',2000)]:
        if not isinstance(data.get(field),str) or not 1<=len(data[field].strip())<=limit:raise ValidationError('请完整填写标题、负责人和排查依据')
    if len(data['note'].strip())<5:raise ValidationError('排查依据至少5字')
    due=data.get('due_date')
    if due in (None,''):due=None
    elif not isinstance(due,str) or date.fromisoformat(due).isoformat()!=due:raise ValidationError('期限格式应为YYYY-MM-DD')
    return {**{f:data[f].strip() for f in ['title','owner','note']},'due_date':due}

def capture_sources(snapshot):
    by_dataset=defaultdict(set)
    for r in snapshot['sources']:by_dataset[r['dataset']].add(r['key'])
    manifest=[];found=set()
    for dataset,keys in by_dataset.items():
        keys=sorted(keys)
        for offset in range(0,len(keys),400):
            for r in Record.objects.filter(dataset=dataset,business_key__in=keys[offset:offset+400]).select_related('source_row__batch'):
                s=r.source_row;b=s.batch;found.add((dataset,r.business_key))
                manifest.append({'dataset':dataset,'key':r.business_key,'revision':r.revision,'record_hash':r.record_hash,'batch_id':str(b.pk),'filename':b.filename,'file_hash':b.file_hash,'sheet':s.sheet,'row':s.row_number})
    manifest.extend({'dataset':ds,'key':key,'missing':True} for ds,keys in by_dataset.items() for key in keys if (ds,key) not in found)
    return sorted(manifest,key=lambda r:(r['dataset'],r['key']))

@transaction.atomic
def create(user,data):
    if not can_edit(user):raise PermissionDenied('当前身份只能查看排查结果')
    if set(data)!={'request_id','root','data_revision','title','owner','due_date','note'}:raise ValidationError('排查快照请求字段不完整')
    rid=uuid.UUID(str(data['request_id']));fingerprint=digest(data)
    previous=TraceCase.objects.filter(request_id=rid).first()
    if previous:
        if previous.created_by!=user.username or previous.request_hash!=fingerprint:raise ReviewConflict('重复请求标识对应不同内容，请重新建立排查')
        return previous
    values=validate(data);root=data['root']
    if not isinstance(root,dict) or set(root)!={'kind','id','material_id'}:raise ValidationError('请从反查结果选择完整对象')
    if data['data_revision']!=list(analytics.revision()):raise ReviewConflict('导入数据已变化，请刷新反查范围后保存快照')
    snapshot=lineage.current(root['kind'],root['id'],root['material_id'])
    snapshot['source_manifest']=capture_sources(snapshot)
    if snapshot['data_revision']!=list(analytics.revision()):raise ReviewConflict('保存期间数据发生变化，请重新查询后保存')
    rule=CodingRule.objects.filter(key='trace_case').first()
    if not rule:raise ValidationError('尚未配置trace_case排查编号规则，请由管理员配置')
    code=coding.allocate(rule.pk,timezone.localtime(),1,user.username)[0]
    case=TraceCase.objects.create(code=code,request_id=rid,request_hash=fingerprint,**values,snapshot=snapshot,snapshot_hash=digest(snapshot),created_by=user.username,updated_by=user.username)
    AuditEvent.objects.create(action='trace_case.create',actor=user.username,object_type='TraceCase',object_id=str(case.pk),detail={'code':case.code,'root':snapshot['root'],'summary':snapshot['summary'],'snapshot_hash':case.snapshot_hash,'source_records':len(snapshot['source_manifest']),'business_facts_changed':False})
    return case

@transaction.atomic
def update(user,case_id,data):
    if not can_edit(user):raise PermissionDenied('当前身份只能查看排查记录')
    if set(data)!={'version','title','owner','due_date','status','note'}:raise ValidationError('处置字段不完整或包含不可修改字段')
    if data['status'] not in STATUSES:raise ValidationError('处置状态不可用')
    if data['status']=='演练已结案' and access.role(user) not in ['admin','quality']:raise PermissionDenied('模拟结案由质量岗位或管理员核验')
    c=TraceCase.objects.select_for_update().get(pk=case_id)
    if type(data['version']) is not int or data['version']!=c.version:raise ReviewConflict('排查记录已被更新，请重新读取')
    before=info(c)
    for k,v in validate(data).items():setattr(c,k,v)
    c.status=data['status'];c.version+=1;c.updated_by=user.username;c.save(update_fields=['title','owner','due_date','status','note','version','updated_by','updated_at'])
    serial=lambda x:json.loads(json.dumps(x,default=str,ensure_ascii=False))
    AuditEvent.objects.create(action='trace_case.update',actor=user.username,object_type='TraceCase',object_id=str(c.pk),detail={'before':serial(before),'after':serial(info(c)),'snapshot_unchanged':True,'business_facts_changed':False})
    return c

def compare(c):
    root=c.snapshot['root'];now=lineage.current(root['kind'],root['id'],root['material_id']);before={r['id']:r for r in c.snapshot['units']};after={r['id']:r for r in now['units']}
    fields=['relation','quality','release_valid','session_id','release_id','shipped','shipment_ids','order_line_ids','ownership','issues']
    added=sorted(set(after)-set(before));removed=sorted(set(before)-set(after));changed=[]
    for key in sorted(set(before)&set(after)):
        diffs={field:{'before':before[key][field],'now':after[key][field]} for field in fields if before[key][field]!=after[key][field]}
        if diffs:changed.append({'id':key,'changes':diffs})
    old_edges={e['id']:e for e in c.snapshot['edges']};new_edges={e['id']:e for e in now['edges']}
    edge_changes=sorted(k for k in set(old_edges)|set(new_edges) if old_edges.get(k)!=new_edges.get(k))
    return {'code':c.code,'snapshot_hash':c.snapshot_hash,'before_revision':c.snapshot['data_revision'],'current_revision':now['data_revision'],'before_summary':c.snapshot['summary'],'current_summary':now['summary'],'added_count':len(added),'removed_count':len(removed),'changed_count':len(changed),'edge_change_count':len(edge_changes),'added':added[:100],'removed':removed[:100],'changed':changed[:100],'edge_changes':edge_changes[:100],'limit':100,'snapshot_unchanged':digest(c.snapshot)==c.snapshot_hash,'notice':'保存快照保持原样。范围移出可能来自更正或关联删除，不能据此认定已无风险；如需保留新范围，请另存排查快照。'}
