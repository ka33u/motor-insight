import hashlib,json,urllib.error,urllib.request
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
 before=sha(ROOT/'data/platform.sqlite3');assert before==json.loads((ROOT/'data/model-results-before/manifest.json').read_text())['database_sha256']
 def fetch(path,status=200):
  try:
   with urllib.request.urlopen('http://127.0.0.1:8765'+path,timeout=10) as r:code=r.status;raw=r.read()
  except urllib.error.HTTPError as e:code=e.code;raw=e.read()
  assert code==status,(path,code);return raw
 assert 'model_card_results.css?v=' in fetch('/').decode()
 for name in ('model_card_results.js','model_card_results.css','model_cards.js','app.js'):assert fetch('/static/'+name)==(ROOT/'static'/name).read_bytes()
 fetch('/api/model-cards/a99a0cba-5385-4e06-9a01-37d545bb3294/evidence',401);assert sha(ROOT/'data/platform.sqlite3')==before
 proof=dict(success=True,url='http://127.0.0.1:8765/#model-cards',pid=int((ROOT/'data/server.pid').read_text()),assets_exact=True,new_evidence_route_auth_required=True,main_database_unchanged=True,database_sha256=before,browser_acceptance=False,mobile_acceptance=False)
 (ROOT/'data/model_results_main_service.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2)+'\n');print(json.dumps(proof,ensure_ascii=False))
if __name__=='__main__':main()
