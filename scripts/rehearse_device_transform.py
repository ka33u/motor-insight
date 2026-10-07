import hashlib,json,os,sqlite3,sys,tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'scripts'))
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def rehearse():
 main=ROOT/'data/platform.sqlite3';before=sha(main)
 with tempfile.TemporaryDirectory(prefix='motor-transform-') as temp:
  target=Path(temp)/'platform.sqlite3'
  with sqlite3.connect('file:'+str(main)+'?mode=ro',uri=True) as source,sqlite3.connect(target) as destination:source.backup(destination)
  os.environ['MOTOR_SQLITE_PATH']=str(target);os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings');import django;django.setup()
  from django.core.management import call_command
  from django.test import override_settings
  from django.db import connection
  from device_transform_exercise import exercise
  call_command('migrate',verbosity=0)
  with override_settings(DEVICE_FILE_ROOT=Path(temp)/'originals'):result=exercise(ROOT,export=True)
  connection.close();assert sha(main)==before;result.update(main_database_sha256=before,main_database_unchanged=True,isolated_migration_and_native_api=True);(ROOT/'data/device_transform_rehearsal.json').write_text(json.dumps(result,ensure_ascii=False,indent=2));print(json.dumps({k:v for k,v in result.items() if k not in ('template','receipt','request_bodies','calls')},ensure_ascii=False,indent=2))
if __name__=='__main__':rehearse()
