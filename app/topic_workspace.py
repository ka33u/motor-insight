"""Personal BI views and same-definition range comparisons, with explicit drift checks."""
import hashlib,json,math
from collections import defaultdict,Counter
from decimal import Decimal
from django.core.exceptions import ValidationError,PermissionDenied
from django.db import transaction
from django.db.models import Q
from . import access,analytics,bi_scope,metric_registry,topic_linkage
from .models import Topic,AnalysisModel,TopicView,AuditEvent,Record
from .analysis_engine import validate_definition,run_analysis,selected_rows,group_key
from .import_review import ReviewConflict
from .semantic_schema import SEMANTIC_SCHEMAS

NOTICE='保存分析条件与模型版本依据，不冻结数据。每次打开读取当前已导入记录；日期选择业务对象，不重放当时状态。视角仅本人使用，管理员保留平台审计权限。'
COMPARE_NOTE='同一张卡两边使用相同模型，按相同分组值对齐；日期分组不自动平移。缺少分组或数值不补零；比例之差用百分点。范围可重叠，样本结构差异不能直接解释为效率变化或因果关系。'

def digest(value):return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,default=str).encode()).hexdigest()
def visible(user,query):return query if access.role(user)=='admin' else query.filter(Q(owner=user.username)|Q(is_public=True))
def clean_text(value,label,limit):
    if not isinstance(value,str) or not 1<=len(value.strip())<=limit:raise ValidationError(f'{label}须为1—{limit}字')
    return value.strip()
def config(data):
    keys={'scope','reference_scope','primary_label','reference_label'}
    if not isinstance(data,dict) or not keys<=set(data) or set(data)-keys-{'links'}:raise ValidationError('分析视角需包含当前范围、对照范围及两侧名称')
    if not isinstance(data['scope'],dict):raise ValidationError('当前范围须为对象')
    value={'scope':bi_scope.validate_scope(data['scope']),
            'reference_scope':None if data['reference_scope'] is None else bi_scope.validate_scope(data['reference_scope']),
            'primary_label':clean_text(data['primary_label'],'当前范围名称',30),
            'reference_label':clean_text(data['reference_label'],'对照范围名称',30)}
    if 'links' in data:value['links']=topic_linkage.validate(data['links'])
    return value

def context(user,topic_id):
    t=visible(user,Topic.objects.all()).get(pk=topic_id);cards=[];bindings=[]
    for index,c in enumerate(t.layout):
        m=visible(user,AnalysisModel.objects.all()).filter(pk=c['model_id']).first()
        available=bool(m)
        if m:
            try:validate_definition(user,m.dataset,m.definition,allow_inactive=True)
            except (ValidationError,KeyError,TypeError):available=False
        binding={'slot':index,'model_id':c['model_id'],'available':available}
        card={'slot':index,'span':c.get('span',1),'available':available}
        if available:
            binding.update(version=m.version,dataset=m.dataset,definition_hash=digest(m.definition),calculation_hash=metric_registry.calculation_hash(m.dataset))
            card.update(model={'id':m.pk,'name':m.name,'dataset':m.dataset,'definition':m.definition,'version':m.version},contract=bi_scope.contract(m.dataset),link_contract=topic_linkage.contract(user,m.dataset))
        bindings.append(binding);cards.append(card)
    manifest={'topic_id':t.pk,'topic_version':t.version,'cards':bindings}
    return {'topic':{'id':t.pk,'name':t.name,'description':t.description,'version':t.version,'can_edit':access.can_edit(user) and (t.owner==user.username or access.role(user)=='admin')},
            'cards':cards,'binding':manifest,'context_token':digest(manifest),'notice':NOTICE,'compare_note':COMPARE_NOTE,'linkage':topic_linkage.metadata()}

def require_context(ctx,token):
    if not isinstance(token,str) or token!=ctx['context_token']:raise ReviewConflict('专题、模型或访问条件已变化，请刷新并重新核对分析视角；未自动替换已保存定义')

