import csv,io,json,tempfile,uuid
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch
from django.contrib.auth.models import User,Group
from django.core.exceptions import ValidationError,PermissionDenied
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from app import device_transform as dt,device_files as files
from app.models import Record,DeviceFile,DeviceTransformTemplate as Template,DeviceTransformVersion as Version,DeviceTransformReceipt as Receipt,DeviceFileReview,FileReadGrant,AuditEvent
from app.import_review import ReviewConflict
from tests.test_platform import PlatformCase

class DeviceTransformTests(PlatformCase):
 def setUp(self):
  super().setUp();self.client.force_login(self.admin);self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.override=self.settings(DEVICE_FILE_ROOT=Path(self.temp.name));self.override.enable();self.addCleanup(self.override.disable)
  for ds,v in [('products',dict(id='CP001')),('work_orders',dict(id='WO001',product_id='CP001')),('units',dict(id='M260921000001',work_order_id='WO001',product_id='CP001')),('equipment',dict(id='SB001')),('test_specs',dict(id='SPEC1')),('test_sessions',dict(id='T001',unit_id='M260921000001',equipment_id='SB001',tested='2026-09-21T08:00:00',spec_version='A',result='合格',complete=True,voided=False)),('measurements',dict(id='M001',session_id='T001',spec_id='SPEC1',raw_value=1.25,raw_unit='Ω',value=1.25,unit='Ω',result='合格',file_reference='sim.csv'))]:self.record(ds,v)
  self.headers=['vendor_'+k for k in files.HEADERS];self.values=dict(zip(self.headers,['T001','M260921000001','WO001','CP001','SB001','2026/09/21 08:00:00','A','M001','SPEC1','1.25','Ω','1250','mΩ','PASS']));self.spec=dict(encoding='utf-8-sig',delimiter=';',headers=self.headers,fields={k:dict(column=h) for k,h in zip(files.HEADERS,self.headers)},result_map={'PASS':'合格','FAIL':'不合格'},tested_format='%Y/%m/%d %H:%M:%S',conversions=['mΩ→Ω']);self.source=self.archive(self.headers,[self.values])
 def archive(self,headers,rows,encoding='utf-8-sig',delimiter=';',user=None):
  stream=io.StringIO();w=csv.DictWriter(stream,headers,delimiter=delimiter);w.writeheader();w.writerows(rows);return files.upload(user or self.admin,SimpleUploadedFile('模拟机台.csv',stream.getvalue().encode(encoding)),uuid.uuid4(),'模拟机台字段转换原件')
 def draft(self,spec=None,file=None,expected=None,code='PARSER.SIM.001'):
  body=dict(code=code,name='模拟机台字段模板',file_id=str((file or self.source).pk),definition=spec or self.spec,request_id=str(uuid.uuid4()),expected_revision=expected);return dt.draft(self.admin,body),body
 def active(self):
  t,b=self.draft();v=t['versions'][0];body=dict(request_id=str(uuid.uuid4()),expected_revision=t['revision'],reason='核对模拟列名、单位、编号和全部会话字段');return dt.activate(self.admin,v['id'],body),v['id'],body
 def execute(self):
  t,vid,_=self.active();p,raw=dt.preview(self.admin,self.source.pk,self.spec);b=dict(file_id=str(self.source.pk),version_id=vid,request_id=str(uuid.uuid4()),preview_token=p['token']);return dt.execute(self.admin,b),b
 def test_preview_unit_time_result_and_raw_value_preserved(self):
  p,raw=dt.preview(self.admin,self.source.pk,self.spec);self.assertTrue(p['can_transform']);r=p['lineage'][0]['output_values'];self.assertEqual((r['raw_value'],r['raw_unit'],r['value'],r['unit'],r['tested'],r['result']),('1.25','Ω','1.250','Ω','2026-09-21T08:00:00','合格'));self.assertEqual(len(p['lineage'][0]['changes']),3);self.assertFalse(Template.objects.exists());self.assertEqual(DeviceFile.objects.count(),1);self.assertTrue(files.compare(files.parse(raw,'csv'),files.target('T001'))['ok'])
 def test_zero_leading_identifiers_are_text(self):
  p,_=dt.preview(self.admin,self.source.pk,self.spec);self.assertEqual(p['lineage'][0]['source_values']['vendor_unit_id'],'M260921000001');self.assertEqual(p['lineage'][0]['output_values']['measurement_id'],'M001')
 def test_inspect_reads_actual_headers_and_samples_no_writes(self):
  d=dt.inspection(self.admin,dict(file_id=str(self.source.pk),encoding='utf-8-sig',delimiter=';'));self.assertEqual(d['headers'],self.headers);self.assertEqual(d['rows'],1);self.assertEqual(d['sample'][0]['line'],2);self.assertEqual(d['sample'][0]['values'],self.values)
 def test_gb18030_encoding_and_tab_supported(self):
  f=self.archive(self.headers,[self.values],encoding='gb18030',delimiter='\t');s={**self.spec,'encoding':'gb18030','delimiter':'\t'};self.assertTrue(dt.preview(self.admin,f.pk,s)[0]['can_transform'])
 def test_wrong_encoding_or_delimiter_rejected(self):
  with self.assertRaises((ReviewConflict,ValidationError)):dt.preview(self.admin,self.source.pk,{**self.spec,'encoding':'gb18030'})
  with self.assertRaises((ReviewConflict,ValidationError)):dt.preview(self.admin,self.source.pk,{**self.spec,'delimiter':','})
 def test_duplicate_headers_and_empty_source_rejected(self):
  f=files.upload(self.admin,SimpleUploadedFile('重复.csv',b'x;x\n1;2\n'),uuid.uuid4(),'模拟重复列待核对')
  with self.assertRaises(ValidationError):dt.inspection(self.admin,dict(file_id=str(f.pk),encoding='utf-8-sig',delimiter=';'))
  f=files.upload(self.admin,SimpleUploadedFile('空表.csv',b'x;y\n'),uuid.uuid4(),'模拟空表待核对')
  with self.assertRaises(ValidationError):dt.inspection(self.admin,dict(file_id=str(f.pk),encoding='utf-8-sig',delimiter=';'))
 def test_non_csv_source_not_transformable(self):
  f=files.upload(self.admin,SimpleUploadedFile('说明.txt',b'manual'),uuid.uuid4(),'非结构化说明模拟')
  with self.assertRaises(ValidationError):dt.preview(self.admin,f.pk,self.spec)
 def test_header_order_change_rejected(self):
  f=self.archive(list(reversed(self.headers)),[self.values])
  with self.assertRaises(ReviewConflict):dt.preview(self.admin,f.pk,self.spec)
 def test_extra_missing_fields_and_expression_not_allowed(self):
  for changed in [{**self.spec,'expression':'__import__("os")'}, {**self.spec,'fields':{k:v for k,v in self.spec['fields'].items() if k!='unit_id'}}, {**self.spec,'fields':{**self.spec['fields'],'value':{'expression':'1+2'}}}]:
   with self.subTest(changed=changed),self.assertRaises(ValidationError):dt.definition(changed)
 def test_identity_raw_measurement_and_result_constants_forbidden(self):
  for field in dt.NO_CONSTANT:
   with self.subTest(field=field),self.assertRaises(ValidationError):dt.definition({**self.spec,'fields':{**self.spec['fields'],field:{'constant':'x'}}})
 def test_declared_constant_equipment_is_explicit_and_verified(self):
  p,_=dt.preview(self.admin,self.source.pk,{**self.spec,'fields':{**self.spec['fields'],'equipment_id':{'constant':'SB001'}}});self.assertTrue(p['can_transform']);self.assertEqual(p['definition']['fields']['equipment_id'],{'constant':'SB001'})
 def test_unknown_unit_conversion_and_duplicate_rule_rejected(self):
  for c in [['mΩ→A'],['mΩ→Ω','mΩ→Ω'],[{}]]:
   with self.subTest(c=c),self.assertRaises(ValidationError):dt.definition({**self.spec,'conversions':c})
 def test_wrong_sn_or_unit_blocks_output(self):
  for field,value in [('vendor_unit_id','WRONG-SN'),('vendor_unit','unknown-unit')]:
   f=self.archive(self.headers,[{**self.values,field:value}]);p,_=dt.preview(self.admin,f.pk,self.spec);self.assertFalse(p['can_transform']);self.assertFalse(p['checks'][0]['matches_current'])
 def test_unknown_result_code_is_error(self):
  f=self.archive(self.headers,[{**self.values,'vendor_result':'UNDEFINED'}]);p,_=dt.preview(self.admin,f.pk,self.spec);self.assertFalse(p['can_transform']);self.assertTrue(p['errors'])
 def test_nonfinite_and_extreme_numeric_reported(self):
  for value in ('NaN','Infinity','1e9999','1e-999999999','__import__("os")'):
   f=self.archive(self.headers,[{**self.values,'vendor_value':value}]);p,_=dt.preview(self.admin,f.pk,self.spec);self.assertFalse(p['can_transform']);self.assertTrue(p['errors'])
 def test_aware_or_invalid_time_not_silently_converted(self):
  for stamp in ('2026-09-21T08:00:00+08:00','2026-09-21T08:00:00.123','invalid'):
   f=self.archive(self.headers,[{**self.values,'vendor_tested':stamp}]);p,_=dt.preview(self.admin,f.pk,{**self.spec,'tested_format':'iso'});self.assertFalse(p['can_transform'])
 def test_duplicate_measurement_rows_not_eligible(self):
  f=self.archive(self.headers,[self.values,self.values]);p,_=dt.preview(self.admin,f.pk,self.spec);self.assertFalse(p['can_transform']);self.assertIn('重复',p['checks'][0]['comparison']['issues'][0])
 def test_missing_current_target_not_eligible(self):
  Record.objects.filter(dataset='test_sessions').delete();p,_=dt.preview(self.admin,self.source.pk,self.spec);self.assertFalse(p['can_transform']);self.assertIsNone(p['checks'][0]['target'])
 def test_template_draft_replay_and_request_conflict(self):
  t,b=self.draft();self.assertEqual(dt.draft(self.admin,b),t);self.assertEqual(Template.objects.count(),1);self.assertEqual(Version.objects.count(),1)
  with self.assertRaises(ReviewConflict):dt.draft(self.admin,{**b,'name':'changed'})
 def test_draft_not_usable_until_active(self):
  t,_=self.draft()
  with self.assertRaises(ReviewConflict):dt.get_version(self.admin,t['versions'][0]['id'],active=True)
 def test_invalid_draft_preserved_but_not_activatable(self):
  f=self.archive(self.headers,[{**self.values,'vendor_unit_id':'WRONG'}]);t,_=self.draft(file=f);self.assertFalse(t['versions'][0]['payload']['review']['can_transform'])
  with self.assertRaises(ReviewConflict):dt.activate(self.admin,t['versions'][0]['id'],dict(request_id=str(uuid.uuid4()),expected_revision=t['revision'],reason='模拟核对失败不能启用'))
 def test_activate_idempotent_and_old_expected_revision_rejected(self):
  t,vid,b=self.active();self.assertEqual(dt.activate(self.admin,vid,b),t)
  with self.assertRaises(ReviewConflict):dt.activate(self.admin,vid,{**b,'reason':'不同用途'})
 def test_new_version_retires_old_payload_unchanged(self):
  first,vid,_=self.active();v1=Version.objects.get(pk=vid);payload=deepcopy(v1.payload);content_hash=v1.payload_hash;t,_=self.draft(expected=first['revision']);v2=t['versions'][0];second=dt.activate(self.admin,v2['id'],dict(request_id=str(uuid.uuid4()),expected_revision=t['revision'],reason='再次核对模拟版本并替代旧配置'));v1.refresh_from_db();self.assertEqual(v1.payload,payload);self.assertEqual(v1.payload_hash,content_hash);self.assertEqual(v1.state,'retired');self.assertEqual(second['current_version'],2)
  with self.assertRaises(ReviewConflict):dt.get_version(self.admin,vid,active=True)
 def test_source_or_current_facts_change_blocks_activation(self):
  t,_=self.draft();r=Record.objects.get(dataset='measurements');r.values={**r.values,'value':2};r.save()
  with self.assertRaises(ReviewConflict):dt.activate(self.admin,t['versions'][0]['id'],dict(request_id=str(uuid.uuid4()),expected_revision=t['revision'],reason='旧样例依据已经变化'))
 def test_rules_change_disables_active_template(self):
  _,vid,_=self.active()
  with patch.object(dt,'rules_hash',return_value='changed'),self.assertRaises(ReviewConflict):dt.get_version(self.admin,vid,active=True)
 def test_template_or_version_integrity_tamper_rejected(self):
  _,vid,_=self.active();Template.objects.update(metadata_hash='x')
  with self.assertRaises(ReviewConflict):dt.get_version(self.admin,vid)
 def test_version_payload_immutable(self):
  t,_=self.draft();v=Version.objects.get();v.payload={}
  with self.assertRaises(ValidationError):v.save()
 def test_version_lifecycle_integrity_checked(self):
  _,vid,_=self.active();Version.objects.filter(pk=vid).update(state='draft')
  with self.assertRaises(ReviewConflict):dt.get_version(self.admin,vid)
 def test_execute_exact_standard_file_no_business_or_association_writes(self):
  before=list(Record.objects.order_by('id').values());done,_=self.execute();output=files.get(self.admin,done['output']['id']);self.assertEqual(output.parsed['mode'],'structured');self.assertTrue(files.preview(self.admin,output.pk,'T001')['can_confirm']);self.assertEqual(before,list(Record.objects.order_by('id').values()));self.assertEqual(DeviceFile.objects.count(),2);self.assertFalse(DeviceFileReview.objects.exists());self.assertFalse(FileReadGrant.objects.exists());self.assertFalse(done['payload']['association_confirmed'])
 def test_execute_replay_no_new_receipt_file_or_audit(self):
  done,b=self.execute();n=AuditEvent.objects.count();self.assertEqual(dt.execute(self.admin,b),done);self.assertEqual(Receipt.objects.count(),1);self.assertEqual(DeviceFile.objects.count(),2);self.assertEqual(AuditEvent.objects.count(),n)
  with self.assertRaises(ReviewConflict):dt.execute(self.admin,{**b,'preview_token':'changed'})
 def test_execute_stale_preview_blocks_upload(self):
  _,vid,_=self.active();p,_=dt.preview(self.admin,self.source.pk,self.spec);r=Record.objects.get(dataset='measurements');r.values={**r.values,'value':2};r.save()
  with self.assertRaises(ReviewConflict):dt.execute(self.admin,dict(file_id=str(self.source.pk),version_id=vid,request_id=str(uuid.uuid4()),preview_token=p['token']))
  self.assertEqual(DeviceFile.objects.count(),1)
 def test_interruption_after_archive_resumes_one_output(self):
  _,vid,_=self.active();p,_=dt.preview(self.admin,self.source.pk,self.spec);b=dict(file_id=str(self.source.pk),version_id=vid,request_id=str(uuid.uuid4()),preview_token=p['token'])
  with patch.object(Receipt,'save',side_effect=RuntimeError('interrupted')),self.assertRaises(RuntimeError):dt.execute(self.admin,b)
  self.assertEqual(DeviceFile.objects.count(),2);self.assertEqual(Receipt.objects.count(),0);dt.execute(self.admin,b);self.assertEqual(DeviceFile.objects.count(),2);self.assertEqual(Receipt.objects.count(),1)
 def test_historical_receipt_survives_rule_or_target_change_with_warning(self):
  done,_=self.execute();r=Record.objects.get(dataset='measurements');r.values={**r.values,'value':2};r.save();current=dt.detail(self.admin,done['id']);self.assertFalse(current['current_targets'][0]['current_target_unchanged']);self.assertEqual(current['payload'],done['payload']);self.assertNotEqual(current['receipt'],done['receipt'])
 def test_source_corrupt_separate_from_successful_historical_output(self):
  done,_=self.execute();files.path(self.source).write_bytes(b'corrupt');current=dt.detail(self.admin,done['id']);self.assertEqual(current['source']['current_integrity'],'failed');self.assertEqual(current['output']['current_integrity'],'ok');self.assertEqual(current['payload'],done['payload'])
 def test_receipt_immutable_and_tampered_hash_rejected(self):
  done,_=self.execute();r=Receipt.objects.get()
  with self.assertRaises(ValidationError):r.save()
  Receipt.objects.update(payload_hash='x')
  with self.assertRaises(ReviewConflict):dt.detail(self.admin,done['id'])
 def test_private_template_source_and_receipt(self):
  done,_=self.execute();self.assertEqual(dt.board(self.quality)['templates'],[])
  with self.assertRaises(Version.DoesNotExist):dt.get_version(self.quality,Version.objects.get().pk)
  with self.assertRaises(DeviceFile.DoesNotExist):dt.inspection(self.quality,dict(file_id=str(self.source.pk),encoding='utf-8-sig',delimiter=';'))
  with self.assertRaises(Receipt.DoesNotExist):dt.detail(self.quality,done['id'])
 def test_fresh_disabled_or_changed_role_checked(self):
  self.admin.is_active=False;self.admin.save()
  with self.assertRaises(PermissionDenied):dt.board(self.admin)
 def test_csv_export_matching_all_rows_and_stale_receipt(self):
  done,_=self.execute();url=f'/api/device-transform/receipts/{done["id"]}/export';self.assertEqual(self.client.get(url,dict(receipt='stale')).status_code,400);r=self.client.get(url,dict(receipt=done['receipt']));self.assertEqual(r.status_code,200);rows=list(csv.reader(io.StringIO(r.content.decode('utf-8-sig'))));self.assertEqual(len(rows),5);self.assertEqual(rows[4][1:4],['M001','T001','M260921000001']);self.assertEqual(AuditEvent.objects.filter(action='device_transform.export').count(),1)
 def test_api_unknown_parameters_csrf_and_wrong_method(self):
  self.assertEqual(self.client.get('/api/device-transform?extra=x').status_code,400);self.assertEqual(self.client.get('/api/device-transform/inspect').status_code,405)
  c=Client(enforce_csrf_checks=True);c.force_login(self.admin);self.assertEqual(c.post('/api/device-transform/drafts','{}',content_type='application/json').status_code,403)
 def test_preview_active_template_cannot_override_definition(self):
  _,vid,_=self.active();r=self.post('/api/device-transform/preview',dict(file_id=str(self.source.pk),definition=self.spec,version_id=vid));self.assertEqual(r.status_code,400)
