"""Immutable, private BI receipts. Frozen evidence never follows current Record pointers."""
import json,uuid
from collections import defaultdict
from django.core.exceptions import ValidationError,PermissionDenied
from django.core.serializers.json import DjangoJSONEncoder
from django.db import transaction
from . import topic_workspace as ws,access,analytics
from .analysis_engine import selected_rows,group_key,validate_raw_definition
from .models import Topic,AnalysisModel,TopicSnapshot,Record,AuditEvent
from .semantic_schema import SEMANTIC_SCHEMAS
from .import_review import ReviewConflict
from . import bi_card_summary

NOTICE='结果快照固定保存时的数值、条件、模型定义和当时可见的来源行；不是全数据库复算包。不是自动结账或业务批准，也不补建过去未保存的历史。源Excel保存在导入归档中；设备原始附件未因此接入。'
MAX_OBJECTS=20000
MAX_SOURCES=100000
MAX_BYTES=20*1024*1024

def info(s):
    return {'id':str(s.pk),'topic_id':s.topic_id,'name':s.name,'note':s.note,'created_at':s.created_at,
            'payload_hash':s.payload_hash,'as_of':s.payload['result']['as_of'],'cards':len(s.payload['result']['cards']),
            'source_count':len(s.payload['sources']),'object_count':sum(len(rows) for card in s.payload['cohorts'].values() for rows in card.values()),'notice':NOTICE}

def authorize(user,s):
    # Read old definitions without resolving current metric versions, which may be retired.
    ws.visible(user,Topic.objects.all()).get(pk=s.topic_id)
    for card in s.payload['result']['cards']:
        m=card['model']
        if not ws.visible(user,AnalysisModel.objects.all()).filter(pk=m['id']).exists():raise PermissionDenied('快照包含当前不可访问的模型，暂不可读取')
        try:validate_raw_definition(user,m['dataset'],card['primary']['resolved_definition'])
        except (ValidationError,KeyError):raise PermissionDenied('快照包含当前不可访问的指标，暂不可读取')
    for dataset,fields in s.payload['fields'].items():
        if not access.allowed(user,dataset) or not {f['name'] for f in fields}<={f['name'] for f in access.permitted_fields(user,dataset)}:
            raise PermissionDenied('快照包含当前不可访问的来源字段，暂不可读取')

def get(user,topic_id,snapshot_id):
    s=TopicSnapshot.objects.get(pk=snapshot_id,topic_id=topic_id,owner=user)
    verify(s);authorize(user,s)
    return s

def verify(s):
    receipt={'name':s.name,'note':s.note,'owner_id':s.owner_id,'topic_id':s.topic_id,'request_id':str(s.request_id)}
    if ws.digest(s.payload)!=s.payload_hash or s.payload.get('receipt')!=receipt:raise ReviewConflict('快照完整性核验未通过，已暂停读取；请核对备份')

def listing(user,topic_id,page=1):
    ws.visible(user,Topic.objects.all()).get(pk=topic_id)
    if type(page) is not int or not 1<=page<=10000:raise ValidationError('页码无效')
    query=TopicSnapshot.objects.filter(owner=user,topic_id=topic_id).order_by('-created_at','id');rows=[]
    for s in query[(page-1)*20:page*20]:
        try:verify(s);authorize(user,s)
        except (PermissionDenied,Topic.DoesNotExist,ReviewConflict):
            rows.append({'id':str(s.pk),'available':False,'created_at':s.created_at});continue
        rows.append({**info(s),'available':True})
    return {'rows':rows,'page':page,'size':20,'total':query.count(),'notice':NOTICE}

