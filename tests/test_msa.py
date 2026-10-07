from copy import deepcopy
from datetime import datetime,timedelta
from django.test import SimpleTestCase
from app import msa
from app.msa_source_contract import issues
def fixture():
 s=dict(id='MS1',name='合成交叉试验',product_id='P1',spec_id='S1',instrument_id='G1',protocol_version='SIM.01',design='交叉可重复测量（模拟）',model='CROSSED_RANDOM_FULL',measurement_method='M1',unit='Ω',part_count=2,operator_count=2,repeat_count=2,started='2026-09-28T08:00:00',finished='2026-09-28T09:00:00',status='已结束',randomization='固定方案模拟随机顺序',owner_id='E1',conditions='合成工况',purpose='算法演练',note='不用于实际MSA资格')
 members=[dict(id='P'+str(i),study_id='MS1',kind='样件',unit_id='U'+str(i),operator_id=None,blind_label='P'+str(i),reference='SIM-P'+str(i),note='合成样件') for i in (1,2)]+[dict(id='A'+str(i),study_id='MS1',kind='操作员',unit_id=None,operator_id='E'+str(i),blind_label='A'+str(i),reference='SIM-A'+str(i),note='合成人员') for i in (1,2)]
 points=[]
 for i,a in enumerate((-1,1),1):
  for j,b in enumerate((-.25,.25),1):
   for k,e in enumerate((-.02,.02),1):
    n=len(points)+1;at=datetime(2026,9,28,8)+timedelta(minutes=n);interaction=.1 if i==j else -.1
    points.append(dict(id='O'+str(n),study_id='MS1',part_member_id='P'+str(i),operator_member_id='A'+str(j),repeat=k,run_order=n,measured=at.isoformat(),registered=(at+timedelta(seconds=2)).isoformat(),value=round(10+a+b+interaction+e,6),unit='Ω',method_version='M1',temperature_c=25,state='有效',reference='SIM-O'+str(n),note='合成观测'))
 spec=dict(id='S1',product_id='P1',test_code='R',unit='Ω',lsl=8,usl=12,effective='2026-09-01')
 instrument=dict(id='G1',parameter='R',unit='Ω',active_from='2026-01-01T00:00:00',retired=None)
 units={u:dict(id=u,product_id='P1',assembly_at='2026-09-27T00:00:00') for u in ('U1','U2')};people={e:dict(id=e,active=True) for e in ('E1','E2')}
 cal=[dict(id='C1',series='C',version=1,previous_id=None,status='已登记',instrument_id='G1',performed='2026-09-01T08:00:00',valid_from='2026-09-01T08:00:00',valid_until='2026-12-01T00:00:00',result='符合登记范围',parameter='R',unit='Ω',certificate_no='SIM-C1',registered='2026-09-01T08:10:00',reference='SIM-CAL')]
 return s,members,points,spec,instrument,units,people,cal
