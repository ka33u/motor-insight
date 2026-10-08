from copy import deepcopy
from decimal import Decimal
from unittest.mock import patch
from django.test import SimpleTestCase
from django.contrib.auth.models import User,Group
from app import joint_schedule, finite_schedule, crew_schedule, joint_material_evidence as evidence
from app.models import Record,AuditEvent
from .test_joint_schedule import fixture,declare
from .test_crew_schedule import declare as declare_crew
from .test_platform import PlatformCase

class MaterialEvidenceTests(SimpleTestCase):
    def setUp(self):self.args=list(fixture())
    def result(self):
        declare(*self.args[:2]);return joint_schedule.analyze(*self.args)
    def build(self,material='M1',unit='kg'):return evidence.build(self.result(),material,unit)

    def test_hand_oracle_whole_batch_not_portion_sum(self):
        d,_=self.build();self.assertEqual(d['summary'],dict(demands=2,reserved_demands=2,jobs=1,lots=1,allocations=2,required_qty='5',reserved_qty='5',unreserved_qty='0',total_supply_qty='5',excluded_qty='0',horizon_remaining_qty='0',outside_remaining_qty='0'))
        a,_=self.build('M2','件');self.assertEqual(a['demands'][0]['task_ids'],['TC1','TC2']);self.assertEqual(a['summary']['required_qty'],'2');self.assertEqual(a['summary']['allocations'],1)

    def test_shared_shortage_preserves_partial_job_reservation(self):
        self.args[1]['joint_supplies'][0]['qty']=4;d,_=self.build()
        self.assertEqual(d['summary']['reserved_qty'],'3');self.assertEqual(d['summary']['unreserved_qty'],'2');self.assertEqual(d['summary']['horizon_remaining_qty'],'1')
        self.assertEqual(d['balance']['initial_supply_gap_qty'],'1');self.assertEqual(d['jobs'][0]['state'],'blocked')
        self.assertEqual(d['demands'][1]['reservation'],None);self.assertTrue(any(t['reason'] for t in d['tasks']))

    def test_two_batch_pool_preserves_each_policy_original_recipient(self):
        parent,refs=self.args[2:];base,ct=parent['base'],parent['tables'];bt=base['tables']
        bt['schedule_jobs'][0]['priority']=2
        bt['schedule_jobs'].append({**bt['schedule_jobs'][0],'id':'J2','priority':1,'due':'2026-10-02T11:00:00'})
        for ds in ('schedule_tasks','schedule_edges','schedule_options'):
            added=[]
            for old in bt[ds]:
                row={**old,'id':old['id']+'-2'}
                if ds=='schedule_tasks':row['job_id']='J2'
                if ds=='schedule_edges':row['from_task_id']+='-2';row['to_task_id']+='-2'
                if ds=='schedule_options':row['task_id']+='-2'
                added.append(row)
            bt[ds].extend(added)
        ct['crew_candidates'].extend([{**c,'id':c['id']+'-2','task_id':c['task_id']+'-2'} for c in list(ct['crew_candidates'])])
        self.args[1]['joint_demands'].extend([{**d,'id':d['id']+'-2','job_id':'J2'} for d in list(self.args[1]['joint_demands'])])
        for field,ds in [('job_count','schedule_jobs'),('task_count','schedule_tasks'),('edge_count','schedule_edges'),('option_count','schedule_options')]:base['study'][field]=len(bt[ds])
        cs=parent['result']['study'];declare_crew(cs,ct)
        for policy,winner in [('due','J1'),('priority','J2')]:
            base['result']=finite_schedule.analyze(base['study'],bt,refs,policy);parent['result']=crew_schedule.analyze(cs,ct,base,refs)
            d,_=self.build();self.assertEqual(d['summary']['jobs'],2);self.assertEqual(d['summary']['required_qty'],'10');self.assertEqual(d['summary']['reserved_qty'],'5')
            self.assertEqual({a['job_id'] for a in d['allocations']},{winner})
            self.assertEqual({j['id'] for j in d['jobs'] if j['reserved_qty']=='5'},{winner})

    def test_unreserved_due_to_people_does_not_claim_material_shortage(self):
        self.args[2]['tables']['crew_windows']=[];d,_=self.build()
        self.assertEqual(d['summary']['unreserved_qty'],'5');self.assertEqual(d['balance']['initial_supply_gap_qty'],'0');self.assertEqual(d['summary']['horizon_remaining_qty'],'5')
        self.assertEqual(d['allocations'],[])

    def test_isolated_whole_lot_excludes_unavailable_part_once(self):
        self.args[1]['joint_supplies'][0].update(status='隔离',unavailable_qty=1);d,_=self.build()
        self.assertEqual(d['summary']['excluded_qty'],'5');self.assertEqual(d['lots'][0]['unavailable_qty'],'1');self.assertEqual(d['lots'][0]['usable_qty'],'0')

    def test_partial_exclusion_retains_exact_balance(self):
        self.args[1]['joint_supplies'][0]['unavailable_qty']=1;d,_=self.build()
        self.assertEqual(d['summary']['excluded_qty'],'1');self.assertEqual(d['summary']['reserved_qty'],'3');self.assertEqual(d['summary']['horizon_remaining_qty'],'1')

    def test_horizon_end_is_exclusive_and_late_stock_stays_visible(self):
        for delta in ('2026-10-02T12:00:00','2026-10-02T13:00:00'):
            self.args[1]['joint_supplies'][0].update(kind='未来到料假设',available_from=delta);d,_=self.build()
            self.assertEqual(d['summary']['outside_remaining_qty'],'5');self.assertEqual(d['summary']['horizon_remaining_qty'],'0');self.assertFalse(d['lots'][0]['inside_horizon'])

    def test_fifo_split_keeps_original_global_sequence(self):
        lots=self.args[1]['joint_supplies'];lots[0]['qty']=1
        lots.extend([{**lots[0],'id':'L0','qty':2},{**lots[0],'id':'L3','qty':2,'kind':'未来到料假设','available_from':'2026-10-02T09:00:00'}]);d,_=self.build()
        self.assertEqual([a['supply_id'] for a in d['allocations']],['L0','L1','L3']);self.assertEqual([a['sequence'] for a in d['allocations']],[1,2,3])
        self.assertEqual(d['allocations'][-1]['reserved_at'],'2026-10-02T09:00:00')

    def test_decimal_fraction_accounting_does_not_use_float_sums(self):
        lots=self.args[1]['joint_supplies'];lots[0]['qty']=.1
        lots.extend([{**lots[0],'id':'L0','qty':.2},{**lots[0],'id':'L3','qty':4.7}]);d,_=self.build()
        self.assertEqual(d['summary']['total_supply_qty'],'5');self.assertEqual(d['summary']['reserved_qty'],'5');self.assertEqual(d['summary']['horizon_remaining_qty'],'0')

    def test_supply_only_pair_retains_stock_without_fabricated_demand(self):
        self.args[3]['materials']['M3']=dict(id='M3',name='模拟备件',unit='件')
        self.args[1]['joint_supplies'].append({**self.args[1]['joint_supplies'][1],'id':'SPARE','material_id':'M3','qty':10});d,_=self.build('M3','件')
        self.assertEqual(d['summary']['demands'],0);self.assertEqual(d['summary']['horizon_remaining_qty'],'10');self.assertEqual(d['jobs'],[]);self.assertEqual(d['tasks'],[])

    def test_zero_stock_is_not_missing_data(self):
        self.args[1]['joint_supplies'][0]['qty']=0;d,_=self.build()
        self.assertEqual(d['summary']['total_supply_qty'],'0');self.assertEqual(d['balance']['initial_supply_gap_qty'],'5');self.assertEqual(len(d['lots']),1)

    def test_pair_isolation_and_direct_sources_include_all_peer_needs(self):
        d,refs=self.build();self.assertEqual({r['id'] for r in d['demands']},{'D1','D2'});self.assertEqual({r['id'] for r in d['lots']},{'L1'})
        for ds,key in [('joint_demands','D1'),('joint_demands','D2'),('joint_bindings','K1'),('bom','B1'),('materials','M1'),('joint_supplies','L1'),('schedule_tasks','TA'),('schedule_jobs','J1')]:self.assertIn((ds,key),refs)
        self.assertNotIn(('joint_demands','D3'),refs);self.assertNotIn(('joint_supplies','L2'),refs)

    def test_different_material_or_unit_never_merges(self):
        for material,unit in [('M1','件'),('M2','kg'),('ABSENT','kg')]:
            with self.assertRaises(ValueError):self.build(material,unit)

    def test_paused_and_incomplete_results_are_rejected(self):
        for change in [lambda d:d.update(state='paused'),lambda d:d['tasks'].pop(),lambda d:d['demands'].pop(),lambda d:d['balances'].append(d['balances'][0])]:
            d=self.result();change(d)
            with self.assertRaises(ValueError):evidence.build(d,'M1','kg')

    def test_bad_quantities_and_ledger_conservation_are_rejected(self):
        for value in ['NaN','Infinity','-1','4.999',None]:
            d=self.result();d['balances'][0]['required_qty']=value
            with self.assertRaises(ValueError):evidence.build(d,'M1','kg')
        d=self.result();d['lots'][0]['remaining_qty']='1'
        with self.assertRaises(ValueError):evidence.build(d,'M1','kg')

    def test_duplicate_cross_unit_or_foreign_allocations_are_rejected(self):
        for change in [lambda d:d['reservations'].append(d['reservations'][0]),lambda d:d['reservations'][0].update(unit='件'),lambda d:d['reservations'][0].update(task_id='ABSENT'),lambda d:d['reservations'][0].update(job_id='OTHER')]:
            d=self.result();change(d)
            with self.assertRaises(ValueError):evidence.build(d,'M1','kg')

    def test_wrong_trigger_time_and_disguised_partial_reservation_are_rejected(self):
        for change in [lambda d:d['reservations'][0].update(reserved_at='2026-10-02T07:00:00'),lambda d:d['reservations'][0].update(available_from='2026-10-02T09:00:00'),lambda d:d['demands'][0].update(state='unreserved'),lambda d:d['tasks'][0].update(demand_ids=[])]:
            d=self.result();change(d)
            with self.assertRaises(ValueError):evidence.build(d,'M1','kg')

    def test_allowlist_and_detached_result(self):
        d=self.result()
        for name in ('balances','lots','demands','jobs','tasks','reservations'):
            for row in d[name]:row.update(hourly_cents=987654321,private_note='PRIVATE-SIM')
        before=deepcopy(d);report,_=evidence.build(d,'M1','kg')
        self.assertNotIn('PRIVATE-SIM',str(report));self.assertNotIn('hourly_cents',str(report));report['tasks'][0]['root_tasks'].append('CHANGE');self.assertEqual(d,before)

