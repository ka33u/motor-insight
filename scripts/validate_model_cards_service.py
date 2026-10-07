"""Read-only public health/assets/auth checks of the owned main preview."""
import hashlib,json,urllib.request,urllib.error
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
 before=sha(ROOT/'data/platform.sqlite3');expected=json.loads((ROOT/'data/model_cards_release.json').read_text());assert before==expected['database_sha256']
 def fetch(path,status=200):
  try:
   with urllib.request.urlopen('http://127.0.0.1:8765'+path,timeout=10) as r:actual=r.status;raw=r.read()
  except urllib.error.HTTPError as e:actual=e.code;raw=e.read()
  assert actual==status,(path,actual);return raw
 assert json.loads(fetch('/api/auth'))['authenticated'] is False
 index=fetch('/').decode();assert 'model_cards.js?v=' in index
 for name in ('model_cards.js','topics.js','app.js','msa.js','spc_workspace.js'):assert fetch('/static/'+name)==(ROOT/'static'/name).read_bytes()
 for path in ('/api/model-cards','/api/model-cards/preview/44','/api/msa','/api/spc-result-snapshots'):fetch(path,401)
 assert sha(ROOT/'data/platform.sqlite3')==before
 proof=dict(success=True,url='http://127.0.0.1:8765/#model-cards',pid=int((ROOT/'data/server.pid').read_text()),assets_exact=True,authentication_required=True,main_database_unchanged=True,database_sha256=before,browser_acceptance=False,mobile_acceptance=False)
 (ROOT/'data/model_cards_main_service.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2)+'\n');print(json.dumps(proof,ensure_ascii=False))
if __name__=='__main__':main()
