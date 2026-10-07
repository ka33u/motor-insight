"""Generate illustrative characteristic evidence tied to existing IQC records."""
import os,sys,json,random
from pathlib import Path
from datetime import datetime,timedelta
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings')
import django;django.setup()
from app import analytics,supply,incoming_quality as eng
from app.schema import SCHEMAS
raw=analytics.tables();rng=random.Random(20261005);materials=supply.ix(raw['materials']);receipts=supply.ix(raw['receipts']);tables={k:[] for k in eng.NEW_TABLES};cases={}
recheck_index=next(i for i,q in enumerate(raw['incoming_inspections'],1) if q['defect_count']>0)
# All values and ranges below are invented demonstrations, not product standards.
features={'硅钢':[('THK','演示厚度','mm',.5,.02),('WIDTH','演示宽度','mm',500,5)],'铜线':[('DIAM','演示线径','mm',.8,.025),('RES','演示单位长度电阻','Ω/m',.03,.004)],'轴承':[('BORE','演示内径','mm',25,.03),('OUTER','演示外径','mm',52,.04)],'轴':[('DIAM','演示轴径','mm',25,.02),('LEN','演示轴长','mm',230,1)],'壳体':[('BORE','演示配合孔径','mm',100,.08),('LEN','演示壳长','mm',210,1.5)],'漆料':[('VISC','演示黏度','mPa·s',120,12),('SOLID','演示固含量','%',45,3)],'绝缘':[('THK','演示厚度','mm',.25,.02),('WIDTH','演示宽度','mm',50,1)],'铝材':[('HARD','演示硬度','HBW',50,5),('DENS','演示密度','g/cm³',2.7,.05)]}
norm_index={}
for m in raw['materials']:
    for version,start,end in [('IQC-V01','2026-08-01','2026-09-19'),('IQC-V02','2026-09-19',None)]:
        for i,(code,name,unit,center,band) in enumerate(features[m['category']]):
            center=round(center*(1+int(m['id'][-1])*.001),5);band*=.9 if version=='IQC-V02' else 1
            s=dict(id=f'IQCS-{m["id"]}-{code}-{version}',material_id=m['id'],version=version,parameter=code,name=name,unit=unit,lsl=round(center-band,6),usl=round(center+band,6),mandatory=True,effective=start,expires=end,basis='所有限值仅为合成演示输入，不是图纸、国标、采购协议或正式验收值。');tables['incoming_specs'].append(s)
        # Optional numeric characteristic is recorded for only part of the samples.
        s=dict(id=f'IQCS-{m["id"]}-ROUGH-{version}',material_id=m['id'],version=version,parameter='ROUGH',name='演示辅助表面读数',unit='演示单位',lsl=0,usl=5,mandatory=False,effective=start,expires=end,basis='模拟选检特性，仅演练可缺选检项，数值与单位没有生产用途。');tables['incoming_specs'].append(s)
        norm_index[(m['id'],version)]=[s for s in tables['incoming_specs'] if s['material_id']==m['id'] and s['version']==version]
def stamp(x):return x.isoformat(timespec='seconds')
def execution(p,q,idx,tag,offset=0,void=False,future=False,kind=None):
    checked=datetime.fromisoformat(q['inspected'])-timedelta(minutes=15-offset);cid=f'IQCD2609-{idx:05d}-{tag}'
    c=dict(id=cid,plan_id=p['id'],checked=stamp(checked),registered='2026-10-02T09:00:00' if future else stamp(checked+timedelta(minutes=1)),inspector_id=q['inspector_id'],voided=void,reference=f'模拟原始记录-{cid}',reason='补编逐样本模拟数据，原批次结论及处置保持原值；复查另立记录，不覆盖首检。');tables['incoming_checks'].append(c)
    for n in range(1,p['sample_count']+1):
        for s in norm_index[(receipts[q['receipt_id']]['material_id'],p['spec_version'])]:
            if not s['mandatory'] and n%4:continue
            center=(s['lsl']+s['usl'])/2;band=(s['usl']-s['lsl'])/2;value=round(center+band*(rng.uniform(-.6,.6)+(idx%4-1.5)*.025),6)
            if n<=q['defect_count'] and s['mandatory'] and s['parameter']==norm_index[(s['material_id'],s['version'])][0]['parameter'] and kind!='recheck_pass':value=round(s['usl']+band*.2,6)
            v=dict(id=f'{cid}-S{n:02d}-{s["parameter"]}',check_id=cid,sample_no=n,spec_id=s['id'],value=value,unit=s['unit'],instrument=f'模拟采集点-IQC-{idx%6+1:02d}',file_reference=f'模拟特性原件-{cid}.csv')
            if kind=='missing' and n==20 and s['mandatory'] and s['parameter']==norm_index[(s['material_id'],s['version'])][0]['parameter']:continue
            if kind=='unit' and n==1:v['unit']='错单位-演练'
            if kind=='wrong_spec' and n==1:v['spec_id']=tables['incoming_specs'][0]['id']
            if kind=='sample_range' and n==20:v['sample_no']=21
            tables['incoming_readings'].append(v)
            if kind=='duplicate' and n==1:tables['incoming_readings'].append(v|dict(id=v['id']+'-DUP'))
    return c
