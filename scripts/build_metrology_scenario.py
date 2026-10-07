"""Build detailed synthetic inputs; actual facts enter only through XLSX ingestion."""
import os,sys,json,sqlite3
from pathlib import Path
from collections import defaultdict
from datetime import datetime,timedelta
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings')
import django;django.setup()
from app.schema import SCHEMAS
from app import metrology as eng

def later(stamp,minutes=1):return (datetime.fromisoformat(stamp)+timedelta(minutes=minutes)).isoformat(timespec='seconds')

with sqlite3.connect('file:'+str(ROOT/'data/platform.sqlite3')+'?mode=ro',uri=True) as c:
    data=defaultdict(list)
    for ds,v in c.execute('select dataset,"values" from app_record order by business_key'):data[ds].append(json.loads(v))
assert not any(data[k] for k in eng.TABLES),'refuses to generate over existing calibration facts'
idx={k:{r['id']:r for r in data[k]}for k in eng.BASE}
new={k:[] for k in eng.TABLES};owner='E00153';registry={};source_rows=[]
for stage,(dataset,field) in eng.SOURCE.items():
    for raw in data[dataset]:
        if stage=='test':
            parent=idx['test_sessions'][raw['session_id']];spec=idx['test_specs'][raw['spec_id']]
            at=parent['tested'];parameter=spec['test_code'];eid=parent['equipment_id'];alias=eid+'-'+parameter;person=parent['operator_id'];plan=operation=None
        elif stage=='incoming':
            parent=idx['incoming_checks'][raw['check_id']];spec=idx['incoming_specs'][raw['spec_id']]
            at=parent['checked'];parameter=spec['parameter'];eid=None;alias=raw['instrument'];person=parent['inspector_id'];plan=idx['incoming_check_plans'][parent['plan_id']];operation=None
        else:
            parent=idx['process_checks'][raw['check_id']];spec=idx['process_specs'][raw['spec_id']]
            at=parent['checked'];parameter=spec['parameter'];alias=raw['instrument'];person=parent['inspector_id'];plan=idx['process_check_plans'][parent['plan_id']];operation=idx['operations'][plan['operation_id']];eid=operation['equipment_id']
        key=(stage,alias,parameter,spec['unit']);registry[key]=dict(stage=stage,alias=alias,parameter=parameter,unit=spec['unit'],equipment_id=eid)
        source_rows.append(dict(stage=stage,field=field,raw=raw,parent=parent,spec=spec,at=at,person=person,key=key,
                                source_digest=eng.digest([raw,parent,spec,plan,operation])))
for i,(key,r) in enumerate(sorted(registry.items()),1):
    iid=f'JL-YQ-{i:05d}';r['id']=iid
    new['metrology_instruments'].append(dict(id=iid,asset_code=f'JL-ZC-{i:05d}',name=f"{eng.STAGES[r['stage']]}{r['parameter']}通道{i:03d}",
        stage=r['stage'],parameter=r['parameter'],unit=r['unit'],source_alias=r['alias'],equipment_id=r['equipment_id'],tool_id=None,
        active_from='2026-01-01T00:00:00',retired=None,owner_id=owner,
        note='新编模拟仪器/通道身份；采集点与使用记录的对应是显式模拟资料，不是对真实设备身份的推定。'))
instruments={r['id']:r for r in new['metrology_instruments']}
for i,t in enumerate([r for r in data['tools'] if r['kind']=='计量器具'],1):
    new['metrology_instruments'].append(dict(id=f'JL-DZ-{i:05d}',asset_code=f'JL-DZ-{i:05d}',name=t['name'],stage='档案',parameter='未指定',unit='未指定',
        source_alias=t['id'],equipment_id=t['equipment_id'],tool_id=t['id'],active_from='2026-01-01T00:00:00',retired=None,owner_id=owner,
        note='原计量台账身份参照；尚无逐测量使用对应、校准证书或适用要求，不能据当前到期日期判断历史测量。'))
