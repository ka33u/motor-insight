import hashlib,json,shutil,sqlite3
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def checkpoint():
 out=ROOT/'data/device-transform-before';out.mkdir(exist_ok=True);assert not (out/'manifest.json').exists(),'Never overwrite parent evidence'
 main=ROOT/'data/platform.sqlite3';digest=sha(main);assert digest=='bf695505203f61f6209094c0a59938f70d86968bc0ecd3b14a21628f09a18cc2';shutil.copy2(main,out/'platform.sqlite3');assert sha(out/'platform.sqlite3')==digest==sha(main)
 prior=json.loads((ROOT/'data/device-collector-before/manifest.json').read_text());physical=dict(prior['physical'])
 with sqlite3.connect('file:'+str(main)+'?mode=ro',uri=True) as db:
  for key,file_hash in db.execute('SELECT id,file_hash FROM app_devicefile'):
   import uuid
   name='data/device_files/'+str(uuid.UUID(key))+'.bin';physical[name]=file_hash;assert sha(ROOT/name)==file_hash
 for p in (ROOT/'data/device_inbox').rglob('*'):
  if p.is_file():physical[p.relative_to(ROOT).as_posix()]=sha(p)
 runtime={}
 for name in ('app/models.py','app/schema.py','app/access.py','config/settings.py','app/device_collector.py','app/device_collector_views.py','scripts/recovery.py'):
  dest=out/name;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(ROOT/name,dest);runtime[name]=sha(dest)
 result=dict(database=str(out/'platform.sqlite3'),database_sha256=digest,physical=physical,protected=prior['protected'],runtime=runtime,catalog=json.loads((ROOT/'data/bi_design.json').read_text()))
 (out/'manifest.json').write_text(json.dumps(result,ensure_ascii=False,indent=2));print(json.dumps(dict(database_sha256=digest,old_files=len(physical)),ensure_ascii=False))
if __name__=='__main__':checkpoint()
