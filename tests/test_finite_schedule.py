from copy import deepcopy
from django.test import SimpleTestCase
from app import finite_schedule as engine
from app.finite_schedule_contract import issues

def fixture():
 s=dict(id='SP1',name='独立试排',version='V1',baseline='2026-10-02T08:00:00',horizon_end='2026-10-02T12:00:00',owner_id='E1',scope='独立模拟',assumptions='单容量假设',reference='SIM')
 j=dict(id='J1',study_id='SP1',product_id='P1',route_version='V1',qty=2,released=s['baseline'],due='2026-10-02T10:00:00',priority=1,family='A',task_count=4,edge_count=4,reference='SIM')
 routes={k:dict(id=k,product_id='P1',version='V1',mandatory=True,process=p,branch=b) for k,p,b in [('A','冲片','定子'),('B','转子铸铝','转子'),('C','装配','整机')]}
 deps={k:dict(id=k,product_id='P1',from_route_id=a,to_route_id='C') for k,a in [('AC','A'),('BC','B')]}
 tasks=[dict(id=k,job_id='J1',route_id=r,portion=portion,lot_qty=q,unit_minutes=m,basis='SIM') for k,r,portion,q,m in [('TA','A','BULK',2,10),('TB','B','BULK',2,5),('TC1','C','U001',1,10),('TC2','C','U002',1,10)]]
 edges=[dict(id=f'D{i}',study_id='SP1',from_task_id=a,to_task_id=b,dependency_id=dep,lag_minutes=lag,basis='SIM') for i,(a,b,dep,lag) in enumerate([('TA','TC1','AC',5),('TA','TC2','AC',5),('TB','TC1','BC',10),('TB','TC2','BC',10)],1)]
 resources={k:dict(id=k,process=p,capacity=1,max_batch_qty=q,station=k,effective='2026-01-01') for k,p,q in [('R1','冲片',60),('R2','转子铸铝',60),('R3','装配',1)]}
 options=[dict(id='O'+t['id'],task_id=t['id'],resource_id={'A':'R1','B':'R2','C':'R3'}[t['route_id']],setup_minutes=5,basis='SIM') for t in tasks]
 windows=[dict(id='W'+k,study_id='SP1',resource_id=k,started=s['baseline'],finished=s['horizon_end'],basis='SIM') for k in resources]
 tables=dict(schedule_jobs=[j],schedule_tasks=tasks,schedule_edges=edges,schedule_options=options,schedule_windows=windows,schedule_blocks=[])
 for f,ds in [('job_count','schedule_jobs'),('task_count','schedule_tasks'),('edge_count','schedule_edges'),('option_count','schedule_options'),('window_count','schedule_windows'),('block_count','schedule_blocks')]:s[f]=len(tables[ds])
 refs=dict(products={'P1':{'id':'P1'}},employees={'E1':{'id':'E1'}},routes=routes,route_dependencies=deps,production_resources=resources)
 return s,tables,refs
