"""Native-view simulation; no association, grant, metric or business fact writes."""
import csv,hashlib,io,json,time,uuid
from pathlib import Path

def exercise(root,export=False):
 from django.test import RequestFactory
 from django.contrib.auth.models import User
 from app import device_collector as engine,device_collector_views as views,device_files as originals,metric_registry
 from app.models import Record,DeviceFile,DeviceFileReview,FileReadGrant,DeviceCollectionRun,DeviceCollectionEvent,AuditEvent,MetricVersion
 admin=User.objects.get(username='demo_admin');factory=RequestFactory();before=dict(facts=Record.objects.count(),files=DeviceFile.objects.count(),reviews=DeviceFileReview.objects.count(),grants=FileReadGrant.objects.count(),audits=AuditEvent.objects.count());calls=[]
 def invoke(fn,body=None,user=admin,run_id=None,query=None):
  request=factory.get('/api/device-collection',query or {}) if body is None else factory.post('/api/device-collection',json.dumps(body),content_type='application/json');request.user=user
  result=fn(request,**({'run_id':uuid.UUID(run_id)} if run_id else {}));calls.append(dict(view=fn.__name__,user=user.username,status=result.status_code));assert result.status_code==200,(calls[-1],result.content[:250]);return result
 def decode(fn,**kwargs):return json.loads(invoke(fn,**kwargs).content)
 source='DS-PC-2026-001';first=decode(views.preview,body=dict(source_id=source,prior_receipt=None));assert first['summary']==dict(waiting=5,skipped=1,too_big=1),first['summary']
 time.sleep(2.15);second=decode(views.preview,body=dict(source_id=source,prior_receipt=first['receipt']));assert second['summary']==dict(stable=5,skipped=1,too_big=1),second['summary']
 fixture=json.loads((root/'data/device_inbox/fixture_manifest.json').read_text());by_path={str(Path(r['path']).relative_to(source)):r for r in fixture['files'] if r['path'].startswith(source+'/')}
 for item in second['items']:
  expected=by_path[item['path']];assert item['size']==expected['size']
  if item['eligible']:assert item['sha256']==expected['sha256']
 create_body=dict(source_id=source,request_id=str(uuid.uuid4()),receipt=second['receipt'],keys=[i['key'] for i in second['items'] if i['eligible']]);run=decode(views.create,body=create_body);assert decode(views.create,body=create_body)['receipt']==run['receipt'];assert DeviceCollectionRun.objects.count()==1
 take_body=dict(request_id=str(uuid.uuid4()),versions={r['item']['key']:0 for r in run['rows']});done=decode(views.collect,body=take_body,run_id=run['id']);assert done['summary']==dict(archived=4,reused=1),done['summary'];assert decode(views.collect,body=take_body,run_id=run['id'])['receipt']==done['receipt']
 assertions=[]
 for row in done['rows']:
  f=originals.get(admin,row['archive']['id']);expected=by_path[row['item']['path']];assert originals.contents(f)==(root/'data/device_inbox'/source/row['item']['path']).read_bytes();assert f.file_hash==expected['sha256'] and f.size==expected['size']
  if f.parsed['mode']=='structured':
   p=originals.preview(admin,f.pk,f.parsed['sessions'][0]);wrong=row['item']['path']=='线索错位.csv';assert p['can_confirm'] is (not wrong);assert p['comparison']['ok'] is (not wrong);assertions.append(dict(path=row['item']['path'],mode='structured',matches_current_session=not wrong,can_confirm=p['can_confirm']))
  else:assert f.parsed['mode']=='manual';assertions.append(dict(path=row['item']['path'],mode='manual',content_verified=False))
 profiles=[]
 for role in ('admin','analyst','quality','operations','finance','viewer'):
  user=User.objects.filter(groups__name=role,is_active=True).first();request=factory.get('/api/device-collection');request.user=user;response=views.board(request);assert response.status_code==(200 if role in ('admin','quality') else 403);profiles.append(dict(role=role,status=response.status_code))
  if role=='quality':assert json.loads(response.content)['runs']==[]
 csv_verified=False
 if export:
  result=invoke(views.export,run_id=run['id'],query=dict(receipt=done['receipt']));rows=list(csv.reader(io.StringIO(result.content.decode('utf-8-sig'))));assert len(rows)==len(done['rows'])+4 and {r[0] for r in rows[4:]}=={r['item']['path'] for r in done['rows']};csv_verified=True
 assert Record.objects.count()==before['facts']==212691 and DeviceFile.objects.count()==before['files']+4 and DeviceFileReview.objects.count()==before['reviews'] and FileReadGrant.objects.count()==before['grants'];assert DeviceCollectionEvent.objects.count()==5
 v8=MetricVersion.objects.get(metric__key='DELIVERY_OTIF',version=8,status='published');assert metric_registry.calculation_hash(v8.metric.dataset)==v8.calculation_hash=='9d9a5af3d45172eca16790d628a36bc6acbe18d1e2a811a66a5b5fbff7037fe3'
 new=list(DeviceFile.objects.filter(owner=admin).order_by('-created_at')[:4]);assert {str(f.pk) for f in new}=={r['archive']['id'] for r in done['rows']}
 return dict(synthetic=True,local_simulation=True,real_device_pc_connected=False,native_api_views=True,source_id=source,run_id=done['id'],run=done,request_bodies=dict(create=create_body,collect=take_body),observations=7,stable_selectable=5,known_distinct_content=4,new_private_originals=[dict(id=str(f.pk),filename=f.filename,sha256=f.file_hash,size=f.size,metadata_hash=f.metadata_hash,owner=admin.username) for f in new],native_session_checks=assertions,all_frozen_and_archived_bytes_match=True,role_profiles=profiles,business_facts_before=before['facts'],business_facts_after=Record.objects.count(),associations_or_grants_added=False,published_v8_hash_unchanged=True,repeat_requests_no_extra_writes=True,api_csv_full_scope_checked=csv_verified,audit_increment=AuditEvent.objects.count()-before['audits'],calls=calls,browser_mobile_and_actual_download_accepted=False)
