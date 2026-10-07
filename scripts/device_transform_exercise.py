"""Exercise native archive/template/preview/execute APIs on synthetic protocol files."""
import csv,hashlib,io,json,uuid
from pathlib import Path

def exercise(root,export=False):
 from django.test import RequestFactory
 from django.contrib.auth.models import User
 from django.core.files.uploadedfile import SimpleUploadedFile
 from app import device_transform as engine,device_transform_views as views,device_file_views as archive_views,device_files as files,metric_registry
 from app.models import Record,DeviceFile,DeviceFileReview,FileReadGrant,AuditEvent,DeviceTransformTemplate as Template,DeviceTransformVersion as Version,DeviceTransformReceipt as Receipt,MetricVersion
 fixture=json.loads((root/'outputs/device_transform_samples/manifest.json').read_text());factory=RequestFactory();admin=User.objects.get(username='demo_admin');before=dict(facts=Record.objects.count(),files=DeviceFile.objects.count(),reviews=DeviceFileReview.objects.count(),grants=FileReadGrant.objects.count(),audits=AuditEvent.objects.count());calls=[]
 def invoke(fn,body=None,user=admin,kwargs=None,query=None):
  r=factory.get('/api/device-transform',query or {}) if body is None else factory.post('/api/device-transform',json.dumps(body),content_type='application/json');r.user=user;response=fn(r,**(kwargs or {}));calls.append(dict(view=fn.__name__,user=user.username,status=response.status_code));assert response.status_code==200,(calls[-1],response.content[:300]);return response
 def decode(fn,**kw):return json.loads(invoke(fn,**kw).content)
 sources=[]
 for item in fixture['files']:
  file=root/'outputs/device_transform_samples'/item['filename'];raw=file.read_bytes();assert hashlib.sha256(raw).hexdigest()==item['sha256']
  r=factory.post('/api/device-files/upload',dict(file=SimpleUploadedFile(item['filename'],raw),request_id=str(uuid.uuid4()),note='合成模拟厂商格式，由已导入Excel业务事实生成，不是真实设备采集证据'));r.user=admin;response=archive_views.upload(r);assert response.status_code==200,response.content;sources.append(json.loads(response.content));assert sources[-1]['parser']=='manual'
 spec=fixture['definition'];good,bad=sources
 inspect=decode(views.inspect,body=dict(file_id=good['id'],encoding=spec['encoding'],delimiter=spec['delimiter']));assert inspect['rows']==fixture['rows']==24 and inspect['headers']==spec['headers']
 first=decode(views.preview,body=dict(file_id=good['id'],definition=spec,version_id=None));wrong=decode(views.preview,body=dict(file_id=bad['id'],definition=spec,version_id=None));assert first['can_transform'] and len(first['checks'])==3 and not wrong['can_transform'] and wrong['errors']
 draft_body=dict(code='PARSER.SIM.SB08.CSV',name='模拟综合机台分号CSV字段模板',file_id=good['id'],definition=spec,request_id=str(uuid.uuid4()),expected_revision=None);template=decode(views.draft,body=draft_body);assert decode(views.draft,body=draft_body)==template;vid=template['versions'][0]['id'];payload_hash=template['versions'][0]['payload_hash']
 activation_body=dict(request_id=str(uuid.uuid4()),expected_revision=template['revision'],reason='模拟配置核对：原列、GB18030分号、毫欧换算、时间及判定码逐项对照；不代表业务审批');template=decode(views.activate,kwargs=dict(version_id=vid),body=activation_body);assert decode(views.activate,kwargs=dict(version_id=vid),body=activation_body)==template
 reviewed=decode(views.preview,body=dict(file_id=good['id'],definition=None,version_id=vid));assert reviewed==first
 execute_body=dict(file_id=good['id'],version_id=vid,request_id=str(uuid.uuid4()),preview_token=reviewed['token']);receipt=decode(views.execute,body=execute_body);assert decode(views.execute,body=execute_body)==receipt;output=files.get(admin,receipt['output']['id']);assert output.parsed['mode']=='structured' and output.file_hash==first['output_sha256']
 expected=fixture['standard_expected'];actual=output.parsed['rows'];assert len(actual)==len(expected)
 for source_row,converted in zip(expected,actual):
  for key in files.HEADERS:assert (files.equal_number(source_row[key],converted[key]) if key in ('raw_value','value') else str(source_row[key])==converted[key]),(key,source_row[key],converted[key])
 checks=[]
 for sid in fixture['sessions']:
  p=files.preview(admin,output.pk,sid);assert p['can_confirm'] and p['comparison']['ok'];checks.append(dict(session_id=sid,current_fields_match=True,source_refs=len(p['target']['sources']),measurement_rows=p['comparison']['row_count']))
 csv_verified=False
 if export:
  result=invoke(views.export,kwargs=dict(receipt_id=uuid.UUID(receipt['id'])),query=dict(receipt=receipt['receipt']));rows=list(csv.reader(io.StringIO(result.content.decode('utf-8-sig'))));assert len(rows)==fixture['rows']+4;assert [r[1] for r in rows[4:]]==[r['measurement_id'] for r in expected];csv_verified=True
 profiles=[]
 for role in ('admin','analyst','quality','operations','finance','viewer'):
  user=User.objects.filter(groups__name=role,is_active=True).first();r=factory.get('/api/device-transform');r.user=user;response=views.board(r);assert response.status_code==(200 if role in ('admin','quality') else 403);profiles.append(dict(role=role,status=response.status_code))
  if role=='quality':assert json.loads(response.content)['templates']==[] and json.loads(response.content)['receipts']==[]
 assert Record.objects.count()==before['facts']==212691 and DeviceFile.objects.count()==before['files']+3 and DeviceFileReview.objects.count()==before['reviews'] and FileReadGrant.objects.count()==before['grants'];assert (Template.objects.count(),Version.objects.count(),Receipt.objects.count())==(1,1,1)
 v8=MetricVersion.objects.get(metric__key='DELIVERY_OTIF',version=8,status='published');assert metric_registry.calculation_hash(v8.metric.dataset)==v8.calculation_hash=='9d9a5af3d45172eca16790d628a36bc6acbe18d1e2a811a66a5b5fbff7037fe3'
 originals=[files.get(admin,fid) for fid in [good['id'],bad['id'],str(output.pk)]]
 return dict(synthetic=True,native_api_views=True,real_device_pc_connected=False,template=template,template_payload_hash=payload_hash,receipt=receipt,receipt_id=receipt['id'],version_id=vid,source_files=sources,new_files=[dict(id=str(f.pk),filename=f.filename,sha256=f.file_hash,size=f.size,metadata_hash=f.metadata_hash,owner=admin.username) for f in originals],request_bodies=dict(draft=draft_body,activate=activation_body,execute=execute_body),rows=24,sessions=3,all_standard_cells_equal_original_excel_facts=True,native_session_checks=checks,wrong_sn_and_unknown_result_blocked=True,role_profiles=profiles,repeat_requests_no_extra_writes=True,business_facts_before=before['facts'],business_facts_after=Record.objects.count(),associations_or_grants_added=False,published_v8_hash_unchanged=True,api_csv_full_scope_checked=csv_verified,audit_increment=AuditEvent.objects.count()-before['audits'],calls=calls,browser_mobile_and_actual_download_accepted=False)
