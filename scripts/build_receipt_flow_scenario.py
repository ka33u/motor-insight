"""Generate detailed work-window records without rewriting receipt facts."""
import os,sys,json
from datetime import datetime,timedelta
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings')
import django;django.setup()
from app import analytics,supply,receipt_flow
from app.schema import SCHEMAS
raw=analytics.tables();d=supply.SupplyData(raw);headers=[];versions=[];cases={}
warehouse=[e['id'] for e in raw['employees'] if e['department_id']=='D11' and e['active']]
def stamp(t):return t.isoformat(timespec='seconds')
def add(r,idx,stage,source):
 prefix='IQCJ' if stage=='来料检验' else 'PUTJ';jid=f'{prefix}2609-{idx:05d}'
 h=dict(id=jid,receipt_id=r['id'],stage=stage,created=r['received'],reference=f'模拟任务依据-{jid}',note='模拟检验或上架工位窗口，可含设备运行；不作为个人直接工时、正式派工或作业资格批准。');headers.append(h)
 finished=datetime.fromisoformat(source['inspected'] if stage=='来料检验' else source['occurred'])
 if idx%13==0:finished-=timedelta(minutes=5 if stage=='来料检验' else 10)
 minutes=30+(idx%5)*15 if stage=='来料检验' else 20+(idx%3)*10;started=finished-timedelta(minutes=minutes)
 assigned=datetime.fromisoformat(r['received'])+timedelta(minutes=10+idx%3*5) if stage=='来料检验' else finished-timedelta(minutes=55)
 root=dict(id=jid+'-V01',job_id=jid,version=1,previous_id=None,status='模拟确认',assigned=stamp(assigned),started=stamp(started),finished=stamp(finished),inspection_id=source['id'] if stage=='来料检验' else None,movement_id=source['id'] if stage=='入库上架' else None,registered=stamp(finished+timedelta(minutes=10)),owner_id=source['inspector_id'] if stage=='来料检验' else warehouse[(idx-1)%len(warehouse)],station='IQC-A-'+str(idx%8+1) if stage=='来料检验' else source['location'],reference=f'模拟窗口登记-{jid}-01',reason='依据已有模拟检验/入库节点补编作业窗口；原实物节点、数量与状态未改。');versions.append(root);current=root
 def revision(status='模拟确认',future=False):
  nonlocal current
  number=current['version']+1;v=current|dict(id=jid+f'-V{number:02d}',version=number,previous_id=current['id'],status=status,registered='2026-10-02T09:00:00' if future else stamp(finished+timedelta(minutes=20+number)),reference=f'模拟窗口登记-{jid}-{number:02d}',reason='模拟窗口起点更正；结束仍对应原节点，保留首版。')
  v['started']=stamp(datetime.fromisoformat(current['started'])-timedelta(minutes=5));versions.append(v)
  if status=='模拟确认' and not future:current=v
  return v
 if idx%17==0:revision()
 if idx%19==0:revision(future=True)
 elif idx%23==0:revision(status='草稿')
 elif idx%29==0:revision(status='作废')
 if stage=='来料检验' and idx in {2,5,11}:
  v=revision()
  if idx==2:v['started']=stamp(finished+timedelta(minutes=5));cases[jid]='最新窗口开始晚于结束，暂停分解'
  if idx==5:v['inspection_id']=raw['incoming_inspections'][0]['id'];cases[jid]='最新版本引用其他到货检验，暂停分解'
  if idx==11:v['assigned']=None;cases[jid]='最新版本缺派工，不回退旧版'
 if stage=='入库上架' and idx==3:revision()['previous_id']=None;cases[jid]='新版缺前序，不回退首版'
 if stage=='入库上架' and idx==4:
  versions.append(root|{'id':jid+'-V01B'});cases[jid]='同一作业版号重复确认'

for idx,r in enumerate(d.receipts.values(),1):
 if idx%7 and r['latest_inspection']:add(r,idx,'来料检验',r['latest_inspection'])
 if idx%9 and r['approved']:
  for m in r['_moves']:add(r,idx,'入库上架',m)
scenario={'as_of':analytics.AS_OF,'schema_version':'motor-source-v1','notice':'全部合成模拟来料作业窗口，关联现有到货、来料检验与入库流水，不改原实物数量或状态。任务与窗口版本分开；部分任务故意未登记，保留更正、草稿、作废、未来版本及5类异常。窗口可含设备运行，不是个人工时、正式派工、实际排队或SLA。缺失或异常仅暂停历时分解，不抹去原节点。','schemas':{k:SCHEMAS[k] for k in ['receipt_jobs','receipt_job_versions']},'tables':{'receipt_jobs':headers,'receipt_job_versions':versions},'cases':cases}
(ROOT/'data/receipt_flow_scenario.json').write_text(json.dumps(scenario,ensure_ascii=False,indent=2))
engine=receipt_flow.ReceiptFlow(raw|scenario['tables']);summary=receipt_flow.summary(engine.rows);actual={j['id'] for r in engine.rows for j in r['jobs'] if j['issues']};assert actual==set(cases),(actual,cases)
assert (summary['objects'],summary['completed'],summary['disposition'],summary['attention'])==(133,125,8,0)
print(json.dumps({'tables':{k:len(v) for k,v in scenario['tables'].items()},'cases':cases,'summary':summary},ensure_ascii=False,indent=2))
