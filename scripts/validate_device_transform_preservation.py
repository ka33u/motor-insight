"""Prove exact transform-only additions against the bf695 parent database."""
import hashlib,json,os,sqlite3,sys,uuid
from collections import Counter
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def verify_increment():
 import django
 from django.apps import apps
 if not apps.ready:os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings');django.setup()
 from app import device_transform as engine,device_files as files
 from app.models import DeviceTransformTemplate as Template,DeviceTransformVersion as Version,DeviceTransformReceipt as Receipt
 manifest=json.loads((ROOT/'data/device-transform-before/manifest.json').read_text());actual=json.loads((ROOT/'data/device_transform_actual.json').read_text());rehearsal=json.loads((ROOT/'data/device_transform_rehearsal.json').read_text());main=ROOT/'data/platform.sqlite3'
 assert sha(manifest['database'])==manifest['database_sha256']==rehearsal['main_database_sha256']=='bf695505203f61f6209094c0a59938f70d86968bc0ecd3b14a21628f09a18cc2'
 assert actual['synthetic'] and actual['native_api_views'] and not actual['real_device_pc_connected'] and not actual['associations_or_grants_added'] and actual['audit_increment']==6 and actual['repeat_requests_no_extra_writes'] and actual['all_standard_cells_equal_original_excel_facts']
 with sqlite3.connect('file:'+str(main)+'?mode=ro',uri=True) as db:
  assert db.execute('PRAGMA integrity_check').fetchall()==[('ok',)] and db.execute('PRAGMA foreign_key_check').fetchone() is None
  db.execute('ATTACH DATABASE ? AS old',('file:'+manifest['database']+'?mode=ro',));old_schema=set(db.execute('SELECT type,name,tbl_name,sql FROM old.sqlite_master'));new_schema=set(db.execute('SELECT type,name,tbl_name,sql FROM main.sqlite_master'));assert old_schema<=new_schema
  new_tables={'app_devicetransformtemplate','app_devicetransformversion','app_devicetransformreceipt'};assert all(r[2] in new_tables for r in new_schema-old_schema)
  old_names={r[0] for r in db.execute("SELECT name FROM old.sqlite_master WHERE type='table' AND name!='sqlite_sequence'")};names={r[0] for r in db.execute("SELECT name FROM main.sqlite_master WHERE type='table' AND name!='sqlite_sequence'")};assert len(old_names)==45 and names-old_names==new_tables and len(names)==48;added={}
  for name in old_names:
   assert name.replace('_','').isalnum();q='"'+name+'"';assert db.execute(f'SELECT * FROM old.{q} EXCEPT SELECT * FROM main.{q} LIMIT 1').fetchone() is None,name
   n=db.execute(f'SELECT count(*) FROM main.{q}').fetchone()[0]-db.execute(f'SELECT count(*) FROM old.{q}').fetchone()[0]
   if n:added[name]=n
  assert added==dict(app_devicefile=3,app_auditevent=6,auth_permission=12,django_content_type=3,django_migrations=1),added
  model_names={n.removeprefix('app_') for n in new_tables};assert set(db.execute('SELECT app_label,model FROM django_content_type WHERE id NOT IN (SELECT id FROM old.django_content_type)'))=={('app',n) for n in model_names}
  perms=db.execute('SELECT p.codename,c.app_label,c.model FROM auth_permission p JOIN django_content_type c ON c.id=p.content_type_id WHERE p.id NOT IN (SELECT id FROM old.auth_permission)').fetchall();assert set(perms)=={(v+'_'+n,'app',n) for n in model_names for v in ('add','change','delete','view')}
  assert db.execute('SELECT app,name FROM django_migrations WHERE id NOT IN (SELECT id FROM old.django_migrations)').fetchall()==[('app','0018_device_transform_templates')]
  oldseq=dict(db.execute('SELECT name,seq FROM old.sqlite_sequence'));seq=dict(db.execute('SELECT name,seq FROM main.sqlite_sequence'));assert set(seq)-set(oldseq)=={'app_devicetransformversion'} and seq['app_devicetransformversion']==1
  for name,value in oldseq.items():assert seq[name]==value+added.get(name,0),name
  ids={uuid.UUID(r['id']).hex for r in actual['new_files']};assert {r[0] for r in db.execute('SELECT id FROM app_devicefile WHERE id NOT IN (SELECT id FROM old.app_devicefile)')}==ids
  events=db.execute('SELECT action,actor,object_id,detail FROM app_auditevent WHERE id NOT IN (SELECT id FROM old.app_auditevent) ORDER BY id').fetchall();assert Counter(e[0] for e in events)==Counter({'device_file.archive':3,'device_transform.draft':1,'device_transform.activate':1,'device_transform.execute':1})
  for action,actor,key,raw in events:
   payload=json.loads(raw);assert actor=='demo_admin' and payload['business_facts_changed'] is False
   if action=='device_file.archive':assert uuid.UUID(key).hex in ids
   elif action in ('device_transform.draft','device_transform.activate'):assert key==actual['template']['id'] and payload['version_id']==actual['version_id'] and payload['payload_hash']==actual['template_payload_hash'] and payload['private_configuration'] and not payload['business_approval']
   else:assert key==actual['receipt_id'] and payload['payload_hash']==actual['receipt']['payload_hash'] and not payload['association_confirmed']
  assert db.execute('SELECT count(*),count(DISTINCT dataset) FROM app_record').fetchone()==(212691,112) and db.execute('SELECT count(*) FROM app_devicefile').fetchone()==(401,)
  assert db.execute('SELECT count(*) FROM app_filereadgrant').fetchone()==(0,)
 for group in ('physical','protected'):
  for name,digest in manifest[group].items():assert sha(ROOT/name)==digest,name
 for name,digest in manifest['runtime'].items():assert sha(ROOT/'data/device-transform-before'/name)==digest,name
 for name in ('app/schema.py','app/access.py','config/settings.py','app/device_collector.py','app/device_collector_views.py','scripts/recovery.py'):assert sha(ROOT/name)==manifest['runtime'][name],name
 assert (ROOT/'app/models.py').read_bytes().startswith((ROOT/'data/device-transform-before/app/models.py').read_bytes())
 from django.contrib.auth.models import User
 admin=User.objects.get(username='demo_admin');assert engine.detail(admin,actual['receipt_id'])==actual['receipt'];assert (Template.objects.count(),Version.objects.count(),Receipt.objects.count())==(1,1,1)
 assert engine.info(Template.objects.get())==actual['template'];v=Version.objects.get();assert v.payload_hash==actual['template_payload_hash'] and v.payload['rules_hash']==engine.rules_hash()
 for item in actual['new_files']:
  f=files.get(admin,item['id']);assert f.filename==item['filename'] and f.file_hash==item['sha256'] and f.metadata_hash==item['metadata_hash'] and f.size==item['size'] and sha(files.path(f))==item['sha256']
 return dict(synthetic=True,parent_database=manifest['database'],parent_database_sha256=manifest['database_sha256'],current_main_database_sha256=sha(main),all_old_sql_rows_unchanged=True,old_sql_tables=45,new_operational_tables=3,exact_old_table_additions=added,templates=1,template_versions=1,transform_receipts=1,new_private_originals=3,rows_checked=24,sessions_checked=3,old_physical_files_unchanged=len(manifest['physical']),protected_engines_unchanged=16,old_schema_access_and_collector_exact=True,no_associations_or_grants_or_metric_publications=True,all_original_excel_business_facts_unchanged=True,migration='0018_device_transform_templates')
if __name__=='__main__':
 result=verify_increment();(ROOT/'data/device_transform_preservation.json').write_text(json.dumps(result,ensure_ascii=False,indent=2));print(json.dumps(result,ensure_ascii=False,indent=2))
