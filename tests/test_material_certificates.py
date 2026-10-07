import copy,csv,io,tempfile,uuid
from pathlib import Path
from django.test import SimpleTestCase,override_settings
from django.core.files.uploadedfile import SimpleUploadedFile
from app import material_certificates as eng,device_files,analytics
from app.models import Record,AuditEvent
from tests.test_supply import fixture as supply_fixture
from tests.test_platform import PlatformCase

def fixture():
    d=supply_fixture();d['receipts'][0]['certificate']='CZ-001'
    d['material_certificates']=[dict(id='C',number='CZ-001',supplier_id='S1',material_id='M1',supplier_lot='SB001',issued='2026-09-04',file_id='file',file_sha256='a'*64,property_count=2,document_type='模拟声明',basis='纯演示供方内容')]
    d['material_certificate_properties']=[dict(id='P1',certificate_id='C',parameter='WIDTH',name='宽度',value=10,unit='mm',method='模拟方法',reference='模拟项目1'),dict(id='P2',certificate_id='C',parameter='VALUE',name='辅助读数',value=0,unit='演示单位',method='模拟方法',reference='模拟项目2')]
    d['receipt_certificate_links']=[dict(id='L1',receipt_id='R1',certificate_id='C',version=1,previous_id=None,lot='L2',supplier_lot='SB001',recorded='2026-09-05T10:00:00',status='登记关联',owner_id='E1',reference='模拟核对依据',note='模拟关联，不批准材料')]
    return d
def raw(d,**change):
    c=d['material_certificates'][0];out=io.StringIO();writer=csv.writer(out);writer.writerow(eng.HEADERS)
    for p in d['material_certificate_properties']:
        r=dict(certificate_no=c['number'],supplier_id=c['supplier_id'],material_id=c['material_id'],supplier_lot=c['supplier_lot'],issued=c['issued'],property_id=p['id'],**{k:str(p[k]) for k in ['parameter','value','unit','method','reference']});r.update(change);writer.writerow([r[k] for k in eng.HEADERS])
    return ('\ufeff'+out.getvalue()).encode()
def resolved(d,**change):return dict(status='verified',issues=[],observation='a'*64,file=dict(id='file',filename='演示证明.csv',kind='csv',size=500,file_hash='a'*64),parsed=eng.parse(raw(d,**change),'csv'))

