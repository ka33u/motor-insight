import copy,json,uuid
from unittest.mock import patch
from django.contrib.auth.models import User,Group
from django.core.exceptions import ValidationError
from django.test import Client
from app import topic_workspace as ws,topic_linkage as links,topic_snapshots as ss
from app.models import AnalysisModel,Topic,Record,TopicView,TopicSnapshot,AuditEvent
from app.import_review import ReviewConflict
from app.schema import SCHEMAS
from app.semantic_schema import SEMANTIC_SCHEMAS
from tests.test_platform import PlatformCase

CONF=dict(scope={},reference_scope={},primary_label='当前',reference_label='参照')

class TopicLinkageTests(PlatformCase):
    def setUp(self):
        super().setUp();self.client.force_login(self.admin)
        self.model=AnalysisModel.objects.create(name='电量',dataset='energy',definition=dict(dimension='workshop',metrics=[dict(agg='sum',field='kwh')],chart='bar'),is_public=True,owner='admin')
        self.other=AnalysisModel.objects.create(name='安环状态',dataset='ehs',definition=dict(dimension='status',metrics=[dict(agg='count')],chart='bar'),is_public=True,owner='admin')
        self.topic=Topic.objects.create(name='跨部门车间',layout=[dict(model_id=self.model.id,span=1),dict(model_id=self.other.id,span=1)],owner='admin',is_public=True)
        for i,workshop,day,kwh in [('E1','绕组','24',10),('E2','绕组','25',20),('E3','组装','25',50)]:self.record('energy',dict(id=i,workshop=workshop,started=f'2026-09-{day}T08:00:00',ended=f'2026-09-{day}T09:00:00',kwh=kwh,tariff_cents=100))
        for i,workshop,status in [('H1','绕组','开放'),('H2','组装','开放'),('H3','绕组','已复核')]:self.record('ehs',dict(id=i,workshop=workshop,status=status))
    def conf(self,*items):return {**copy.deepcopy(CONF),'links':links.validate(dict(revision=links.REVISION,rules_hash=links.rules_hash(),selections=[dict(kind=k,value=v) for k,v in items or [('workshop','绕组')]]))}
    def evaluate(self,conf=None,user=None):
        user=user or self.admin;ctx=ws.context(user,self.topic.id)
        return ws.run(user,self.topic.id,dict(context_token=ctx['context_token'],config=conf or copy.deepcopy(CONF)))
    def pick(self,result=None,**change):
        r=result or self.evaluate();return self.post(f'/api/topics/{self.topic.id}/link-select',{**dict(context_token=r['context_token'],facts_token=r['facts_token'],config=r['config'],slot=0,side='primary',group='绕组'),**change})
    def evidence(self,r,slot=0,**change):return ws.evidence(self.admin,self.topic.id,{**dict(context_token=r['context_token'],facts_token=r['facts_token'],config=r['config'],slot=slot,side='primary',group=None,page=1),**change})
    def freeze(self,r):return ss.create(self.admin,self.topic.id,dict(request_id=str(uuid.uuid4()),context_token=r['context_token'],facts_token=r['facts_token'],summary_token=r['summary_token'],config=r['config'],name='车间结果',note='合成联动范围复盘'))
    def test_all_declared_direct_contracts_reference_real_authorized_string_fields(self):
        schemas={**SCHEMAS,**SEMANTIC_SCHEMAS}
        self.assertEqual(len(links.CONTRACTS),7)
        for kind,c in links.CONTRACTS.items():
            for ds,field in c['fields'].items():
                self.assertIn(field,{f['name'] for f in schemas[ds]['fields']},(kind,ds))
                self.assertEqual(links.contract(self.admin,ds)[kind]['field'],field)
    def test_point_selection_and_full_source_intersections_on_both_sides(self):
        original=self.evaluate();response=self.pick(original);self.assertEqual(response.status_code,200)
        r=self.evaluate(response.json()['config'])
        self.assertEqual([c['primary']['matched'] for c in r['cards']],[2,2])
        self.assertEqual([c['reference']['matched'] for c in r['cards']],[2,2])
        self.assertEqual(r['cards'][0]['scope_summary']['primary']['value'],30)
        self.assertFalse(r['cards'][0]['scope_summary']['comparison']['blocked'])
        self.assertEqual({x['values']['id'] for x in self.evidence(r)['rows']},{'E1','E2'})
        self.assertEqual({x['values']['id'] for x in self.evidence(r,1)['rows']},{'H1','H3'})
    def test_original_models_topic_and_business_facts_never_changed_by_linking(self):
        before=list(Record.objects.values_list('id','values','revision'));definitions=list(AnalysisModel.objects.values_list('id','definition','version'));layout=copy.deepcopy(self.topic.layout);audits=AuditEvent.objects.count()
        r=self.evaluate(self.conf());self.assertEqual(self.pick(self.evaluate()).status_code,200)
        self.assertEqual(before,list(Record.objects.values_list('id','values','revision')));self.assertEqual(definitions,list(AnalysisModel.objects.values_list('id','definition','version')))
        self.topic.refresh_from_db();self.assertEqual(self.topic.layout,layout);self.assertEqual(AuditEvent.objects.count(),audits)
        self.assertEqual(r['cards'][0]['model']['saved_definition'],self.model.definition)
    def test_unsupported_card_pauses_no_unfiltered_fallback(self):
        self.other.dataset='orders';self.other.definition=dict(dimension='status',metrics=[dict(agg='count')]);self.other.save()
        r=self.evaluate(self.conf());self.assertIn('无车间',r['cards'][1]['error']);self.assertNotIn('primary',r['cards'][1]);self.assertNotIn('scope_summary',r['cards'][1])
        with self.assertRaises(ValidationError):self.evidence(r,1)
        with self.assertRaises(ValidationError):self.freeze(r)
    def test_local_filters_and_date_ranges_are_retained(self):
        self.topic.layout=self.topic.layout[:1];self.topic.save();self.model.definition['filters']=[dict(field='kwh',op='gte',value=15)];self.model.save()
        conf=self.conf()
        conf['scope']={'from':'2026-09-25','to':'2026-09-25'};conf['reference_scope']={'from':'2026-09-24','to':'2026-09-24'}
        r=self.evaluate(conf);c=r['cards'][0];self.assertEqual((c['primary']['matched'],c['reference']['matched']),(1,0));self.assertEqual(c['scope_summary']['primary']['value'],20)
        self.assertEqual(c['model']['definition']['filters'][0],self.model.definition['filters'][0])
    def test_absent_identity_stays_empty_and_does_not_remove_filter(self):
        r=self.evaluate(self.conf(('workshop','历史车间0001')));self.assertEqual(r['cards'][0]['primary']['matched'],0);self.assertEqual(r['cards'][1]['primary']['matched'],0)
        self.assertEqual(r['config']['links']['selections'][0]['value'],'历史车间0001')
    def test_numeric_dates_display_names_status_and_custom_group_labels_are_not_identities(self):
        for ds,dimension in [('energy','started'),('energy','kwh'),('ehs','status')]:
            self.model.dataset=ds;self.model.definition=dict(dimension=dimension,metrics=[dict(agg='count')]);self.model.save()
            self.assertEqual(self.evaluate()['cards'][0]['link_choices'],[])
        self.assertNotIn('supplier',links.contract(self.admin,'bi_purchase'))
    def test_missing_or_colliding_display_group_is_not_linkable(self):
        self.record('energy',dict(id='E4',workshop=None,kwh=2));self.record('energy',dict(id='E5',workshop='未填写',kwh=3))
        r=self.evaluate();self.assertNotIn('未填写',[c['group'] for c in r['cards'][0]['link_choices']]);self.assertEqual(self.pick(r,group='未填写').status_code,400)
    def test_literal_missing_label_with_no_missing_rows_remains_exact_identity(self):
        self.record('energy',dict(id='E4',workshop='未填写',kwh=2));r=self.evaluate();self.assertEqual(self.pick(r,group='未填写').status_code,200)
    def test_client_cannot_invent_source_group_or_field_mapping(self):
        r=self.evaluate();self.assertEqual(self.pick(r,group='冲片').status_code,400)
        self.assertEqual(self.pick(r,field='status').status_code,400)
        self.assertEqual(self.pick(r,slot=True).status_code,400);self.assertEqual(self.pick(r,slot=-1).status_code,400)
        self.assertEqual(self.pick(r,side='both').status_code,400)
    def test_reference_side_selection_exists_on_requested_side(self):
        self.topic.layout=self.topic.layout[:1];self.topic.save();conf=copy.deepcopy(CONF);conf['scope']={'from':'2026-09-24','to':'2026-09-24'};conf['reference_scope']={'from':'2026-09-25','to':'2026-09-25'}
        r=self.evaluate(conf);self.assertEqual(self.pick(r,group='组装').status_code,400);self.assertEqual(self.pick(r,group='组装',side='reference').status_code,200)
        c=self.evaluate(self.pick(r,group='组装',side='reference').json()['config'])['cards'][0];self.assertEqual((c['primary']['matched'],c['reference']['matched']),(0,1))
    def test_stale_facts_or_models_prevent_selection(self):
        r=self.evaluate();record=Record.objects.get(business_key='E1');record.values['kwh']=99;record.save();self.assertEqual(self.pick(r).status_code,409)
        r=self.evaluate();self.model.version+=1;self.model.save();self.assertEqual(self.pick(r).status_code,409)
    def test_invalid_link_schema_and_duplicate_identity_and_maximum(self):
        base=self.conf()['links']
        bad=[None,[],{**base,'sql':'select 1'},{**base,'selections':[]},{**base,'selections':[base['selections'][0]]*2},{**base,'selections':[dict(kind=k,value='x') for k in ('unit','equipment','material','supplier')]},{**base,'selections':[dict(kind='status',value='开放')]},{**base,'selections':[dict(kind='unit',value=1)]},{**base,'selections':[dict(kind='unit',value=' x')]},{**base,'selections':[dict(kind='unit',value='A\nB')]},{**base,'selections':[dict(kind='unit',value='x'*151)]}]
        for value in bad:
            with self.subTest(value=value),self.assertRaises(ValidationError):ws.config({**CONF,'links':value})
    def test_link_rules_drift_blocks_saved_config_and_current_compare_without_rewriting_snapshot(self):
        conf=self.conf();r=self.evaluate(conf);snapshot=self.freeze(r);saved=ws.save_view(self.admin,self.topic.id,dict(name='联动视角',config=conf,context_token=r['context_token']))
        with patch('app.topic_linkage.rules_hash',return_value='new'):
            with self.assertRaises(ReviewConflict):self.evaluate(conf)
            self.assertTrue(ws.list_views(self.admin,ws.context(self.admin,self.topic.id))[0]['linkage_stale'])
            self.assertTrue(ss.compare_current(self.admin,self.topic.id,snapshot.id)['blocked'])
            self.assertEqual(ss.get(self.admin,self.topic.id,snapshot.id).payload_hash,snapshot.payload_hash)
        self.assertEqual(TopicView.objects.get(pk=saved['id']).config,conf)
    def test_limits_preserve_all_native_filters_and_pause_instead_of_dropping(self):
        self.model.definition['filters']=[dict(field='kwh',op='gte',value=0)]*10;self.model.save()
        r=self.evaluate(self.conf());self.assertIn('最多10',r['cards'][0]['error']);self.assertNotIn('primary',r['cards'][0])
        self.model.refresh_from_db();self.assertEqual(len(self.model.definition['filters']),10)
    def test_multiple_identity_conditions_intersect_and_keep_leading_zeros(self):
        self.model.dataset='units';self.model.definition=dict(dimension='product_id',metrics=[dict(agg='count')]);self.model.save()
        self.record('units',dict(id='SN0001',product_id='0001',work_order_id='WO0001'));self.record('units',dict(id='SN0002',product_id='0001',work_order_id='WO0002'))
        c=self.evaluate(self.conf(('configuration','0001'),('work_order','WO0001')))['cards'][0]
        self.assertEqual(c['primary']['matched'],1);self.assertEqual(c['linkage']['mapped'][0]['value'],'0001')
    def test_authorized_identity_selection_uses_private_model_permissions(self):
        self.model.is_public=False;self.model.save();self.client.force_login(self.quality)
        self.assertEqual(self.post(f'/api/topics/{self.topic.id}/link-select',dict(context_token=ws.context(self.quality,self.topic.id)['context_token'],facts_token=self.evaluate(user=self.quality)['facts_token'],config=CONF,slot=0,side='primary',group='绕组')).status_code,400)
        self.topic.is_public=False;self.topic.save();self.assertEqual(self.client.get(f'/api/topics/{self.topic.id}/workspace').status_code,404)
    def test_hidden_financial_card_and_identity_contract_do_not_leak(self):
        self.other.name='财务秘密';self.other.dataset='costs';self.other.definition=dict(metrics=[dict(agg='sum',field='amount_cents')]);self.other.save()
        r=self.evaluate(self.conf(),self.quality);self.assertNotIn('财务秘密',json.dumps(r,ensure_ascii=False));ctx=ws.context(self.quality,self.topic.id);self.assertNotIn('link_contract',ctx['cards'][1])
    def test_personal_view_roundtrip_and_owner_isolation(self):
        r=self.evaluate(self.conf());v=ws.save_view(self.admin,self.topic.id,dict(name='绕组复盘',config=r['config'],context_token=r['context_token']))
        self.assertEqual(ws.list_views(self.admin,ws.context(self.admin,self.topic.id))[0]['config'],r['config']);self.assertEqual(ws.list_views(self.quality,ws.context(self.quality,self.topic.id)),[])
        self.assertEqual(self.evaluate(v['config'])['cards'][0]['primary']['matched'],2)
    def test_source_pagination_and_group_keep_linked_scope(self):
        r=self.evaluate(self.conf());self.assertEqual(self.evidence(r,page=2)['rows'],[]);self.assertEqual(self.evidence(r,group='组装')['total'],0)
        self.assertTrue(all(x['source']['file']=='unit-test.xlsx' for x in self.evidence(r)['rows']))
    def test_result_csv_contains_same_scope_original_and_effective_definition(self):
        r=self.evaluate(self.conf());rows,_=ws.export_rows(self.admin,self.topic.id,dict(context_token=r['context_token'],facts_token=r['facts_token'],config=r['config'],slot=0))
        self.assertIn('专题联动条件与直接字段',rows[0]);self.assertIn('保存的模型定义',rows[0]);self.assertNotIn('组装',[x[rows[0].index('车间')] for x in rows[1:]])
        self.assertTrue(all(len(row)==len(rows[0]) for row in rows))
    def test_snapshot_freezes_only_linked_sources_and_exports_original_receipt(self):
        r=self.evaluate(self.conf());s=self.freeze(r);self.assertEqual(set(s.payload['sources']),{ws.digest([ds,k]) for ds,k in [('energy','E1'),('energy','E2'),('ehs','H1'),('ehs','H3')]})
        for sides in s.payload['cohorts'].values():self.assertTrue(all(len(rows)==2 for rows in sides.values()))
        self.assertFalse(ss.compare_current(self.admin,self.topic.id,s.id)['blocked']);self.assertTrue(all(v['delta']==0 for c in ss.compare_current(self.admin,self.topic.id,s.id)['cards'] for row in c['comparison']['rows'] for v in row['values']))
        rows=ss.export_rows(s);self.assertIn('保存的联动条件与逐卡直接字段',rows[0]);self.assertTrue(all(len(row)==len(rows[0]) for row in rows))
    def test_summary_export_preserves_same_configuration_and_audit(self):
        r=self.evaluate(self.conf());response=self.client.get(f'/api/topics/{self.topic.id}/summary/export',dict(context_token=r['context_token'],facts_token=r['facts_token'],summary_token=r['summary_token'],config=json.dumps(r['config'])))
        self.assertEqual(response.status_code,200);self.assertIn('workshop',response.content.decode());self.assertEqual(AuditEvent.objects.get(action='topic_scope_summary.export').detail['config'],r['config'])
    def test_pivot_receipt_uses_effective_filters_and_freezes_same_population(self):
        self.model.definition.update(chart='pivot',pivot={'dimension':'started','grain':'day'});self.model.save()
        r=self.evaluate(self.conf());self.assertNotIn('error',r['cards'][0]);self.assertEqual(r['cards'][0]['primary']['pivot']['grand_total']['row_count'],2);self.assertEqual(r['cards'][0]['link_choices'],[])
        self.assertEqual(len(self.freeze(r).payload['cohorts']['0']['primary']),2)
    def test_auth_csrf_and_query_injection(self):
        r=self.evaluate();payload=dict(context_token=r['context_token'],facts_token=r['facts_token'],config=r['config'],slot=0,side='primary',group='绕组')
        secure=Client(enforce_csrf_checks=True);secure.force_login(self.admin);self.assertEqual(secure.post(f'/api/topics/{self.topic.id}/link-select',json.dumps(payload),content_type='application/json').status_code,403)
        self.assertEqual(self.post(f'/api/topics/{self.topic.id}/link-select?sql=x',payload).status_code,400)
        self.client.logout();self.assertEqual(self.post(f'/api/topics/{self.topic.id}/link-select',payload).status_code,401)
    def test_published_metric_fixed_scope_and_version_survive_link_intersection(self):
        from tests.test_metric_registry import payload
        from app.models import MetricVersion
        p=payload();p['filters']=[dict(field='workshop',op='eq',value='绕组')]
        v=self.post('/api/metrics',dict(key='ENERGY_LINK_TEST',dataset='energy',payload=p)).json()
        v=self.post('/api/metrics/'+str(v['id']),dict(action='submit',revision=v['revision'])).json()
        self.client.force_login(self.quality);response=self.post('/api/metrics/'+str(v['id']),dict(action='publish',revision=v['revision'],reason='核对测试环境合成电量与固定范围'));self.assertEqual(response.status_code,200,response.content)
        before=copy.deepcopy(MetricVersion.objects.get(pk=v['id']).payload)
        self.model.definition=dict(dimension='workshop',metric_ref=dict(key='ENERGY_LINK_TEST',version=1),filters=[],chart='bar');self.model.save()
        c=self.evaluate(self.conf())['cards'][0];self.assertEqual(c['scope_summary']['primary']['value'],30);self.assertEqual(c['primary']['metric_receipt']['version'],1)
        c=self.evaluate(self.conf(('workshop','组装')))['cards'][0];self.assertEqual(c['primary']['matched'],0)
        self.assertEqual(MetricVersion.objects.get(pk=v['id']).payload,before)
    def test_old_unlinked_view_binding_and_snapshot_comparison_are_compatible(self):
        r=self.evaluate();v=ws.save_view(self.admin,self.topic.id,dict(name='旧无联动视角',config=r['config'],context_token=r['context_token']));s=self.freeze(r)
        with patch('app.topic_linkage.rules_hash',return_value='changed'):
            self.assertFalse(ws.list_views(self.admin,ws.context(self.admin,self.topic.id))[0]['stale']);self.assertFalse(ss.compare_current(self.admin,self.topic.id,s.id)['blocked'])
        self.assertNotIn('links',TopicView.objects.get(pk=v['id']).config)
