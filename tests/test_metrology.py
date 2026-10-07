from copy import deepcopy
from django.test import SimpleTestCase
from app.metrology import Metrology,summary,TABLES,BASE,digest

AT='2026-09-22T12:00:00';KNOWN='2026-10-01T18:00:00'
def fixture():
    d={k:[] for k in TABLES+BASE}
    d['units']=[dict(id='SN1',work_order_id='WO1',assembly_at='2026-09-21T12:00:00')]
    d['work_orders']=[dict(id='WO1',product_id='P1')]
    d['test_sessions']=[dict(id='TS1',unit_id='SN1',tested=AT,result='合格')]
    d['test_specs']=[dict(id='SP1',test_code='R',unit='Ω')]
    d['measurements']=[dict(id='M1',session_id='TS1',spec_id='SP1',unit='Ω',value=1.1,result='合格')]
    d['metrology_instruments']=[dict(id='I1',stage='test',parameter='R',unit='Ω',active_from='2026-01-01T00:00:00',retired=None)]
    d['metrology_rules']=[dict(id='R1',series='REQ1',version=1,status='已登记',previous_id=None,stage='test',parameter='R',unit='Ω',required=True,effective='2026-01-01T00:00:00',expires=None,registered='2026-01-01T00:00:00')]
    d['metrology_uses']=[dict(id='U1',series='USE1',version=1,status='已登记',previous_id=None,stage='test',measurement_id='M1',incoming_reading_id=None,process_reading_id=None,instrument_id='I1',measured=AT,registered='2026-09-22T12:01:00')]
    d['metrology_calibrations']=[dict(id='C1',series='CAL1',version=1,status='已登记',previous_id=None,instrument_id='I1',performed='2026-09-01T08:00:00',valid_from='2026-09-01T08:00:00',valid_until='2026-10-01T00:00:00',result='符合登记范围',parameter='R',unit='Ω',certificate_no='SIM1',reference='模拟登记',registered='2026-09-01T08:01:00')]
    return d
def version(d,ds,changes,registered='2026-09-25T09:00:00'):
    old=d[ds][-1];new=deepcopy(old);new.update(id=old['id']+'V2',version=old['version']+1,previous_id=old['id'],registered=registered);new.update(changes);d[ds].append(new);return new
def notice(d,mode='明确起点',start='2026-09-22T12:00:00',end='2026-09-23T12:00:00'):
    d['metrology_notices']=[dict(id='N1',series='NOTICE1',version=1,status='已登记',previous_id=None,instrument_id='I1',calibration_id='C1',discovered='2026-09-24T08:00:00',lower_mode=mode,impact_from=start,impact_until=end,registered='2026-09-24T09:00:00')]