def view_info(v,ctx):
    old={x['slot']:x for x in v.binding.get('cards',[])};new={x['slot']:x for x in ctx['binding']['cards']}
    changes=[]
    if v.binding.get('topic_version')!=ctx['binding']['topic_version']:changes.append({'kind':'topic','before':v.binding.get('topic_version'),'after':ctx['binding']['topic_version']})
    for slot in sorted(set(old)|set(new)):
        if old.get(slot)!=new.get(slot):changes.append({'kind':'card','slot':slot,'before_version':old.get(slot,{}).get('version'),'after_version':new.get(slot,{}).get('version'),'available':new.get(slot,{}).get('available',False)})
    linkage_stale=bool(v.config.get('links') and (v.config['links'].get('rules_hash')!=topic_linkage.rules_hash() or v.config['links'].get('revision')!=topic_linkage.REVISION))
    if linkage_stale:changes.append(dict(kind='linkage',before=v.config['links'].get('revision'),after=topic_linkage.REVISION))
    return {'id':v.pk,'topic_id':v.topic_id,'name':v.name,'config':v.config,'version':v.version,'archived':v.archived,
            'binding_token':digest(v.binding),'stale':v.binding!=ctx['binding'] or linkage_stale,'linkage_stale':linkage_stale,'changes':changes,'created_at':v.created_at,'updated_at':v.updated_at,'notice':NOTICE}

def list_views(user,ctx,archived=False):
    return [view_info(v,ctx) for v in TopicView.objects.filter(owner=user,topic_id=ctx['topic']['id'],archived=archived).order_by('-updated_at','id')]

def audit(user,action,v,before):
    snapshot=lambda:{'name':v.name,'config':v.config,'binding':v.binding,'version':v.version,'archived':v.archived,'topic_id':v.topic_id}
    AuditEvent.objects.create(action='topic_view.'+action,actor=user.username,object_type='TopicView',object_id=str(v.pk),detail={'before':before,'after':snapshot()})

def snapshot(v):return {'name':v.name,'config':v.config,'binding':v.binding,'version':v.version,'archived':v.archived,'topic_id':v.topic_id}

@transaction.atomic
def save_view(user,topic_id,data,view_id=None):
    expected={'name','config','context_token'}|({'version','rebind','reason'} if view_id else set())
    if set(data)!=expected:raise ValidationError('保存参数不完整或包含不支持字段')
    ctx=context(user,topic_id);require_context(ctx,data['context_token']);definition=config(data['config']);name=clean_text(data['name'],'视角名称',120)
    if view_id:
        v=TopicView.objects.select_for_update().get(pk=view_id,topic_id=topic_id,owner=user)
        if type(data['version']) is not int or v.version!=data['version']:raise ReviewConflict('个人视角已更新，请重新打开后修改')
        if v.archived:raise ValidationError('请先恢复已归档视角')
        if type(data['rebind']) is not bool:raise ValidationError('请明确是否核对新定义')
        if v.binding!=ctx['binding'] and not data['rebind']:raise ReviewConflict('定义已变化，请先查看差异并明确按新定义保存')
        if data['rebind'] and (not isinstance(data['reason'],str) or not 5<=len(data['reason'].strip())<=1000):raise ValidationError('请填写5—1000字的重新核对依据')
        if not data['rebind'] and data['reason']:raise ValidationError('普通保存不接受定义重新核对依据')
        before=snapshot(v);v.version+=1
    else:
        if TopicView.objects.filter(owner=user).count()>=200:raise ValidationError('每人最多保留200个个人视角（含归档），请联系管理员整理')
        v=TopicView(owner=user,topic_id=topic_id);before=None
    v.name=name;v.config=definition;v.binding=ctx['binding'];v.save();audit(user,'save',v,before)
    if view_id and data['rebind']:
        AuditEvent.objects.create(action='topic_view.rebind',actor=user.username,object_type='TopicView',object_id=str(v.pk),detail={'reason':data['reason'],'from':before['binding'],'to':v.binding,'version':v.version})
    return view_info(v,ctx)

