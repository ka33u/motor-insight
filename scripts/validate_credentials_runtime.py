"""Native HTTP rehearsal against a fresh SQLite copy, never the main account DB.

The subprocess is owned here and stopped in finally. New secrets stay in memory;
reports contain only outcome flags, account metadata and audit action counts.
"""
import hashlib
import argparse
import json
import os
from pathlib import Path
import secrets
import re
import socket
import sqlite3
import subprocess
import sys
import time
from collections import Counter

import recovery
from accept_restored_application import Client

ROOT = Path(__file__).resolve().parents[1]
MAIN_SHA = 'cc17088ff8da71770975a599da397faee8ae074f6efd85dc83a825f7ea0d4866'
PORT = 8877


def password():
    return 'Rehearsal-' + secrets.token_urlsafe(24) + '!'


def login(client, username, value):
    client.call('/', binary=True)
    result = client.call('/api/auth', {'username': username, 'password': value})
    assert result['authenticated'] and result['username'] == username


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-name', default='credentials-rehearsal')
    args = parser.parse_args()
    assert re.fullmatch(r'credentials-rehearsal(?:-[a-z0-9-]{1,40})?', args.run_name)
    assert recovery.sha_file(ROOT/'data/platform.sqlite3') == MAIN_SHA
    directory = ROOT/'data'/args.run_name
    directory.mkdir(exist_ok=False)
    db = directory/'platform.sqlite3'
    with recovery.connect_readonly(ROOT/'data/platform.sqlite3') as source, sqlite3.connect(db) as target:
        source.backup(target)
    baseline = recovery.database_inventory(db)
    with socket.socket() as probe:
        assert probe.connect_ex(('127.0.0.1', PORT)) != 0, 'Choose an unused rehearsal port'
    env = os.environ.copy()
    for key in ('PYTHONPATH', 'PYTHONHOME', 'VIRTUAL_ENV', 'DJANGO_SETTINGS_MODULE'):
        env.pop(key, None)
    env.update(PYTHONNOUSERSITE='1', MOTOR_SQLITE_PATH=str(db))
    report = {'success': False, 'transport': 'Native local HTTP; no browser',
              'database': str(db), 'main_database_unchanged': False, 'roles': [], 'checks': {}}
    log = (directory/'server.log').open('ab')
    server = subprocess.Popen([str(ROOT/'.venv/bin/python'), str(ROOT/'manage.py'),
        'runserver', f'127.0.0.1:{PORT}', '--noreload'], cwd=ROOT, env=env,
        stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT)
    try:
        for _ in range(80):
            if server.poll() is not None:
                raise RuntimeError('Isolated server exited before acceptance')
            try:
                if Client(PORT).call('/api/auth')['authenticated'] is False:
                    break
            except OSError:
                pass
            time.sleep(.25)
        else:
            raise RuntimeError('Isolated server did not become ready')
        admin = Client(PORT); admin.login('demo_admin')
        accounts = admin.call('/api/accounts')
        quality_id = next(r['id'] for r in accounts['rows'] if r['username'] == 'demo_quality')
        previous = admin.call(f'/api/accounts/{quality_id}')
        clients = [Client(PORT), Client(PORT)]
        for client in clients:
            client.login('demo_quality')
        p = admin.call(f'/api/accounts/{quality_id}/password/preview', {'receipt': previous['receipt']})
        assert p['permissions_unchanged'] and 'password' not in p['target']
        value = password()
        submitted_secrets = ['MotorDemo!2026', value]
        payload = dict(preview_token=p['preview_token'], password=value, confirmation=value, reason='隔离模拟账号口令恢复验收')
        saved = admin.call(f'/api/accounts/{quality_id}/password/reset', payload)
        admin.call(f'/api/accounts/{quality_id}/password/reset', payload, expected=409)
        after = admin.call(f'/api/accounts/{quality_id}')
        assert after['permissions'] == previous['permissions'] and after['user']['role'] == previous['user']['role']
        assert after['user']['revision'] == previous['user']['revision']
        for client in clients:
            client.call('/api/records/units/export', expected=401)
            client.call('/api/auth', dict(username='demo_quality', password='MotorDemo!2026'), expected=401)
        check = Client(PORT); login(check, 'demo_quality', value)
        check.call('/api/records/costs', expected=403)
        report['checks']['admin_reset'] = dict(old_sessions_rejected=2, old_password_rejected=True,
            new_login_passed=True, permissions_equal=True, repeated_request_rejected=True)
        disabled_value = password()
        submitted_secrets.append(disabled_value)
        created = json.loads(admin.call('/api/accounts', dict(username='rehearsal_inactive',
            display_name='隔离验收停用岗位', role='quality', is_active=False,
            password=disabled_value, reason='隔离验收停用账号口令维护'), expected=201))
        inactive_id = created['user']['id']
        info = admin.call(f'/api/accounts/{inactive_id}')
        p = admin.call(f'/api/accounts/{inactive_id}/password/preview', {'receipt': info['receipt']})
        new_disabled = password()
        submitted_secrets.append(new_disabled)
        admin.call(f'/api/accounts/{inactive_id}/password/reset', dict(preview_token=p['preview_token'],
            password=new_disabled, confirmation=new_disabled, reason='隔离核对停用状态不会改变'))
        assert admin.call(f'/api/accounts/{inactive_id}')['user']['is_active'] is False
        outsider = Client(PORT); outsider.call('/', binary=True)
        outsider.call('/api/auth', dict(username='rehearsal_inactive', password=new_disabled), expected=401)
        report['checks']['inactive_reset'] = dict(remains_inactive=True, new_password_login_rejected=True)
        # The administrative actor changes its own credential last.
        for role in ['quality', 'analyst', 'operations', 'finance', 'viewer', 'admin']:
            username = 'demo_' + role
            old = value if role == 'quality' else 'MotorDemo!2026'
            client = Client(PORT); login(client, username, old)
            context = client.call('/api/credentials')
            client.call('/api/credentials/change', dict(context_token=context['context_token'],
                current_password='wrong', password=password(), confirmation='different'), expected=400)
            new = password()
            submitted_secrets.append(new)
            result = client.call('/api/credentials/change', dict(context_token=context['context_token'],
                current_password=old, password=new, confirmation=new))
            assert result['signed_out'] and client.call('/api/auth')['authenticated'] is False
            client.call('/', binary=True)
            client.call('/api/auth', dict(username=username, password=old), expected=401)
            login(client, username, new)
            assert client.call('/api/auth')['role'] == role
            if role in ('admin', 'analyst', 'finance'):
                assert isinstance(client.call('/api/records/costs')['rows'], list)
            else:
                client.call('/api/records/costs', expected=403)
            topic = client.call('/api/topics/3/workspace')
            result = client.call('/api/topics/3/run', dict(context_token=topic['context_token'],
                config=dict(scope={}, reference_scope={}, primary_label='原范围', reference_label='相同参照')))
            assert result['cards'][0]['primary']['matched'] == 4500
            client.call('/api/credentials/change', {}, expected=403, csrf=False)
            if role != 'admin':
                client.call(f'/api/accounts/{quality_id}/password/preview', {'receipt': 'old'}, expected=403)
            report['roles'].append(dict(role=role, self_change_and_new_login=True,
                old_credential_and_session_rejected=True, permissions_and_topic_unchanged=True))
        with recovery.connect_readonly(db) as con:
            events = list(con.execute('SELECT action,detail FROM app_auditevent WHERE id>780'))
            actions = Counter(x[0] for x in events)
            assert actions['account.password_reset'] == 2 and actions['account.password_change'] == 6
            assert actions['account.create'] == 1
            assert set(actions) <= {'auth.login', 'account.create', 'account.password_reset', 'account.password_change'}
            raw_events = '\n'.join(x[1] for x in events)
            stored_hashes = [r[0] for r in con.execute('SELECT password FROM auth_user')]
            for secret in submitted_secrets + stored_hashes:
                assert secret not in raw_events
            assert all(json.loads(detail)['before']['revision'] == json.loads(detail)['after']['revision']
                for action,detail in events if action in ('account.password_reset', 'account.password_change'))
        report['audit_actions'] = dict(actions)
        report['checks']['audit'] = dict(no_submitted_password_or_hash_in_credential_events=True,
            exactly_two_admin_resets=True, exactly_six_self_changes=True, permission_configuration_revision_unchanged=True)
        report['success'] = True
    finally:
        server.terminate()
        try: server.wait(timeout=10)
        except subprocess.TimeoutExpired:
            server.kill(); server.wait(timeout=5)
        log.close()
        final = recovery.database_inventory(db)
        changed = {k for k,v in final['tables'].items() if v != baseline['tables'][k]}
        permitted = {'auth_user', 'auth_user_groups', 'app_accountaccessstate',
                     'app_accountchangelock', 'app_auditevent', 'django_session'}
        assert changed <= permitted, changed
        assert final['schema_sha256'] == baseline['schema_sha256']
        report.update(changed_tables=sorted(changed), all_other_tables_exact=True,
            business_facts_models_topics_views_snapshots_files_and_metrics_unchanged=True,
            owned_server_stopped=server.poll() is not None,
            main_database_unchanged=recovery.sha_file(ROOT/'data/platform.sqlite3') == MAIN_SHA,
            browser_verified=False, real_accounts_changed=False, real_systems_connected=False)
        assert report['main_database_unchanged']
        (ROOT/'data/credentials_runtime_validation.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')
        print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)


if __name__ == '__main__':
    main()