class MSAMethodTests(SimpleTestCase):
 def setUp(self):self.args=list(fixture())
 def result(self):return msa.analyze(*self.args)
 def test_independent_orthogonal_effects_exact_ss_and_variance(self):
  d=self.result();self.assertEqual(d['state'],'trial');r=d['result'];self.assertEqual(r['grand_mean'],10)
  rows={r['key']:r for r in r['anova']}
  for key,ss,df in [('part',8,1),('operator',.5,1),('interaction',.08,1),('repeatability',.0032,4),('total',8.5832,7)]:
   self.assertAlmostEqual(rows[key]['ss'],ss,places=13);self.assertEqual(rows[key]['df'],df)
  c={r['key']:r for r in r['components']}
  for key,v in [('repeatability',.0008),('operator',.105),('interaction',.0396),('part',1.98),('grr',.1454),('total',2.1254)]:self.assertAlmostEqual(c[key]['variance'],v,places=13)
  self.assertAlmostEqual(r['ss_reconciliation'],0,places=30)
 def test_percent_variance_sums_100_study_percent_does_not(self):
  c={r['key']:r for r in self.result()['result']['components']};keys=['repeatability','operator','interaction','part']
  self.assertAlmostEqual(sum(c[k]['variance_percent'] for k in keys),100);self.assertGreater(sum(c[k]['study_percent'] for k in keys),100)
  self.assertAlmostEqual(c['grr']['tolerance_percent'],100*6*(.1454**.5)/4)
 def test_full_interaction_never_selected_away(self):
  d=self.result();self.assertIn('交互',d['model_policy']);self.assertTrue(any(r['key']=='interaction' for r in d['result']['anova']));self.assertFalse(d['formal_qualification']);self.assertIsNone(d['cpk'])
 def test_input_not_modified_and_deterministic(self):
  before=deepcopy(self.args);self.assertEqual(self.result(),self.result());self.assertEqual(self.args,before)
 def test_missing_repeated_measure_not_zero_or_drop(self):
  self.args[2].pop();d=self.result();self.assertEqual(d['state'],'paused');self.assertIsNone(d['result']);self.assertEqual(d['coverage']['registered'],7)
  self.assertEqual(d['matrix'][-1]['missing_repeats'],[2])
 def test_duplicate_cell_preserved_pauses_balance(self):
  p={**self.args[2][0], 'id':'O9','run_order':9};self.args[2].append(p);d=self.result();self.assertEqual(d['coverage']['registered'],9);self.assertEqual(d['state'],'paused');self.assertEqual(d['matrix'][0]['duplicate_repeats'],[1])
 def test_missing_value_and_zero_are_different(self):
  self.args[2][0]['value']=0;d=self.result();self.assertEqual(d['state'],'trial');self.assertTrue(d['points'][0]['eligible'])
  self.args[2][0].update(value=None,state='缺测');d=self.result();self.assertEqual(d['state'],'paused');self.assertIsNone(d['points'][0]['value'])
 def test_mixed_units_or_method_pause_without_conversion(self):
  for field,value in [('unit','mΩ'),('method_version','M2')]:
   args=list(fixture());args[2][0][field]=value;d=msa.analyze(*args);self.assertEqual(d['state'],'paused');self.assertEqual(d['points'][0]['value'],8.83)
 def test_binary_counts_only_no_continuous_anova(self):
  self.args[0]['unit']=self.args[3]['unit']=self.args[4]['unit']=self.args[7][0]['unit']='bool'
  for i,p in enumerate(self.args[2]):p['unit']='bool';p['value']=i%2
  d=self.result();self.assertIsNone(d['result']);self.assertEqual(d['category_counts'],{'0':4,'1':4})
 def test_single_operator_does_not_invent_reproducibility(self):
  self.args[0]['operator_count']=1;d=self.result();self.assertEqual(d['state'],'paused');self.assertIsNone(d['result'])
 def test_zero_variation_has_no_percentage_or_ideal_qualification(self):
  for p in self.args[2]:p['value']=0
  d=self.result();self.assertEqual(d['state'],'paused');self.assertEqual(d['result']['grand_mean'],0)
  self.assertTrue(all(c['variance_percent'] is None for c in d['result']['components']));self.assertFalse(d['formal_qualification'])
 def test_negative_moment_estimates_kept_and_clamped_not_pooled(self):
  for n,p in enumerate(self.args[2]):p['value']=10+(-.1 if n%2==0 else .1)
  d=self.result();self.assertEqual(d['state'],'trial');c={c['key']:c for c in d['result']['components']}
  self.assertLess(c['interaction']['raw_variance'],0);self.assertTrue(c['interaction']['clamped']);self.assertEqual(c['interaction']['variance'],0);self.assertTrue(d['warnings'])
 def test_no_double_sided_tolerance_still_calculates_components(self):
  self.args[3]['lsl']=None;d=self.result();self.assertEqual(d['state'],'trial');self.assertTrue(all(c['tolerance_percent'] is None for c in d['result']['components']))
 def test_unknown_plan_end_preserves_rows_and_pauses(self):
  self.args[0]['finished']=None;d=self.result();self.assertEqual(d['state'],'paused');self.assertEqual(len(d['points']),8)
 def test_wrong_member_role_or_foreign_study_pauses(self):
  self.args[2][0]['operator_member_id']='P1';self.assertEqual(self.result()['state'],'paused')
  self.args[2][0]['operator_member_id']='A1';self.args[1][0]['study_id']='FOREIGN';self.assertEqual(self.result()['state'],'paused')
 def test_duplicate_same_sn_or_operator_not_new_independent_factor(self):
  self.args[1][1]['unit_id']='U1';self.args[1][3]['operator_id']='E1';d=self.result();self.assertEqual(d['state'],'paused');self.assertIsNone(d['result'])
 def test_future_or_unknown_measurements_not_accepted(self):
  for time in [None,'2026-10-10T08:00:00','2026-09-28T08:10:00+08:00']:
   self.args[2][0]['measured']=time;self.assertEqual(self.result()['state'],'paused')
 def test_retired_or_wrong_instrument_project_pauses(self):
  self.args[4]['retired']='2026-09-28T08:30:00';self.assertEqual(self.result()['state'],'paused')
  self.args[4]['retired']=None;self.args[4]['parameter']='IR';self.assertEqual(self.result()['state'],'paused')
 def test_expired_calibration_does_not_fall_back(self):
  self.args[7][0]['valid_until']='2026-09-28T08:30:00';d=self.result();self.assertEqual(d['calibration']['state'],'unavailable');self.assertIsNone(d['result'])
 def test_withdrawn_or_conflicting_latest_calibration_pauses(self):
  newer={**self.args[7][0],'id':'C2','version':2,'previous_id':'C1','status':'撤销','registered':'2026-09-26T08:00:00'};self.args[7].append(newer);self.assertEqual(self.result()['state'],'paused')
 def test_future_calibration_ignored_for_cutoff_not_backdated(self):
  self.args[7].append({**self.args[7][0],'id':'CF','series':'F','performed':'2026-10-05T08:00:00','registered':'2026-10-05T08:10:00'});d=self.result();self.assertEqual(d['state'],'trial');self.assertEqual(d['calibration']['selected']['id'],'C1')
 def test_calibration_change_inside_study_needs_split(self):
  self.args[7].append({**self.args[7][0],'id':'C2','series':'NEW','performed':'2026-09-28T08:30:00','registered':'2026-09-28T08:35:00'});self.assertEqual(self.result()['state'],'paused')
 def test_large_numeric_scale_pauses_instead_of_infinity(self):
  for n,p in enumerate(self.args[2]):p['value']=(-1 if n%2 else 1)*1e308
  d=self.result();self.assertEqual(d['state'],'paused');self.assertIsNone(d['result'])
 def test_tiny_tolerance_never_returns_infinite_percent(self):
  self.args[3].update(lsl=0,usl=1e-320);d=self.result();self.assertEqual(d['state'],'paused');self.assertIsNone(d['result'])
 def test_rows_and_members_capped_before_cross_product(self):
  with self.assertRaises(ValueError):msa.analyze(*self.args[:2],[self.args[2][0]]*5001,*self.args[3:])
  args=deepcopy(self.args);args[1]*=30
  with self.assertRaises(ValueError):msa.analyze(*args)
 def test_row_contract_preserves_literal_zero_and_missing(self):
  self.assertEqual(issues('msa_observations',dict(state='有效',value=0)),[]);self.assertTrue(issues('msa_observations',dict(state='缺测',value=0)))
