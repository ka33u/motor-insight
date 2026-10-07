import io,csv,json,uuid,tempfile,copy
from pathlib import Path
from unittest.mock import patch
from django.test import override_settings,Client
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.exceptions import ValidationError,PermissionDenied
from django.contrib.auth.models import User,Group
from app import device_files as df
from app.models import Record,DeviceFile,DeviceFileReview,AuditEvent
from app.import_review import ReviewConflict
from tests.test_platform import PlatformCase

class DeviceFilesTests(PlatformCase):
    def setUp(self):
        super().setUp();self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.override=override_settings(DEVICE_FILE_ROOT=self.temp.name);self.override.enable();self.addCleanup(self.override.disable);self.client.force_login(self.admin)
        facts={'products':[{'id':'P1','family':'YE4'}],'equipment':[{'id':'EQ1','name':'试验台'}],'work_orders':[{'id':'W1','product_id':'P1'}],
               'units':[{'id':'SN001','work_order_id':'W1','product_id':'P1','assembly_at':'2026-09-21T08:00:00'}],
               'test_sessions':[{'id':'T1','unit_id':'SN001','equipment_id':'EQ1','tested':'2026-09-21T09:00:00','spec_version':'A','result':'合格','voided':False,'complete':True}],
               'test_specs':[{'id':'SP1','product_id':'P1','version':'A','unit':'A'}],
               'measurements':[{'id':'M1','session_id':'T1','spec_id':'SP1','raw_value':1250.5,'raw_unit':'mA','value':1.2505,'unit':'A','result':'合格','file_reference':'device.csv'}],
               'orders':[{'id':'SO1','customer_id':'C1'}],'order_lines':[{'id':'SO1-01','order_id':'SO1','product_id':'P1','unit_price_cents':12345}],
               'allocations':[{'id':'AL1','work_order_id':'W1','order_line_id':'SO1-01','qty':1,'effective':'2026-09-20'}]}
        for ds,rows in facts.items():
            for r in rows:self.record(ds,r)
        self.base_record_hash=self.facts_hash()
    def facts_hash(self):return df.digest(list(Record.objects.order_by('id').values('id','dataset','business_key','values','revision','record_hash','source_row_id')))
    def values(self):return dict(session_id='T1',unit_id='SN001',work_order_id='W1',product_id='P1',equipment_id='EQ1',tested='2026-09-21T09:00:00',spec_version='A',measurement_id='M1',spec_id='SP1',raw_value='1250.5',raw_unit='mA',value='1.2505',unit='A',result='合格')
    def csv(self,rows=None,headers=None,encoding='utf-8-sig'):
        out=io.StringIO();writer=csv.DictWriter(out,headers or df.HEADERS);writer.writeheader();writer.writerows(rows if rows is not None else [self.values()]);return out.getvalue().encode(encoding)
    def upload(self,raw=None,name='检测原件.csv',user=None,rid=None,note='模拟设备原始导出用于核对'):
        return df.upload(user or self.admin,SimpleUploadedFile(name,raw if raw is not None else self.csv()),rid or str(uuid.uuid4()),note)
    def payload(self,f,action='confirm',sid='T1'):
        p=df.preview(self.admin,f.pk,sid);return {'request_id':str(uuid.uuid4()),'session_id':sid,'action':action,'reason':'逐项核对原件及会话标识','unit_id':p['target']['unit_id'] if p['target'] else '', 'token':p['token']}
    def change(self,key,**updates):
        r=Record.objects.get(business_key=key);r.values.update(updates);r.save();return r
    def test_archive_is_byte_exact_and_metadata_immutable(self):
        raw=self.csv();f=self.upload(raw);self.assertEqual(df.contents(f),raw);self.assertEqual(f.parsed['mode'],'structured');self.assertEqual(f.parsed['sessions'],['T1'])
        f.note='改写';self.assertRaises(ValidationError,f.save)
    def test_csv_gb18030_and_reordered_headers_are_supported(self):
        f=self.upload(self.csv(headers=list(reversed(df.HEADERS)),encoding='gb18030'));p=df.preview(self.admin,f.pk,'T1');self.assertTrue(p['can_confirm']);self.assertIn('GB18030',f.parsed['message'])
    def test_compare_checks_identity_values_units_equipment_and_version(self):
        for field,value in [('unit_id','WRONG'),('equipment_id','EQ2'),('spec_version','B'),('raw_value','1250'),('raw_unit','A'),('value','1250.5'),('tested','2026-09-22T09:00:00'),('spec_id','SP2'),('result','不合格')]:
            with self.subTest(field=field):
                row=self.values();row[field]=value;f=self.upload(self.csv([row]));p=df.preview(self.admin,f.pk,'T1');self.assertFalse(p['can_confirm']);self.assertTrue(any(x['field']==field for r in p['comparison']['rows'] for x in r['differences']))
                self.assertRaises(ValidationError,df.review,self.admin,f.pk,self.payload(f))
    def test_decimal_equivalence_does_not_infer_unit_conversion(self):
        row=self.values();row['value']='1.250500';f=self.upload(self.csv([row]));self.assertTrue(df.preview(self.admin,f.pk,'T1')['can_confirm'])
        for v in ['NaN','Infinity','-Infinity','1e999999']:
            row['value']=v;f=self.upload(self.csv([row]));self.assertFalse(df.preview(self.admin,f.pk,'T1')['can_confirm'])
    def test_duplicate_and_missing_measurements_cannot_confirm(self):
        f=self.upload(self.csv([self.values(),self.values()]));self.assertFalse(df.preview(self.admin,f.pk,'T1')['can_confirm'])
        self.record('measurements',{'id':'M2','session_id':'T1','spec_id':'SP1','raw_value':1,'raw_unit':'A','value':1,'unit':'A','result':'合格','file_reference':'d.csv'})
        f=self.upload();p=df.preview(self.admin,f.pk,'T1');self.assertFalse(p['can_confirm']);self.assertIn('M2',' '.join(p['comparison']['issues']))
    def test_malformed_standard_headers_are_not_manual_override(self):
        raw=b'session_id,unit_id\nT1,SN001\n';f=self.upload(raw);self.assertEqual(f.parsed['mode'],'invalid');self.assertFalse(df.preview(self.admin,f.pk,'T1')['can_confirm'])
        raw=('session_id,'+','.join(df.HEADERS)+'\n').encode();f=self.upload(raw);self.assertEqual(f.parsed['mode'],'invalid')
    def test_structured_file_cannot_associate_unlisted_session(self):
        s=Record.objects.get(business_key='T1').values;self.record('test_sessions',{**s,'id':'T2'});f=self.upload();p=df.preview(self.admin,f.pk,'T2');self.assertFalse(p['can_confirm'])
    def test_multiple_sessions_checked_independently(self):
        s=Record.objects.get(business_key='T1').values;self.record('test_sessions',{**s,'id':'T2','attempt':2});m=Record.objects.get(business_key='M1').values;self.record('measurements',{**m,'id':'M2','session_id':'T2'})
        row={**self.values(),'session_id':'T2','measurement_id':'M2','value':'2'};f=self.upload(self.csv([self.values(),row]));d=df.detail(self.admin,f.pk)
        self.assertEqual([(x['session_id'],x['can_confirm']) for x in d['checks']],[('T1',True),('T2',False)])
    def test_manual_formats_require_explicit_sn_and_keep_manual_label(self):
        for name,raw in [('note.txt',b'SN001 T1 raw log'),('report.pdf',b'%PDF-1.4\noriginal'),('photo.png',b'\x89PNG\r\n\x1a\noriginal'),('photo.jpg',b'\xff\xd8\xfforiginal'),('report.xlsx',b'PK\x03\x04original')]:
            f=self.upload(raw,name);p=self.payload(f);p['unit_id']='OTHER';self.assertRaises(ValidationError,df.review,self.admin,f.pk,p)
            p['unit_id']='SN001';r=df.review(self.admin,f.pk,p);self.assertEqual(r.payload['mode'],'manual');self.assertIsNone(r.payload['comparison'])
    def test_invalid_extensions_signatures_binary_csv_and_limits(self):
        for name,raw in [('run.exe',b'MZ'),('chart.svg',b'<svg>'),('page.html',b'<html>'),('report.pdf',b'not pdf'),('a.csv',b'\x00file')]:
            self.assertRaises(ValidationError,self.upload,raw,name)
        self.assertRaises(ValidationError,self.upload,b'', 'a.txt')
        with patch.object(df,'MAX_BYTES',10):self.assertRaises(ValidationError,self.upload,b'x'*11,'a.txt')
        self.assertRaises(ValidationError,self.upload,self.csv([self.values()]*2001))
    def test_missing_target_or_dependency_blocks_confirmation(self):
        f=self.upload();self.assertFalse(df.preview(self.admin,f.pk,'MISSING')['can_confirm']);Record.objects.filter(business_key='EQ1').delete();self.assertFalse(df.preview(self.admin,f.pk,'T1')['can_confirm'])
    def test_unique_allocation_is_explicitly_indirect_and_prices_not_saved(self):
        t=df.target('T1');self.assertEqual(t['order_lines'],['SO1-01']);self.assertIn('间接推定',t['ownership']);self.assertFalse(any('unit_price_cents' in s['values'] for s in t['sources'].values()))
    def add_other_order(self):
        self.record('orders',{'id':'SO2','customer_id':'C2'});self.record('order_lines',{'id':'SO2-01','order_id':'SO2','product_id':'P1'});self.record('allocations',{'id':'AL2','work_order_id':'W1','order_line_id':'SO2-01','qty':1,'effective':'2026-09-20'})
    def test_shared_order_remains_ambiguous_without_sn_shipping(self):
        self.add_other_order();t=df.target('T1');self.assertEqual(t['order_lines'],[]);self.assertEqual(t['candidate_order_lines'],['SO1-01','SO2-01']);self.assertIn('待核对',t['ownership'])
    def test_shipping_identifies_order_and_multiple_shipping_blocks_ownership(self):
        self.add_other_order()
        for i in [1,2]:
            self.record('shipments',{'id':f'SH{i}','order_line_id':f'SO{i}-01','shipped':'2026-09-22T10:00:00'});self.record('shipment_units',{'id':f'SU{i}','shipment_id':f'SH{i}','unit_id':'SN001'})
            t=df.target('T1');self.assertEqual(t['order_lines'],['SO1-01'] if i==1 else [])
    def test_future_allocation_and_shipment_are_excluded(self):
        self.add_other_order();self.change('AL2',effective='2026-11-01');self.record('shipments',{'id':'SH2','order_line_id':'SO2-01','shipped':'2026-11-01T10:00:00'});self.record('shipment_units',{'id':'SU2','shipment_id':'SH2','unit_id':'SN001'})
        self.assertEqual(df.target('T1')['candidate_order_lines'],['SO1-01'])
    def test_voided_and_incomplete_files_are_historical_not_quality_approval(self):
        self.change('T1',voided=True,complete=False);f=self.upload();p=df.preview(self.admin,f.pk,'T1');self.assertTrue(p['can_confirm']);self.assertTrue(p['target']['voided']);self.assertEqual(len(p['target']['messages']),2)
    def test_confirm_revoke_and_reconfirm_preserve_all_history(self):
        f=self.upload();r1=df.review(self.admin,f.pk,self.payload(f));r2=df.review(self.admin,f.pk,self.payload(f,'revoke'));r3=df.review(self.admin,f.pk,self.payload(f))
        self.assertEqual([r.version for r in [r1,r2,r3]],[1,2,3]);self.assertEqual(df.listing(self.admin)['rows'][0]['active_sessions'],1);self.assertEqual(df.detail(self.admin,f.pk)['history'][-1]['payload_hash'],r1.payload_hash)
        self.assertRaises(ValidationError,r1.save);self.assertEqual(self.facts_hash(),self.base_record_hash)
    def test_revoke_requires_live_link_and_can_revoke_missing_target(self):
        f=self.upload();self.assertRaises(ValidationError,df.review,self.admin,f.pk,self.payload(f,'revoke'));df.review(self.admin,f.pk,self.payload(f));Record.objects.filter(business_key='EQ1').delete();r=df.review(self.admin,f.pk,self.payload(f,'revoke'));self.assertEqual(r.action,'revoke')
    def test_changed_sources_mark_stale_without_mutating_history(self):
        f=self.upload();r=df.review(self.admin,f.pk,self.payload(f));before=copy.deepcopy(r.payload);self.change('M1',value=2)
        p=df.preview(self.admin,f.pk,'T1');self.assertTrue(p['source_changed']);self.assertFalse(p['can_confirm']);r.refresh_from_db();self.assertEqual(r.payload,before)
    def test_stale_preview_rejects_fact_and_review_changes(self):
        f=self.upload();p=self.payload(f);self.change('SO1',customer_id='C2');self.assertRaises(ReviewConflict,df.review,self.admin,f.pk,p)
        a=self.payload(f);b=self.payload(f);df.review(self.admin,f.pk,a);self.assertRaises(ReviewConflict,df.review,self.admin,f.pk,b)
    def test_upload_and_review_retries_are_idempotent(self):
        rid=str(uuid.uuid4());f=self.upload(rid=rid);self.assertEqual(self.upload(rid=rid).pk,f.pk);self.assertRaises(ReviewConflict,self.upload,rid=rid,note='不同的文件来源用途说明')
        p=self.payload(f);r=df.review(self.admin,f.pk,p);self.change('M1',value=2);self.assertEqual(df.review(self.admin,f.pk,p).pk,r.pk)
        p['reason']='同一申请号不同依据';self.assertRaises(ReviewConflict,df.review,self.admin,f.pk,p)
    def test_permissions_owner_isolation_and_role_revocation(self):
        f=self.upload();self.assertRaises(DeviceFile.DoesNotExist,df.get,self.quality,f.pk)
        viewer=User.objects.create_user('viewer');self.assertRaises(PermissionDenied,self.upload,user=viewer);self.assertRaises(PermissionDenied,df.listing,viewer)
        self.admin.groups.clear();self.assertRaises(PermissionDenied,df.get,self.admin,f.pk)
    def test_integrity_checks_file_metadata_and_review_payload(self):
        f=self.upload();df.path(f).write_bytes(b'changed');self.assertRaises(ReviewConflict,df.get,self.admin,f.pk)
        f=self.upload();DeviceFile.objects.filter(pk=f.pk).update(note='tampered');self.assertRaises(ReviewConflict,df.get,self.admin,f.pk)
        f=self.upload();r=df.review(self.admin,f.pk,self.payload(f));DeviceFileReview.objects.filter(pk=r.pk).update(payload={'broken':True});self.assertRaises(ReviewConflict,df.detail,self.admin,f.pk)
    def test_audit_failure_rolls_back_archive_bytes_and_review(self):
        with patch.object(AuditEvent.objects,'create',side_effect=RuntimeError('audit failed')):
            self.assertRaises(RuntimeError,self.upload)
        self.assertEqual(DeviceFile.objects.count(),0);self.assertEqual(list(Path(self.temp.name).glob('*.bin')),[])
        f=self.upload();p=self.payload(f)
        with patch.object(AuditEvent.objects,'create',side_effect=RuntimeError('audit failed')):self.assertRaises(RuntimeError,df.review,self.admin,f.pk,p)
        self.assertEqual(DeviceFileReview.objects.count(),0)
    def test_api_csrf_auth_download_headers_and_json_evidence(self):
        locked=Client(enforce_csrf_checks=True);self.assertEqual(locked.get('/api/device-files').status_code,401);locked.force_login(self.admin);self.assertEqual(locked.post('/api/device-files/upload',{}).status_code,403)
        f=self.upload();df.review(self.admin,f.pk,self.payload(f));r=self.client.get(f'/api/device-files/{f.pk}/original');self.assertEqual(r.status_code,200);self.assertEqual(r.content,self.csv());self.assertTrue(r['Content-Disposition'].startswith('attachment'));self.assertEqual(r['X-Content-Type-Options'],'nosniff');self.assertEqual(r['Cache-Control'],'no-store')
        r=self.client.get(f'/api/device-files/{f.pk}/export');self.assertEqual(r.json()['history'][0]['payload']['target']['unit_id'],'SN001')
        self.client.force_login(self.quality);self.assertEqual(self.client.get(f'/api/device-files/{f.pk}/original').status_code,404)
    def test_listing_can_find_confirmed_sn_and_session(self):
        f=self.upload();self.assertEqual(len(df.listing(self.admin,q='T1')['rows']),1);self.assertEqual(df.listing(self.admin,unit_id='SN001')['rows'],[])
        df.review(self.admin,f.pk,self.payload(f));self.assertEqual(len(df.listing(self.admin,unit_id='SN001')['rows']),1)
        df.review(self.admin,f.pk,self.payload(f,'revoke'));self.assertEqual(df.listing(self.admin,unit_id='SN001')['rows'],[])
    def test_unknown_csv_uses_manual_mode_and_does_not_execute_formulas(self):
        raw=b'note,value\n"=HYPERLINK(\"\"x\"\")",1\n';f=self.upload(raw);self.assertEqual(f.parsed['mode'],'manual');self.assertEqual(df.contents(f),raw)
    def test_preview_and_download_do_not_change_business_facts(self):
        f=self.upload();before=self.facts_hash();df.detail(self.admin,f.pk);df.preview(self.admin,f.pk,'T1');df.contents(f);self.assertEqual(self.facts_hash(),before)
