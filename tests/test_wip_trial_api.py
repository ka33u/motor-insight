import json
from copy import deepcopy
from unittest.mock import patch
from django.contrib.auth.models import User,Group
from app.models import Record,AuditEvent,AccountAccessState
from app.ingestion import fingerprint
from app import wip_trial_replay,wip_trial_contract as contract
from .test_platform import PlatformCase
from .test_wip_trial import fixture,running,seal


class WipTrialAPITests(PlatformCase):
    def setUp(self):
        super().setUp();self.args=running(fixture());study,tables,joint,refs=self.args
        from app.wip_trial import parent_tables
        for ds,rows in {**parent_tables(joint),**tables,'wip_trial_studies':[study]}.items():
            for r in rows:self.record(ds,r)
        for ds,rows in refs.items():
            for r in rows.values():
                if not Record.objects.filter(dataset=ds,business_key=r['id']).exists():self.record(ds,r)
        self.client.force_login(self.admin);self.clock=patch('app.analytics.AS_OF',study['cutoff']);self.clock.start();self.addCleanup(self.clock.stop)
    def board(self,**kw):return self.client.get('/api/wip-trial/WR1',kw)
    def export(self,d=None,fmt='json',**kw):return self.client.get('/api/wip-trial/WR1/export',dict(receipt=(d or self.board().json())['receipt'],format=fmt,**kw))
    def change(self,ds,key,**fields):
        r=Record.objects.get(dataset=ds,business_key=key);r.values.update(fields);r.record_hash=fingerprint(r.values);r.revision+=1;r.save();row=r.source_row;row.normalized=r.values;row.record_hash=r.record_hash;row.save()
    def test_normal_board_and_json_replay(self):
        b=self.board();self.assertEqual(b.status_code,200,b.content);self.assertEqual(b.json()['state'],'trial',b.json()['issues'])
        r=self.export();self.assertEqual(r.status_code,200,r.content);d=r.json();self.assertEqual(wip_trial_replay.replay(d),d['result']);self.assertEqual(r['Cache-Control'],'no-store')
        self.assertNotIn('receipt',d);self.assertEqual(AuditEvent.objects.get(action='wip_trial.export').detail['business_facts_changed'],False)
    def test_roles_raw_data_and_method(self):
        self.client.logout();self.assertEqual(self.board().status_code,401)
        for role in ('admin','analyst','operations','quality','finance','viewer'):
            user=User.objects.filter(username=role).first() or User.objects.create_user(role);user.groups.add(Group.objects.get_or_create(name=role)[0]);self.client.force_login(user)
            expected=200 if role in ('admin','analyst','operations') else 403
            self.assertEqual(self.board().status_code,expected);self.assertEqual(self.client.get('/api/wip-trial').status_code,expected)
            for ds in self.args[1]|{'wip_trial_studies':[]} :self.assertEqual(self.client.get('/api/records/'+ds).status_code,expected)
        self.client.force_login(self.admin);self.assertEqual(self.client.post('/api/wip-trial/WR1').status_code,405)
    def test_strict_query_and_page(self):
        for query in ('?policy=bad','?policy=due&policy=priority','?q=x','?page=1'):self.assertEqual(self.client.get('/api/wip-trial/WR1'+query).status_code,400)
        self.assertEqual(self.client.get('/api/wip-trial/WR1/export').status_code,400);receipt=self.board().json()['receipt']
        for page in ('0','1.5','１００','-1'):self.assertEqual(self.client.get('/api/wip-trial/WR1/sources',dict(receipt=receipt,page=page)).status_code,400)
        self.assertEqual(self.export(fmt='html').status_code,400)
    def test_receipts_bind_policy_account_epoch_and_expiry(self):
        d=self.board().json();self.assertEqual(self.export(d,policy='priority').status_code,409)
        AccountAccessState.objects.create(user=self.admin,revision=2);self.assertEqual(self.export(d).status_code,409)
        with patch('django.core.signing.time.time',return_value=0):old=self.board().json()
        self.assertEqual(self.export(old).status_code,409)
        d=self.board().json();u=User.objects.create_user('other');u.groups.add(Group.objects.get_or_create(name='analyst')[0]);self.client.force_login(u);self.assertEqual(self.export(d).status_code,409)
    def test_changed_operation_pauses_and_revokes_old_export(self):
        d=self.board().json();self.change('operations','OP1',good_qty=0);self.assertEqual(self.export(d).status_code,409)
        b=self.board().json();self.assertEqual(b['state'],'paused');self.assertIsNone(b['summary']);self.assertEqual(b['tasks'],[])
        doc=self.export(b).json();self.assertEqual(wip_trial_replay.replay(doc),doc['result'])
    def test_source_metadata_and_rules_revoke(self):
        d=self.board().json();self.batch.filename='renamed.xlsx';self.batch.save();self.assertEqual(self.export(d).status_code,409)
        d=self.board().json()
        with patch('app.wip_trial.rule_hash',return_value='changed'):self.assertEqual(self.export(d).status_code,409)
    def test_complete_source_pages_and_detail(self):
        d=self.board().json();sources=[];page=1
        while True:
            r=self.client.get('/api/wip-trial/WR1/sources',dict(receipt=d['receipt'],page=page)).json();sources+=r['rows']
            if len(sources)>=r['total']:break
            page+=1
        self.assertEqual(len(sources),d['source_count']);self.assertTrue(all(s['filename']=='unit-test.xlsx' and s['row']==2 for s in sources))
        r=self.client.get('/api/wip-trial/WR1/tasks/TA',dict(receipt=d['receipt']));self.assertEqual(r.status_code,200,r.content);self.assertEqual(r.json()['operation']['id'],'OP1');self.assertEqual(r.json()['row']['remaining_qty'],1)
        self.assertEqual(self.client.get('/api/wip-trial/WR1/tasks/bad',dict(receipt=d['receipt'])).status_code,404)
    def test_exports_do_not_leak_prices_names_or_pay(self):
        self.change('employees','E1',name='SECRET PERSON',hourly_cents=889977);self.change('materials','M1',unit_cost_cents=554499)
        d=self.export().content.decode()
        for forbidden in ('SECRET PERSON','hourly_cents','unit_cost_cents','889977','554499'):self.assertNotIn(forbidden,d)
        self.assertEqual(wip_trial_replay.replay(json.loads(d)),json.loads(d)['result'])
    def test_csv_retains_every_input_and_formula_safety(self):
        d=self.board().json();r=self.export(d,'csv');self.assertEqual(r.status_code,200);s=r.content.decode('utf-8-sig')
        for word in ('wip_trial_tasks','wip_trial_materials','schedule_tasks','operations','来源','OP1','WR1'):self.assertIn(word,s)
    def test_versions_not_fallback_and_duplicate_version_pauses(self):
        study,tables,joint,refs=deepcopy(self.args);study.update(id='WR2',version=2,supersedes_id='WR1',name='new invalid')
        for rows in tables.values():
            for r in rows:r['id']='NEW-'+r['id'];r['study_id']='WR2'
        refs['wip_trial_studies']={'WR1':self.args[0]};seal(study,tables,joint,refs);study['reference_hash']='0'*64;study['content_hash']=contract.bundle_hash(study,tables)
        self.record('wip_trial_studies',study)
        for ds,rows in tables.items():
            for r in rows:self.record(ds,r)
        rows=self.client.get('/api/wip-trial').json()['rows'];self.assertEqual(rows[0]['id'],'WR2');self.assertTrue(rows[0]['is_latest']);self.assertFalse(rows[1]['is_latest'])
        self.assertEqual(self.client.get('/api/wip-trial/WR2').json()['state'],'paused');self.assertEqual(self.board().json()['state'],'trial')
        dupe=dict(self.args[0],id='WR-DUPLICATE');self.record('wip_trial_studies',dupe);self.assertEqual(self.board().json()['state'],'paused')
    def test_task_evidence_export_roundtrip_and_byte_audit(self):
        import hashlib
        receipt=self.board().json()['receipt']
        detail=self.client.get('/api/wip-trial/WR1/tasks/TA',dict(receipt=receipt)).json()
        for fmt in ('json','csv'):
            r=self.client.get('/api/wip-trial/WR1/tasks/TA/export',dict(receipt=receipt,format=fmt));self.assertEqual(r.status_code,200,r.content)
            if fmt=='json':
                d=r.json();self.assertEqual(d['decision'],detail['decision']);self.assertEqual(wip_trial_replay.replay_decision(d),d['decision']);self.assertEqual(wip_trial_replay.replay(d),d['result'])
            else:self.assertIn('任务派序解释',r.content.decode('utf-8-sig'))
            audit=AuditEvent.objects.latest('id');self.assertEqual(audit.detail['task_id'],'TA');self.assertEqual(audit.detail['file_sha256'],hashlib.sha256(r.content).hexdigest());self.assertFalse(audit.detail['business_facts_changed'])
    def test_decision_definition_change_revokes_receipt(self):
        receipt=self.board().json()['receipt']
        with patch('app.wip_trial_decision.definition_hash',return_value='new'):
            for suffix in ('/tasks/TA','/tasks/TA/export','/export'):
                self.assertEqual(self.client.get('/api/wip-trial/WR1'+suffix,dict(receipt=receipt)).status_code,409)
    def test_task_exports_enforce_roles_missing_and_strict_parameters(self):
        receipt=self.board().json()['receipt'];path='/api/wip-trial/WR1/tasks/TA/export'
        for q in ({},{'receipt':receipt,'format':'html'},{'receipt':receipt,'extra':'x'}):self.assertEqual(self.client.get(path,q).status_code,400)
        self.assertEqual(self.client.get('/api/wip-trial/WR1/tasks/unknown/export',dict(receipt=receipt)).status_code,404)
        for role in ('quality','finance','viewer'):
            u=User.objects.filter(username=role).first() or User.objects.create_user(role);u.groups.add(Group.objects.get_or_create(name=role)[0]);self.client.force_login(u)
            self.assertEqual(self.client.get(path,dict(receipt=receipt)).status_code,403)
    def test_task_export_does_not_leak_personnel_or_prices(self):
        self.change('employees','E1',name='SECRET PERSON',hourly_cents=889977);self.change('materials','M1',unit_cost_cents=554499)
        receipt=self.board().json()['receipt'];r=self.client.get('/api/wip-trial/WR1/tasks/TA/export',dict(receipt=receipt))
        for forbidden in ('SECRET PERSON','hourly_cents','unit_cost_cents','889977','554499','joint_context'):self.assertNotIn(forbidden,r.content.decode())
    def selected(self,board=None,fmt='json',**scope):
        return self.client.get('/api/wip-trial/WR1/selection/export',dict(receipt=(board or self.board().json())['receipt'],format=fmt,**scope))
    def test_selection_capabilities_are_explicit(self):
        self.assertEqual(self.board().json()['capabilities'],dict(task_decision='WIP_DISPATCH_EVIDENCE_1',task_selection='WIP_TASK_SELECTION_1'))
    def test_selection_export_exact_ids_preserves_original_result_and_replays(self):
        b=self.board().json();r=self.selected(b,state='carried');self.assertEqual(r.status_code,200,r.content);d=r.json();s=d['selection']
        self.assertEqual(s['task_ids'],['TA']);self.assertEqual(s['selected_count'],1);self.assertEqual(s['whole_task_count'],4)
        self.assertEqual(s['state_counts'],dict(completed=0,carried=1,scheduled=0,blocked=0));self.assertEqual(s['filters'],dict(job='',state='carried',root=''))
        self.assertEqual(d['result']['tasks'],b['tasks']);self.assertEqual(len(d['result']['tasks']),4);self.assertEqual(wip_trial_replay.replay_selection(d),s)
        self.assertEqual(s['whole_job_results'],b['jobs']);self.assertEqual(len(s['work_orders']),1);self.assertEqual(r['Cache-Control'],'no-store')
    def test_selection_empty_intersection_is_empty_not_whole_plan_zero(self):
        d=self.selected(state='completed').json();s=d['selection'];self.assertEqual(s['selected_count'],0);self.assertEqual(s['selected_tasks'],[])
        self.assertEqual(s['whole_task_count'],4);self.assertTrue(d['result']['tasks']);self.assertFalse(s['whole_job_results']);self.assertFalse(s['work_orders'])
        self.assertEqual(wip_trial_replay.replay_selection(d),s)
    def test_selection_root_intersects_state_and_original_descendants(self):
        self.change('wip_trial_supplies','S-L2',qty=0)
        # Reseal the synthetic fixture through the test record service. Actual
        # business data still enters only through normal Excel imports.
        from app.wip_trial_contract import bundle_hash
        study=Record.objects.get(dataset='wip_trial_studies',business_key='WR1').values
        tables={ds:list(Record.objects.filter(dataset=ds,values__study_id='WR1').values_list('values',flat=True)) for ds in self.args[1]}
        self.change('wip_trial_studies','WR1',content_hash=bundle_hash(study,tables))
        b=self.board().json();self.assertEqual(b['state'],'trial',b['issues']);root=next(t['id'] for t in b['tasks'] if t['root_tasks']==[t['id']])
        d=self.selected(b,job='J1',root=root,state='blocked').json();expected=[t['id'] for t in b['tasks'] if root in t['root_tasks']]
        self.assertEqual(d['selection']['task_ids'],expected);self.assertEqual(wip_trial_replay.replay_selection(d),d['selection'])
        self.assertEqual(self.selected(b,root=root,state='carried').json()['selection']['selected_count'],0)
    def test_selection_invalid_paused_and_repeated_filters_rejected(self):
        b=self.board().json()
        for scope in ({'job':'UNKNOWN'},{'root':'UNKNOWN'},{'root':'TA'},{'state':'late'},{'job':'x'*201},{'format':'xlsx'},{'extra':'x'}):
            q=dict(receipt=b['receipt'],format='json');q.update(scope)
            self.assertEqual(self.client.get('/api/wip-trial/WR1/selection/export',q).status_code,400,scope)
        self.assertEqual(self.client.get('/api/wip-trial/WR1/selection/export',dict(receipt=b['receipt'],state=['carried','blocked'])).status_code,400)
        self.assertEqual(self.client.get('/api/wip-trial/WR1/selection/export').status_code,400)
        self.change('operations','OP1',good_qty=0);paused=self.board().json();self.assertEqual(paused['state'],'paused');self.assertEqual(self.selected(paused).status_code,400)
    def test_selection_definition_source_and_policy_changes_revoke(self):
        b=self.board().json()
        with patch('app.wip_trial_selection.definition_hash',return_value='changed'):self.assertEqual(self.selected(b).status_code,409)
        self.assertEqual(self.selected(b,policy='priority').status_code,409)
        self.batch.filename='new-source.xlsx';self.batch.save();self.assertEqual(self.selected(b).status_code,409)
    def test_selection_roles_accounts_and_methods(self):
        path='/api/wip-trial/WR1/selection/export';b=self.board().json()
        self.assertEqual(self.client.post(path).status_code,405)
        for role in ('admin','analyst','operations','quality','finance','viewer'):
            u=User.objects.create_user('selection-'+role);u.groups.add(Group.objects.get_or_create(name=role)[0]);self.client.force_login(u)
            if role in ('admin','analyst','operations'):
                receipt=self.board().json()['receipt'];self.assertEqual(self.client.get(path,dict(receipt=receipt)).status_code,200)
                self.assertEqual(self.client.get(path,dict(receipt=b['receipt'])).status_code,409)
            else:self.assertEqual(self.client.get(path,dict(receipt=b['receipt'])).status_code,403)
        self.client.logout();self.assertEqual(self.client.get(path,dict(receipt=b['receipt'])).status_code,401)
    def test_selection_csv_one_row_per_selected_task_audits_file_bytes(self):
        import csv,hashlib,io
        b=self.board().json();r=self.selected(b,'csv',state='carried');self.assertEqual(r.status_code,200,r.content)
        rows=list(csv.reader(io.StringIO(r.content.decode('utf-8-sig'))));i=rows.index(['筛选任务 · 一行一原任务']);header=rows[i+1];values=[]
        for line in rows[i+2:]:
            if not line:break
            values.append(dict(zip(header,line)))
        self.assertEqual([row['id'] for row in values],['TA']);self.assertEqual(values[0]['state'],'carried')
        self.assertIn(['完整方案任务数','4'],rows);self.assertIn(['完整方案来源 · 保留共享竞争依据'],rows)
        audit=AuditEvent.objects.latest('id');self.assertEqual(audit.action,'wip_trial.selection_export');self.assertEqual(audit.detail['file_sha256'],hashlib.sha256(r.content).hexdigest());self.assertEqual(audit.detail['task_count'],1)
        self.assertFalse(audit.detail['business_facts_changed']);self.assertEqual(audit.detail['filters'],dict(job='',state='carried',root=''))
    def test_selection_exports_do_not_include_pay_prices_or_people_names(self):
        self.change('employees','E1',name='SECRET PERSON',hourly_cents=889977);self.change('materials','M1',unit_cost_cents=554499)
        for fmt in ('csv','json'):
            r=self.selected(fmt=fmt);self.assertEqual(r.status_code,200,r.content)
            for text in ('SECRET PERSON','hourly_cents','unit_cost_cents','889977','554499','joint_context'):self.assertNotIn(text,r.content.decode())
    def test_selection_definition_changed_during_export_rolls_back_audit(self):
        b=self.board().json();from app import wip_trial_selection
        original=wip_trial_selection.select;before=AuditEvent.objects.count()
        def change(*args):
            chosen=original(*args)
            AccountAccessState.objects.create(user=self.admin,revision=4)
            return chosen
        with patch('app.wip_trial_selection.select',side_effect=change):self.assertEqual(self.selected(b).status_code,409)
        self.assertEqual(AuditEvent.objects.count(),before);self.assertFalse(AccountAccessState.objects.filter(user=self.admin).exists())
    def test_selection_replay_rejects_tampered_scope_rows_or_definition(self):
        original=self.selected(state='carried').json()
        for change in (
            lambda d:d['selection'].update(version='FUTURE'),
            lambda d:d['selection']['filters'].update(state=''),
            lambda d:d['selection'].update(task_ids=[]),
            lambda d:d['selection']['selected_tasks'][0].update(remaining_qty=999),
            lambda d:d['result']['tasks'][0].update(remaining_qty=999),
        ):
            doc=deepcopy(original);change(doc)
            with self.assertRaises(ValueError):wip_trial_replay.replay_selection(doc)
    def test_selection_pure_helper_does_not_mutate_and_rejects_bad_mapping(self):
        from app import wip_trial_selection as selection
        d=self.export().json();result=d['result'];links=d['inputs']['wip_trial_jobs'];before=deepcopy((result,links))
        selection.select(result,links,dict(state='carried'));self.assertEqual((result,links),before)
        for bad in ([],links+links):
            with self.assertRaises(ValueError):selection.select(result,bad,{})
        for filters in ({'job':None},{'state':False},{'root':42},{'state':'future'},{'extra':''}):
            with self.assertRaises(ValueError):selection.normalize(filters)
