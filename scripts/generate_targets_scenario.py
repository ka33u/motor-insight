"""Construct explicit synthetic targets and confirmations for XLSX import."""
import os,sys,json
from pathlib import Path
from datetime import datetime,timedelta
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings')
import django;django.setup()
from django.contrib.auth.models import User
from app.models import AnalysisModel
from app.schema import SCHEMAS
from app import targets as k,metric_registry
admin=User.objects.get(username='demo_admin');models={m.pk:m for m in AnalysisModel.objects.all()};tables={ds:[] for ds in k.DATASETS}

def target(series,name,department,mid,start,end,unit,direction,low=None,high=None,margin=0,measure='m0',version=1,previous=None,approved='2026-09-20T08:00:00',minimum=1,status='已确认'):
    m=models[mid];r=dict(id=f'{series}-V{version:02d}',series=series,version=version,supersedes_id=previous,name=name,department=department,owner='模拟'+department+'责任岗位',model_id=mid,model_version=m.version,model_signature=k.model_signature(m),calculation_hash=metric_registry.calculation_hash(m.dataset),measure=measure,unit=unit,period_start=start,period_end=end,family=None,customer_id=None,direction=direction,lower=low,upper=high,warning_margin=margin,minimum_samples=minimum,approved=approved,status=status,basis='合成目标假设，仅用于演示比较流程；不是行业基准或正式考核标准。',reason='首版模拟目标' if version==1 else '模拟评审调整目标，保留上一版与调整依据，不覆盖历史目标')
    tables['kpi_targets'].append(r);return r

def confirm(t,status='完整',stale=False):
    e=k.evaluation(admin,t,models[t['model_id']]);through=t['period_end']+'T23:59:59';when=max(datetime.fromisoformat(through)+timedelta(hours=8),datetime.fromisoformat(t['approved'])+timedelta(hours=1)).isoformat(timespec='seconds')
    tables['kpi_target_checks'].append(dict(id='SJQR-'+t['id'],target_id=t['id'],through=through,confirmed=when,data_signature='0'*64 if stale else e['data_signature'],status=status,owner='模拟数据责任岗位',note='合成资料确认演练；已核对本目标日期范围的来源记录与当前事实摘要。确认不是实际财务结账或质量批准。',voided=False))

for day in range(21,26):
    period=f'2026-09-{day}';suffix=f'2609{day}'
    a=target('MB-ZP-'+suffix,'日装配记录数量','生产计划',5,period,period,'台','gte',low={21:900,22:950,23:920,24:950,25:880}[day],margin=30,minimum=100);a['basis']='用户描述约900台/日；以此设置880至950台的合成目标情景，不是已确认生产计划。';confirm(a)
    if day==22:
        revised=target(a['series'],a['name'],a['department'],5,period,period,'台','gte',low=920,margin=30,version=2,previous=a['id'],approved='2026-09-24T08:00:00',minimum=100);confirm(revised)
    q=target('MB-ZL-'+suffix,'装配队列首次完整检测合格率','质量',31,period,period,'%','gte',low=94,margin=2,minimum=100);confirm(q,status='待补' if day==24 else '完整')
    d=target('MB-TJ-'+suffix,'设备去重停机小时','设备',39,period,period,'小时','lte',high=20,margin=5);confirm(d)
    e=target('MB-NY-'+suffix,'模拟电价下的日用电费用','能源',40,period,period,'元','lte',high=3000,margin=300);confirm(e,stale=day==25)
    l=target('MB-GS-'+suffix,'作业登记时长中位数','生产计划',52,period,period,'分钟','between',low=4,high=8,margin=2,measure='m2',minimum=20);confirm(l)

t=target('MB-JF-2609','本月下单队列截至快照的交付率','销售',44,'2026-09-01','2026-09-30','%','gte',low=95,margin=3);confirm(t)
t=target('MB-KP-2609','本月开票未税金额','财务',20,'2026-09-01','2026-09-30','元','gte',low=6000000,margin=500000);confirm(t)
t=target('MB-ZP-2610W1','本周装配数量（进行中）','生产计划',5,'2026-09-28','2026-10-04','台','gte',low=4500,margin=100)
t=target('MB-ZP-2610W2','下周装配数量（尚未开始）','生产计划',5,'2026-10-05','2026-10-11','台','gte',low=4500,margin=100)
t=target('MB-ZP-2608','早期装配数量（缺少样本）','生产计划',5,'2026-08-01','2026-08-31','台','gte',low=18000,margin=500,approved='2026-07-31T08:00:00');confirm(t)
t=target('MB-GS-P90-2609','登记时长P90（模型待核对示例）','生产计划',52,'2026-09-21','2026-09-25','分钟','lte',high=30,margin=5,measure='m3');t['model_signature']='0'*64
t=target('MB-ZL-DRAFT-2610','下月质量目标草稿','质量',31,'2026-10-01','2026-10-31','%','gte',low=95,margin=2,status='草稿',approved=None)
scenario={'schema_version':1,'as_of':'2026-10-01T18:00:00','seed':'targets-v1','notice':'所有目标均为合成假设，用于BI目标比较演练，不是正式考核或行业基准。固定模型版本、单位、期间与范围；资料确认绑定当前范围事实摘要。保留目标调整历史，期间未结束或资料待补不判最终达标。开票不等于收入，工时中位数不等于单台节拍。','schemas':{ds:SCHEMAS[ds] for ds in k.DATASETS},'tables':tables}
(ROOT/'data/targets_scenario.json').write_text(json.dumps(scenario,ensure_ascii=False,indent=2));print(json.dumps({ds:len(rows) for ds,rows in tables.items()},ensure_ascii=False))
