"""Deterministic, separate laboratory trial facts; never rewrite old tests."""
import hashlib
import json
import os
import random
import sys
from datetime import datetime,timedelta
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT));os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings')
import django;django.setup()
from app.schema import SCHEMAS
from app.models import Record
from app.spc_schema import DATASETS
from app.spc_source_contract import issues


def main():
    main_file=ROOT/'data/platform.sqlite3';before=hashlib.sha256(main_file.read_bytes()).hexdigest()
    assert before==json.loads((ROOT/'data/spc-before/manifest.json').read_text())['database_sha256']
    units=sorted([r.values for r in Record.objects.filter(dataset='units') if r.values['product_id']=='CP.00008.A'],key=lambda r:r['id'])
    assert len(units)==100
    profiles=[('normal','受控波动样例'),('shift','监控段均值偏移'),('exceed','单点超过模拟公差'),
              ('monitor_gap','监控段采样缺号'),('baseline_gap','基线段采样缺号'),
              ('replicate','基线重复样件'),('binary','旋向二值项目'),('constant','基线零变异'),
              ('small','小批量不足样本'),('unknown_order','实际采样顺序未知')]
    tables={key:[] for key in DATASETS};expected=[]
    for index,(kind,name) in enumerate(profiles,1):
        start=datetime(2026,9,27,8)+timedelta(hours=3*(index-1))
        count=12 if kind=='small' else 80;baseline=6 if kind=='small' else 40
        study_id=f'SPC2609-{index:04d}';binary=kind=='binary';unit='bool' if binary else 'Ω'
        method='SIM-DIR.01' if binary else 'SIM-R-25C.01'
        study=dict(id=study_id,name=name,product_id='CP.00008.A',
            spec_id='JC-CP.00008.A-'+('DIR' if binary else 'R')+'-A',equipment_id='SB-08-01',
            stage='终检实验室受控试验',protocol_version=f'SPCPL-0008-{index:02d}.V1',
            method='I_MR',measurement_method=method,unit=unit,started=start.isoformat(),
            finished=(start+timedelta(minutes=count*2+1)).isoformat(),status='已结束',
            expected_points=count,baseline_end=baseline,
            order_basis='未知' if kind=='unknown_order' else '设备计数（模拟）',owner_id='E00009',
            measurement_system_ref=None,conditions='25C附近受控环境；数值和顺序均为本次独立合成试验',
            purpose='算法与采样资料演练',note='独立于旧终检会话；没有工厂测量系统研究或正式稳定性审批。'+name)
        assert not issues('spc_studies',study);tables['spc_studies'].append(study)
        rng=random.Random(260927+index)
        for sequence in range(1,count+1):
            # An absent source is kept absent. Analysis must surface the gap.
            if kind=='monitor_gap' and sequence==54 or kind=='baseline_gap' and sequence==19:continue
            observed=start+timedelta(minutes=sequence*2)
            value=1.0 if binary else round(.323+rng.gauss(0,.0016),6)
            if kind=='shift' and sequence>40:value=round(value+.010,6)
            if kind=='exceed' and sequence==61:value=.3498
            if kind=='binary' and sequence==52:value=0.0
            if kind=='constant':value=.324
            selected=sequence-2 if kind=='replicate' and sequence==18 else sequence-1
            sn=units[selected]['id'];assert units[selected]['assembly_at']<=observed.isoformat()
            point=dict(id=f'{study_id}-O{sequence:04d}',study_id=study_id,sequence=sequence,
                unit_id=sn,measured=None if kind=='unknown_order' else observed.isoformat(),
                registered=(observed+timedelta(seconds=20)).isoformat(),value=value,unit=unit,
                replicate=2 if kind=='replicate' and sequence==18 else 1,method_version=method,
                temperature_c=round(25+rng.uniform(-.15,.15),2),state='有效',operator_id='E00009',
                reference=f'SIM-ACQ-{index:02d}-{sequence:06d}',
                note='缺实际采样时间与顺序依据' if kind=='unknown_order' else '独立受控模拟观测')
            assert not issues('spc_observations',point);tables['spc_observations'].append(point)
        event_sequence=41 if kind=='shift' else 61 if kind=='exceed' else 54 if kind=='monitor_gap' else 19 if kind=='baseline_gap' else 18 if kind=='replicate' else 1
        event_time=start+timedelta(minutes=event_sequence*2)
        event=dict(id=f'{study_id}-E01',study_id=study_id,sequence=event_sequence,
            occurred=event_time.isoformat(),registered=(event_time+timedelta(seconds=30)).isoformat(),
            category='模拟调整' if kind=='shift' else '资料说明',description=name+'；仅为合成事件，不证明实际原因',
            operator_id='E00009',reference=f'SIM-EVENT-{index:02d}-01')
        tables['spc_events'].append(event)
        expected.append(dict(id=study_id,profile=kind,planned=count,
                             recorded=sum(p['study_id']==study_id for p in tables['spc_observations']),
                             baseline_end=baseline))
    assert {key:len(rows) for key,rows in tables.items()}==dict(spc_studies=10,spc_observations=730,spc_events=10)
    report=dict(classification='新增独立合成试验；不是原检测顺序补录',business_cutoff='2026-10-01T18:00:00',
                main_database_sha256=before,tables=tables,schemas={key:SCHEMAS[key] for key in DATASETS},
                profiles=expected,old_production_test_records_unchanged=True)
    output=ROOT/'data/spc_scenario.json';output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    assert hashlib.sha256(main_file.read_bytes()).hexdigest()==before
    print(json.dumps(dict(success=True,studies=10,observations=730,events=10,main_database_unchanged=True)))


if __name__=='__main__':main()
