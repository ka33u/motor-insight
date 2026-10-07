"""Guarded normal ingestion of the rehearsed synthetic certificate workbook."""
import os,sys,json,hashlib,sqlite3
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings')
import django;django.setup()
from django.db import transaction
from app.models import Record,AuditEvent,ImportBatch,FileReadGrant
from app.ingestion import stage_file,commit_batch
from app.metrology_evidence import TABLES
file=ROOT/'outputs/01a0f580-2480-7820-bc97-8ca293421c39/31_计量原件_模拟.xlsx'
proof=json.loads((ROOT/'data/metrology_evidence_import_rehearsal.json').read_text());checked=json.loads((ROOT/'data/metrology_evidence_validation.json').read_text());digest=hashlib.sha256(file.read_bytes()).hexdigest()
assert digest==proof['workbook_sha256'] and proof['isolated_import'] and proof['idempotent'] and proof['all_old_records_unchanged']
assert checked['independent_raw_certificate_and_instrument_queue'] and checked['manual_edge_cases']==13 and all(checked['api'].values())
backup=ROOT/'data/metrology-evidence-import-before';backup.mkdir(exist_ok=True)
if not (backup/'platform.sqlite3').exists():
    with sqlite3.connect(ROOT/'data/platform.sqlite3') as source,sqlite3.connect(backup/'platform.sqlite3') as target:source.backup(target)
with transaction.atomic():
    existing=ImportBatch.objects.filter(file_hash=digest).first()
    assert existing or not Record.objects.filter(dataset__in=TABLES).exists(),'拒绝覆盖已有校准证明来源'
    before=Record.objects.count();grants=FileReadGrant.objects.count();batch,repeated=stage_file(file)
    assert batch.summary['valid']==proof['rows'] and not batch.summary.get('invalid') and not batch.summary.get('conflict'),batch.summary
    commit_batch(batch.pk);assert Record.objects.count()==before+(0 if repeated else proof['rows'])
    assert FileReadGrant.objects.count()==grants
    if not repeated:AuditEvent.objects.create(action='simulation.xlsx_import',actor='local-simulation-builder',object_type='ImportBatch',object_id=str(batch.pk),detail={'synthetic':True,'workbook_sha256':digest,'rows':proof['rows'],'ingestion_service':True,'human_approval':False,'source_system_write':False})
report={'batch_id':str(batch.pk),'repeated':repeated,'sha256':digest,'records_before':before,'records_after':Record.objects.count(),'synthetic':True,'via_ingestion_service':True,'no_automatic_file_grants':True}
(ROOT/'data/metrology_evidence_actual_import.json').write_text(json.dumps(report,ensure_ascii=False,indent=2));print(json.dumps(report,ensure_ascii=False))
