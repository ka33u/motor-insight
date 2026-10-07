import hashlib,json,shutil,sqlite3
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def checkpoint():
 out=ROOT/'data/device-collector-before';out.mkdir(exist_ok=True);assert not (out/'manifest.json').exists(),'Never overwrite parent evidence'
 main=ROOT/'data/platform.sqlite3';digest=sha(main);assert not Path(str(main)+'-wal').exists();shutil.copy2(main,out/'platform.sqlite3');assert sha(main)==sha(out/'platform.sqlite3')==digest
 previous=json.loads((ROOT/'data/device-intake-before/manifest.json').read_text());physical=dict(previous['physical'])
 with sqlite3.connect('file:'+str(main)+'?mode=ro',uri=True) as db:
  for path,digest in db.execute('SELECT file_path,file_hash FROM app_importbatch'):
   p=Path(path);physical[str(p.relative_to(ROOT))]=digest;assert sha(p)==digest
 physical['outputs/01a0f580-2480-7820-bc97-8ca293421c39/33_设备目录与待采集_模拟.xlsx']=sha(ROOT/'outputs/01a0f580-2480-7820-bc97-8ca293421c39/33_设备目录与待采集_模拟.xlsx')
 runtime={}
 for name in ('app/models.py','app/schema.py','app/access.py','config/settings.py'):
  dest=out/name;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(ROOT/name,dest);runtime[name]=sha(dest)
 manifest=dict(database=str(out/'platform.sqlite3'),database_sha256=sha(main),physical=physical,protected=previous['protected'],runtime=runtime,catalog=json.loads((ROOT/'data/bi_design.json').read_text()))
 (out/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2));print(json.dumps(dict(database_sha256=manifest['database_sha256'],old_files=len(physical),protected=len(previous['protected'])),ensure_ascii=False))
if __name__=='__main__':checkpoint()