class CertificateTests(SimpleTestCase):
    def setUp(self):self.d=fixture();self.file=resolved(self.d)
    def data(self):return eng.Certificates(self.d,lambda key:copy.deepcopy(self.file))
    def row(self):return self.data().index['R1']
    def second(self,**change):
        self.d['receipt_certificate_links'].append(self.d['receipt_certificate_links'][0]|dict(id='L2',version=2,previous_id='L1',recorded='2026-09-05T10:10:00')|change)
    def test_clear_grains_and_raw_status_preserved(self):
        r=self.row();self.assertEqual(r['state'],'consistent');self.assertEqual(len(r['comparison']),2);self.assertEqual(r['comparison'][1]['declared']['value'],0);self.assertEqual(r['raw_receipt_status'],'检验合格');self.assertEqual(eng.summary(self.data().rows)['objects'],2)
    def test_missing_and_future_link_do_not_look_consistent(self):
        self.assertEqual(self.data().index['R2']['state'],'missing_link');self.d['receipt_certificate_links'][0]['recorded']='2026-10-02T10:00:00';r=self.row();self.assertEqual(r['state'],'missing_link');self.assertEqual(r['future_links'],1)
    def test_latest_bad_does_not_fall_back(self):
        self.second(lot='other');r=self.row();self.assertEqual(r['state'],'record_attention');self.assertEqual(r['link_id'],'L2')
    def test_withdrawn_latest_not_replaced_by_old(self):
        self.second(status='撤销关联');r=self.row();self.assertEqual(r['state'],'withdrawn');self.assertIsNone(r['file']);self.assertEqual(len(r['history']),2)
    def test_future_correction_keeps_current_link_and_evidence(self):
        self.second(recorded='2026-10-02T10:00:00',lot='wrong');r=self.row();self.assertEqual(r['state'],'consistent');self.assertEqual(r['link_id'],'L1');self.assertEqual(r['future_links'],1);self.assertTrue(any(x['dataset']=='receipt_certificate_links' and x['key']=='L2' for x in r['sources']))
    def test_duplicate_version_or_timestamp_not_guessed(self):
        for changes in [dict(version=1),dict(recorded='2026-09-05T10:00:00')]:
            self.d=fixture();self.second(**changes);r=self.row();self.assertEqual(r['state'],'record_attention');self.assertIsNone(r['link_id'])
    def test_bad_order_chain_and_owner_block(self):
        for changes in [dict(version=3),dict(previous_id='wrong'),dict(owner_id='none'),dict(recorded='bad'),dict(recorded='2026-09-05T08:00:00'),dict(status='approved'),dict(note='')]:
            self.d=fixture();self.second(**changes);self.assertEqual(self.row()['state'],'record_attention',changes)
    def test_zero_bool_float_version_is_invalid(self):
        for value in [0,True,1.0]:
            self.d=fixture();self.d['receipt_certificate_links'][0]['version']=value;self.assertEqual(self.row()['state'],'record_attention')
    def test_unparseable_registration_does_not_throw_or_choose_old(self):
        self.second(recorded=None);r=self.row();self.assertEqual(r['state'],'record_attention');self.assertIsNone(r['link_id'])
    def test_current_correction_can_replace_historical_bad_owner(self):
        self.d['receipt_certificate_links'][0]['owner_id']='unknown';self.second(owner_id='E1');r=self.row();self.assertEqual(r['state'],'consistent');self.assertEqual(r['history'][0]['owner_id'],'unknown')
    def test_identity_number_and_supplier_lot_must_match(self):
        for key,value in [('number','wrong'),('material_id','M2'),('supplier_id','S2'),('supplier_lot','other')]:
            self.d=fixture();self.d['material_certificates'][0][key]=value;self.assertEqual(self.row()['state'],'record_attention')
    def test_no_association_by_certificate_number_alone(self):
        self.d['receipt_certificate_links']=[];self.assertEqual(self.row()['state'],'missing_link')
    def test_issued_date_cannot_be_invalid_or_later_than_arrival(self):
        for value in ['bad','2026-09-06','2026-10-02']:
            self.d=fixture();self.d['material_certificates'][0]['issued']=value;self.assertEqual(self.row()['state'],'record_attention')
    def test_property_count_and_duplicate_parameters_block(self):
        for count in [0,1,True,1001]:
            self.d=fixture();self.d['material_certificates'][0]['property_count']=count;self.assertEqual(self.row()['state'],'record_attention')
        self.d=fixture();self.d['material_certificate_properties'][1]['parameter']='WIDTH';self.assertEqual(self.row()['state'],'record_attention')
    def test_bad_values_units_methods_not_healthy(self):
        for key,value in [('value',float('nan')),('value',float('inf')),('value',True),('unit',''),('method',''),('reference','')]:
            self.d=fixture();self.d['material_certificate_properties'][0][key]=value;self.assertEqual(self.row()['state'],'record_attention')
    def test_missing_and_different_hash_not_healthy(self):
        self.d['material_certificates'][0]['file_id']=None;self.assertEqual(self.row()['state'],'file_missing')
        self.d=fixture();self.d['material_certificates'][0]['file_sha256']='';self.assertEqual(self.row()['state'],'record_attention')
        self.d=fixture();self.d['material_certificates'][0]['file_sha256']='b'*64;self.assertEqual(self.row()['state'],'file_attention')
    def test_no_access_missing_corrupt_are_distinct(self):
        for state in ['no_access','file_missing','file_attention']:
            self.file=dict(status=state,issues=['原件待核对'],observation=state);self.assertEqual(self.row()['state'],state)
    def test_non_csv_not_silently_verified(self):
        self.file['parsed']=eng.parse(b'paper','txt');self.assertEqual(self.row()['state'],'unparsed')
    def test_header_and_each_property_metadata_must_match(self):
        for key,value in [('certificate_no','other'),('material_id','M2'),('supplier_id','S2'),('supplier_lot','other'),('issued','2026-09-03'),('parameter','other'),('unit','cm'),('method','other'),('reference','other'),('value','10.1')]:
            self.file=resolved(self.d,**{key:value});self.assertEqual(self.row()['state'],'content_attention',key)
    def test_numeric_format_equivalence_is_explicit(self):
        self.d['material_certificate_properties']=self.d['material_certificate_properties'][:1];self.d['material_certificates'][0]['property_count']=1;self.file=resolved(self.d,value='10.000000');self.assertEqual(self.row()['state'],'consistent')
    def test_original_missing_extra_duplicate_lines_not_healthy(self):
        for rows in [[],self.file['parsed']['rows'][:1],self.file['parsed']['rows']*2]:
            self.file=resolved(self.d);self.file['parsed']['rows']=rows;self.assertEqual(self.row()['state'],'content_attention')
    def test_parser_unknown_duplicate_headers_and_bad_column_count(self):
        for source in [b'a,a\n1,1\n',b'a,b\n1,2\n',(','.join(eng.HEADERS)+'\n1,2\n').encode()]:self.assertEqual(eng.parse(source,'csv')['mode'],'invalid')
    def test_parser_nan_infinity_empty_and_corrupt_csv(self):
        for value in ['NaN','Infinity','']:
            self.assertEqual(eng.parse(raw(self.d,value=value),'csv')['mode'],'invalid')
        self.assertEqual(eng.parse(b'\x00','csv')['mode'],'invalid')
    def test_parser_duplicates_and_limit(self):
        text=raw(self.d).decode('utf-8-sig');head,*rows=text.splitlines();self.assertEqual(eng.parse((head+'\n'+rows[0]+'\n'+rows[0]).encode(),'csv')['mode'],'invalid');self.assertEqual(eng.parse((head+'\n'+('\n'.join(rows)+'\n')*501).encode(),'csv')['mode'],'invalid')
    def test_cohort_search_dates_and_input_preservation(self):
        old=copy.deepcopy(self.d);data=self.data();self.assertEqual(len(data.cohort({'q':'SB001'})),1);self.assertEqual(data.cohort({'received_from':'2026-10-01'}),[]);self.assertEqual(self.d,old)
    def test_global_orphans_and_purchase_quantity_unchanged(self):
        self.d['material_certificate_properties'].append(self.d['material_certificate_properties'][0]|dict(id='orphan',certificate_id='missing'));self.assertTrue(self.data().global_issues)

