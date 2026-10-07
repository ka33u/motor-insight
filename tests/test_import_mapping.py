import copy,json,tempfile,time
from pathlib import Path
from unittest.mock import patch
from django.test import SimpleTestCase,TestCase,Client
from django.contrib.auth.models import User,Group
from django.core.files.uploadedfile import SimpleUploadedFile
from app import import_mapping as m
from app.ingestion import stage_file,commit_batch,fingerprint
from app.models import Record,ImportRow,ImportBatch,AuditEvent
from app.schema import SCHEMAS

ROOT=Path(__file__).resolve().parents[1]
FILE=ROOT/'outputs/01a0f580-2480-7820-bc97-8ca293421c39/32_字段映射演练_模拟.xlsx'
EXPECTED=json.loads((ROOT/'tests/fixtures/import_mapping_exercise_expected.json').read_text())


class MappingColumns(SimpleTestCase):
    def setUp(self):self.s=SCHEMAS['suppliers']
    def test_all_standard_internal_headers(self):
        for s in SCHEMAS.values():
            columns,extra=m.columns_for(s,[f['name'] for f in s['fields']],{})
            self.assertEqual(set(columns),{f['name'] for f in s['fields']});self.assertEqual(extra,[])
    def test_all_standard_chinese_headers(self):
        for s in SCHEMAS.values():
            columns,extra=m.columns_for(s,[f['label'] for f in s['fields']],{})
            self.assertEqual(set(columns),{f['name'] for f in s['fields']});self.assertEqual(extra,[])
    def test_two_aliases_must_not_overwrite_id(self):
        with self.assertRaisesRegex(ValueError,'多列'):m.columns_for(self.s,['id','供应商编码'],{})
    def test_two_explicit_columns_must_not_overwrite_id(self):
        with self.assertRaisesRegex(ValueError,'多列'):m.columns_for(self.s,['甲','乙'],{'fields':{'甲':'id','乙':'id'}})
    def test_implicit_alias_and_explicit_column_cannot_collide(self):
        with self.assertRaisesRegex(ValueError,'多列'):m.columns_for(self.s,['id','甲'],{'fields':{'甲':'id'}})
    def test_explicit_ignored_alias_resolves_ambiguity(self):
        columns,extra=m.columns_for(self.s,['id','供应商编码'],{'ignore':['id']})
        self.assertEqual(columns,{'id':1});self.assertEqual(extra,[])
    def test_unknown_target_rejected(self):
        with self.assertRaisesRegex(ValueError,'目标字段'):m.columns_for(self.s,['甲'],{'fields':{'甲':'not_a_field'}})
    def test_nonexistent_source_rejected(self):
        for conf in [{'fields':{'不存在':'id'}},{'ignore':['不存在']}]:
            with self.assertRaisesRegex(ValueError,'不存在'):m.columns_for(self.s,['id'],conf)
    def test_unknown_column_reported(self):
        self.assertEqual(m.columns_for(self.s,['id','随手备注'],{})[1],['随手备注'])
    def test_chinese_target_label_legacy_mapping_supported(self):
        self.assertEqual(m.columns_for(self.s,['甲'],{'fields':{'甲':'供应商编码'}})[0],{'id':0})
    def test_duplicate_json_key_rejected_at_any_depth(self):
        for value in ['{"页":{},"页":{}}','{"页":{"fields":{"甲":"id","甲":"name"}}}']:
            with self.assertRaisesRegex(ValueError,'重复'):m.parse_mapping(value)
    def test_conf_shape_and_skip_strict(self):
        for value in [[],{'页':[]},{'页':{'unknown':1}},{'页':{'skip':'true'}},{'页':{'skip':False}},{'页':{'skip':True,'dataset':'suppliers'}},{'页':{'dataset':'bi_units'}}]:
            with self.assertRaises(ValueError):m.validate_shape(value)
    def test_fields_and_ignored_types_strict(self):
        for value in [{'fields':[]},{'fields':{'甲':1}},{'ignore':'甲'},{'ignore':['甲','甲']},{'fields':{'甲':'id'},'ignore':['甲']}]:
            with self.assertRaises(ValueError):m.validate_shape({'页':value})
    def test_mapping_order_does_not_change_digest(self):
        self.assertEqual(m.digest({'a':1,'b':2}),m.digest({'b':2,'a':1}))


