import json,csv,io
from copy import deepcopy
from unittest.mock import patch
from django.test import TestCase,Client
from django.contrib.auth.models import User,Group
from app import wip_views
from app.models import Record,AuditEvent
from tests.test_wip_flow import fixture,event,lot

class WipAPITests(TestCase):
    def setUp(self):
        self.user=User.objects.create_user('wip-viewer');self.user.groups.add(Group.objects.create(name='viewer'));self.client.force_login(self.user)
        self.data=fixture();self.rev=(0,0);wip_views.current.cache_clear()
        self.patches=[patch('app.analytics.tables',side_effect=lambda:self.data),patch('app.analytics.revision',side_effect=lambda:self.rev)]
        for p in self.patches:p.start();self.addCleanup(p.stop)
        self.addCleanup(wip_views.current.cache_clear)
        self.scope={'as_of':'2026-09-02T18:00:00'}
    def read(self,extra=None):
        r=self.client.get('/api/wip-flow',self.scope|(extra or {}));self.assertEqual(r.status_code,200);return r.json()
    def bound(self,extra=None):
        q=self.scope|(extra or {});return q|{'receipt':self.read(extra)['receipt']}
    def test_authentication_and_read_only_methods(self):
        self.assertEqual(Client().get('/api/wip-flow').status_code,401)
        self.assertEqual(self.client.post('/api/wip-flow').status_code,405)
    def test_summary_list_and_positions_use_same_root_cohort(self):
        d=self.read({'work_order_id':'WO1'});self.assertEqual(d['summary']['objects'],1);self.assertEqual(d['total'],1)
        self.assertEqual(d['summary']['groups'][0]['wip_qty'],10);self.assertEqual(d['positions'][0]['share_qty'],10)
        self.assertEqual(d['rows'][0]['id'],'R1');self.assertNotIn('expected_consumption_sn',d['rows'][0])
    def test_detail_requires_receipt_and_selected_scope(self):
        self.assertEqual(self.client.get('/api/wip-flow/rows/R1',self.scope).status_code,400)
        q=self.bound({'work_order_id':'WO1'});self.assertEqual(self.client.get('/api/wip-flow/rows/R1',q).status_code,200)
        self.assertEqual(self.client.get('/api/wip-flow/rows/R2',q).status_code,404)
    def test_old_receipt_rejected_on_filter_cutoff_revision_or_role_change(self):
        q=self.bound()
        self.assertEqual(self.client.get('/api/wip-flow/rows/R1',q|{'kind':'定子'}).status_code,409)
        self.assertEqual(self.client.get('/api/wip-flow/rows/R1',q|{'as_of':'2026-09-01T18:00:00'}).status_code,409)
        self.rev=(1,1);self.assertEqual(self.client.get('/api/wip-flow/rows/R1',q).status_code,409)
        q=self.bound();self.user.groups.clear();self.user.groups.add(Group.objects.create(name='quality'))
        self.assertEqual(self.client.get('/api/wip-flow/rows/R1',q).status_code,401)
        self.client.force_login(self.user)
        self.assertEqual(self.client.get('/api/wip-flow/rows/R1',q).status_code,409)
    def test_conflicting_roles_and_inactive_account_cannot_read(self):
        self.user.groups.add(Group.objects.create(name='quality'));self.assertEqual(self.client.get('/api/wip-flow').status_code,401)
        self.user.groups.clear();self.user.is_active=False;self.user.save();self.assertEqual(self.client.get('/api/wip-flow').status_code,401)
    def test_rule_version_change_invalidates_export(self):
        q=self.bound()
        with patch('app.wip_views.rule_hash',return_value='changed-rules'):self.assertEqual(self.client.get('/api/wip-flow/export',q).status_code,409)
    def test_strict_unknown_repeated_invalid_fields(self):
        for q in [{'page':'0'},{'stage':'wrong'},{'as_of':'2026-10-02T00:00:00'},{'as_of':'2026-09-01 08:00:00'},{'from':'2026-9-1'},{'from':'2026-09-02','to':'2026-09-01'},{'family':'missing'},{'work_order_id':'missing'},{'unused':'x'}]:
            with self.subTest(q=q):self.assertEqual(self.client.get('/api/wip-flow',self.scope|q).status_code,400)
        self.assertEqual(self.client.get('/api/wip-flow?kind=定子&kind=转子').status_code,400)
    def test_csv_exports_are_complete_and_preserve_null_vs_zero(self):
        self.data['wip_openings']=[x for x in self.data['wip_openings'] if x['root_batch_id']!='R1']
        event(self.data,'S','报废登记',[('L2','A','R2',10)],[('L2','SCRAP','R2',10)])
        q=self.bound();r=self.client.get('/api/wip-flow/export',q);self.assertEqual(r.status_code,200);self.assertEqual(r['Cache-Control'],'no-store')
        rows=list(csv.reader(io.StringIO(r.content.decode('utf-8-sig'))));self.assertEqual(len(rows),7)
        index={v:i for i,v in enumerate(rows[4])};objects={row[0]:row for row in rows[5:]}
        self.assertEqual(objects['R1'][index['可核对在制件数']],'');self.assertEqual(objects['R2'][index['可核对在制件数']],'0')
        self.assertEqual(AuditEvent.objects.filter(action='wip.export').count(),1)
    def test_cross_wo_position_export_preserves_share_and_whole_quantity(self):
        lot(self.data,'LM');event(self.data,'M','合批',[('L1','A','R1',10),('L2','A','R2',10)],[('LM','B','R1',10),('LM','B','R2',10)])
        q=self.bound({'work_order_id':'WO1'});r=self.client.get('/api/wip-flow/positions-export',q)
        rows=list(csv.reader(io.StringIO(r.content.decode('utf-8-sig'))));self.assertEqual(len(rows),6)
        cols={v:i for i,v in enumerate(rows[4])};self.assertEqual(rows[5][cols['本原批次份额件数']],'10');self.assertEqual(rows[5][cols['整批已核定位置件数']],'20')
    def test_detail_read_does_not_change_business_facts(self):
        q=self.bound();before=[Record.objects.count(),AuditEvent.objects.count()];r=self.client.get('/api/wip-flow/rows/R1',q)
        self.assertEqual(r.status_code,200);self.assertEqual([Record.objects.count(),AuditEvent.objects.count()],before)
        self.assertEqual(r['Cache-Control'],'no-store')
    def test_evidence_download_right_does_not_follow_read_right(self):
        r=self.client.get('/api/wip-flow/rows/R1/evidence',self.bound());self.assertEqual(r.status_code,200)
        self.assertFalse(r.json()['can_download_original']);self.assertTrue(r.json()['rows'])
    def test_future_replay_is_separate_from_root_created_cohort(self):
        self.data['work_orders'].append(dict(id='WO3',product_id='P01',planned_start='2026-09-01',status='未开工'))
        d=self.read({'work_order_id':'WO3'});self.assertEqual(d['summary']['objects'],0);self.assertEqual(d['plan_context']['total'],1)
        self.assertNotIn('planned_qty',d['plan_context']['rows'][0])
    def late_bad(self):
        event(self.data,'T','工序交接',[('L1','A','R1',10)],[('L1','B','R1',10)])
        event(self.data,'T','工序交接',[('L1','A','R1',10)],[('L1','B','R1',9)],version=2,previous='T-V1',recorded='2026-09-03T10:00:00')
    def test_registration_cutoff_is_explicit_validated_and_bound(self):
        self.late_bad();old=self.bound();new=self.bound({'known_as_of':'2026-09-04T18:00:00'})
        self.assertNotEqual(old['receipt'],new['receipt'])
        self.assertEqual(self.client.get('/api/wip-flow/comparison',old|{'known_as_of':new['known_as_of']}).status_code,409)
        for at in ['', '2026-09-01T18:00:00','2026-10-02T18:00:00','2026-09-04T18:00:00Z']:
            self.assertEqual(self.client.get('/api/wip-flow',self.scope|{'known_as_of':at}).status_code,400)
        self.assertEqual(self.client.get('/api/wip-flow?known_as_of=2026-10-01T18:00:00&known_as_of=2026-10-01T18:00:00').status_code,400)
    def test_comparison_reports_unknown_without_false_negative_quantity(self):
        self.late_bad();q=self.bound({'known_as_of':'2026-09-04T18:00:00'});r=self.client.get('/api/wip-flow/comparison',q)
        self.assertEqual(r.status_code,200);d=r.json();self.assertEqual((d['summary']['objects'],d['total']),(2,1));self.assertEqual(d['summary']['outcome_changed'],1)
        self.assertIsNone(d['rows'][0]['wip_delta']);g=d['summary']['groups'][0];self.assertEqual((g['both_verified'],g['lost_verification'],g['comparable_delta']),(1,1,0))
    def test_comparison_uses_fixed_right_state_selection(self):
        self.late_bad();q=self.bound({'known_as_of':'2026-09-04T18:00:00','stage':'attention'});d=self.client.get('/api/wip-flow/comparison',q).json()
        self.assertEqual(d['summary']['objects'],1);self.assertEqual(d['rows'][0]['before']['state'],'active')
        self.assertEqual(self.client.get('/api/wip-flow/comparison/rows/R2',q).status_code,404)
    def test_comparison_requires_login_receipt_and_read_only_methods(self):
        for path in ['/api/wip-flow/comparison','/api/wip-flow/comparison/export','/api/wip-flow/comparison/rows/R1']:
            self.assertEqual(Client().get(path).status_code,401)
            self.assertEqual(self.client.get(path,self.scope).status_code,400)
            self.assertEqual(self.client.post(path).status_code,405)
    def test_comparison_detail_preserves_versions_and_two_cutoff_flags(self):
        self.late_bad();q=self.bound({'known_as_of':'2026-09-04T18:00:00'});d=self.client.get('/api/wip-flow/comparison/rows/R1',q).json()
        v=d['row']['version_changes'][0];self.assertEqual(v['before']['selected_id'],'T-V1');self.assertEqual(v['after']['selected_id'],'T-V2')
        h=self.client.get('/api/wip-flow/rows/R1',q).json()['events'][0]['versions'][-1]
        self.assertTrue(h['selected']);self.assertFalse(h['after_business_cutoff']);self.assertFalse(h['after_known_cutoff']);self.assertFalse(h['after_cutoff'])
    def test_comparison_csv_contains_full_selected_cohort_and_null_delta(self):
        self.late_bad();q=self.bound({'known_as_of':'2026-09-04T18:00:00'});r=self.client.get('/api/wip-flow/comparison/export',q);self.assertEqual(r.status_code,200)
        rows=list(csv.reader(io.StringIO(r.content.decode('utf-8-sig'))));self.assertEqual(len(rows),7);self.assertIn(q['known_as_of'],rows[0])
        cols={v:i for i,v in enumerate(rows[4])};data={r[0]:r for r in rows[5:]}
        self.assertEqual(data['R1'][cols['同批次可比在制差']],'');self.assertEqual(data['R2'][cols['同批次可比在制差']],'0')
        self.assertEqual(AuditEvent.objects.filter(action='wip.comparison_export').count(),1)
    def test_comparison_read_is_immutable_and_revision_change_rejects_receipt(self):
        q=self.bound();before=[Record.objects.count(),AuditEvent.objects.count()]
        self.assertEqual(self.client.get('/api/wip-flow/comparison',q).status_code,200)
        self.assertEqual(self.client.get('/api/wip-flow/comparison/rows/R1',q).status_code,200)
        self.assertEqual([Record.objects.count(),AuditEvent.objects.count()],before)
        self.rev=(1,1);self.assertEqual(self.client.get('/api/wip-flow/comparison/export',q).status_code,409)
    def test_comparison_scope_and_rule_changes_reject_old_receipt(self):
        q=self.bound({'work_order_id':'WO1'});self.assertEqual(self.client.get('/api/wip-flow/comparison/rows/R2',q).status_code,404)
        self.assertEqual(self.client.get('/api/wip-flow/comparison',q|{'q':'different'}).status_code,409)
        with patch('app.wip_views.rule_hash',return_value='different'):
            self.assertEqual(self.client.get('/api/wip-flow/comparison/export',q).status_code,409)
    def test_no_change_comparison_is_empty_but_full_cohort_is_reported(self):
        q=self.bound();d=self.client.get('/api/wip-flow/comparison',q).json();self.assertEqual(d['rows'],[]);self.assertEqual(d['summary']['unchanged'],2);self.assertEqual(d['summary']['objects'],2)
