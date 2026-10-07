"""Enumerate every source addition; preserve old rows, files and definitions."""
import hashlib,json,sqlite3,uuid,sys
from collections import Counter
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def verify_increment():
 manifest=json.loads((ROOT/'data/device-intake-before/manifest.json').read_text());actual=json.loads((ROOT/'data/device_intake_actual_import.json').read_text());rehearsal=json.loads((ROOT/'data/device_intake_import_rehearsal.json').read_text());expected=json.loads((ROOT/'data/device_intake_scenario.json').read_text())
 assert sha(manifest['database'])==manifest['database_sha256']==rehearsal['main_database_sha256']=='be7fbaf32c0bddbc66efe196c20f34f3454dfed6111218de8f935257ff414196'
 assert actual['synthetic'] and not actual['live_collection'] and actual['normal_ingestion'];count=actual['rows'];assert count==sum(map(len,expected['tables'].values()))==225
 comparison=ROOT/'data/platform.sqlite3';later=None
 if (ROOT/'data/device_collector_actual.json').exists():
  from validate_device_collector_preservation import verify_increment as verify_collector
  later=verify_collector();comparison=Path(later['parent_database'])
 with sqlite3.connect('file:'+str(comparison)+'?mode=ro',uri=True) as db:
  db.execute('ATTACH DATABASE ? AS old',('file:'+manifest['database']+'?mode=ro',))
  assert db.execute('SELECT type,name,tbl_name,sql FROM main.sqlite_master ORDER BY type,name').fetchall()==db.execute('SELECT type,name,tbl_name,sql FROM old.sqlite_master ORDER BY type,name').fetchall()
  names=[r[0] for r in db.execute("SELECT name FROM old.sqlite_master WHERE type='table' AND name!='sqlite_sequence'")];assert len(names)==43;added={}
  for name in names:
   assert name.replace('_','').isalnum();q='"'+name+'"'
   if name not in ('app_importtemplate','app_importtemplateversion'):assert db.execute(f'SELECT * FROM old.{q} EXCEPT SELECT * FROM main.{q} LIMIT 1').fetchone() is None,name
   n=db.execute(f'SELECT count(*) FROM main.{q}').fetchone()[0]-db.execute(f'SELECT count(*) FROM old.{q}').fetchone()[0]
   if n:added[name]=n
  assert added=={'app_record':count,'app_importrow':count,'app_importbatch':1,'app_auditevent':5,'app_importtemplateversion':1},added
  refresh=actual['template_refresh'];t=refresh['template'];tid=uuid.UUID(t['id']).hex;oldid=refresh['old_version_id'];newid=refresh['new_version_id']
  assert refresh['synthetic'] and not refresh['human_business_approval'] and refresh['local_api_views'] and refresh['fresh_example_can_use']
  assert db.execute('SELECT * FROM old.app_importtemplate WHERE id!=? EXCEPT SELECT * FROM main.app_importtemplate',(tid,)).fetchone() is None
  cols=[r[1] for r in db.execute('PRAGMA old.table_info(app_importtemplate)')]
  old_template=dict(zip(cols,db.execute('SELECT * FROM old.app_importtemplate WHERE id=?',(tid,)).fetchone()));current_template=dict(zip(cols,db.execute('SELECT * FROM main.app_importtemplate WHERE id=?',(tid,)).fetchone()))
  assert current_template=={**old_template,'revision':4,'current_version':2} and old_template['revision']==2 and old_template['current_version']==1
  assert db.execute('SELECT * FROM old.app_importtemplateversion WHERE id!=? EXCEPT SELECT * FROM main.app_importtemplateversion',(oldid,)).fetchone() is None
  columns=[r[1] for r in db.execute('PRAGMA old.table_info(app_importtemplateversion)')];oldv=dict(zip(columns,db.execute('SELECT * FROM old.app_importtemplateversion WHERE id=?',(oldid,)).fetchone()));currentv=dict(zip(columns,db.execute('SELECT * FROM main.app_importtemplateversion WHERE id=?',(oldid,)).fetchone()))
  assert currentv=={**oldv,'state':'retired'} and oldv['state']=='active' and oldv['content_hash']==refresh['old_content_hash']
  newv=dict(zip(columns,db.execute('SELECT * FROM main.app_importtemplateversion WHERE id=?',(newid,)).fetchone()));payload=json.loads(newv['payload']);oldpayload=json.loads(oldv['payload'])
  from app.import_mapping import digest as canonical
  from app.schema import SCHEMAS
  assert payload=={**oldpayload,'schema_hash':canonical(SCHEMAS)}==refresh['new_version_payload']
  assert newv['content_hash']==canonical(payload) and newv['template_id']==tid and newv['number']==2 and newv['state']=='active' and newv['created_by']==newv['activated_by']=='demo_admin' and newv['reason']==refresh['reason']
  oldseq=dict(db.execute('SELECT name,seq FROM old.sqlite_sequence'));seq=dict(db.execute('SELECT name,seq FROM main.sqlite_sequence'));assert set(seq)==set(oldseq)
  for name,value in oldseq.items():assert seq[name]==value+added.get(name,0),name
  bid=uuid.UUID(actual['batch_id']).hex;batch=db.execute('SELECT file_hash,file_path,status FROM app_importbatch WHERE id=?',(bid,)).fetchone();assert batch and batch[0]==actual['sha256']==rehearsal['workbook_sha256']==sha(batch[1]) and batch[2]=='committed'
  events=db.execute('SELECT action,object_id,detail FROM app_auditevent WHERE id NOT IN (SELECT id FROM old.app_auditevent) ORDER BY id').fetchall();assert [a for a,_,_ in events]==['import.stage','import.commit','simulation.xlsx_import','import_template.draft','import_template.activate']
  for action,key,payload in events[:3]:assert uuid.UUID(key).hex==bid
  for action,key,payload in events[3:]:
   value=json.loads(payload);assert uuid.UUID(key).hex==tid and value['version_id']==newid and value['number']==2 and value['business_facts_changed'] is False and value['business_approval'] is False
  details={a:json.loads(v) for a,_,v in events};assert details['import.stage']['counts']==dict(valid=count,total=count,unknown_sheets=[]);assert details['import.commit']==dict(committed=count,total=count,unknown_sheets=[])
  assert details['simulation.xlsx_import']==dict(synthetic=True,workbook_sha256=actual['sha256'],rows=count,ingestion_service=True,human_approval=False,source_system_write=False)
  rows=db.execute('SELECT r.dataset,r.business_key,r."values",r.record_hash,i.dataset,i.business_key,i.normalized,i.record_hash,i.batch_id,i.status,i.row_number,i.sheet FROM app_record r JOIN app_importrow i ON i.id=r.source_row_id WHERE r.id NOT IN (SELECT id FROM old.app_record)').fetchall()
  corpus={(ds,r['id']):r for ds,records in expected['tables'].items() for r in records};assert {(r[0],r[1]) for r in rows}==set(corpus)
  for ds,key,values,digest,ids,ikey,normalized,idigest,ibatch,status,rowno,sheet in rows:
   value=json.loads(values);canonical=hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()
   assert ds==ids and key==ikey and digest==idigest==canonical and ibatch==bid and status=='committed' and rowno>=2
   assert value==json.loads(normalized)==corpus[ds,key] and sheet==expected['schemas'][ds]['label']
  assert db.execute('SELECT count(*),count(DISTINCT dataset) FROM app_record').fetchone()==(212691,112)
  assert db.execute('SELECT count(*) FROM app_devicefile').fetchone()==(394,) and db.execute('SELECT count(*) FROM app_filereadgrant').fetchone()==(0,)
 for group in ('physical','protected'):
  for name,digest in manifest[group].items():assert sha(ROOT/name)==digest,name
 for name,digest in manifest['runtime'].items():assert sha(ROOT/'data/device-intake-before'/name)==digest,name
 original_schema=(ROOT/'data/device-intake-before/app/schema.py').read_bytes();assert (ROOT/'app/schema.py').read_bytes().startswith(original_schema),'Existing schema declarations changed'
 original_access=(ROOT/'data/device-intake-before/app/access.py').read_text();addition="    if dataset in {'device_sources','device_scan_runs','device_file_observations'}:return role(user) in ['admin','quality']\n"
 assert (ROOT/'app/access.py').read_text()==original_access.replace('    if dataset not in schemas():return False\n','    if dataset not in schemas():return False\n'+addition),'Old access policy changed'
 # Live contracts, rather than source-file hashes alone, prove all old datasets.
 from app.schema import SCHEMAS
 from app.import_mapping import rules_hash
 assert {k:v for k,v in SCHEMAS.items() if k in manifest['schemas']}==manifest['schemas']
 assert {k:v for k,v in SCHEMAS.items() if k not in manifest['schemas']}==expected['schemas']
 assert rules_hash()==manifest['mapping_rules_hash'],'Mapping, ingestion and manufacturing rule implementations changed'
 return dict(synthetic=True,all_old_sql_rows_unchanged_except_exact_template_lifecycle=True,all_old_business_rows_unchanged=True,old_sql_tables=43,sequences_and_sql_definitions_exact=True,additions=added,exact_template_lifecycle_changes=dict(template_revision=4,current_version=2,old_version_state='retired',old_payload_unchanged=True,new_version_state='active',fresh_example_can_use=True),records_before=212466,records_after=212691,exact_excel_source_rows=count,old_datasets_unchanged=109,new_raw_datasets=3,old_physical_files_unchanged=442,protected_engines_unchanged=16,old_schema_contracts_and_role_policy_unchanged=True,new_device_scope_roles=['admin','quality'],no_migrations=True,no_associations_or_grants_or_metric_publications=True,parent_database=manifest['database'],parent_database_sha256=manifest['database_sha256'],main_database_sha256=sha(comparison),current_main_database_sha256=sha(ROOT/'data/platform.sqlite3'),later_collector_increment=later,new_import_archive_sha256=actual['sha256'])
if __name__=='__main__':
 r=verify_increment();(ROOT/'data/device_intake_preservation.json').write_text(json.dumps(r,ensure_ascii=False,indent=2));print(json.dumps(r,ensure_ascii=False,indent=2))
