"""Freeze the complete parent state before the additive discovery rehearsal."""
import hashlib,json,os,shutil,sqlite3,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def checkpoint():
 out=ROOT/'data/device-intake-before';out.mkdir(exist_ok=True)
 if (out/'manifest.json').exists():raise ValueError('Parent checkpoint already exists; never overwrite it')
 source=ROOT/'data/platform.sqlite3';target=out/'platform.sqlite3'
 digest=sha(source)
 assert not Path(str(source)+'-wal').exists(),'Checkpoint requires a settled database'
 shutil.copy2(source,target)
 assert sha(target)==sha(source)==digest
 with sqlite3.connect('file:'+str(target)+'?mode=ro',uri=True) as db:assert db.execute('PRAGMA integrity_check').fetchone()==('ok',)
 field=json.loads((ROOT/'data/field-catalog-before/manifest.json').read_text())
 manifest=dict(database=str(target),database_sha256=sha(target),catalog=json.loads((ROOT/'data/bi_design.json').read_text()),physical=field['physical'],protected=field['protected'],runtime={})
 for name in ('app/schema.py','app/access.py'):
  destination=out/name;destination.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(ROOT/name,destination)
  manifest['runtime'][name]=sha(destination)
 sys.path.insert(0,str(ROOT));os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings')
 import django;django.setup()
 from app.schema import SCHEMAS
 from app.import_mapping import rules_hash
 manifest['schemas']=SCHEMAS;manifest['mapping_rules_hash']=rules_hash()
 (out/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2))
 print(json.dumps(dict(database_sha256=manifest['database_sha256'],schemas=len(SCHEMAS),physical=len(manifest['physical']),protected=len(manifest['protected'])),ensure_ascii=False))
if __name__=='__main__':checkpoint()
