import copy,json
from unittest.mock import patch
from django.contrib.auth.models import User,Group
from django.core.exceptions import ValidationError
from django.test import Client,SimpleTestCase
from app import topic_workspace as ws
from app.models import Topic,TopicView,AnalysisModel,AuditEvent,Record
from app.import_review import ReviewConflict
from tests.test_platform import PlatformCase

CONF={'scope':{'from':'2026-09-25','to':'2026-09-25'},'reference_scope':{'from':'2026-09-24','to':'2026-09-24'},'primary_label':'9月25日','reference_label':'9月24日'}

class TopicWorkspaceTests(PlatformCase):
    def setUp(self):
        super().setUp();self.client.force_login(self.admin)
        self.model=AnalysisModel.objects.create(name='车间能耗',dataset='energy',definition={'dimension':'workshop','metrics':[{'agg':'sum','field':'kwh'}],'chart':'bar'},owner='admin',is_public=True)
        self.topic=Topic.objects.create(name='能耗对照',layout=[{'model_id':self.model.pk,'span':2}],owner='admin',is_public=True)
        for ident,workshop,day,value in [('E1','绕组','24',10),('E2','绕组','25',20),('E3','绕组','25',5),('E4','组装','24',0),('E5','组装','25',3),('E6','冲片','25',4)]:
            self.record('energy',{'id':ident,'workshop':workshop,'started':f'2026-09-{day}T08:00:00','ended':f'2026-09-{day}T12:00:00','kwh':value,'tariff_cents':100})
    def ctx(self,user=None):return ws.context(user or self.admin,self.topic.pk)
    def payload(self,config=None):return {'context_token':self.ctx()['context_token'],'config':copy.deepcopy(config or CONF)}
    def save(self,user=None):return ws.save_view(user or self.admin,self.topic.pk,{**self.payload(),'name':'我的能耗视角'})
    def evidence(self,result,**changes):
        return ws.evidence(self.admin,self.topic.pk,{'context_token':result['context_token'],'facts_token':result['facts_token'],'config':result['config'],'slot':0,'side':'primary','group':None,'page':1,**changes})
    def test_comparison_correct_deltas_missing_groups_and_zero_base(self):
        result=ws.run(self.admin,self.topic.pk,self.payload());rows={r['dimension']:r for r in result['cards'][0]['comparison']['rows']}
        self.assertEqual((rows['绕组']['primary_rows'],rows['绕组']['reference_rows']),(2,1))
        v=rows['绕组']['values'][0];self.assertEqual((v['primary'],v['reference'],v['delta'],v['relative_pct']),(25,10,15,150))
        self.assertIsNone(rows['组装']['values'][0]['relative_pct']);self.assertEqual(rows['组装']['values'][0]['delta'],3)
        self.assertIsNone(rows['冲片']['values'][0]['reference']);self.assertIsNone(rows['冲片']['values'][0]['delta'])
    def test_ratio_compares_weighted_results_in_percentage_points(self):
        self.model.definition={'dimension':'workshop','metrics':[{'agg':'ratio','field':'kwh','denominator':'tariff_cents'}],'chart':'bar'};self.model.save()
        result=ws.run(self.admin,self.topic.pk,self.payload());v=next(r for r in result['cards'][0]['comparison']['rows'] if r['dimension']=='绕组')['values'][0]
        self.assertEqual((v['primary'],v['reference'],v['delta']),(12.5,10,2.5));self.assertEqual(v['delta_unit'],'百分点');self.assertIsNone(v['relative_pct'])
        self.assertEqual(result['cards'][0]['primary']['components'][1]['metric_index'],0)
    def test_configuration_mix_and_overlap_are_explicit(self):
        self.model.dataset='bi_work_orders';self.model.definition={'dimension':'family','metrics':[{'agg':'count'}],'chart':'bar'};self.model.save()
        rows=[{'id':'W1','family':'YE4','product_id':'P1','planned_end':'2026-09-24'},{'id':'W2','family':'YE4','product_id':'P2','planned_end':'2026-09-25'}]
        with patch('app.analysis_engine.semantic.rows',return_value=rows):
            result=ws.run(self.admin,self.topic.pk,self.payload());q=result['cards'][0]['comparability']
            self.assertEqual(q['shared_configuration_count'],0);self.assertFalse(q['same_configuration_mix']);self.assertEqual(q['overlap_objects'],0)
            result=ws.run(self.admin,self.topic.pk,self.payload({**CONF,'reference_scope':CONF['scope']}));q=result['cards'][0]['comparability']
            self.assertEqual(q['overlap_objects'],1);self.assertTrue(q['same_configuration_mix'])
    def test_configuration_unknown_is_counted_not_assumed_comparable(self):
        self.model.dataset='bi_work_orders';self.model.definition={'metrics':[{'agg':'count'}],'chart':'bar'};self.model.save()
        with patch('app.analysis_engine.semantic.rows',return_value=[{'id':'W1','product_id':None,'planned_end':'2026-09-25'}]):
            result=ws.run(self.admin,self.topic.pk,self.payload());q=result['cards'][0]['comparability']
            self.assertEqual(q['primary_unknown_configuration'],1);self.assertFalse(q['same_configuration_mix'])
    def test_model_without_configuration_does_not_claim_mix_matches(self):
        result=ws.run(self.admin,self.topic.pk,self.payload());q=result['cards'][0]['comparability']
        self.assertFalse(q['configuration_available']);self.assertNotIn('same_configuration_mix',q)
    def test_saved_config_survives_new_session_and_never_stores_values(self):
        before=list(Record.objects.values_list('id','values','revision'));v=self.save();self.client.logout();self.client.force_login(self.admin)
        data=self.client.get(f'/api/topics/{self.topic.pk}/workspace').json();stored=data['views'][0]
        self.assertEqual(stored['config'],CONF);self.assertFalse(stored['stale']);self.assertEqual(stored['id'],v['id'])
        self.assertNotIn('rows',TopicView.objects.get().config);self.assertEqual(before,list(Record.objects.values_list('id','values','revision')))
    def test_owner_isolation_including_admin_cannot_update_others_views(self):
        v=self.save(self.quality);self.assertEqual(ws.list_views(self.admin,self.ctx()),[])
        response=self.post(f'/api/topics/{self.topic.pk}/views/{v["id"]}',{**self.payload(),'name':'试图覆盖','version':1,'rebind':False,'reason':''})
        self.assertEqual(response.status_code,404)
        self.assertEqual(self.post(f'/api/topics/{self.topic.pk}/views/{v["id"]}/archive',{'version':1,'archived':True}).status_code,404)
        self.assertEqual(TopicView.objects.get().owner,self.quality)
    def test_viewer_can_save_personal_view_without_editing_shared_models(self):
        viewer=User.objects.create_user('viewer');viewer.groups.add(Group.objects.create(name='viewer'));self.client.force_login(viewer)
        body={**self.payload(),'name':'只读账号个人筛选'};self.assertEqual(self.post(f'/api/topics/{self.topic.pk}/views',body).status_code,200)
        self.topic.refresh_from_db();self.model.refresh_from_db();self.assertEqual((self.topic.version,self.model.version),(1,1))
    def test_model_version_and_definition_drift_block_old_binding(self):
        v=self.save();old=self.payload();self.model.definition['metrics'][0]['agg']='avg';self.model.version=2;self.model.save()
        ctx=self.ctx();info=ws.list_views(self.admin,ctx)[0];self.assertTrue(info['stale']);self.assertEqual(info['changes'][0]['after_version'],2)
        with self.assertRaises(ReviewConflict):ws.run(self.admin,self.topic.pk,old)
        # Hash detects a changed definition even when an out-of-band writer forgot to bump a version.
        self.model.version=1;self.model.save();self.assertTrue(ws.list_views(self.admin,self.ctx())[0]['stale'])
    def test_rebind_requires_explicit_reason_and_preserves_old_binding_in_audit(self):
        v=self.save();old=copy.deepcopy(TopicView.objects.get().binding);self.model.version=2;self.model.save()
        body={**self.payload(),'name':'更新视角','version':1,'rebind':False,'reason':''}
        with self.assertRaises(ReviewConflict):ws.save_view(self.admin,self.topic.pk,body,v['id'])
        with self.assertRaises(ValidationError):ws.save_view(self.admin,self.topic.pk,{**body,'rebind':True,'reason':'短'},v['id'])
        updated=ws.save_view(self.admin,self.topic.pk,{**body,'rebind':True,'reason':'已核对新模型定义仍适用'},v['id']);self.assertEqual(updated['version'],2);self.assertFalse(updated['stale'])
        self.assertEqual(AuditEvent.objects.get(action='topic_view.rebind').detail['from'],old)
    def test_stale_personal_revision_does_not_overwrite(self):
        v=self.save();body={**self.payload(),'name':'更新名字','version':1,'rebind':False,'reason':''};ws.save_view(self.admin,self.topic.pk,body,v['id'])
        with self.assertRaises(ReviewConflict):ws.save_view(self.admin,self.topic.pk,body,v['id'])
        self.assertEqual(TopicView.objects.get().version,2)
    def test_archive_restore_is_reversible_and_archived_edit_is_blocked(self):
        v=self.save();ws.archive_view(self.admin,self.topic.pk,v['id'],{'version':1,'archived':True})
        self.assertFalse(ws.list_views(self.admin,self.ctx()));self.assertEqual(len(ws.list_views(self.admin,self.ctx(),True)),1)
        with self.assertRaises(ValidationError):ws.save_view(self.admin,self.topic.pk,{**self.payload(),'name':'不能编辑','version':2,'rebind':False,'reason':''},v['id'])
        restored=ws.archive_view(self.admin,self.topic.pk,v['id'],{'version':2,'archived':False});self.assertEqual(restored['version'],3)
        self.assertEqual(len(ws.list_views(self.admin,self.ctx())),1)
    def test_save_and_audit_rollback_together(self):
        with patch('app.topic_workspace.AuditEvent.objects.create',side_effect=RuntimeError('disk failure')):
            with self.assertRaises(RuntimeError):self.save()
        self.assertFalse(TopicView.objects.exists())
    def test_csrf_authentication_and_private_topic_access(self):
        secure=Client(enforce_csrf_checks=True);secure.force_login(self.admin)
        self.assertEqual(secure.post(f'/api/topics/{self.topic.pk}/views',json.dumps({**self.payload(),'name':'未带令牌'}),content_type='application/json').status_code,403)
        self.topic.is_public=False;self.topic.save();self.client.force_login(self.quality)
        self.assertEqual(self.client.get(f'/api/topics/{self.topic.pk}/workspace').status_code,404)
        self.client.logout();self.assertEqual(self.client.get(f'/api/topics/{self.topic.pk}/workspace').status_code,401)
    def test_hidden_financial_model_returns_no_name_definition_or_values(self):
        self.model.name='财务敏感说明';self.model.dataset='costs';self.model.definition={'metrics':[{'agg':'sum','field':'amount_cents'}]};self.model.save()
        ctx=self.ctx(self.quality);self.assertFalse(ctx['cards'][0]['available']);self.assertNotIn('model',ctx['cards'][0]);self.assertNotIn('dataset',ctx['binding']['cards'][0])
        result=ws.run(self.quality,self.topic.pk,{'context_token':ctx['context_token'],'config':CONF});self.assertNotIn('model',result['cards'][0]);self.assertNotIn('财务敏感说明',json.dumps(result,ensure_ascii=False))
    def test_scope_unsupported_on_either_side_pauses_card_without_fallback(self):
        conf={**CONF,'reference_scope':{'family':'YE4'}};result=ws.run(self.admin,self.topic.pk,self.payload(conf))
        self.assertIn('无法应用产品族',result['cards'][0]['error']);self.assertNotIn('primary',result['cards'][0])
    def test_malformed_configs_and_booleans_rejected(self):
        for change in [{'scope':None},{'scope':{'sql':'select 1'}},{'reference_scope':[]},{'scope':{'from':'20261003'}},{'primary_label':''},{'extra':'bad'}]:
            with self.assertRaises(ValidationError):ws.config({**CONF,**change})
    def test_same_scope_and_empty_results_are_explicit(self):
        conf={**CONF,'reference_scope':CONF['scope']};result=ws.run(self.admin,self.topic.pk,self.payload(conf));self.assertTrue(result['same_scope'])
        result=ws.run(self.admin,self.topic.pk,self.payload({**CONF,'scope':{'from':'2030-01-01'},'reference_scope':{'from':'2030-01-01'}}))
        self.assertEqual(result['cards'][0]['comparison']['rows'],[])
    def test_evidence_side_group_and_page_match_comparison(self):
        result=ws.run(self.admin,self.topic.pk,self.payload());left=self.evidence(result,group='绕组');right=self.evidence(result,side='reference',group='绕组')
        self.assertEqual((left['total'],right['total']),(2,1));self.assertEqual({r['values']['id'] for r in left['rows']},{'E2','E3'})
        self.assertEqual(right['rows'][0]['source']['file'],'unit-test.xlsx');self.assertEqual(self.evidence(result,side='reference',group='冲片')['total'],0)
        self.assertEqual(self.evidence(result,page=2)['rows'],[])
    def test_evidence_refuses_data_or_definition_drift(self):
        result=ws.run(self.admin,self.topic.pk,self.payload());record=Record.objects.first();record.values={**record.values,'kwh':15};record.save()
        with self.assertRaises(ReviewConflict):self.evidence(result)
        result=ws.run(self.admin,self.topic.pk,self.payload());self.model.version+=1;self.model.save()
        with self.assertRaises(ReviewConflict):self.evidence(result)
    def test_changed_fact_revision_during_run_rejects_mixed_result(self):
        with patch('app.topic_workspace.analytics.revision',side_effect=[(1,'a'),(1,'b')]),patch('app.topic_workspace.comparability',return_value={}),patch('app.topic_workspace.run_analysis',return_value={'rows':[],'truncated':False,'measures':[],'resolved_definition':{'metrics':[]}}):
            with self.assertRaises(ReviewConflict):ws.run(self.admin,self.topic.pk,self.payload())
    def test_evidence_hides_financial_fields_for_quality(self):
        ctx=self.ctx(self.quality);result=ws.run(self.quality,self.topic.pk,{'context_token':ctx['context_token'],'config':CONF})
        data=ws.evidence(self.quality,self.topic.pk,{'context_token':result['context_token'],'facts_token':result['facts_token'],'config':CONF,'slot':0,'side':'primary','group':None,'page':1})
        self.assertNotIn('tariff_cents',data['rows'][0]['values']);self.assertNotIn('tariff_cents',[f['name'] for f in data['fields']])
    def test_fact_changes_do_not_claim_view_is_historical_snapshot(self):
        self.save();r=Record.objects.get(business_key='E2');r.values={**r.values,'kwh':50};r.save()
        self.assertFalse(ws.list_views(self.admin,self.ctx())[0]['stale']);result=ws.run(self.admin,self.topic.pk,self.payload())
        row=next(r for r in result['cards'][0]['primary']['rows'] if r['dimension']=='绕组');self.assertEqual(row['m0'],55)
    def test_export_same_range_nulls_labels_and_csv_safety(self):
        import csv,io
        result=ws.run(self.admin,self.topic.pk,self.payload());query={'context_token':result['context_token'],'facts_token':result['facts_token'],'config':json.dumps(CONF),'slot':'0'}
        response=self.client.get(f'/api/topics/{self.topic.pk}/export',query)
        self.assertEqual(response.status_code,200);self.assertIn('attachment',response['Content-Disposition']);rows=list(csv.DictReader(io.StringIO(response.content.decode('utf-8-sig'))))
        self.assertEqual(len(rows),3);a=next(r for r in rows if r['车间']=='绕组');self.assertEqual((a['当前值'],a['对照值'],a['差值']),('25','10','15.0'))
        self.assertEqual(next(r for r in rows if r['车间']=='冲片')['对照值'],'')
        conf={**CONF,'primary_label':'=HYPERLINK("x")'};query['config']=json.dumps(conf);response=self.client.get(f'/api/topics/{self.topic.pk}/export',query)
        self.assertIn("'=HYPERLINK",response.content.decode('utf-8-sig'))
    def test_export_refuses_stale_facts_or_restricted_card(self):
        result=ws.run(self.admin,self.topic.pk,self.payload());data={'context_token':result['context_token'],'facts_token':'invalid','config':CONF,'slot':0}
        with self.assertRaises(ReviewConflict):ws.export_rows(self.admin,self.topic.pk,data)
        self.model.dataset='costs';self.model.definition={'metrics':[{'agg':'sum','field':'amount_cents'}]};self.model.save();ctx=self.ctx(self.quality)
        result=ws.run(self.quality,self.topic.pk,{'context_token':ctx['context_token'],'config':CONF})
        from django.core.exceptions import PermissionDenied
        with self.assertRaises(PermissionDenied):ws.export_rows(self.quality,self.topic.pk,{'context_token':ctx['context_token'],'facts_token':result['facts_token'],'config':CONF,'slot':0})
    def test_reading_and_running_never_writes_audit_or_business_records(self):
        count=AuditEvent.objects.count();views=TopicView.objects.count();before=list(Record.objects.values_list('id','values','revision'))
        ctx=self.ctx();ws.list_views(self.admin,ctx);r=ws.run(self.admin,self.topic.pk,self.payload());self.evidence(r)
        self.assertEqual(AuditEvent.objects.count(),count);self.assertEqual(TopicView.objects.count(),views);self.assertEqual(before,list(Record.objects.values_list('id','values','revision')))

