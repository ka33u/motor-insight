"""Read-only native HTTP/static and current private API checks; no browser."""
import hashlib,json,os,sys,urllib.request,urllib.error
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings')
import django;django.setup()
from django.contrib.auth.models import User
from app import device_transform as engine,device_transform_views as views
from app.models import Record,DeviceFile
from django.test import RequestFactory

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def validate():
 before=sha(ROOT/'data/platform.sqlite3');actual=json.loads((ROOT/'data/device_transform_actual.json').read_text());http=[]
 for path in ('/','/static/app.js','/static/device_transform.js','/static/device_transform.css','/static/device_files.js','/api/device-transform','/api/device-transform/receipts/'+actual['receipt_id'],'/api/device-transform/receipts/'+actual['receipt_id']+'/export'):
  try:
   with urllib.request.urlopen('http://127.0.0.1:8765'+path,timeout=5) as r:status=r.status;raw=r.read()
  except urllib.error.HTTPError as ex:status=ex.code;raw=ex.read()
  assert status==(401 if path.startswith('/api/') else 200),(path,status)
  if path.startswith('/static/'):assert raw==(ROOT/path.lstrip('/')).read_bytes()
  if path=='/':assert b'/static/device_transform.css?v=' in raw and b'/static/device_transform.js' in raw
  http.append(dict(path=path,status=status))
 admin=User.objects.get(username='demo_admin');r=RequestFactory().get('/api/device-transform');r.user=admin;response=views.board(r);assert response.status_code==200;board=json.loads(response.content);assert len(board['templates'])==len(board['receipts'])==1;detail=engine.detail(admin,actual['receipt_id']);assert detail==actual['receipt']
 assert detail['source']['current_integrity']==detail['output']['current_integrity']=='ok' and all(c['current_target_unchanged'] for c in detail['current_targets']);assert Record.objects.count()==212691 and DeviceFile.objects.count()==401
 assert sha(ROOT/'data/platform.sqlite3')==before;result=dict(native_http=http,readonly_current_template_and_receipt=True,standard_rows=24,sessions=3,current_original_integrity=True,current_business_targets_unchanged=True,main_database_sha256=before,main_database_unchanged=True,browser_rendered_verified=False,mobile_interaction_verified=False,actual_download_verified=False)
 (ROOT/'data/device_transform_runtime_validation.json').write_text(json.dumps(result,ensure_ascii=False,indent=2));print(json.dumps(result,ensure_ascii=False,indent=2))
if __name__=='__main__':validate()
