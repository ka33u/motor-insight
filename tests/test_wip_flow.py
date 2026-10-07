from copy import deepcopy
from django.test import SimpleTestCase
from app.wip_flow import Wip,summary,TABLES,BASE

def fixture():
    d={k:[] for k in TABLES+BASE}
    d['products']=[dict(id='P01',family='异步',model='演示配置')]
    d['employees']=[dict(id='E01')]
    d['wip_locations']=[dict(id=k,name=k,workshop='模拟车间',process=None,kind=kind,note='模拟位置') for k,kind in [('A','生产缓冲'),('B','生产缓冲'),('RW','返工区'),('ISO','隔离区'),('USE','装配耗用'),('SCRAP','报废登记')]]
    for i in [1,2]:
        d['work_orders'].append(dict(id=f'WO{i}',product_id='P01'))
        d['batches'].append(dict(id=f'R{i}',work_order_id=f'WO{i}',kind='定子',qty=10,created='2026-09-01T08:00:00'))
        lot(d,f'L{i}')
        d['wip_openings'].append(dict(id=f'O{i}',root_batch_id=f'R{i}',lot_id=f'L{i}',location_id='A',qty=10,occurred='2026-09-01T08:00:00',recorded='2026-09-01T08:00:00',owner_id='E01',reference='模拟实物基准',note='完整十件'))
    return d
def lot(d,key):
    d['wip_lots'].append(dict(id=key,product_id='P01',kind='定子',created='2026-09-01T08:00:00',container='BOX-'+key,note='模拟周转档案'))
def event(d,key,kind,outs,ins,at='2026-09-01T09:00:00',version=1,status='登记',previous=None,recorded=None,sequence=1):
    # tuples: lot, location, root, qty[, SN]
    h=dict(id=f'{key}-V{version}',series=key,version=version,previous_id=previous,occurred=at,sequence=sequence,recorded=recorded or at,status=status,kind=kind,
       input_lots=','.join(dict.fromkeys(x[0] for x in outs)),output_lots=','.join(dict.fromkeys(x[0] for x in ins)),line_count=len(outs)+len(ins),sender_id='E01',receiver_id='E01',operation_id=None,reference='模拟流转依据',note='完整份额登记')
    d['wip_event_versions'].append(h)
    for side,rows in [('出',outs),('入',ins)]:
        for i,x in enumerate(rows):d['wip_event_lines'].append(dict(id=f'{h["id"]}-{side}-{i}',event_id=h['id'],side=side,lot_id=x[0],location_id=x[1],root_batch_id=x[2],qty=x[3],unit_id=x[4] if len(x)>4 else None,note='模拟份额'))
    return h
def current(d,cutoff='2026-09-02T18:00:00'):return Wip(d,cutoff)

