"""Freeze resource-only trials before additive staffing assumptions."""
import hashlib,json,os,shutil,sqlite3,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
 target=ROOT/'data/crew-schedule-before';assert not target.exists();target.mkdir()
 phase=json.loads((ROOT/'data/finite_schedule_phase.json').read_text());db=ROOT/'data/platform.sqlite3';assert sha(db)==phase['main_database_sha256'] and phase['restore_verified'];shutil.copy2(db,target/'platform.sqlite3')
 old=json.loads((ROOT/'data/finite-schedule-before/manifest.json').read_text());physical={n:sha(ROOT/n) for n in old['physical']};protected={n:sha(ROOT/n) for n in old['protected']}
 os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings');sys.path.insert(0,str(ROOT));import django;django.setup()
 from app.models import ImportBatch
 from app.schema import SCHEMAS
 from app.metric_registry import calculation_hash
 for b in ImportBatch.objects.all():physical[str(Path(b.file_path).relative_to(ROOT))]=sha(Path(b.file_path))
 n='outputs/01a0f580-2480-7820-bc97-8ca293421c39/36_有限资源试排_模拟.xlsx';physical[n]=sha(ROOT/n)
 for n in ('app/finite_schedule.py','app/finite_schedule_data.py','app/finite_schedule_schema.py','app/finite_schedule_contract.py','app/finite_schedule_views.py','app/model_card_exports.py','app/workforce.py','static/finite_schedule.js','static/finite_schedule.css'):protected[n]=sha(ROOT/n)
 for n in ('app/schema.py','app/manufacturing_rules.py','app/access.py','app/views.py','config/urls.py','static/app.js','templates/index.html','data/bi_design.json','README.md','docs/BUILD_PLAN.md'):
  p=target/n;p.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(ROOT/n,p)
 with sqlite3.connect(db) as c:tables={n:c.execute('SELECT count(*) FROM "'+n+'"').fetchone()[0] for n, in c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name!='sqlite_sequence'").fetchall()}
 manifest=dict(database_sha256=sha(db),physical=physical,protected=protected,tables=tables,schemas=SCHEMAS,delivery_v8_hash=calculation_hash('bi_order_lines'))
 (target/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n');print(json.dumps(dict(success=True,tables=len(tables),schemas=len(SCHEMAS),physical=len(physical),protected=len(protected))))
if __name__=='__main__':main()
