"""Freeze current facts, contracts and source files before the additive OEE trial."""
import hashlib,json,os,shutil,sqlite3,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings')
import django;django.setup()
from app.schema import SCHEMAS
def main():
 out=ROOT/'data/oee-before';out.mkdir(exist_ok=False)
 with sqlite3.connect(ROOT/'data/platform.sqlite3') as src,sqlite3.connect(out/'platform.sqlite3') as dst:src.backup(dst)
 prior=json.loads((ROOT/'data/topic-pages-before/manifest.json').read_text());physical={p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in prior['physical']}
 files={}
 for directory in ('app','config','static','templates','scripts'):
  for f in (ROOT/directory).rglob('*'):
   if f.is_file() and '__pycache__' not in f.parts:
    rel=str(f.relative_to(ROOT));files[rel]=hashlib.sha256(f.read_bytes()).hexdigest();target=out/rel;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(f,target)
 for p in ('data/bi_design.json','outputs/BI深化设计_20261007_离线资料包.zip','README.md','docs/BUILD_PLAN.md'):
  target=out/p;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(ROOT/p,target)
 with sqlite3.connect(out/'platform.sqlite3') as db:tables={t[0]:db.execute('SELECT COUNT(*) FROM "'+t[0]+'"').fetchone()[0] for t in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
 value=dict(schemas=SCHEMAS,physical=physical,files=files,tables=tables,database_sha256=hashlib.sha256((out/'platform.sqlite3').read_bytes()).hexdigest())
 (out/'manifest.json').write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n');print(json.dumps(dict(tables=len(tables),schemas=len(SCHEMAS),physical=len(physical),protected=len(files))))
if __name__=='__main__':main()
