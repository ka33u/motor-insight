"""Unauthenticated HTTP service checks; no browser rendering, sessions or facts."""
import hashlib,json,urllib.request,urllib.error
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def verify():
 rows=[]
 for path in ['/api/auth','/api/issue-workspace','/static/issue_workspace.js','/']:
  try:
   with urllib.request.urlopen('http://127.0.0.1:8765'+path,timeout=5) as r:data=r.read();status=r.status
  except urllib.error.HTTPError as e:status=e.code;data=e.read()
  assert status==(401 if path=='/api/issue-workspace' else 200),(path,status)
  if path=='/static/issue_workspace.js':assert data==(ROOT/'static/issue_workspace.js').read_bytes()
  if path=='/':assert b'issue_workspace.css' in data and b'issue_workspace.js' in data
  rows.append({'path':path,'status':status})
 proof={'managed_pid':int((ROOT/'data/server.pid').read_text()),'urls':rows,'new_route_loaded':True,'current_module_bytes_served':True,'main_database_sha256':hashlib.sha256((ROOT/'data/platform.sqlite3').read_bytes()).hexdigest(),'unauthenticated_native_http_smoke_only':True,'browser_mobile_and_download_accepted':False}
 (ROOT/'data/issue_workspace_runtime_validation.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2));print(json.dumps(proof,ensure_ascii=False,indent=2));return proof
if __name__=='__main__':verify()
