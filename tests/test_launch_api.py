import csv
import io
from unittest.mock import patch
from django.contrib.auth.models import User, Group
from django.db import IntegrityError
from app.models import Record, AuditEvent, AccountAccessState
from app.ingestion import fingerprint
from app.launch_contract import bundle_hash
from .test_platform import PlatformCase
from .test_launch import fixture


class LaunchAPITests(PlatformCase):
    def setUp(self):
        super().setUp()
        s,t,p,refs,_=fixture();joint=p['parent'];crew=joint['parent'];base=crew['base']
        rows={}
        for ds,row in [('launch_studies',s),('order_baselines',p['result']['study']),('joint_studies',joint['result']['study']),('crew_studies',crew['result']['study']),('schedule_studies',base['study'])]:rows[ds,row['id']]=row
        for ds,items in {**t,**p['tables'],**joint['tables'],**crew['tables'],**base['tables']}.items():
            for row in items:rows[ds,row['id']]=row
        for ds,items in refs.items():
            for row in items.values():rows[ds,row['id']]=row
        for (ds,_),row in rows.items():self.record(ds,row)
        self.client.force_login(self.admin)

    def board(self):return self.client.get('/api/launch-review/LR1')
    def export(self,d=None,fmt='json',**kwargs):return self.client.get('/api/launch-review/LR1/export',dict(receipt=(d or self.board().json())['receipt'],format=fmt,**kwargs))
    def change(self,ds,key,**fields):
        r=Record.objects.get(dataset=ds,business_key=key);r.values.update(fields);r.record_hash=fingerprint(r.values);r.revision+=1;r.save()
        source=r.source_row;source.normalized=r.values;source.record_hash=r.record_hash;source.save()

    def test_roles_raw_catalog_and_read_only(self):
        counts=(Record.objects.count(),AuditEvent.objects.count())
        self.client.logout();self.assertEqual(self.board().status_code,401)
        for role in ('admin','analyst','operations','quality','finance','viewer'):
            user=User.objects.filter(username=role).first() or User.objects.create_user(role)
            user.groups.add(Group.objects.get_or_create(name=role)[0]);self.client.force_login(user)
            expected=200 if role in ('admin','analyst','operations') else 403
            for path in ('/api/launch-review','/api/launch-review/LR1','/api/records/launch_documents','/api/records/launch_documents/export','/api/bi-field-catalog?dataset=launch_documents'):
                self.assertEqual(self.client.get(path).status_code,expected,path)
        self.assertEqual((counts[0],counts[1]+3),(Record.objects.count(),AuditEvent.objects.count()))

    def test_board_detail_sources_and_full_export(self):
        d=self.board().json();self.assertEqual(d['summary']['satisfied'],4)
        q=dict(receipt=d['receipt'])
        task=self.client.get('/api/launch-review/LR1/tasks/TA',q).json();self.assertEqual(task['row']['id'],'TA');self.assertTrue(task['can_download_original'])
        sources=self.client.get('/api/launch-review/LR1/sources',q).json();self.assertEqual(sources['total'],d['source_count'])
        self.assertTrue(all('source_row_id' in r for r in sources['rows']))
        r=self.export(d);doc=r.json();self.assertEqual(r['Cache-Control'],'no-store')
        self.assertEqual(len(doc['trial']['resource_inputs']['schedule_tasks']),4)
        self.assertEqual(len(doc['launch_inputs']['launch_requirements']),9)
        self.assertNotIn('receipt',doc);self.assertNotIn('cents',r.content.decode());self.assertEqual(doc['order_baseline']['result']['summary']['uncovered_qty'],8)
        self.assertEqual(AuditEvent.objects.latest('id').action,'launch.export')

    def test_current_tool_or_parent_change_invalidates_old_reading(self):
        for ds,key,fields in [('tools','TOOL1',{'uses':100}),('bom','B1',{'qty':999})]:
            before=self.board().json();self.change(ds,key,**fields);self.assertEqual(self.export(before).status_code,409)
        d=self.board().json();self.assertEqual(d['basis_state'],'review');self.assertEqual(d['summary']['satisfied'],0)

    def test_added_or_modified_evidence_requires_new_digest(self):
        before=self.board().json()
        self.change('launch_documents','DOCA',status='作废')
        self.assertEqual(self.export(before).status_code,409)
        d=self.board().json();self.assertEqual(d['state'],'paused');self.assertIsNone(d['summary'])
        self.assertEqual(len(self.export(d).json()['launch_inputs']['launch_documents']),3)

    def test_receipt_expiry_account_epoch_policy_and_rule(self):
        with patch('django.core.signing.time.time',return_value=0):old=self.board().json()
        self.assertEqual(self.export(old).status_code,409)
        d=self.board().json();self.assertEqual(self.export(d,policy='priority').status_code,409)
        AccountAccessState.objects.create(user=self.admin,revision=2)
        self.assertEqual(self.export(d).status_code,409)
        d=self.board().json()
        with patch('app.launch.rule_hash',return_value='changed'):self.assertEqual(self.export(d).status_code,409)

    def test_strict_queries_methods_and_foreign_detail(self):
        self.assertEqual(self.client.post('/api/launch-review/LR1').status_code,405)
        for query in ('?policy=bad','?policy=due&policy=priority','?filter=unknown'):
            self.assertEqual(self.client.get('/api/launch-review/LR1'+query).status_code,400)
        q=dict(receipt=self.board().json()['receipt'])
        self.assertEqual(self.client.get('/api/launch-review/LR1/tasks/OTHER',q).status_code,404)
        for page in ('0','-1','2.2','１００'):
            self.assertEqual(self.client.get('/api/launch-review/LR1/sources',dict(q,page=page)).status_code,400)
        self.assertEqual(self.client.get('/api/launch-review/LR1/export').status_code,400)

    def test_csv_formula_safety_and_atomic_export_failure(self):
        self.change('launch_studies','LR1',name='=2+2')
        response=self.export(fmt='csv');rows=list(csv.reader(io.StringIO(response.content.decode('utf-8-sig'))))
        self.assertIn("'=2+2",rows[0])
        count=AuditEvent.objects.count()
        with patch('app.launch_views.AuditEvent.objects.create',side_effect=IntegrityError):self.assertEqual(self.export().status_code,409)
        self.assertEqual(AuditEvent.objects.count(),count)

    def test_corrupt_provenance_is_rejected(self):
        source=Record.objects.get(dataset='tools',business_key='TOOL1').source_row;source.row_number=99;source.normalized={'id':'OTHER'};source.save()
        self.assertEqual(self.board().status_code,400)
