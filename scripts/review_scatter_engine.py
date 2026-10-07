"""One-time simulated metric re-review after adding a presentation calculation type."""
import os,sys,json,copy
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings')
import django;django.setup()
from django.db import transaction
from django.test import RequestFactory
from django.contrib.auth.models import User
from app import metric_registry as registry,views
from app.models import AnalysisModel,MetricVersion
from app.analysis_engine import run_analysis

def projection(r):
    d=copy.deepcopy(r);d.pop('definition',None);d.pop('metric_receipt',None)
    if d.get('pivot'):d['pivot'].pop('revision',None)
    return json.loads(json.dumps(d,ensure_ascii=False,default=str))
admin=User.objects.get(username='demo_admin');reviewer=User.objects.get(username='demo_operations')
baseline=json.loads((ROOT/'data/scatter_before.json').read_text())
assert len(baseline)==50
assert not MetricVersion.objects.filter(metric__key='DELIVERY_OTIF',version=7).exists(),'Already reviewed; do not replay.'
with transaction.atomic():
    for m in AnalysisModel.objects.filter(pk__in=baseline).order_by('pk'):
        d,_=registry.resolve(admin,m.dataset,m.definition,allow_inactive=True)
        assert projection(run_analysis(admin,m.dataset,d))==projection(baseline[str(m.pk)]),m.pk
    old=MetricVersion.objects.select_related('metric').get(metric__key='DELIVERY_OTIF',version=6,status='published')
    v=registry.transition(admin,old.pk,{'action':'fork','revision':old.revision})
    payload=copy.deepcopy(v.payload);payload['change_reason']='分组散点引擎扩展后的模拟复核：50个既有模型数值、来源数和计算分量与升级前逐项一致；交付公式、固定范围、日期口径保持不变。'
    v=registry.transition(admin,v.pk,{'action':'save','revision':v.revision,'payload':payload})
    v=registry.transition(admin,v.pk,{'action':'submit','revision':v.revision})
    assert (v.evidence['components'][0]['numerator'],v.evidence['components'][0]['denominator'])==(15,165)
    v=registry.transition(reviewer,v.pk,{'action':'publish','revision':v.revision,'reason':'模拟独立岗位复核：50个旧模型结果与来源数量不变，交付按期足量15/有效到期165，结果9.090909%。仅演练账号审核，不代表工厂业务批准。'})
    m=AnalysisModel.objects.get(pk=44);assert m.definition['metric_ref']=={'key':'DELIVERY_OTIF','version':6}
    d=copy.deepcopy(m.definition);d['metric_ref']['version']=7
    req=RequestFactory().post('/api/models',json.dumps({'id':m.pk,'version':m.version,'name':m.name,'dataset':m.dataset,'definition':d,'is_public':m.is_public}),content_type='application/json');req.user=admin
    response=views.analysis_models(req);assert response.status_code==200,response.content;m.refresh_from_db()
    registry.transition(reviewer,old.pk,{'action':'retire','revision':old.revision,'reason':'新计算引擎已经完成v7模拟复核，模型44显式选择v7；保留v6定义、证据和历史快照。'})
    assert projection(run_analysis(admin,m.dataset,m.definition))==projection(baseline['44'])
report={'synthetic':True,'unchanged_model_results':50,'published':registry.receipt(v),'migrated_model':views.model_info(m),'existing_views':'Existing four view bindings unchanged; calculation revision now requires explicit recheck.','historical_snapshots':'Existing frozen payloads retained; cross-revision numeric comparison pauses.'}
(ROOT/'data/scatter_engine_review.json').write_text(json.dumps(report,ensure_ascii=False,indent=2,default=str))
print(json.dumps({'verified_existing_models':50,'published_metric_version':v.version,'model44_version':m.version,'calculation_hash':v.calculation_hash},ensure_ascii=False))