@transaction.atomic
def archive_view(user,topic_id,view_id,data):
    if set(data)!={'version','archived'} or type(data['archived']) is not bool:raise ValidationError('请提供视角版本及归档状态')
    ctx=context(user,topic_id);v=TopicView.objects.select_for_update().get(pk=view_id,owner=user,topic_id=topic_id)
    if type(data['version']) is not int or v.version!=data['version']:raise ReviewConflict('个人视角已更新，请刷新后操作')
    if v.archived==data['archived']:raise ValidationError('视角已处于该状态')
    before=snapshot(v);v.archived=data['archived'];v.version+=1;v.save();audit(user,'archive' if v.archived else 'restore',v,before)
    return view_info(v,ctx)

def finite(v):return type(v) in [float,int] and math.isfinite(v)

def compare(current,reference,unit_sets=None):
    if current.get('pivot') or reference.get('pivot'):
        from .pivot_comparison import compare as pivot_compare
        return pivot_compare(current,reference)
    if current['truncated'] or reference['truncated']:return {'blocked':True,'rows':[],'note':'至少一侧超过1000组；对照暂停，请缩小范围，避免把未返回的分组当作缺失。'}
    left={r['dimension']:r for r in current['rows']};right={r['dimension']:r for r in reference['rows']};rows=[]
    for name in sorted(set(left)|set(right)):
        a,b=left.get(name),right.get(name);values=[]
        for m in current['measures']:
            key=m['key'];av=a.get(key) if a else None;bv=b.get(key) if b else None
            proportion=m.get('unit')=='%' or (key=='m0' and current.get('metric_receipt',{} ) and current['metric_receipt']['unit']=='%') or (key.startswith('m') and current['resolved_definition']['metrics'][int(key[1:])]['agg']=='ratio')
            delta=relative=None;reason=''
            if a is None or b is None:reason='一侧无此分组，不补零'
            elif not finite(av) or not finite(bv):reason='一侧缺少有效数值或为非数值度量'
            elif unit_sets and ((name,key,0) in unit_sets or (name,key,1) in unit_sets) and (unit_sets.get((name,key,0),set())!=unit_sets.get((name,key,1),set()) or None in unit_sets.get((name,key,0),set()) or None in unit_sets.get((name,key,1),set())):reason='两侧计量单位不同或未知，差值暂停'
            else:
                delta=float(Decimal(str(av))-Decimal(str(bv)))
                if not math.isfinite(delta):delta=None;reason='差值超出数值范围'
                elif proportion:reason='比例仅显示百分点差，不计算增长率'
                elif bv>0:
                    relative=float(Decimal(str(delta))/Decimal(str(bv))*100)
                    if not math.isfinite(relative):relative=None;reason='相对变化超出数值范围'
                else:reason='对照值为零或负数，不计算相对变化'
            values.append({'key':key,'primary':av,'reference':bv,'delta':delta,'relative_pct':relative,'delta_unit':'百分点' if proportion else '同指标单位','reason':reason})
        rows.append({'dimension':name,'primary_rows':a['row_count'] if a else None,'reference_rows':b['row_count'] if b else None,'values':values})
    return {'blocked':False,'rows':rows,'note':COMPARE_NOTE}

def mixed_unit_sets(user,model,conf,result):
    fields={f['name']:f for f in access.permitted_fields(user,model['dataset'])};dynamic={}
    for i,m in enumerate(result['resolved_definition']['metrics']):
        if m['agg'] not in ['count','distinct'] and fields.get(m.get('field'),{}).get('unit_field'):dynamic[f'm{i}']=(m['field'],fields[m['field']]['unit_field'])
    if not dynamic:return None
    units=defaultdict(set)
    for side,scope in enumerate([conf['scope'],conf['reference_scope']]):
        rows,_,_=selected_rows(user,model['dataset'],model['definition'],scope)
        for r in rows:
            for key,(field,unit) in dynamic.items():
                if r.get(field) is not None:units[(group_key(r,model['definition']),key,side)].add(r.get(unit))
    return units

