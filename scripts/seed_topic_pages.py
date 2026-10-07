"""Create two synthetic personal page definitions through normal preview/save services.

No direct configuration insertion, business fact modification or shared topic change.
Run only on the explicit demo database selected by MOTOR_SQLITE_PATH.
"""
import json,os,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings')
import django;django.setup()
from django.contrib.auth import get_user_model
from django.db import transaction
from app import topic_pages as pages
from app.models import TopicPage

def examples():
 return [
 dict(owner='demo_analyst',definition=dict(topic_id=15,code='PAGE.DELIVERY.DAILY.0001',title='交付口径每日复查',question='当前已到期订单行，按已发布的交付口径表现如何，哪些对象应到交付工作台核查？',cadence='每日经营会前核对；协调后复查；资料截至模拟2026-10-01 18:00',sections=[dict(id='RESULT',title='按共同交付定义看结果',role='result',note='先核对当前/对照范围、承诺交付日、分子分母及发布版本。产品族结构变化不等于业务效率改善。',cards=[dict(slot=0,span=2,title='产品族交付达成及同范围依据',note='沿用 DELIVERY_OTIF v8；下钻原卡与整范围摘要，分组样本不直接平均。')])],navigation=[dict(topic_id=2,label='核查订单与交付对象',mode='new')]),second_version=True),
 dict(owner='demo_admin',definition=dict(topic_id=4,code='PAGE.QUALITY.DAILY.0001',title='终检证据每日复查',question='整机最新状态、首检表现与全部检测会话有什么区别，哪些处置状态需要继续核查？',cadence='班后核对；质量协调后复查；模拟规范不能用于真实质量批准',sections=[dict(id='RESULT',title='整机结果与首检比较',role='result',note='两卡按装配日选整机；最新状态与首检样本口径不同。',cards=[dict(slot=3,span=1,title='整机最新检测状态',note='按SN计整机；不得把最新通过当成首检通过。'),dict(slot=2,span=1,title='产品族首检合格表现',note='查看首次应测与首测通过的分母，不把无检测记录填为正常。')]),dict(id='EXPLAIN',title='全部会话与处置解释',role='explain',note='这两卡分别按检测发生日与问题发现日，日期筛选不构成同一业务队列。',cards=[dict(slot=0,span=1,title='全部检测会话构成',note='会话次数包含复测，不能当作电机台数；按原卡追查来源。'),dict(slot=1,span=1,title='问题处置状态',note='处置记录状态不是整机放行批准；核对对象、日期和依据。')])],navigation=[dict(topic_id=2,label='检查订单交付关联',mode='new')]),second_version=False)]

@transaction.atomic
def seed():
 rows=[]
 for e in examples():
  user=get_user_model().objects.get(username=e['owner']);d=e['definition'];existing=TopicPage.objects.filter(owner=user,code=d['code']).first()
  if existing:
   r=pages.read(user,existing.pk);assert r['ready'] and r['version']==(2 if e['second_version'] else 1);rows.append(dict(id=r['id'],owner=user.username,code=r['code'],version=r['version'],reused=True));continue
  preview=pages.preview(user,d);body=dict(request_id='940b2b04-5f13-4ef4-8e52-06ad978ac7d3' if e['second_version'] else 'ae295602-dc3d-49f6-abee-45c6ee6e1caf',definition=d,receipt=preview['receipt'],reason='依据原专题卡及日期角色，保存合成个人阅读编排')
  r=pages.save(user,body)
  if e['second_version']:
   d={**d,'question':d['question']+'？复查时同时确认数据变化与口径变化。'};d['question']=d['question'].replace('？？','？');preview=pages.preview(user,d)
   r=pages.save(user,dict(request_id='ab71121e-b3f2-4620-b82d-c45d69d4d614',definition=d,receipt=preview['receipt'],reason='补充复查问题，区分数据变化与指标定义变化',revision=r['revision']),r['id'])
  current=pages.read(user,r['id']);assert current['ready'];rows.append(dict(id=r['id'],owner=user.username,code=r['code'],version=r['version'],reused=False))
 return dict(success=True,synthetic=True,normal_preview_save_services=True,business_facts_changed=False,shared_topics_changed=False,pages=rows)
if __name__=='__main__':print(json.dumps(seed(),ensure_ascii=False,indent=2))
