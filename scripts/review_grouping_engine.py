"""One-time simulated engine re-review; never writes imported business records."""
import os,sys,json,copy
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings')
import django;django.setup()
from django.contrib.auth.models import User
from django.db import transaction
from app.models import AnalysisModel,MetricVersion,AuditEvent,TopicView
from app.analysis_engine import run_analysis
from app import metric_registry as registry,topic_workspace as ws
from app.views import model_info

u=User.objects.get(username='demo_admin');reviewer=User.objects.get(username='demo_operations')
baseline=json.loads((ROOT/'data/business_groups_baseline.json').read_text())
assert not MetricVersion.objects.filter(metric__key='DELIVERY_OTIF',version=4).exists(),'Already reviewed; use validation instead of replaying migration'
with transaction.atomic():
    for m in AnalysisModel.objects.filter(id__in=[int(x) for x in baseline]).order_by('id'):
        d,_=registry.resolve(u,m.dataset,m.definition,allow_inactive=True)
        result=run_analysis(u,m.dataset,d)
        assert {k:result[k] for k in baseline[str(m.pk)]}==baseline[str(m.pk)],m.pk
    old=MetricVersion.objects.select_related('metric').get(metric__key='DELIVERY_OTIF',version=3)
    v=registry.transition(u,old.pk,{'action':'fork','revision':old.revision})
    payload=copy.deepcopy(v.payload);payload['change_reason']='业务分组引擎扩展后的模拟复核：46个旧模型汇总及来源数量逐项与升级前一致，交付公式、固定范围及日期定义不变。'
    v=registry.transition(u,v.pk,{'action':'save','revision':v.revision,'payload':payload})
    v=registry.transition(u,v.pk,{'action':'submit','revision':v.revision})
    assert (v.evidence['components'][0]['numerator'],v.evidence['components'][0]['denominator'])==(15,165)
    v=registry.transition(reviewer,v.pk,{'action':'publish','revision':v.revision,'reason':'自动模拟独立岗位复核：升级前后46个旧模型结果逐项相同；交付有效到期分母165、按期足量15，结果9.090909%。仅演练账号审核，不代表真实业务负责人验收。'})
    m=AnalysisModel.objects.select_for_update().get(pk=44);before=model_info(m)
    assert m.definition['metric_ref']=={'key':'DELIVERY_OTIF','version':3}
    m.definition=copy.deepcopy(m.definition);m.definition['metric_ref']['version']=4;m.version+=1;m.save()
    AuditEvent.objects.create(action='model.save',actor=u.username,object_type='AnalysisModel',object_id=str(m.pk),detail={'before':before,'after':model_info(m),'reason':payload['change_reason']})
    registry.transition(reviewer,old.pk,{'action':'retire','revision':old.revision,'reason':'保留v3原定义和审核样例；计算引擎扩展后已完成v4模拟复核，演练模型44显式选择v4。'})
    rebound=[]
    for view in TopicView.objects.filter(owner=u):
        ctx=ws.context(u,view.topic_id);r=ws.run(u,view.topic_id,{'context_token':ctx['context_token'],'config':view.config})
        assert all(c.get('available') and not c.get('error') for c in r['cards'])
        receipt=ws.save_view(u,view.topic_id,{'name':view.name,'config':view.config,'context_token':ctx['context_token'],'version':view.version,'rebind':True,'reason':'模拟引擎升级复核：旧模型结果与升级前逐项一致，原范围和名称不变；明确更新计算规则绑定，历史审计保留。'},view.pk)
        rebound.append({'id':view.pk,'version':receipt['version'],'stale':receipt['stale']})
    final=run_analysis(u,m.dataset,m.definition)
    assert {k:final[k] for k in baseline['44']}==baseline['44']
report={'synthetic':True,'unchanged_model_results':len(baseline),'published':registry.receipt(v),'migrated_model':model_info(m),'rebound_personal_views':rebound,'historical_snapshots':'Unchanged; conservative comparison blocks old calculation binding, while frozen values and source evidence remain readable.'}
(ROOT/'data/grouping_engine_review.json').write_text(json.dumps(report,ensure_ascii=False,indent=2,default=str))
print(json.dumps({'model_results_verified':len(baseline),'metric_version':v.version,'model44_version':m.version,'views':rebound},ensure_ascii=False))
