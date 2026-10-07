"""Exact zero-write checkpoint and runtime/source invariants for BI linkage."""
import json,hashlib,sqlite3,copy
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def verify():
    m=json.loads((ROOT/'data/topic-linkage-before/manifest.json').read_text());main=ROOT/'data/platform.sqlite3'
    assert sha(main)==m['database_sha256']=='cc17088ff8da71770975a599da397faee8ae074f6efd85dc83a825f7ea0d4866'
    for group in ('physical','protected'):
        for name,digest in m[group].items():assert sha(ROOT/name)==digest,name
    for name,digest in m['runtime'].items():assert sha(ROOT/'data/topic-linkage-before'/name)==digest,name
    with sqlite3.connect('file:'+str(main)+'?mode=ro',uri=True) as db:
        assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
        assert db.execute('SELECT count(*),count(DISTINCT dataset) FROM app_record').fetchone()==(212691,112)
        assert db.execute('SELECT count(*) FROM app_analysismodel').fetchone()[0]==52
        assert db.execute('SELECT count(*) FROM app_topicview').fetchone()[0]==6
        assert db.execute('SELECT count(*) FROM app_topicsnapshot').fetchone()[0]==4
        assert db.execute('SELECT count(*) FROM app_auditevent').fetchone()[0]==780
        assert db.execute("SELECT count(*) FROM sqlite_master WHERE type='table' AND name!='sqlite_sequence'").fetchone()[0]==48
    catalog=json.loads((ROOT/'data/bi_design.json').read_text())
    if 'method_workshop' in catalog['framework']:
        from refine_bi_methods import remove_exact_increment as remove_methods
        remove_methods(catalog)
    from refine_bi_topic_linkage import ROW,remove_exact_increment
    if any(r[0]==ROW[0] for r in catalog['framework']['presentation']):assert remove_exact_increment(copy.deepcopy(catalog))==m['catalog']
    else:assert catalog==m['catalog']
    result=dict(main_database_byte_exact=True,main_database_sha256=sha(main),all_48_sql_tables_and_sequences_unchanged=True,all_original_sources_and_files_unchanged=len(m['physical']),protected_engines_unchanged=16,models_unchanged=52,topic_views_unchanged=6,snapshots_unchanged=4,no_main_audits_or_business_writes=True,catalog_exact_additive_scope=True)
    (ROOT/'data/topic_linkage_preservation.json').write_text(json.dumps(result,ensure_ascii=False,indent=2));return result
if __name__=='__main__':print(json.dumps(verify(),ensure_ascii=False,indent=2))
