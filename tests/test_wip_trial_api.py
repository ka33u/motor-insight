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
