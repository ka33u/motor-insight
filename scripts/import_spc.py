"""One guarded, standard import of the independently verified synthetic study."""
import hashlib,json,os,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
    db=ROOT/'data/platform.sqlite3';before=ROOT/'data/spc-before/manifest.json';parent=json.loads(before.read_text())
    assert sha(db)==parent['database_sha256']=='cc17088ff8da71770975a599da397faee8ae074f6efd85dc83a825f7ea0d4866'
    assert not os.environ.get('MOTOR_SQLITE_PATH'),'Explicit main-only operation; alternate DB overrides refused'
    assert not (ROOT/'data/spc_main_import.json').exists(),'Existing main receipt retained'
    rehearsal=json.loads((ROOT/'data/spc_rehearsal_validation.json').read_text());http=json.loads((ROOT/'data/spc_http_validation.json').read_text())
    assert rehearsal['success'] and rehearsal['all_fields_roundtrip'] and http['success'] and http['main_database_unchanged']
    tests=(ROOT/'data/spc_full_tests.log').read_text();assert 'Ran 2128 tests' in tests and '\nOK\n' in tests
    path=ROOT/'outputs/01a0f580-2480-7820-bc97-8ca293421c39/34_过程稳定性采样_模拟.xlsx';assert sha(path)==rehearsal['workbook_sha256']
    for name,digest in parent['physical'].items():assert sha(ROOT/name)==digest,name
    sys.path.insert(0,str(ROOT));os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings')
    import django;django.setup()
    from django.db import transaction
    from django.contrib.auth import get_user_model
    from app import access
    from app.models import Record,ImportRow,ImportBatch,AuditEvent
    from app.ingestion import stage_file,commit_batch
    from scripts.refresh_spc_template import refresh
    users=list(get_user_model().objects.all());admin=next(u for u in users if access.role(u)=='admin')
    old=(Record.objects.count(),ImportBatch.objects.count(),ImportRow.objects.count(),AuditEvent.objects.count())
    with transaction.atomic():
        batch,repeated=stage_file(path);assert not repeated and batch.summary==dict(valid=750,total=750,unknown_sheets=[])
        commit_batch(batch.pk);batch.refresh_from_db();assert batch.summary==dict(committed=750,total=750,unknown_sheets=[])
        counts=(Record.objects.count(),ImportBatch.objects.count(),ImportRow.objects.count(),AuditEvent.objects.count())
        again,repeated=stage_file(path);assert repeated and again.pk==batch.pk;commit_batch(again.pk)
        assert counts==(Record.objects.count(),ImportBatch.objects.count(),ImportRow.objects.count(),AuditEvent.objects.count())
        template=refresh(admin,ROOT)
        assert Record.objects.count()==old[0]+750 and ImportBatch.objects.count()==old[1]+1 and ImportRow.objects.count()==old[2]+750
    result=dict(success=True,synthetic=True,normal_import=True,human_business_approval=False,batch_id=str(batch.pk),
                workbook_sha256=sha(path),source_archive=batch.file_path,source_archive_sha256=sha(Path(batch.file_path)),
                added=dict(spc_studies=10,spc_observations=730,spc_events=10),records=Record.objects.count(),
                batches=ImportBatch.objects.count(),rows=ImportRow.objects.count(),audits=AuditEvent.objects.count(),
                replay_unchanged=True,template=template,database_sha256=sha(db))
    (ROOT/'data/spc_main_import.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({k:v for k,v in result.items() if k!='template'},ensure_ascii=False))
if __name__=='__main__':main()
