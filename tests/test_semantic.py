from copy import deepcopy
from unittest.mock import patch
from django.test import SimpleTestCase
from django.core.exceptions import ValidationError
from app.schema import SCHEMAS
from app.semantic import build,union_minutes
from app.analysis_engine import run_analysis

def fixture():
    d={k:[] for k in SCHEMAS}
    d['products']=[dict(id='P1',family='F1',power_kw=1.5,voltage=380)]
    d['customers']=[dict(id='C1',name='模拟客户',region='华东')]
    d['orders']=[dict(id='O1',customer_id='C1',order_date='2026-09-01')]
    d['order_lines']=[dict(id='L1',order_id='O1',product_id='P1',qty=10,unit_price_cents=1000,due='2026-09-25',custom_requirement='定制')]
    d['work_orders']=[dict(id='W1',product_id='P1',planned_end='2026-09-20',planned_qty=10,status='执行中')]
    d['allocations']=[dict(id='A1',work_order_id='W1',order_line_id='L1',qty=10,effective='2026-09-01')]
    d['units']=[dict(id=f'U{i}',work_order_id='W1',product_id='P1',assembly_at=f'2026-09-21T0{7+i}:00:00',stator_batch='B1',rotor_batch='B2',status='已发货') for i in [1,2]]
    d['test_specs']=[dict(id='S1',product_id='P1',version='A',mandatory=True,unit='Ω',lsl=0,usl=2)]
    for index,(unit,attempt,value) in enumerate([('U1',1,3),('U1',2,1),('U2',1,1)],1):
        result='不合格' if value>2 else '合格'
        d['test_sessions'].append(dict(id=f'T{index}',unit_id=unit,equipment_id='EQ1',spec_version='A',voided=False,complete=True,result=result,tested=f'2026-09-21T{9+index}:00:00',attempt=attempt))
        d['measurements'].append(dict(id=f'MS{index}',session_id=f'T{index}',spec_id='S1',value=value,unit='Ω',result=result))
    d['releases']=[dict(id='R1',unit_id='U1',session_id='T2',released='2026-09-21T13:00:00',status='批准放行'),dict(id='R2',unit_id='U2',session_id='T3',released='2026-09-21T14:00:00',status='批准放行')]
    d['delivery_plans']=[dict(id='DP1',order_line_id='L1',qty=1,due='2026-09-22'),dict(id='DP2',order_line_id='L1',qty=9,due='2026-09-25')]
    d['shipments']=[dict(id='SH1',delivery_plan_id='DP1',order_line_id='L1',qty=1,shipped='2026-09-22T10:00:00'),dict(id='SH2',delivery_plan_id='DP2',order_line_id='L1',qty=1,shipped='2026-09-26T10:00:00')]
    d['shipment_units']=[dict(id='SU1',unit_id='U1',shipment_id='SH1'),dict(id='SU2',unit_id='U2',shipment_id='SH2')]
    d['costs']=[dict(id='COST1',work_order_id='W1',category='材料',amount_cents=1000,occurred='2026-09-21'),dict(id='COST2',work_order_id='W1',category='人工',amount_cents=200,occurred='2026-09-21')]
    d['materials']=[dict(id='M1',name='轴承',category='轴承',unit='件',unit_cost_cents=100)]
    d['inventory_opening']=[dict(id='OP1',material_id='M1',lot='LOT1',location='A1',as_of='2026-09-01',qty=10,unit_cost_cents=100,status='冻结')]
    d['inventory_status_events']=[dict(id='ST1',material_id='M1',lot='LOT1',location='A1',occurred='2026-09-18T07:00:00',from_status='冻结',to_status='可用')]
    d['inventory_movements']=[dict(id='IM1',material_id='M1',lot='LOT1',location='A1',occurred='2026-09-19T08:00:00',qty_signed=-2)]
    d['suppliers']=[dict(id='SUP1',name='模拟供应商')]
    d['purchase_lines']=[dict(id='PO1',supplier_id='SUP1',material_id='M1',ordered='2026-09-01',due='2026-09-17',qty=10,status='部分到货')]
    d['receipts']=[dict(id='RC1',purchase_line_id='PO1',qty=4,received='2026-09-16T08:00:00',status='检验合格')]
    d['incoming_inspections']=[dict(id='QC1',receipt_id='RC1',inspected='2026-09-16T12:00:00',result='合格',disposition='批准入库')]
    d['invoices']=[dict(id='INV1',customer_id='C1',issued='2026-09-22',due='2026-09-25',net_cents=1000,tax_cents=130,status='部分收款')]
    d['payments']=[dict(id='PAY1',invoice_id='INV1',paid='2026-09-23',amount_cents=400),dict(id='PAY2',invoice_id='INV1',paid='2026-10-10',amount_cents=730)]
    d['equipment']=[dict(id='EQ1',name='检测台',workshop='质量',process='终检')]
    d['downtime']=[dict(id='DT1',equipment_id='EQ1',started='2026-09-22T10:00:00',finished='2026-09-22T11:00:00',reason='设备故障'),dict(id='DT2',equipment_id='EQ1',started='2026-09-22T10:30:00',finished='2026-09-22T11:30:00',reason='待料')]
    d['energy']=[dict(id='EM1',workshop='绕组',started='2026-09-21T23:30:00',ended='2026-09-22T00:30:00',kwh=10,tariff_cents=100)]
    return d

