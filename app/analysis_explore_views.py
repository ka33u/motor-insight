import json,secrets
from django.core.cache import cache
from django.http import HttpResponse
from django.db import transaction
from . import analysis_engine as engine,analysis_drill as drill,analytics,access,bi_scope,metric_registry
from .models import Record,AuditEvent
from .semantic_schema import SEMANTIC_SCHEMAS
from .topic_workspace import digest
from .import_review import ReviewConflict
from .quality_views import csv_reply
from .views import api,body,reply

def respond(value):
    r=reply(value);r['Cache-Control']='no-store';return r

def context(request,extra=(),allow_pivot=False):
    p=body(request)
    if set(p)-({'dataset','definition','scope','path','revision'}|set(extra)):raise ValueError('包含未知的逐层分析参数')
    if not {'dataset','definition','path'}<=set(p):raise ValueError('请提供数据集、定义和下钻路径')
    ds=p['dataset'];definition=p['definition'];scope=bi_scope.validate_scope(p.get('scope'))
    normalized=engine.validate_definition(request.user,ds,definition)
    if normalized.get('chart')=='pivot' and not allow_pivot:raise ValueError('透视表请使用行列来源与完整矩阵导出入口')
    ls=drill.levels(request.user,ds,normalized)
    revision={'data':list(analytics.revision()),'calculation':metric_registry.calculation_hash(ds),'definition':digest(definition),'scope':digest(scope),'as_of':analytics.AS_OF}
    if p.get('revision') is not None and p['revision']!=revision:raise ReviewConflict('数据、计算或分析条件已变化，请重新打开逐层分析；未沿用旧结果')
    if p['path'] and p.get('revision') is None:raise ValueError('继续下钻需带上当前结果依据')
    # Even exports/evidence validate every parent group and the leaf index.
    rows,scanned,info=engine.selected_rows(request.user,ds,definition,scope,p['path'])
    current=drill.at_level(normalized,len(p['path']))
    return p,ds,definition,scope,revision,ls,rows,scanned,info,current

def source_data(user,ds,rows,page):
    selected=sorted(rows,key=lambda r:str(r['id']))[(page-1)*30:page*30];provenance={}
    if ds not in SEMANTIC_SCHEMAS:
        for rec in Record.objects.filter(dataset=ds,business_key__in=[r['id'] for r in selected]).select_related('source_row__batch'):
            provenance[rec.business_key]={'file':rec.source_row.batch.filename,'sheet':rec.source_row.sheet,'row':rec.source_row.row_number,'batch':str(rec.source_row.batch_id)}
    return {'total':len(rows),'page':page,'size':30,'fields':access.permitted_fields(user,ds),
      'rows':[{'values':access.sanitize(user,ds,r),'source':provenance.get(r['id']),
        'references':[x for x in r.get('_sources',[]) if access.allowed(user,x['dataset'])]} for r in selected]}

@api(('POST',))
@transaction.atomic
def board(request):
    p,ds,d,scope,revision,ls,rows,scanned,info,current=context(request)
    if current.get('chart')=='pivot':raise ValueError('透视表请点击行列单元格查看来源')
    result=engine.run_analysis(request.user,ds,d,scope,p['path'])
    # Root custom grouping retains its published labels in the navigation.
    if d.get('grouping_ref'):ls[0]['label']=engine.business_groups.resolve(request.user,ds,d)['name']
    return respond({'result':result,'levels':ls,'path':p['path'],'revision':revision,'can_expand':len(p['path'])<len(ls)-1,'notice':drill.NOTICE})

@api(('POST',))
@transaction.atomic
def evidence(request):
    p,ds,d,scope,revision,ls,rows,scanned,info,current=context(request,('group','page'))
    if 'group' in p:
        if not isinstance(p['group'],str):raise ValueError('来源分组须为文本')
        rows=[r for r in rows if engine.group_key(r,current)==p['group']]
    page=p.get('page',1)
    if type(page) is not int or page<1:raise ValueError('页码无效')
    return respond({**source_data(request.user,ds,rows,page),'revision':revision,'path':p['path'],'group':p.get('group'),'scope':info,'can_download_original':access.can_import(request.user)})

@api(('POST',))
@transaction.atomic
def export(request):
    p,ds,d,scope,revision,ls,rows,scanned,info,current=context(request,('kind','group'))
    if p.get('revision') is None:raise ValueError('导出需带上已查看结果的依据')
    kind=p.get('kind','result')
    data=[['逐层分析 · 合成模拟数据','数据集',ds,'路径',json.dumps(p['path'],ensure_ascii=False)],
      ['原定义',json.dumps(d,ensure_ascii=False),'范围',json.dumps(scope,ensure_ascii=False),'截止',analytics.AS_OF],
      ['说明',drill.NOTICE]]
    if kind=='result':
        if 'group' in p:raise ValueError('结果导出不接受来源分组参数')
        r=engine.run_analysis(request.user,ds,d,scope,p['path'])
        data.append(['返回分组',len(r['rows']),'全部分组',r['groups'],'截断',r['truncated']])
        from .analysis_quantiles import evidence
        statistical=bool(r.get('quantile_notice'))
        data.append([r['dimension_label'],*[m['label'] for m in r['measures']],'来源行数',*(['分位数计算与样本依据'] if statistical else [])])
        data.extend([[x['dimension'],*[x[m['key']] for m in r['measures']],x['row_count'],*([evidence(x)] if statistical else [])] for x in r['rows']]);n=len(r['rows'])
    elif kind=='evidence':
        if 'group' in p:
            if not isinstance(p['group'],str):raise ValueError('来源分组须为文本')
            rows=[r for r in rows if engine.group_key(r,current)==p['group']]
        if len(rows)>10000:raise ValueError('来源超过10,000行，请缩小范围后导出；本次未截断导出')
        fields=access.permitted_fields(request.user,ds)
        data.append(['所选分组',p.get('group','全部当前范围'),'来源行数',len(rows)])
        data.append([f['label'] for f in fields]);data.extend([[row.get(f['name']) for f in fields] for row in sorted(rows,key=lambda r:str(r['id']))]);n=len(rows)
    else:raise ValueError('导出类型无效')
    data.append(['计算依据',json.dumps(revision,ensure_ascii=False)])
    csv=csv_reply(data,'analysis-drill').content.decode('utf-8-sig')
    AuditEvent.objects.create(action='analysis.explore_export',actor=request.user.username,object_type='AnalysisExploration',object_id=ds,detail={'kind':kind,'rows':n,'path':p['path'],'scope':scope,'definition':d,'revision':revision})
    token=secrets.token_urlsafe(32)
    cache.set('analysis-export:'+token,{'user':request.user.pk,'role':access.role(request.user),'dataset':ds,'csv':csv,'kind':kind},300)
    return respond({'filename':'analysis-drill-'+kind+'.csv','csv':csv,'rows':n,'download_url':'/api/analyze/explore/files/'+token})

@api()
def download(request,token):
    item=cache.get('analysis-export:'+token)
    if not item or item['user']!=request.user.pk:raise ValueError('导出文件不存在或已过期，请重新生成')
    if item['role']!=access.role(request.user) or not access.allowed(request.user,item['dataset']):raise ValueError('当前权限已变化，请重新生成导出')
    response=HttpResponse('\ufeff'+item['csv'],content_type='text/csv; charset=utf-8')
    response['Content-Disposition']='attachment; filename="'+item.get('filename','analysis-drill-'+item['kind']+'.csv')+'"'
    response['Cache-Control']='no-store';response['X-Content-Type-Options']='nosniff'
    return response
