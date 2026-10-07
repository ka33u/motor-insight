"""Read-only main-state preservation and actual-data exercise in a disposable DB."""
import os,sys,json,sqlite3,tempfile,zipfile,hashlib,uuid
from pathlib import Path
from datetime import datetime,timedelta,timezone as tz
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));BASELINE=ROOT/'data/backups/motor-backup-20261006-100931.zip'
def canonical(v):return hashlib.sha256(json.dumps(v,ensure_ascii=False,sort_keys=True,default=str).encode()).hexdigest()
def sql(path):
 c=sqlite3.connect(Path(path).resolve().as_uri()+'?mode=ro',uri=True);c.row_factory=sqlite3.Row;return c

with tempfile.TemporaryDirectory(prefix='file-sharing-review-') as directory:
 temp=Path(directory);baseline=temp/'before.sqlite3';copy=temp/'exercise.sqlite3'
 with zipfile.ZipFile(BASELINE) as z:
  assert z.testzip() is None;baseline.write_bytes(z.read('data/platform.sqlite3'));manifest=json.loads(z.read('manifest.json'))
  for f in manifest['files']:
   raw=z.read(f['path']);assert len(raw)==f['size'] and hashlib.sha256(raw).hexdigest()==f['sha256']
   if f['path'] not in ['data/platform.sqlite3','data/bi_design.json']:assert (ROOT/f['path']).read_bytes()==raw
 with sql(baseline) as old,sql(ROOT/'data/platform.sqlite3') as live:
  additions={};preserved={}
  for (name,) in old.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"):
   keys=[r['name'] for r in sorted(old.execute('PRAGMA table_info("'+name+'")'),key=lambda r:r['pk']) if r['pk']]
   assert keys,name
   before={tuple(r[k] for k in keys):dict(r) for r in old.execute('SELECT * FROM "'+name+'"')};after={tuple(r[k] for k in keys):dict(r) for r in live.execute('SELECT * FROM "'+name+'"')}
   assert all(after[k]==v for k,v in before.items()),name
   new=[v for k,v in after.items() if k not in before];preserved[name]=len(before)
   if new:
    assert name in ['django_migrations','django_content_type','auth_permission'],name
    additions[name]=len(new)
  assert additions=={'django_migrations':1,'django_content_type':1,'auth_permission':4},additions
  assert live.execute('SELECT COUNT(*) FROM app_filereadgrant').fetchone()[0]==0
 with sqlite3.connect(ROOT/'data/platform.sqlite3') as src,sqlite3.connect(copy) as dst:src.backup(dst)
 os.environ['MOTOR_SQLITE_PATH']=str(copy);os.environ['DJANGO_SETTINGS_MODULE']='config.settings'
 import django;django.setup()
 from django.conf import settings
 assert Path(settings.DATABASES['default']['NAME']).resolve()==copy.resolve()
 from django.contrib.auth.models import User
 from django.test import Client
 from django.utils import timezone
 from app import file_sharing as share,material_certificates as cert,analytics,device_files as files
 from app.models import Record,FileReadGrant,AccountAccessState,AnalysisModel,MetricVersion
 from app import targets,metric_registry
 from app.analysis_engine import run_analysis
 from app.models import DeviceFile
 from app.import_review import ReviewConflict
 # All mutations below are confined to the copied DB; no file upload or byte write.
 admin=User.objects.get(username='demo_admin');quality=User.objects.get(username='demo_quality')
 tables=analytics.tables();owner_rows=cert.Certificates(tables,cert.resolver(admin));chosen=next(r for r in owner_rows.rows if r['state']=='consistent' and DeviceFile.objects.get(pk=r['file']['id']).owner_id==admin.pk)
 f=DeviceFile.objects.get(pk=chosen['file']['id']);key=chosen['id'];raw=files.path(f).read_bytes();before_raw=hashlib.sha256(raw).hexdigest()
 facts_before=canonical(list(Record.objects.order_by('id').values()));checks=[]
 def mark(name):checks.append(name)
 def independent_read(at=None):
  with sql(copy) as c:
   account=dict(c.execute('SELECT * FROM auth_user WHERE id=?',(quality.pk,)).fetchone())
   groups=[r[0] for r in c.execute('SELECT g.name FROM auth_group g JOIN auth_user_groups ug ON ug.group_id=g.id WHERE ug.user_id=? ORDER BY g.name',(quality.pk,))]
   known=set(groups)&{'admin','analyst','quality','operations','finance','viewer'}
   role='admin' if account['is_superuser'] else (next(iter(known)) if len(known)==1 else ('viewer' if not known else None))
   if not account['is_active'] or role is None:return False
   state=c.execute('SELECT revision FROM app_accountaccessstate WHERE user_id=?',(quality.pk,)).fetchone()
   stamp=canonical(dict(id=quality.pk,active=bool(account['is_active']),role=role,superuser=bool(account['is_superuser']),groups=groups,revision=state[0] if state else 0))
   events=[dict(r) for r in c.execute('SELECT * FROM app_filereadgrant WHERE file_id=? ORDER BY version',(f.pk.hex,))];last=None;latest=None
   for n,e in enumerate(events,1):
    p=json.loads(e['payload']);expected=dict(file_id=str(f.pk),file_hash=f.file_hash,metadata_hash=f.metadata_hash,recipient_id=e['recipient_id'],actor_id=e['actor_id'],action=e['action'],version=n,request_id=str(uuid.UUID(e['request_id'])),previous_id=last['id'] if last else None,previous_hash=last['payload_hash'] if last else None)
    if e['version']!=n or e['actor_id']!=f.owner_id or canonical(p)!=e['payload_hash'] or any(p.get(k)!=v for k,v in expected.items()):return False
    if e['recipient_id']==quality.pk:latest=p
    last=e
   if not latest or latest['action']!='grant' or latest['recipient_stamp']!=stamp:return False
   until=datetime.strptime(latest['expires_at'],'%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=tz.utc) if latest['expires_at'] else None
   return until is None or (at or datetime.now(tz.utc))<until
 def expected(value):
  assert independent_read()==value
  try:share.readable(quality,f.pk);actual=True
  except (DeviceFile.DoesNotExist,ReviewConflict):actual=False
  assert actual==value
 def data(action='grant',until=''):return dict(recipient_id=quality.pk,action=action,reason='隔离副本中的模拟原件授权演练，不是主库人工批准',expires_at=until)
 def save(d):
  p=share.preview(admin,f.pk,d);payload=d|dict(request_id=str(uuid.uuid4()),token=p['token']);return share.commit(admin,f.pk,payload),payload
 expected(False);mark('default_private')
 before=FileReadGrant.objects.count();share.preview(admin,f.pk,data());assert FileReadGrant.objects.count()==before;mark('preview_no_mutation')
 e1,retry=save(data());expected(True);mark('exact_recipient_grant')
 reader=cert.Certificates(tables,cert.resolver(quality)).index[key];assert reader['state']=='consistent';assert reader['raw_receipt_status']==chosen['raw_receipt_status'];mark('certificate_identity_and_original_iqc_preserved')
 client=Client();client.force_login(quality);old=client.get('/api/material-certificates').json()['receipt']
 reply=client.get('/api/shared-originals/'+str(f.pk)+'/original');assert reply.status_code==200 and reply.content==raw
 assert reply['Cache-Control']=='no-store' and reply['X-Content-Type-Options']=='nosniff' and 'sandbox' in reply['Content-Security-Policy'];mark('in_process_api_download_bytes_and_headers')
 assert client.get('/api/device-files/'+str(f.pk)+'/original').status_code==404;mark('association_workspace_remains_owner_only')
 save(data('revoke'));expected(False);assert client.get('/api/shared-originals/'+str(f.pk)+'/original').status_code==404;mark('revoke_stops_next_read')
 before=FileReadGrant.objects.count();assert share.commit(admin,f.pk,retry).pk==e1.pk and FileReadGrant.objects.count()==before;expected(False);mark('retry_does_not_restore_permission')
 save(data());expected(True);new=client.get('/api/material-certificates').json()['receipt'];assert new!=old
 assert client.get('/api/material-certificates/export?receipt='+old).status_code==409;mark('regrant_invalidates_old_bi_receipt')
 state,_=AccountAccessState.objects.get_or_create(user=quality);state.revision+=1;state.save();expected(False);mark('account_configuration_change_pauses_read')
 end=(timezone.now()+timedelta(hours=2)).replace(microsecond=0);save(data(until=end.strftime('%Y-%m-%dT%H:%M:%SZ')));expected(True)
 assert independent_read(end) is False
 with patch('app.file_sharing.timezone.now',return_value=end):
  try:share.readable(quality,f.pk);raise AssertionError('expired grant read allowed')
  except DeviceFile.DoesNotExist:pass
 mark('exclusive_expiry_boundary')
 last=FileReadGrant.objects.order_by('-version').first();FileReadGrant.objects.filter(pk=last.pk).update(payload_hash='bad');expected(False)
 assert cert.Certificates(tables,cert.resolver(quality)).index[key]['state']=='no_access';mark('damaged_grant_does_not_become_material_failure')
 assert files.contents(f)==raw and hashlib.sha256(files.path(f).read_bytes()).hexdigest()==before_raw;assert canonical(list(Record.objects.order_by('id').values()))==facts_before
 # Numerical results and published metric identity remain unchanged.
 models_before=json.loads((ROOT/'data/assembly_plans_before.json').read_text())
 def projection(value):
  projected=json.loads(json.dumps(value,default=str));projected.pop('metric_receipt',None)
  for key2 in ['pivot','scatter']:
   if isinstance(projected.get(key2),dict):projected[key2].pop('revision',None)
  return projected
 model_count=0
 for mid,prior in models_before['models'].items():
  m=AnalysisModel.objects.get(pk=mid);assert projection(run_analysis(admin,m.dataset,m.definition))==projection(prior),mid
  model_count+=1
 assert model_count==52
 assert {r['id']:json.loads(json.dumps(r,default=str)) for r in targets.Targets(admin).rows.values()}=={r['id']:r for r in models_before['targets']}
 metric=MetricVersion.objects.get(status='published',metric__key='DELIVERY_OTIF',version=8)
 assert metric.calculation_hash==metric_registry.calculation_hash(metric.metric.dataset)=='9d9a5af3d45172eca16790d628a36bc6acbe18d1e2a811a66a5b5fbff7037fe3'
 mark('business_facts_and_original_bytes_unchanged')
 report=dict(synthetic=True,baseline=str(BASELINE.relative_to(ROOT)),main_tables_preserved=preserved,
   permitted_schema_metadata_additions=additions,main_read_grants=0,isolated_database_only=True,
   actual_receipt=key,original_sha256=before_raw,checks=checks,models_evaluated=model_count,
   targets_preserved=33,published_metric_version=8,records=Record.objects.count(),browser=dict(rendered=False,mobile=False,actual_download=False,sharing_ui=False,
   reason='浏览器自动授权此前连续两次超时，待询无答复；上述下载为隔离副本API测试客户端，不代表浏览器实测'))
 (ROOT/'data/file_sharing_validation.json').write_text(json.dumps(report,ensure_ascii=False,indent=2));print(json.dumps({k:v for k,v in report.items() if k!='main_tables_preserved'},ensure_ascii=False))