requirements=sorted({(r['stage'],r['parameter'],r['unit'])for r in registry.values()})
for i,(stage,parameter,unit) in enumerate(requirements,1):
    sid=f'JL-YQG-{i:04d}'
    new['metrology_rules'].append(dict(id=sid+'-V01',series=sid,version=1,previous_id=None,status='已登记',stage=stage,parameter=parameter,unit=unit,
        required=parameter not in ['DIR','ROUGH'] if stage in ['test','incoming'] else True,
        effective='2026-01-01T00:00:00',expires=None,registered='2026-01-01T00:00:00',owner_id=owner,reference='模拟适用要求-'+sid,
        note='仅用于合成工作流演练，覆盖当前该环节同特性/单位的模拟规范版本；不是企业批准的计量要求。旋向及演示辅助表面读数另列不要求登记。'))

def calibration(iid,series,performed,until,version=1,previous=None,result='符合登记范围',status='已登记',registered=None,start=None,note='模拟校准登记，无真实实验室或证书原件核验。'):
    inst=instruments[iid]
    return dict(id=series+f'-V{version:02d}',series=series,version=version,previous_id=previous,status=status,instrument_id=iid,
        performed=performed,valid_from=start or performed,valid_until=until,result=result,parameter=inst['parameter'],unit=inst['unit'],
        certificate_no='SIM-CERT-'+series,laboratory='模拟校准单位甲',registered=registered or later(performed,10),owner_id=owner,
        reference='模拟完整校准记录-'+series,note=note)

required_inst=[r for r in new['metrology_instruments'] if r['id'] in instruments and not (r['stage']=='test' and r['parameter']=='DIR' or r['stage']=='incoming' and r['parameter']=='ROUGH')]
for r in required_inst:
    iid=r['id'];serial=iid.rsplit('-',1)[-1]
    new['metrology_calibrations']+= [calibration(iid,'JL-JZ-'+serial+'-A','2026-01-01T08:00:00','2026-09-01T00:00:00'),
        calibration(iid,'JL-JZ-'+serial+'-B','2026-09-01T08:00:00','2026-12-01T00:00:00')]

def pick(stage,parameter=None,equipment=None):
    return next(r for r in new['metrology_instruments'] if r['stage']==stage and (parameter is None or r['parameter']==parameter) and (equipment is None or r['equipment_id']==equipment))
cases={}
expired=pick('test','R','SB-08-01');failed=pick('test','HV','SB-08-02');bad=pick('test','I0','SB-08-01');withdrawn=pick('test','NO','SB-08-02')
pending=pick('incoming','THK');missing=pick('incoming','RES');conflict=pick('process','METAL_TEMP');retired=pick('process','DIAMETER')
base={r['instrument_id']:r for r in new['metrology_calibrations'] if r['series'].endswith('-B')}
base[expired['id']]['valid_until']='2026-09-22T12:00:00';cases['expired_instrument']=expired['id']
new['metrology_calibrations'].append(calibration(failed['id'],'JL-JZ-FAIL','2026-09-23T08:00:00','2026-12-01T00:00:00',result='不符合登记范围',registered='2026-09-24T09:00:00'))
cases['failed_instrument']=failed['id']
original=base[bad['id']]
new['metrology_calibrations'].append(dict(original,id=original['series']+'-V02',version=2,previous_id=original['id'],valid_until='2026-08-31T00:00:00',registered='2026-09-25T18:00:00',note='模拟错误完整更正：失效起点早于实施时间；必须停止判断，不回退旧合格记录。'))
cases['bad_latest_instrument']=bad['id']
original=base[withdrawn['id']]
new['metrology_calibrations'].append(dict(original,id=original['series']+'-V02',version=2,previous_id=original['id'],status='撤销',registered='2026-09-24T18:00:00',note='模拟撤销；不使用更早周期掩盖最近登记已撤销。'))
cases['withdrawn_instrument']=withdrawn['id']
base[pending['id']]['valid_from']='2026-09-19T12:00:00';cases['pending_instrument']=pending['id']
new['metrology_calibrations']=[r for r in new['metrology_calibrations'] if r['instrument_id']!=missing['id']];cases['missing_instrument']=missing['id']
new['metrology_calibrations'].append(calibration(conflict['id'],'JL-JZ-SAME','2026-09-01T08:00:00','2026-12-01T00:00:00'));cases['conflict_instrument']=conflict['id']
retired['retired']='2026-09-20T12:00:00';cases['retired_instrument']=retired['id']
new['metrology_calibrations'].append(calibration(expired['id'],'JL-JZ-FUTURE','2026-10-05T08:00:00','2027-01-01T00:00:00',registered='2026-10-05T09:00:00'));cases['future_calibration']='JL-JZ-FUTURE-V01'
# A draft never supersedes a published record.
original=base[expired['id']]
new['metrology_calibrations'].append(dict(original,id=original['series']+'-D02',version=2,previous_id=original['id'],status='草稿',registered='2026-09-25T19:00:00',note='模拟草稿：不改变已登记校准。'))