class FiniteScheduleTests(SimpleTestCase):
 def setUp(self):self.args=list(fixture())
 def result(self):
  # Mutations in these algorithm tests deliberately define a new complete input.
  for f,ds in [('job_count','schedule_jobs'),('task_count','schedule_tasks'),('edge_count','schedule_edges'),('option_count','schedule_options'),('window_count','schedule_windows'),('block_count','schedule_blocks')]:self.args[0][f]=len(self.args[1][ds])
  return engine.analyze(*self.args)
 def test_hand_calculated_parallel_join_and_batch_qty(self):
  d=self.result();t={t['id']:t for t in d['tasks']};self.assertEqual(d['state'],'trial');self.assertEqual(t['TA']['finished'],'2026-10-02T08:25:00');self.assertEqual(t['TB']['finished'],'2026-10-02T08:15:00');self.assertEqual(t['TC1']['started'],'2026-10-02T08:30:00');self.assertEqual(t['TC2']['finished'],'2026-10-02T08:55:00');self.assertEqual(d['summary']['qty'],2)
 def test_no_input_mutation_and_determinism(self):
  before=deepcopy(self.args);self.assertEqual(self.result(),self.result());self.assertEqual(self.args,before)
 def test_first_setup_same_family_no_second_setup(self):
  d=self.result();t={t['id']:t for t in d['tasks']};self.assertEqual(t['TC1']['setup_minutes'],5);self.assertEqual(t['TC2']['setup_minutes'],0)
 def test_resource_tail_and_nonoverlap(self):
  d=self.result();tasks=[t for t in d['tasks'] if t['resource_id']=='R3'];self.assertGreaterEqual(tasks[1]['started'],tasks[0]['finished']);self.assertEqual(d['resources'][2]['busy_minutes'],25)
 def test_load_denominator_and_clipped_block(self):
  self.args[1]['schedule_blocks']=[dict(id='X',study_id='SP1',resource_id='R1',started='2026-10-02T07:00:00',finished='2026-10-02T08:10:00',reason='保养',basis='SIM')];d=self.result();self.assertEqual(d['resources'][0]['available_minutes'],230);self.assertEqual(d['tasks'][0]['started'],'2026-10-02T08:10:00')
 def test_boundary_touching_block_does_not_delay(self):
  self.args[1]['schedule_blocks']=[dict(id='X',study_id='SP1',resource_id='R1',started='2026-10-02T08:25:00',finished='2026-10-02T09:00:00',reason='保养',basis='SIM')];self.assertEqual(self.result()['tasks'][0]['started'],'2026-10-02T08:00:00')
 def test_overlapping_task_block_shifts_whole_task(self):
  self.args[1]['schedule_blocks']=[dict(id='X',study_id='SP1',resource_id='R1',started='2026-10-02T08:20:00',finished='2026-10-02T09:00:00',reason='保养',basis='SIM')];self.assertEqual(self.result()['tasks'][0]['started'],'2026-10-02T09:00:00')
 def test_max_batch_qty_blocks_and_propagates(self):
  self.args[2]['production_resources']['R1']['max_batch_qty']=1;d=self.result();self.assertEqual(d['summary']['blocked_tasks'],3);self.assertIsNone(d['jobs'][0]['finished']);self.assertEqual(d['tasks'][-1]['root_tasks'],['TA'])
 def test_missing_candidate_does_not_claim_delivery(self):
  self.args[1]['schedule_options'].pop();d=self.result();self.assertEqual(d['summary']['complete_jobs'],0);self.assertEqual(d['summary']['blocked_jobs'],1);self.assertIn('没有登记',d['tasks'][-1]['reason'])
 def test_horizon_not_crossed_or_task_split(self):
  self.args[0]['horizon_end']='2026-10-02T08:20:00';d=self.result();self.assertEqual(d['summary']['blocked_tasks'],3);self.assertEqual(d['summary']['late_jobs'],0)
 def test_late_and_blocked_are_distinct(self):
  self.args[1]['schedule_jobs'][0]['due']='2026-10-02T08:50:00';d=self.result();self.assertEqual(d['summary']['late_jobs'],1);self.assertEqual(d['summary']['blocked_jobs'],0);self.assertEqual(d['jobs'][0]['lateness_minutes'],5)
 def test_release_time_and_lag(self):
  self.args[1]['schedule_jobs'][0]['released']='2026-10-02T09:00:00';d=self.result();self.assertEqual(d['tasks'][0]['started'],'2026-10-02T09:00:00');self.assertEqual(d['tasks'][2]['dependency_ready'],'2026-10-02T09:30:00')
 def test_multiple_windows_lunch_gap_and_setup_together(self):
  self.args[1]['schedule_windows'][0]['finished']='2026-10-02T08:20:00';self.args[1]['schedule_windows'].append(dict(id='Wextra',study_id='SP1',resource_id='R1',started='2026-10-02T09:00:00',finished='2026-10-02T12:00:00',basis='SIM'));self.assertEqual(self.result()['tasks'][0]['started'],'2026-10-02T09:00:00')
 def test_overlapping_calendars_pause_no_healthy_zero(self):
  self.args[1]['schedule_windows'].append({**self.args[1]['schedule_windows'][0],'id':'Wduplicate'});d=self.result();self.assertEqual(d['state'],'paused');self.assertIsNone(d['summary']);self.assertEqual(d['tasks'],[])
 def test_overlapping_blocks_pause(self):
  a=dict(id='X1',study_id='SP1',resource_id='R1',started='2026-10-02T09:00:00',finished='2026-10-02T10:00:00',reason='SIM',basis='SIM');self.args[1]['schedule_blocks']=[a,{**a,'id':'X2'}];self.assertEqual(self.result()['state'],'paused')
 def test_cycle_is_rejected(self):
  e={**self.args[1]['schedule_edges'][0],'id':'DC','from_task_id':'TC1','to_task_id':'TA'};self.args[1]['schedule_edges'].append(e);self.assertIn('依赖存在环路；所有试排暂停',self.result()['issues'])
 def test_deleted_task_or_dependency_not_silently_omitted(self):
  for ds in ['schedule_tasks','schedule_edges']:
   self.args=list(fixture());self.args[1][ds].pop();self.assertEqual(self.result()['state'],'paused')
 def test_wrong_route_version_or_missing_reference_pauses(self):
  self.args[1]['schedule_jobs'][0]['route_version']='OTHER';self.assertEqual(self.result()['state'],'paused');self.args=list(fixture());self.args[2]['products'].clear();self.assertEqual(self.result()['state'],'paused')
 def test_route_task_qty_reconciliation(self):
  self.args[1]['schedule_tasks'][2]['lot_qty']=2;self.assertEqual(self.result()['state'],'paused')
 def test_duplicate_portion_is_not_another_unit(self):
  self.args[1]['schedule_tasks'][3]['portion']='U001';self.assertEqual(self.result()['state'],'paused')
 def test_resource_process_capacity_and_effective_are_checked(self):
  for field,value in [('capacity',2),('process','OTHER'),('effective','2027-01-01')]:
   self.args=list(fixture());self.args[2]['production_resources']['R1'][field]=value;self.assertEqual(self.result()['state'],'paused')
 def test_fractional_minute_rounding_busy_does_not_round_twice(self):
  self.args[1]['schedule_tasks'][0]['unit_minutes']=.01;self.args[1]['schedule_options'][0]['setup_minutes']=0;d=self.result();self.assertEqual(d['tasks'][0]['finished'],'2026-10-02T08:00:02');self.assertEqual(d['resources'][0]['busy_minutes'],2/60)
 def test_unsupported_policy_or_oversized_horizon(self):
  with self.assertRaises(ValueError):engine.analyze(*self.args,'arbitrary')
  self.args[0]['horizon_end']='2027-10-02T08:00:00'
  with self.assertRaises(ValueError):self.result()
 def test_import_numeric_and_local_datetime_contract(self):
  self.assertTrue(issues('schedule_tasks',dict(lot_qty=0,unit_minutes=float('nan'))));self.assertTrue(issues('schedule_windows',dict(started='2026-10-02T08:00:00+08:00')))
 def test_declared_population_cannot_silently_shrink(self):
  self.args[1]['schedule_options'].pop();d=engine.analyze(*self.args);self.assertEqual(d['state'],'paused');self.assertIsNone(d['summary'])