def comparability(user,model,conf):
    cohorts=[selected_rows(user,model['dataset'],model['definition'],scope)[0] for scope in [conf['scope'],conf['reference_scope']]]
    ids=[{str(r['id']) for r in rows} for rows in cohorts]
    has_config=any(f['name']=='product_id' for f in access.permitted_fields(user,model['dataset']))
    out={'primary_objects':len(ids[0]),'reference_objects':len(ids[1]),'overlap_objects':len(ids[0]&ids[1]),'configuration_available':has_config}
    if has_config:
        counts=[Counter(r.get('product_id') for r in rows if r.get('product_id')) for rows in cohorts]
        out.update(primary_configurations=dict(sorted(counts[0].items())),reference_configurations=dict(sorted(counts[1].items())),
                   shared_configuration_count=len(set(counts[0])&set(counts[1])),primary_unknown_configuration=sum(not r.get('product_id') for r in cohorts[0]),reference_unknown_configuration=sum(not r.get('product_id') for r in cohorts[1]))
        totals=[sum(c.values()) for c in counts]
        out['same_configuration_mix']=bool(all(totals)) and all(counts[0][key]*totals[1]==counts[1][key]*totals[0] for key in set(counts[0])|set(counts[1]))
        out['note']='配置分布按此模型来源行计数，不代表按产量加权结构；相同配置仍需核实数量、批量、工艺、材料及结账状态，不能推断因果。'
    else:out['note']='此模型没有直接产品配置字段，未进行同配置核对；须结合对象粒度解释差异。'
    return out

@transaction.atomic
def run(user,topic_id,data):
    if set(data)!={'context_token','config'}:raise ValidationError('专题运行须包含当前定义凭据和完整视角')
    ctx=context(user,topic_id);require_context(ctx,data['context_token']);conf=config(data['config']);before=analytics.revision();cards=[]
    for card in ctx['cards']:
        row={'slot':card['slot'],'span':card['span'],'available':card['available']}
        if not card['available']:row['error']='当前身份无此模型权限，未读取数据';cards.append(row);continue
        m=card['model'];row['model']=m
        try:
            m,link_receipt=topic_linkage.effective(user,m,conf.get('links'));row['model']=m
            if link_receipt:row['linkage']=link_receipt
            result=run_analysis(user,m['dataset'],m['definition'],conf['scope']);row['primary']=result
            if conf['reference_scope'] is not None:
                ref=run_analysis(user,m['dataset'],m['definition'],conf['reference_scope']);row['reference']=ref
                row['comparison']=compare(result,ref,mixed_unit_sets(user,m,conf,result));row['comparability']=comparability(user,m,conf)
        except ValidationError as ex:
            row.pop('primary',None);row['error']='；'.join(ex.messages)
        cards.append(row)
    after=analytics.revision();latest=context(user,topic_id)
    if before!=after or ctx['context_token']!=latest['context_token']:raise ReviewConflict('计算期间数据或模型已变化，请重新运行专题')
    from .bi_card_summary import attach
    for row in cards:
        if row.get('primary'):
            attach(user,row['model'],row,conf)
            candidates=[]
            for side in ('primary','reference'):
                if side in row:
                    found=topic_linkage.choices(user,row['model'],row[side],conf['scope' if side=='primary' else 'reference_scope'],side)
                    candidates.extend(c for c in found if not any(c['group']==old['group'] and c['kind']==old['kind'] for old in candidates))
            row['link_choices']=candidates
    if after!=analytics.revision() or latest['context_token']!=context(user,topic_id)['context_token']:raise ReviewConflict('计算摘要期间数据或模型已变化，请重新运行专题')
    from .file_sharing import fresh,account_receipt
    from .bi_card_summary import digest as summary_digest
    summary_token=summary_digest([ctx['binding'],conf,account_receipt(fresh(user)),[c.get('scope_summary') for c in cards]])
    return {'topic':ctx['topic'],'config':conf,'context_token':ctx['context_token'],'facts_token':digest(before),'cards':cards,'summary_token':summary_token,
            'as_of':analytics.AS_OF,'notice':NOTICE,'compare_note':COMPARE_NOTE,'same_scope':conf['scope']==conf['reference_scope'] if conf['reference_scope'] is not None else False}

