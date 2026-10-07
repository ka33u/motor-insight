"""Read public loopback assets without creating a main-database session."""
import hashlib,json,urllib.request
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
 before=sha(ROOT/'data/platform.sqlite3');base='http://127.0.0.1:8765'
 def fetch(path):
  with urllib.request.urlopen(base+path,timeout=10) as r:return r.read()
 assert 'authenticated' in json.loads(fetch('/api/auth'));index=fetch('/').decode();assert '/static/msa.css?v=' in index
 for name in ('msa.js','msa.css','app.js','catalog_planning.js','spc.js','spc_workspace.js'):assert fetch('/static/'+name)==(ROOT/'static'/name).read_bytes()
 for path in ('/api/msa','/api/msa/MSA2609-0001'):
  try:fetch(path);raise AssertionError('Unauthorized response')
  except urllib.error.HTTPError as e:assert e.code==401
 assert sha(ROOT/'data/platform.sqlite3')==before
 p=dict(success=True,url=base+'/#msa',assets_exact=True,authentication_required=True,main_database_unchanged=True,database_sha256=before,pid=int((ROOT/'data/server.pid').read_text()),browser_acceptance=False)
 (ROOT/'data/msa_main_service.json').write_text(json.dumps(p,ensure_ascii=False,indent=2)+'\n');print(json.dumps(p,ensure_ascii=False))
if __name__=='__main__':main()
