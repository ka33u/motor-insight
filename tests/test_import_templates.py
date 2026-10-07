"""Template evidence, lifecycle, drift and full import invariants."""
import copy,io,json,time,zipfile
from unittest.mock import patch
from django.test import TestCase,SimpleTestCase,Client
from django.contrib.auth.models import User,Group
from django.core.files.uploadedfile import SimpleUploadedFile
from app import import_templates as t,import_mapping as m
from app.models import ImportTemplate,ImportTemplateVersion,ImportTemplateUse,ImportBatch,AuditEvent,Record
from app.ingestion import commit_batch
from tests.test_import_mapping import MappingWorkflow,FILE


def renamed_header(old,new):
    # Fault injection into the existing fixture; no spreadsheet authoring.
    out=io.BytesIO()
    with zipfile.ZipFile(FILE) as source,zipfile.ZipFile(out,'w') as dest:
        for i in source.infolist():
            data=source.read(i.filename)
            if i.filename.endswith('.xml'):data=data.replace(old.encode(),new.encode())
            dest.writestr(i,data)
    return out.getvalue()


class DriftContracts(SimpleTestCase):
    def test_same_headers_no_difference(self):
        self.assertEqual(t.differences([{'name':'页','headers':['甲','乙']}],[{'name':'页','headers':['甲','乙']}]),[])
    def test_added_and_removed_columns_are_blocking(self):
        d=t.differences([{'name':'页','headers':['甲','乙']}],[{'name':'页','headers':['甲','丙']}])
        self.assertEqual({x['kind'] for x in d},{'added_columns','removed_columns'});self.assertTrue(all(x['blocking'] for x in d))
    def test_reordered_headers_only_are_nonblocking(self):
        self.assertFalse(t.differences([{'name':'页','headers':['甲','乙']}],[{'name':'页','headers':['乙','甲']}])[0]['blocking'])
    def test_removed_and_added_sheets_are_blocking(self):
        self.assertEqual({x['kind'] for x in t.differences([{'name':'旧页','headers':['甲']}],[{'name':'新页','headers':['甲']}])},{'added_sheet','removed_sheet'})
    def test_workbook_order_is_nonblocking(self):
        a=[{'name':'甲页','headers':['甲']},{'name':'乙页','headers':['乙']}]
        self.assertEqual(t.differences(a,a[::-1])[0]['kind'],'reordered_sheets')
    def test_blank_column_positions_are_not_guessed_as_fields(self):
        self.assertFalse(t.differences([{'name':'页','headers':['','甲']}],[{'name':'页','headers':['甲','']}])[0]['blocking'])


