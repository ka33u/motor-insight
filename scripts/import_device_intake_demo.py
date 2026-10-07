"""Normal guarded ingestion of the rehearsed synthetic discovery declaration."""
import hashlib,json,os,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings')
import django;django.setup()
from django.db import transaction
from app import device_intake as eng
from app.models import Record,AuditEvent,ImportBatch
from app.ingestion import stage_file,commit_batch
from refresh_device_intake_template import refresh
from django.contrib.auth.models import User
def ingest():
 source=ROOT/'data/platform.sqlite3';proof=json.loads((ROOT/'data/device_intake_import_rehearsal.json').read_text());before=json.loads((ROOT/'data/device-intake-before/manifest.json').read_text())
 file=ROOT/'outputs/01a0f580-2480-7820-bc97-8ca293421c39/33_设备目录与待采集_模拟.xlsx';digest=hashlib.sha256(file.read_bytes()).hexdigest()
 assert not (ROOT/'data/device_intake_actual_import.json').exists(),'Already imported; do not overwrite original proof'
 assert hashlib.sha256(source.read_bytes()).hexdigest()==proof['main_database_sha256']==before['database_sha256']
 assert proof['native_stage_commit_and_replay'] and proof['all_old_records_unchanged'] and proof['all_page_and_csv_keys_match'] and proof['no_associations_or_grants_added']
 assert digest==proof['workbook_sha256'] and not Record.objects.filter(dataset__in=eng.DATASETS).exists()
 with transaction.atomic():
  batch,repeated=stage_file(file);assert not repeated and batch.summary==dict(valid=proof['rows'],total=proof['rows'],unknown_sheets=[])
  commit_batch(batch.pk);assert Record.objects.count()==212466+proof['rows']
  AuditEvent.objects.create(action='simulation.xlsx_import',actor='local-simulation-builder',object_type='ImportBatch',object_id=str(batch.pk),detail=dict(synthetic=True,workbook_sha256=digest,rows=proof['rows'],ingestion_service=True,human_approval=False,source_system_write=False))
  assert proof['existing_template_native_v2_refresh']['fresh_example_can_use']
  refreshed=refresh(User.objects.get(username='demo_admin'),ROOT)
 report=dict(batch_id=str(batch.pk),sha256=digest,records_before=212466,records_after=Record.objects.count(),rows=proof['rows'],tables=proof['tables'],synthetic=True,live_collection=False,normal_ingestion=True,new_originals=0,new_grants=0,new_associations=0,template_refresh=refreshed)
 (ROOT/'data/device_intake_actual_import.json').write_text(json.dumps(report,ensure_ascii=False,indent=2));print(json.dumps(report,ensure_ascii=False,indent=2))
if __name__=='__main__':ingest()