def capture(user,result,binding):
    if not result['cards']:raise ValidationError('空专题没有可保存的分析结果')
    if any(not c.get('available') or c.get('error') or c['primary']['truncated'] or c.get('reference',{}).get('truncated') for c in result['cards']):
        raise ValidationError('请先处理未计算、无权限或超过分组上限的卡片，再保存完整结果快照')
    fields={};cohorts={};wanted=defaultdict(set);objects=0
    for card in result['cards']:
        model=card['model'];ds=model['dataset'];fields[ds]=access.permitted_fields(user,ds);cohorts[str(card['slot'])]={}
        for side in ['primary','reference']:
            if side not in card:continue
            scope=result['config']['scope' if side=='primary' else 'reference_scope']
            rows,_,_=selected_rows(user,ds,model['definition'],scope);objects+=len(rows)
            summary=card.get('scope_summary',{}).get(side)
            if summary and summary['population_digest']!=bi_card_summary.digest(sorted(rows,key=lambda r:str(r['id']))):raise ReviewConflict('摘要与保存的来源对象已变化，请重新运行后保存')
            if objects>MAX_OBJECTS:raise ValidationError('快照超过20000个来源对象，请缩小范围或拆分专题')
            frozen=[]
            for row in sorted(rows,key=lambda r:str(r['id'])):
                refs=row.get('_sources',[]) if ds in SEMANTIC_SCHEMAS else [{'dataset':ds,'key':str(row['id'])}]
                permitted={(ref['dataset'],str(ref['key'])) for ref in refs if access.allowed(user,ref['dataset'])}
                for dataset,key in permitted:wanted[dataset].add(key)
                frozen.append({'id':str(row['id']),'group':group_key(row,card[side]['resolved_definition']),
                               'values':access.sanitize(user,ds,row),'sources':[ws.digest([d,k]) for d,k in sorted(permitted)],
                               'omitted_sources':len({(r['dataset'],str(r['key'])) for r in refs})-len(permitted)})
            cohorts[str(card['slot'])][side]=frozen
    if sum(len(v) for v in wanted.values())>MAX_SOURCES:raise ValidationError('快照来源记录过多，请缩小范围')
    sources={}
    for ds,keys in sorted(wanted.items()):
        fields[ds]=access.permitted_fields(user,ds);keys=sorted(keys)
        for offset in range(0,len(keys),400):
            for r in Record.objects.filter(dataset=ds,business_key__in=keys[offset:offset+400]).select_related('source_row__batch'):
                row=r.source_row;b=row.batch
                sources[ws.digest([ds,r.business_key])]={'dataset':ds,'key':r.business_key,'values':access.sanitize(user,ds,r.values),
                    'record_id':r.pk,'revision':r.revision,'record_hash':r.record_hash,'source_row_id':row.pk,
                    'batch_id':str(b.pk),'filename':b.filename,'file_hash':b.file_hash,'sheet':row.sheet,'row':row.row_number}
        missing=[key for key in keys if ws.digest([ds,key]) not in sources]
        if missing:raise ValidationError('来源引用缺少正式记录，不能保存完整证据；请先核对导入')
    payload={'format_version':1,'result':result,'binding':binding,'fields':fields,'cohorts':cohorts,'sources':sources,'notice':NOTICE}
    serialized=json.dumps(payload,ensure_ascii=False,allow_nan=False,cls=DjangoJSONEncoder)
    if len(serialized.encode())>MAX_BYTES:raise ValidationError('快照超过20MB，请缩小范围或拆分专题')
    return json.loads(serialized)

