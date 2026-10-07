"""Structural checks across committed XLSX facts; no inferred business approval.

Snapshots contain counters and issue identities, never source cell values. Rule
results are permission-projected when read, so saved checks grant no extra access.
"""
import hashlib,json,math,uuid
from collections import Counter,defaultdict
from datetime import date,datetime
from pathlib import Path
from django.db import transaction
from django.db.models import Count
from django.utils import timezone
from . import access,analytics
from .schema import SCHEMAS
from .ingestion import fingerprint
from .manufacturing_rules import issues as manufacturing_issues
from .models import Record,ImportBatch,ImportRow,DataQualityScan,DataMonitorPolicy,AuditEvent

RULES={'required':'必填缺失','type':'类型或格式','key':'主键不一致','reference':'引用缺失','source':'来源行不一致','hash':'记录摘要不一致','manufacturing':'制造行内约束'}
NOTE='基础检查核对已入库字段、主键、声明引用、来源行，以及工单计划日期/正数量、批次正数量、工序时间与行内数量守恒。不证明事实真实、期间完整、跨记录业务关系、质量合格或原件文件字节完整。'
LINKS={'service':'#service','service_events':'#service','service_tasks':'#service','service_conditions':'#service','energy':'#energy','ehs':'#energy','maintenance':'#assets','tools':'#assets','downtime':'#assets','equipment':'#assets','attendance':'#workforce','labor_entries':'#workforce','skills':'#workforce','test_sessions':'#quality','measurements':'#quality','releases':'#quality','test_specs':'#quality','shipments':'#delivery','shipment_units':'#delivery','orders':'#delivery','order_lines':'#delivery','delivery_plans':'#delivery','inventory_movements':'#supply','inventory_opening':'#supply','inventory_status_events':'#supply','purchase_lines':'#supply','receipts':'#supply','incoming_inspections':'#supply','genealogy':'#lineage','ar_opening':'#receivables','ar_events':'#receivables','invoices':'#receivables','payments':'#receivables'}

LINKS.update({ds:'#engineering' for ds in ['products','bom','routes','route_dependencies','projects','engineering_changes','project_milestones','change_actions']})

def digest(value):return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),default=str).encode()).hexdigest()
LINKS.update({ds:'#sales' for ds in ['quotes','quote_details','quote_order_links','quote_tasks']})
LINKS.update({ds:'#manufacturing' for ds in ['work_orders','batches','operations']})

def engine_hash():
    h=hashlib.sha256(analytics.AS_OF.encode())
    for name in ['data_health.py','schema.py','manufacturing_rules.py']:h.update((Path(__file__).parent/name).read_bytes())
    return h.hexdigest()

def canonical(value,kind):
    if kind=='str':return isinstance(value,str) and bool(value.strip()) and value==value.strip() and not value.startswith('=')
    if kind=='bool':return type(value) is bool
    if kind=='int':return type(value) is int
    if kind=='float':return type(value) in [int,float] and math.isfinite(value)
    if kind in ['date','datetime']:
        if not isinstance(value,str):return False
        try:
            if kind=='date':return date.fromisoformat(value).isoformat()==value
            parsed=datetime.fromisoformat(value)
            return parsed.tzinfo is None and parsed.isoformat(timespec='seconds')==value
        except ValueError:return False
    return False

