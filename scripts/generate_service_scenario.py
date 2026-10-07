"""Produce synthetic supplemental Excel inputs; never write business records."""
import os,sys,json
from pathlib import Path
from datetime import datetime,timedelta
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings')
import django;django.setup()
from app.schema import SCHEMAS
from app.models import Record
from app.analytics import AS_OF
raw={k:list(Record.objects.filter(dataset=k).values_list('values',flat=True)) for k in ['service','employees','products','units']}
staff=sorted([r['id'] for r in raw['employees'] if r['department_id']=='D16' and r['active']]);units={r['id']:r for r in raw['units']};products={r['id']:r for r in raw['products']}
tables={k:[] for k in ['service_events','service_tasks','service_conditions']};cutoff=datetime.fromisoformat(AS_OF)
iso=lambda t:t.isoformat(timespec='seconds')
for i,s in enumerate(sorted(raw['service'],key=lambda x:x['id']),1):
    reported=datetime.fromisoformat(s['reported']);response=datetime.fromisoformat(s['response']);closed=datetime.fromisoformat(s['closed']) if s['closed'] else None;owner=staff[(i-1)%len(staff)]
    prefix=f'{reported:%y%m%d}-{i:04d}';info=response+timedelta(minutes=20+i%4*10)
    events=[(reported,'客户报修','电话','记录客户描述的问题：'+s['failure']+'；使用环境：'+s['environment']),
            (response,'首次响应','电话','确认SN和客户资料，安排资料收集'),(info,'资料收集','邮件','登记客户提供的供电、环境与安装资料；缺项另列'),
            (reported+timedelta(hours=2+i%3),'远程核对','视频','按问题类别整理排查记录，制造原因和责任尚未认定')]
    if closed:events.append((closed,'台账关闭','内部记录','与原售后单关闭时间对应；模拟资料整理完成，非客户签章证明'))
    elif reported+timedelta(days=1+i%2)<cutoff:events.append((reported+timedelta(days=1+i%2),'进度记录','电话','尚需补充现场资料；保持原售后单跟进中状态'))
    for j,(when,kind,channel,note) in enumerate(sorted(events),1):
        assert reported<=when<=cutoff and (not closed or when<=closed)
        tables['service_events'].append(dict(id=f'SHJL-{prefix}-{j:02d}',service_id=s['id'],occurred=iso(when),kind=kind,channel=channel,owner_id=owner,description=note,source_kind='合成过程记录'))
    for j,kind in enumerate(['补充工况资料','核对处置记录'],1):
        due=reported+timedelta(hours=4 if j==1 else 7) if closed else reported+timedelta(hours=(24,72,168)[(i//3+j)%3])
        completed=reported+timedelta(hours=(3+(i%5==0)*1.5) if j==1 else 6) if closed else (response+timedelta(hours=1) if j==1 and (i//3)%3 else None)
        status='已完成' if completed else '待资料' if j==1 else '执行中'
        tables['service_tasks'].append(dict(id=f'SHRW-{prefix}-{j:02d}',service_id=s['id'],created=iso(response),kind=kind,owner_id=owner,due=iso(due),completed=iso(completed) if completed else None,status=status,description=('整理客户供电、环境及安装资料，并标记尚未核实的字段' if j==1 else '核对服务过程与原SN、交付和出厂检测记录，记录仍缺少的证据'),result='模拟任务资料已登记，客户自报数值仍待现场核实' if completed else None))
    p=products[units[s['unit_id']]['product_id']]
    conditions=[('供电线电压',None if i%4==0 else p['voltage']+[-8,3,12][i%3],'V','客户未提供读数' if i%4==0 else '客户自报供电读数，未提供测量仪器及校准证据'),
                ('环境温度',None if i%5==0 else 22+i%12,'℃','客户未提供温度记录' if i%5==0 else '客户自报环境温度，未核实测量点与测量时刻'),
                ('安装资料',None,None,['地脚紧固资料未提供','已提供安装方向描述，照片待核对','负载联接说明待补充'][i%3])]
    for j,(item,value,unit,note) in enumerate(conditions,1):
        tables['service_conditions'].append(dict(id=f'SHGK-{prefix}-{j:02d}',service_id=s['id'],recorded=iso(info),item=item,value=value,unit=unit,description=note,source_kind='客户自报（模拟）',status='待核实' if value is not None or item=='安装资料' else '未提供',owner_id=owner))
out={'notice':'全部为合成模拟数据；基于现有45张售后单补充过程、任务和客户自报工况。保留原报修、响应、关闭及费用；不代表实际客户沟通、现场测量、批准结案或故障原因。','as_of':AS_OF,'schema_version':1,'schemas':{k:SCHEMAS[k] for k in tables},'tables':tables}
(ROOT/'data/service_scenario.json').write_text(json.dumps(out,ensure_ascii=False,indent=2))
print(json.dumps({k:len(v) for k,v in tables.items()},ensure_ascii=False))