class TemplateWorkflow(TestCase):
    setUp=MappingWorkflow.setUp
    upload=MappingWorkflow.upload
    preview=MappingWorkflow.preview
    assert_originals=MappingWorkflow.assert_originals
    definition={'code':'TPL-SIM-001','name':'跨部门模拟表头','department':'采购/销售/仓储','reason':'核对模拟表头与必填列'}
    def post_file(self,url,data=None,content=None,filename=None,client=None):
        fields={'file':SimpleUploadedFile(filename or FILE.name,FILE.read_bytes() if content is None else content)}
        fields.update(data or {})
        return (client or self.client).post(url,fields)
    def create(self,definition=None,mapping=None,client=None):
        d=self.preview()
        return self.post_file('/api/import-templates',{'definition':json.dumps(definition or self.definition,ensure_ascii=False),'mapping':json.dumps(mapping or self.mapping,ensure_ascii=False),'inspection_receipt':d['receipt']},client=client)
    def new(self):
        r=self.create();self.assertEqual(r.status_code,200,r.content);return r.json()
    def template_preview(self,vid,purpose='use',**kwargs):
        return self.post_file('/api/import-templates/preview',{'version_id':vid,'purpose':purpose},**kwargs)
    def activate(self,obj=None):
        obj=obj or self.new();d=self.template_preview(obj['version_id'],'activate').json();self.assertTrue(d['template_can_apply'],d)
        r=self.post_file('/api/import-templates/activate',{'template_receipt':d['template_receipt'],'definition':json.dumps({'revision':d['template']['revision'],'reason':'本地模拟映射核对后启用'})})
        self.assertEqual(r.status_code,200,r.content);return r.json()
    def retire(self,obj):
        return self.client.post('/api/import-templates/'+obj['id']+'/retire',json.dumps({'revision':obj['revision'],'reason':'模板资料需复核'}),content_type='application/json')
    def apply(self,d,client=None,**kwargs):
        return self.post_file('/api/imports',{'mapping':json.dumps(d['template_mapping'],ensure_ascii=False),'inspection_receipt':d['receipt'],'template_receipt':d['template_receipt']},client=client,**kwargs)
    def test_create_snapshot_without_business_import(self):
        before=(ImportBatch.objects.count(),Record.objects.count());o=self.new();v=ImportTemplateVersion.objects.get(pk=o['version_id'])
        self.assertEqual(v.state,'draft');self.assertEqual(v.payload['mapping'],self.mapping);self.assertEqual(m.digest(v.payload),v.content_hash)
        self.assertEqual((ImportBatch.objects.count(),Record.objects.count()),before);self.assert_originals()
    def test_same_create_idempotent(self):
        a=self.new();b=self.new();self.assertEqual(a['version_id'],b['version_id']);self.assertTrue(b['repeated']);self.assertEqual(ImportTemplate.objects.count(),1);self.assertEqual(AuditEvent.objects.filter(action='import_template.draft').count(),1)
    def test_same_existing_payload_reuses_immutable_version(self):
        a=self.new();r=self.create({'template_id':a['template']['id'],'revision':1,'reason':'重复核对'});self.assertEqual(r.status_code,200);self.assertTrue(r.json()['repeated']);self.assertEqual(ImportTemplateVersion.objects.count(),1)
    def test_wrong_existing_revision_rejected(self):
        a=self.new();self.assertEqual(self.create({'template_id':a['template']['id'],'revision':0,'reason':'过期'}).status_code,409)
    def test_same_code_cannot_rename_existing_template(self):
        self.new();d=dict(self.definition,name='另一个模板');self.assertEqual(self.create(d).status_code,409)
    def test_invalid_code_or_empty_metadata(self):
        for key,val in [('code','中文'),('name',''),('department',''),('reason','')]:
            d=dict(self.definition);d[key]=val;self.assertEqual(self.create(d).status_code,400)
        self.assertEqual(ImportTemplate.objects.count(),0)
    def test_unknown_definition_parameter_rejected(self):
        self.assertEqual(self.create(dict(self.definition,approved=True)).status_code,400)
    def test_changed_mapping_receipt_blocks_draft(self):
        changed=copy.deepcopy(self.mapping);changed['导入说明']={'skip':True};changed['字段字典']={'skip':True};changed['采购部_供方清单']['ignore'].append('供方资格登记');changed['采购部_供方清单']['fields'].pop('供方资格登记')
        self.assertEqual(self.create(mapping=changed).status_code,409);self.assertEqual(ImportTemplate.objects.count(),0)
    def test_draft_cannot_be_used(self):
        a=self.new();r=self.template_preview(a['version_id']);self.assertEqual(r.status_code,200);self.assertFalse(r.json()['template_can_apply']);self.assertNotIn('template_receipt',r.json())
    def test_activate_and_use_are_different_purposes(self):
        a=self.new();d=self.template_preview(a['version_id'],'activate').json();r=self.apply(d);self.assertEqual(r.status_code,409);self.assertEqual(ImportBatch.objects.count(),1)
    def test_preview_read_only(self):
        a=self.activate();before=(ImportTemplate.objects.count(),ImportTemplateVersion.objects.count(),ImportBatch.objects.count(),AuditEvent.objects.count())
        self.template_preview(a['versions'][0]['id']);self.assertEqual(before,(ImportTemplate.objects.count(),ImportTemplateVersion.objects.count(),ImportBatch.objects.count(),AuditEvent.objects.count()))
    def test_active_template_stages_full_source_and_records_provenance(self):
        a=self.activate();d=self.template_preview(a['versions'][0]['id']).json();r=self.apply(d);self.assertEqual(r.status_code,200,r.content)
        b=ImportBatch.objects.get(pk=r.json()['id']);self.assertEqual(b.summary['duplicate'],15);self.assertEqual(b.summary['conflict'],1);self.assertEqual(b.summary['invalid'],1)
        use=ImportTemplateUse.objects.get();self.assertEqual(use.version_id,a['versions'][0]['id']);self.assertEqual(use.evidence['review_state'],'headers_only');self.assertFalse(use.evidence['business_approval'])
        self.assertEqual(r.json()['template_uses'][0]['version'],1);commit_batch(b.pk);self.assert_originals()
    def test_replay_does_not_duplicate_use_or_formal_records(self):
        a=self.activate();d=self.template_preview(a['versions'][0]['id']).json();r=self.apply(d);commit_batch(r.json()['id']);r2=self.apply(d)
        self.assertTrue(r2.json()['repeated']);self.assertEqual(ImportTemplateUse.objects.count(),1);self.assert_originals()
    def test_retirement_invalidates_use_receipt_before_archive(self):
        a=self.activate();d=self.template_preview(a['versions'][0]['id']).json();self.assertEqual(self.retire(a).status_code,200)
        self.assertEqual(self.apply(d).status_code,409);self.assertEqual(ImportBatch.objects.count(),1);self.assertFalse(ImportTemplateUse.objects.exists())
    def test_retired_version_can_be_freshly_reviewed_and_reactivated(self):
        a=self.activate();v=ImportTemplateVersion.objects.get();original=copy.deepcopy(v.payload);self.retire(a)
        a=self.activate({'version_id':v.pk});v.refresh_from_db();self.assertEqual(v.payload,original);self.assertEqual(a['current_version'],1)
    def test_stale_lifecycle_revision_rejected(self):
        a=self.activate();old=dict(a,revision=1);self.assertEqual(self.retire(old).status_code,409)
    def test_renamed_header_is_explicit_blocking_drift(self):
        a=self.activate();d=self.template_preview(a['versions'][0]['id'],content=renamed_header('供方编号','供方编码变更')).json()
        self.assertFalse(d['template_can_apply']);self.assertEqual({x['kind'] for x in d['drift']},{'added_columns','removed_columns'});self.assertNotIn('template_receipt',d)
    def test_renamed_sheet_is_explicit_blocking_drift(self):
        a=self.activate();d=self.template_preview(a['versions'][0]['id'],content=renamed_header('采购部_供方清单','采购部_供方清单新版')).json()
        self.assertFalse(d['template_can_apply']);self.assertEqual({x['kind'] for x in d['drift']},{'added_sheet','removed_sheet'})
    def test_payload_tamper_rejected(self):
        a=self.activate();v=ImportTemplateVersion.objects.get();v.payload['mapping']['个人备注_不导入']={};v.save(update_fields=['payload'])
        self.assertEqual(self.template_preview(v.pk).status_code,409)
    def test_changed_schema_or_rules_requires_new_version(self):
        a=self.activate();vid=a['versions'][0]['id']
        with patch('app.import_mapping.rules_hash',return_value='changed'):
            d=self.template_preview(vid).json();self.assertFalse(d['template_can_apply']);self.assertFalse(d['rules_current'])
    def test_changed_content_or_filename_blocks_receipt(self):
        a=self.activate();d=self.template_preview(a['versions'][0]['id']).json()
        for kwargs in [{'content':FILE.read_bytes()+b'changed'},{'filename':'changed.xlsx'}]:self.assertEqual(self.apply(d,**kwargs).status_code,409)
        self.assertEqual(ImportBatch.objects.count(),1)
    def test_changed_schema_after_preview_blocks_stage(self):
        a=self.activate();d=self.template_preview(a['versions'][0]['id']).json()
        with patch('app.import_mapping.rules_hash',return_value='changed'):self.assertEqual(self.apply(d).status_code,409)
    def test_expired_and_tampered_receipts_rejected(self):
        a=self.activate();d=self.template_preview(a['versions'][0]['id']).json()
        changed=dict(d,template_receipt=d['template_receipt']+'x');self.assertEqual(self.apply(changed).status_code,409)
        with patch('django.core.signing.time.time',return_value=time.time()+901):self.assertEqual(self.apply(d).status_code,409)
    def test_missing_mapping_receipt_cannot_use_template(self):
        a=self.activate();d=self.template_preview(a['versions'][0]['id']).json();self.assertEqual(self.apply(dict(d,receipt='')).status_code,400)
    def test_other_admin_reads_and_uses_but_cannot_manage(self):
        a=self.activate();other=User.objects.create_user('template_other');other.groups.add(Group.objects.get(name='admin'));c=Client();c.force_login(other)
        self.assertEqual(c.get('/api/import-templates').status_code,200)
        d=self.template_preview(a['versions'][0]['id'],client=c).json();self.assertTrue(d['template_can_apply']);self.assertEqual(self.apply(d,client=c).status_code,200)
        self.assertEqual(self.template_preview(a['versions'][0]['id'],'activate',client=c).status_code,403)
        self.assertEqual(c.post('/api/import-templates/'+a['id']+'/retire',json.dumps({'revision':a['revision'],'reason':'他人'}),content_type='application/json').status_code,403)
    def test_another_account_cannot_replay_receipt(self):
        a=self.activate();d=self.template_preview(a['versions'][0]['id']).json();other=User.objects.create_user('other_admin');other.groups.add(Group.objects.get(name='admin'));c=Client();c.force_login(other)
        self.assertEqual(self.apply(d,client=c).status_code,409)
    def test_auth_and_role_and_method_guards(self):
        self.assertEqual(Client().get('/api/import-templates').status_code,401);c=Client();c.force_login(self.viewer);self.assertEqual(c.get('/api/import-templates').status_code,403)
        self.assertEqual(self.client.get('/api/import-templates/preview').status_code,405)
    def test_csrf_enforced(self):
        c=Client(enforce_csrf_checks=True);c.force_login(self.admin);self.assertEqual(self.post_file('/api/import-templates',client=c).status_code,403)
    def test_new_version_preserves_previous_and_retires_it_on_activation(self):
        a=self.activate();old=ImportTemplateVersion.objects.get();saved=copy.deepcopy(old.payload)
        changed=copy.deepcopy(self.mapping);changed['采购部_供方清单']['fields']['供方编号']='供应商编码'
        d=self.upload(mapping=changed).json();r=self.post_file('/api/import-templates',{'definition':json.dumps({'template_id':a['id'],'revision':a['revision'],'reason':'显式采用当前中文字段标签'}),'mapping':json.dumps(changed,ensure_ascii=False),'inspection_receipt':d['receipt']})
        self.assertEqual(r.status_code,200,r.content);b=self.activate(r.json());old.refresh_from_db();self.assertEqual(old.payload,saved);self.assertEqual(old.state,'retired');self.assertEqual(b['current_version'],2)
    def test_recheck_preserves_historical_template_without_reactivating_it(self):
        a=self.activate();d=self.template_preview(a['versions'][0]['id']).json();r=self.apply(d);commit_batch(r.json()['id']);self.retire(a)
        recheck=self.client.post('/api/imports/'+r.json()['id']+'/recheck',json.dumps({}),content_type='application/json')
        self.assertEqual(recheck.status_code,200,recheck.content);history=recheck.json()['template_uses'][0]
        self.assertEqual(history['version'],1);self.assertEqual(history['evidence']['kind'],'historical_template_reference');self.assertFalse(history['evidence']['fresh_template_activation'])
        self.assertEqual(ImportTemplate.objects.get().current_version,0);self.assert_originals()
    def test_new_draft_invalidates_old_activation_preview(self):
        a=self.new();d=self.template_preview(a['version_id'],'activate').json();changed=copy.deepcopy(self.mapping);changed['采购部_供方清单']['fields']['供方编号']='供应商编码'
        p=self.upload(mapping=changed).json();r=self.post_file('/api/import-templates',{'definition':json.dumps({'template_id':a['template']['id'],'revision':1,'reason':'调整映射目标名称'}),'mapping':json.dumps(changed,ensure_ascii=False),'inspection_receipt':p['receipt']});self.assertEqual(r.status_code,200)
        r=self.post_file('/api/import-templates/activate',{'template_receipt':d['template_receipt'],'definition':json.dumps({'revision':1,'reason':'旧预览'})});self.assertEqual(r.status_code,409)
    def test_activation_does_not_certify_business_records(self):
        self.activate();event=AuditEvent.objects.get(action='import_template.activate');self.assertFalse(event.detail['business_approval']);self.assertFalse(event.detail['business_facts_changed']);self.assertEqual(event.detail['header_review']['purpose'],'activate');self.assert_originals()
    def test_invalid_preview_purpose_and_unknown_version(self):
        a=self.new();self.assertEqual(self.template_preview(a['version_id'],'arbitrary').status_code,400);self.assertEqual(self.template_preview(987654321).status_code,404)
    def test_lifecycle_history_is_paginated_and_scoped_to_template(self):
        a=self.activate();self.retire(a)
        for i in range(31):AuditEvent.objects.create(action='import_template.use',actor=self.admin.username,object_type='ImportTemplate',object_id=a['id'],detail={'number':1,'batch_id':str(i)})
        AuditEvent.objects.create(action='import_template.use',object_type='ImportTemplate',object_id='other-template',detail={})
        r=self.client.get('/api/import-templates/'+a['id']).json();self.assertEqual(r['history']['total'],34);self.assertEqual(len(r['history']['rows']),30)
        r=self.client.get('/api/import-templates/'+a['id']+'?page=2').json();self.assertEqual(len(r['history']['rows']),4)