@transaction.atomic
def create(user,topic_id,data):
    required={'request_id','context_token','facts_token','config','name','note'}
    if not required<=set(data) or set(data)-required-{'summary_token'}:raise ValidationError('快照保存参数不完整或包含不支持字段')
    if 'summary_token' in data and (not isinstance(data['summary_token'],str) or len(data['summary_token'])!=64):raise ValidationError('摘要凭据格式无效，请刷新专题')
    rid=uuid.UUID(str(data['request_id']));request_hash=ws.digest({'topic_id':topic_id,**data})
    previous=TopicSnapshot.objects.filter(request_id=rid).first()
    if previous:
        if previous.owner_id!=user.pk or previous.topic_id!=topic_id or previous.request_hash!=request_hash:raise ReviewConflict('申请号已用于另一份快照，不能更换内容重试')
        return get(user,topic_id,previous.pk)
    name=ws.clean_text(data['name'],'快照名称',120);note=ws.clean_text(data['note'],'保存说明',1000)
    if len(note)<5:raise ValidationError('请填写至少5字的保存用途或复盘说明')
    if TopicSnapshot.objects.filter(owner=user).count()>=100:raise ValidationError('本地演示每人最多100份快照，请先规划归档容量')
    ctx=ws.context(user,topic_id);ws.require_context(ctx,data['context_token'])
    result=ws.run(user,topic_id,{'context_token':data['context_token'],'config':data['config']})
    if result['facts_token']!=data['facts_token']:raise ReviewConflict('数据已变化，请重新运行专题，确认结果后保存')
    if 'summary_token' in data and result['summary_token']!=data['summary_token']:raise ReviewConflict('摘要来源、算法或权限已变化，请重新运行后核对保存')
    payload=capture(user,result,ctx['binding'])
    if any(c['scope_summary']['primary']['algorithm']!=bi_card_summary.algorithm(c['model']['dataset']) for c in result['cards']):raise ReviewConflict('摘要算法在保存期间变化，请重新运行后保存')
    payload['receipt']={'name':name,'note':note,'owner_id':user.pk,'topic_id':topic_id,'request_id':str(rid)}
    if ws.digest(analytics.revision())!=result['facts_token'] or ws.context(user,topic_id)['context_token']!=result['context_token']:
        raise ReviewConflict('保存期间数据、模型或访问权限已变，请重新运行后保存')
    s=TopicSnapshot.objects.create(owner=user,topic_id=topic_id,request_id=rid,request_hash=request_hash,name=name,note=note,payload=payload,payload_hash=ws.digest(payload))
    AuditEvent.objects.create(action='topic_snapshot.create',actor=user.username,object_type='TopicSnapshot',object_id=str(s.pk),
        detail={'name':s.name,'topic_id':topic_id,'payload_hash':s.payload_hash,'source_count':len(payload['sources']),'business_facts_changed':False})
    return s

def detail(user,topic_id,snapshot_id):
    s=get(user,topic_id,snapshot_id)
    return {**info(s),'result':s.payload['result']}

def evidence(user,topic_id,snapshot_id,data):
    if set(data)-{'slot','side','group','page','selection'} or not {'slot','side','group','page'}<=set(data):raise ValidationError('快照来源参数无效')
    s=get(user,topic_id,snapshot_id);slot,side,page=data['slot'],data['side'],data['page']
    if type(slot) is not int or str(slot) not in s.payload['cohorts'] or side not in s.payload['cohorts'][str(slot)]:raise ValidationError('所选分析卡或范围不存在')
    if type(page) is not int or not 1<=page<=100000 or (data['group'] is not None and (not isinstance(data['group'],str) or len(data['group'])>300)):raise ValidationError('页码或分组值无效')
    rows=s.payload['cohorts'][str(slot)][side]
    if 'selection' in data:
        if data['group'] is not None:raise ValidationError('透视来源不可同时指定旧分组')
        card=next(c for c in s.payload['result']['cards'] if c['slot']==slot)
        result=card[side]
        if not result.get('pivot'):raise ValidationError('此快照不是透视结果')
        from .analysis_pivot import select
        chosen={r['id'] for r in select([r['values'] for r in rows],result['resolved_definition'],data['selection'],result['pivot'])}
        rows=[r for r in rows if r['id'] in chosen]
    elif data['group'] is not None:rows=[r for r in rows if r['group']==data['group']]
    model=next(c['model'] for c in s.payload['result']['cards'] if c['slot']==slot)
    # The large per-object manifest is a separate paginated endpoint, not embedded here.
    return {'total':len(rows),'page':page,'size':30,'fields':s.payload['fields'][model['dataset']],
            'rows':[{k:v for k,v in r.items() if k!='sources'}|{'source_count':len(r['sources'])} for r in rows[(page-1)*30:page*30]],'payload_hash':s.payload_hash}