def inspect(records,identities,batches):
    """One streaming pass; identities include referenced rows from every table."""
    totals={};issues=[]
    for ds,sp in SCHEMAS.items():
        totals[ds]={'dataset':ds,'rows':0,'fields':{f['name']:{'present':0,'missing':0,'invalid':0,'reference_present':0,'reference_missing':0,'minimum':None,'maximum':None,'future':0,'past_maximum':None} for f in sp['fields']},'batches':Counter()}
    for rec in records:
        ds=rec['dataset']
        if ds not in totals:continue
        sp=SCHEMAS[ds];r=rec['values'];out=totals[ds];out['rows']+=1;out['batches'][str(rec['source_row__batch_id'])]+=1
        def issue(rule,field,message):issues.append({'dataset':ds,'record_id':rec['id'],'key':rec['business_key'],'rule':rule,'field':field,'message':message,'record_hash':rec['record_hash']})
        if not isinstance(r,dict):issue('type','', '记录内容不是字段对象');continue
        if r.get(sp['primary_key'])!=rec['business_key']:issue('key',sp['primary_key'],'记录内主键与入库身份不一致')
        for field in sp['fields']:
            name=field['name'];value=r.get(name);cell=out['fields'][name]
            missing=value is None or isinstance(value,str) and not value.strip()
            if missing:
                cell['missing']+=1
                if field['required']:issue('required',name,'必填字段缺失')
                continue
            cell['present']+=1
            if not canonical(value,field['type']):
                cell['invalid']+=1;issue('type',name,'存储类型或标准格式与字段约定不一致');continue
            if field['reference']:
                cell['reference_present']+=1
                if (field['reference'],value) not in identities:cell['reference_missing']+=1;issue('reference',name,'声明的引用记录不存在')
            if field['type'] in ['date','datetime']:
                cell['minimum']=min(cell['minimum'],value) if cell['minimum'] else value;cell['maximum']=max(cell['maximum'],value) if cell['maximum'] else value
                future=value[:10]>analytics.AS_OF[:10] if field['type']=='date' else value>analytics.AS_OF
                if future:cell['future']+=1
                else:cell['past_maximum']=max(cell['past_maximum'],value) if cell['past_maximum'] else value
        for problem in manufacturing_issues(ds,r):issue('manufacturing',problem['field'],problem['code']+'：'+problem['message'])
        if rec['record_hash']!=fingerprint(r):issue('hash','','当前字段内容与保存摘要不一致')
        if rec['source_row__dataset']!=ds or rec['source_row__business_key']!=rec['business_key'] or rec['source_row__record_hash']!=rec['record_hash'] or rec['source_row__normalized']!=r:
            issue('source','','正式记录与绑定来源行的身份、内容或摘要不一致')
    for out in totals.values():
        out['batches']=[{**batches.get(key,{'id':key,'missing':True}),'records':n} for key,n in sorted(out['batches'].items())]
    return {'as_of':analytics.AS_OF,'datasets':totals,'issues':issues,'rules':RULES,'note':NOTE,'unknown_datasets':sorted({ds for ds,key in identities if ds not in SCHEMAS})}

@transaction.atomic
def run(user,request_id):
    if not access.can_edit(user):from django.core.exceptions import PermissionDenied;raise PermissionDenied('仅管理员或分析师可运行基础检查')
    rid=uuid.UUID(str(request_id));previous=DataQualityScan.objects.filter(request_id=rid).first()
    if previous:
        if previous.actor!=user.username:raise ValueError('请求标识已被其他账号使用')
        return previous
    rev=list(analytics.revision());identities=set(Record.objects.values_list('dataset','business_key'))
    batches={str(b.pk):{'id':str(b.pk),'filename':b.filename,'committed_at':b.committed_at.isoformat() if b.committed_at else None,'status':b.status,'file_hash':b.file_hash} for b in ImportBatch.objects.all()}
    fields=['id','dataset','business_key','values','record_hash','source_row__batch_id','source_row__dataset','source_row__business_key','source_row__record_hash','source_row__normalized']
    result=inspect(Record.objects.order_by('dataset','business_key').values(*fields).iterator(chunk_size=1000),identities,batches)
    scan=DataQualityScan.objects.create(request_id=rid,actor=user.username,source_revision=rev,engine_hash=engine_hash(),snapshot=result,snapshot_hash=digest(result))
    AuditEvent.objects.create(action='data_health.scan',actor=user.username,object_type='DataQualityScan',object_id=str(scan.pk),detail={'source_revision':rev,'engine_hash':scan.engine_hash,'records':sum(x['rows'] for x in result['datasets'].values()),'issues':len(result['issues']),'snapshot_hash':scan.snapshot_hash,'business_facts_changed':False})
    return scan

def policy_info(policy,ds):
    defaults={'dataset':ds,'owner':'','business_clock':'','max_business_lag_days':None,'max_import_age_hours':None,'note':'','version':0,'updated_by':'','updated_at':None}
    return {k:getattr(policy,k) for k in defaults} if policy else defaults