@transaction.atomic
def evidence(user,topic_id,data):
    if set(data)!={'context_token','facts_token','config','slot','side','group','page'}:raise ValidationError('来源请求参数不完整')
    ctx=context(user,topic_id);require_context(ctx,data['context_token']);before=analytics.revision()
    if data['facts_token']!=digest(before):raise ReviewConflict('来源数据已更新，请重新运行专题再下钻')
    conf=config(data['config']);slot=data['slot'];side=data['side']
    if type(slot) is not int or not 0<=slot<len(ctx['cards']):raise ValidationError('分析卡位置无效')
    card=ctx['cards'][slot]
    if not card['available']:raise PermissionDenied('没有此模型的数据权限')
    if side not in ['primary','reference'] or side=='reference' and conf['reference_scope'] is None:raise ValidationError('此视角没有所选对照范围')
    if type(data['page']) is not int or not 1<=data['page']<=100000:raise ValidationError('页码无效')
    if data['group'] is not None and (not isinstance(data['group'],str) or len(data['group'])>300):raise ValidationError('分组值格式无效')
    m,_=topic_linkage.effective(user,card['model'],conf.get('links'));scope=conf['scope'] if side=='primary' else conf['reference_scope'];rows,_,meta=selected_rows(user,m['dataset'],m['definition'],scope)
    if data['group'] is not None:rows=[r for r in rows if group_key(r,m['definition'])==data['group']]
    page=data['page'];total=len(rows);selected=sorted(rows,key=lambda r:str(r['id']))[(page-1)*30:page*30];sources={}
    if m['dataset'] not in SEMANTIC_SCHEMAS:
        for r in Record.objects.filter(dataset=m['dataset'],business_key__in=[r['id'] for r in selected]).select_related('source_row__batch'):
            sources[r.business_key]={'file':r.source_row.batch.filename,'sheet':r.source_row.sheet,'row':r.source_row.row_number}
    if before!=analytics.revision() or ctx['context_token']!=context(user,topic_id)['context_token']:raise ReviewConflict('来源或模型在读取期间变化，请重新运行专题')
    return {'total':total,'page':page,'size':30,'scope':scope,'side':side,'group':data['group'],'fields':access.permitted_fields(user,m['dataset']),
            'rows':[{'values':access.sanitize(user,m['dataset'],r),'source':sources.get(r['id']),'references':[ref for ref in r.get('_sources',[]) if access.allowed(user,ref['dataset'])]} for r in selected]}

