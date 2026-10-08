import copy,json
from unittest.mock import patch
from django.test import SimpleTestCase,Client,RequestFactory
from django.contrib.auth.models import User,Group
from django.core.exceptions import PermissionDenied
from app import joint_comparison as engine,joint_comparison_views as views,joint_schedule,joint_schedule_data
from app.import_review import ReviewConflict
from app.models import Record,AuditEvent,AccountAccessState
from app.ingestion import fingerprint
from .test_platform import PlatformCase
from .test_joint_schedule import fixture

class JointComparisonRules(SimpleTestCase):
    def setUp(self):
        self.left=joint_schedule.analyze(*fixture());self.right=copy.deepcopy(self.left);self.right.update(policy='priority',policy_name='批次优先级优先')
    def result(self):return engine.compare(self.left,self.right)
    def test_equal_outputs_reconcile_without_double_counting(self):
        d=self.result();self.assertEqual(d['summary']['jobs'],1);self.assertEqual(d['summary']['qty'],2);self.assertEqual(d['summary']['same'],1);self.assertEqual(d['summary']['changed_tasks'],0);self.assertEqual(sum(r['qty'] for r in d['transitions']),2)
    def test_negative_minutes_are_earlier_and_lateness_has_same_direction(self):
        self.right['jobs'][0].update(finished='2026-10-02T08:45:00',lateness_minutes=0);d=self.result();self.assertEqual(d['jobs'][0]['finish_delta_minutes'],-10);self.assertEqual(d['summary']['earlier'],1)
        self.right['jobs'][0].update(finished='2026-10-02T09:15:00',state='late',lateness_minutes=15);d=self.result();self.assertEqual(d['jobs'][0]['finish_delta_minutes'],20);self.assertEqual(d['jobs'][0]['lateness_delta_minutes'],15)
    def test_blocked_completion_never_replaced_by_zero(self):
        self.right['jobs'][0].update(finished=None,state='blocked',lateness_minutes=None);d=self.result();self.assertIsNone(d['jobs'][0]['finish_delta_minutes']);self.assertIsNone(d['jobs'][0]['lateness_delta_minutes']);self.assertEqual(d['summary']['no_longer_complete'],1)
        self.left['jobs'][0].update(finished=None,state='blocked',lateness_minutes=None);self.assertEqual(self.result()['summary']['both_blocked'],1)
        self.right['jobs'][0].update(finished='2026-10-02T09:00:00',state='scheduled',lateness_minutes=0);self.assertEqual(self.result()['summary']['newly_complete'],1)
    def test_paused_is_not_empty_healthy_comparison(self):
        self.right.update(state='paused',summary=None,issues=['资料不足']);d=self.result();self.assertEqual(d['state'],'paused');self.assertIsNone(d['summary']);self.assertFalse(d['jobs']);self.assertEqual(d['columns']['priority']['issues'],['资料不足'])
    def test_identity_scope_and_assumption_mismatch_fail_closed(self):
        for change in (lambda r:r['jobs'].clear(),lambda r:r['jobs'].append(copy.deepcopy(r['jobs'][0])),lambda r:r['jobs'][0].update(qty=5),lambda r:r['tasks'][0].update(route_id='OTHER'),lambda r:r['study'].update(version='V2')):
            self.setUp();change(self.right)
            with self.assertRaises(ReviewConflict):self.result()
    def test_policy_direction_is_fixed(self):
        self.right['policy']='due'
        with self.assertRaises(ReviewConflict):self.result()
    def test_assignment_and_root_cause_changes_retained(self):
        self.right['tasks'][0].update(employee_id='OTHER',root_tasks=['PREV'],reason='等待');r=self.result()['tasks'][0];self.assertIn('employee_id',r['changes']);self.assertIn('root_tasks',r['changes']);self.assertEqual(r['right']['root_tasks'],['PREV'])
    def test_material_delta_decimal_and_conservation(self):
        b=self.right['balances'][0];b.update(reserved_qty='4.999',total_remaining_qty='0.001');r=self.result()['materials'][0];self.assertEqual((r['reserved_delta_qty'],r['remaining_delta_qty']),('-0.001','0.001'))
        b['total_remaining_qty']='1'
        with self.assertRaises(ReviewConflict):self.result()
    def test_allocation_union_and_timing_not_only_total(self):
        self.right['reservations'][0]['reserved_at']='2026-10-02T09:00:00';d=self.result();self.assertEqual(d['summary']['changed_allocations'],1);self.assertEqual(d['allocations'][0]['qty_delta'],'0')
        self.right['reservations'].pop(0);r=self.result()['allocations'][0];self.assertIsNone(r['right']);self.assertEqual(r['qty_delta'],'-3')
    def test_reordered_rows_pair_by_identity_not_position(self):
        self.right['tasks'].reverse();self.right['balances'].reverse();self.assertEqual(self.result()['summary']['changed_tasks'],0)
    def test_compare_does_not_mutate_calculator_outputs(self):
        old=copy.deepcopy((self.left,self.right));self.result();self.assertEqual(old,(self.left,self.right))
    def test_source_and_parent_mismatch_rejected(self):
        left=dict(source_hash='a',rule_hash='b',sources=[],tables={},references={},parent=dict(tables={},base=dict(tables={})));right=copy.deepcopy(left);engine.same_inputs(left,right)
        for key in ('source_hash','rule_hash','sources','tables','references'):
            right=copy.deepcopy(left);right[key]='changed'
            with self.assertRaises(ReviewConflict):engine.same_inputs(left,right)
        right=copy.deepcopy(left);right['parent']['tables']={'extra':[]}
        with self.assertRaises(ReviewConflict):engine.same_inputs(left,right)

