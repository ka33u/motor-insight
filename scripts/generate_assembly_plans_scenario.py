"""Build synthetic commitments as XLSX inputs; never writes business records."""
import os,sys,json,copy
from collections import defaultdict
from datetime import datetime,timedelta
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings')
import django;django.setup()
from app.models import Record
from app.schema import SCHEMAS
from app import assembly_plans as p
wo={r['id']:r for r in Record.objects.filter(dataset='work_orders').values_list('values',flat=True)}
units=list(Record.objects.filter(dataset='units').values_list('values',flat=True));byday=defaultdict(list)
for u in units:byday[u['assembly_at'][:10]].append(u)
used={u['work_order_id'] for u in units};spares=[k for k in sorted(wo) if k not in used];tables={ds:[] for ds in p.DATASETS}
def add(date_key,version,qty,released,reason,status='已发布'):
    series='SCJH-ZP-'+date_key[2:].replace('-','');key=f'{series}-V{version:02d}';prev=(datetime.fromisoformat(date_key)-timedelta(days=1)).date().isoformat()
    h=dict(id=key,series=series,version=version,supersedes_id=f'{series}-V{version-1:02d}' if version>1 else None,production_date=date_key,freeze_at=prev+'T18:00:00',released=released,status=status,owner='模拟总装计划岗位',line_count=len(qty),reason=reason,basis='模拟装配日计划假设；每版为整厂完整快照，不是历史真实承诺或排程批准。')
    tables[p.DATASETS[0]].append(h)
    for i,(work_order,amount) in enumerate(sorted(qty.items()),1):tables[p.DATASETS[1]].append(dict(id=f'{key}-L{i:03d}',version_id=key,work_order_id=work_order,product_id=wo[work_order]['product_id'],qty=amount,reason='合成安排：'+reason))
    return h
def check(date_key,status='完整',stale=False):
    when=(datetime.fromisoformat(date_key)+timedelta(days=1)).date().isoformat()+'T08:00:00'
    tables[p.DATASETS[2]].append(dict(id='ZPQR-'+date_key[2:].replace('-',''),production_date=date_key,through=date_key+'T23:59:59',confirmed=when,data_signature='0'*64 if stale else p.signature(byday[date_key]),status=status,owner='模拟装配数据岗位',note='已按当日整机档案逐台核对的合成确认；不代表质检或入库批准。',voided=False))
for i,date_key in enumerate(sorted(byday)):
    actual=defaultdict(int)
    for u in byday[date_key]:actual[u['work_order_id']]+=1
    extras=spares[i*2:i*2+2];base=dict(actual);cut=sum(wo[k]['planned_qty'] for k in extras);first=sorted(actual)[0]
    # Keep the same 900 total while changing its order mix: aggregate quantity
    # alone would wrongly imply complete execution of the original schedule.
    removed=base.pop(first);cut-=removed
    for k in sorted(base):
        if cut<=0:break
        delta=min(5,base[k],cut);base[k]-=delta;cut-=delta
    assert cut==0
    base.update({k:wo[k]['planned_qty'] for k in extras});prev=(datetime.fromisoformat(date_key)-timedelta(days=1)).date().isoformat()
    add(date_key,1,base,prev+'T16:00:00','首版模拟承诺；包含待执行工单并保留未排产样例')
    revised=dict(base);revised[first]=actual[first];revised.pop(extras[0]);add(date_key,2,revised,prev+'T20:00:00','冻结后调整：补排原未排工单并撤下一项待执行安排')
    if date_key=='2026-09-22':add(date_key,3,dict(actual),'2026-09-24T09:00:00','期后调整示例：按已登记队列重排，不能据此覆盖原承诺兑现率')
    if date_key=='2026-09-24':add(date_key,3,dict(actual),None,'待讨论的新安排，未发布不进入当前计划','草稿')
    if date_key=='2026-09-25':add(date_key,3,dict(actual),'2026-10-02T09:00:00','未来发布示例，业务截止前不生效')
    check(date_key,'待补' if date_key=='2026-09-24' else '完整',stale=date_key=='2026-09-25')
for j,date_key in enumerate(['2026-09-26','2026-10-01','2026-10-02']):
    group=spares[10+j*6:16+j*6];qty={k:wo[k]['planned_qty'] for k in group};prev=(datetime.fromisoformat(date_key)-timedelta(days=1)).date().isoformat()
    add(date_key,1,qty,prev+'T16:00:00','模拟待执行日计划；对照零产量、进行中和未来日期')
    if date_key=='2026-09-26':check(date_key)
notice='全部为合成计划，用于版本与兑现演练。按既有工单构造900台的原计划并故意改变工单组合；不声称还原历史承诺。每版完整快照，冻结点为前一日18时，发布时间与调整说明单独保留。装配台数不等于检验合格或入库。'
scenario={'schema_version':1,'as_of':'2026-10-01T18:00:00','seed':'assembly-plans-v1','notice':notice,'schemas':{ds:SCHEMAS[ds] for ds in p.DATASETS},'tables':tables}
(ROOT/'data/assembly_plans_scenario.json').write_text(json.dumps(scenario,ensure_ascii=False,indent=2));print(json.dumps({ds:len(rows) for ds,rows in tables.items()},ensure_ascii=False))
