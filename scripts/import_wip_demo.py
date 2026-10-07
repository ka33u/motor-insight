"""Add the rehearsed synthetic XLSX via normal ingestion, with no replacement."""
import os,sys,json,hashlib
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings')
import django;django.setup()
from django.db import transaction
from app.models import Record,AuditEvent,ImportBatch
from app.ingestion import stage_file,commit_batch
from app.wip_flow import TABLES
file=ROOT/'outputs/01a0f580-2480-7820-bc97-8ca293421c39/29_在制流转_模拟.xlsx'
proof=json.loads((ROOT/'data/wip_import_rehearsal.json').read_text());digest=hashlib.sha256(file.read_bytes()).hexdigest()
assert digest==proof['workbook_sha256'] and proof['isolated_import'] and proof['idempotent'] and proof['all_old_records_unchanged']
with transaction.atomic():
    existing=ImportBatch.objects.filter(file_hash=digest).first()
    assert existing or not Record.objects.filter(dataset__in=TABLES).exists(),'拒绝覆盖已有在制流转事实'
    before=Record.objects.count();batch,repeated=stage_file(file)
    assert batch.summary['valid']==proof['rows'] and not batch.summary.get('invalid') and not batch.summary.get('conflict'),batch.summary
    commit_batch(batch.pk);assert Record.objects.count()==before+(0 if repeated else proof['rows'])
    if not repeated:AuditEvent.objects.create(action='simulation.xlsx_import',actor='local-simulation-builder',object_type='ImportBatch',object_id=str(batch.pk),detail={'synthetic':True,'workbook_sha256':digest,'rows':proof['rows'],'ingestion_service':True,'human_approval':False,'source_system_write':False})
report={'batch_id':str(batch.pk),'repeated':repeated,'sha256':digest,'records_before':before,'records_after':Record.objects.count(),'synthetic':True,'via_ingestion_service':True}
(ROOT/'data/wip_actual_import.json').write_text(json.dumps(report,ensure_ascii=False,indent=2));print(json.dumps(report,ensure_ascii=False))