class ComparisonBoundaryTests(SimpleTestCase):
    def result(self,value=1,unit=None,rows=None):return {'rows':rows if rows is not None else [{'dimension':'A','row_count':2,'m0':value}],'truncated':False,'measures':[{'key':'m0','label':'值',**({'unit':unit} if unit else {})}],'resolved_definition':{'metrics':[{'agg':'sum'}]},'metric_receipt':None}
    def test_truncated_groups_pause_comparison(self):self.assertTrue(ws.compare({**self.result(),'truncated':True},self.result())['blocked'])
    def test_negative_base_has_difference_but_no_percent(self):
        v=ws.compare(self.result(10),self.result(-5))['rows'][0]['values'][0];self.assertEqual(v['delta'],15);self.assertIsNone(v['relative_pct'])
    def test_null_and_text_and_nonfinite_are_not_coerced_to_zero(self):
        for value in [None,'2026-09-25',float('inf'),True]:self.assertIsNone(ws.compare(self.result(value),self.result(5))['rows'][0]['values'][0]['delta'])
    def test_dynamic_unit_difference_or_unknown_pauses_difference(self):
        for units in [{('A','m0',0):{'kg'},('A','m0',1):{'件'}},{('A','m0',0):{None},('A','m0',1):{None}}]:
            v=ws.compare(self.result(10),self.result(5),units)['rows'][0]['values'][0];self.assertIsNone(v['delta']);self.assertIn('计量单位',v['reason'])
    def test_derived_percentage_or_governed_percentage_uses_points(self):
        for r in [self.result(80,'%'),{**self.result(80),'metric_receipt':{'unit':'%'}}]:
            v=ws.compare(r,self.result(75))['rows'][0]['values'][0];self.assertEqual(v['delta'],5);self.assertEqual(v['delta_unit'],'百分点');self.assertIsNone(v['relative_pct'])
    def test_date_groups_not_implicitly_shifted(self):
        a=self.result(rows=[{'dimension':'2026-09-25','row_count':1,'m0':5}]);b=self.result(rows=[{'dimension':'2026-09-24','row_count':1,'m0':3}])
        rows=ws.compare(a,b)['rows'];self.assertEqual(len(rows),2);self.assertTrue(all(r['values'][0]['delta'] is None for r in rows))