class SemanticGrainTests(SimpleTestCase):
    def setUp(self):self.data=fixture();self.views=build(self.data)
    def test_order_does_not_fan_out_through_plans_shipments_tests(self):
        r=self.views['bi_order_lines'][0]
        self.assertEqual(len(self.views['bi_order_lines']),1)
        self.assertEqual((r['qty'],r['shipped_qty'],r['produced_qty'],r['overdue_qty']),(10,2,2,8))
        self.assertEqual((r['on_time_plan_count'],r['due_plan_count']),(1,2));self.assertEqual(r['order_net_cents'],10000)
    def test_first_failure_survives_retest_and_work_order_aggregates(self):
        u=self.views['bi_units'][0];w=self.views['bi_work_orders'][0]
        self.assertEqual((u['session_count'],u['first_pass_count'],u['latest_result']),(2,0,'合格'))
        self.assertEqual((w['first_tested_count'],w['first_pass_count'],w['total_cost_cents'],w['unit_cost_cents']),(2,1,1200,600))
    def test_shared_work_order_does_not_invent_serial_order_assignment(self):
        self.data['order_lines'].append({**self.data['order_lines'][0],'id':'L2'})
        self.data['allocations'].append(dict(id='A2',work_order_id='W1',order_line_id='L2',qty=5,effective='2026-09-01'))
        result=build(self.data)
        self.assertTrue(all(r['produced_qty'] is None for r in result['bi_order_lines']))
        self.assertTrue(all(r['customer'] is None for r in result['bi_units']))
    def test_inventory_state_applies_only_after_effective_time(self):
        row=self.views['bi_inventory'][0];self.assertEqual((row['balance_qty'],row['available_qty'],row['reference_value_cents']),(8,8,800))
        self.data['inventory_status_events'][0]['occurred']='2026-10-05T07:00:00'
        row=build(self.data)['bi_inventory'][0];self.assertEqual((row['state'],row['available_qty']),('冻结',0))
    def test_procurement_uses_receipts_and_batch_disposition(self):
        row=self.views['bi_purchase'][0];self.assertEqual((row['received_qty'],row['accepted_qty'],row['overdue_qty'],row['on_time_line_count']),(4,4,6,0))
    def test_future_cash_is_excluded_and_aging_uses_due_date(self):
        row=self.views['bi_receivables'][0];self.assertEqual((row['paid_cents'],row['balance_cents'],row['overdue_days'],row['aging_bucket']),(400,730,6,'1—30天'))
    def test_overlapping_downtime_is_not_double_counted(self):
        row=self.views['bi_equipment_day'][0];self.assertEqual((row['downtime_events'],row['downtime_minutes'],row['fault_minutes']),(2,90,60))
    def test_cross_midnight_energy_is_split_without_gain(self):
        self.assertEqual([(r['date'],r['kwh'],r['energy_cost_cents']) for r in self.views['bi_energy_day']],[('2026-09-21',5,500),('2026-09-22',5,500)])
    def test_ratio_is_ratio_of_sums_and_zero_denominator_is_null(self):
        user=type('Admin',(),{'is_authenticated':True,'is_active':True,'is_superuser':True})()
        rows=[dict(id='1',family='F',first_pass_count=1,first_tested_count=1),dict(id='2',family='F',first_pass_count=0,first_tested_count=9),dict(id='3',family='Z',first_pass_count=0,first_tested_count=0)]
        with patch('app.analysis_engine.semantic.rows',return_value=rows):
            result=run_analysis(user,'bi_work_orders',{'dimension':'family','metrics':[{'agg':'ratio','field':'first_pass_count','denominator':'first_tested_count'}]})
        self.assertEqual(result['rows'][0]['m0'],10);self.assertIsNone(result['rows'][1]['m0'])
    def test_mixed_inventory_units_require_separate_groups(self):
        user=type('Admin',(),{'is_authenticated':True,'is_active':True,'is_superuser':True})()
        rows=[dict(id='1',unit='件',balance_qty=10),dict(id='2',unit='kg',balance_qty=20)]
        with patch('app.analysis_engine.semantic.rows',return_value=rows):
            with self.assertRaises(ValidationError):run_analysis(user,'bi_inventory',{'dimension':'','metrics':[{'agg':'sum','field':'balance_qty'}]})
            r=run_analysis(user,'bi_inventory',{'dimension':'unit','metrics':[{'agg':'sum','field':'balance_qty'}],'chart':'table'})
            self.assertEqual(len(r['rows']),2)
            with self.assertRaises(ValidationError):run_analysis(user,'bi_inventory',{'dimension':'unit','metrics':[{'agg':'sum','field':'balance_qty'}],'chart':'bar'})
