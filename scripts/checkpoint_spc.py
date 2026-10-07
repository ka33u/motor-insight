"""Freeze the BI-method-workshop parent state before controlled trial data."""
import hashlib
import json
import os
import shutil
import sqlite3
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]


def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()


def main():
    target=ROOT/'data/spc-before';target.mkdir(exist_ok=False)
    source=ROOT/'data/platform.sqlite3'
    assert not Path(str(source)+'-wal').exists()
    digest=sha(source);assert digest=='cc17088ff8da71770975a599da397faee8ae074f6efd85dc83a825f7ea0d4866'
    shutil.copy2(source,target/'platform.sqlite3')
    assert sha(target/'platform.sqlite3')==sha(source)==digest
    previous=json.loads((ROOT/'data/bi-depth-before/manifest.json').read_text())
    runtime={}
    for name in ['app/schema.py','app/manufacturing_rules.py','static/app.js','templates/index.html',
                 'app/views.py','config/urls.py','data/bi_design.json','scripts/refine_bi_catalog.py']:
        p=target/name;p.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(ROOT/name,p);runtime[name]=sha(p)
    sys.path.insert(0,str(ROOT));os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings')
    import django;django.setup()
    from app.schema import SCHEMAS
    from app.metric_registry import calculation_hash
    from app.import_mapping import rules_hash
    from app.models import MetricVersion
    published=MetricVersion.objects.get(pk=11)
    assert published.calculation_hash==calculation_hash(published.metric.dataset)
    with sqlite3.connect((target/'platform.sqlite3').as_uri()+'?mode=ro',uri=True) as conn:
        assert conn.execute('PRAGMA integrity_check').fetchall()==[('ok',)]
        counts={n:conn.execute('SELECT count(*) FROM "'+n+'"').fetchone()[0]
                for n, in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    manifest=dict(database=str(target/'platform.sqlite3'),database_sha256=digest,
                  catalog=json.loads((ROOT/'data/bi_design.json').read_text()),schemas=SCHEMAS,
                  physical=previous['physical'],protected=previous['protected'],runtime=runtime,
                  table_counts=counts,mapping_rules_hash=rules_hash(),
                  delivery_v8_calculation_hash=published.calculation_hash)
    (target/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(dict(success=True,database_sha256=digest,schemas=len(SCHEMAS),
                         physical=len(manifest['physical']),tables=len(counts))))


if __name__=='__main__':main()