class JointComparisonAPI(PlatformCase):
    def setUp(self):
        super().setUp();study,tables,parent,refs=fixture();self.record('joint_studies',study);self.record('crew_studies',parent['result']['study']);self.record('schedule_studies',parent['base']['study'])
        for ds,rows in {**tables,**parent['tables'],**parent['base']['tables']}.items():
            for row in rows:self.record(ds,row)
        for ds,rows in refs.items():
            for row in rows.values():self.record(ds,row)
        self.client.force_login(self.admin)
    def call(self,suffix='',body=None,status=200):
        r=self.client.post('/api/joint-comparison/MP1'+suffix,json.dumps(body or {}),content_type='application/json');self.assertEqual(r.status_code,status,r.content[:200]);return r
    def read(self):return self.call().json()
    def change(self,ds,key,**values):
        r=Record.objects.get(dataset=ds,business_key=key);r.values.update(values);r.record_hash=fingerprint(r.values);r.revision+=1;r.save();s=r.source_row;s.normalized=r.values;s.record_hash=r.record_hash;s.save()
    def test_normal_comparison_matches_each_existing_calculator(self):
        d=self.read();self.assertEqual(d['state'],'compared');self.assertEqual(d['summary']['tasks'],4)
        for policy,side in [('due','left'),('priority','right')]:
            original=self.client.get('/api/joint-schedule/MP1',dict(policy=policy,receipt=d['policy_receipts'][policy])).json();self.assertEqual(d['columns'][policy]['summary'],original['summary']);self.assertEqual(d['jobs'][0][side],original['jobs'][0])
    def test_six_roles_and_anonymous(self):
        self.client.logout();self.call(status=401)
        for role in ('admin','analyst','operations','quality','finance','viewer'):
            u=User.objects.filter(username=role).first() or User.objects.create_user(role);u.groups.add(Group.objects.get_or_create(name=role)[0]);self.client.force_login(u);self.call(status=200 if role in ('admin','analyst','operations') else 403)
    def test_strict_json_queries_methods_csrf_and_no_cache(self):
        self.assertEqual(self.call()['Cache-Control'],'no-store');self.assertEqual(self.client.get('/api/joint-comparison/MP1').status_code,405)
        self.assertEqual(self.client.post('/api/joint-comparison/MP1?q=x','{}',content_type='application/json').status_code,400)
        self.assertEqual(self.client.post('/api/joint-comparison/MP1','{"receipt":"x","receipt":"y"}',content_type='application/json').status_code,400)
        self.call(body={'policy':'due'},status=400);self.call(body={'receipt':None},status=400)
        c=Client(enforce_csrf_checks=True);c.force_login(self.admin);self.assertEqual(c.post('/api/joint-comparison/MP1','{}',content_type='application/json').status_code,403)
    def test_source_paging_detail_and_empty_or_invalid_page(self):
        d=self.read();s=self.call('/sources',{'receipt':d['receipt']}).json();self.assertEqual(s['total'],d['source_count']);self.assertEqual(len(s['rows']),min(40,s['total']))
        self.assertFalse(self.call('/sources',dict(receipt=d['receipt'],page=10000)).json()['rows'])
        for p in (0,'1',True,10001):self.call('/sources',dict(receipt=d['receipt'],page=p),400)
        t=self.call('/tasks/'+d['tasks'][0]['id'],dict(receipt=d['receipt'])).json();self.assertEqual(t['task'],d['tasks'][0]);self.assertTrue(t['left']['demands']);self.call('/tasks/OTHER',dict(receipt=d['receipt']),404)
    def test_required_receipt_expiry_and_tamper(self):
        self.call('/sources',status=400);self.call('/export',{'receipt':None},400);self.call('/export',{'receipt':'bad'},409)
        with patch('django.core.signing.time.time',return_value=0):d=self.read()
        self.call('/sources',{'receipt':d['receipt']},409)
    def test_account_epoch_and_cross_user_receipts(self):
        d=self.read();AccountAccessState.objects.create(user=self.admin,revision=2);self.call('/sources',{'receipt':d['receipt']},409)
        d=self.read();u=User.objects.create_user('other');u.groups.add(Group.objects.get(name='admin'));self.client.force_login(u);self.call('/sources',{'receipt':d['receipt']},409)
    def test_current_role_and_disabled_account_checked(self):
        req=RequestFactory().post('/api/joint-comparison/MP1','{}',content_type='application/json');req.user=self.admin;User.objects.filter(pk=self.admin.pk).update(is_active=False);self.assertEqual(views.board(req,'MP1').status_code,403)
    def test_changed_fact_source_or_rules_reject_old_receipt(self):
        d=self.read();self.change('joint_supplies','L1',qty=6);self.call('/sources',{'receipt':d['receipt']},409)
        d=self.read();self.batch.filename='renamed.xlsx';self.batch.save();self.call('/sources',{'receipt':d['receipt']},409)
        d=self.read()
        with patch('app.joint_comparison_views.rules',return_value='changed'):self.call('/sources',{'receipt':d['receipt']},409)
    def test_export_complete_no_receipts_and_read_only(self):
        before=list(Record.objects.values());d=self.read();self.assertEqual(AuditEvent.objects.count(),0)
        for fmt in ('json','csv'):
            r=self.call('/export',dict(receipt=d['receipt'],format=fmt));self.assertEqual(r['Cache-Control'],'no-store');out=r.json();self.assertNotIn(d['receipt'],out['text']);self.assertNotIn('hourly_cents',out['text'])
            if fmt=='json':
                doc=json.loads(out['text']);self.assertEqual(len(doc['comparison']['tasks']),4);self.assertEqual(doc['left']['material_inputs'],doc['right']['material_inputs']);self.assertIn('sources',doc['left'])
            else:self.assertIn('两列共同来源',out['text']);self.assertIn('right/resource_inputs/schedule_tasks',out['text'])
        self.assertEqual(before,list(Record.objects.values()));self.assertEqual(AuditEvent.objects.count(),2)
    def test_export_failure_atomicity_and_invalid_format(self):
        d=self.read();self.call('/export',dict(receipt=d['receipt'],format='html'),400)
        with patch('app.joint_comparison_views.AuditEvent.objects.create',side_effect=ValueError('audit failed')):self.call('/export',dict(receipt=d['receipt']),400)
        self.assertFalse(AuditEvent.objects.exists())
    def test_paused_export_preserves_all_original_inputs(self):
        self.change('joint_demands','D1',required_qty=999);d=self.read();self.assertEqual(d['state'],'paused');self.assertIsNone(d['summary'])
        doc=json.loads(self.call('/export',{'receipt':d['receipt']}).json()['text']);self.assertEqual(len(doc['left']['material_inputs']['joint_demands']),3);self.assertEqual(len(doc['right']['resource_inputs']['schedule_tasks']),4)
    def test_csv_formula_guard_retains_json_original(self):
        self.change('joint_studies','MP1',name='=SUM(1,2)');d=self.read();out=self.call('/export',dict(receipt=d['receipt'],format='csv')).json()['text'];self.assertIn("'=SUM",out)
        doc=json.loads(self.call('/export',dict(receipt=d['receipt'])).json()['text']);self.assertEqual(doc['comparison']['study']['name'],'=SUM(1,2)')