for i,r in enumerate(source_rows,1):
    # Intentionally omitted usage evidence is visible as unknown, never guessed.
    if i%2603==0 and r['spec'].get('test_code')!='DIR' and r['spec'].get('parameter')!='ROUGH':
        cases.setdefault('missing_usage_readings',[]).append(r['stage']+':'+r['raw']['id']);continue
    sid=f'JL-SY-{i:06d}'
    row=dict(id=sid+'-V01',series=sid,version=1,previous_id=None,status='已登记',stage=r['stage'],
        measurement_id=None,incoming_reading_id=None,process_reading_id=None,instrument_id=registry[r['key']]['id'],measured=r['at'],
        registered=later(r['at']),owner_id=r['person'],reference='模拟逐测量对应-'+r['raw']['id'],
        note='逐条对应既有原始测量，不增加样本或整机产量；原检测、批准和发货记录不变。')
    row[r['field']]=r['raw']['id'];new['metrology_uses'].append(row)
uses={r['id']:r for r in new['metrology_uses']}
selected=[r for r in new['metrology_uses'] if r['stage']=='test' and r['instrument_id']==expired['id']]
for i,r in enumerate(selected[:6]):
    key='test:'+r['measurement_id'];sid=r['series'];v=dict(r,id=sid+'-V02',version=2,previous_id=r['id'],registered='2026-09-26T08:00:00')
    if i==0:v['instrument_id']=None;v['note']='模拟新版缺仪器身份，不允许按设备猜仪器。';cases['missing_identity']=key
    if i==1:v['instrument_id']=failed['id'];v['note']='模拟错特性通道，不能用其他项目的校准。';cases['wrong_channel']=key
    if i==2:v['measured']=later(r['measured']);v['note']='模拟测量时间不符，不能挪时间规避到期。';cases['wrong_time']=key
    if i==3:v['status']='撤销';v['note']='模拟使用对应撤销。';cases['withdrawn_usage']=key
    if i==4:
        new['metrology_uses'].append(dict(v,id=sid+'-V02B',note='模拟重复最新版，身份待核。'));cases['duplicate_latest_usage']=key
    if i==5:v['note']='模拟晚登记的同身份完整更正，保留两份依据。';cases['late_corrected_usage']=key
    new['metrology_uses'].append(v)

def notice(iid,sid,start,until,discovered,mode='明确起点',version=1,previous=None,status='已登记',registered=None):
    return dict(id=sid+f'-V{version:02d}',series=sid,version=version,previous_id=previous,status=status,instrument_id=iid,
                calibration_id=None,kind='模拟通道偏离待复核',discovered=discovered,lower_mode=mode,impact_from=start,impact_until=until,
                registered=registered or later(discovered,10),owner_id=owner,reference='模拟失准核查-'+sid,
                note='范围只是待复核候选，不改变原检测或批准。起点未知时仅列已登记资料中的潜在对象。')
