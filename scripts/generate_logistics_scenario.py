"""Deterministic synthetic shipment records; business data enters via XLSX only."""
import os,sys,json
from pathlib import Path
from datetime import datetime,timedelta
from collections import defaultdict
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings')
import django;django.setup()
from app.models import Record
from app.schema import SCHEMAS
from app.logistics import DATASETS

tables={k:[] for k in DATASETS};packs=defaultdict(list)
for r in Record.objects.filter(dataset='shipment_units').values_list('values',flat=True):packs[r['shipment_id']].append(r['unit_id'])
ships=list(Record.objects.filter(dataset='shipments').order_by('business_key').values_list('values',flat=True))
fmt=lambda d:d.isoformat(timespec='seconds')
for i,s in enumerate(ships,1):
    # Missing delivery terms, no receipt, partial, refusal, future and void cases
    # are intentionally retained so the UI cannot infer full receipt from signed.
    mode=i%10;sid=s['id'];dispatch=f'YS2609-{i:06d}';sent=datetime.fromisoformat(s['shipped']);hand=sent+timedelta(minutes=20);arrival=datetime.fromisoformat(s['signed']) if s.get('signed') else hand+timedelta(days=2)
    if arrival<hand:arrival=hand+timedelta(days=2)
    promise=hand+timedelta(days=1 if mode==3 else 3)
    tables['transport_dispatches'].append(dict(id=dispatch,shipment_id=sid,handed=None if mode==8 else fmt(hand),promised=None if mode==9 else fmt(promise),route='模拟工厂—客户区域配送',reference=None if mode==8 else f'JJ-{i:06d}'))
    for j,kind,t,location in [(1,'已交接',hand,'模拟工厂发运区'),(2,'运输中',hand+timedelta(hours=6),'模拟区域转运点')]:
        tables['transport_events'].append(dict(id=f'WLJD-{i:06d}-{j:02d}',dispatch_id=dispatch,occurred=fmt(t),kind=kind,location=location,note='合成运输登记，仅演练',voided=False))
    if mode!=4:
        tables['transport_events'].append(dict(id=f'WLJD-{i:06d}-03',dispatch_id=dispatch,occurred=fmt(arrival-timedelta(minutes=10)),kind='物流到达',location='模拟客户收货区',note='物流到达与客户签收分别登记',voided=False))
    else:
        tables['transport_events'].append(dict(id=f'WLJD-{i:06d}-03',dispatch_id=dispatch,occurred=fmt(hand+timedelta(hours=8)),kind='运输异常',location='模拟区域转运点',note='模拟转运延误，待补客户签收证据',voided=False))
    units=sorted(packs[sid]);groups=[]
    if mode==4:continue
    if mode==1:groups=[(units[:max(1,len(units)//2)],arrival,False,'接收')]
    elif mode==2:groups=[(units[:-1],arrival,False,'接收'),(units[-1:],arrival,False,'拒收')]
    elif mode==5:groups=[(units[:len(units)//2],arrival-timedelta(hours=2),False,'接收'),(units[len(units)//2:],arrival,False,'接收')]
    elif mode==6:groups=[(units,datetime(2026,10,3,12),False,'接收')]
    elif mode==7:groups=[(units,arrival-timedelta(hours=1),True,'拒收'),(units,arrival,False,'接收')]
    else:groups=[(units,arrival,False,'接收')]
    for j,(members,t,voided,outcome) in enumerate(groups,1):
        if not members:continue
        rid=f'QS2609-{i:06d}-{j:02d}'
        tables['customer_receipts'].append(dict(id=rid,dispatch_id=dispatch,received=fmt(t),document=f'MN-QSPJ-{i:06d}-{j:02d}',receiver='模拟客户收货岗位',voided=voided))
        for k,uid in enumerate(members,1):tables['customer_receipt_units'].append(dict(id=f'{rid}-{k:04d}',receipt_id=rid,unit_id=uid,outcome=outcome,reason='作废演练' if voided else '模拟包装破损，拒收待协调' if outcome=='拒收' else '模拟签收登记，不代表质量验收'))
scenario={'schema_version':1,'as_of':'2026-10-01T18:00:00','seed':'logistics-v1','notice':'全部为合成模拟数据。发运、物流到达与客户签收分别登记；同一SN仅一份有效接收结论，分批接收、拒收、作废及未来记录单列。文件编号为模拟引用，无真实签收原件；不代表质量验收、退货入库或收入确认。','schemas':{k:SCHEMAS[k] for k in DATASETS},'tables':tables}
(ROOT/'data/logistics_scenario.json').write_text(json.dumps(scenario,ensure_ascii=False,indent=2))
print(json.dumps({k:len(v) for k,v in tables.items()},ensure_ascii=False))
