import json
from unittest.mock import patch
from django.contrib.auth.models import User,Group
from django.core.exceptions import PermissionDenied,ValidationError
from django.test import Client
from app import workbench as w,workbench_trials as t
from app.models import Record,WorkbenchEntry,PersonalWorkbench,AuditEvent
from app.import_review import ReviewConflict
from app.ingestion import fingerprint
from .test_platform import PlatformCase

class TrialFavoritesTests(PlatformCase):
    def setUp(self):
        super().setUp();self.users={'admin':self.admin,'quality':self.quality}
        for role in ('analyst','operations','finance','viewer'):
            u=User.objects.create_user('favorite_'+role);u.groups.add(Group.objects.get_or_create(name=role)[0]);self.users[role]=u
        self.rows={family:self.record(value[1],dict(id='000019',name='合成'+family,version='SIM-V1',owner_id='DO-NOT-COPY',assumptions='NO-RESULT')) for family,value in t.FAMILIES.items()}
        self.client.force_login(self.admin)
    def target(self,family='joint',mode='compare'):return f'{family}:{self.rows[family].pk}:{mode}'
    def add(self,family='joint',mode='compare',user=None):
        u=user or self.admin;return w.change(u,dict(action='add',revision=w.board(u)['revision'],kind='trial',target=self.target(family,mode),alias='早会方案',section='生产核查'))
    def lookup(self,family='joint',policy='due',view='compare',**changes):
        return dict(route=t.FAMILIES[family][0],study='000019',policy=policy,view=view,**changes)
    def update(self,family,**values):
        r=self.rows[family];r.values.update(values);r.record_hash=fingerprint(r.values);r.revision+=1;r.save()
        row=r.source_row;row.normalized=r.values;row.record_hash=r.record_hash;row.save();return r
    def test_all_eleven_destinations_preserve_study_and_modes(self):
        for family in t.FAMILIES:
            for mode in t.modes(family):
                row=t.resolve(self.admin,self.target(family,mode));self.assertEqual(row['params']['study'],'000019');self.assertEqual(row['route'],t.FAMILIES[family][0]);self.assertEqual(row['state'],'ready')
                if mode=='compare':self.assertEqual(row['params'],dict(study='000019',view='compare'))
                elif mode.startswith('trial-'):self.assertEqual(row['params'],dict(study='000019',view='trial',policy=mode[6:]))
                else:self.assertEqual(row['params']['policy'],mode)
        self.assertEqual(len(w.catalog(self.admin,dict(kind='trial',q='',page=1))['rows']),11)
    def test_six_roles_use_exact_destination_permission(self):
        for role,user in self.users.items():
            catalog=w.catalog(user,dict(kind='trial',q='',page=1));self.assertEqual(catalog['total'],11 if role in ('admin','analyst','operations') else 2)
            for family in t.FAMILIES:
                if family=='finite' or role in ('admin','analyst','operations'):t.resolve(user,self.target(family,'due'))
                else:
                    with self.assertRaises(PermissionDenied):t.resolve(user,self.target(family,'due'))
    def test_no_trial_calculations_or_business_writes_for_navigation(self):
        before=list(Record.objects.values());events=AuditEvent.objects.count()
        with patch('app.joint_schedule_data.load',side_effect=AssertionError('Do not calculate')),patch('app.finite_schedule_data.load',side_effect=AssertionError('Do not calculate')):
            w.catalog(self.admin,dict(kind='trial',q='',page=1));t.lookup(self.admin,self.lookup())
        self.assertEqual(list(Record.objects.values()),before);self.assertEqual(AuditEvent.objects.count(),events);self.assertFalse(PersonalWorkbench.objects.exists())
    def test_no_raw_assumptions_people_or_results_in_targets(self):
        value=json.dumps(t.resolve(self.admin,self.target()),ensure_ascii=False)
        for forbidden in ('DO-NOT-COPY','NO-RESULT','receipt','source_hash','reservations'):self.assertNotIn(forbidden,value)
        self.assertIn('未保存计算结果',value);self.assertIn('可打开不表示',value)
    def test_current_route_lookup_preserves_original_identifier_and_deduplicates_compare(self):
        a=t.lookup(self.admin,self.lookup());b=t.lookup(self.admin,self.lookup(policy='priority'));self.assertEqual(a,b)
        self.assertEqual(a['target'],self.target());self.assertEqual(a['params']['study'],'000019')
        self.rows['joint'].business_key='19';self.rows['joint'].save()
        with self.assertRaises(Record.DoesNotExist):t.lookup(self.admin,self.lookup())
    def test_lookup_strict_fields_and_supported_modes(self):
        cases=[self.lookup(receipt='SECRET'),{**self.lookup(),'view':'trial'},{**self.lookup(),'policy':'fast'},{**self.lookup(),'route':'https://other'},{**self.lookup(),'study':''},{**self.lookup(),'study':'bad\n'}]
        for data in cases:
            with self.assertRaises(ValidationError):t.lookup(self.admin,data)
        for family in ('finite','crew'):
            with self.assertRaises(ValidationError):t.lookup(self.admin,self.lookup(family))
    def test_target_parser_rejects_invalid_and_noncanonical_ids(self):
        for target in ('joint:01:due','joint:0:due','joint:-1:due','joint:1:trial-due','other:1:due','joint:1:compare:SECRET','joint:1:due\n','https://external',None):
            with self.assertRaises(ValidationError):w.target_key('trial',target)
    def test_dataset_and_record_id_must_both_match(self):
        with self.assertRaises(Record.DoesNotExist):t.resolve(self.admin,f"joint:{self.rows['finite'].pk}:due")
    def test_add_open_home_edit_and_remove_preserve_typed_target(self):
        d=self.add();row=d['rows'][0];self.assertEqual(row['target'],self.target())
        opened=w.open_entry(self.admin,dict(id=row['id'],revision=d['revision']));self.assertEqual(opened['params'],dict(study='000019',view='compare'))
        d=w.change(self.admin,dict(action='home',revision=d['revision'],id=row['id']));self.assertEqual(w.start(self.admin)['params'],opened['params'])
        d=w.change(self.admin,dict(action='edit',revision=d['revision'],id=row['id'],alias='每周复核',section='周会'));self.assertEqual(d['rows'][0]['alias'],'每周复核')
        w.change(self.admin,dict(action='remove',revision=d['revision'],id=row['id']));self.assertEqual(w.start(self.admin)['route'],'overview');self.assertEqual(Record.objects.count(),4)
    def test_duplicate_same_destination_and_stale_revision_rejected(self):
        self.add()
        with self.assertRaises(ReviewConflict):self.add()
        with self.assertRaises(ReviewConflict):w.change(self.admin,dict(action='add',revision=0,kind='trial',target=self.target('joint','due'),alias='',section=''))
        self.add('joint','due');self.add('joint','priority');self.assertEqual(WorkbenchEntry.objects.count(),3)
    def test_current_metadata_changes_are_visible_without_overwriting_alias(self):
        d=self.add();self.update('joint',name='正常导入后的新名称',version='SIM-V2');r=w.board(self.admin)['rows'][0]
        self.assertIn('新名称',r['label']);self.assertIn('SIM-V2',r['note']);self.assertEqual(r['version'],2);self.assertEqual(r['alias'],'早会方案');self.assertEqual(r['id'],d['rows'][0]['id'])
    def test_deleted_target_is_unavailable_and_home_falls_back(self):
        d=self.add();w.change(self.admin,dict(action='home',revision=d['revision'],id=d['rows'][0]['id']));self.rows['joint'].delete();r=w.board(self.admin)['rows'][0]
        self.assertEqual(r['state'],'unavailable');self.assertNotIn('合成joint',r['label']);self.assertIsNone(r['route']);self.assertEqual(w.start(self.admin)['route'],'workbench')
    def test_permission_revoked_hides_target_and_blocks_open(self):
        user=self.users['operations'];d=self.add(user=user);user.groups.set([Group.objects.get(name='viewer')]);r=w.board(user)['rows'][0];self.assertEqual(r['state'],'unavailable');self.assertNotIn('000019',r['label'])
        with self.assertRaises(ReviewConflict):w.open_entry(user,dict(id=r['id'],revision=d['revision']))
    def test_owner_isolation_including_admin(self):
        a=self.add();b=self.add(user=self.users['operations'])
        with self.assertRaises(WorkbenchEntry.DoesNotExist):w.open_entry(self.admin,dict(id=b['rows'][0]['id'],revision=a['revision']))
        self.assertEqual(len(w.board(self.users['viewer'])['rows']),0)
    def test_source_integrity_failure_does_not_show_available_shortcut(self):
        self.add();r=self.rows['joint'];r.values['name']='unverified';r.save();self.assertEqual(w.board(self.admin)['rows'][0]['state'],'unavailable')
    def test_catalog_pagination_covers_all_modes_and_lookup_does_not_depend_on_first_page(self):
        for i in range(12):self.record('joint_studies',dict(id=f'MP-{i:03}',name='共享供给',version='V1'))
        first=w.catalog(self.admin,dict(kind='trial',q='',page=1));rows=[]
        for page in range(1,4):rows+=w.catalog(self.admin,dict(kind='trial',q='',page=page))['rows']
        self.assertEqual(first['total'],47);self.assertEqual(len({r['target'] for r in rows}),47)
        target=t.lookup(self.admin,{**self.lookup(),'study':'MP-011'});found=w.catalog(self.admin,dict(kind='trial',q=target['target'],page=1));self.assertIn(target,found['rows'])
    def test_http_target_lookup_requires_login_csrf_post_and_body(self):
        self.client.logout();self.assertEqual(self.post('/api/workbench/trial-target',self.lookup()).status_code,401)
        self.client.force_login(self.admin);self.assertEqual(self.client.get('/api/workbench/trial-target').status_code,405)
        self.assertEqual(self.post('/api/workbench/trial-target?policy=due',self.lookup()).status_code,400)
        response=self.post('/api/workbench/trial-target',self.lookup());self.assertEqual(response.status_code,200);self.assertEqual(response['Cache-Control'],'no-store')
        c=Client(enforce_csrf_checks=True);c.force_login(self.admin);self.assertEqual(c.post('/api/workbench/trial-target',json.dumps(self.lookup()),content_type='application/json').status_code,403)
    def test_unauthorized_lookup_does_not_reveal_missing_or_existing_study(self):
        self.client.force_login(self.quality)
        for key in ('000019','MISSING'):
            response=self.post('/api/workbench/trial-target',{**self.lookup(),'study':key});self.assertEqual(response.status_code,403)
    def test_failed_audit_rolls_back_personal_config(self):
        with patch.object(AuditEvent.objects,'create',side_effect=RuntimeError('fail')):
            with self.assertRaises(RuntimeError):self.add()
        self.assertFalse(WorkbenchEntry.objects.exists());self.assertFalse(PersonalWorkbench.objects.exists())
    def test_reads_do_not_write_usage_history(self):
        d=self.add();before=list(AuditEvent.objects.values());w.board(self.admin);w.open_entry(self.admin,dict(id=d['rows'][0]['id'],revision=d['revision']));w.start(self.admin);self.assertEqual(list(AuditEvent.objects.values()),before)
