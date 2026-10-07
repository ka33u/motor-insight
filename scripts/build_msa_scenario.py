"""Deterministic crossed trials using existing configuration, SN and operators."""
import hashlib,json,os,random,sys
from datetime import datetime,timedelta
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings')
import django;django.setup()
from app.models import Record
from app.schema import SCHEMAS
from app.msa_schema import DATASETS
from app.msa_source_contract import issues
def main():
 before=hashlib.sha256((ROOT/'data/platform.sqlite3').read_bytes()).hexdigest();manifest=json.loads((ROOT/'data/msa-before/manifest.json').read_text());assert before==manifest['database_sha256']
 units=sorted((r.values for r in Record.objects.filter(dataset='units') if r.values['product_id']=='CP.00008.A'),key=lambda r:r['id'])[:10]
 instruments={r.values['parameter']:r.business_key for r in Record.objects.filter(dataset='metrology_instruments') if r.values['equipment_id']=='SB-08-02'}
 operators=['E00009','E00025','E00041'];tables={k:[] for k in DATASETS};profiles=[]
 cases=[('normal','完整交叉采样'),('repeat_noise','重复测量波动'),('operator_offset','操作员均值差异'),('interaction','样件与人员交互'),('missing','交叉单元缺测'),('duplicate','同一轮次重复登记'),('mixed_unit','单位未统一'),('binary','二值旋向项目'),('constant','全体零变异'),('one_operator','单操作员资料'),('expired','校准登记过期')]
 for n,(kind,name) in enumerate(cases,1):
  study_id=f'MSA2609-{n:04d}';start=datetime(2026,9,28,8)+timedelta(hours=(n-1)*3);person_ids=operators[:1] if kind=='one_operator' else operators
  binary=kind=='binary';unit='bool' if binary else 'Ω';parameter='DIR' if binary else 'R';method='SIM-DIR.01' if binary else 'SIM-R-25C.01'
  instrument='JL-YQ-00127' if kind=='expired' else instruments[parameter]
  s=dict(id=study_id,name=name,product_id='CP.00008.A',spec_id=f'JC-CP.00008.A-{parameter}-A',instrument_id=instrument,protocol_version=f'MSAPL-0008-{n:02d}.V1',design='交叉可重复测量（模拟）',model='CROSSED_RANDOM_FULL',measurement_method=method,unit=unit,part_count=10,operator_count=len(person_ids),repeat_count=3,started=start.isoformat(),finished=(start+timedelta(minutes=20)).isoformat(),status='已结束',randomization=f'固定种子{260928+n}随机轮次登记，标签仅用于模拟盲测',owner_id='E00009',conditions='25C附近固定工况，独立合成测量。样件代表性、实际盲测和误差独立性未工厂审定。',purpose='测量系统数据与算法演练',note=name+'；不是实际MSA资格结论，不更改原终检与SPC依据。')
  tables['msa_studies'].append(s);parts=[];people=[]
  for i,u in enumerate(units,1):
   m=dict(id=f'{study_id}-P{i:02d}',study_id=study_id,kind='样件',unit_id=u['id'],operator_id=None,blind_label=f'P{i:02d}',reference=f'SIM-MSA-PART-{n:02d}-{i:02d}',note='同配置SN作为独立合成可重复测量样件，代表性未审定。');parts.append(m);tables['msa_members'].append(m)
  for j,person in enumerate(person_ids,1):
   m=dict(id=f'{study_id}-A{j:02d}',study_id=study_id,kind='操作员',unit_id=None,operator_id=person,blind_label=f'A{j:02d}',reference=f'SIM-MSA-OP-{n:02d}-{j:02d}',note='模拟试验人员身份，实际方法资质与盲测未核实。');people.append(m);tables['msa_members'].append(m)
  trials=[(i,j,k) for i in range(10) for j in range(len(people)) for k in range(1,4)];rng=random.Random(260928+n);rng.shuffle(trials)
  case_rows=[]
  for order,(i,j,k) in enumerate(trials,1):
   at=start+timedelta(seconds=order*10);value=round(.323+(i-4.5)*.0025+rng.gauss(0,.0001 if kind!='repeat_noise' else .003),6)
   if kind=='operator_offset':value=round(value+(j-1)*.004,6)
   if kind=='interaction':value=round(value+(i-4.5)*(j-1)*.001,6)
   if kind=='constant':value=.324
   if binary:value=float(0 if i==4 and j==1 else 1)
   p=dict(id=f'{study_id}-O{order:04d}',study_id=study_id,part_member_id=parts[i]['id'],operator_member_id=people[j]['id'],repeat=k,run_order=order,measured=at.isoformat(),registered=(at+timedelta(seconds=2)).isoformat(),value=value,unit=unit,method_version=method,temperature_c=round(25+rng.uniform(-.1,.1),2),state='有效',reference=f'SIM-MSA-READ-{n:02d}-{order:04d}',note='独立合成测量，不补录旧终检或证明真实仪器性能。')
   if kind=='missing' and i==4 and j==1 and k==2:continue
   if kind=='mixed_unit' and order==44:p['unit']='mΩ';p['value']=round(value*1000,3);p['note']='保留声明单位与原数值，分析不能擅自换算。'
   case_rows.append(p)
  if kind=='duplicate':
   p={**case_rows[0],'id':study_id+'-O0091','run_order':91,'measured':(start+timedelta(seconds=910)).isoformat(),'registered':(start+timedelta(seconds=912)).isoformat(),'reference':f'SIM-MSA-READ-{n:02d}-0091','note':'同一样件人员轮次的独立重复登记，保留并暂停平衡试算。'};case_rows.append(p)
  tables['msa_observations'].extend(case_rows);profiles.append(dict(id=study_id,profile=kind,points=len(case_rows)))
 for ds,rows in tables.items():
  for row in rows:assert not issues(ds,row),(ds,row['id'],issues(ds,row))
 assert {k:len(v) for k,v in tables.items()}==dict(msa_studies=11,msa_members=141,msa_observations=930)
 value=dict(classification='独立合成测量系统试验',seed_base=260928,main_database_sha256=before,tables=tables,schemas={k:SCHEMAS[k] for k in DATASETS},profiles=profiles)
 (ROOT/'data/msa_scenario.json').write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n');assert hashlib.sha256((ROOT/'data/platform.sqlite3').read_bytes()).hexdigest()==before
 print(json.dumps(dict(success=True,studies=11,members=141,observations=930,total_rows=1082,main_database_unchanged=True)))
if __name__=='__main__':main()
