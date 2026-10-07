"""Capture the unchanged export phase before additive scheduling contracts."""
import hashlib,json,os,shutil,sqlite3,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
 target=ROOT/'data/finite-schedule-before';assert not target.exists();target.mkdir()
 db=ROOT/'data/platform.sqlite3';assert sha(db)=='9f5c107ff2aff4f2cf76210aaf96b767c228ad77f3cda950e701d9731fc6722c'
 shutil.copy2(db,target/'platform.sqlite3')
 parent=json.loads((ROOT/'data/model-exports-before/manifest.json').read_text())
 physical={n:sha(ROOT/n) for n in parent['physical']};protected={n:sha(ROOT/n) for n in parent['protected']}
 for name in ('app/schema.py','app/manufacturing_rules.py','app/views.py','config/urls.py','static/app.js','templates/index.html','data/bi_design.json','README.md','docs/BUILD_PLAN.md'):
  p=target/name;p.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(ROOT/name,p)
 os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings');sys.path.insert(0,str(ROOT));import django;django.setup()
 from app.schema import SCHEMAS
 from app.metric_registry import calculation_hash
 with sqlite3.connect(db) as c:tables={n:c.execute('SELECT count(*) FROM "'+n+'"').fetchone()[0] for n, in c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name!='sqlite_sequence'").fetchall()}
 value=dict(database_sha256=sha(db),physical=physical,protected=protected,tables=tables,schemas=SCHEMAS,delivery_v8_hash=calculation_hash('bi_order_lines'))
 (target/'manifest.json').write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')
 print(json.dumps(dict(success=True,tables=len(tables),schemas=len(SCHEMAS),physical=len(physical),protected=len(protected))))
if __name__=='__main__':main()
