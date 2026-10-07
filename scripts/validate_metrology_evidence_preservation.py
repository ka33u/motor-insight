"""Verify the exact authorized synthetic archive and normal XLSX increments."""
import hashlib
import json
import os
import sqlite3
import sys
import uuid
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def compare_tables(db, prior, expected):
    names = [r[0] for r in db.execute(
        f"SELECT name FROM {prior}.sqlite_master WHERE type='table' AND name!='sqlite_sequence'")]
    assert len(names) == 40
    added = {}
    for name in names:
        assert name.replace('_', '').isalnum()
        q = '"' + name + '"'
        assert db.execute(f'SELECT * FROM {prior}.{q} EXCEPT SELECT * FROM main.{q} LIMIT 1').fetchone() is None, name
        count = db.execute(f'SELECT count(*) FROM main.{q}').fetchone()[0] - db.execute(f'SELECT count(*) FROM {prior}.{q}').fetchone()[0]
        if count:
            added[name] = count
    assert added == expected, added
    old_seq = dict(db.execute(f'SELECT name,seq FROM {prior}.sqlite_sequence'))
    current_seq = dict(db.execute('SELECT name,seq FROM main.sqlite_sequence'))
    assert set(old_seq) == set(current_seq)
    seq_expected = {n.removeprefix('app_'): c for n,c in expected.items()}
    for name, value in old_seq.items():
        assert current_seq[name] == value + seq_expected.get(name.removeprefix('app_'), 0), name
    return names, added


def verify_increment():
    manifest = json.loads((ROOT/'data/metrology-evidence-before/manifest.json').read_text())
    build = json.loads((ROOT/'data/metrology_evidence_scenario_build.json').read_text())
    actual = json.loads((ROOT/'data/metrology_evidence_actual_import.json').read_text())
    archive_db = ROOT/'data/metrology-evidence-import-before/platform.sqlite3'
    source=ROOT/'data/platform.sqlite3';template_increment=None
    if (ROOT/'data/import_templates_actual_setup.json').exists():
        from validate_import_templates_preservation import verify_increment as verify_templates
        template_increment=verify_templates()
        source=Path(template_increment['before_database'])
    db = sqlite3.connect('file:'+str(source)+'?mode=ro', uri=True)
    try:
        db.execute('ATTACH DATABASE ? AS prior', ('file:'+str(archive_db)+'?mode=ro',))
        db.execute('ATTACH DATABASE ? AS original', ('file:'+manifest['database']+'?mode=ro',))
        compare_tables(db, 'prior', {'app_record':524, 'app_importrow':524, 'app_importbatch':1, 'app_auditevent':3})
        names, added = compare_tables(db, 'original', {
            'app_record':524, 'app_importrow':524, 'app_importbatch':1,
            'app_auditevent':262, 'app_devicefile':259})
        archives = {uuid.UUID(x['id']).hex:x for x in build['archives']}
        assert len(archives) == 259
        new_files = db.execute('SELECT id,filename,file_hash,owner_id FROM app_devicefile WHERE id NOT IN (SELECT id FROM original.app_devicefile)').fetchall()
        assert {r[0] for r in new_files} == set(archives)
        for key, filename, digest, owner in new_files:
            expected = archives[key]
            assert filename == expected['filename'] and digest == expected['sha256']
            assert db.execute('SELECT username FROM auth_user WHERE id=?', (owner,)).fetchone()[0] == expected['owner']
            assert sha(ROOT/'data/device_files'/f'{uuid.UUID(key)}.bin') == digest
        archive_events = db.execute('SELECT action,object_id,detail FROM prior.app_auditevent WHERE id NOT IN (SELECT id FROM original.app_auditevent)').fetchall()
        assert Counter(uuid.UUID(r[1]).hex for r in archive_events) == Counter(archives.keys())
        for action, key, details in archive_events:
            details = json.loads(details); expected = archives[uuid.UUID(key).hex]
            assert action == 'device_file.archive' and details['business_facts_changed'] is False
            assert details['sha256'] == expected['sha256'] and details['filename'] == expected['filename']
        bid = uuid.UUID(actual['batch_id']).hex
        batch = db.execute('SELECT file_hash,file_path,status FROM app_importbatch WHERE id=?', (bid,)).fetchone()
        assert batch[0] == actual['sha256'] and sha(batch[1]) == actual['sha256'] and batch[2] == 'committed'
        events = db.execute('SELECT action,object_id,detail FROM app_auditevent WHERE id NOT IN (SELECT id FROM prior.app_auditevent)').fetchall()
        assert Counter(e[0] for e in events) == Counter(['import.stage','import.commit','simulation.xlsx_import'])
        assert all(uuid.UUID(e[1]).hex == bid for e in events)
        details = {e[0]:json.loads(e[2]) for e in events}
        assert details['import.stage']['counts'] == {'valid':524,'total':524,'unknown_sheets':[]}
        assert details['import.commit'] == {'committed':524,'total':524,'unknown_sheets':[]}
        assert details['simulation.xlsx_import'] == dict(synthetic=True, workbook_sha256=actual['sha256'], rows=524, ingestion_service=True, human_approval=False, source_system_write=False)
        records = db.execute('SELECT r.dataset,r.business_key,r."values",r.record_hash,i.dataset,i.business_key,i.normalized,i.record_hash,i.batch_id,i.status,i.row_number,i.sheet FROM app_record r JOIN app_importrow i ON i.id=r.source_row_id WHERE r.id NOT IN (SELECT id FROM prior.app_record)').fetchall()
        assert len(records) == 524
        corpus = json.loads((ROOT/'data/metrology_evidence_scenario.json').read_text())['tables']
        expected = {(ds, str(row['id'])):row for ds,rows in corpus.items() for row in rows}
        assert {(r[0],r[1]) for r in records} == set(expected)
        for ds,key,values,digest,ids,ikey,normalized,idigest,ibatch,status,rowno,sheet in records:
            assert ds == ids and key == ikey and digest == idigest and ibatch == bid and status == 'committed'
            assert json.loads(values) == json.loads(normalized) == expected[(ds,key)]
            assert rowno >= 2 and sheet in {'校准证明台账','校准原件关联'}
        assert db.execute('SELECT count(*) FROM app_record').fetchone()[0] == 212466
        assert db.execute('SELECT count(DISTINCT dataset) FROM app_record').fetchone()[0] == 109
        assert db.execute('SELECT count(*) FROM app_devicefile').fetchone()[0] == 394
        assert db.execute('SELECT count(*) FROM app_filereadgrant').fetchone()[0] == 0
        for name,digest in manifest['files'].items():
            assert sha(ROOT/name) == digest, name
        for name,digest in manifest['protected'].items():
            assert sha(ROOT/name) == digest, name
        return dict(synthetic=True, all_old_sql_rows_unchanged=True, old_sql_tables=len(names), additions=added,
            records_before=211942, records_after=212466, source_datasets=109, new_source_rows=524,
            exact_source_row_links_verified=524, normal_import_batch_id=actual['batch_id'],
            original_archive_count=394, new_originals=259, new_archive_audits=259,
            exact_archive_ids_verified=True, new_original_bytes_verified=True,
            old_physical_files_unchanged=len(manifest['files']), protected_files_unchanged=len(manifest['protected']),
            no_automatic_file_grants=True, database_sha256=template_increment['main_database_sha256'] if template_increment else sha(ROOT/'data/platform.sqlite3'),
            current_main_database_sha256=sha(ROOT/'data/platform.sqlite3'),
            exact_later_template_increment=template_increment)
    finally:
        db.close()


