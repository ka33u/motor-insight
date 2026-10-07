"""Import rehearsed synthetic workbook via ingestion; never replace old facts."""
import os,sys,json,hashlib
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings')
import django;django.setup()
from django.db import transaction
from app.models import Record,AuditEvent,ImportBatch
from app.ingestion import stage_file,commit_batch
from app.metrology import TABLES
file=ROOT/'outputs/01a0f580-2480-7820-bc97-8ca293421c39/30_计量校准_模拟.xlsx'
proof=json.loads((ROOT/'data/metrology_import_rehearsal.json').read_text());checked=json.loads((ROOT/'data/metrology_validation.json').read_text());sha=hashlib.sha256(file.read_bytes()).hexdigest()
assert sha==proof['workbook_sha256'] and proof['isolated_import'] and proof['idempotent'] and proof['all_old_records_unchanged']
assert checked['independent_raw_register'] and checked['manual_edge_cases'] and all(v for v in checked['api'].values())
with transaction.atomic():
    existing=ImportBatch.objects.filter(file_hash=sha).first()
    assert existing or not Record.objects.filter(dataset__in=TABLES).exists(),'拒绝覆盖已有计量台账'
    before=Record.objects.count();batch,repeated=stage_file(file)
    assert batch.summary['valid']==proof['rows'] and not batch.summary.get('invalid') and not batch.summary.get('conflict'),batch.summary
    commit_batch(batch.pk);assert Record.objects.count()==before+(0 if repeated else proof['rows'])
    if not repeated:AuditEvent.objects.create(action='simulation.xlsx_import',actor='local-simulation-builder',object_type='ImportBatch',object_id=str(batch.pk),detail={'synthetic':True,'workbook_sha256':sha,'rows':proof['rows'],'ingestion_service':True,'human_approval':False,'source_system_write':False})
report={'batch_id':str(batch.pk),'repeated':repeated,'sha256':sha,'records_before':before,'records_after':Record.objects.count(),'synthetic':True,'via_ingestion_service':True}
(ROOT/'data/metrology_actual_import.json').write_text(json.dumps(report,ensure_ascii=False,indent=2));print(json.dumps(report,ensure_ascii=False))
