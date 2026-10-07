from unittest.mock import patch
from django.test import SimpleTestCase,TestCase
from django.contrib.auth.models import User,Group
from django.core.exceptions import ValidationError
from app.bi_scope import apply,validate_scope
from app.analysis_engine import run_analysis
from app.semantic import build
from tests.test_semantic import fixture

class ScopeTests(SimpleTestCase):
    def setUp(self):self.data=fixture();self.views=build(self.data)
    def scoped(self,dataset,rows,scope):
        with patch('app.bi_scope.analytics.tables',return_value=self.data):return apply(dataset,rows,scope)
    def test_date_end_includes_whole_day_and_filters_not_asof(self):
        rows,meta=self.scoped('bi_units',self.views['bi_units'],{'from':'2026-09-21','to':'2026-09-21'})
        self.assertEqual(len(rows),2);self.assertEqual(meta['date_label'],'装配日');self.assertTrue(all(r['released_count']==1 for r in rows))
        self.assertEqual(self.scoped('bi_units',self.views['bi_units'],{'from':'2026-09-22'})[0],[])
    def test_family_customer_and_date_intersection_through_session(self):
        rows,_=self.scoped('test_sessions',self.data['test_sessions'],{'family':'F1','customer_id':'C1','to':'2026-09-21'})
        self.assertEqual(len(rows),3)
        self.assertEqual(self.scoped('test_sessions',self.data['test_sessions'],{'family':'Other','customer_id':'C1'})[0],[])
    def test_customer_is_identifier_not_name(self):
        self.data['customers'].append({'id':'C2','name':'模拟客户','region':'华东'})
        self.assertEqual(self.scoped('bi_order_lines',self.views['bi_order_lines'],{'customer_id':'C2'})[0],[])
    def test_shared_work_order_excluded_and_reported_for_customer_scope(self):
        self.data['order_lines'].append({**self.data['order_lines'][0],'id':'L2'})
        self.data['allocations'].append(dict(id='A2',work_order_id='W1',order_line_id='L2',effective='2026-09-01'))
        rows,meta=self.scoped('bi_units',self.views['bi_units'],{'customer_id':'C1'})
        self.assertEqual(rows,[]);self.assertEqual(meta['unknown_customer_rows'],2)
    def test_unsupported_filter_never_silently_returns_all(self):
        for dataset,scope in [('bi_inventory',{'to':'2026-09-21'}),('bi_energy_day',{'customer_id':'C1'}),('bi_purchase',{'family':'F1'})]:
            with self.assertRaises(ValidationError):self.scoped(dataset,self.views[dataset],scope)
    def test_unknown_and_invalid_scope_rejected(self):
        for value in [{'to':'2026-02-30'},{'from':'2026-09-22','to':'2026-09-21'},{'sql':'1=1'},[],{'from':'20260921'}]:
            with self.assertRaises(ValidationError):validate_scope(value)
    def test_reset_and_local_filter_intersect_with_dashboard_scope(self):
        definition={'dimension':'family','metrics':[{'agg':'ratio','field':'first_pass_count','denominator':'first_tested_count'}],'filters':[{'field':'id','op':'eq','value':'U1'}],'chart':'bar'}
        with patch('app.analysis_engine.allowed',return_value=True),patch('app.analysis_engine.permitted_fields',return_value=__import__('app.semantic_schema',fromlist=['SEMANTIC_SCHEMAS']).SEMANTIC_SCHEMAS['bi_units']['fields']),patch('app.analysis_engine.semantic.rows',return_value=self.views['bi_units']),patch('app.bi_scope.analytics.tables',return_value=self.data):
            result=run_analysis(None,'bi_units',definition,{'family':'F1'})
            self.assertEqual((result['matched'],result['rows'][0]['m0']),(1,0))
            self.assertEqual(run_analysis(None,'bi_units',{**definition,'filters':[]},{})['matched'],2)

class EvidencePermissionTests(TestCase):
    def setUp(self):
        self.user=User.objects.create_user('qa');self.user.groups.add(Group.objects.create(name='quality'));self.client.force_login(self.user)
    def test_money_metric_or_filter_cannot_be_read_through_evidence(self):
        for definition in [dict(metrics=[dict(agg='sum',field='order_net_cents')]),dict(metrics=[dict(agg='count')],filters=[dict(field='order_net_cents',op='gte',value=0)])]:
            response=self.client.post('/api/analyze/evidence',{'dataset':'bi_order_lines','definition':definition},content_type='application/json')
            self.assertEqual(response.status_code,400)
    def test_evidence_uses_same_scope_group_and_hides_money_sources(self):
        data=fixture();views=build(data)
        definition={'dimension':'family','metrics':[{'agg':'count'}]}
        with patch('app.analysis_engine.semantic.rows',return_value=views['bi_work_orders']),patch('app.bi_scope.analytics.tables',return_value=data):
            response=self.client.post('/api/analyze/evidence',{'dataset':'bi_work_orders','definition':definition,'scope':{'family':'F1'},'group':'F1'},content_type='application/json')
            result=response.json();self.assertEqual(result['total'],1)
            self.assertNotIn('total_cost_cents',result['rows'][0]['values'])
            self.assertTrue(all(r['dataset']!='costs' for r in result['rows'][0]['references']))
            result=self.client.post('/api/analyze/evidence',{'dataset':'bi_work_orders','definition':definition,'scope':{'family':'Other'}},content_type='application/json').json()
            self.assertEqual(result['total'],0)
