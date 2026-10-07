"""Detailed synthetic discrete curves using existing Excel business identities."""
import json
import os
import sys
from datetime import datetime,timedelta
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings')
import django;django.setup()
from app.models import Record
from app.schema import SCHEMAS
from app.curing_schema import DATASETS
from app import curing
from app.analytics import AS_OF

refs={ds:{r['id']:r for r in Record.objects.filter(dataset=ds).values_list('values',flat=True)} for ds in ('operations','batches','work_orders','products','production_resources','equipment','routes','allocations','order_lines')}
ops=sorted([o for o in refs['operations'].values() if o['process']=='浸漆固化' and o['finished']],key=lambda o:(o['started'],o['id']))
chosen=[];last={}
for o in ops:
    if o['started']>=last.get(o['resource_id'],''):
        chosen.append(o);last[o['resource_id']]=o['finished']
    if len(chosen)==34:break
assert len(chosen)==34
cases=[('normal','ready'),('normal2','ready'),('normal3','ready'),('inclusive','ready'),('exact45','ready'),
       ('overtemp','out'),('short','out'),('gap','missing'),('missing_point','missing'),('missing_channel','missing'),
       ('wrong_unit','attention'),('duplicate_time','attention'),('duplicate_sequence','attention'),('sequence_gap','attention'),
       ('partial','open'),('missing_start','missing'),('missing_end','missing'),('unknown_version','attention'),('expired','attention'),
       ('extra_channel','attention'),('batch_mismatch','attention'),('over_qty','attention'),('zero_qty','attention'),('no_load','missing'),
       ('future_point','attention'),('voided','voided'),('unclosed','open'),('future','future'),
       ('overlap_a','attention'),('overlap_b','attention'),('split_hold','out'),('ambiguous_profile','attention'),('invalid_limits','attention'),('part_sensor','attention')]
tables={ds:[] for ds in DATASETS};expected={};case_keys={}
for n,((case,state),op) in enumerate(zip(cases,chosen),1):
    if case=='overlap_b':op=chosen[n-2]
    start=datetime.fromisoformat(op['started']);end=datetime.fromisoformat(op['finished']);wo=refs['work_orders'][op['work_order_id']]
    assert (end-start).total_seconds()==5400
    code=f'GT-{op["equipment_id"].replace("-","")}-{start:%y%m%d}-{n:04d}'
    if case=='future':start=datetime(2026,10,2,8);end=start+timedelta(minutes=90);code=f'GT-{op["equipment_id"].replace("-","")}-261002-{n:04d}'
    profile=dict(id=f'GF-CURE-26-{n:03d}-A01',program_code=f'XH-DZ-{n:03d}',program_version='A.01',product_id=wo['product_id'],route_version=wo['route_version'],
                 effective='2026-09-01T00:00:00',expires='2026-09-15T00:00:00' if case=='expired' else None,
                 min_hold_minutes=45.0,max_gap_minutes=5.0,basis='全部为自编模拟：炉温145至155℃，相邻采样不超过5分钟，支持连续45分钟，绝对上限170℃。非生产工艺标准。')
    tables['cure_profiles'].append(profile)
    for c in ('T01','T02'):
        tables['cure_channels'].append(dict(id=f'{profile["id"]}-{c}',profile_id=profile['id'],channel_code=c,position='炉腔前部' if c=='T01' else '炉腔后部',
            sensor_kind='工件芯温' if case=='part_sensor' else '炉温',hold_lsl=156.0 if case=='invalid_limits' else 145.0,hold_usl=155.0,max_temp_c=170.0,basis='合成温度通道；未证明校准、时钟同步、温场均匀性及工件温度。'))
    run=dict(id=code,equipment_id=op['equipment_id'],resource_id=op['resource_id'],program_code=profile['program_code'],program_version='A.99' if case=='unknown_version' else 'A.01',
             started=start.isoformat(),finished=None if case=='unclosed' else end.isoformat(),registered=(end+timedelta(minutes=10)).isoformat(),capture_state='部分' if case in ('partial','unclosed') else '未采集' if case=='future' else '完整',
             load_count=0,sample_count=0,channel_count=0,operator_id=op['employee_id'],voided=case=='voided',reference=f'MOCK-CURVE-EXPORT-26-{n:04d}',
             note=f'自编独立案例 {case}；不是设备真实导出或实际在炉状态；装载量为半成品件数。')
    tables['cure_runs'].append(run);expected[code]=state;case_keys[case]=code
    if case not in ('no_load','future'):
        bad_batch=next(b for b in refs['batches'].values() if b['work_order_id']!=op['work_order_id'] and b['kind']=='定子') if case=='batch_mismatch' else None
        tables['cure_loads'].append(dict(id=f'ZL-CURE-26-{n:04d}-01',run_id=code,operation_id=op['id'],batch_id=bad_batch['id'] if bad_batch else op['object_id'],
             qty=op['input_qty']+1 if case=='over_qty' else 0 if case=='zero_qty' else op['input_qty'],unit='件',position='料架A / 第01层',note='按既有Excel报工与批次声明对应；本炉逐件订单关系未采集。'))
    if case=='ambiguous_profile':
        p=dict(profile,id=profile['id']+'-DUP');tables['cure_profiles'].append(p)
    for c in ('T01','T02') if case!='future' else ():
        if case=='missing_channel' and c=='T02':continue
        selected=[]
        for j in range(19):
            if case=='gap' and c=='T01' and j in (8,9):continue
            if case=='missing_start' and c=='T01' and j==0:continue
            if case in ('missing_end','unclosed') and j==18:continue
            value=[80,105,130][j] if j<3 else 150+(n%3-1)*.4+(.2 if c=='T02' else 0) if j<=15 else [120,80,50][j-16]
            if case=='inclusive' and 3<=j<=15:value=145 if c=='T01' else 155
            if case=='exact45' and j>12:value=120
            if case=='short' and j>7:value=120
            if case=='overtemp' and c=='T01' and j==9:value=190
            if case=='split_hold' and j==9:value=130
            measured=start+timedelta(minutes=5*j)
            if case=='duplicate_time' and c=='T01' and j==9:measured-=timedelta(minutes=5)
            if case=='future_point' and c=='T01' and j==18:measured=datetime(2026,10,2,8)
            missing=case=='missing_point' and c=='T01' and j==9
            selected.append(dict(id=f'WD-CURE-26-{n:04d}-{c}-{j+1:04d}',run_id=code,channel_code=c,sequence=len(selected)+1,
                 measured=measured.isoformat(),value=None if missing else round(value,3),unit='K' if case=='wrong_unit' and c=='T01' and j==9 else '℃',
                 quality='缺测' if missing else '有效',reference=f'{run["reference"]} / {c} / 原始行{j+2:04d}',note='自编5分钟离散采样；未插值、未补零。'))
        if case=='duplicate_sequence' and c=='T01':selected[9]['sequence']=9
        if case=='sequence_gap' and c=='T01':
            for s in selected[9:]:s['sequence']+=1
        tables['cure_samples']+=selected
    if case=='extra_channel':
        tables['cure_samples'].append(dict(tables['cure_samples'][-1],id=f'WD-CURE-26-{n:04d}-T99-0001',channel_code='T99',sequence=1,measured=start.isoformat()))
    run['load_count']=sum(l['run_id']==code for l in tables['cure_loads']);run['sample_count']=sum(s['run_id']==code for s in tables['cure_samples']);run['channel_count']=len({s['channel_code'] for s in tables['cure_samples'] if s['run_id']==code})

