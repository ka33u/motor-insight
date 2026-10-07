"""Explicitly align demo labels after v4 review; preserve facts and visibility."""
import os,sys,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings')
import django;django.setup()
from django.contrib.auth.models import User
from django.test import RequestFactory
from django.db import transaction
from app.models import AnalysisModel,Topic,TopicView
from app import views,topic_workspace as ws
u=User.objects.get(username='demo_admin');factory=RequestFactory()
def post(view,path,data):
    req=factory.post(path,json.dumps(data),content_type='application/json');req.user=u
    response=view(req);assert response.status_code==200,response.content
    return json.loads(response.content)
with transaction.atomic():
    m=AnalysisModel.objects.get(pk=44)
    assert m.definition['metric_ref']=={'key':'DELIVERY_OTIF','version':4}
    if m.name!='按产品族交付达成 · 发布指标v4':
        post(views.analysis_models,'/api/models',{**views.model_info(m),'name':'按产品族交付达成 · 发布指标v4'})
    t=Topic.objects.get(pk=15)
    description='使用已模拟审核发布的交付指标；具体版本以分析卡口径为准。日期按下单日选择订单队列，状态仍截至模拟快照。停用版本和显式迁移记录保留；真实业务口径仍待工厂负责人验收。'
    if t.description!=description:
        post(views.topics,'/api/topics',{'id':t.pk,'version':t.version,'name':t.name,'description':description,'is_public':t.is_public,'layout':t.layout})
    receipts=[]
    for v in TopicView.objects.filter(owner=u):
        ctx=ws.context(u,v.topic_id)
        if ws.view_info(v,ctx)['stale']:
            result=ws.save_view(u,v.topic_id,{'name':v.name,'config':v.config,'context_token':ctx['context_token'],'version':v.version,'rebind':True,'reason':'仅校正交付演练模型和专题的陈旧版本文字；指标v4、计算定义、数据范围和可见权限不变，显式更新模型/专题版本绑定。'},v.pk)
            receipts.append({'id':v.pk,'version':result['version'],'stale':result['stale']})
(ROOT/'data/grouping_demo_labels.json').write_text(json.dumps({'model':views.model_info(AnalysisModel.objects.get(pk=44)),'topic_version':Topic.objects.get(pk=15).version,'rebound_views':receipts},ensure_ascii=False,indent=2))
print(json.dumps({'model_version':AnalysisModel.objects.get(pk=44).version,'topic_version':Topic.objects.get(pk=15).version,'views':receipts},ensure_ascii=False))
