import hashlib,json,os,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'scripts'));os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings')
import django;django.setup()
from django.core.management import call_command
from django.db import connection
from app.models import DeviceTransformTemplate
from device_transform_exercise import exercise
if __name__=='__main__':
 marker=ROOT/'data/device_transform_actual.json';assert not marker.exists(),'Never replay an uncertain setup without checking its native request IDs';assert DeviceTransformTemplate._meta.db_table not in connection.introspection.table_names()
 parent=json.loads((ROOT/'data/device-transform-before/manifest.json').read_text());assert hashlib.sha256((ROOT/'data/platform.sqlite3').read_bytes()).hexdigest()==parent['database_sha256'];assert json.loads((ROOT/'data/device_transform_rehearsal.json').read_text())['main_database_unchanged']
 call_command('migrate',verbosity=1);result=exercise(ROOT,export=False);marker.write_text(json.dumps(result,ensure_ascii=False,indent=2));print(json.dumps({k:v for k,v in result.items() if k not in ('template','receipt','request_bodies','calls')},ensure_ascii=False,indent=2))
