import copy,csv,io,json
from unittest.mock import patch
from django.contrib.auth.models import User,Group
from django.core.exceptions import PermissionDenied
from app import target_breakdown as b,targets as k,metric_registry
from app.models import Record,AuditEvent
from tests.test_targets import TargetFixture

class BreakdownTests(TargetFixture):
    def calc(self,p=None):return b.Breakdown(self.admin,self.t['id'],k.Targets(self.admin,self.tables)).calculate(p or {})
    def instance(self):return b.Breakdown(self.admin,self.t['id'],k.Targets(self.admin,self.tables))
    def configure(self,dataset,metrics,unit,measure='m0',derived=None):
        self.model.dataset=dataset;self.model.definition.update(dimension='',grain='value',metrics=metrics,derived=derived or [],display_metric=measure,chart='table');self.model.save();self.t.update(unit=unit,measure=measure,model_signature=k.model_signature(self.model),calculation_hash=metric_registry.calculation_hash(dataset))
    def cost(self,key,category,value):return self.record('costs',dict(id=key,category=category,occurred='2026-09-20',amount_cents=value))
    def test_count_partition_matches_original_and_no_subgroup_targets(self):
        d=self.calc({'dimension':'id'});self.assertEqual((d['parent']['actual'],d['additive_sum'],d['groups']),(2,2,2));self.assertTrue(d['source_conserved']);self.assertTrue(d['reconciles']);self.assertEqual(sum(r['share_pct'] for r in d['rows']),100);self.assertNotIn('candidate_state',d['rows'][0])
    def test_context_family_join_does_not_multiply_and_tracks_source(self):
        self.record('products',dict(id='P',family='伺服电机'));d=self.calc();self.assertEqual(d['axis']['dimension'],'product.family');self.assertEqual((d['rows'][0]['label'],d['rows'][0]['source_rows']),('伺服电机',2));ref=self.instance().source_refs({'id':'U1','product_id':'P'},dict(path='[]'),d['axis']);self.assertIn(dict(dataset='products',key='P'),ref)
    def test_context_missing_link_and_empty_field_separate(self):
        self.record('products',dict(id='P',family=None));self.record('units',dict(id='U3',assembly_at='2026-09-20T10:00:00',product_id='NO'));d=self.calc();self.assertEqual({r['missing_kind'] for r in d['rows']},{'missing_value','missing_link'});self.assertEqual(sum(r['source_rows'] for r in d['rows']),3)
    def test_null_and_literal_missing_label_remain_distinct(self):
        self.configure('costs',[dict(agg='count',field=None)],'条');self.cost('A',None,1);self.cost('B','未填写',2);d=self.calc({'dimension':'category'});self.assertEqual({r['label'] for r in d['rows']},{'未填写','原值：未填写'});self.assertEqual(len({r['token'] for r in d['rows']}),2)
    def test_nested_path_evidence_and_return_preserve_population(self):
        root=self.calc({'dimension':'product_id'});p=dict(dimension='work_order_id',path=json.dumps([dict(dimension='product_id',grain='value',token=root['rows'][0]['token'])]));d=self.calc(p);self.assertEqual((d['parent']['source_rows'],d['total']['actual']),(2,2));rows,*_=self.instance().evidence({**p,'group':d['rows'][0]['token']});self.assertEqual({r['id'] for r in rows},{'U1','U2'})
    def test_forged_cross_group_path_or_object_rejected(self):
        with self.assertRaises(ValueError):self.calc({'dimension':'id','path':json.dumps([dict(dimension='product_id',grain='value',token='0'*64)])})
        with self.assertRaises(ValueError):self.instance().evidence({'dimension':'id','group':'0'*64})
    def test_invalid_fields_date_grains_sorts_and_paths(self):
        for p in [{'dimension':'secret'},{'dimension':'id','grain':'day'},{'dimension':'id','sort':'bad'},{'path':'bad'},{'path':'{}'},{'path':json.dumps([{}])},{'path':'x'*6001}]:
            with self.assertRaises(ValueError,msg=str(p)):self.calc(p)
    def test_no_repeated_axis_in_path(self):
        d=self.calc({'dimension':'id'});path=[dict(dimension='id',grain='value',token=d['rows'][0]['token'])]
        with self.assertRaises(ValueError):self.calc({'dimension':'id','path':json.dumps(path)})
        with self.assertRaises(ValueError):self.calc({'path':json.dumps(path*2)})
        with self.assertRaises(ValueError):self.calc({'path':json.dumps(path*4)})
    def test_date_grouping_preserves_day_and_month(self):
        day=self.calc({'dimension':'assembly_at','grain':'day'});month=self.calc({'dimension':'assembly_at','grain':'month'});self.assertEqual(day['rows'][0]['label'],'2026-09-20');self.assertEqual(month['rows'][0]['label'],'2026-09');self.assertEqual(day['parent']['actual'],month['parent']['actual'])
    def test_filters_and_target_period_not_reset(self):
        self.model.definition['filters']=[dict(field='id',op='eq',value='U1')];self.model.save();self.t['model_signature']=k.model_signature(self.model);self.record('units',dict(id='OTHER',assembly_at='2026-09-21T08:00:00'));d=self.calc({'dimension':'id'});self.assertEqual([r['label'] for r in d['rows']],['U1']);self.assertTrue(any(f['value']=='U1' for f in d['filters']))
    def test_sum_converted_units_and_positive_shares(self):
        self.configure('costs',[dict(agg='sum',field='amount_cents')],'元');self.cost('A','甲',125);self.cost('B','乙',375);d=self.calc({'dimension':'category'});self.assertEqual([r['actual'] for r in d['rows']],[3.75,1.25]);self.assertEqual(d['parent']['actual'],5);self.assertEqual([r['share_pct'] for r in d['rows']],[75,25])
    def test_negative_or_zero_values_do_not_forge_share(self):
        self.configure('costs',[dict(agg='sum',field='amount_cents')],'元');self.cost('A','甲',100);self.cost('B','乙',-100);d=self.calc({'dimension':'category'});self.assertEqual(d['parent']['actual'],0);self.assertFalse(d['share_available']);self.assertTrue(d['reconciles'])
    def test_missing_values_are_counted_and_disable_share(self):
        self.configure('costs',[dict(agg='sum',field='amount_cents')],'元');self.cost('A','甲',100);self.cost('B','乙',None);d=self.calc({'dimension':'category'});self.assertEqual(d['parent']['missing_rows'],1);self.assertIsNone(next(x for x in d['rows'] if x['label']=='乙')['actual']);self.assertFalse(d['share_available']);self.assertTrue(d['reconciles'])
    def test_average_is_from_rows_not_group_means(self):
        self.configure('costs',[dict(agg='avg',field='amount_cents')],'元')
        for key,cat,value in [('A','甲',100),('B','乙',1000),('C','乙',2000)]:self.cost(key,cat,value)
        d=self.calc({'dimension':'category'});self.assertAlmostEqual(d['parent']['actual'],31/3);self.assertNotEqual(d['parent']['actual'],sum(r['actual'] for r in d['rows'])/2);self.assertFalse(d['additive'])
    def test_median_not_averaged_and_has_basis(self):
        self.configure('costs',[dict(agg='median',field='amount_cents')],'元')
        for key,cat,value in [('A','甲',100),('B','乙',1000),('C','乙',2000)]:self.cost(key,cat,value)
        d=self.calc({'dimension':'category'});self.assertEqual(d['parent']['actual'],10);self.assertEqual(d['parent']['quantile']['valid_rows'],3);self.assertFalse(d['share_available']);self.assertEqual(d['rows'][0]['quantile']['weight'],'每条来源记录等权')
    def test_percentile_recomputes_from_scoped_values(self):
        self.configure('costs',[dict(agg='percentile',field='amount_cents',percentile=90)],'元')
        for key,cat,value in [('A','甲',100),('B','乙',1000),('C','乙',2000)]:self.cost(key,cat,value)
        d=self.calc({'dimension':'category'});self.assertEqual(d['parent']['actual'],18);self.assertEqual(d['rows'][0]['actual'],19)
    def test_ratio_uses_denominators_and_shows_percentage_points(self):
        self.configure('invoices',[dict(agg='ratio',field='tax_cents',denominator='net_cents')],'%')
        for key,customer,n,den in [('A','甲',1,2),('B','乙',9,10)]:self.record('invoices',dict(id=key,customer_id=customer,issued='2026-09-20',tax_cents=n,net_cents=den))
        d=self.calc({'dimension':'customer_id'});self.assertAlmostEqual(d['parent']['actual'],1000/12);self.assertEqual((d['parent']['numerator'],d['parent']['denominator']),(10,12));self.assertFalse(d['additive']);self.assertEqual(d['difference_unit'],'百分点')
    def test_zero_denominator_bucket_not_zero_rate(self):
        self.configure('invoices',[dict(agg='ratio',field='tax_cents',denominator='net_cents')],'%');self.record('invoices',dict(id='A',customer_id='甲',issued='2026-09-20',tax_cents=0,net_cents=0));d=self.calc({'dimension':'customer_id'});self.assertIsNone(d['rows'][0]['actual']);self.assertIsNone(d['rows'][0]['difference'])
    def test_distinct_not_summed_across_groups(self):
        self.configure('costs',[dict(agg='distinct',field='category')],'个');self.cost('A','甲',100);self.cost('B','甲',200);d=self.calc({'dimension':'id'});self.assertEqual(d['parent']['actual'],1);self.assertEqual(sum(x['actual'] for x in d['rows']),2);self.assertFalse(d['additive'])
    def test_derived_formula_recomputes_and_preserves_missingness(self):
        self.configure('costs',[dict(agg='sum',field='amount_cents')],'元','d0',[dict(label='换算总额',expression='m0',unit='元')]);self.cost('A','甲',200);self.cost('B','乙',100);d=self.calc({'dimension':'category'});self.assertEqual(d['parent']['actual'],3);self.assertFalse(d['additive']);self.assertEqual(d['kind'],'derived')
    def test_future_empty_not_zero(self):
        self.t.update(period_start='2026-10-05',period_end='2026-10-06');d=self.calc({'dimension':'id'});self.assertEqual(d['rows'],[]);self.assertIsNone(d['parent']['actual']);self.assertEqual(d['target']['state'],'future')
    def test_blocked_target_cannot_analyze(self):
        self.t['model_signature']='0'*64
        with self.assertRaises(ValueError):self.calc()
    def test_context_restricted_field_not_offered(self):
        original=b.access.permitted_fields
        with patch.object(b.access,'permitted_fields',side_effect=lambda user,ds:[f for f in original(user,ds) if ds!='products' or f['name']!='family']):self.assertNotIn('product.family',self.instance().option_map)
    def test_work_order_context_and_source_dependencies(self):
        self.configure('labor_entries',[dict(agg='count',field=None)],'条');self.record('products',dict(id='P',family='伺服'));self.record('work_orders',dict(id='W',product_id='P'));self.record('labor_entries',dict(id='L',work_order_id='W',started='2026-09-20T08:00:00',activity='加工'));d=self.calc({'dimension':'product.family'});self.assertEqual(d['rows'][0]['label'],'伺服');refs=self.instance().source_refs({'id':'L','work_order_id':'W'},{'path':'[]'},d['axis']);self.assertIn(dict(dataset='work_orders',key='W'),refs)
    def test_more_than_page_or_chart_limits_stays_complete(self):
        for i in range(30):self.record('units',dict(id='MORE'+str(i),assembly_at='2026-09-20T10:00:00',product_id='P'))
        self.save_targets();receipt=self.client.get('/api/targets/'+self.t['id']).json()['receipt'];q=dict(receipt=receipt,dimension='id');d=self.client.get('/api/targets/'+self.t['id']+'/breakdown',q).json();self.assertEqual((d['groups'],len(d['rows']),len(d['chart_rows']),d['parent']['source_rows']),(32,20,10,32));csvdata=self.client.get('/api/targets/'+self.t['id']+'/breakdown/export',q);rows=list(csv.reader(io.StringIO(csvdata.content.decode('utf-8-sig'))));self.assertEqual(len(rows),38)
    def test_api_evidence_scope_source_ref_and_stale_receipt(self):
        self.record('products',dict(id='P',family='伺服'));self.save_targets();key=self.t['id'];receipt=self.client.get('/api/targets/'+key).json()['receipt'];q=dict(receipt=receipt,dimension='id');root='/api/targets/'+key+'/breakdown';d=self.client.get(root,q).json();g=next(r for r in d['rows'] if r['label']=='U1')['token'];e=self.client.get(root+'/evidence',{**q,'group':g}).json();self.assertEqual([r['id'] for r in e['rows']],['U1']);self.assertEqual(self.client.get(root+'/sources',{**q,'group':g,'object_id':'U2'}).status_code,400);self.assertEqual(self.client.get(root+'/sources',{**q,'group':g,'object_id':'U1'}).status_code,200);self.assertEqual(self.client.get(root,{**q,'receipt':'old'}).status_code,409)
    def test_api_all_read_routes_authorized_and_no_writes(self):
        self.save_targets();before=list(Record.objects.values_list('values',flat=True));key=self.t['id'];receipt=self.client.get('/api/targets/'+key).json()['receipt'];self.client.get('/api/targets/'+key+'/breakdown',{'receipt':receipt});self.assertEqual(before,list(Record.objects.values_list('values',flat=True)));self.client.logout()
        for suffix in ['', '/evidence','/sources','/export']:self.assertEqual(self.client.get('/api/targets/'+key+'/breakdown'+suffix,{'receipt':receipt}).status_code,401)
        self.client.force_login(self.quality)
        for suffix in ['', '/evidence','/sources','/export']:self.assertEqual(self.client.get('/api/targets/'+key+'/breakdown'+suffix,{'receipt':receipt}).status_code,403)
