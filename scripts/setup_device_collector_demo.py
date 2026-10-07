"""Explicit synthetic collector demonstration after verified copy rehearsal."""
import hashlib,json,os,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'scripts'));os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings')
import django;django.setup()
from django.core.management import call_command
from app.models import DeviceCollectionRun
from device_collector_exercise import exercise
if __name__=='__main__':
 marker=ROOT/'data/device_collector_actual.json';assert not marker.exists(),'Never repeat an uncertain actual setup without checking its run and request IDs';assert not DeviceCollectionRun._meta.db_table in __import__('django.db',fromlist=['connection']).connection.introspection.table_names(),'Migration must be performed here after the parent hash check'
 parent=json.loads((ROOT/'data/device-collector-before/manifest.json').read_text());assert hashlib.sha256((ROOT/'data/platform.sqlite3').read_bytes()).hexdigest()==parent['database_sha256'];assert json.loads((ROOT/'data/device_collector_rehearsal.json').read_text())['main_database_unchanged']
 call_command('migrate',verbosity=1);result=exercise(ROOT,export=False);marker.write_text(json.dumps(result,ensure_ascii=False,indent=2));print(json.dumps({k:v for k,v in result.items() if k not in ('run','request_bodies','calls')},ensure_ascii=False,indent=2))
