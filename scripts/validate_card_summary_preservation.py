"""Require exact preservation of all 43 tables, identities, files and engines."""
import hashlib,json,sqlite3
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
from verification_checkpoint import historical_database
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def verify():
 manifest=json.loads((ROOT/'data/card-summary-before/manifest.json').read_text());main=historical_database(ROOT)
 assert sha(main)==manifest['database_sha256'],'Main database bytes changed'
 with sqlite3.connect('file:'+str(main)+'?mode=ro',uri=True) as db:
  db.execute('ATTACH DATABASE ? AS old',('file:'+manifest['database']+'?mode=ro',))
  tables=[r[0] for r in db.execute("SELECT name FROM main.sqlite_master WHERE type='table'")]
  assert set(tables)=={r[0] for r in db.execute("SELECT name FROM old.sqlite_master WHERE type='table'")};assert len(tables)==44
  for name in tables:
   assert name.replace('_','').isalnum();q='"'+name+'"'
   assert db.execute(f'PRAGMA main.table_info({q})').fetchall()==db.execute(f'PRAGMA old.table_info({q})').fetchall(),name
   assert db.execute(f'SELECT * FROM old.{q} EXCEPT SELECT * FROM main.{q} LIMIT 1').fetchone() is None,name
   assert db.execute(f'SELECT * FROM main.{q} EXCEPT SELECT * FROM old.{q} LIMIT 1').fetchone() is None,name
  assert db.execute('SELECT type,name,tbl_name,sql FROM main.sqlite_master ORDER BY type,name').fetchall()==db.execute('SELECT type,name,tbl_name,sql FROM old.sqlite_master ORDER BY type,name').fetchall()
  facts=db.execute('SELECT count(*),count(DISTINCT dataset) FROM app_record').fetchone();assert facts==(212466,109)
 for group in ('physical','protected'):
  for name,digest in manifest[group].items():assert sha(ROOT/name)==digest,name
 assert len(manifest['physical'])==442 and len(manifest['protected'])==16
 return dict(all_main_sql_tables_unchanged=43,sequences_and_sql_definitions_unchanged=True,main_database_sha256=sha(main),facts=facts[0],datasets=facts[1],physical_files_unchanged=442,protected_engines_unchanged=16,main_snapshots_views_followups_audits_added=0,business_facts_changed=False)
if __name__=='__main__':
 r=verify();(ROOT/'data/card_summary_preservation.json').write_text(json.dumps(r,ensure_ascii=False,indent=2));print(json.dumps(r,ensure_ascii=False,indent=2))
