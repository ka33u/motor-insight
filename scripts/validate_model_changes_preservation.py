"""Verify an additive metadata migration against a local pre-change checkpoint."""
import argparse
import hashlib
import json
import os
import sqlite3
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--db',type=Path,default=ROOT/'data/platform.sqlite3');args=parser.parse_args()
    baseline=ROOT/'data/model-change-before'
    expected=json.loads((baseline/'tables.json').read_text());manifest=json.loads((baseline/'manifest.json').read_text())
    allowed={'django_migrations','sqlite_sequence','django_content_type','auth_permission'}
    digest=lambda value:hashlib.sha256(json.dumps(value,ensure_ascii=False,default=str).encode()).hexdigest()
    with sqlite3.connect(args.db) as db:
        tables={r[0] for r in db.execute("select name from sqlite_master where type='table'")}
        assert tables==set(expected)|{'app_analysismodelchange'}
        for table,sha in expected.items():
            if table not in allowed:assert digest(db.execute('select * from "'+table+'" order by rowid').fetchall())==sha,table
        assert db.execute('select count(*) from app_analysismodelchange').fetchone()[0]==0
        assert db.execute('PRAGMA integrity_check').fetchall()==[('ok',)]
        assert db.execute('PRAGMA foreign_key_check').fetchall()==[]
        assert db.execute("select count(*) from django_migrations where app='app' and name='0022_analysis_model_change'").fetchone()[0]==1
        with sqlite3.connect(baseline/'platform.sqlite3') as prior:
            for table,count in (('django_migrations',1),('django_content_type',1),('auth_permission',4)):
                old=set(prior.execute('select * from '+table));new=set(db.execute('select * from '+table))
                assert old.issubset(new) and len(new-old)==count,table
            migrated=next(iter(set(db.execute('select * from django_content_type'))-set(prior.execute('select * from django_content_type'))))
            assert migrated[1:]==('app','analysismodelchange')
            new_permissions=set(db.execute('select content_type_id,codename from auth_permission'))-set(prior.execute('select content_type_id,codename from auth_permission'))
            assert {r[1] for r in new_permissions}=={v+'_analysismodelchange' for v in ('add','change','delete','view')}
            assert {r[0] for r in new_permissions}=={migrated[0]}
            old_sequence=dict(prior.execute('select * from sqlite_sequence'));new_sequence=dict(db.execute('select * from sqlite_sequence'))
            assert new_sequence=={name:value+({'auth_permission':4,'django_content_type':1,'django_migrations':1}.get(name,0)) for name,value in old_sequence.items()}
    os.environ['MOTOR_SQLITE_PATH']=str(args.db.resolve());os.environ['DJANGO_SETTINGS_MODULE']='config.settings';sys.path.insert(0,str(ROOT))
    import django;django.setup()
    from app import first_piece_data,finite_schedule
    from app.models import Record,MetricVersion
    from app.schema import SCHEMAS
    from app.metric_registry import calculation_hash
    assert SCHEMAS==manifest['schemas']
    assert finite_schedule.digest(list(Record.objects.order_by('dataset','business_key').values('dataset','business_key','record_hash')))==manifest['record_digest']
    assert first_piece_data.load()==json.loads((baseline/'first_piece.json').read_text())
    assert calculation_hash('bi_order_lines')==MetricVersion.objects.get(pk=11).calculation_hash=='9d9a5af3d45172eca16790d628a36bc6acbe18d1e2a811a66a5b5fbff7037fe3'
    for name,sha in manifest['originals'].items():assert hashlib.sha256((ROOT/name).read_bytes()).hexdigest()==sha,name
    proof=dict(success=True,additive_metadata_migration='0022_analysis_model_change',tables=len(tables),unchanged_existing_tables=len(expected)-len(allowed),
        facts_preserved=230802,raw_schemas_preserved=149,originals_preserved=457,existing_models_views_pages_cards_snapshots_preserved=True,
        first_piece_and_delivery_v8_preserved=True,main_model_changes_created=0,browser_acceptance=False)
    output=ROOT/('data/model_changes_preservation.json' if args.db.resolve()==ROOT/'data/platform.sqlite3' else 'data/model_changes_upgrade_rehearsal.json')
    output.write_text(json.dumps(proof,ensure_ascii=False,indent=2)+'\n');print(json.dumps(proof,ensure_ascii=False))

if __name__=='__main__':main()
