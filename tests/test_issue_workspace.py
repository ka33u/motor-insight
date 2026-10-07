import csv,io,json,uuid
from datetime import date
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import parse_qs,urlencode
from django.contrib.auth.models import User,Group
from django.core import signing
from django.http import QueryDict
from django.test import Client
from app import issue_workspace as iw,coordination_hub as hub
from app.models import Record,IssueDisposition,AuditEvent
from .test_platform import PlatformCase

class IssueWorkspaceTests(PlatformCase):
 def setUp(self):
  super().setUp()
  for role in ('analyst','operations','finance','viewer'):
   u=User.objects.create_user(role,password='!');u.groups.add(Group.objects.get_or_create(name=role)[0]);setattr(self,role,u)
  self.unit=self.record('units',dict(id='SN001',product_id='P1',work_order_id='WO1',assembly_at='2026-09-21T10:00:00',status='待检'))
  self.product=self.record('products',dict(id='P1',family='YE3',model='试验配置',price_cents=123456))
  self.session=self.record('test_sessions',dict(id='TS1',unit_id='SN001',result='合格',tested='2026-09-21T12:00:00',raw_file='设备本地引用.xlsx'))
  self.line=self.record('order_lines',dict(id='L1',net_cents=887700));self.record('delivery_plans',dict(id='DP1',order_line_id='L1',qty=10))
  self.record('tools',dict(id='T1',name='试验量具'))
  self.rows=[self.qrow('SN001','YE3',['failed','attention']),self.qrow('SN002','YE3',['untested']),self.qrow('SN003','YE4',[],True,False),self.qrow('SN004','YE3',['incomplete']),self.qrow('SN005','YE3',['release'])]
  self.tables={'nonconformities':[dict(id='NCR1',unit_id='SN001',found='2026-09-22T10:00:00',closed=False,due='2026-09-30',description='模拟整改'),dict(id='NCR-FUTURE',unit_id='SN001',found='2026-10-02T10:00:00',closed=False,due='2026-09-30',description='未来不纳入')]}
  self.raw={'families':['YE3','YE4'],'as_of':'2026-10-01T18:00:00','late_plans':[dict(id='DP1',line='L1',remaining=10,days=2)],'issues':[dict(key='校准到期T1',kind='校准到期',object='T1',owner='设备计量',detail='量具到期')], 'kpis':[{'key':k,'value':i,'name':k,'denominator':None} for i,k in enumerate(('otif','fpy','coverage','late','produced','shipped'))]}
  self.quality_data=SimpleNamespace(rows=self.rows,detail=lambda key:{'sources':[dict(dataset='units',key=key),dict(dataset='products',key='P1'),dict(dataset='test_sessions',key='TS1')] if key=='SN001' else [dict(dataset='units',key=key)]})
  self.mocks=[patch('app.issue_workspace.analytics.overview',side_effect=lambda family='':{**self.raw,'late_plans':self.raw['late_plans'] if family!='YE4' else []}),patch('app.issue_workspace.quality_board.current',return_value=self.quality_data),patch('app.issue_workspace.analytics.tables',side_effect=lambda:self.tables),patch('app.issue_workspace.timezone.localdate',return_value=date(2026,10,6))]
  for p in self.mocks:p.start();self.addCleanup(p.stop)
  self.client.force_login(self.admin)
 def qrow(self,key,family,flags,release=False,shipped=False):return dict(id=key,family=family,flags=flags,release_valid=release,shipped=shipped,work_order_id='WO1',product_id='P1',issues=['设备记录待核对'])
 def workspace(self,scope=None,user=None):return iw.Workspace(user or self.admin,iw.filters(scope or {}))
 def get(self,scope=None):return self.client.get('/api/issue-workspace',scope or {})
 def info(self,key='quality-observation:failed:SN001',scope=None,receipt=None):
  d=self.workspace(scope);return self.client.get('/api/issue-workspace/rows/'+key,{**d.filters,'receipt':receipt or d.receipt})
 def payload(self,d=None,**changes):
  d=d or self.workspace();return dict(scope=d.filters,receipt=d.receipt,version=0,status='处理中',owner='模拟质量岗位',note='模拟核查依据，等待复核',due_date='2026-10-05',request_id=str(uuid.uuid4()),**changes)
 def save(self,p=None,key='quality-observation:failed:SN001'):return self.post('/api/issue-workspace/rows/'+key+'/follow-up',p or self.payload())
 def export(self,d=None,receipt=None):
  d=d or self.workspace();return self.client.get('/api/issue-workspace/export',{**d.filters,'receipt':receipt or d.receipt})
 def facts(self):return list(Record.objects.order_by('id').values())

 def test_observations_not_distinct_objects_and_all_nine_kinds(self):
  d=self.get().json();self.assertEqual((d['total'],d['summary']['distinct_objects']),(9,7));self.assertEqual(set(d['kind_counts']),set(iw.KINDS));self.assertEqual(d['today'],'2026-10-06')
 def test_future_ncr_is_excluded(self):self.assertNotIn('ncr:NCR-FUTURE',self.workspace().index)
 def test_family_limits_unit_and_plan_but_tools_explicitly_global(self):
  d=self.get({'family':'YE4'}).json();self.assertEqual(d['total'],2);r=next(r for r in d['rows'] if r['dataset']=='tools');self.assertIn('全厂',r['scope']);self.assertIn('tab=tool',r['object_href']);self.assertNotIn('SN001',json.dumps(d))
 def test_same_object_can_be_multiple_observations(self):
  d=self.get({'q':'SN001'}).json();self.assertEqual(d['total'],3);self.assertEqual(d['summary']['distinct_objects'],1)
 def test_same_scope_detail_and_task_links(self):
  d=self.get({'family':'YE3','kind':'终检不合格'}).json();r=d['rows'][0];self.assertIn('family=YE3',r['object_href']);self.assertIn('dataset=units',r['task_href'])
 def test_unknown_and_duplicate_filters_fail(self):
  for query in ('bad=1','family=YE3&family=YE4','page=1&page=2'):
   with self.subTest(query=query):self.assertEqual(self.client.get('/api/issue-workspace?'+query).status_code,400)
 def test_invalid_values_family_and_page_fail(self):
  for p in ({'family':'MISSING'},{'kind':'待放行'},{'status':'已批准'},{'severity':'低'},{'page':'0'},{'page':'1.5'},{'q':'x'*256}):
   with self.subTest(p=p):self.assertEqual(self.get(p).status_code,400)
 def test_intersection_filters_owners_are_literal(self):
  self.save();d=self.get(dict(kind='终检不合格',family='YE3',status='处理中',owner='模拟质量岗位',q='等待复核',severity='高')).json();self.assertEqual(d['total'],1)
 def test_empty_range_has_zero_summary_and_no_rows(self):
  d=self.get({'q':'NOTFOUND'}).json();self.assertEqual(d['total'],0);self.assertEqual(d['rows'],[]);self.assertTrue(all(v==0 for v in d['summary'].values()))
 def test_server_paging_beyond_150_and_focus_location(self):
  self.rows[:]=[self.qrow(f'SN{i:04}','YE3',['untested']) for i in range(181)];self.raw['issues']=[];self.raw['late_plans']=[];self.tables['nonconformities']=[]
  d=self.get({'page':'7'}).json();self.assertEqual((d['total'],len(d['rows'])),(181,1));self.assertEqual(d['rows'][0]['object'],'SN0180')
  focus=self.get({'focus':'quality-observation:untested:SN0180'}).json();self.assertEqual(focus['page'],7);self.assertTrue(focus['focus_found'])
 def test_focus_does_not_filter_or_bypass_scope(self):
  d=self.get({'family':'YE4','focus':'quality-observation:failed:SN001'}).json();self.assertFalse(d['focus_found']);self.assertEqual(d['total'],2)
 def test_export_contains_whole_scope_not_only_visible_page(self):
  self.rows[:]=[self.qrow(f'SN{i:04}','YE3',['untested']) for i in range(181)];self.raw['issues']=[];self.raw['late_plans']=[];self.tables['nonconformities']=[]
  response=self.export();rows=list(csv.reader(io.StringIO(response.content.decode('utf-8-sig'))));self.assertEqual(len(rows),185);self.assertIn('SN0180',response.content.decode('utf-8-sig'));self.assertEqual(response['Cache-Control'],'no-store')
  self.assertEqual(AuditEvent.objects.get(action='issue_workspace.export').detail['summary']['observations'],181)
 def test_export_scope_metadata_provenance_and_formula_safety(self):
  self.raw['issues'][0]['detail']='=FORMULA';d=self.workspace({'kind':'工具校准到期'});r=self.export(d);rows=list(csv.reader(io.StringIO(r.content.decode('utf-8-sig'))));self.assertEqual(rows[4][6],"'=FORMULA");self.assertIn('unit-test.xlsx',rows[4][-1]);self.assertIn('工具校准到期',rows[0][-1])
 def test_source_detail_real_file_sheet_row_and_permission(self):
  self.client.force_login(self.quality);d=self.workspace(user=self.quality);r=self.client.get('/api/issue-workspace/rows/quality-observation:failed:SN001',{**d.filters,'receipt':d.receipt}).json()
  self.assertEqual(len(r['sources']),3);p=next(x for x in r['sources'] if x['dataset']=='products');self.assertNotIn('price_cents',p['values']);self.assertEqual(p['file'],'unit-test.xlsx');self.assertEqual(p['row'],2);self.assertFalse(r['can_download_original'])
 def test_admin_can_read_money_in_permitted_source(self):self.assertEqual(next(x for x in self.info().json()['sources'] if x['dataset']=='products')['values']['price_cents'],123456)
 def test_outside_selected_detail_is_404(self):self.assertEqual(self.info(scope={'family':'YE4'}).status_code,404)
 def test_missing_source_flag_is_visible(self):self.assertTrue(self.info('quality-observation:untested:SN002').json()['row']['source_missing'])
 def test_reads_do_not_mutate_any_note_fact_or_audit(self):
  facts=self.facts();counts=(IssueDisposition.objects.count(),AuditEvent.objects.count());self.get();self.info();self.assertEqual(counts,(IssueDisposition.objects.count(),AuditEvent.objects.count()));self.assertEqual(facts,self.facts())
 def test_anonymous_and_conflicting_roles_fail(self):
  self.client.logout();self.assertEqual(self.get().status_code,401);self.admin.groups.add(Group.objects.get_or_create(name='quality')[0]);self.client.force_login(self.admin);self.assertEqual(self.get().status_code,401)
 def test_viewer_and_finance_cannot_write(self):
  for user in (self.viewer,self.finance):
   self.client.force_login(user);d=self.workspace(user=user);self.assertFalse(self.get().json()['can_follow_up']);self.assertEqual(self.save(self.payload(d)).status_code,403)
 def test_viewer_has_no_task_creation_link(self):
  self.client.force_login(self.viewer);self.assertTrue(all(not r['task_href'] for r in self.get().json()['rows']))
 def test_csrf_write_required(self):
  c=Client(enforce_csrf_checks=True);c.force_login(self.admin);self.assertEqual(c.post('/api/issue-workspace/rows/quality-observation:failed:SN001/follow-up',json.dumps(self.payload()),content_type='application/json').status_code,403)
 def test_receipt_tamper_and_cross_user_fail(self):
  receipt=self.workspace().receipt;self.assertEqual(self.info(receipt=receipt+'x').status_code,409);self.client.force_login(self.quality);self.assertEqual(self.info(receipt=receipt).status_code,409)
 def test_expired_receipt_fails_before_followup_or_export(self):
  with patch('django.core.signing.time.time',return_value=1000):d=self.workspace();p=self.payload(d)
  with patch('django.core.signing.time.time',return_value=1901):self.assertEqual(self.save(p).status_code,409);self.assertEqual(self.export(d).status_code,409)
  self.assertEqual(IssueDisposition.objects.count(),0);self.assertEqual(AuditEvent.objects.count(),0)
 def test_receipt_cannot_change_scope(self):
  d=self.workspace({'family':'YE3'});self.assertEqual(self.info(scope={'family':'YE4'},receipt=d.receipt).status_code,409)
 def test_direct_source_content_change_invalidates_even_without_revision_bump(self):
  d=self.workspace();Record.objects.filter(pk=self.session.pk).update(values={**self.session.values,'result':'不合格'});self.assertEqual(self.export(d).status_code,409);self.assertEqual(self.save(self.payload(d)).status_code,409)
 def test_source_file_header_change_invalidates_receipt(self):
  d=self.workspace();self.batch.filename='changed.xlsx';self.batch.save();self.assertEqual(self.info(receipt=d.receipt).status_code,409)
 def test_role_change_invalidates_receipt(self):
  d=self.workspace();self.admin.groups.clear();self.admin.groups.add(Group.objects.get_or_create(name='operations')[0]);self.assertEqual(self.info(receipt=d.receipt).status_code,409)
 def test_followup_version_and_history_not_source_approval(self):
  facts=self.facts();r=self.save();self.assertEqual(r.status_code,200);n=IssueDisposition.objects.get();self.assertEqual((n.version,n.key),(1,iw.note_key('quality-observation:failed:SN001')));self.assertEqual(facts,self.facts());a=AuditEvent.objects.get();self.assertFalse(a.detail['business_approval']);self.assertFalse(a.detail['business_facts_changed']);self.assertEqual(self.info().json()['history_total'],1)
 def test_repeat_idempotent_and_changed_payload_collision(self):
  p=self.payload();self.assertEqual(self.save(p).status_code,200);again=self.save(p);self.assertTrue(again.json()['repeated']);self.assertEqual(IssueDisposition.objects.get().version,1);self.assertEqual(AuditEvent.objects.count(),1);self.assertEqual(self.save({**p,'note':'修改后的核对依据'}).status_code,409)
 def test_other_followup_invalidates_old_range_receipt(self):
  d=self.workspace();self.save();self.assertEqual(self.save(self.payload(d),key='quality-observation:untested:SN002').status_code,409)
 def test_expected_version_cannot_be_ignored(self):
  self.save();p=self.payload();self.assertEqual(self.save(p).status_code,409);p['version']=1;self.assertEqual(self.save(p).status_code,200);self.assertEqual(IssueDisposition.objects.get().version,2)
 def test_saved_note_due_date_current_day_and_terminal_state(self):
  self.save();d=self.get({'kind':'终检不合格'}).json();self.assertEqual(d['summary']['followup_overdue'],1);p=self.payload();p.update(version=1,status='已核验');self.assertEqual(self.save(p).status_code,200);self.assertEqual(self.get({'kind':'终检不合格'}).json()['summary']['followup_overdue'],0);self.assertIn('quality-observation:failed:SN001',self.workspace().index)
 def test_payload_unknown_and_invalid_fields_cannot_write(self):
  for changes in ({'version':True},{'version':-1},{'request_id':'bad'},{'owner':''},{'note':'短'},{'due_date':'2026-1-1'},{'status':'已放行'},{'extra':'ignored'}):
   p=self.payload();p.update(changes)
   with self.subTest(changes=changes):self.assertEqual(self.save(p).status_code,400)
  self.assertEqual(IssueDisposition.objects.count(),0)
 def test_old_unversioned_api_cannot_write(self):
  self.assertEqual(self.post('/api/issues',{'key':'终检不合格SN001','status':'已核验'}).status_code,409);self.assertEqual(IssueDisposition.objects.count(),0)
 def test_hub_uses_saved_scope_and_hashed_namespace(self):
  d=self.workspace({'family':'YE3','kind':'终检不合格'});self.save(self.payload(d));h=hub.Hub(self.admin,date(2026,10,6));r=next(r for r in h.rows if r['domain']=='overview-issue');params=parse_qs(r['href'].partition('?')[2]);self.assertEqual(params['family'],['YE3']);self.assertEqual(params['focus'],['quality-observation:failed:SN001']);self.assertEqual(r['source_key'],'SN001');self.assertEqual(h.detail(r['id'],1)['source']['key'],'SN001')
 def test_hub_preserves_note_after_observation_disappears(self):
  self.save();self.rows[0]['flags']=[];self.assertNotIn('quality-observation:failed:SN001',self.workspace().index);self.assertTrue(any(r['domain']=='overview-issue' for r in hub.Hub(self.quality,date(2026,10,6)).rows))
 def test_hub_untrusted_missing_audit_fails_closed(self):
  IssueDisposition.objects.create(key=iw.note_key('fake'),status='处理中');self.assertEqual(hub.resolve(iw.note_key('fake')),None);self.assertFalse(hub.Hub(self.quality,date(2026,10,6)).rows)
 def test_history_pagination_exact_observation_not_same_sn_other_kind(self):
  self.save();note=IssueDisposition.objects.get();a=AuditEvent.objects.get();
  for i in range(22):AuditEvent.objects.create(action=a.action,actor=a.actor,object_type=a.object_type,object_id=note.key,detail=a.detail)
  response=self.client.get('/api/issue-workspace/rows/quality-observation:failed:SN001',{**self.workspace().filters,'receipt':self.workspace().receipt,'page':'2'}).json();self.assertEqual((response['history_total'],len(response['history'])),(23,3));self.assertEqual(self.info('quality-observation:attention:SN001').json()['history_total'],0)
 def test_home_presets_do_not_change_six_metric_values(self):
  values=self.raw['kpis'];
  for preset in ('management','quality','production','finance','read'):
   d=self.client.get('/api/overview',{'preset':preset}).json();self.assertEqual(d['kpis'],values);self.assertEqual(len(d['presentation']['primary']),3);self.assertIn('总览 v1',d['presentation']['boundary'])
 def test_home_default_role_and_no_money_profile_for_quality(self):
  self.client.force_login(self.quality);d=self.client.get('/api/overview').json();self.assertEqual(d['presentation']['preset'],'quality');self.assertNotIn('finance',[x['key'] for x in d['presentation']['choices']]);self.assertEqual(self.client.get('/api/overview',{'preset':'finance'}).status_code,400)
 def test_home_strict_scope_and_propagated_counts(self):
  d=self.client.get('/api/overview',{'family':'YE4'}).json();self.assertEqual(d['presentation']['scope']['family'],'YE4');self.assertEqual(d['presentation']['kind_counts']['合格已放行待发运'],1);self.assertEqual(d['presentation']['kind_counts']['终检不合格'],0);self.assertEqual(self.client.get('/api/overview?family=YE3&family=YE4').status_code,400)