class MappingWorkflow(TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.settings_context=self.settings(BASE_DIR=Path(self.temp.name));self.settings_context.enable();self.addCleanup(self.settings_context.disable)
        self.admin=User.objects.create_user('mapping_admin',password='MappingTest!2026');self.admin.groups.add(Group.objects.create(name='admin'))
        self.viewer=User.objects.create_user('mapping_viewer',password='MappingTest!2026');self.viewer.groups.add(Group.objects.create(name='viewer'))
        self.client.force_login(self.admin)
        self.mapping=copy.deepcopy(EXPECTED['mapping'])
        self.base=ImportBatch.objects.create(filename='fixture',file_hash='fixture',file_path='none',status='committed')
        seed={(ds,row['id']):row for ds,rows in EXPECTED['canonical'].items() for row in rows}
        for r in EXPECTED['references']:seed.setdefault((r['dataset'],r['values']['id']),r['values'])
        for (ds,key),value in seed.items():
            row=ImportRow.objects.create(batch=self.base,sheet=ds,row_number=2,dataset=ds,business_key=key,raw=value,normalized=value,record_hash=fingerprint(value),status='committed')
            Record.objects.create(dataset=ds,business_key=key,values=value,record_hash=row.record_hash,source_row=row)
        self.initial={r.pk:(r.values,r.source_row_id,r.revision,r.record_hash) for r in Record.objects.all()}
    def upload(self,url='/api/imports/mapping/preview',mapping=None,receipt=None,data=None,filename=None,client=None):
        payload={'file':SimpleUploadedFile(filename or FILE.name,FILE.read_bytes() if data is None else data,content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')}
        if mapping is not None:payload['mapping']=json.dumps(mapping,ensure_ascii=False)
        if receipt is not None:payload['inspection_receipt']=receipt
        return (client or self.client).post(url,payload)
    def preview(self):
        response=self.upload(mapping=self.mapping);self.assertEqual(response.status_code,200,response.content);self.assertTrue(response.json()['can_stage']);return response.json()
    def assert_originals(self):
        self.assertEqual({r.pk:(r.values,r.source_row_id,r.revision,r.record_hash) for r in Record.objects.all()},self.initial)
    def test_inspect_is_source_backed_read_only(self):
        before=(ImportBatch.objects.count(),ImportRow.objects.count(),AuditEvent.objects.count())
        response=self.upload('/api/imports/inspect');self.assertEqual(response.status_code,200,response.content)
        d=response.json();self.assertEqual(len(d['sheets']),6);self.assertEqual(response['Cache-Control'],'no-store');self.assertFalse(d['can_stage']);self.assertNotIn('receipt',d)
        self.assertEqual(next(s for s in d['sheets'] if s['name']=='采购部_供方清单')['samples'][0]['values'][0],'GY00001')
        self.assertEqual(before,(ImportBatch.objects.count(),ImportRow.objects.count(),AuditEvent.objects.count()));self.assert_originals()
    def test_preview_checks_columns_not_whole_rows(self):
        d=self.preview();self.assertEqual(d['receipt_valid_seconds'],900);self.assertFalse(any(s['sample_issues'] for s in d['sheets']));self.assertEqual(ImportBatch.objects.count(),1)
        response=self.upload('/api/imports',self.mapping,d['receipt']);self.assertEqual(response.status_code,200,response.content)
        self.assertEqual({k:response.json()['summary'][k] for k in ['duplicate','conflict','invalid']},EXPECTED['expected_status']);self.assert_originals()
    def test_native_types_and_normalized_values_preserved(self):
        d=self.preview();result=self.upload('/api/imports',self.mapping,d['receipt']).json();batch=ImportBatch.objects.get(pk=result['id'])
        expected={(ds,r['id']):r for ds,rows in EXPECTED['canonical'].items() for r in rows}
        for row in batch.rows.filter(status='duplicate'):self.assertEqual(row.normalized,expected[(row.dataset,row.business_key)])
        invalid=batch.rows.get(status='invalid');self.assertEqual(invalid.raw['往来客户号'],19);self.assertTrue(any('文本' in i['message'] for i in invalid.issues))
        self.assertEqual(batch.rows.get(status='conflict').normalized['lead_days'],EXPECTED['canonical']['suppliers'][0]['lead_days']+1)
    def test_mapping_review_audit_is_not_business_approval(self):
        d=self.preview();r=self.upload('/api/imports',self.mapping,d['receipt'])
        audit=AuditEvent.objects.get(action='import.mapping_verified');self.assertEqual(audit.object_id,r.json()['id'])
        self.assertEqual(audit.detail['schema_hash'],d['schema_hash']);self.assertEqual(audit.detail['rules_hash'],d['rules_hash'])
        self.assertEqual(audit.detail['sha256'],d['sha256']);self.assertEqual(audit.detail['mapping_hash'],m.digest(self.mapping))
        self.assertFalse(audit.detail['business_approval']);self.assertEqual(audit.detail['review_state'],'headers_only')
        self.assertNotIn('receipt',audit.detail)
    def test_commit_does_not_approve_conflict_and_replay_idempotent(self):
        d=self.preview();response=self.upload('/api/imports',self.mapping,d['receipt']);bid=response.json()['id']
        commit_batch(bid);batch=ImportBatch.objects.get(pk=bid);self.assertEqual(batch.status,'partial');self.assertEqual(batch.summary['skipped_sheets'],['个人备注_不导入']);self.assert_originals()
        replay=self.upload('/api/imports',self.mapping,d['receipt']);self.assertTrue(replay.json()['repeated']);self.assertEqual(replay.json()['id'],bid);self.assertEqual(ImportBatch.objects.count(),2)
    def test_legacy_direct_upload_retains_mapping(self):
        response=self.upload('/api/imports',self.mapping);self.assertEqual(response.status_code,200,response.content);self.assertEqual(ImportBatch.objects.get(pk=response.json()['id']).mapping,self.mapping)
    def test_mandatory_column_missing_blocks_receipt(self):
        self.mapping['采购部_供方清单']['fields'].pop('供方编号');self.mapping['采购部_供方清单']['ignore'].append('供方编号')
        response=self.upload(mapping=self.mapping);self.assertEqual(response.status_code,200);self.assertFalse(response.json()['can_stage']);self.assertNotIn('receipt',response.json());self.assertTrue(any('必填' in x for x in response.json()['issues']))
    def test_unselected_sheet_blocks_receipt(self):
        self.mapping.pop('个人备注_不导入');d=self.upload(mapping=self.mapping).json();self.assertFalse(d['can_stage']);self.assertTrue(any('明确' in x for x in d['issues']))
    def test_unmatched_column_needs_explicit_ignore(self):
        self.mapping['采购部_供方清单'].pop('ignore');d=self.upload(mapping=self.mapping).json();self.assertFalse(d['can_stage']);self.assertTrue(any('未明确忽略' in x for x in d['issues']))
    def test_all_skipped_has_no_receipt(self):
        self.mapping={k:{'skip':True} for k in self.mapping};d=self.upload(mapping=self.mapping).json();self.assertFalse(d['can_stage']);self.assertIn('至少选择一张业务表',d['issues'])
    def test_mapping_nonexistent_sheet_is_400(self):
        self.mapping['不存在']={'skip':True};response=self.upload(mapping=self.mapping);self.assertEqual(response.status_code,400);self.assertEqual(ImportBatch.objects.count(),1)
    def test_cross_account_receipt_rejected_before_archive(self):
        d=self.preview();other=User.objects.create_user('mapping_other');other.groups.add(Group.objects.get(name='admin'));self.client.force_login(other)
        r=self.upload('/api/imports',self.mapping,d['receipt']);self.assertEqual(r.status_code,409);self.assertEqual(ImportBatch.objects.count(),1)
    def test_changed_mapping_rejected_before_archive(self):
        d=self.preview();self.mapping['采购部_供方清单']['fields']['供方全称']='category'
        response=self.upload('/api/imports',self.mapping,d['receipt']);self.assertEqual(response.status_code,409);self.assertEqual(ImportBatch.objects.count(),1)
    def test_changed_bytes_rejected_before_archive(self):
        d=self.preview();r=self.upload('/api/imports',self.mapping,d['receipt'],data=FILE.read_bytes()+b'changed');self.assertEqual(r.status_code,409);self.assertEqual(ImportBatch.objects.count(),1)
    def test_changed_filename_rejected(self):
        d=self.preview();r=self.upload('/api/imports',self.mapping,d['receipt'],filename='another.xlsx');self.assertEqual(r.status_code,409)
    def test_schema_drift_requires_new_preview(self):
        d=self.preview();changed=copy.deepcopy(SCHEMAS);changed['suppliers']['version']+=1
        with patch.object(m,'SCHEMAS',changed):r=self.upload('/api/imports',self.mapping,d['receipt'])
        self.assertEqual(r.status_code,409);self.assertEqual(ImportBatch.objects.count(),1)
    def test_expiry_at_boundary(self):
        with patch('django.core.signing.time.time',return_value=1700000000):d=self.preview()
        with patch('django.core.signing.time.time',return_value=1700000901):r=self.upload('/api/imports',self.mapping,d['receipt'])
        self.assertEqual(r.status_code,409)
    def test_tampered_signature_rejected(self):
        d=self.preview();r=self.upload('/api/imports',self.mapping,d['receipt']+'x');self.assertEqual(r.status_code,409)
    def test_changed_conversion_rules_require_new_preview(self):
        d=self.preview()
        with patch.object(m,'rules_hash',return_value='changed'):r=self.upload('/api/imports',self.mapping,d['receipt'])
        self.assertEqual(r.status_code,409);self.assertEqual(ImportBatch.objects.count(),1)
    def test_non_admin_denied_for_both_reading_and_staging(self):
        self.client.force_login(self.viewer)
        for url in ['/api/imports/inspect','/api/imports/mapping/preview','/api/imports']:
            self.assertEqual(self.upload(url,self.mapping).status_code,403)
        self.assertEqual(ImportBatch.objects.count(),1)
    def test_auth_and_method(self):
        self.assertEqual(self.client.get('/api/imports/inspect').status_code,405);self.client.logout();self.assertEqual(self.upload('/api/imports/inspect').status_code,401)
    def test_csrf_still_required(self):
        client=Client(enforce_csrf_checks=True);client.force_login(self.admin)
        self.assertEqual(self.upload('/api/imports/mapping/preview',self.mapping,client=client).status_code,403)
    def test_wrong_container_or_extension(self):
        for data,filename in [(b'not an xlsx','bad.xlsx'),(FILE.read_bytes(),'bad.xls')]:
            self.assertEqual(self.upload('/api/imports/inspect',data=data,filename=filename).status_code,400)
    def test_different_mapping_not_silently_reused(self):
        a=self.upload('/api/imports',self.mapping).json();commit_batch(a['id'])
        self.mapping['个人备注_不导入']={'dataset':'departments','fields':{'便签号':'id','私人演练便签':'name'}}
        b=self.upload('/api/imports',self.mapping).json();self.assertFalse(b['repeated']);self.assertNotEqual(a['id'],b['id']);self.assert_originals()
