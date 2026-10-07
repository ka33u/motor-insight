"""Author explicit synthetic source declarations using existing business IDs."""
import hashlib,json,os,sys
from collections import Counter
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings')
import django;django.setup()
from app.models import Record,DeviceFile
from app.schema import SCHEMAS
def build():
 eq={r.business_key:r.values for r in Record.objects.filter(dataset='equipment')}
 sources=[];scans=[];rows=[]
 definitions=[('SB-08-01','csv'),('SB-08-02','csv'),('SB-08-03','csv'),('SB-06-01','txt'),('SB-06-02','txt'),('SB-06-03','txt'),('SB-04-01','xlsx'),('SB-04-02','xlsx'),('SB-05-01','csv'),('SB-03-01','csv'),('SB-11-01','csv'),('SB-01-01','csv')]
 for i,(equipment,fmt) in enumerate(definitions,1):
  sources.append(dict(id=f'DS-PC-2026-{i:03}',equipment_id=equipment,host_label=f'SIM-PC-{equipment}',directory=f'D:\\SimMotor\\Exports\\{equipment}',format=fmt,scan_interval_hours=24 if i<10 else 48,registered='2026-09-20T08:00:00',owner_id=eq[equipment]['owner_id'],active=i!=12,note='合成目录声明。设备电脑与目录均为模拟别名，没有实际访问设备电脑。'))
 # No scan source 12; source 11 failed, source 10 registered but not executed,
 # source 9 genuinely declared empty, source 8 partial, source 7 stale.
 for i in range(1,12):
  for roundno in range(1,3 if i<=6 else 2):
   start=f'2026-09-{30 if roundno==1 else 31:02}T09:00:00' if roundno==1 else '2026-10-01T09:00:00'
   if i==7:start='2026-09-25T09:00:00'
   status={8:'部分完成',9:'完成',10:'未执行',11:'失败'}.get(i,'完成')
   run=dict(id=f'SCAN-20261001-{i:03}-{roundno:02}',source_id=sources[i-1]['id'],started=start,finished=start[:10]+'T09:20:00' if status=='完成' else None,status=status,reported_count=0 if i>=9 else 18 if i<=3 else 12 if i<=6 else 8,operator_id=eq[sources[i-1]['equipment_id']]['owner_id'],note='合成扫描声明，由模拟 Excel 导入。失败与未执行不代表目录中没有文件。')
   scans.append(run)
   for n in range(1,(run['reported_count'] or 0)+1):
    fmt=sources[i-1]['format'];key=f'OBS-20261001-{i:03}-{roundno:02}-{n:04}';sha=hashlib.sha256(f'{i}/{n}'.encode()).hexdigest();name=f'{sources[i-1]["equipment_id"]}_{n:05}.{fmt}'
    row=dict(id=key,scan_id=run['id'],relative_path=f'{start[:10]}\\{name}',filename=name,size_bytes=1000+i*100+n*37,sha256=sha,modified=start[:10]+'T08:55:00',discovered=start[:10]+'T09:10:00',read_state='可读',format=fmt,session_hint=None,unit_hint=None,note='合成文件发现声明。指纹和字节数为演练值，未归档时不证明存在实际文件。')
    if n==2:row['sha256']=None;row['note']='缺少摘要，不能凭文件名判断同一内容。'
    if n==3:row['read_state']='正在写入';row['note']='模拟仍在写入，等待文件稳定后再采集。'
    if n==4:row['read_state']='无权限'
    if n==5:row['read_state']='损坏'
    if n==6:row['modified']=start[:10]+'T09:15:00';row['note']='模拟时钟或扫描时间错位。'
    if n==7:row['format']='pdf';row['note']='模拟格式声明与文件扩展名不同。'
    if n==8:row['relative_path']='..\\'+name
    if n==9:row['session_hint']='TS-PENDING-2026-000001';row['unit_hint']='M-PENDING-2026-000001'
    if n==10:row['sha256']=hashlib.sha256(f'{i}/1'.encode()).hexdigest();row['size_bytes']=1000+i*100+37;row['note']='模拟同一内容另一个路径，保留两条发现记录，不重复计算唯一内容。'
    rows.append(row)
 # Reuse already archived synthetic byte fingerprints without writing any file.
 originals=list(DeviceFile.objects.order_by('created_at')[:2])+list(DeviceFile.objects.filter(owner__username='demo_quality').order_by('created_at')[:1])+list(DeviceFile.objects.filter(owner__username='demo_admin',kind='txt').order_by('created_at')[:1])
 assert len(originals)==4,'Four existing synthetic originals are required'
 for n,f in enumerate(originals):
  r=next(x for x in rows if x['scan_id']=='SCAN-20261001-001-02' and x['id'].endswith(f'{n+11:04}'))
  r.update(filename=f.filename,relative_path='existing-synthetic-copy\\'+f.filename,size_bytes=f.size,sha256=f.file_hash,format=f.kind,read_state='可读',note='模拟目录发现与已有合成归档相同内容的复制件；不是实际设备采集证明。')
  if f.parsed['mode']=='structured':
   hint=f.parsed['sessions'][0];r['session_hint']=hint;r['unit_hint']=Record.objects.get(dataset='test_sessions',business_key=hint).values['unit_id']
 payload=dict(synthetic=True,live_collection=False,tables={'device_sources':sources,'device_scan_runs':scans,'device_file_observations':rows},schemas={k:SCHEMAS[k] for k in ('device_sources','device_scan_runs','device_file_observations')})
 (ROOT/'data/device_intake_scenario.json').write_text(json.dumps(payload,ensure_ascii=False,indent=2))
 print(json.dumps(dict(synthetic=True,rows={k:len(v) for k,v in payload['tables'].items()},live_collection=False),ensure_ascii=False))
if __name__=='__main__':build()
