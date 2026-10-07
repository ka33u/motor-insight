"""Recovery safety with small fixtures; actual runtime recovery is verified separately."""
from contextlib import closing
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import sqlite3
import stat
import tempfile
import unittest
from unittest.mock import patch
import uuid
import warnings
import zipfile

ROOT=Path(__file__).resolve().parents[1]
def module(name):
    spec=importlib.util.spec_from_file_location(name,ROOT/'scripts'/(name+'.py'))
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
r=module('recovery');serve=module('serve')

class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.base=Path(self.temp.name).resolve();self.root=self.base/'original';self.root.mkdir()
        for name in r.REQUIRED-{'data/platform.sqlite3'}:
            p=self.root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text('fixture')
        self.key=uuid.uuid4().hex;self.device=uuid.uuid4().hex
        self.original='data/imports/'+str(uuid.UUID(self.key))+'.xlsx'
        self.device_name='data/device_files/'+str(uuid.UUID(self.device))+'.bin'
        for name,raw in [(self.original,b'original workbook'),(self.device_name,b'original detector')]:
            p=self.root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(raw)
        db=self.root/'data/platform.sqlite3'
        with closing(sqlite3.connect(db)) as con:
            con.executescript('CREATE TABLE app_importbatch (id TEXT PRIMARY KEY,file_path TEXT,file_hash TEXT,status TEXT); CREATE TABLE app_devicefile (id TEXT PRIMARY KEY,file_hash TEXT,size INTEGER); CREATE TABLE app_record (id INTEGER PRIMARY KEY,business_key TEXT,amount INTEGER); CREATE TABLE app_auditevent (id INTEGER PRIMARY KEY,detail TEXT);')
            con.execute('INSERT INTO app_importbatch VALUES (?,?,?,?)',(self.key,str(self.root/self.original),r.sha_file(self.root/self.original),'committed'))
            con.execute('INSERT INTO app_devicefile VALUES (?,?,?)',(self.device,r.sha_file(self.root/self.device_name),(self.root/self.device_name).stat().st_size))
            con.execute('INSERT INTO app_record VALUES (1,?,?)',('MO2609-000233',123450))
            con.execute('INSERT INTO app_auditevent VALUES (1,?)',(str(self.root/self.original),));con.commit()
        wheelroot=self.root/'data/recovery-wheels';wheelroot.mkdir();lock=[]
        for name in sorted(r.EXPECTED_PACKAGES):
            wheel=wheelroot/(name.replace('-','_')+'-1.0-py3-none-any.whl')
            with zipfile.ZipFile(wheel,'w') as z:z.writestr(name+'.dist-info/METADATA',f'Name: {name}\nVersion: 1.0\n')
            lock.append(f'{name}==1.0 --hash=sha256:{r.sha_file(wheel)}')
        (self.root/'requirements.lock').write_text('\n'.join(lock))
        self.archive=self.base/'bundle.zip';self.report=r.pack(self.root,self.archive)
    def tearDown(self):self.temp.cleanup()
    def rewrite(self,change):
        with zipfile.ZipFile(self.archive) as z:entries=[(i,z.read(i)) for i in z.infolist()]
        change(entries)
        altered=self.base/'altered.zip'
        with warnings.catch_warnings():
            warnings.simplefilter('ignore',UserWarning)
            with zipfile.ZipFile(altered,'w') as z:
                for i,raw in entries:z.writestr(i,raw)
        return altered,r.sha_file(altered)
    def reject(self,change,message=None):
        archive,digest=self.rewrite(change)
        with self.assertRaises(r.RecoveryError) as caught:r.verify(archive,digest)
        if message:self.assertIn(message,str(caught.exception))
    def fixture_collector(self):
        rows=[]
        for name in sorted(r.COLLECTOR_FIXTURES-{'data/device_inbox/fixture_manifest.json'}):
            p=self.root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(b'synthetic local protocol')
            rows.append(dict(path=name.removeprefix('data/device_inbox/'),sha256=r.sha_file(p),size=p.stat().st_size))
        manifest=self.root/'data/device_inbox/fixture_manifest.json';manifest.write_text(json.dumps(dict(synthetic=True,business_facts_changed=False,files=rows)))
        return manifest,rows
    def test_collector_fixture_pack_and_verify_only_explicit_examples(self):
        self.fixture_collector();(self.root/'data/device_inbox/not_in_bundle.txt').write_text('unlisted')
        archive=self.base/'collector.zip';r.pack(self.root,archive);self.assertTrue(r.verify(archive)['verified'])
        with zipfile.ZipFile(archive) as z:self.assertEqual({n for n in z.namelist() if n.startswith('data/device_inbox/')},r.COLLECTOR_FIXTURES)
    def test_collector_fixture_missing_or_damaged_rejected(self):
        _,rows=self.fixture_collector();(self.root/'data/device_inbox'/rows[0]['path']).write_bytes(b'damaged')
        with self.assertRaisesRegex(r.RecoveryError,'fixture'):r.pack(self.root,self.base/'damaged.zip')
    def test_collector_fixture_extra_or_traversal_manifest_rejected(self):
        manifest,rows=self.fixture_collector();rows[0]['path']='../../secret';manifest.write_text(json.dumps(dict(synthetic=True,business_facts_changed=False,files=rows)))
        with self.assertRaisesRegex(r.RecoveryError,'fixture'):r.pack(self.root,self.base/'outside.zip')
    def test_collector_fixture_symlink_or_nonsynthetic_manifest_rejected(self):
        manifest,rows=self.fixture_collector();p=self.root/'data/device_inbox'/rows[0]['path'];outside=self.base/'outside';p.rename(outside);p.symlink_to(outside)
        with self.assertRaisesRegex(r.RecoveryError,'fixture'):r.pack(self.root,self.base/'linked.zip')
        manifest.write_text(json.dumps(dict(synthetic=False,business_facts_changed=False,files=rows)))
        with self.assertRaisesRegex(r.RecoveryError,'fixture'):r.pack(self.root,self.base/'real.zip')
    def test_complete_bundle_verifies_and_bootstrap_matches(self):
        x=r.verify(self.archive);self.assertTrue(x['verified']);self.assertEqual(x['original_references'],2)
        self.assertEqual(Path(self.report['bootstrap']).read_bytes(),(self.root/'scripts/recovery.py').read_bytes())
    def test_outer_digest_required_and_tamper_rejected(self):
        with self.assertRaises(r.RecoveryError):r.verify(self.archive,'0'*64)
        Path(str(self.archive)+'.sha256').unlink()
        with self.assertRaises(r.RecoveryError):r.verify(self.archive)
    def test_file_payload_tamper_rejected_even_with_updated_outer_hash(self):
        def edit(a):
            i=next(i for i,x in enumerate(a) if x[0].filename=='static/app.js');a[i]=(a[i][0],b'tampered')
        self.reject(edit,'size')
    def test_traversal_and_absolute_and_drive_names_rejected(self):
        for name in ['../outside','/tmp/outside','C:/outside','app/../../outside','app//x','app/./x','app\\evil']:
            with self.subTest(name=name):self.reject(lambda a:a.append((zipfile.ZipInfo(name),b'bad')))
        self.assertFalse((self.base/'outside').exists())
    def test_duplicate_and_case_collisions_rejected(self):
        self.reject(lambda a:a.append(next(e for e in a if e[0].filename=='static/app.js')),'Duplicate')
        self.reject(lambda a:a.append((zipfile.ZipInfo('STATIC/app.js'),b'bad')))
    def test_symlink_rejected(self):
        def edit(a):
            i=next(i for i,x in enumerate(a) if x[0].filename=='static/app.js');info=a[i][0];info.external_attr=(stat.S_IFLNK|0o777)<<16
        self.reject(edit,'regular')
    def test_environment_and_pid_and_venv_are_not_restore_members(self):
        for name in ['.env','.venv/bin/python','data/server.pid','.restore-in-progress']:
            with self.subTest(name=name):self.reject(lambda a:a.append((zipfile.ZipInfo(name),b'bad')))
    def test_extra_unmanifested_member_rejected(self):
        self.reject(lambda a:a.append((zipfile.ZipInfo('static/new.js'),b'bad')),'coverage')
    def test_missing_runtime_member_rejected(self):
        self.reject(lambda a:a.pop(next(i for i,x in enumerate(a) if x[0].filename=='manage.py')),'coverage')
    def test_invalid_manifest_type_rejected(self):
        def edit(a):
            i=next(i for i,x in enumerate(a) if x[0].filename=='manifest.json');a[i]=(a[i][0],b'[]')
        self.reject(edit,'format')
    def test_expansion_limit_rejected(self):
        with patch.object(r,'MAX_BYTES',1):
            with self.assertRaisesRegex(r.RecoveryError,'expansion'):r.verify(self.archive)
    def test_missing_original_rejected_before_target_exists(self):
        def edit(a):
            a.pop(next(i for i,x in enumerate(a) if x[0].filename==self.original))
            i=next(i for i,x in enumerate(a) if x[0].filename=='manifest.json');m=json.loads(a[i][1]);m['files']=[e for e in m['files'] if e['path']!=self.original];a[i]=(a[i][0],r.dump(m).encode())
        archive,digest=self.rewrite(edit);target=self.base/'new'
        with self.assertRaisesRegex(r.RecoveryError,'original'):r.restore(archive,target,digest)
        self.assertFalse(target.exists())
    def test_pack_rejects_modified_original(self):
        (self.root/self.original).write_bytes(b'changed')
        with self.assertRaisesRegex(r.RecoveryError,'original'):r.pack(self.root,self.base/'new.zip')
    def test_pack_rejects_external_original_path(self):
        with closing(sqlite3.connect(self.root/'data/platform.sqlite3')) as con:
            con.execute('UPDATE app_importbatch SET file_path=?',('/another/root.xlsx',));con.commit()
        with self.assertRaisesRegex(r.RecoveryError,'path'):r.pack(self.root,self.base/'new.zip')
    def test_pack_rejects_missing_or_changed_wheel(self):
        wheel=next((self.root/'data/recovery-wheels').glob('*.whl'));wheel.unlink()
        with self.assertRaisesRegex(r.RecoveryError,'wheels'):r.pack(self.root,self.base/'new.zip')
    def test_pack_never_overwrites_existing_bundle(self):
        before=self.archive.read_bytes()
        with self.assertRaisesRegex(r.RecoveryError,'exists'):r.pack(self.root,self.archive)
        self.assertEqual(before,self.archive.read_bytes())
    def test_existing_target_is_never_modified(self):
        target=self.base/'existing';target.mkdir();(target/'keep').write_text('user work')
        with self.assertRaisesRegex(r.RecoveryError,'exists'):r.restore(self.archive,target)
        self.assertEqual((target/'keep').read_text(),'user work')
    def test_symlink_target_refused(self):
        target=self.base/'link';target.symlink_to(self.base/'missing')
        with self.assertRaisesRegex(r.RecoveryError,'exists'):r.restore(self.archive,target)
    def test_restore_only_changes_location_keeps_facts_and_historical_audit(self):
        before=r.sha_file(self.root/'data/platform.sqlite3');target=self.base/'恢复 副本'
        with patch.object(r,'install_runtime',return_value='test-python'):
            report=r.restore(self.archive,target)
        self.assertEqual(report['status'],'ready');self.assertFalse((target/'.restore-in-progress').exists())
        self.assertEqual(report['import_paths_rebased'],1);self.assertEqual(before,r.sha_file(self.root/'data/platform.sqlite3'))
        self.assertEqual(r.database_inventory(target/'data/platform.sqlite3'),r.database_inventory(self.root/'data/platform.sqlite3'))
        with closing(r.connect_readonly(target/'data/platform.sqlite3')) as con:
            self.assertEqual(con.execute('SELECT file_path FROM app_importbatch').fetchone()[0],str(target/self.original))
            self.assertEqual(con.execute('SELECT detail FROM app_auditevent').fetchone()[0],str(self.root/self.original))
        self.assertEqual(r.check_originals(target,target/'data/platform.sqlite3',target),2)
    def test_runtime_failure_is_isolated_and_never_marked_ready(self):
        target=self.base/'failed';before=r.sha_file(self.root/'data/platform.sqlite3')
        with patch.object(r,'install_runtime',side_effect=r.RecoveryError('deliberate install failure')):
            with self.assertRaisesRegex(r.RecoveryError,'deliberate'):r.restore(self.archive,target)
        self.assertEqual(json.loads((target/'.restore-in-progress').read_text())['status'],'failed')
        self.assertFalse((target/'data/recovery-restore.json').exists());self.assertEqual(before,r.sha_file(self.root/'data/platform.sqlite3'))
    def test_runtime_mismatch_stops_before_target_reservation(self):
        target=self.base/'wrong-python'
        with patch.object(r,'runtime_check',side_effect=r.RecoveryError('wrong Python')):
            with self.assertRaises(r.RecoveryError):r.restore(self.archive,target)
        self.assertFalse(target.exists())
    def test_environment_does_not_inherit_host_python_or_database(self):
        with patch.dict(os.environ,{'PYTHONPATH':'/outside','VIRTUAL_ENV':'/outside','MOTOR_SQLITE_PATH':'/live.sqlite3','PIP_INDEX_URL':'https://example.invalid'}):
            env=r.clean_environment()
        for key in ['PYTHONPATH','VIRTUAL_ENV','MOTOR_SQLITE_PATH','PIP_INDEX_URL']:self.assertNotIn(key,env)
        self.assertEqual(env['PYTHONNOUSERSITE'],'1')
    def test_install_uses_offline_hashed_dependencies_and_new_location(self):
        calls=[]
        with patch.object(r,'run_checked',side_effect=lambda args,*a,**k:calls.append(args) or ''):
            r.install_runtime(self.root)
        pip=calls[1]
        for flag in ['--no-index','--no-deps','--require-hashes','--no-cache-dir']:self.assertIn(flag,pip)
        self.assertIn(str(self.root/'.venv'),calls[0]);self.assertEqual(pip[0],str(self.root/'.venv/bin/python'))

