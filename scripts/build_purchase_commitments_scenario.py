"""Synthetic complete supplier commitments, derived from existing purchase IDs."""
import os,sys,json
from datetime import date,timedelta
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings')
import django;django.setup()
from app import analytics,supply
from app.schema import SCHEMAS

d=analytics.tables();original=supply.SupplyData(d);versions=[];lines=[];cases={}
buyers=[e['id'] for e in d['employees'] if e['department_id']=='D10' and e['active']]
assert buyers
def add(p,idx,version,previous,status='模拟确认',future=False,suffix=''):
    vid=f'PC2609-{idx:05d}-V{version:02d}{suffix}'
    due=date.fromisoformat(p['due']);changed=version>1
    when=(date(2026,10,2) if future else due+timedelta(days=1 if idx%2 else -1) if changed else date.fromisoformat(p['ordered']))
    confirmed=when.isoformat()+'T10:00:00';effective=when.isoformat()+'T11:00:00';registered=when.isoformat()+'T12:00:00'
    if status!='模拟确认':confirmed=None;effective='2026-09-30T11:00:00';registered='2026-09-30T12:00:00'
    dates=[p['due']] if not changed else [(due+timedelta(days=2)).isoformat(),'2026-10-03' if p['remaining_qty'] else (due+timedelta(days=4)).isoformat()]
    qty=float(p['qty']);first=qty*.4
    if p['unit']=='件':first=float(int(first))
    quantities=[qty] if len(dates)==1 else [first,qty-first]
    reason='首版登记原采购承诺，数量与采购行一致。' if not changed else ('供应商分两批交付，首批待催到，尾批模拟确认10月3日到货；未登记ETA或检验可用时间。' if p['remaining_qty'] else '供应商调整分批交付计划；保留原承诺，实到与检验依据仍以原记录核对。')
    v=dict(id=vid,purchase_line_id=p['id'],version=version,previous_id=previous,status=status,confirmed=confirmed,effective=effective,registered=registered,total_qty=qty,line_count=len(dates),owner_id=buyers[(idx-1)%len(buyers)],reference=f'模拟供应商确认-PC2609-{idx:05d}-{version:02d}',reason=reason)
    versions.append(v)
    for seq,(deadline,amount) in enumerate(zip(dates,quantities),1):
        lines.append(dict(id=vid+f'-D{seq:02d}',version_id=vid,sequence=seq,due=deadline,qty=amount,reference=f'模拟分批交付凭据-{idx:05d}-{version:02d}-{seq:02d}',note='完整版本内的到货承诺；与真实收货段次无显式匹配，仅用于分析分配演练。'))
    return v

for idx,p in enumerate(original.po_rows,1):
    if idx in {13,47,99}:cases[p['id']]='缺少确认版本';continue
    root=add(p,idx,1,None);current=root
    if idx%3==0 or p['remaining_qty'] or idx in {5,6,7,8,9}:
        current=add(p,idx,2,root['id'])
    if idx==5:current['total_qty']+=5;cases[p['id']]='最新版本数量不符，不回退首版'
    if idx==6:current['line_count']=3;cases[p['id']]='完整版本声明缺段'
    if idx==7:
        [r for r in lines if r['version_id']==current['id']][1]['sequence']=1;cases[p['id']]='交付段次重复'
    if idx==8:current['version']=3;cases[p['id']]='前序版本不连续'
    if idx==9:current['confirmed']=None;cases[p['id']]='确认状态缺确认时间，不回退首版'
    if idx==11:add(p,idx,1,None,suffix='B');cases[p['id']]='同一版本号重复确认'
    if idx%17==0:add(p,idx,current['version']+1,current['id'],future=True)
    elif idx%19==0:add(p,idx,current['version']+1,current['id'],status='草稿')
    elif idx%23==0:add(p,idx,current['version']+1,current['id'],status='作废')

data={'as_of':analytics.AS_OF,'schema_version':'motor-source-v1','notice':'全部合成模拟采购承诺，使用现有模拟采购行与采购工号。每版为完整分段快照，保留原采购日期与数量；演练分批改期、草稿、作废、未来生效、缺确认时间、缺段、数量冲突与重复版号。异常版本用于展示待核对，不代表真实供应商承诺或审批。实到、检验和入库事实未修改。',
      'schemas':{k:SCHEMAS[k] for k in ['purchase_commitment_versions','purchase_commitment_lines']},
      'tables':{'purchase_commitment_versions':versions,'purchase_commitment_lines':lines},'cases':cases}
(ROOT/'data/purchase_commitments_scenario.json').write_text(json.dumps(data,ensure_ascii=False,indent=2))
new=supply.SupplyData(d);assert [supply.clean(p) for p in new.po_rows]==[supply.clean(p) for p in original.po_rows]
from app.purchase_commitments import Commitments,summary
engine=Commitments(d|data['tables']);stats=summary(engine.rows)
assert stats['attention']==len(cases) and stats['changed']>0 and stats['late_change']>0 and stats['valid']>100,stats
assert stats['original_rate']==supply.summary(original.po_rows,'purchase')['ontime_rate']
print(json.dumps({'tables':{k:len(v) for k,v in data['tables'].items()},'cases':cases,'summary':stats},ensure_ascii=False,indent=2))