class MaterialEvidenceAPITests(PlatformCase):
    def setUp(self):
        super().setUp();study,tables,parent,refs=fixture()
        self.record('joint_studies',study);self.record('crew_studies',parent['result']['study']);self.record('schedule_studies',parent['base']['study'])
        for ds,rows in {**tables,**parent['tables'],**parent['base']['tables']}.items():
            for row in rows:self.record(ds,row)
        for ds,rows in refs.items():
            for row in rows.values():self.record(ds,row)
        self.client.force_login(self.admin)
    def board(self):return self.client.get('/api/joint-schedule/MP1').json()
    def detail(self,receipt=None,material='M1',unit='kg',**extra):return self.client.get('/api/joint-schedule/MP1/materials/'+material,dict(receipt=receipt or self.board()['receipt'],unit=unit,**extra))

    def test_detail_reads_original_ledger_without_writes(self):
        records=list(Record.objects.order_by('id').values());audit=AuditEvent.objects.count();r=self.detail()
        self.assertEqual(r.status_code,200,r.content);self.assertEqual(r['Cache-Control'],'no-store');self.assertEqual(r.json()['evidence']['summary']['required_qty'],'5')
        self.assertEqual(list(Record.objects.order_by('id').values()),records);self.assertEqual(AuditEvent.objects.count(),audit)

    def test_exact_peer_sources_and_original_permission(self):
        d=self.detail().json();keys={(s['dataset'],s['key']) for s in d['sources']}
        for pair in [('joint_studies','MP1'),('joint_demands','D2'),('joint_supplies','L1'),('schedule_tasks','TB'),('bom','B2')]:self.assertIn(pair,keys)
        self.assertNotIn(('joint_supplies','L2'),keys);self.assertEqual(len(keys),len(d['sources']));self.assertTrue(d['can_download_original'])

    def test_six_roles_and_anonymous_access(self):
        for role in ('analyst','operations','quality','finance','viewer'):
            user=User.objects.create_user('material-'+role);user.groups.add(Group.objects.get_or_create(name=role)[0]);self.client.force_login(user)
            if role in ('analyst','operations'):
                r=self.detail();self.assertEqual(r.status_code,200);self.assertFalse(r.json()['can_download_original'])
            else:self.assertEqual(self.detail(receipt='DENIED').status_code,403)
        self.client.logout();self.assertEqual(self.detail(receipt='DENIED').status_code,401)

    def test_units_unknown_pair_and_missing_receipt(self):
        self.assertEqual(self.detail(unit='件').status_code,404);self.assertEqual(self.detail(material='ABSENT').status_code,404)
        self.assertEqual(self.client.get('/api/joint-schedule/MP1/materials/M1',{'unit':'kg'}).status_code,400)
        self.assertEqual(self.client.get('/api/joint-schedule/MP1/materials/M1',{'receipt':self.board()['receipt']}).status_code,400)
        self.assertEqual(self.detail(unexpected='x').status_code,400)

    def test_duplicate_unit_and_stale_policy_rejected(self):
        receipt=self.board()['receipt']
        self.assertEqual(self.client.get('/api/joint-schedule/MP1/materials/M1',{'receipt':receipt,'unit':['kg','件']}).status_code,400)
        self.assertEqual(self.detail(receipt,policy='priority').status_code,409)

    def test_definition_change_invalidates_receipt(self):
        receipt=self.board()['receipt']
        with patch('app.joint_material_evidence.definition_hash',return_value='CHANGED'):self.assertEqual(self.detail(receipt).status_code,409)

    def test_definition_change_during_read_rejects_payload(self):
        receipt=self.board()['receipt'];old=evidence.definition_hash()
        with patch('app.joint_material_evidence.definition_hash',side_effect=[old,'CHANGED']):self.assertEqual(self.detail(receipt).status_code,409)

    def test_cross_account_receipt_is_rejected(self):
        receipt=self.board()['receipt'];user=User.objects.create_user('other');user.groups.add(Group.objects.get_or_create(name='analyst')[0]);self.client.force_login(user)
        self.assertEqual(self.detail(receipt).status_code,409)

    def test_export_reconstruction_is_query_free_and_original_format(self):
        board=self.board();d=self.detail(board['receipt']).json();doc=self.client.get('/api/joint-schedule/MP1/export',{'receipt':board['receipt'],'format':'json'}).json()
        with self.assertNumQueries(0):report,_=evidence.build(doc['result'],'M1','kg')
        self.assertEqual(report,d['evidence']);self.assertEqual(doc['result']['tasks'],board['tasks']);self.assertNotIn('material_evidence',doc['result'])