class CertificateAPITests(PlatformCase):
    def setUp(self):
        super().setUp();self.d=fixture();self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.override=override_settings(DEVICE_FILE_ROOT=Path(self.temp.name));self.override.enable();self.addCleanup(self.override.disable)
        f=device_files.upload(self.admin,SimpleUploadedFile('模拟证明.csv',raw(self.d)),uuid.uuid4(),'模拟来源与核对，不是正式供方证明');self.file=f
        self.d['material_certificates'][0].update(file_id=str(f.pk),file_sha256=f.file_hash)
        for ds,rows in self.d.items():
            for r in rows:self.record(ds,r)
        analytics._tables.cache_clear();self.addCleanup(analytics._tables.cache_clear);self.client.force_login(self.admin)
    def get(self,query=''):return self.client.get('/api/material-certificates'+query)
    def read(self,query=''):return self.get(query).json()
    def url(self,query=''):return '?receipt='+self.read(query)['receipt']+('&'+query.lstrip('?') if query else '')
    def test_auth_role_methods_and_no_store(self):
        self.assertEqual(self.get()['Cache-Control'],'no-store');self.assertEqual(self.client.post('/api/material-certificates').status_code,405);self.client.logout();self.assertEqual(self.get().status_code,401)
        from django.contrib.auth.models import User,Group
        for role in ['viewer','analyst']:
            user=User.objects.create_user(role,password='test-password');user.groups.add(Group.objects.get_or_create(name=role)[0]);self.client.force_login(user);self.assertEqual(self.get().status_code,403)
    def test_strict_filters(self):
        for q in ['?page=0','?page=x','?stage=unknown','?q=a&q=b','?received_from=2026-10-02','?received_from=2026-09-06&received_to=2026-09-05','?material_id=unknown','?x=a']:self.assertEqual(self.get(q).status_code,400,q)
    def test_current_owner_and_other_owner_not_leaked(self):
        d=self.read();self.assertEqual(d['summary']['consistent'],1);self.client.force_login(self.quality);d=self.read();r=next(r for r in d['rows'] if r['id']=='R1');self.assertEqual(r['state'],'no_access');self.assertIsNone(r['file']);self.assertNotIn('filename',str(r['file']))
    def test_stamp_bound_to_actor_scope_and_revision(self):
        query=self.url();self.assertEqual(self.client.get('/api/material-certificates/rows/R1'+query).status_code,200);self.assertEqual(self.client.get('/api/material-certificates/rows/R1').status_code,400);self.assertEqual(self.client.get('/api/material-certificates/rows/R1'+query+'&stage=consistent').status_code,409)
        self.client.force_login(self.quality);self.assertEqual(self.client.get('/api/material-certificates/rows/R1'+query).status_code,409)
    def test_physical_file_change_invalidates_stamp_without_fact_change(self):
        query=self.url();before=Record.objects.count();device_files.path(self.file).write_bytes(b'changed');self.assertEqual(self.client.get('/api/material-certificates/export'+query).status_code,409);self.assertEqual(Record.objects.count(),before);self.assertEqual(self.read()['summary']['file_attention'],1)
    def test_missing_bytes_distinct_and_download_paused(self):
        device_files.path(self.file).unlink();self.assertEqual(self.read()['summary']['file_missing'],1);self.assertEqual(self.client.get('/api/device-files/'+str(self.file.pk)+'/original').status_code,409)
    def test_tampered_archive_metadata_not_trusted(self):
        type(self.file).objects.filter(pk=self.file.pk).update(note='changed');self.assertEqual(self.read()['summary']['file_attention'],1)
    def test_no_stage_or_search_fallback_and_summary_scope(self):
        d=self.read('?stage=consistent');self.assertEqual(d['total'],1);self.assertEqual(d['summary']['objects'],2);self.assertEqual(self.read('?q=notfound')['summary']['objects'],0);self.assertEqual(self.client.get('/api/material-certificates/rows/R2'+self.url('?stage=consistent')).status_code,404)
    def test_evidence_and_detail_not_financial_or_other_owner(self):
        query=self.url();r=self.client.get('/api/material-certificates/rows/R1'+query).json();self.assertEqual(len(r['comparison']),2);self.assertNotIn('cents',str(r));e=self.client.get('/api/material-certificates/rows/R1/evidence'+query).json();self.assertTrue(e['can_download_original']);self.assertNotIn('values',str(e['rows']))
    def test_full_export_not_page_and_stale_does_not_audit(self):
        q=self.url('?page=100');r=self.client.get('/api/material-certificates/export'+q);self.assertEqual(r.status_code,200);self.assertEqual(r['Cache-Control'],'no-store');rows=list(csv.reader(io.StringIO(r.content.decode('utf-8-sig'))));self.assertEqual(len(rows),7);self.assertEqual(AuditEvent.objects.filter(action='material_certificate.export').count(),1);self.assertEqual(self.client.get('/api/material-certificates/export'+q+'&stage=consistent').status_code,409);self.assertEqual(AuditEvent.objects.filter(action='material_certificate.export').count(),1)