new['metrology_notices']=[
    notice(expired['id'],'JL-YX-0001','2026-09-22T12:00:00','2026-09-24T12:00:00','2026-09-24T13:00:00'),
    notice(expired['id'],'JL-YX-0002','2026-09-23T12:00:00','2026-09-25T12:00:00','2026-09-25T13:00:00'),
    notice(failed['id'],'JL-YX-0003','2026-09-21T08:00:00','2026-09-23T08:00:00','2026-09-24T09:00:00'),
    notice(pending['id'],'JL-YX-0004',None,'2026-09-20T18:00:00','2026-09-21T09:00:00',mode='起点未知'),
    notice(conflict['id'],'JL-YX-0005','2026-09-18T08:00:00','2026-09-21T18:00:00','2026-09-22T09:00:00'),
    notice(retired['id'],'JL-YX-0006',None,'2026-09-21T12:00:00','2026-09-22T09:00:00',mode='起点未知'),
]
n=new['metrology_notices'][4]
new['metrology_notices'].append(dict(n,id=n['series']+'-V02',version=2,previous_id=n['id'],impact_until=n['impact_from'],registered='2026-09-26T09:00:00',note='模拟影响范围错误更正，不能显示已无影响。'))
n=new['metrology_notices'][5]
new['metrology_notices'].append(dict(n,id=n['series']+'-V02',version=2,previous_id=n['id'],status='撤销',registered='2026-09-27T09:00:00',note='模拟撤销影响通知，保留过去核查依据。'))
new['metrology_notices'].append(notice(bad['id'],'JL-YX-FUTURE','2026-10-03T08:00:00','2026-10-04T18:00:00','2026-10-05T09:00:00'))

# Current review examples retain exactly the source/context digest and basis versions.
data.update(new);engine=eng.Metrology(data)
affected=[r for r in engine.rows if r['notice_ids'] and r['use_id'] and not r['voided']]
for i,r in enumerate(affected[::max(1,len(affected)//24)][:24],1):
    sid=f'JL-HC-{i:05d}'
    new['metrology_reviews'].append(dict(id=sid+'-V01',series=sid,version=1,previous_id=None,status='已登记',notice_id=r['notice_ids'][0],use_id=r['use_id'],
        calibration_id=r['calibration_id'],source_digest=r['source_digest'],result=['处理中','资料已核对','建议复测'][i%3],registered='2026-09-28T10:00:00',
        owner_id=owner,reference='模拟核查依据-'+sid,note='合成核查登记，不是质量批准、实测复检或客户处置。仅对应引用版本，不关闭其他影响登记。'))
if new['metrology_reviews']:
    new['metrology_reviews'][0]['source_digest']='0'*64;cases['stale_review']=new['metrology_reviews'][0]['id']
data.update(new);engine=eng.Metrology(data)
hist=eng.Metrology(data,cutoff='2026-09-22T18:00:00',known_cutoff='2026-09-22T18:00:00')
restated=eng.Metrology(data,cutoff='2026-09-22T18:00:00',known_cutoff='2026-10-01T18:00:00')
scenario={'schema_version':1,'as_of':'2026-10-01T18:00:00','notice':'全部为合成模拟资料。仪器通道、适用要求、校准历史和逐测量使用显式对应既有终检、来料及工序记录。登记有效不证明真实测量能力或产品合格；失准范围与核查不改变原检测、放行和发货。',
          'schemas':{k:SCHEMAS[k] for k in eng.TABLES},'tables':new}
(ROOT/'data/metrology_scenario.json').write_text(json.dumps(scenario,ensure_ascii=False,indent=2))
report={'tables':{k:len(v) for k,v in new.items()},'rows':sum(map(len,new.values())),
        'summary':eng.summary(engine.rows),'historical_summary':eng.summary(hist.rows),'restated_summary':eng.summary(restated.rows),
        'cases':cases,'source_measurements':len(source_rows),'global_issues':engine.global_issues,'simulation_only':True}
(ROOT/'data/metrology_scenario_build.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
print(json.dumps({k:v for k,v in report.items() if k not in ['cases','global_issues']},ensure_ascii=False))
