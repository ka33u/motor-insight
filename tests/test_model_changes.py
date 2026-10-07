import copy
import json
import time
import uuid
from unittest.mock import patch
from django.contrib.auth.models import User, Group
from django.core.exceptions import ValidationError, PermissionDenied
from django.db import IntegrityError, transaction
from django.test import Client
from app import model_changes as changes, topic_workspace as ws, bi_scope
from app.import_review import ReviewConflict
from app.models import (AnalysisModel, AnalysisModelChange, Topic, TopicView, TopicSnapshot,
    AnalysisModelCard, AnalysisModelCardVersion, TopicPage, TopicPageVersion, AuditEvent,
    Record, AccountAccessState)
from tests.test_platform import PlatformCase


class ModelChangeTests(PlatformCase):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.admin)
        self.model=AnalysisModel.objects.create(name='车间能耗',dataset='energy',owner='admin',is_public=True,
            definition=dict(dimension='workshop',metrics=[dict(agg='sum',field='kwh')],chart='bar'))
        self.topic=Topic.objects.create(name='能耗专题',owner='admin',is_public=True,layout=[dict(model_id=self.model.pk)])
        for n,group,day,kwh in [(1,'A','24',10),(2,'A','25',20),(3,'B','25',5)]:
            self.record('energy',dict(id=f'0000{n}',workshop=group,started=f'2026-09-{day}T08:00:00',ended=f'2026-09-{day}T12:00:00',kwh=kwh,tariff_cents=100))

    def body(self,**candidate):
        self.model.refresh_from_db()
        value={key:copy.deepcopy(getattr(self.model,key)) for key in ('name','dataset','definition','is_public')}
        value.update(name='车间能耗候选');value.update(candidate)
        return dict(version=self.model.version,candidate=value,scope={},links=None)

    def reviewed(self,body=None,user=None):
        data=body or self.body();preview=changes.preview(user or self.admin,self.model.pk,data)
        return dict(**data,receipt=preview['receipt'],reason='已核对来源和下游定义',acknowledged=True,request_id=str(uuid.uuid4()))

    def evidence(self,body=None,**kwargs):
        body=body or self.body();p=changes.preview(self.admin,self.model.pk,body)
        return changes.evidence(self.admin,self.model.pk,dict(**body,receipt=p['receipt'],side=kwargs.get('side','before'),subset=kwargs.get('subset','all'),page=kwargs.get('page',1)))

    def view(self,owner=None,config=None):
        return TopicView.objects.create(owner=owner or self.admin,topic=self.topic,name='保存范围',
            config=config or dict(scope={},reference_scope=None,primary_label='本期',reference_label='对照'),binding=ws.context(self.admin,self.topic.pk)['binding'])

    def test_preview_read_only_and_full_population_average_not_average_of_groups(self):
        body=self.body();body['candidate']['definition']['metrics'][0]['agg']='avg'
        before=list(Record.objects.values());p=changes.preview(self.admin,self.model.pk,body)
        self.assertEqual(p['original_result']['summary']['value'],35)
        self.assertAlmostEqual(p['candidate_result']['summary']['value'],35/3,places=3)
        self.assertNotEqual(p['candidate_result']['summary']['value'],10)
        self.assertEqual(p['population'],dict(comparable=True,before=3,after=3,shared=3,added=0,removed=0,reason=p['population']['reason']))
        self.assertEqual(list(Record.objects.values()),before);self.assertFalse(AnalysisModelChange.objects.exists());self.assertFalse(AuditEvent.objects.exists())
        self.model.refresh_from_db();self.assertEqual(self.model.version,1)

    def test_filter_scope_intersection_membership_and_leading_zero_source(self):
        body=self.body();body['candidate']['definition']['filters']=[dict(field='workshop',op='eq',value='A')]
        body['scope']={'from':'2026-09-25','to':'2026-09-25'}
        p=changes.preview(self.admin,self.model.pk,body)
        self.assertEqual((p['original_result']['summary']['value'],p['candidate_result']['summary']['value']),(25,20))
        self.assertEqual((p['population']['shared'],p['population']['removed'],p['population']['added']),(1,1,0))
        e=self.evidence(body,subset='removed');self.assertEqual(e['rows'][0]['values']['id'],'00003')
        self.assertEqual(e['rows'][0]['source']['filename'],'unit-test.xlsx');self.assertEqual(e['rows'][0]['source']['sheet'],'energy')
        self.assertEqual(self.evidence(body,side='candidate',subset='shared')['rows'][0]['values']['id'],'00002')
        self.assertEqual(self.evidence(body,side='candidate',subset='added')['total'],0)
        with self.assertRaises(ValidationError):self.evidence(body,side='before',subset='added')

    def test_cross_dataset_same_text_identity_not_paired(self):
        self.record('units',dict(id='00001',assembly_at='2026-09-25T08:00:00'))
        body=self.body(dataset='units',definition=dict(metrics=[dict(agg='count')],chart='table'))
        self.assertFalse(changes.preview(self.admin,self.model.pk,body)['population']['comparable'])
        with self.assertRaises(ValidationError):self.evidence(body,subset='shared')

    def test_unsupported_scope_is_explicit_pause_not_silently_ignored(self):
        body=self.body();body['scope']={'customer_id':'000009'}
        p=changes.preview(self.admin,self.model.pk,body)
        self.assertFalse(p['original_result']['ready']);self.assertIn('客户',p['candidate_result']['error'])
        self.assertFalse(p['population']['comparable'])
        with self.assertRaises(ValidationError):self.evidence(body)

    def test_missing_values_not_zero_and_empty_scope_distinguished(self):
        self.record('energy',dict(id='00004',workshop='B',kwh=None))
        p=changes.preview(self.admin,self.model.pk,self.body())
        self.assertEqual(p['candidate_result']['summary']['missing_rows'],1)
        self.assertEqual(p['candidate_result']['summary']['state'],'partial')
        body=self.body();body['candidate']['definition']['filters']=[dict(field='workshop',op='eq',value='不存在')]
        self.assertEqual(changes.preview(self.admin,self.model.pk,body)['candidate_result']['summary']['state'],'no_sample')

    def test_full_summary_not_limited_to_first_fifteen_preview_groups(self):
        for n in range(18):self.record('energy',dict(id=f'N{n}',workshop=f'W{n}',kwh=1))
        p=changes.preview(self.admin,self.model.pk,self.body())
        self.assertEqual(len(p['candidate_result']['sample_groups']),15)
        self.assertEqual(p['candidate_result']['groups'],20);self.assertEqual(p['candidate_result']['summary']['value'],53)

    def test_ratio_summary_uses_whole_population_numerator_and_denominator(self):
        self.model.dataset='bi_work_orders';self.model.definition=dict(dimension='family',metrics=[dict(agg='ratio',field='released_qty',denominator='produced_qty')]);self.model.save()
        rows=[dict(id='W1',family='A',released_qty=1,produced_qty=1),dict(id='W2',family='B',released_qty=1,produced_qty=9)]
        with patch('app.analysis_engine.semantic.rows',return_value=rows):p=changes.preview(self.admin,self.model.pk,self.body())
        summary=p['candidate_result']['summary']
        self.assertEqual((summary['value'],summary['numerator'],summary['denominator']),(20,2,10))

    def test_semantic_evidence_preserves_declared_references(self):
        self.model.dataset='bi_work_orders';self.model.definition=dict(metrics=[dict(agg='count')]);self.model.save()
        rows=[dict(id='000001',_sources=[dict(dataset='work_orders',key='000001')])]
        with patch('app.analysis_engine.semantic.rows',return_value=rows):e=self.evidence()
        self.assertEqual(e['rows'][0]['values']['id'],'000001');self.assertEqual(e['rows'][0]['references'],rows[0]['_sources']);self.assertIsNone(e['rows'][0]['source'])

    def test_retired_original_can_be_repaired_but_cannot_be_silently_reused(self):
        from tests.test_metric_registry import payload
        v=self.post('/api/metrics',dict(key='ENERGY_CHANGE',dataset='energy',payload=payload())).json()
        v=self.post('/api/metrics/'+str(v['id']),dict(action='submit',revision=v['revision'])).json()
        self.client.force_login(self.quality)
        v=self.post('/api/metrics/'+str(v['id']),dict(action='publish',revision=v['revision'],reason='核对模拟来源与计量')).json()
        self.client.force_login(self.admin)
        self.model.definition=dict(metric_ref=dict(key=v['key'],version=v['version']),filters=[],chart='table');self.model.save()
        self.assertEqual(self.post('/api/metrics/'+str(v['id']),dict(action='retire',revision=v['revision'],reason='停用旧版模拟口径')).status_code,200)
        with self.assertRaises(ValidationError):changes.preview(self.admin,self.model.pk,self.body())
        body=self.body(definition=dict(metrics=[dict(agg='sum',field='kwh')],chart='table'))
        p=changes.preview(self.admin,self.model.pk,body)
        self.assertFalse(p['original_result']['ready']);self.assertTrue(p['candidate_result']['ready'])
        self.assertEqual(changes.commit(self.admin,self.model.pk,self.reviewed(body))['model']['version'],2)

    def test_links_intersect_local_filter_and_remain_explicit(self):
        from app import topic_linkage
        body=self.body();body['candidate']['definition']['filters']=[dict(field='workshop',op='eq',value='A')]
        body['links']=dict(revision=topic_linkage.REVISION,rules_hash=topic_linkage.rules_hash(),selections=[dict(kind='workshop',value='B')])
        p=changes.preview(self.admin,self.model.pk,body)
        self.assertEqual(p['population']['before'],1);self.assertEqual(p['population']['after'],0)
        self.assertEqual(p['links'],body['links'])

    def test_evidence_page_boundaries_and_source_integrity(self):
        for n in range(28):self.record('energy',dict(id=f'Z{n:04d}',workshop='Z',kwh=1))
        first=self.evidence();second=self.evidence(page=2)
        self.assertEqual((first['total'],len(first['rows']),len(second['rows'])),(31,25,6))
        self.assertEqual(len({r['values']['id'] for r in first['rows']+second['rows']}),31)
        with self.assertRaises(ValidationError):self.evidence(page=3)
        row=Record.objects.get(business_key='00001');row.source_row.normalized={'id':'bad'};row.source_row.save()
        with self.assertRaisesMessage(ValueError,'导入行'):self.evidence()

    def test_definition_diff_distinguishes_absent_and_null(self):
        a=dict(name='X',dataset='energy',is_public=False,definition={});b=copy.deepcopy(a);b['definition']['display_metric']=None
        d=changes.differences(a,b)[0];self.assertFalse(d['before_present']);self.assertTrue(d['after_present'])

    def test_noop_rejected(self):
        with self.assertRaisesMessage(ValidationError,'相同'):changes.preview(self.admin,self.model.pk,self.body(name=self.model.name))

    def test_visible_dependency_listing_and_private_artifacts_hidden_even_for_admin(self):
        own=self.view();other=self.view(self.quality);other.name='其他人的秘密视角';other.save()
        binding=ws.context(self.admin,self.topic.pk)['binding']
        for user in (self.admin,self.quality):
            card=AnalysisModelCard.objects.create(owner=user,code='MC-'+user.username)
            payload=dict(binding=dict(source_model=dict(id=self.model.pk)))
            AnalysisModelCardVersion.objects.create(card=card,revision=1,payload=payload,payload_hash=ws.digest(payload),request_id=uuid.uuid4(),request_hash='x')
            page=TopicPage.objects.create(owner=user,topic=self.topic,code='PG-'+user.username)
            payload=dict(binding=dict(topic=binding,navigation=[]))
            TopicPageVersion.objects.create(page=page,number=1,payload=payload,payload_hash=ws.digest(payload))
            payload=dict(binding=binding)
            TopicSnapshot.objects.create(owner=user,topic=self.topic,request_id=uuid.uuid4(),request_hash='x',name='SN-'+user.username,note='',payload=payload,payload_hash=ws.digest(payload))
        protected=[TopicView,AnalysisModelCardVersion,TopicPageVersion,TopicSnapshot]
        before={m.__name__:list(m.objects.values()) for m in protected}
        p=changes.preview(self.admin,self.model.pk,self.body());impact=p['impact']
        self.assertEqual(impact['views'][0]['id'],own.pk)
        for key in ('topics','views','cards','pages','snapshots'):self.assertEqual(len(impact[key]),1,key)
        self.assertNotIn('其他人的秘密视角',json.dumps(impact,ensure_ascii=False));self.assertNotIn('MC-quality',json.dumps(impact))
        changes.commit(self.admin,self.model.pk,self.reviewed())
        self.assertEqual(before,{m.__name__:list(m.objects.values()) for m in protected})

    def test_dependency_date_role_change_and_unsupported_saved_scope(self):
        view=self.view(config=dict(scope={'from':'2026-09-25'},reference_scope=None,primary_label='本期',reference_label='对照'))
        body=self.body(dataset='units',definition=dict(metrics=[dict(agg='count')]))
        p=changes.preview(self.admin,self.model.pk,body)
        self.assertIn('日期角色变化',p['impact']['views'][0]['scope_check'])
        body=self.body(dataset='products',definition=dict(metrics=[dict(agg='count')]))
        self.assertIn('不支持',changes.preview(self.admin,self.model.pk,body)['impact']['views'][0]['scope_check'])

    def test_new_dependency_invalidates_receipt(self):
        body=self.reviewed();self.view()
        with self.assertRaises(ReviewConflict):changes.commit(self.admin,self.model.pk,body)

    def test_other_users_private_dependency_does_not_invalidate_or_reveal(self):
        body=self.reviewed();self.view(self.quality)
        self.assertEqual(changes.commit(self.admin,self.model.pk,body)['model']['version'],2)

    def test_normal_fact_update_invalidates_receipt(self):
        body=self.reviewed();self.record('departments',dict(id='D99',name='新部门',owner='负责人'))
        with self.assertRaises(ReviewConflict):changes.commit(self.admin,self.model.pk,body)

    def test_candidate_scope_sharing_and_rule_changes_invalidate(self):
        original=self.reviewed()
        for key in ('candidate','scope'):
            body=copy.deepcopy(original)
            if key=='scope':body[key]={'from':'2026-09-25'}
            else:body[key]['is_public']=False
            with self.assertRaises(ReviewConflict):changes.commit(self.admin,self.model.pk,body)
        with patch('app.model_changes.rules',return_value='new'):
            with self.assertRaises(ReviewConflict):changes.commit(self.admin,self.model.pk,original)

    def test_model_version_and_silent_definition_change_invalidate(self):
        body=self.reviewed();self.model.name='被改名';self.model.save()
        with self.assertRaises(ReviewConflict):changes.commit(self.admin,self.model.pk,body)
        self.model.version+=1;self.model.save()
        with self.assertRaises(ReviewConflict):changes.preview(self.admin,self.model.pk,{k:body[k] for k in changes.BASE_KEYS})

    def test_account_revision_disabled_and_fresh_role_checked(self):
        body=self.reviewed();AccountAccessState.objects.create(user=self.admin,revision=2)
        with self.assertRaises(ReviewConflict):changes.commit(self.admin,self.model.pk,body)
        self.admin.is_active=False;self.admin.save()
        with self.assertRaises(PermissionDenied):changes.commit(self.admin,self.model.pk,body)

    def test_only_owner_analyst_or_admin_may_update(self):
        analyst=User.objects.create_user('analyst');analyst.groups.add(Group.objects.create(name='analyst'))
        with self.assertRaises(PermissionDenied):changes.preview(analyst,self.model.pk,self.body())
        self.model.owner='analyst';self.model.save()
        self.assertTrue(changes.preview(analyst,self.model.pk,self.body())['receipt'])
        for role in ('operations','quality','finance','viewer'):
            user=User.objects.create_user('user-'+role);user.groups.add(Group.objects.get_or_create(name=role)[0])
            with self.assertRaises(PermissionDenied):changes.preview(user,self.model.pk,self.body())

    def test_private_other_model_is_not_found(self):
        analyst=User.objects.create_user('analyst');analyst.groups.add(Group.objects.create(name='analyst'))
        self.model.is_public=False;self.model.save()
        with self.assertRaises(AnalysisModel.DoesNotExist):changes.preview(analyst,self.model.pk,self.body())

    def test_strict_input_version_scope_and_reason(self):
        good=self.body()
        for body in [dict(good,extra=1),dict(good,version=True),dict(good,scope=[]),dict(good,candidate={**good['candidate'],'name':''}),dict(good,candidate={**good['candidate'],'is_public':'yes'})]:
            with self.assertRaises((ValidationError,ReviewConflict)):changes.preview(self.admin,self.model.pk,body)
        good=self.reviewed()
        for body in [dict(good,acknowledged=False),dict(good,reason='短'),dict(good,extra=1),dict(good,request_id='bad')]:
            with self.assertRaises((ValidationError,ValueError)):changes.commit(self.admin,self.model.pk,body)
        self.assertFalse(AnalysisModelChange.objects.exists())

    def test_expired_and_wrong_receipt_rejected(self):
        body=self.reviewed()
        with patch('time.time',return_value=time.time()+changes.AGE+2):
            with self.assertRaises(ReviewConflict):changes.commit(self.admin,self.model.pk,body)
        body['receipt']='bad'
        with self.assertRaises(ReviewConflict):changes.commit(self.admin,self.model.pk,body)

    def test_checked_commit_ledger_and_exact_idempotence_after_later_update(self):
        body=self.reviewed();first=changes.commit(self.admin,self.model.pk,body)
        self.assertEqual(first['model']['version'],2);self.assertFalse(first['repeated'])
        ledger=AnalysisModelChange.objects.get();self.assertEqual(ledger.payload_hash,ws.digest(ledger.payload))
        self.assertFalse(ledger.payload['business_results_saved']);self.assertNotIn('original_result',ledger.payload)
        changes.commit(self.admin,self.model.pk,self.reviewed(self.body(name='第三版')))
        with patch('time.time',return_value=time.time()+changes.AGE+2):replay=changes.commit(self.admin,self.model.pk,body)
        self.assertTrue(replay['repeated']);self.assertEqual(replay['applied_version'],2);self.assertEqual(replay['model']['version'],3)
        self.assertEqual(AnalysisModelChange.objects.count(),2);self.assertEqual(AuditEvent.objects.count(),2)

    def test_request_id_cannot_be_reused_for_different_body_or_actor(self):
        body=self.reviewed();changes.commit(self.admin,self.model.pk,body)
        with self.assertRaises(ReviewConflict):changes.commit(self.admin,self.model.pk,dict(body,reason='另一份变更理由'))
        other=User.objects.create_user('admin2');other.groups.add(Group.objects.get(name='admin'))
        with self.assertRaises(ReviewConflict):changes.commit(other,self.model.pk,body)

    def test_atomic_rollback_on_audit_failure(self):
        body=self.reviewed()
        with patch('app.model_changes.AuditEvent.objects.create',side_effect=RuntimeError('simulated failure')):
            with self.assertRaises(RuntimeError):changes.commit(self.admin,self.model.pk,body)
        self.model.refresh_from_db();self.assertEqual(self.model.version,1);self.assertFalse(AnalysisModelChange.objects.exists())

    def test_history_no_fabricated_old_versions_immutable_and_hash_checked(self):
        self.model.version=8;self.model.save()
        self.assertEqual(changes.history(self.admin,self.model.pk)['first_recorded_version'],8)
        changes.commit(self.admin,self.model.pk,self.reviewed());h=changes.history(self.admin,self.model.pk)
        self.assertEqual((h['rows'][0]['from_version'],h['rows'][0]['to_version']),(8,9))
        ledger=AnalysisModelChange.objects.get()
        with self.assertRaises(ValidationError):ledger.save()
        AnalysisModelChange.objects.filter(pk=ledger.pk).update(payload_hash='tampered')
        with self.assertRaises(ReviewConflict):changes.history(self.admin,self.model.pk)

    def test_history_permission_rechecked_and_hidden_definition_redacted(self):
        changes.commit(self.admin,self.model.pk,self.reviewed())
        with patch('app.model_changes.readable_change',side_effect=ValidationError('字段当前不可访问')):
            row=changes.history(self.admin,self.model.pk)['rows'][0]
        self.assertTrue(row['restricted']);self.assertNotIn('payload',row);self.assertNotIn('actor',row)

    def test_unique_model_version_constraint(self):
        changes.commit(self.admin,self.model.pk,self.reviewed());old=AnalysisModelChange.objects.get()
        with self.assertRaises(IntegrityError),transaction.atomic():
            AnalysisModelChange.objects.create(request_id=uuid.uuid4(),actor=self.admin,model=self.model,from_version=1,to_version=2,request_hash='x',payload=old.payload,payload_hash=old.payload_hash)

    def test_api_no_store_auth_csrf_and_no_legacy_update_bypass(self):
        base=f'/api/models/{self.model.pk}'
        p=self.post(base+'/change-preview',self.body());self.assertEqual(p.status_code,200,p.content);self.assertEqual(p['Cache-Control'],'no-store')
        self.assertEqual(self.client.get(base+'/changes')['Cache-Control'],'no-store')
        self.assertEqual(self.client.get(base+'/changes?page=1&page=2').status_code,400)
        self.assertEqual(self.post(base+'/change-preview?scope=secret',self.body()).status_code,400)
        direct=self.post('/api/models',dict(id=self.model.pk,name='绕过预演'))
        self.assertEqual(direct.status_code,409);self.assertEqual(direct.json()['code'],'model_change_preview_required')
        csrf=Client(enforce_csrf_checks=True);csrf.force_login(self.admin)
        self.assertEqual(csrf.post(base+'/change-preview',json.dumps(self.body()),content_type='application/json').status_code,403)
        self.client.logout();self.assertEqual(self.post(base+'/change-preview',self.body()).status_code,401)
