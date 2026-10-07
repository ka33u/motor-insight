"""Unauthenticated native HTTP checks; does not render or automate a browser."""
import hashlib,json,urllib.request,urllib.error
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def verify():
 before=hashlib.sha256((ROOT/'data/platform.sqlite3').read_bytes()).hexdigest();rows=[]
 paths=['/api/auth','/api/topics/15/summary/export','/api/topics/15/snapshots/00000000-0000-0000-0000-000000000000/summary/export','/static/topics.js','/static/topic_snapshots.js','/static/bi_card_summary.js','/static/bi_card_summary.css','/']
 for path in paths:
  try:
   with urllib.request.urlopen('http://127.0.0.1:8765'+path,timeout=5) as r:data=r.read();status=r.status
  except urllib.error.HTTPError as e:status=e.code;data=e.read()
  assert status==(401 if '/summary/export' in path else 200),(path,status)
  if path.startswith('/static/'):assert data==(ROOT/path.lstrip('/')).read_bytes(),path
  if path=='/':assert b'bi_card_summary.css' in data
  rows.append(dict(path=path,status=status))
 assert hashlib.sha256((ROOT/'data/platform.sqlite3').read_bytes()).hexdigest()==before
 proof=dict(managed_pid=int((ROOT/'data/server.pid').read_text()),urls=rows,new_routes_loaded=True,current_module_bytes_served=True,main_database_sha256=before,unauthenticated_native_http_smoke_only=True,browser_mobile_and_actual_download_accepted=False)
 (ROOT/'data/card_summary_runtime_validation.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2));print(json.dumps(proof,ensure_ascii=False,indent=2));return proof
if __name__=='__main__':verify()