def validate():
    report = verify_increment()
    sys.path.insert(0, str(ROOT));os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings')
    import django;django.setup()
    from django.contrib.auth.models import User
    from app.models import AnalysisModel,MetricVersion
    from app import targets,metric_registry
    from app.analysis_engine import run_analysis
    defaults = json.loads((ROOT/'data/assembly_plans_before.json').read_text())
    admin = User.objects.get(username='demo_admin')
    def projection(value):
        value=json.loads(json.dumps(value,default=str));value.pop('metric_receipt',None)
        for k in ['pivot','scatter']:
            if isinstance(value.get(k),dict):value[k].pop('revision',None)
        return value
    for mid,value in defaults['models'].items():
        model=AnalysisModel.objects.get(pk=mid)
        assert projection(run_analysis(admin,model.dataset,model.definition)) == projection(value), mid
    assert len(defaults['models']) == 52
    assert {r['id']:json.loads(json.dumps(r,default=str)) for r in targets.Targets(admin).rows.values()} == {r['id']:r for r in defaults['targets']}
    metric=MetricVersion.objects.get(status='published',metric__key='DELIVERY_OTIF',version=8)
    assert metric.calculation_hash == metric_registry.calculation_hash(metric.metric.dataset) == '9d9a5af3d45172eca16790d628a36bc6acbe18d1e2a811a66a5b5fbff7037fe3'
    report.update(models_unchanged=52,targets_unchanged=33,published_otif_version=8,published_hash=metric.calculation_hash,new_metric_publication=False)
    (ROOT/'data/metrology_evidence_preservation.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
    print(json.dumps({k:v for k,v in report.items() if k!='additions'},ensure_ascii=False,indent=2))
    return report


if __name__ == '__main__':
    validate()
