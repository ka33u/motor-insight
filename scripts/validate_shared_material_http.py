"""Exercise the two imported shared-material studies through real local HTTP."""
import argparse
import hashlib
import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlencode, quote

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--db', type=Path, required=True)
    parser.add_argument('--port', type=int, required=True)
    args = parser.parse_args()
    db = args.db.resolve()
    assert db.is_file() and db != ROOT/'data/platform.sqlite3'
    sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
    main_hash = sha(ROOT/'data/platform.sqlite3')
    sys.path.insert(0, str(ROOT))
    os.environ.update(DJANGO_SETTINGS_MODULE='config.settings', MOTOR_SQLITE_PATH=str(db))
    import django
    django.setup()
    from django.test import Client
    from django.test.utils import CaptureQueriesContext
    from django.db import connection, reset_queries
    from django.contrib.auth import get_user_model
    from app.models import Record, AuditEvent
    from app.joint_material_evidence import build
    from validate_shared_material import verify, KEYS, JOBS, MATERIAL
    from validate_joint_material_http import oracle
    verification = verify()
    facts = list(Record.objects.order_by('dataset', 'business_key').values_list('dataset', 'business_key', 'record_hash'))
    audits = AuditEvent.objects.count()
    counts = dict(boards=0, material_details=0, task_details=0, comparisons=0, exports=0, zero_query_rebuilds=0)
    fixtures = {}
    with socket.socket() as sock:
        assert sock.connect_ex(('127.0.0.1', args.port)) != 0
    log = (ROOT/'data/shared_material_http.server.log').open('ab')
    child = subprocess.Popen([sys.executable, str(ROOT/'manage.py'), 'runserver', f'127.0.0.1:{args.port}', '--noreload'],
        cwd=ROOT, env=os.environ.copy(), stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL)
    def fetch(path, cookie=None, value=None, csrf=None, status=200):
        headers = {'Cookie': cookie} if cookie else {}
        body = None
        if value is not None:
            body = json.dumps(value).encode()
            headers.update({'Content-Type': 'application/json', 'X-CSRFToken': csrf})
        try:
            with urllib.request.urlopen(urllib.request.Request(f'http://127.0.0.1:{args.port}'+path, data=body, headers=headers), timeout=40) as r:
                code, raw, meta = r.status, r.read(), dict(r.headers)
        except urllib.error.HTTPError as r:
            code, raw, meta = r.code, r.read(), dict(r.headers)
        assert code == status, (path.split('?')[0], code, raw[:80])
        return raw, meta
    def get(path, cookie=None, status=200):
        return json.loads(fetch(path, cookie, status=status)[0])
    def sources_exact(rows):
        assert len(rows) == len({(s['dataset'], s['key']) for s in rows})
        for s in rows:
            r = Record.objects.select_related('source_row__batch').get(dataset=s['dataset'], business_key=s['key'])
            assert (s['filename'], s['sheet'], s['row']) == (r.source_row.batch.filename, r.source_row.sheet, r.source_row.row_number)
    try:
        for _ in range(80):
            assert child.poll() is None
            try:
                get('/api/auth')
                break
            except urllib.error.URLError:
                time.sleep(.15)
        else:
            raise RuntimeError('Local server unavailable')
        html, headers = fetch('/')
        csrf = headers['Set-Cookie'].split('csrftoken=')[1].split(';')[0]
        get('/api/joint-schedule/'+KEYS[0], status=401)
        roles = []
        for role in ('admin', 'analyst', 'operations', 'quality', 'finance', 'viewer'):
            client = Client()
            client.force_login(get_user_model().objects.get(username='demo_'+role))
            cookie = 'sessionid='+client.cookies['sessionid'].value+'; csrftoken='+csrf
            def post(path, value=None, status=200):
                return json.loads(fetch(path, cookie, value or {}, csrf, status)[0])
            if role not in ('admin', 'analyst', 'operations'):
                for key in KEYS:
                    get('/api/joint-schedule/'+key, cookie, 403)
                    get('/api/joint-schedule/'+key+'/materials/'+MATERIAL+'?unit=kg', cookie, 403)
                    post('/api/joint-comparison/'+key, status=403)
                roles.append(dict(role=role, denied=True))
                continue
            assert set(KEYS) <= {r['id'] for r in get('/api/joint-schedule', cookie)['rows']}
            for key in KEYS:
                compare = post('/api/joint-comparison/'+key)
                counts['comparisons'] += 1
                assert compare['state'] == 'compared' and compare['summary']['jobs'] == 2 and compare['summary']['qty'] == 12
                for policy, side in [('due', 'left'), ('priority', 'right')]:
                    base = '/api/joint-schedule/'+key
                    board = get(base+'?policy='+policy, cookie)
                    counts['boards'] += 1
                    assert {j['id']: j[side] for j in compare['jobs']} == {j['id']: j for j in board['jobs']}
                    q = urlencode(dict(policy=policy, receipt=board['receipt']))
                    for balance in board['balances']:
                        path = base+'/materials/'+quote(balance['material_id'], safe='')+'?'+q+'&'+urlencode(dict(unit=balance['unit']))
                        point = get(path, cookie)
                        counts['material_details'] += 1
                        sources_exact(point['sources'])
                        oracle(board, point['evidence'])
                        assert point['can_download_original'] == (role == 'admin')
                        if balance['material_id'] == MATERIAL:
                            for job in JOBS:
                                task = next(t for t in board['tasks'] if t['job_id'] == job)
                                detail = get(base+'/tasks/'+task['id']+'?'+q, cookie)
                                assert detail['row'] == task
                                sources_exact(detail['sources'])
                                counts['task_details'] += 1
                            if role == 'admin':
                                fixtures[key+'/'+policy] = dict(board=board | {'receipt': None}, material=point['evidence'])
                    raw = fetch(base+'/export?'+q+'&format=json', cookie)[0]
                    counts['exports'] += 1
                    doc = json.loads(raw)
                    assert doc['result']['tasks'] == board['tasks'] and len(doc['resource_inputs']['schedule_tasks']) == 52
                    assert AuditEvent.objects.latest('id').detail['file_sha256'] == hashlib.sha256(raw).hexdigest()
                    reset_queries()
                    with CaptureQueriesContext(connection) as captured:
                        for b in board['balances']:
                            report, _ = build(doc['result'], b['material_id'], b['unit'])
                            oracle(board, report)
                            counts['zero_query_rebuilds'] += 1
                    assert len(captured) == 0
                exported = post('/api/joint-comparison/'+key+'/export', dict(receipt=compare['receipt'], format='json'))
                counts['exports'] += 1
                comparison_doc = json.loads(exported['text'])
                assert len(comparison_doc['comparison']['tasks']) == 52
                assert AuditEvent.objects.latest('id').detail['file_sha256'] == hashlib.sha256(exported['text'].encode()).hexdigest()
            roles.append(dict(role=role, allowed=True))
        assert facts == list(Record.objects.order_by('dataset', 'business_key').values_list('dataset', 'business_key', 'record_hash'))
        assert AuditEvent.objects.count() == audits+counts['exports'] and sha(ROOT/'data/platform.sqlite3') == main_hash
        proof = dict(success=True, roles=roles, **counts, source_rows_exact=True, business_facts_unchanged=True,
                     main_database_unchanged=True, browser_acceptance=False)
        (ROOT/'data/shared_material_http.json').write_text(json.dumps(proof, ensure_ascii=False, indent=2)+'\n')
        (ROOT/'data/shared_material_http_results.json').write_text(json.dumps(fixtures, ensure_ascii=False)+'\n')
        print(json.dumps(proof, ensure_ascii=False))
    finally:
        child.terminate()
        child.wait(timeout=10)
        log.close()


if __name__ == '__main__':
    main()