def freshness(row,policy,now,as_of):
    field=row['fields'].get(policy['business_clock']);lag=None;latest=None
    if field and field['past_maximum']:
        latest=field['past_maximum'];lag=(date.fromisoformat(as_of[:10])-date.fromisoformat(latest)).days if len(latest)==10 else (datetime.fromisoformat(as_of)-datetime.fromisoformat(latest)).total_seconds()/86400
    times=[];invalid_batches=0
    for b in row['batches']:
        try:
            t=datetime.fromisoformat(b['committed_at'])
            if t.tzinfo is None or t>now:raise ValueError()
            times.append(t)
        except (ValueError,TypeError,KeyError):invalid_batches+=1
    last=max(times) if times else None;first=min(times) if times else None;hours=(now-last).total_seconds()/3600 if last else None
    flags=[]
    if policy['max_business_lag_days'] is not None:
        flags+=['business_unknown' if lag is None else 'business_late' if lag>policy['max_business_lag_days'] else 'business_within']
    if policy['max_import_age_hours'] is not None:
        flags+=['import_unknown' if hours is None or invalid_batches else 'import_late' if hours>policy['max_import_age_hours'] else 'import_within']
    return {'business_latest':latest,'business_lag_days':lag,'last_commit':last.isoformat() if last else None,'first_commit':first.isoformat() if first else None,'import_age_hours':hours,'invalid_batch_times':invalid_batches,'future_dates':field['future'] if field else None,'flags':flags,'has_target':bool(flags)}

def project(scan,user,now=None):
    if scan.snapshot_hash!=digest(scan.snapshot):raise ValueError('检查快照摘要不一致，暂停显示；请保留证据后重新运行')
    now=now or timezone.now();policies={p.dataset:p for p in DataMonitorPolicy.objects.all()};visible={ds for ds in SCHEMAS if access.allowed(user,ds)}
    permitted={ds:{f['name'] for f in access.permitted_fields(user,ds)} for ds in visible}
    issues=[i for i in scan.snapshot['issues'] if i['dataset'] in visible and (not i['field'] or i['field'] in permitted[i['dataset']])];counts=Counter(i['dataset'] for i in issues);affected=defaultdict(set)
    for i in issues:affected[i['dataset']].add(i['record_id'])
    rows=[]
    for ds in sorted(visible):
        original=scan.snapshot['datasets'].get(ds)
        if not original:continue
        schema=SCHEMAS[ds];p=policy_info(policies.get(ds),ds);row={**original,'fields':{k:v for k,v in original['fields'].items() if k in permitted[ds]},'label':schema['label'],'department':schema['department'],'policy':p,'issue_count':counts[ds],'affected_rows':len(affected[ds]),'business_href':LINKS.get(ds,'')}
        row['freshness']=freshness(row,p,now,scan.snapshot['as_of']);row['not_checked_fields']=sorted(permitted[ds]-set(row['fields']));row['required_cells']=sum(row['fields'][f['name']]['present']+row['fields'][f['name']]['missing'] for f in schema['fields'] if f['required'] and f['name'] in row['fields']);row['missing_required']=sum(row['fields'][f['name']]['missing'] for f in schema['fields'] if f['required'] and f['name'] in row['fields'])
        row['flags']=['all']+(['empty'] if not row['rows'] else [])+(['issues'] if row['issue_count'] else [])+(['no_target'] if not row['freshness']['has_target'] else [])+(['late'] if any(x.endswith('_late') for x in row['freshness']['flags']) else [])
        rows.append(row)
    return {'id':str(scan.pk),'checked_at':scan.created_at.isoformat(),'as_of':scan.snapshot['as_of'],'source_revision':scan.source_revision,'engine_hash':scan.engine_hash,'snapshot_hash':scan.snapshot_hash,'stale':scan.source_revision!=list(analytics.revision()) or scan.engine_hash!=engine_hash(),'rows':rows,'issues':issues,'now':now.isoformat(),'note':scan.snapshot.get('note',NOTE),'unknown_dataset_count':len(scan.snapshot['unknown_datasets']) if access.can_edit(user) else None}

STAGES={'all':'全部源表','issues':'有基础检查问题','empty':'尚无入库记录','no_target':'未设时效目标','late':'超过已设目标'}
def filters(q):
    if set(q)-{'department','dataset','stage','q','rule','page','scan','kind'}:raise ValueError('不支持的数据质量筛选')
    f={k:q.get(k,'') for k in ['department','dataset','q','rule']};f['stage']=q.get('stage','all')
    if f['stage'] not in STAGES or f['rule'] and f['rule'] not in RULES:raise ValueError('检查状态或规则不可用')
    if any(len(v)>150 for v in f.values()):raise ValueError('筛选内容过长')
    return f

def select(rows,f):return [r for r in rows if (not f['department'] or r['department']==f['department']) and (not f['dataset'] or r['dataset']==f['dataset']) and f['stage'] in r['flags'] and (not f['q'] or f['q'].casefold() in (r['dataset']+' '+r['label']+' '+r['department']).casefold())]
