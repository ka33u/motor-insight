"""Native localhost reads; never claim browser rendering or downloads."""
import urllib.request,urllib.error,json,hashlib
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
before=sha(ROOT/'data/platform.sqlite3');checks=[]
for path in ['/', '/static/topic_linkage.js','/static/topic_linkage.css','/static/topics.js','/static/topic_snapshots.js','/static/app.js','/api/topics/3/workspace']:
    try:
        with urllib.request.urlopen('http://127.0.0.1:8765'+path,timeout=10) as r:body=r.read();status=r.status
    except urllib.error.HTTPError as ex:status=ex.code;body=ex.read()
    assert status==(401 if path.startswith('/api/') else 200),(path,status)
    if path.startswith('/static/'):assert body==(ROOT/path.lstrip('/')).read_bytes()
    if path=='/':assert b'topic_linkage.js?v=' in body and b'/static/topic_linkage.css?v=' in body
    checks.append(dict(path=path,status=status))
assert sha(ROOT/'data/platform.sqlite3')==before
report=dict(native_http=checks,all_loaded_static_bytes_match=True,main_database_unchanged=True,main_database_sha256=before,browser_rendered_verified=False,mobile_interaction_verified=False,actual_download_verified=False)
(ROOT/'data/topic_linkage_http_validation.json').write_text(json.dumps(report,ensure_ascii=False,indent=2));print(json.dumps(report,ensure_ascii=False,indent=2))