for idx,q in enumerate(raw['incoming_inspections'],1):
    r=receipts[q['receipt_id']];version='IQC-V01' if q['inspected'][:10]<'2026-09-19' else 'IQC-V02'
    received=datetime.fromisoformat(r['received']);p=dict(id=f'IQCP2609-{idx:05d}',inspection_id=q['id'],spec_version=version,sample_count=q['sample_size'],created=stamp(received+timedelta(minutes=30)),due=stamp(received+timedelta(hours=2)),owner_id=q['inspector_id'],reference=f'模拟计划依据-IQCP2609-{idx:05d}',note='按原抽样20个补编演示特性计划；20个样本不用于推定整批不良数量，范围内不等于批次批准。');tables['incoming_check_plans'].append(p)
    if idx==10:cases[q['id']]='有原检验结论但尚无特性登记';continue
    if idx==12:p['spec_version']='不存在版本';cases[q['id']]='计划规范版本不存在';continue
    execution(p,q,idx,'01',kind='missing' if idx==1 else None)
    if idx==1:cases[q['id']]='首登记有必检漏项'
    if idx==2:execution(p,q,idx,'02',offset=5,kind='unit');cases[q['id']]='最新登记单位错误，不回退首版'
    if idx==3:execution(p,q,idx,'02',offset=5,kind='duplicate');cases[q['id']]='最新登记同样本同特性重复'
    if idx==5:execution(p,q,idx,'02',offset=5,future=True)
    if idx==6:execution(p,q,idx,'02',offset=5,void=True)
    if idx==7:execution(p,q,idx,'02');cases[q['id']]='两个有效登记同刻并列'
    if idx==8:execution(p,q,idx,'02',offset=5,kind='wrong_spec');cases[q['id']]='最新登记引用其他物料或版本规范'
    if idx==9:p['sample_count']=19;cases[q['id']]='计划样本数与原抽样20个不符'
    if idx==11:
        c=execution(p,q,idx,'02',offset=5);tables['incoming_readings']=[v for v in tables['incoming_readings'] if v['check_id']!=c['id']];cases[q['id']]='最新登记没有实测，不能回退'
    if idx==13:execution(p,q,idx,'02',offset=5,kind='sample_range');cases[q['id']]='最新登记有超范围样本序号'
    if idx==recheck_index:execution(p,q,idx,'02',offset=5,kind='recheck_pass');cases[q['id']]='复查范围内，但原不良样本数3保留并列差异'
scenario=dict(as_of=analytics.AS_OF,schema_version='motor-source-v1',notice='全部合成模拟来料特性。每个样本、特性和登记有独立编号，关联原检验、收货、采购及物料。演示限值和采集点不是生产标准或正式仪器资格；保留复查、作废、截止后、漏项、单位/版本/重复/样本序号错误。不改原IQC结论、处置、库存和供应商档案。原文件编号是模拟外部编号，当前归档依据为本Excel原始行。',schemas={k:SCHEMAS[k] for k in eng.NEW_TABLES},tables=tables,cases=cases)
(ROOT/'data/incoming_quality_scenario.json').write_text(json.dumps(scenario,ensure_ascii=False,indent=2))
d=eng.IncomingQuality(raw|tables);s=eng.summary(d.rows)
for key,note in cases.items():
    row=d.index[key];assert row['state'] not in ['pass','out'] or row['disagreement'],(key,note,row['state'])
assert not d.global_issues and s['objects']==133
print(json.dumps(dict(tables={k:len(v) for k,v in tables.items()},summary=s,cases={k:{'case':v,'state':d.index[k]['state'],'latest':d.index[k]['latest_id'],'computed_defects':d.index[k]['latest_defect_count']} for k,v in cases.items()}),ensure_ascii=False,indent=2))
