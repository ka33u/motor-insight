"""One-time simulated review using normal lifecycle and model APIs, with preserved audits."""
import os,sys,json,copy
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings')
import django;django.setup()
from django.contrib.auth.models import User
from django.db import transaction
from django.test import RequestFactory
from app import metric_registry as registry,views,analysis_engine as engine
from app.models import MetricVersion,AnalysisModel

with transaction.atomic():
    author=User.objects.get(username='demo_admin');reviewer=User.objects.get(username='demo_operations')
    old=MetricVersion.objects.get(pk=8);assert old.status=='published' and old.version==5 and old.revision==4
    assert not old.metric.versions.filter(version=6).exists(),'Already reviewed; do not rerun'
    before=json.loads((ROOT/'data/pivot_before.json').read_text());regression=json.loads((ROOT/'data/pivot_regression.json').read_text());assert len(regression)==49 and all(r['unchanged'] for r in regression.values())
    new=registry.transition(author,old.pk,{'action':'fork','revision':old.revision})
    payload=copy.deepcopy(new.payload);payload['change_reason']='透视聚合扩展后的模拟复核：49个既有模型的数值、来源范围、比率分子分母及派生结果与升级前一致；交付公式、固定范围和日期定义不变。透视格与行列合计从各自来源重算。'
    new=registry.transition(author,new.pk,{'action':'save','revision':new.revision,'payload':payload})
    new=registry.transition(author,new.pk,{'action':'submit','revision':new.revision})
    e=new.evidence;assert e['matched']==300 and e['components'][0]['numerator']==15 and e['components'][0]['denominator']==165
    new=registry.transition(reviewer,new.pk,{'action':'publish','revision':new.revision,'reason':'模拟业务复核：全套763项测试通过，49个旧模型结果保持一致；样例仍为15/165、9.090909%。本操作仅为演示账号验证，非真实工厂业务批准。'})
    m=AnalysisModel.objects.get(pk=44);assert m.version==6 and m.definition['metric_ref']['version']==5
    d=copy.deepcopy(m.definition);d['metric_ref']['version']=6
    req=RequestFactory().post('/api/models',data=json.dumps({'id':m.pk,'version':m.version,'name':'按产品族交付达成 · 发布指标v6','dataset':m.dataset,'definition':d,'is_public':m.is_public}),content_type='application/json');req.user=author
    response=views.analysis_models(req);assert response.status_code==200,response.content
    old=registry.transition(reviewer,old.pk,{'action':'retire','revision':old.revision,'reason':'模型44经模拟复核后显式迁移到v6，停用旧v5；保留原口径、计算指纹、审核样例和历史快照。'})
    m.refresh_from_db();assert engine.run_analysis(author,m.dataset,m.definition)['rows']==before['44']['result']['rows']
    result={'simulated':True,'new_metric_id':new.pk,'metric_version':new.version,'calculation_hash':new.calculation_hash,'model_id':m.pk,'model_version':m.version,'numerator':15,'denominator':165,'old_metric_preserved_and_retired':old.pk}
    (ROOT/'data/pivot_metric_review.json').write_text(json.dumps(result,ensure_ascii=False,indent=2));print(json.dumps(result,ensure_ascii=False))
