from copy import deepcopy
import csv
import io
from django.test import SimpleTestCase
from app.metrology import Metrology
from app.metrology_evidence import Evidence, HEADERS, parse, summary
from tests.test_metrology import fixture, AT, KNOWN, version


class CertificateEvidenceTests(SimpleTestCase):
    def setUp(self):
        self.d=fixture()
        self.d['metrology_instruments'][0].update(name='模拟电阻通道',asset_code='YQ-001',source_alias='模拟采集点')
        cal=self.d['metrology_calibrations'][0];cal['laboratory']='模拟校准单位'
        self.cert={k:cal[k] for k in HEADERS if k in cal}
        self.cert.update(id='D1',issued='2026-09-01T08:30:00',reference='模拟声明依据',
                         file_id='00000000-0000-0000-0000-000000000001',file_sha256='a'*64)
        self.data={'metrology_certificates':[self.cert],'metrology_certificate_links':[
            dict(id='L1',series='LINK1',version=1,previous_id=None,status='已登记',calibration_id='C1',
                 certificate_id='D1',registered='2026-09-01T09:00:00',reference='模拟关联依据')]}
        self.calls=[];self.file_state='verified';self.file_hash='a'*64;self.raw_override=None
    def raw(self):
        out=io.StringIO();w=csv.writer(out);w.writerow(HEADERS);w.writerow([self.cert[k] for k in HEADERS]);return ('\ufeff'+out.getvalue()).encode()
    def resolve(self,key):
        self.calls.append(key)
        if self.file_state!='verified':return dict(state=self.file_state,issues=['模拟不可读取'],observation=self.file_state)
        return dict(state='verified',issues=[],observation='observed',file=dict(id=key,file_hash=self.file_hash,filename='模拟原件.csv'),
                    parsed=parse(self.raw_override or self.raw(),'csv'))
    def e(self,window=30,cutoff=AT,known=KNOWN):return Evidence(Metrology(self.d,cutoff=cutoff,known_cutoff=known),self.data,self.resolve,window)
    def check(self):return self.e().inspections['C1']
    def test_correspondence_does_not_change_original_measurement(self):
        before=deepcopy(self.d);e=self.e();self.assertEqual(e.index['I1']['evidence_state'],'consistent');self.assertEqual(self.d,before)
        self.assertEqual(e.registry.index['test:M1']['source_result'],'合格')
    def test_failed_calibration_is_not_approved_by_matching_certificate(self):
        self.d['metrology_calibrations'][0]['result']=self.cert['result']='不符合登记范围'
        r=self.e().index['I1'];self.assertEqual(r['evidence_state'],'consistent');self.assertEqual(r['due_state'],'failed')
    def test_missing_link_is_distinct_from_missing_file(self):
        self.data['metrology_certificate_links']=[];self.assertEqual(self.check()['state'],'missing_link');self.assertEqual(self.calls,[])
    def test_withdrawn_link_never_reads_old_original(self):
        version(self.data,'metrology_certificate_links',dict(status='撤销'));self.assertEqual(self.check()['state'],'withdrawn');self.assertEqual(self.calls,[])
    def test_broken_latest_link_does_not_fall_back(self):
        version(self.data,'metrology_certificate_links',dict(previous_id=None));self.assertEqual(self.check()['state'],'record_attention');self.assertIsNone(self.check()['link_id'])
    def test_duplicate_latest_version_blocks_selection(self):
        v=version(self.data,'metrology_certificate_links',{});second=deepcopy(v);second['id']='L3';self.data['metrology_certificate_links'].append(second)
        self.assertEqual(self.check()['state'],'record_attention')
    def test_multiple_link_series_for_one_calibration_blocks_selection(self):
        v=deepcopy(self.data['metrology_certificate_links'][0]);v.update(id='L2',series='LINK2');self.data['metrology_certificate_links'].append(v)
        self.assertEqual(self.check()['state'],'record_attention')
    def test_draft_does_not_replace_confirmed_link(self):
        version(self.data,'metrology_certificate_links',dict(status='草稿'));self.assertEqual(self.check()['link_id'],'L1')
    def test_later_registration_only_changes_later_known_view(self):
        version(self.data,'metrology_certificate_links',dict(status='撤销'))
        self.assertEqual(self.e(known='2026-09-23T18:00:00').index['I1']['evidence_state'],'consistent')
        self.assertEqual(self.e().index['I1']['evidence_state'],'withdrawn')
    def test_future_link_is_missing_at_known_cutoff(self):
        self.data['metrology_certificate_links'][0]['registered']='2026-10-02T09:00:00';self.assertEqual(self.check()['state'],'missing_link')
    def test_wrong_calibration_identity_is_not_reused_for_current_version(self):
        self.data['metrology_certificate_links'][0]['calibration_id']='OTHER';self.assertEqual(self.check()['state'],'missing_link')
    def test_unknown_certificate_is_record_attention(self):
        self.data['metrology_certificate_links'][0]['certificate_id']='UNKNOWN';self.assertEqual(self.check()['state'],'record_attention')
    def test_wrong_instrument_keeps_record_error_even_when_raw_matches_declaration(self):
        self.cert['instrument_id']='OTHER';r=self.check();self.assertEqual(r['state'],'record_attention');self.assertEqual(r['file_state'],'verified')
    def test_wrong_unit_is_record_error(self):
        self.cert['unit']='mΩ';self.assertEqual(self.check()['state'],'record_attention')
    def test_issued_before_calibration_is_record_error(self):
        self.cert['issued']='2026-09-01T07:59:59';self.assertEqual(self.check()['state'],'record_attention')
    def test_issued_after_link_is_record_error(self):
        self.cert['issued']='2026-09-02T08:00:00';self.assertEqual(self.check()['state'],'record_attention')
    def test_link_before_calibration_registration_is_record_error(self):
        self.cert['issued']='2026-09-01T08:00:00';self.data['metrology_certificate_links'][0]['registered']='2026-09-01T08:00:30'
        self.assertEqual(self.check()['state'],'record_attention')
    def test_missing_file_identity_is_file_missing(self):
        self.cert['file_id']=None;self.assertEqual(self.check()['state'],'file_missing')
    def test_expected_file_hash_does_not_match_archive(self):
        self.cert['file_sha256']='b'*64;self.assertEqual(self.check()['state'],'file_attention')
    def test_invalid_declared_hash_is_not_content_consistency(self):
        self.cert['file_sha256']='bad';self.assertEqual(self.check()['state'],'record_attention')
    def test_unreadable_file_reveals_no_filename_or_raw_content(self):
        self.file_state='no_access';r=self.check();self.assertEqual(r['state'],'no_access');self.assertIsNone(r['file']);self.assertIsNone(r['parsed']);self.assertEqual(r['comparison'],[])
    def test_record_error_remains_separate_from_file_permission(self):
        self.cert['unit']='mΩ';self.file_state='no_access';r=self.check();self.assertEqual(r['state'],'record_attention');self.assertEqual(r['file_state'],'no_access');self.assertIsNone(r['file'])
    def test_missing_archive_bytes_is_not_unknown_identity(self):
        self.file_state='file_missing';self.assertEqual(self.check()['state'],'file_missing')
    def test_tampered_archive_is_not_consistent(self):
        self.file_state='file_attention';self.assertEqual(self.check()['state'],'file_attention')
    def test_original_field_mismatch_is_visible(self):
        self.raw_override=self.raw().replace(b'SIM1',b'SIM_WRONG');r=self.check();self.assertEqual(r['state'],'content_attention')
        self.assertFalse(next(x for x in r['comparison'] if x['field']=='certificate_no')['matched'])
    def test_reminder_window_uses_natural_time(self):
        self.assertEqual(self.e(window=8).index['I1']['due_state'],'later');self.assertEqual(self.e(window=9).index['I1']['due_state'],'due')
    def test_reminder_window_boundary_inclusive(self):
        self.d['metrology_calibrations'][0]['valid_until']=self.cert['valid_until']='2026-09-30T12:00:00'
        self.assertEqual(self.e(window=8).index['I1']['due_state'],'due')
    def test_expiry_boundary_is_expired_not_reminder(self):
        self.d['metrology_calibrations'][0]['valid_until']=self.cert['valid_until']=AT
        self.assertEqual(self.e().index['I1']['due_state'],'expired')
    def test_invalid_reminder_windows(self):
        for value in [0,366,True,'30',1.5]:
            with self.subTest(value=value),self.assertRaises(ValueError):self.e(window=value)
    def test_archives_do_not_increase_current_instrument_denominator(self):
        i=deepcopy(self.d['metrology_instruments'][0]);i.update(id='ARCHIVE',stage='档案');self.d['metrology_instruments'].append(i)
        e=self.e();self.assertEqual(summary(e.cohort({}))['objects'],1);self.assertEqual(summary(e.cohort({'archives':'1'}))['archives'],1)
    def test_not_required_is_separate_from_unknown_requirement(self):
        self.d['metrology_rules'][0]['required']=False;self.assertEqual(self.e().index['I1']['evidence_state'],'not_required')
        self.d['metrology_rules']=[];self.assertEqual(summary(self.e().cohort({}))['unknown_requirement'],1)
    def test_parser_rejects_extra_and_duplicate_headers(self):
        raw=self.raw().decode('utf-8-sig')
        for header in [','.join(HEADERS)+',extra',','.join(HEADERS[:-1]+[HEADERS[0]])]:
            self.assertEqual(parse((header+'\n'+raw.splitlines()[1]).encode(),'csv')['mode'],'invalid')
    def test_parser_rejects_multiple_claim_rows(self):
        raw=self.raw().decode('utf-8-sig');self.assertEqual(parse((raw+raw.splitlines()[1]+'\n').encode(),'csv')['mode'],'invalid')
    def test_parser_rejects_invalid_dates_and_binary_null(self):
        self.assertEqual(parse(self.raw().replace(b'2026-09-01T08:30:00',b'invalid'),'csv')['mode'],'invalid')
        self.assertEqual(parse(self.raw()+b'\x00','csv')['mode'],'invalid')
    def test_non_csv_is_explicitly_manual(self):
        self.assertEqual(parse(b'%PDF-1.4','pdf')['mode'],'manual')