class PreviewOwnershipTests(unittest.TestCase):
    def test_ownership_requires_exact_root_and_port(self):
        root=Path('/tmp/电机 演示')
        with patch.object(serve,'ROOT',root):
            for text,ok in [(f'python {root}/manage.py runserver 127.0.0.1:8766 --noreload',True),
                            (f'python {root}/manage.py runserver 127.0.0.1:87660 --noreload',False),
                            ('python /other/manage.py runserver 127.0.0.1:8766 --noreload',False)]:
                with patch.object(serve,'description',return_value=text):self.assertEqual(serve.owned(123,8766),ok)
    def test_failed_restore_cannot_be_started(self):
        with tempfile.TemporaryDirectory() as tmp,patch.object(serve,'ROOT',Path(tmp)):
            (Path(tmp)/'.restore-in-progress').write_text('failed')
            with self.assertRaisesRegex(RuntimeError,'incomplete'):serve.main(['start','--port','8766'])
    def test_occupied_other_application_is_not_claimed(self):
        with tempfile.TemporaryDirectory() as tmp,patch.object(serve,'ROOT',Path(tmp)),patch.object(serve,'healthy',return_value=True):
            with self.assertRaisesRegex(RuntimeError,'another/unmanaged'):serve.main(['start','--port','8766'])
    def test_stop_refuses_an_unrelated_pid(self):
        with tempfile.TemporaryDirectory() as tmp,patch.object(serve,'ROOT',Path(tmp)):
            pid,_=serve.paths(8766);pid.parent.mkdir();pid.write_text('123')
            with patch.object(serve,'description',return_value='unrelated'),patch.object(serve.os,'kill') as kill:
                with self.assertRaisesRegex(RuntimeError,'another process'):serve.main(['stop','--port','8766'])
                kill.assert_not_called();self.assertTrue(pid.exists())

if __name__=='__main__':unittest.main()