class WipJournalTests(SimpleTestCase):
    def test_full_baseline_and_separate_physical_positions(self):
        w=current(fixture());self.assertEqual(summary(w.rows)['positions'],2)
        self.assertEqual(w.index['R1']['wip_qty'],10)

    def test_split_merge_and_genealogy_conserve_root_shares(self):
        d=fixture();lot(d,'LA');lot(d,'LB');lot(d,'LM')
        event(d,'S','拆批',[('L1','A','R1',10)],[('LA','A','R1',4),('LB','B','R1',6)])
        event(d,'M','合批',[('LA','A','R1',4),('LB','B','R1',6)],[('LM','B','R1',10)],at='2026-09-01T10:00:00')
        w=current(d);self.assertEqual(w.index['R1']['wip_qty'],10);self.assertFalse(w.index['R1']['issues'])
        self.assertEqual(w.parents['LM'][0]['parents'],['LA','LB'])

    def test_cross_work_order_merge_keeps_parent_members_separate(self):
        d=fixture();lot(d,'LM')
        event(d,'M','合批',[('L1','A','R1',10),('L2','A','R2',10)],[('LM','B','R1',10),('LM','B','R2',10)])
        w=current(d);self.assertEqual(w.members['L1'],{'R1'});self.assertEqual(w.members['L2'],{'R2'})
        self.assertEqual(summary(w.rows)['positions'],1)
        rows=w.cohort({'work_order_id':'WO1'});self.assertEqual(rows[0]['positions'][0]['qty'],10)
        self.assertEqual(rows[0]['positions'][0]['whole_lot_qty'],20)

    def test_partial_consumption_preserves_position_entry_time(self):
        d=fixture();d['units']=[dict(id='SN01',stator_batch='R1',product_id='P01',assembly_at='2026-09-01T10:00:00')]
        event(d,'U','装配耗用',[('L1','A','R1',10)],[('L1','USE','R1',1,'SN01'),('L1','A','R1',9)],at='2026-09-01T10:00:00')
        r=current(d).index['R1'];self.assertEqual((r['wip_qty'],r['prefix_consumed_qty']),(9,1))
        self.assertEqual(r['positions'][0]['entered_at'],'2026-09-01T08:00:00')

    def test_latest_bad_version_never_falls_back(self):
        d=fixture();event(d,'T','工序交接',[('L1','A','R1',10)],[('L1','B','R1',10)])
        h=event(d,'T','工序交接',[('L1','A','R1',10)],[('L1','B','R1',9)],version=2,previous='T-V1',recorded='2026-09-01T09:01:00')
        r=current(d).index['R1'];self.assertIsNone(r['wip_qty']);self.assertEqual(r['positions'],[])
        self.assertIn('原批次份额出入未逐项对平',r['issues'])

    def test_corrected_complete_version_applies_once(self):
        d=fixture();event(d,'T','工序交接',[('L1','A','R1',10)],[('L1','B','R1',9)])
        event(d,'T','工序交接',[('L1','A','R1',10)],[('L1','B','R1',10)],version=2,previous='T-V1',recorded='2026-09-01T09:01:00')
        r=current(d).index['R1'];self.assertEqual(r['wip_qty'],10);self.assertEqual(r['applied_events'],1)

    def test_void_retracts_whole_event_and_draft_is_not_published(self):
        for status in ['作废','草稿']:
            d=fixture();event(d,'T','工序交接',[('L1','A','R1',10)],[('L1','B','R1',10)],status=status)
            r=current(d).index['R1'];self.assertEqual(r['positions'][0]['location_id'],'A')

    def test_invalid_void_does_not_silently_ignore_latest_error(self):
        d=fixture();h=event(d,'T','工序交接',[('L1','A','R1',10)],[('L1','B','R1',10)],status='作废');h['line_count']=3
        self.assertIsNone(current(d).index['R1']['wip_qty'])

    def test_future_registered_version_is_not_yet_known(self):
        d=fixture();event(d,'T','工序交接',[('L1','A','R1',10)],[('L1','B','R1',10)])
        event(d,'T','工序交接',[('L1','A','R1',10)],[('L1','B','R1',9)],version=2,previous='T-V1',recorded='2026-09-03T09:00:00')
        r=current(d).index['R1'];self.assertEqual(r['positions'][0]['location_id'],'B')

    def test_missing_declared_parent_pauses_both_roots(self):
        d=fixture();lot(d,'LM');h=event(d,'M','合批',[('L1','A','R1',10),('L2','A','R2',10)],[('LM','B','R1',10),('LM','B','R2',10)])
        d['wip_event_lines']=[x for x in d['wip_event_lines'] if x['root_batch_id']!='R2']
        w=current(d);self.assertTrue(all(w.index[r]['wip_qty'] is None for r in ['R1','R2']))

    def test_downstream_of_unknown_input_cannot_infer_location(self):
        d=fixture();lot(d,'LM');event(d,'M','合批',[('L1','A','R1',10),('L2','A','R2',10)],[('LM','B','R1',10),('LM','B','R2',9)])
        event(d,'T','工序交接',[('LM','B','R1',10),('LM','B','R2',10)],[('LM','A','R1',10),('LM','A','R2',10)],at='2026-09-01T10:00:00')
        w=current(d);self.assertFalse(any(e['applied'] for e in w.events))

    def test_same_clock_and_sequence_conflict_but_explicit_sequence_orders(self):
        for seq,unknown in [(1,True),(2,False)]:
            d=fixture();event(d,'T1','工序交接',[('L1','A','R1',10)],[('L1','B','R1',10)])
            event(d,'T2','工序交接',[('L1','B','R1',10)],[('L1','A','R1',10)],sequence=seq)
            self.assertEqual(current(d).index['R1']['wip_qty'] is None,unknown)

    def test_independent_containers_can_transfer_at_same_clock(self):
        d=fixture()
        for i in [1,2]:event(d,f'T{i}','工序交接',[(f'L{i}','A',f'R{i}',10)],[(f'L{i}','B',f'R{i}',10)])
        self.assertTrue(all(not r['issues'] for r in current(d).rows))

    def test_partial_take_is_invalid_even_when_out_equals_in(self):
        d=fixture();event(d,'T','工序交接',[('L1','A','R1',2)],[('L1','B','R1',2)])
        self.assertIn('输入周转批次未完整耗用当前在制份额',current(d).index['R1']['issues'])

    def test_missing_baseline_and_zero_current_are_distinct(self):
        d=fixture();d['wip_openings']=[];r=current(d).index['R1'];self.assertIsNone(r['wip_qty']);self.assertEqual(r['state'],'missing')
        d=fixture();event(d,'S','报废登记',[('L1','A','R1',10)],[('L1','SCRAP','R1',10)])
        r=current(d).index['R1'];self.assertEqual(r['wip_qty'],0);self.assertEqual(r['state'],'closed')

    def test_rework_and_isolation_are_positions_not_extra_output(self):
        d=fixture();event(d,'RW','返工转入',[('L1','A','R1',10)],[('L1','RW','R1',10)])
        event(d,'BACK','返工返回',[('L1','RW','R1',10)],[('L1','B','R1',10)],at='2026-09-01T10:00:00')
        event(d,'ISO','隔离转入',[('L1','B','R1',10)],[('L1','ISO','R1',10)],at='2026-09-01T11:00:00')
        r=current(d).index['R1'];self.assertEqual(r['wip_qty'],10);self.assertEqual(r['prefix_consumed_qty'],0);self.assertEqual(r['positions'][0]['kind'],'隔离区')

    def test_wrong_sn_product_and_duplicate_sn_pause_consumption(self):
        for wrong in ['product','duplicate']:
            d=fixture();d['units']=[dict(id='SN01',stator_batch='R1',product_id='WRONG' if wrong=='product' else 'P01',assembly_at='2026-09-01T10:00:00')]
            event(d,'U1','装配耗用',[('L1','A','R1',10)],[('L1','USE','R1',1,'SN01'),('L1','A','R1',9)],at='2026-09-01T10:00:00')
            if wrong=='duplicate':event(d,'U2','装配耗用',[('L1','A','R1',9)],[('L1','USE','R1',1,'SN01'),('L1','A','R1',8)],at='2026-09-01T10:00:00',sequence=2)
            self.assertIsNone(current(d).index['R1']['wip_qty'])

    def test_missing_master_data_evidence_does_not_crash(self):
        d=fixture();d['work_orders']=[];w=current(d);self.assertIsNone(w.index['R1']['wip_qty']);self.assertTrue(w.evidence('R1'))

    def test_reused_split_child_identifier_is_rejected(self):
        d=fixture();lot(d,'LC');event(d,'S','拆批',[('L1','A','R1',10)],[('L2','A','R1',5),('LC','A','R1',5)])
        self.assertIn('拆合批输出标识已经使用，不重建旧周转批次',current(d).index['R1']['issues'])

    def test_root_future_and_late_baseline_are_not_filled_as_zero(self):
        d=fixture();d['batches'][1]['created']='2026-09-03T08:00:00';w=current(d);self.assertNotIn('R2',w.index)
        d=fixture();d['wip_openings'][0]['recorded']='2026-09-03T08:00:00';self.assertIsNone(current(d).index['R1']['wip_qty'])

    def test_already_assembled_sn_without_journal_consumption_is_unknown(self):
        d=fixture();d['units']=[dict(id='SN01',stator_batch='R1',product_id='P01',assembly_at='2026-09-01T10:00:00')]
        r=current(d).index['R1'];self.assertIsNone(r['wip_qty']);self.assertEqual(r['missing_consumption_sn'],['SN01'])

    def test_future_assembly_does_not_require_consumption_yet(self):
        d=fixture();d['units']=[dict(id='SN01',stator_batch='R1',product_id='P01',assembly_at='2026-09-03T10:00:00')]
        self.assertEqual(current(d).index['R1']['wip_qty'],10)
