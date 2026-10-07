import json,secrets
from django.core.cache import cache
from django.db import transaction
from . import analysis_pivot as pivot,analysis_engine as engine,analysis_explore_views as explore,access
from .models import AuditEvent
from .quality_views import csv_reply
from .views import api

def context(request,extra=()):
    p,ds,d,scope,revision,ls,rows,scanned,info,current=explore.context(request,('selection',*extra),allow_pivot=True)
    if p['path'] or current.get('chart')!='pivot':raise ValueError('请使用透视模型的行列来源入口')
    if p.get('revision') is None:raise ValueError('请提供已查看透视结果的计算依据')
    return p,ds,d,scope,revision,rows,current

@api(('POST',))
@transaction.atomic
def evidence(request):
    p,ds,d,scope,revision,rows,current=context(request,('page',))
    selected=pivot.select(rows,current,p.get('selection'))
    page=p.get('page',1)
    if type(page) is not int or not 1<=page<=100000:raise ValueError('页码无效')
    return explore.respond({**explore.source_data(request.user,ds,selected,page),'revision':revision,'selection':p['selection']})

@api(('POST',))
@transaction.atomic
def export(request):
    p,ds,d,scope,revision,rows,current=context(request,('kind',))
    kind=p.get('kind');data=[['透视分析 · 合成模拟数据','数据集',ds],['定义',json.dumps(d,ensure_ascii=False),'范围',json.dumps(scope,ensure_ascii=False)],['说明',pivot.NOTICE]]
    if kind=='result':
        if 'selection' in p:raise ValueError('完整矩阵导出不接受单元格限制')
        result=engine.run_analysis(request.user,ds,d,scope);items=pivot.export_rows(result);data+=items;n=len(items)-1
    elif kind=='evidence':
        selected=pivot.select(rows,current,p.get('selection'))
        if len(selected)>10000:raise ValueError('来源超过10,000行，请缩小范围后导出；本次未截断')
        fields=access.permitted_fields(request.user,ds)
        data += [['行列选择',json.dumps(p['selection'],ensure_ascii=False)], [f['label'] for f in fields]]
        data += [[r.get(f['name']) for f in fields] for r in sorted(selected,key=lambda r:str(r['id']))];n=len(selected)
    else:raise ValueError('导出类型无效')
    data.append(['计算依据',json.dumps(revision,ensure_ascii=False)])
    csv=csv_reply(data,'analysis-pivot').content.decode('utf-8-sig');filename='analysis-pivot-'+kind+'.csv'
    token=secrets.token_urlsafe(32)
    AuditEvent.objects.create(action='analysis.pivot_export',actor=request.user.username,object_type='AnalysisPivot',object_id=ds,detail={'kind':kind,'rows':n,'selection':p.get('selection'),'scope':scope,'definition':d,'revision':revision})
    cache.set('analysis-export:'+token,{'user':request.user.pk,'role':access.role(request.user),'dataset':ds,'csv':csv,'kind':kind,'filename':filename},300)
    return explore.respond({'filename':filename,'rows':n,'download_url':'/api/analyze/explore/files/'+token})
