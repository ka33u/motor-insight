"""Native HTTP and RequestFactory reads; no browser or download acceptance."""
import hashlib,json,os,sys,urllib.request,urllib.error
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings')
import django;django.setup()
from django.contrib.auth.models import User
from app import device_collector as dc,device_intake,bi_field_catalog
from app.models import Record,DeviceFile

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def validate():
 before=sha(ROOT/'data/platform.sqlite3');actual=json.loads((ROOT/'data/device_collector_actual.json').read_text());http=[]
 for path in ('/','/static/app.js','/static/device_collection.js','/static/device_collection.css','/static/device_intake.js','/api/device-collection','/api/device-collection/runs/'+actual['run_id'],'/api/device-collection/runs/'+actual['run_id']+'/export'):
  try:
   with urllib.request.urlopen('http://127.0.0.1:8765'+path,timeout=5) as response:status=response.status;raw=response.read()
  except urllib.error.HTTPError as ex:status=ex.code;raw=ex.read()
  assert status==(401 if path.startswith('/api/') else 200),(path,status)
  if path.startswith('/static/'):assert raw==(ROOT/path.lstrip('/')).read_bytes()
  if path=='/':assert b'/static/device_collection.css?v=' in raw and b'/static/device_collection.js' in raw
  http.append(dict(path=path,status=status))
 admin=User.objects.get(username='demo_admin');board=dc.board(admin);detail=dc.detail(admin,actual['run_id']);assert detail==actual['run'] and board['total_runs']==1 and len(board['sources'])==12
 assert len(device_intake.Workspace(admin).selected())==106 and Record.objects.count()==212691 and DeviceFile.objects.count()==398
 assert sha(ROOT/'data/platform.sqlite3')==before
 report=dict(native_http=http,readonly_current_board_and_receipt=True,source_count=12,private_runs=1,current_summary=detail['summary'],current_original_integrity=all(r['archive']['current_integrity']=='ok' for r in detail['rows']),main_database_sha256=before,main_database_unchanged=True,browser_rendered_verified=False,mobile_interaction_verified=False,actual_download_verified=False)
 (ROOT/'data/device_collector_runtime_validation.json').write_text(json.dumps(report,ensure_ascii=False,indent=2));print(json.dumps(report,ensure_ascii=False,indent=2))
if __name__=='__main__':validate()
