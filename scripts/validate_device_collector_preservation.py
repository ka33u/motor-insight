"""Enumerate exact collector receipts and migration additions against immutable fd5 parent."""
import hashlib,json,sqlite3,sys,uuid
from collections import Counter
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def verify_increment():
 import os,django
 from django.apps import apps
 if not apps.ready:os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings');django.setup()
 from app import device_collector as engine,device_files as files
 from app.models import DeviceCollectionRun,DeviceCollectionEvent,DeviceFile
 manifest=json.loads((ROOT/'data/device-collector-before/manifest.json').read_text());actual=json.loads((ROOT/'data/device_collector_actual.json').read_text());rehearsal=json.loads((ROOT/'data/device_collector_rehearsal.json').read_text())
 assert sha(manifest['database'])==manifest['database_sha256']==rehearsal['main_database_sha256']=='fd5c35d3d28ce675e24bcafee69db00822507924dd46fd4ff66b24da73041cfc'
 assert actual['synthetic'] and actual['local_simulation'] and actual['native_api_views'] and not actual['real_device_pc_connected'] and not actual['associations_or_grants_added'] and actual['repeat_requests_no_extra_writes'] and actual['audit_increment']==10
 old_names=set();added={};main=ROOT/'data/platform.sqlite3';comparison=main;later=None
 if (ROOT/'data/device_transform_actual.json').exists():
  from validate_device_transform_preservation import verify_increment as verify_transform
  later=verify_transform();comparison=Path(later['parent_database'])
 with sqlite3.connect('file:'+str(comparison)+'?mode=ro',uri=True) as db:
  assert db.execute('PRAGMA integrity_check').fetchall()==[('ok',)] and db.execute('PRAGMA foreign_key_check').fetchone() is None
  db.execute('ATTACH DATABASE ? AS old',('file:'+manifest['database']+'?mode=ro',));old_schema=db.execute('SELECT type,name,tbl_name,sql FROM old.sqlite_master ORDER BY type,name').fetchall();new_schema=db.execute('SELECT type,name,tbl_name,sql FROM main.sqlite_master ORDER BY type,name').fetchall();assert set(old_schema)<=set(new_schema),'An old SQL definition changed'
  assert all(row[2] in {'app_devicecollectionrun','app_devicecollectionevent'} for row in set(new_schema)-set(old_schema))
  old_names={r[0] for r in db.execute("SELECT name FROM old.sqlite_master WHERE type='table' AND name!='sqlite_sequence'")};names={r[0] for r in db.execute("SELECT name FROM main.sqlite_master WHERE type='table' AND name!='sqlite_sequence'")};assert len(old_names)==43 and names-old_names=={'app_devicecollectionrun','app_devicecollectionevent'} and len(names)==45
  for name in old_names:
   assert name.replace('_','').isalnum();q='"'+name+'"';assert db.execute(f'SELECT * FROM old.{q} EXCEPT SELECT * FROM main.{q} LIMIT 1').fetchone() is None,name
   n=db.execute(f'SELECT count(*) FROM main.{q}').fetchone()[0]-db.execute(f'SELECT count(*) FROM old.{q}').fetchone()[0]
   if n:added[name]=n
  assert added==dict(app_devicefile=4,app_auditevent=10,auth_permission=8,django_content_type=2,django_migrations=1),added
  perms=db.execute('SELECT p.codename,c.app_label,c.model FROM auth_permission p JOIN django_content_type c ON c.id=p.content_type_id WHERE p.id NOT IN (SELECT id FROM old.auth_permission)').fetchall();assert set(perms)=={(verb+'_'+model,'app',model) for model in ('devicecollectionrun','devicecollectionevent') for verb in ('add','change','delete','view')}
  assert set(db.execute('SELECT app_label,model FROM django_content_type WHERE id NOT IN (SELECT id FROM old.django_content_type)').fetchall())=={('app','devicecollectionevent'),('app','devicecollectionrun')}
  assert db.execute('SELECT app,name FROM django_migrations WHERE id NOT IN (SELECT id FROM old.django_migrations)').fetchall()==[('app','0017_device_collection_receipts')]
  oldseq=dict(db.execute('SELECT name,seq FROM old.sqlite_sequence'));seq=dict(db.execute('SELECT name,seq FROM main.sqlite_sequence'));assert set(seq)-set(oldseq)=={'app_devicecollectionevent'} and seq['app_devicecollectionevent']==5
  for name,value in oldseq.items():assert seq[name]==value+added.get(name,0),name
  newids={uuid.UUID(r['id']).hex for r in actual['new_private_originals']};assert {r[0] for r in db.execute('SELECT id FROM app_devicefile WHERE id NOT IN (SELECT id FROM old.app_devicefile)')}==newids
  audits=db.execute('SELECT action,actor,object_id,detail FROM app_auditevent WHERE id NOT IN (SELECT id FROM old.app_auditevent) ORDER BY id').fetchall();assert Counter(r[0] for r in audits)==Counter({'device_collection.create':1,'device_collection.attempt':5,'device_file.archive':4})
  event_details={r['item_key']:r for r in actual['run']['history']};assert len(event_details)==5
  for action,actor,key,payload in audits:
   value=json.loads(payload);assert actor=='demo_admin' and value['business_facts_changed'] is False
   if action=='device_file.archive':assert uuid.UUID(key).hex in newids
   elif action=='device_collection.create':assert key==actual['run_id'] and value['manifest_hash']==actual['run']['manifest_hash'] and value['items']==5 and value['local_simulation']
   else:
    assert key==actual['run_id'] and value['local_simulation'];p=event_details[value['item_key']];assert value['version']==p['version']==1 and value['state']==p['state'] and value['file_id']==p['file_id'] and value['payload_hash']==engine.digest(p)
  assert db.execute('SELECT count(*),count(DISTINCT dataset) FROM app_record').fetchone()==(212691,112)
  assert db.execute('SELECT count(*) FROM app_filereadgrant').fetchone()==(0,) and db.execute('SELECT count(*) FROM app_devicefile').fetchone()==(398,)
 for group in ('physical','protected'):
  for name,digest in manifest[group].items():assert sha(ROOT/name)==digest,name
 for name,digest in manifest['runtime'].items():assert sha(ROOT/'data/device-collector-before'/name)==digest,name
 for name in ('app/schema.py','app/access.py'):assert sha(ROOT/name)==manifest['runtime'][name],name
 assert (ROOT/'app/models.py').read_bytes().startswith((ROOT/'data/device-collector-before/app/models.py').read_bytes())
 assert (ROOT/'config/settings.py').read_bytes().startswith((ROOT/'data/device-collector-before/config/settings.py').read_bytes())
 from django.contrib.auth.models import User
 admin=User.objects.get(username='demo_admin');d=engine.detail(admin,actual['run_id']);assert d==actual['run'],'Run receipt or current archive changed';assert DeviceCollectionRun.objects.count()==1 and DeviceCollectionEvent.objects.count()==5
 for item in actual['new_private_originals']:
  f=files.get(admin,item['id']);assert files.info(f)['filename']==item['filename'] and f.metadata_hash==item['metadata_hash'] and f.file_hash==item['sha256'] and f.size==item['size'];assert sha(files.path(f))==item['sha256']
 fixture=json.loads((ROOT/'data/device_inbox/fixture_manifest.json').read_text());assert fixture['synthetic'] and fixture['business_facts_changed'] is False
 for item in fixture['files']:assert sha(ROOT/'data/device_inbox'/item['path'])==item['sha256']
 assert {r['sha256'] for r in actual['new_private_originals']}=={r['item']['sha256'] for r in actual['run']['rows']}
 return dict(synthetic=True,parent_database=manifest['database'],parent_database_sha256=manifest['database_sha256'],current_main_database_sha256=sha(main),verification_database=str(comparison),later_transform_increment=later,all_old_sql_rows_unchanged=True,old_sql_tables=43,new_operational_tables=2,exact_old_table_additions=added,collection_runs=1,collection_events=5,new_private_originals=4,old_physical_files_unchanged=len(manifest['physical']),protected_engines_unchanged=16,old_schema_and_access_exact=True,old_business_facts_unchanged=True,no_associations_or_grants_or_metric_publications=True,migration='0017_device_collection_receipts',current_receipts_and_originals_verified=True)
if __name__=='__main__':
 import os;os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings');import django;django.setup()
 result=verify_increment();(ROOT/'data/device_collector_preservation.json').write_text(json.dumps(result,ensure_ascii=False,indent=2));print(json.dumps(result,ensure_ascii=False,indent=2))
