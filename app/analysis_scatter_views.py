import json,secrets
from django.core.cache import cache
from django.db import transaction
from . import analysis_scatter as scatter,analysis_engine as engine,analysis_explore_views as explore,access
from .models import AuditEvent
from .quality_views import csv_reply
from .views import api
from .import_review import ReviewConflict

def context(request,extra=()):
    p,ds,d,scope,revision,ls,rows,scanned,info,current=explore.context(request,('selection',*extra))
    if p['path'] or current.get('chart')!='scatter':raise ValueError('请使用散点模型的分组来源入口')
    if p.get('revision') is None:raise ValueError('请提供已查看散点结果的计算依据')
    result=engine.run_analysis(request.user,ds,d,scope)
    if result['scatter']['revision']!=revision:raise ReviewConflict('散点计算依据变化，请重新运行')
    return p,ds,d,scope,revision,rows,current,result

def selected(p,result,rows,current):
    point=scatter.selection(result,p.get('selection'))
    return [r for r in rows if engine.group_key(r,current)==point['dimension']],point

@api(('POST',))
@transaction.atomic
def evidence(request):
    p,ds,d,scope,revision,rows,current,result=context(request,('page',))
    rows,point=selected(p,result,rows,current);page=p.get('page',1)
    if type(page) is not int or not 1<=page<=100000:raise ValueError('页码无效')
    return explore.respond({**explore.source_data(request.user,ds,rows,page),'revision':revision,'point':point})

@api(('POST',))
@transaction.atomic
def export(request):
    p,ds,d,scope,revision,rows,current,result=context(request,('kind',))
    kind=p.get('kind');data=[['分组散点分析 · 合成模拟数据','数据集',ds],['定义',json.dumps(d,ensure_ascii=False),'范围',json.dumps(scope,ensure_ascii=False)],['说明',scatter.NOTICE]]
    if kind=='result':
        if 'selection' in p:raise ValueError('完整散点结果导出不接受分组限制')
        items=scatter.export_rows(result);data+=items;n=len(items)-1
    elif kind=='evidence':
        rows,point=selected(p,result,rows,current)
        if len(rows)>10000:raise ValueError('来源超过10,000行，请缩小范围；本次未截断')
        fields=access.permitted_fields(request.user,ds)
        data += [['分组',point['dimension']],[f['label'] for f in fields]]
        data += [[r.get(f['name']) for f in fields] for r in sorted(rows,key=lambda r:str(r['id']))];n=len(rows)
    else:raise ValueError('导出类型无效')
    data.append(['计算依据',json.dumps(revision,ensure_ascii=False)])
    csv=csv_reply(data,'analysis-scatter').content.decode('utf-8-sig');filename='analysis-scatter-'+kind+'.csv'
    AuditEvent.objects.create(action='analysis.scatter_export',actor=request.user.username,object_type='AnalysisScatter',object_id=ds,detail={'kind':kind,'rows':n,'selection':p.get('selection'),'scope':scope,'definition':d,'revision':revision})
    token=secrets.token_urlsafe(32);cache.set('analysis-export:'+token,{'user':request.user.pk,'role':access.role(request.user),'dataset':ds,'csv':csv,'kind':kind,'filename':filename},300)
    return explore.respond({'filename':filename,'rows':n,'download_url':'/api/analyze/explore/files/'+token})
