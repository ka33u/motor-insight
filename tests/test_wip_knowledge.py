from copy import deepcopy
from django.test import SimpleTestCase
from app.wip_flow import Wip
from app.wip_comparison import comparison
from tests.test_wip_flow import fixture,event

BUSINESS='2026-09-01T18:00:00';LATER='2026-09-02T18:00:00'
class WipRegistrationCutoffTests(SimpleTestCase):
    def sides(self,d):return Wip(d,BUSINESS),Wip(d,BUSINESS,LATER)
    def test_default_registration_cutoff_preserves_old_replay(self):
        d=fixture();a=Wip(d,BUSINESS);b=Wip(d,BUSINESS,BUSINESS)
        self.assertEqual(a.rows,b.rows)
    def test_late_transfer_appears_only_when_registration_cutoff_advances(self):
        d=fixture();event(d,'T','工序交接',[('L1','A','R1',10)],[('L1','B','R1',10)],recorded='2026-09-02T10:00:00')
        a,b=self.sides(d);self.assertEqual(a.index['R1']['positions'][0]['location_id'],'A');self.assertEqual(b.index['R1']['positions'][0]['location_id'],'B')
        r=comparison(a,b,b.rows)['changed'][0];self.assertTrue(r['outcome_changed']);self.assertEqual(r['wip_delta'],0)
    def test_late_bad_latest_pauses_without_falling_back(self):
        d=fixture();event(d,'T','工序交接',[('L1','A','R1',10)],[('L1','B','R1',10)])
        event(d,'T','工序交接',[('L1','A','R1',10)],[('L1','B','R1',9)],version=2,previous='T-V1',recorded='2026-09-02T10:00:00')
        a,b=self.sides(d);r=comparison(a,b,b.rows)['changed'][0]
        self.assertEqual(r['before']['wip_qty'],10);self.assertIsNone(r['after']['wip_qty']);self.assertIsNone(r['wip_delta'])
        g=comparison(a,b,b.rows)['summary']['groups'][0];self.assertEqual(g['both_verified'],1);self.assertEqual(g['lost_verification'],1);self.assertEqual(g['comparable_delta'],0)
    def test_late_valid_correction_restores_unknown_basis(self):
        d=fixture();event(d,'T','工序交接',[('L1','A','R1',10)],[('L1','B','R1',9)])
        event(d,'T','工序交接',[('L1','A','R1',10)],[('L1','B','R1',10)],version=2,previous='T-V1',recorded='2026-09-02T10:00:00')
        a,b=self.sides(d);r=comparison(a,b,b.rows)['changed'][0];self.assertIsNone(r['before']['wip_qty']);self.assertEqual(r['after']['wip_qty'],10);self.assertIsNone(r['wip_delta'])
        self.assertEqual(comparison(a,b,b.rows)['summary']['groups'][0]['gained_verification'],1)
    def test_identical_outcome_with_new_version_is_evidence_only(self):
        d=fixture();event(d,'T','工序交接',[('L1','A','R1',10)],[('L1','B','R1',10)])
        event(d,'T','工序交接',[('L1','A','R1',10)],[('L1','B','R1',10)],version=2,previous='T-V1',recorded='2026-09-02T10:00:00')
        a,b=self.sides(d);r=comparison(a,b,b.rows)['changed'][0];self.assertEqual(r['change_type'],'仅依据改变');self.assertFalse(r['outcome_changed']);self.assertEqual(r['version_changes'][0]['after']['selected_id'],'T-V2')
    def test_later_opening_fills_basis_without_faking_prior_zero(self):
        d=fixture();d['wip_openings'][0]['recorded']='2026-09-02T10:00:00'
        a,b=self.sides(d);r=comparison(a,b,b.rows)['changed'][0]
        self.assertEqual(r['before']['state'],'missing');self.assertIsNone(r['before']['baseline_qty']);self.assertEqual(r['after']['baseline_qty'],10);self.assertEqual(r['opening_before'],[]);self.assertEqual(r['opening_after'],['O1'])
    def test_newly_known_future_events_do_not_look_like_past_changes(self):
        d=fixture();event(d,'F','工序交接',[('L1','A','R1',10)],[('L1','B','R1',10)],at='2026-09-02T10:00:00')
        a,b=self.sides(d);result=comparison(a,b,b.rows);self.assertEqual(result['changed'],[]);self.assertEqual(result['summary']['unchanged'],2)
    def test_later_void_removes_historical_transfer(self):
        d=fixture();event(d,'T','工序交接',[('L1','A','R1',10)],[('L1','B','R1',10)])
        event(d,'T','工序交接',[('L1','A','R1',10)],[('L1','B','R1',10)],version=2,previous='T-V1',status='作废',recorded='2026-09-02T10:00:00')
        a,b=self.sides(d);r=comparison(a,b,b.rows)['changed'][0];self.assertTrue(r['version_changes'][0]['after']['withdrawn']);self.assertEqual(r['after']['positions'][0]['location_id'],'A')
    def test_later_draft_and_unseen_version_stay_excluded(self):
        d=fixture();event(d,'T','工序交接',[('L1','A','R1',10)],[('L1','B','R1',10)])
        event(d,'T','工序交接',[('L1','A','R1',10)],[('L1','B','R1',9)],version=2,previous='T-V1',status='草稿',recorded='2026-09-02T10:00:00')
        a,b=self.sides(d);self.assertFalse(comparison(a,b,b.rows)['changed'])
        d['wip_event_versions'][-1]['status']='登记';d['wip_event_versions'][-1]['recorded']='2026-09-03T10:00:00'
        a,b=self.sides(d);self.assertFalse(comparison(a,b,b.rows)['changed'])
    def test_business_and_registration_clocks_cannot_be_reversed(self):
        with self.assertRaises(ValueError):Wip(fixture(),BUSINESS,'2026-09-01T08:00:00')
        with self.assertRaises(ValueError):Wip(fixture(),BUSINESS,'2026-09-02 18:00:00')
    def test_future_original_batches_remain_outside_business_cutoff(self):
        d=fixture();d['batches'][1]['created']='2026-09-02T08:00:00'
        a,b=self.sides(d);self.assertEqual(set(a.index),{'R1'});self.assertEqual(set(b.index),{'R1'})
    def test_late_consumption_can_resolve_missing_registration_not_create_output(self):
        d=fixture();d['units']=[dict(id='SN01',stator_batch='R1',product_id='P01',assembly_at='2026-09-01T10:00:00')]
        event(d,'U','装配耗用',[('L1','A','R1',10)],[('L1','USE','R1',1,'SN01'),('L1','A','R1',9)],at='2026-09-01T10:00:00',recorded='2026-09-02T10:00:00')
        a,b=self.sides(d);self.assertIsNone(a.index['R1']['wip_qty']);self.assertEqual(b.index['R1']['wip_qty'],9);self.assertEqual(b.index['R1']['prefix_consumed_qty'],1);self.assertEqual(len(d['units']),1)
    def test_selected_root_identity_is_fixed_even_if_old_state_does_not_match(self):
        d=fixture();event(d,'T','工序交接',[('L1','A','R1',10)],[('L1','B','R1',9)],recorded='2026-09-02T10:00:00')
        a,b=self.sides(d);selected=[r for r in b.rows if r['state']=='attention'];r=comparison(a,b,selected)
        self.assertEqual(r['summary']['objects'],1);self.assertEqual(r['all_rows'][0]['before']['state'],'active')
    def test_invalid_pure_future_header_does_not_taint_earlier_history(self):
        d=fixture();h=event(d,'F','工序交接',[('L1','A','R1',10)],[('L1','B','R1',10)],at='2026-09-02T10:00:00');h['line_count']=3
        a,b=self.sides(d);self.assertEqual(b.index['R1']['wip_qty'],10);self.assertFalse(comparison(a,b,b.rows)['changed'])
        from scripts.wip_raw_ledger import rows_at
        independent,_=rows_at(d,BUSINESS,LATER);self.assertEqual(independent['R1']['wip_qty'],10)
    def test_bad_future_revision_of_past_event_cannot_hide_historical_conflict(self):
        d=fixture();event(d,'T','工序交接',[('L1','A','R1',10)],[('L1','B','R1',10)])
        h=event(d,'T','工序交接',[('L1','A','R1',10)],[('L1','B','R1',9)],at='2026-09-02T10:00:00',version=2,previous='T-V1');h['line_count']=3
        a,b=self.sides(d);self.assertIsNone(b.index['R1']['wip_qty']);self.assertTrue(comparison(a,b,b.rows)['changed'])