def source_evidence(user,topic_id,snapshot_id,data):
    if set(data)!={'slot','side','object_id','page'}:raise ValidationError('快照原始记录参数无效')
    s=get(user,topic_id,snapshot_id);slot,side,page=data['slot'],data['side'],data['page']
    if type(slot) is not int or str(slot) not in s.payload['cohorts'] or side not in s.payload['cohorts'][str(slot)]:raise ValidationError('所选分析卡或范围不存在')
    if type(page) is not int or not 1<=page<=100000 or not isinstance(data['object_id'],str):raise ValidationError('页码或对象编号无效')
    row=next((r for r in s.payload['cohorts'][str(slot)][side] if r['id']==data['object_id']),None)
    if row is None:raise ValidationError('对象不属于保存范围')
    rows=[s.payload['sources'][k] for k in row['sources'][(page-1)*20:page*20]]
    return {'total':len(row['sources']),'page':page,'size':20,'rows':rows,'omitted_sources':row['omitted_sources'],'fields':{r['dataset']:s.payload['fields'][r['dataset']] for r in rows},'payload_hash':s.payload_hash}

def unit_sets(payload_now,payload_old,card,side):
    ds=card['model']['dataset'];fields={f['name']:f for f in payload_old['fields'][ds]};sets=defaultdict(set)
    for i,m in enumerate(card[side]['resolved_definition']['metrics']):
        field=m.get('field');unit=fields.get(field,{}).get('unit_field')
        if unit and m['agg'] not in ['count','distinct']:
            for index,p in enumerate([payload_now,payload_old]):
                for r in p['cohorts'][str(card['slot'])][side]:
                    if r['values'].get(field) is not None:sets[(r['group'],f'm{i}',index)].add(r['values'].get(unit))
    return sets

@transaction.atomic
def compare_current(user,topic_id,snapshot_id):
    s=get(user,topic_id,snapshot_id);old=s.payload;ctx=ws.context(user,topic_id)
    if ctx['binding']!=old['binding']:return {'blocked':True,'note':'专题、模型或计算口径已变；原快照仍可读取，暂停把当前值与旧值相减。请先核对定义。'}
    try:result=ws.run(user,topic_id,{'context_token':ctx['context_token'],'config':old['result']['config']})
    except ReviewConflict as ex:return {'blocked':True,'note':str(ex)}
    try:now=capture(user,result,ctx['binding'])
    except ValidationError as ex:return {'blocked':True,'note':'当前计算无法形成完整可比结果：'+'；'.join(ex.messages)}
    cards=[]
    for c,previous in zip(result['cards'],old['result']['cards']):
        for side in ['primary','reference']:
            if side not in c:continue
            current_rows={r['id']:r for r in now['cohorts'][str(c['slot'])][side]};old_rows={r['id']:r for r in old['cohorts'][str(c['slot'])][side]}
            cards.append({'slot':c['slot'],'name':c['model']['name'],'side':side,'measures':c[side]['measures'],'dimension_label':c[side]['dimension_label'],
                          'scope_summary_comparison':bi_card_summary.compare(c.get('scope_summary',{}).get(side),previous.get('scope_summary',{}).get(side)),
                          'comparison':ws.compare(c[side],previous[side],unit_sets(now,old,c,side)),
                          **({'current_result':c[side]} if c[side].get('pivot') else {}),
                          'added_objects':len(current_rows.keys()-old_rows.keys()),'removed_objects':len(old_rows.keys()-current_rows.keys()),
                          'changed_objects':sum(current_rows[k]!=old_rows[k] for k in current_rows.keys()&old_rows.keys())})
    old_refs,now_refs=old['sources'],now['sources']
    if result['facts_token']!=ws.digest(analytics.revision()) or ctx['context_token']!=ws.context(user,topic_id)['context_token']:raise ReviewConflict('比较期间数据或模型变化，请重试')
    return {'blocked':False,'cards':cards,'current_facts_token':result['facts_token'],'saved_facts_token':old['result']['facts_token'],
            'source_added':len(now_refs.keys()-old_refs.keys()),'source_removed':len(old_refs.keys()-now_refs.keys()),
            'source_changed':sum(now_refs[k]!=old_refs[k] for k in now_refs.keys()&old_refs.keys()),
            'note':'两次使用同一范围与定义核对来源；普通分组与透视行列均展示当前值减保存值；合计比较各次独立汇总结果。新增、移出或更正的事实均可能影响结果；这不是自然期间同比，也不表示原因。原快照未修改。'}

