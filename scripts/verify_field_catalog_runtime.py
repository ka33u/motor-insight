"""Native, unauthenticated localhost checks; no browser automation or rendering."""
import hashlib,json,urllib.request,urllib.error
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def verify():
 before=hashlib.sha256((ROOT/'data/platform.sqlite3').read_bytes()).hexdigest();rows=[]
 for path in ['/api/auth','/api/bi-field-catalog','/api/bi-field-catalog/export','/static/app.js','/static/bi_field_catalog.js','/static/bi_field_catalog.css','/']:
  try:
   with urllib.request.urlopen('http://127.0.0.1:8765'+path,timeout=5) as r:data=r.read();status=r.status
  except urllib.error.HTTPError as e:status=e.code;data=e.read()
  assert status==(401 if path.startswith('/api/bi-field-catalog') else 200),(path,status)
  if path.startswith('/static/'):assert data==(ROOT/path.lstrip('/')).read_bytes(),path
  if path=='/':assert b'bi_field_catalog.css' in data
  rows.append(dict(path=path,status=status))
 assert hashlib.sha256((ROOT/'data/platform.sqlite3').read_bytes()).hexdigest()==before
 proof=dict(managed_pid=int((ROOT/'data/server.pid').read_text()),urls=rows,new_routes_loaded=True,current_module_bytes_served=True,main_database_sha256=before,unauthenticated_native_http_smoke_only=True,browser_mobile_model_modal_and_actual_download_accepted=False)
 (ROOT/'data/field_catalog_runtime_validation.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2));print(json.dumps(proof,ensure_ascii=False,indent=2));return proof
if __name__=='__main__':verify()
