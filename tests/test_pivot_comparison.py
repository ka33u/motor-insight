import copy
from unittest.mock import patch
from django.test import SimpleTestCase
from app import analysis_engine as eng, pivot_comparison as pc
from .test_derived import ADMIN, ROWS, source_tables
from .test_analysis_pivot import model


class PivotComparisonTests(SimpleTestCase):
    def calc(self, rows=None, definition=None, dataset='bi_work_orders'):
        with patch('app.analysis_engine.semantic.rows', return_value=ROWS if rows is None else rows), patch('app.bi_scope.analytics.tables', return_value=source_tables()), patch('app.analysis_pivot.receipt', return_value={}):
            return eng.run_analysis(ADMIN, dataset, definition or model())

    def total(self, a, b, key='d0'):
        return next(v for v in pc.compare(a, b)['matrix']['grand_total']['values'] if v['key'] == key)

    def test_same_range_zero_and_input_immutable(self):
        r = self.calc(); before = copy.deepcopy(r)
        c = pc.compare(r, r)
        self.assertEqual(self.total(r, r)['delta'], 0)
        self.assertEqual(c['rule_version'], pc.VERSION)
        self.assertEqual(r, before)
        self.assertEqual(len(c['matrix']['cells']), 4)

    def test_average_totals_are_not_sum_of_row_differences(self):
        d = {**model(), 'metrics': [{'agg': 'avg', 'field': 'produced_qty'}], 'derived': [], 'display_metric': 'm0'}
        a = self.calc([{**r, 'produced_qty': v} for r, v in zip(ROWS, [1, 9, 8])], d)
        b = self.calc([{**r, 'produced_qty': v} for r, v in zip(ROWS, [1, 1, 8])], d)
        c = pc.compare(a, b)
        self.assertAlmostEqual(self.total(a, b, 'm0')['delta'], 8/3)
        self.assertEqual(sum(x['values'][0]['delta'] for x in c['matrix']['row_totals']), 4)

    def test_distinct_total_recomputed_across_groups(self):
        d = {**model(), 'metrics': [{'agg': 'distinct', 'field': 'product_id'}], 'derived': [], 'display_metric': 'm0'}
        a = self.calc([ROWS[0], ROWS[2]], d)
        b = self.calc([ROWS[0], {**ROWS[2], 'product_id': 'P1'}], d)
        self.assertEqual(self.total(a, b, 'm0')['delta'], 1)
        self.assertEqual(sum(x['values'][0]['delta'] for x in pc.compare(a,b)['matrix']['row_totals']), 0)

    def test_ratio_uses_percentage_points(self):
        d = {**model(), 'metrics': [{'agg': 'ratio', 'field': 'released_qty', 'denominator': 'produced_qty'}], 'derived': [], 'display_metric': 'm0'}
        a = self.calc([{**ROWS[0], 'produced_qty': 10, 'released_qty': 8}], d)
        b = self.calc([{**ROWS[0], 'produced_qty': 10, 'released_qty': 6}], d)
        v = self.total(a,b,'m0')
        self.assertEqual(v['delta'],20); self.assertEqual(v['delta_unit'],'百分点'); self.assertIsNone(v['relative_pct'])

    def test_derived_percentage_uses_points(self):
        d = model(); d['metrics'][0]['field']='released_qty'; d['derived'][0]['unit']='%'
        a = self.calc([{**ROWS[0], 'produced_qty': 10, 'released_qty': 8}],d)
        b = self.calc([{**ROWS[0], 'produced_qty': 10, 'released_qty': 6}],d)
        self.assertEqual(self.total(a,b)['delta_unit'],'百分点')

    def test_cost_derived_compares_quotients(self):
        a = self.calc(); b = self.calc([{**r, 'total_cost_cents': r['total_cost_cents']*2} for r in ROWS])
        v=self.total(a,b)
        self.assertEqual(v['delta'],-41); self.assertEqual(v['relative_pct'],-50); self.assertEqual(v['delta_unit'],'元/台')

    def test_only_one_side_group_not_zero(self):
        a=self.calc(); b=self.calc([ROWS[0]])
        rows=pc.compare(a,b)['matrix']['row_totals']; v=next(x for x in rows if x['reference_rows'] is None)
        self.assertIsNone(v['values'][0]['reference']); self.assertIsNone(v['values'][0]['delta']); self.assertIn('分组',v['values'][0]['reason'])

    def test_empty_intersection_not_missing_axis(self):
        r=self.calc(); c=pc.compare(r,r)
        x=next(x for x in c['matrix']['cells'] if x['primary_rows']==0)
        self.assertEqual(x['reference_rows'],0); self.assertIsNone(x['values'][0]['delta']); self.assertIn('无来源对象',x['values'][0]['reason'])

    def test_both_empty_and_one_empty(self):
        empty=self.calc([])
        for a,b in [(empty,empty),(self.calc(),empty)]:
            self.assertIsNone(self.total(a,b)['delta']); self.assertIsNone(self.total(a,b)['relative_pct'])

    def test_zero_and_negative_baseline(self):
        a=self.calc()
        for value in (0,-2):
            b=self.calc([{**r,'total_cost_cents':value} for r in ROWS]);v=self.total(a,b,'m0')
            self.assertIsNotNone(v['delta']);self.assertIsNone(v['relative_pct']);self.assertIn('零或负数',v['reason'])

    def test_dynamic_units_same_axis_pause_difference(self):
        d={'dimension':'category','pivot':{'dimension':'material_id'},'chart':'pivot','metrics':[{'agg':'sum','field':'balance_qty'}]}
        row={'id':'I1','category':'原料','material_id':'M1','balance_qty':2}
        a=self.calc([{**row,'unit':'kg'}],d,'bi_inventory');b=self.calc([{**row,'unit':'件'}],d,'bi_inventory')
        v=self.total(a,b,'m0');self.assertIsNone(v['delta']);self.assertEqual((v['primary_unit'],v['reference_unit']),('kg','件'));self.assertIn('单位不同',v['reason'])

    def test_blocked_margins_keep_source_counts(self):
        d={'dimension':'unit','pivot':{'dimension':'category'},'chart':'pivot','metrics':[{'agg':'sum','field':'balance_qty'}]}
        rows=[{'id':'I1','category':'原料','unit':'kg','balance_qty':2},{'id':'I2','category':'原料','unit':'件','balance_qty':3}]
        r=self.calc(rows,d,'bi_inventory');c=pc.compare(r,r)
        self.assertEqual(c['matrix']['grand_total']['primary_rows'],2);self.assertIsNone(self.total(r,r,'m0')['delta']);self.assertIn('当前侧',self.total(r,r,'m0')['reason'])

    def test_missing_input_reason_is_per_measure(self):
        r=self.calc([{**ROWS[0],'produced_qty':None}]);v=self.total(r,r)
        self.assertIsNone(v['delta']);self.assertIn('缺失',v['reason']);self.assertEqual(self.total(r,r,'m0')['delta'],0)

    def test_identity_not_label_matches(self):
        a=self.calc([{**r,'family':f} for r,f in zip(ROWS,[None,'未填写',1])]);b=self.calc([{**ROWS[0],'family':'1'},{**ROWS[1],'family':'合计'}]);c=pc.compare(a,b)
        self.assertEqual(len(c['matrix']['rows']),5);self.assertEqual(len({x['key'] for x in c['matrix']['rows']}),5)
        self.assertTrue(all(v['delta'] is None for x in c['matrix']['row_totals'] for v in x['values']))
        self.assertIsNotNone(self.total(a,b,'m0')['delta'])

    def test_merged_limits_reject_before_truncating(self):
        for axis,limit in [('rows',200),('columns',50)]:
            a=self.calc();b=copy.deepcopy(a)
            a['pivot'][axis]=[{'key':str(i),'label':str(i)} for i in range(limit)]
            b['pivot'][axis]=[{'key':'extra','label':'extra'}]
            c=pc.compare(a,b);self.assertTrue(c['blocked']);self.assertNotIn('matrix',c);self.assertIn('未截断',c['note'])

    def test_definition_change_truncation_and_nonpivot_blocked(self):
        a=self.calc()
        for mutation in ['definition','truncated','pivot']:
            b=copy.deepcopy(a)
            if mutation=='definition':b['resolved_definition']['dimension']='product_id'
            elif mutation=='truncated':b['truncated']=True
            else:b.pop('pivot')
            self.assertTrue(pc.compare(a,b)['blocked'])

    def test_numeric_overflow_and_text_do_not_create_infinity(self):
        for av,bv,reason in [(1e308,-1e308,'差值超出'),(1e308,1e-308,'相对变化超出'),('x','y','非数值')]:
            c=lambda v:dict(m0=v,empty=False,blocked='',row_count=1)
            v=pc.value_pair(c(av),c(bv),{'key':'m0'},'元')
            self.assertIn(reason,v['reason']);self.assertIsNone(v['relative_pct'])

    def test_export_complete_cells_margins_with_identity_and_rules(self):
        r=self.calc();c=pc.compare(r,r);rows=pc.export_rows(c)
        self.assertEqual(len(rows),1+9*3);self.assertEqual(sum(x[1]=='总计' for x in rows[1:]),3)
        self.assertIn('行身份',rows[0]);self.assertTrue(all(x[0]==pc.VERSION for x in rows[1:]));self.assertTrue(all(len(x)==len(rows[0]) for x in rows))