def export_rows(s):
    # Export only the frozen contract; later explanatory-text changes must not alter it.
    def evidence(cell,key=None):
        values=cell.get('quantiles',{})
        if key is not None:values={key:values[key]} if key in values else {}
        return json.dumps({'notice':r.get('quantile_notice',''),'samples':values},ensure_ascii=False,separators=(',',':')) if values else ''
    result=s.payload['result'];rows=[['快照名称','快照标识','保存时间','快照摘要','状态截止','当前范围','对照范围','模型','模型版本','范围名称','分组','度量','数值','单位','来源行数']]
    linked=bool(result['config'].get('links'))
    statistical=any(c.get(side,{}).get('quantile_notice') for c in result['cards'] for side in ['primary','reference'])
    if statistical:rows[0].append('分位数计算与样本依据')
    for c in result['cards']:
        for side in ['primary','reference']:
            if side not in c:continue
            r=c[side]
            if r.get('scatter'):
                for point in r['scatter']['points']:
                    for axis,a in r['scatter']['axes'].items():
                        rows.append([s.name,str(s.pk),s.created_at.isoformat(),s.payload_hash,result['as_of'],json.dumps(result['config']['scope'],ensure_ascii=False),json.dumps(result['config']['reference_scope'],ensure_ascii=False),c['model']['name'],c['model']['version'],result['config']['primary_label' if side=='primary' else 'reference_label'],json.dumps({'分组':point['dimension'],'坐标轴':axis,'完整输入行数':point['valid_inputs'][axis],'绘点':point['plotted'],'说明':point['reason']},ensure_ascii=False),a['label'],point[axis],a['unit'],point['row_count'],*([evidence(next((row for row in r['rows'] if row['dimension']==point['dimension']),{}),a['key'])] if statistical else [])])
                continue
            if r.get('pivot'):
                from .analysis_pivot import export_rows as pivot_export
                # Long-form cell and margin rows keep explicit axis labels and result type.
                p=r['pivot'];cells=[*p['cells'],*p['row_totals'],*p['column_totals'],p['grand_total']]
                for x,cell in zip(pivot_export(r)[1:],cells):
                    for i,m in enumerate(r['measures']):
                        rows.append([s.name,str(s.pk),s.created_at.isoformat(),s.payload_hash,result['as_of'],json.dumps(result['config']['scope'],ensure_ascii=False),json.dumps(result['config']['reference_scope'],ensure_ascii=False),c['model']['name'],c['model']['version'],result['config']['primary_label' if side=='primary' else 'reference_label'],json.dumps({'类型':x[0],'行':x[1],'列':x[2],'说明':cell['reason']},ensure_ascii=False),m['label'],x[3+i],m.get('unit','见保存模型字段口径'),x[-2],*([evidence(cell,m['key'])] if statistical else [])])
                continue
            for row in r['rows']:
                for m in r['measures']:
                    rows.append([s.name,str(s.pk),s.created_at.isoformat(),s.payload_hash,result['as_of'],json.dumps(result['config']['scope'],ensure_ascii=False),json.dumps(result['config']['reference_scope'],ensure_ascii=False),
                        c['model']['name'],c['model']['version'],result['config']['primary_label' if side=='primary' else 'reference_label'],row['dimension'],m['label'],row[m['key']],m.get('unit','见保存模型字段口径'),row['row_count'],*([evidence(row,m['key'])] if statistical else [])])
    if linked:
        rows[0].append('保存的联动条件与逐卡直接字段')
        saved_links=json.dumps(dict(config=result['config']['links'],cards=[dict(slot=c['slot'],model_id=c['model']['id'],mapping=c['linkage']) for c in result['cards']]),ensure_ascii=False)
        for row in rows[1:]:
            row.append(saved_links)
    return rows