class MetrologyTests(SimpleTestCase):
    def setUp(self):self.d=fixture()
    def m(self,known=KNOWN):return Metrology(self.d,cutoff=AT,known_cutoff=known)
    def r(self,known=KNOWN):return self.m(known).index['test:M1']
    def test_valid_measurement_keeps_original_verdict(self):
        r=self.r();self.assertEqual(r['calibration_state'],'valid');self.assertEqual(r['source_result'],'合格');self.assertEqual(summary(self.m().rows)['required'],1)
    def test_use_one_minute_after_business_time_unknown_then_known(self):
        self.assertEqual(self.r(AT)['calibration_state'],'unknown_use');self.assertEqual(self.r()['calibration_state'],'valid')
    def test_valid_from_inclusive(self):
        self.d['metrology_calibrations'][0]['valid_from']=AT;self.assertEqual(self.r()['calibration_state'],'valid')
    def test_valid_until_exclusive(self):
        self.d['metrology_calibrations'][0]['valid_until']=AT;self.assertEqual(self.r()['calibration_state'],'expired')
    def test_pending(self):
        self.d['metrology_calibrations'][0]['valid_from']='2026-09-23T00:00:00';self.assertEqual(self.r()['calibration_state'],'pending')
    def test_missing_register(self):
        self.d['metrology_calibrations']=[];self.assertEqual(self.r()['calibration_state'],'missing')
    def test_latest_failed_never_falls_back(self):
        c=deepcopy(self.d['metrology_calibrations'][0]);c.update(id='C2',series='CAL2',performed='2026-09-20T08:00:00',valid_from='2026-09-20T08:00:00',registered='2026-09-20T09:00:00',result='不符合登记范围');self.d['metrology_calibrations'].append(c);self.assertEqual(self.r()['calibration_state'],'failed')
    def test_latest_invalid_never_falls_back(self):
        version(self.d,'metrology_calibrations',dict(valid_until='2026-08-01T00:00:00'));self.assertEqual(self.r()['calibration_state'],'invalid')
    def test_latest_withdrawn_never_falls_back(self):
        version(self.d,'metrology_calibrations',dict(status='撤销'));self.assertEqual(self.r()['calibration_state'],'withdrawn')
    def test_draft_does_not_replace_register(self):
        version(self.d,'metrology_calibrations',dict(status='草稿',valid_until=AT));self.assertEqual(self.r()['calibration_state'],'valid')
    def test_future_calibration_does_not_invalidate_past(self):
        c=deepcopy(self.d['metrology_calibrations'][0]);c.update(id='C2',series='CAL2',performed='2026-09-23T08:00:00',valid_from='2026-09-23T08:00:00',registered='2026-09-23T09:00:00');self.d['metrology_calibrations'].append(c);version(self.d,'metrology_calibrations',dict(previous_id='UNKNOWN'));self.assertEqual(self.r()['calibration_state'],'valid')
    def test_future_registration_does_not_replace_known(self):
        version(self.d,'metrology_calibrations',dict(status='撤销'));self.assertEqual(self.r('2026-09-23T18:00:00')['calibration_state'],'valid')
    def test_calibration_same_instant_conflict(self):
        c=deepcopy(self.d['metrology_calibrations'][0]);c.update(id='C2',series='CAL2');self.d['metrology_calibrations'].append(c);self.assertEqual(self.r()['calibration_state'],'conflict')
    def test_duplicate_latest_use_unknown(self):
        u=version(self.d,'metrology_uses',{});v=deepcopy(u);v['id']='U3';self.d['metrology_uses'].append(v);self.assertEqual(self.r()['calibration_state'],'unknown_use')
    def test_wrong_channel_unknown(self):
        self.d['metrology_instruments'][0]['unit']='mΩ';self.assertEqual(self.r()['calibration_state'],'unknown_use')
    def test_instrument_retirement_exclusive(self):
        self.d['metrology_instruments'][0]['retired']=AT;self.assertEqual(self.r()['calibration_state'],'unknown_use')
    def test_invalid_master_interval_unknown(self):
        self.d['metrology_instruments'][0]['retired']='2025-01-01T00:00:00';self.assertEqual(self.r()['calibration_state'],'unknown_use')
    def test_wrong_measured_time_unknown(self):
        self.d['metrology_uses'][0]['measured']='2026-09-22T12:00:01';self.assertEqual(self.r()['calibration_state'],'unknown_use')
    def test_use_with_two_sources_unknown(self):
        self.d['metrology_uses'][0]['incoming_reading_id']='X';self.assertEqual(self.r()['calibration_state'],'unknown_use')
    def test_withdrawn_use_unknown(self):
        version(self.d,'metrology_uses',dict(status='撤销'));self.assertEqual(self.r()['calibration_state'],'unknown_use')
    def test_unknown_requirement_separate_denominator(self):
        self.d['metrology_rules']=[];s=summary(self.m().rows);self.assertEqual(s['required'],0);self.assertEqual(s['unknown_requirement'],1);self.assertEqual(self.r()['calibration_state'],'unknown_rule')
    def test_optional_not_bad_rate(self):
        self.d['metrology_rules'][0]['required']=False;self.d['metrology_calibrations']=[];self.assertEqual(self.r()['calibration_state'],'not_required');self.assertEqual(summary(self.m().rows)['required'],0)
    def test_voided_not_in_denominator(self):
        self.d['test_sessions'][0]['voided']=True;self.assertEqual(self.r()['calibration_state'],'voided');self.assertEqual(summary(self.m().rows)['active_readings'],0)
    def test_missing_measurement_clock_is_explicitly_unlisted(self):
        self.d['test_sessions'][0]['tested']='bad';m=self.m();self.assertEqual(m.rows,[]);self.assertEqual(len(m.global_issues),1)
    def test_notice_start_inclusive(self):
        notice(self.d);self.assertEqual(self.r()['notice_ids'],['N1']);self.assertEqual(self.r()['impact_state'],'matched')
    def test_notice_end_exclusive(self):
        notice(self.d,start='2026-09-21T12:00:00',end=AT);self.assertEqual(self.r()['notice_ids'],[]);self.assertEqual(self.r()['impact_state'],'none')
    def test_unknown_lower_is_potential(self):
        notice(self.d,mode='起点未知',start=None);self.assertEqual(self.r()['impact_state'],'potential')
    def test_bad_notice_latest_no_fallback(self):
        notice(self.d);version(self.d,'metrology_notices',dict(impact_until=AT));self.assertEqual(self.r()['impact_state'],'unknown');self.assertEqual(self.r()['notice_ids'],[])
    def test_withdrawn_notice_not_matched(self):
        notice(self.d);version(self.d,'metrology_notices',dict(status='撤销'));self.assertEqual(self.r()['impact_state'],'none')
    def test_review_binds_source_and_calibration_version(self):
        notice(self.d);r=self.r();self.d['metrology_reviews']=[dict(id='RV1',series='REVIEW1',version=1,status='已登记',previous_id=None,use_id='U1',notice_id='N1',calibration_id='C1',source_digest=r['source_digest'],result='资料已核对',registered='2026-09-26T09:00:00')];self.assertEqual(self.r()['review_state'],'checked');self.d['measurements'][0]['value']=1.2;self.assertEqual(self.r()['review_state'],'stale')
    def test_one_review_cannot_cover_two_notices(self):
        notice(self.d);r=self.r();n=deepcopy(self.d['metrology_notices'][0]);n.update(id='N2',series='NOTICE2');self.d['metrology_notices'].append(n);self.d['metrology_reviews']=[dict(id='RV1',series='REVIEW1',version=1,status='已登记',previous_id=None,use_id='U1',notice_id='N1',calibration_id='C1',source_digest=r['source_digest'],result='资料已核对',registered='2026-09-26T09:00:00')];self.assertEqual(self.r()['review_state'],'none');self.assertEqual(summary(self.m().rows)['matched'],1)
    def test_review_before_notice_cannot_count_checked(self):
        notice(self.d);r=self.r();self.d['metrology_reviews']=[dict(id='RV1',series='REVIEW1',version=1,status='已登记',previous_id=None,use_id='U1',notice_id='N1',calibration_id='C1',source_digest=r['source_digest'],result='资料已核对',registered='2026-09-23T09:00:00')];self.assertEqual(self.r()['review_state'],'invalid')
    def test_candidates_do_not_become_confirmed_shipments(self):
        self.d['order_lines']=[dict(id='OL1',product_id='P1',order_id='ORD1')];self.d['allocations']=[dict(id='A1',work_order_id='WO1',order_line_id='OL1',effective='2026-09-20')];m=self.m();down=m.downstream(m.rows);self.assertEqual(len(down['candidate_orders']),1);self.assertEqual(down['shipment_orders'],[])
    def test_source_references_unique(self):
        r=self.r();self.assertEqual(len(r['sources']),len({(s['dataset'],s['key']) for s in r['sources']}))
    def test_known_cutoff_before_business_rejected(self):
        with self.assertRaises(ValueError):self.r('2026-09-21T12:00:00')
