"""Add only the rehearsed synthetic XLSX through the normal ingestion service.

No source-system write, replacement, deletion, or fabricated human approval.
"""
import os,sys,json,hashlib
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings')
import django;django.setup()
from django.db import transaction
from app.models import Record,AuditEvent,ImportBatch
from app.ingestion import stage_file,commit_batch
from app.incoming_quality import NEW_TABLES
file=ROOT/'outputs/01a0f580-2480-7820-bc97-8ca293421c39/27_来料特性_模拟.xlsx'
proof=json.loads((ROOT/'data/incoming_quality_import_rehearsal.json').read_text())
digest=hashlib.sha256(file.read_bytes()).hexdigest()
assert digest==proof['workbook_sha256'] and proof['isolated_import'] and proof['idempotent']
with transaction.atomic():
    existing=ImportBatch.objects.filter(file_hash=digest).first()
    assert existing or not Record.objects.filter(dataset__in=NEW_TABLES).exists(),'拒绝覆盖已有来料特性数据'
    before=Record.objects.count();batch,repeated=stage_file(file)
    assert batch.summary['valid']==proof['rows'] and not batch.summary.get('invalid') and not batch.summary.get('conflict'),batch.summary
    commit_batch(batch.pk);assert Record.objects.count()==before+(0 if repeated else proof['rows'])
    if not repeated:AuditEvent.objects.create(action='simulation.xlsx_import',actor='local-simulation-builder',object_type='ImportBatch',object_id=str(batch.pk),detail={'synthetic':True,'workbook_sha256':digest,'rows':proof['rows'],'ingestion_service':True,'human_approval':False,'source_system_write':False})
report={'batch_id':str(batch.pk),'repeated':repeated,'sha256':digest,'records_before':before,'records_after':Record.objects.count(),'synthetic':True,'via_ingestion_service':True}
(ROOT/'data/incoming_quality_actual_import.json').write_text(json.dumps(report,ensure_ascii=False,indent=2));print(json.dumps(report,ensure_ascii=False))
