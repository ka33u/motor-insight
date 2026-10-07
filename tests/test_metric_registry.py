from copy import deepcopy
from unittest.mock import patch
from django.contrib.auth.models import User,Group
from django.core.exceptions import ValidationError
from django.test import Client
from app import metric_registry as registry,analytics
from app.analysis_engine import run_analysis,selected_rows
from app.models import GovernedMetric,MetricVersion,AuditEvent,AnalysisModel,Topic,Record
from tests.test_platform import PlatformCase

def payload():
    return dict(name='模拟车间用电',business_definition='汇总已导入的指定车间表计用电。',purpose='检查计量范围与用电变化，不判断单位产品能效。',business_owner='能源管理岗位',clock='按读数覆盖区间，固定模拟数据截止。',unit='kWh',exclusions='只含车间A，不推算缺失表计。',comparison='同计量范围与时长比较。',change_reason='首次建立演示指标。',review_role='quality',measure={'agg':'sum','field':'kwh'},filters=[{'field':'workshop','op':'eq','value':'A'}])

class MetricRegistryTests(PlatformCase):
    def setUp(self):
        super().setUp();self.client.force_login(self.admin)
        for i,(workshop,kwh) in enumerate([('A',10),('A',30),('B',90)]):self.record('energy',{'id':str(i),'workshop':workshop,'kwh':kwh})
    def create(self,p=None,key='ENERGY_SAMPLE',dataset='energy'):
        r=self.post('/api/metrics',dict(key=key,dataset=dataset,payload=p or payload()));self.assertEqual(r.status_code,200,r.content);return r.json()
    def act(self,v,action,**kw):return self.post('/api/metrics/'+str(v['id']),{'action':action,'revision':v['revision'],**kw})
    def publish(self,v=None):
        self.client.force_login(self.admin);v=v or self.create();v=self.act(v,'submit').json();self.client.force_login(self.quality)
        r=self.act(v,'publish',reason='已核对模拟来源、范围与计算结果。');self.assertEqual(r.status_code,200,r.content);return r.json()
    def ref(self,v,**extra):return {'metric_ref':{'key':v['key'],'version':v['version']},'filters':[],'chart':'table',**extra}
    def test_draft_is_not_analysis_and_self_approval_is_rejected(self):
        v=self.create();self.assertEqual(self.post('/api/analyze',{'dataset':'energy','definition':self.ref(v)}).status_code,400)
        v=self.act(v,'submit').json();self.assertEqual(v['status'],'review');self.assertEqual(v['evidence']['rows'][0]['m0'],40)
        self.assertEqual(self.act(v,'publish',reason='管理员自审也应被拒绝').status_code,403)
        self.assertEqual(self.act(v,'save',payload=payload()).status_code,400)
    def test_published_contract_is_pinned_and_cannot_be_overridden(self):
        v=self.publish();d=self.ref(v)
        r=run_analysis(self.quality,'energy',d);self.assertEqual(r['rows'][0]['m0'],40);self.assertEqual(r['metric_receipt']['version'],1)
        self.assertEqual(run_analysis(self.quality,'energy',self.ref(v,filters=[{'field':'kwh','op':'gte','value':'20'}]))['rows'][0]['m0'],30)
        with self.assertRaises(ValidationError):run_analysis(self.quality,'energy',self.ref(v,metrics=[{'agg':'count'}]))
        with self.assertRaises(ValidationError):run_analysis(self.quality,'products',d)
        self.client.force_login(self.admin);self.assertEqual(self.act(v,'save',payload=payload()).status_code,400)
    def test_fork_and_new_release_do_not_silently_change_old_models(self):
        v1=self.publish();self.client.force_login(self.admin)
        saved=self.post('/api/models',dict(name='固定v1',dataset='energy',definition=self.ref(v1),is_public=True)).json()
        v2=self.act(v1,'fork').json();self.assertEqual(v2['version'],2)
        self.assertEqual(self.act(v1,'fork').status_code,409)
        p=deepcopy(v2['payload']);p['filters']=[];p['change_reason']='扩大到全部车间，另立新版本。'
        v2=self.act(v2,'save',payload=p).json();v2=self.publish(v2)
        self.assertEqual(run_analysis(self.quality,'energy',self.ref(v1))['rows'][0]['m0'],40)
        self.assertEqual(run_analysis(self.quality,'energy',self.ref(v2))['rows'][0]['m0'],130)
        self.assertEqual(AnalysisModel.objects.get(pk=saved['id']).definition['metric_ref']['version'],1)
    def test_retirement_exposes_impact_and_stops_analysis_without_hiding_model(self):
        v=self.publish();self.client.force_login(self.admin)
        m=self.post('/api/models',dict(name='停用演练',dataset='energy',definition=self.ref(v),is_public=True)).json()
        self.post('/api/topics',dict(name='指标专题',layout=[{'model_id':m['id'],'span':1}],is_public=True))
        detail=self.client.get('/api/metrics/'+str(v['id'])).json();self.assertEqual((detail['impact']['model_count'],detail['impact']['topic_count']),(1,1))
        self.assertEqual(self.act(v,'retire',reason='模拟演练停用，保留所有历史引用。').status_code,200)
        self.assertIn(m['id'],[x['id'] for x in self.client.get('/api/models').json()])
        self.assertEqual(self.post('/api/analyze',{'dataset':'energy','definition':self.ref(v)}).status_code,400)
        self.assertEqual(MetricVersion.objects.get(pk=v['id']).payload,v['payload'])
    def test_stale_edit_no_fact_changes_and_audit_failure_rolls_back(self):
        v=self.create();self.assertEqual(self.act(v,'save',payload=payload()).status_code,200)
        self.assertEqual(self.act(v,'submit').status_code,409);self.assertEqual(Record.objects.count(),3)
        v=self.client.get('/api/metrics/'+str(v['id'])).json()
        with patch('app.metric_registry.AuditEvent.objects.create',side_effect=RuntimeError('audit failed')):
            with self.assertRaises(RuntimeError):self.act(v,'submit')
        self.assertEqual(MetricVersion.objects.get(pk=v['id']).status,'draft')
    def test_reject_withdraw_and_resubmit_preserve_history(self):
        v=self.create();v=self.act(v,'submit').json();self.client.force_login(self.quality)
        v=self.act(v,'reject',reason='请补充模拟指标的比较范围。').json();self.assertEqual(v['status'],'draft')
        self.client.force_login(self.admin);v=self.act(v,'submit').json();v=self.act(v,'withdraw').json();self.assertEqual(v['status'],'draft')
        actions=list(AuditEvent.objects.filter(object_id=str(v['id']),object_type='MetricVersion').values_list('action',flat=True));self.assertIn('metric.reject',actions);self.assertIn('metric.withdraw',actions)
    def test_data_or_code_change_between_submit_and_publish_requires_review(self):
        v=self.create();v=self.act(v,'submit').json();self.client.force_login(self.quality)
        self.record('energy',{'id':'NEW','workshop':'A','kwh':2})
        self.assertEqual(self.act(v,'publish',reason='数据已变，不能按旧样例直接发布。').status_code,409)
        with patch('app.metric_registry.calculation_hash',return_value='changed'):
            self.assertEqual(self.act(v,'publish',reason='代码已变，不能按旧样例直接发布。').status_code,400)
    def test_published_rule_drift_pauses_but_new_data_recomputes(self):
        v=self.publish();self.record('energy',{'id':'NEW','workshop':'A','kwh':2})
        self.assertEqual(run_analysis(self.quality,'energy',self.ref(v))['rows'][0]['m0'],42)
        with patch('app.metric_registry.calculation_hash',return_value='changed'):
            with self.assertRaises(ValidationError):run_analysis(self.quality,'energy',self.ref(v))
    def test_permissions_and_sensitive_fixed_filters_are_not_leaked(self):
        p=payload();p['measure']={'agg':'count'};p['filters']=[{'field':'price_cents','op':'gte','value':1}]
        v=self.create(p,key='SENSITIVE_COUNT',dataset='products');self.client.force_login(self.quality)
        self.assertEqual(self.client.get('/api/metrics').json()['versions'],[])
        self.assertEqual(self.client.get('/api/metrics/'+str(v['id'])).status_code,403)
        self.assertEqual(self.post('/api/metrics/'+str(v['id'])+'/preview',{}).status_code,403)
        self.assertEqual(self.post('/api/metrics',dict(key='BAD_CREATE',dataset='energy',payload=payload())).status_code,403)
    def test_fixed_and_extra_filters_match_evidence(self):
        v=self.publish();d=self.ref(v,filters=[{'field':'kwh','op':'gte','value':20}]);rows,_,_=selected_rows(self.quality,'energy',d)
        self.assertEqual([r['id'] for r in rows],['1']);r=self.post('/api/analyze/evidence',{'dataset':'energy','definition':d}).json();self.assertEqual(r['total'],1)
    def test_history_does_not_leak_previously_sensitive_definitions(self):
        p=payload();p['measure']={'agg':'count'};p['filters']=[{'field':'price_cents','op':'gte','value':987654}]
        v=self.create(p,key='CHANGING_SCOPE',dataset='products');p['filters']=[]
        v=self.act(v,'save',payload=p).json();self.client.force_login(self.quality)
        history=self.client.get('/api/metrics/'+str(v['id'])).json()['history'];self.assertTrue(history[0]['detail']['before']['restricted'])
        self.assertNotIn('987654',str(history));self.assertNotIn('price_cents',str(history))
    def test_ratio_uses_sums_null_pairs_and_exposes_numerator(self):
        p=payload();p.update(unit='%',measure={'agg':'ratio','field':'on_time_plan_count','denominator':'due_plan_count'},filters=[])
        sample=[dict(id='L1',on_time_plan_count=1,due_plan_count=2),dict(id='L2',on_time_plan_count=1,due_plan_count=8),dict(id='L3',on_time_plan_count=None,due_plan_count=10)]
        with patch('app.semantic.rows',return_value=sample):
            v=self.publish(self.create(p,key='OTIF_TEST',dataset='bi_order_lines'));r=run_analysis(self.quality,'bi_order_lines',self.ref(v))
            self.assertEqual(r['rows'][0]['m0'],20);self.assertEqual((r['components'][0]['numerator'],r['components'][0]['denominator'],r['components'][0]['excluded_null_rows']),(2,10,1))
            sample[0]['due_plan_count']=0;sample[1]['due_plan_count']=0
            self.assertIsNone(run_analysis(self.quality,'bi_order_lines',self.ref(v))['rows'][0]['m0'])
    def test_payload_injection_invalid_reference_and_empty_sample_rejected(self):
        for changes in [{'measure':{'agg':'eval','field':'kwh'}},{'measure':{'agg':'sum','field':'kwh','sql':'SELECT 1'}},{'filters':[{'field':'kwh','op':'gte','value':{}}]},{'clock':''}]:
            self.assertEqual(self.post('/api/metrics',dict(key='BAD_METRIC',dataset='energy',payload={**payload(),**changes})).status_code,400)
        v=self.create({**payload(),'filters':[{'field':'workshop','op':'eq','value':'MISSING'}]});self.assertEqual(self.act(v,'submit').status_code,400)
        self.assertEqual(self.post('/api/analyze',{'dataset':'energy','definition':{'metric_ref':{'key':'A','version':True}}}).status_code,400)
    def test_auth_csrf_wrong_review_role_and_contributors_separation(self):
        self.assertEqual(Client().get('/api/metrics').status_code,401)
        c=Client(enforce_csrf_checks=True);c.force_login(self.admin);self.assertEqual(c.post('/api/metrics','{}',content_type='application/json').status_code,403)
        v=self.create();v=self.act(v,'submit').json()
        operations=User.objects.create_user('ops');operations.groups.add(Group.objects.create(name='operations'));self.client.force_login(operations)
        self.assertEqual(self.act(v,'publish',reason='错误业务岗位不能审核。').status_code,403)
        self.client.force_login(self.admin);v=self.act(v,'withdraw').json()
        other=User.objects.create_user('second_admin');other.groups.add(Group.objects.get(name='admin'));self.client.force_login(other)
        v=self.act(v,'save',payload=payload()).json();v=self.act(v,'submit').json();self.client.force_login(self.admin)
        self.assertEqual(self.act(v,'publish',reason='原编写人也不能参与自审。').status_code,403)
