"""Native local HTTP bytes plus main read-only API observations; no browser."""
import hashlib,json,os,sys,urllib.request,urllib.error
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def verify():
 before=sha(ROOT/'data/platform.sqlite3');rows=[]
 for path in ['/api/auth','/api/device-intake','/api/device-intake/export','/api/device-intake/rows/OBS-20261001-001-02-0011','/static/app.js','/static/device_intake.js','/static/device_intake.css','/']:
  try:
   with urllib.request.urlopen('http://127.0.0.1:8765'+path,timeout=5) as r:data=r.read();status=r.status
  except urllib.error.HTTPError as e:status=e.code;data=e.read()
  assert status==(401 if path.startswith('/api/device-intake') else 200),(path,status)
  if path.startswith('/static/'):assert data==(ROOT/path.lstrip('/')).read_bytes(),path
  if path=='/':assert b'device_intake.css' in data and b'device_intake.js' in data
  rows.append(dict(path=path,status=status))
 os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings')
 import django;django.setup()
 from django.test import RequestFactory
 from django.contrib.auth.models import User
 from app import device_intake_views as views,bi_field_catalog as fields,import_templates
 from app.models import ImportTemplate
 admin=User.objects.get(username='demo_admin');factory=RequestFactory();request=factory.get('/api/device-intake');request.user=admin;response=views.board(request);assert response.status_code==200;d=json.loads(response.content)
 assert d['total']==106 and d['summary']['sources']==12 and d['can_collect_live'] is False
 field=fields.build(admin,{});assert (len(field['datasets']),field['authorized_fields'])==(121,1184)
 template=import_templates.info(ImportTemplate.objects.get(code='TPL-SIM-DEPTS-001'),admin);assert template['revision']==4 and template['current_version']==2 and next(v for v in template['versions'] if v['number']==2)['can_use']
 assert sha(ROOT/'data/platform.sqlite3')==before
 proof=dict(managed_pid=int((ROOT/'data/server.pid').read_text()),urls=rows,current_module_bytes_served=True,main_native_read_only_board_summary=d['summary'],field_catalog_datasets=121,field_catalog_fields=1184,template_v2_can_use=True,main_database_sha256=before,native_http_and_api_only=True,browser_mobile_and_actual_download_accepted=False,real_equipment_scanned=False)
 (ROOT/'data/device_intake_runtime_validation.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2));print(json.dumps(proof,ensure_ascii=False,indent=2));return proof
if __name__=='__main__':verify()
