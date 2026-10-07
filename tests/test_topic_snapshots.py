import copy,csv,io,json,uuid
from unittest.mock import patch
from django.contrib.auth.models import User,Group
from django.core.exceptions import ValidationError,PermissionDenied
from django.test import Client
from app import topic_snapshots as ss,topic_workspace as ws
from app.models import Topic,TopicSnapshot,AnalysisModel,Record,AuditEvent
from app.import_review import ReviewConflict
from tests.test_platform import PlatformCase

CONF={'scope':{'from':'2026-09-25','to':'2026-09-25'},'reference_scope':{'from':'2026-09-24','to':'2026-09-24'},'primary_label':'当前日','reference_label':'参照日'}

class TopicSnapshotTests(PlatformCase):
    def setUp(self):
        super().setUp();self.client.force_login(self.admin)
        self.model=AnalysisModel.objects.create(name='能耗',dataset='energy',definition={'dimension':'workshop','metrics':[{'agg':'sum','field':'kwh'}],'chart':'bar'},owner='admin',is_public=True)
        self.topic=Topic.objects.create(name='能耗专题',layout=[{'model_id':self.model.pk,'span':2}],owner='admin',is_public=True)
        for key,shop,day,qty in [('E1','绕组','24',10),('E2','绕组','25',20),('E3','组装','25',None)]:
            self.record('energy',{'id':key,'workshop':shop,'started':f'2026-09-{day}T08:00:00','ended':f'2026-09-{day}T12:00:00','kwh':qty,'tariff_cents':100})
    def payload(self,user=None,conf=None):
        user=user or self.admin;ctx=ws.context(user,self.topic.pk)
        run=ws.run(user,self.topic.pk,{'context_token':ctx['context_token'],'config':conf or CONF})
        return {'request_id':str(uuid.uuid4()),'context_token':ctx['context_token'],'facts_token':run['facts_token'],'config':copy.deepcopy(conf or CONF),'name':'能耗周会快照','note':'保留本次周会模拟分析证据'}
    def save(self,user=None):return ss.create(user or self.admin,self.topic.pk,self.payload(user))
    def ev(self,s,**extra):return ss.evidence(self.admin,self.topic.pk,s.pk,{'slot':0,'side':'primary','group':None,'page':1,**extra})
    def source(self,s,**extra):return ss.source_evidence(self.admin,self.topic.pk,s.pk,{'slot':0,'side':'primary','object_id':'E2','page':1,**extra})
    def test_frozen_result_and_source_remain_after_current_record_correction(self):
        s=self.save();before=copy.deepcopy(s.payload);r=Record.objects.get(business_key='E2');r.values['kwh']=99;r.revision+=1;r.save()
        r.source_row.normalized['kwh']=123;r.source_row.save()
        d=ss.detail(self.admin,self.topic.pk,s.pk)
        self.assertEqual(next(x['m0'] for x in d['result']['cards'][0]['primary']['rows'] if x['dimension']=='绕组'),20)
        self.assertEqual(self.source(s)['rows'][0]['values']['kwh'],20)
        self.assertEqual(self.source(s)['rows'][0]['revision'],1)
        s.refresh_from_db();self.assertEqual(s.payload,before);self.assertEqual(s.payload_hash,ws.digest(before))
    def test_source_manifest_preserves_excel_identity_and_hash(self):
        s=self.save();source=self.source(s)['rows'][0]
        self.assertEqual((source['filename'],source['sheet'],source['row']),('unit-test.xlsx','energy',2));self.assertEqual(source['file_hash'],'t')
        self.assertEqual(source['batch_id'],str(self.batch.pk));self.assertIn('record_hash',source)
    def test_idempotent_retry_returns_old_snapshot_even_after_facts_change(self):
        body=self.payload();s=ss.create(self.admin,self.topic.pk,body);r=Record.objects.get(business_key='E2');r.values['kwh']=88;r.save()
        self.assertEqual(ss.create(self.admin,self.topic.pk,body).pk,s.pk);self.assertEqual(TopicSnapshot.objects.count(),1);self.assertEqual(AuditEvent.objects.filter(action='topic_snapshot.create').count(),1)
        with self.assertRaises(ReviewConflict):ss.create(self.admin,self.topic.pk,{**body,'name':'重复号修改内容'})
        with self.assertRaises(ReviewConflict):ss.create(self.quality,self.topic.pk,body)
    def test_owner_isolation_including_admin(self):
        s=self.save(self.quality)
        self.assertEqual(ss.listing(self.admin,self.topic.pk)['total'],0)
        self.assertEqual(self.client.get(f'/api/topics/{self.topic.pk}/snapshots/{s.pk}').status_code,404)
        self.assertEqual(self.client.get(f'/api/topics/{self.topic.pk}/snapshots/{s.pk}/export?format=json').status_code,404)
    def test_role_revocation_blocks_old_sensitive_fields(self):
        s=self.save();self.admin.groups.clear();self.admin.groups.add(Group.objects.get(name='quality'))
        with self.assertRaises(PermissionDenied):ss.get(self.admin,self.topic.pk,s.pk)
        item=ss.listing(self.admin,self.topic.pk)['rows'][0];self.assertFalse(item['available']);self.assertNotIn('name',item)
        self.assertEqual(self.client.get(f'/api/topics/{self.topic.pk}/snapshots/{s.pk}/export').status_code,403)
    def test_quality_snapshot_never_captures_financial_fields(self):
        s=self.save(self.quality);text=json.dumps(s.payload)
        self.assertNotIn('tariff_cents',text);self.assertEqual(ss.detail(self.quality,self.topic.pk,s.pk)['source_count'],3)
    def test_private_parent_or_model_blocks_read_and_export(self):
        s=self.save(self.quality);self.topic.is_public=False;self.topic.save()
        with self.assertRaises(Topic.DoesNotExist):ss.get(self.quality,self.topic.pk,s.pk)
        self.topic.is_public=True;self.topic.save();self.model.is_public=False;self.model.save()
        with self.assertRaises(PermissionDenied):ss.get(self.quality,self.topic.pk,s.pk)
    def test_changed_definition_leaves_frozen_readable_but_comparison_blocked(self):
        s=self.save();self.model.definition['metrics'][0]['agg']='avg';self.model.version+=1;self.model.save()
        self.assertEqual(ss.detail(self.admin,self.topic.pk,s.pk)['result']['cards'][0]['model']['version'],1)
        result=ss.compare_current(self.admin,self.topic.pk,s.pk);self.assertTrue(result['blocked']);self.assertNotIn('cards',result)
    def test_corruption_and_overwriting_are_rejected(self):
        s=self.save()
        with self.assertRaises(ValidationError):s.save()
        corrupted=copy.deepcopy(s.payload);corrupted['result']['cards'][0]['primary']['rows'][0]['m0']=123456
        TopicSnapshot.objects.filter(pk=s.pk).update(payload=corrupted)
        with self.assertRaises(ReviewConflict):ss.get(self.admin,self.topic.pk,s.pk)
        self.assertEqual(self.client.get(f'/api/topics/{self.topic.pk}/snapshots/{s.pk}/export').status_code,409)
    def test_stale_page_or_model_cannot_save_recomputed_different_result(self):
        body=self.payload();r=Record.objects.get(business_key='E2');r.values['kwh']=77;r.save()
        with self.assertRaises(ReviewConflict):ss.create(self.admin,self.topic.pk,body)
        body=self.payload();self.model.version+=1;self.model.save()
        with self.assertRaises(ReviewConflict):ss.create(self.admin,self.topic.pk,body)
        self.assertFalse(TopicSnapshot.objects.exists())
    def test_audit_failure_rolls_back_snapshot(self):
        with patch('app.topic_snapshots.AuditEvent.objects.create',side_effect=RuntimeError('storage failed')):
            with self.assertRaises(RuntimeError):self.save()
        self.assertFalse(TopicSnapshot.objects.exists())
    def test_client_cannot_supply_frozen_values_or_bypass_validation(self):
        body=self.payload()
        for change in [{'payload':{}},{'name':''},{'note':'短'},{'request_id':'bad-id'}]:
            self.assertEqual(self.post(f'/api/topics/{self.topic.pk}/snapshots',{**body,**change}).status_code,400)
        self.assertFalse(TopicSnapshot.objects.exists())
    def test_csrf_auth_and_immutable_api(self):
        body=self.payload();secure=Client(enforce_csrf_checks=True);secure.force_login(self.admin)
        self.assertEqual(secure.post(f'/api/topics/{self.topic.pk}/snapshots',json.dumps(body),content_type='application/json').status_code,403)
        s=self.save();self.assertEqual(self.post(f'/api/topics/{self.topic.pk}/snapshots/{s.pk}',{'name':'覆盖'}).status_code,405)
        self.client.logout();self.assertEqual(self.client.get(f'/api/topics/{self.topic.pk}/snapshots/{s.pk}').status_code,401)
    def test_current_comparison_reports_corrections_additions_and_removed_groups(self):
        s=self.save();r=Record.objects.get(business_key='E2');r.values['kwh']=30;r.revision+=1;r.save()
        Record.objects.get(business_key='E3').delete();self.record('energy',{'id':'E4','workshop':'冲片','started':'2026-09-25T09:00:00','ended':'2026-09-25T10:00:00','kwh':5,'tariff_cents':100})
        result=ss.compare_current(self.admin,self.topic.pk,s.pk);self.assertFalse(result['blocked']);self.assertEqual((result['source_added'],result['source_removed'],result['source_changed']),(1,1,1))
        current=result['cards'][0];self.assertEqual((current['added_objects'],current['removed_objects'],current['changed_objects']),(1,1,1))
        rows={r['dimension']:r for r in current['comparison']['rows']};self.assertEqual(rows['绕组']['values'][0]['delta'],10);self.assertEqual(rows['绕组']['values'][0]['relative_pct'],50)
        self.assertIsNone(rows['冲片']['values'][0]['delta']);self.assertIsNone(rows['组装']['values'][0]['primary'])
        self.assertEqual(TopicSnapshot.objects.get().payload_hash,s.payload_hash)
    def test_current_comparison_unchanged_values_all_zero_except_missing(self):
        s=self.save();r=ss.compare_current(self.admin,self.topic.pk,s.pk);self.assertEqual((r['source_added'],r['source_removed'],r['source_changed']),(0,0,0))
        value=next(x for x in r['cards'][0]['comparison']['rows'] if x['dimension']=='绕组')['values'][0];self.assertEqual(value['delta'],0)
    def test_ratio_changes_are_percentage_points(self):
        self.model.definition['metrics']=[{'agg':'ratio','field':'kwh','denominator':'tariff_cents'}];self.model.save();s=self.save()
        r=Record.objects.get(business_key='E2');r.values['kwh']=40;r.save();result=ss.compare_current(self.admin,self.topic.pk,s.pk)
        v=next(r for r in result['cards'][0]['comparison']['rows'] if r['dimension']=='绕组')['values'][0]
        self.assertEqual((v['delta'],v['delta_unit']),(20,'百分点'));self.assertIsNone(v['relative_pct'])
    def test_group_side_pagination_and_unknown_object_never_fall_back(self):
        s=self.save();self.assertEqual(self.ev(s,group='不存在')['total'],0);self.assertEqual(self.ev(s,side='reference')['total'],1)
        self.assertEqual(self.ev(s,page=2)['rows'],[]);self.assertEqual(self.source(s,page=2)['rows'],[])
        for extra in [{'slot':True},{'side':'unknown'},{'page':0},{'group':7}]:
            with self.assertRaises(ValidationError):self.ev(s,**extra)
        with self.assertRaises(ValidationError):self.source(s,object_id='E1')
    def test_export_uses_frozen_values_and_preserves_nulls_and_formula_protection(self):
        body=self.payload();body['name']='=1+1';s=ss.create(self.admin,self.topic.pk,body);r=Record.objects.get(business_key='E2');r.values['kwh']=77;r.save()
        response=self.client.get(f'/api/topics/{self.topic.pk}/snapshots/{s.pk}/export');self.assertEqual(response.status_code,200)
        rows=list(csv.DictReader(io.StringIO(response.content.decode('utf-8-sig'))));self.assertEqual(len(rows),3)
        self.assertTrue(all(r['快照名称']=="'=1+1" for r in rows));self.assertEqual(next(r['数值'] for r in rows if r['范围名称']=='当前日' and r['分组']=='绕组'),'20')
        self.assertEqual(next(r['数值'] for r in rows if r['分组']=='组装'),'')
        exported=self.client.get(f'/api/topics/{self.topic.pk}/snapshots/{s.pk}/export?format=json').json();self.assertEqual(exported['payload_hash'],ws.digest(exported['payload']))
    def test_limits_reject_partial_snapshots(self):
        for constant,value in [('MAX_OBJECTS',1),('MAX_SOURCES',1),('MAX_BYTES',10)]:
            with patch('app.topic_snapshots.'+constant,value):
                with self.assertRaises(ValidationError):self.save()
        self.assertFalse(TopicSnapshot.objects.exists())
    def test_error_restricted_and_empty_topics_cannot_snapshot(self):
        self.topic.layout=[];self.topic.save()
        with self.assertRaises(ValidationError):self.save()
        self.topic.layout=[{'model_id':self.model.pk}];self.topic.save();self.model.dataset='costs';self.model.definition={'metrics':[{'agg':'sum','field':'amount_cents'}]};self.model.save()
        with self.assertRaises(ValidationError):self.save(self.quality)
    def test_empty_cohort_can_be_saved_without_fabricated_zero(self):
        body=self.payload(conf={**CONF,'scope':{'from':'2027-01-01'},'reference_scope':None});s=ss.create(self.admin,self.topic.pk,body)
        self.assertEqual(s.payload['result']['cards'][0]['primary']['rows'],[]);self.assertEqual(len(s.payload['sources']),0)
    def test_save_detects_changes_during_evidence_capture(self):
        body=self.payload();original=ss.capture
        def changing(*args):
            result=original(*args);r=Record.objects.get(business_key='E2');r.values['kwh']=67;r.save();return result
        with patch('app.topic_snapshots.capture',side_effect=changing):
            with self.assertRaises(ReviewConflict):ss.create(self.admin,self.topic.pk,body)
        self.assertFalse(TopicSnapshot.objects.exists());self.assertEqual(Record.objects.get(business_key='E2').values['kwh'],20)
    def test_missing_semantic_source_rejects_capture(self):
        self.model.dataset='bi_work_orders';self.model.definition={'dimension':'family','metrics':[{'agg':'count'}]};self.model.save()
        rows=[{'id':'W1','family':'YE4','product_id':'P1','planned_end':'2026-09-25','_sources':[{'dataset':'work_orders','key':'missing'}]}]
        with patch('app.analysis_engine.semantic.rows',return_value=rows):
            with self.assertRaises(ValidationError):self.save()
    def test_semantic_provenance_deduplicates_sources_across_cards(self):
        self.model.dataset='bi_work_orders';self.model.definition={'dimension':'family','metrics':[{'agg':'count'}]};self.model.save()
        self.topic.layout=[{'model_id':self.model.pk},{'model_id':self.model.pk}];self.topic.save()
        self.record('work_orders',{'id':'W1','product_id':'P1','planned_end':'2026-09-25','planned_qty':10})
        rows=[{'id':'W1','family':'YE4','product_id':'P1','planned_end':'2026-09-25','_sources':[{'dataset':'work_orders','key':'W1'}]}]
        with patch('app.analysis_engine.semantic.rows',return_value=rows):s=self.save()
        self.assertEqual(ss.info(s)['object_count'],2);self.assertEqual(ss.info(s)['source_count'],1)
        source=ss.source_evidence(self.admin,self.topic.pk,s.pk,{'slot':1,'side':'primary','object_id':'W1','page':1});self.assertEqual(source['rows'][0]['values']['planned_qty'],10)

    def test_metadata_changes_also_invalidate_integrity(self):
        s=self.save();TopicSnapshot.objects.filter(pk=s.pk).update(note='未获准的覆盖说明')
        with self.assertRaises(ReviewConflict):ss.get(self.admin,self.topic.pk,s.pk)
        self.assertFalse(ss.listing(self.admin,self.topic.pk)['rows'][0]['available'])

    def test_retired_metric_resolution_not_required_to_read_frozen_values(self):
        s=self.save()
        with patch('app.metric_registry.resolve',side_effect=ValidationError('指标已停用')):
            self.assertEqual(ss.detail(self.admin,self.topic.pk,s.pk)['id'],str(s.pk))

    def test_truncated_results_cannot_be_saved_as_complete(self):
        body=self.payload();original=ws.run
        def truncated(*args):
            result=original(*args);result['cards'][0]['primary']['truncated']=True;return result
        with patch('app.topic_workspace.run',side_effect=truncated):
            with self.assertRaises(ValidationError):ss.create(self.admin,self.topic.pk,body)
        self.assertFalse(TopicSnapshot.objects.exists())

    def test_dynamic_units_block_subtraction_after_unit_change(self):
        card={'slot':0,'model':{'dataset':'dynamic'},'primary':{'resolved_definition':{'metrics':[{'agg':'sum','field':'qty'}]}}}
        before={'fields':{'dynamic':[{'name':'qty','unit_field':'unit'}]},'cohorts':{'0':{'primary':[{'group':'全部','values':{'qty':5,'unit':'kg'}}]}}}
        now=copy.deepcopy(before);now['cohorts']['0']['primary'][0]['values']['unit']='件'
        units=ss.unit_sets(now,before,card,'primary')
        result={'truncated':False,'resolved_definition':card['primary']['resolved_definition'],'measures':[{'key':'m0'}],'rows':[{'dimension':'全部','m0':5,'row_count':1}]}
        value=ws.compare(result,result,units)['rows'][0]['values'][0]
        self.assertIsNone(value['delta']);self.assertIn('单位不同',value['reason'])
