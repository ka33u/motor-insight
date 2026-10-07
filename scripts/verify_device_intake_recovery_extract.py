"""Inspect the current bundle without starting or restoring an application."""
import hashlib,json,sqlite3,tempfile,zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def verify():
 pack=json.loads((ROOT/'data/device_intake_recovery_pack.json').read_text());archive=Path(pack['archive']);before=hashlib.sha256((ROOT/'data/platform.sqlite3').read_bytes()).hexdigest()
 with zipfile.ZipFile(archive) as z,tempfile.TemporaryDirectory(prefix='motor-device-intake-extract-') as temp:
  assert z.testzip() is None
  names=z.namelist();db_name=next(n for n in names if n.endswith('data/platform.sqlite3'))
  file=Path(temp)/'platform.sqlite3';file.write_bytes(z.read(db_name))
  with sqlite3.connect('file:'+str(file)+'?mode=ro',uri=True) as db:
   assert db.execute('PRAGMA integrity_check').fetchone()==('ok',)
   facts=db.execute('SELECT count(*),count(DISTINCT dataset) FROM app_record').fetchone();assert facts==(212691,112)
   assert dict(db.execute("SELECT dataset,count(*) FROM app_record WHERE dataset IN ('device_sources','device_scan_runs','device_file_observations') GROUP BY dataset"))==dict(device_sources=12,device_scan_runs=17,device_file_observations=196)
   counts={table:db.execute('SELECT count(*) FROM '+table).fetchone()[0] for table in ('app_importbatch','app_devicefile','app_topicview','app_topicsnapshot','app_filereadgrant','app_importtemplateuse','app_importtemplateversion','app_auditevent')}
   assert counts==dict(app_importbatch=47,app_devicefile=394,app_topicview=6,app_topicsnapshot=4,app_filereadgrant=0,app_importtemplateuse=0,app_importtemplateversion=2,app_auditevent=764)
   assert db.execute('SELECT revision,current_version FROM app_importtemplate').fetchone()==(4,2)
   assert db.execute('SELECT number,state FROM app_importtemplateversion ORDER BY number').fetchall()==[(1,'retired'),(2,'active')]
  current=['app/device_intake.py','app/device_intake_views.py','app/schema.py','app/access.py','static/app.js','static/device_intake.js','static/device_intake.css','templates/index.html','config/urls.py','docs/设备目录与待采集说明.txt','README.md','docs/BUILD_PLAN.md','data/bi_design.json','outputs/BI需求与呈现方案.html','outputs/BI一页概览.html','outputs/01a0f580-2480-7820-bc97-8ca293421c39/33_设备目录与待采集_模拟.xlsx','tests/test_device_intake.py']
  for path in current:
   name=next(n for n in names if n==path or n.endswith('/'+path));assert z.read(name)==(ROOT/path).read_bytes(),path
 assert hashlib.sha256((ROOT/'data/platform.sqlite3').read_bytes()).hexdigest()==before
 report=dict(readonly_extracted_database_checked=True,records=facts[0],raw_datasets=facts[1],counts=counts,exact_current_runtime_and_guides_included=len(current),main_database_unchanged=True,application_restored_or_browser_tested=False)
 (ROOT/'data/device_intake_recovery_extracted_db_check.json').write_text(json.dumps(report,ensure_ascii=False,indent=2));print(json.dumps(report,ensure_ascii=False,indent=2));return report
if __name__=='__main__':verify()