@transaction.atomic
def export_rows(user,topic_id,data):
    if set(data)!={'context_token','facts_token','config','slot'} or type(data['slot']) is not int:raise ValidationError('导出参数不完整')
    result=run(user,topic_id,{'context_token':data['context_token'],'config':data['config']})
    if result['facts_token']!=data['facts_token']:raise ReviewConflict('数据已变化，请重新运行专题后导出')
    if not 0<=data['slot']<len(result['cards']):raise ValidationError('分析卡位置无效')
    card=result['cards'][data['slot']]
    if not card['available']:raise PermissionDenied('没有此模型的导出权限')
    if card.get('error'):raise ValidationError(card['error'])
    if card.get('comparison',{}).get('blocked'):raise ValidationError('对照结果超过分组上限，请缩小范围后导出')
    conf=result['config'];r=card['primary'];q=card.get('comparability',{})
    heads=['专题','模型','模型版本','当前名称','当前范围','对照名称','对照范围','状态截止','数据修订标记','重叠对象数','共同配置数','可比性说明','结果截断']
    meta=[result['topic']['name'],card['model']['name'],card['model']['version'],conf['primary_label'],json.dumps(conf['scope'],ensure_ascii=False),conf['reference_label'],json.dumps(conf['reference_scope'],ensure_ascii=False),result['as_of'],result['facts_token'],q.get('overlap_objects'),q.get('shared_configuration_count'),q.get('note','')+('两侧配置分布不同或有未知配置。' if q.get('configuration_available') and (not q.get('same_configuration_mix') or q.get('primary_unknown_configuration') or q.get('reference_unknown_configuration')) else ''),'是' if r['truncated'] else '否']
    if conf.get('links'):
        heads+=['专题联动条件与直接字段','保存的模型定义','本次有效分析定义']
        meta += [json.dumps(card['linkage'],ensure_ascii=False),json.dumps(card['model']['saved_definition'],ensure_ascii=False),json.dumps(card['model']['definition'],ensure_ascii=False)]
    if r.get('grouping_receipt'):
        g=r['grouping_receipt'];heads+=['个人分组编码','分组版本','分组摘要','分组规则']
        meta += [g['code'],g['version'],g['hash'],json.dumps(g['payload'],ensure_ascii=False)]
    if r.get('scatter'):
        from .analysis_scatter import export_rows as scatter_export
        rows=[[*heads,'范围侧','分析定义',*scatter_export(r)[0]]]
        for side in ['primary','reference']:
            if side in card:rows.extend([[*meta,conf['primary_label' if side=='primary' else 'reference_label'],json.dumps(card['model']['definition'],ensure_ascii=False),*x] for x in scatter_export(card[side])[1:]])
    elif r.get('pivot') and 'comparison' in card:
        from .pivot_comparison import export_rows as comparison_export
        exported=comparison_export(card['comparison'])
        rows=[[*heads,*exported[0]],*[[*meta,*x] for x in exported[1:]]]
    elif r.get('pivot'):
        from .analysis_pivot import export_rows as pivot_export
        rows=[[ *heads,'范围侧',*pivot_export(r)[0]]]
        for side in ['primary','reference']:
            if side in card:rows.extend([[*meta,conf['primary_label' if side=='primary' else 'reference_label'],*x] for x in pivot_export(card[side])[1:]])
    elif 'comparison' in card:
        rows=[[ *heads,r['dimension_label'],'度量','当前值','对照值','差值','差值单位','相对变化(%)','说明','当前来源行数','对照来源行数']]
        labels={m['key']:m['label'] for m in r['measures']}
        for row in card['comparison']['rows']:
            for v in row['values']:rows.append([*meta,row['dimension'],labels[v['key']],v['primary'],v['reference'],v['delta'],v['delta_unit'],v['relative_pct'],v['reason'],row['primary_rows'],row['reference_rows']])
    else:rows=[[ *heads,r['dimension_label'],*r['labels'],'来源行数'],*[[*meta,row['dimension'],*[row[m['key']] for m in r['measures']],row['row_count']] for row in r['rows']]]
    if r.get('quantile_notice') and not r.get('scatter') and not (r.get('pivot') and 'comparison' not in card):
        from .analysis_quantiles import evidence
        primary={x['dimension']:x for x in r['rows']};reference={x['dimension']:x for x in card.get('reference',{}).get('rows',[])}
        if r.get('pivot'):
            def cells(result):
                p=result.get('pivot',{})
                return {(x['row'],x['column']):x for part in ['cells','row_totals','column_totals'] for x in p.get(part,[])}|{(None,None):p.get('grand_total',{})}
            primary=cells(r);reference=cells(card.get('reference',{}))
        rows[0].extend(['当前分位数计算与样本依据','对照分位数计算与样本依据'])
        for x in rows[1:]:
            key=(x[len(heads)+2],x[len(heads)+3]) if r.get('pivot') else x[len(heads)]
            x.extend([evidence(primary.get(key,{})),evidence(reference.get(key,{}))])
    return rows,card['model']['id']