result=curing.analyze(tables,refs,AS_OF)
actual={r['run']['id']:r['state'] for r in result['rows']}
assert actual==expected,[(k,actual[k],v) for k,v in expected.items() if actual[k]!=v]
def row(case):return next(r for r in result['rows'] if r['run']['id']==case_keys[case])
assert [c['longest_hold_minutes'] for c in row('normal')['channels']]==[60,60]
assert [c['longest_hold_minutes'] for c in row('exact45')['channels']]==[45,45]
assert [c['longest_hold_minutes'] for c in row('split_hold')['channels']]==[25,25]
assert len(row('overlap_a')['conflict_ids'])==len(row('overlap_b')['conflict_ids'])==1
output=dict(notice=curing.NOTICE,as_of=AS_OF,tables=tables,schemas={ds:SCHEMAS[ds] for ds in DATASETS},expected=expected,cases=case_keys,
            counts={ds:len(tables[ds]) for ds in DATASETS},summary=curing.scoped(result,curing.filters({}))['summary'])
(ROOT/'data/curing_scenario.json').write_text(json.dumps(output,ensure_ascii=False,indent=2)+'\n')
selected={}
selected['operations']={k:refs['operations'][k] for k in {r['operation_id'] for r in tables['cure_loads']}}
selected['batches']={k:refs['batches'][k] for k in {r['batch_id'] for r in tables['cure_loads']}}
selected['work_orders']={k:refs['work_orders'][k] for k in {r['work_order_id'] for r in selected['batches'].values()}}
pids={r['product_id'] for r in selected['work_orders'].values()}|{r['product_id'] for r in tables['cure_profiles']}
selected['products']={k:refs['products'][k] for k in pids}
selected['production_resources']={k:refs['production_resources'][k] for k in {r['resource_id'] for r in tables['cure_runs']}}
selected['equipment']={k:refs['equipment'][k] for k in {r['equipment_id'] for r in tables['cure_runs']}}
selected['routes']={k:r for k,r in refs['routes'].items() if r['product_id'] in pids}
selected['allocations']={k:r for k,r in refs['allocations'].items() if r['work_order_id'] in selected['work_orders']}
selected['order_lines']={k:refs['order_lines'][k] for k in {r['order_line_id'] for r in selected['allocations'].values()}}
(ROOT/'tests/fixtures/curing_scenario.json').write_text(json.dumps(dict(**{k:v for k,v in output.items() if k!='schemas'},refs=selected),ensure_ascii=False)+'\n')
print(json.dumps(dict(counts=output['counts'],summary=output['summary']),ensure_ascii=False))
