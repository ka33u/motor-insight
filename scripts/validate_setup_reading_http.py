"""Setup and delivery tradeoff checks on a disposable normally replayed Excel database."""
import argparse, hashlib, json, os, socket, subprocess, sys, time
import urllib.error, urllib.request
from decimal import Decimal
from pathlib import Path
from urllib.parse import urlencode
ROOT = Path(__file__).resolve().parents[1]


from setup_reading_oracle import oracle


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--db', type=Path, required=True); parser.add_argument('--port', type=int, required=True)
    args = parser.parse_args()
    db = args.db.resolve(); assert db.is_file() and db != ROOT/'data/platform.sqlite3'
    sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
    main_hash = sha(ROOT/'data/platform.sqlite3')
    sys.path.insert(0, str(ROOT)); os.environ.update(DJANGO_SETTINGS_MODULE='config.settings', MOTOR_SQLITE_PATH=str(db))
    import django; django.setup()
    from django.test import Client
    from django.test.utils import CaptureQueriesContext
    from django.db import connection, reset_queries
    from django.contrib.auth import get_user_model
    from app.models import Record, AuditEvent
    from app import joint_setup, joint_schedule_data, joint_comparison
    facts = list(Record.objects.order_by('dataset', 'business_key').values_list('dataset', 'business_key', 'record_hash'))
    assert len(facts) == 233788
    audits = AuditEvent.objects.count(); counts = dict(comparisons=0, original_boards=0, event_checks=0, task_details=0, exports=0, zero_query_rebuilds=0)
    keys = [f'MP-261002-{n:03}' for n in range(1, 11)]+['MP-261009-001', 'MP-261009-002','MP-261016-001']
    originals = {key+'/'+p: sha_result(joint_schedule_data.load(key, p)['result']) for key in keys for p in ('due', 'priority')}
    with socket.socket() as sock: assert sock.connect_ex(('127.0.0.1', args.port)) != 0
    log = (ROOT/'data/setup_reading_http.server.log').open('ab')
    child = subprocess.Popen([sys.executable, str(ROOT/'manage.py'), 'runserver', f'127.0.0.1:{args.port}', '--noreload'],
        cwd=ROOT, env=os.environ.copy(), stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL)
    def fetch(path, cookie=None, value=None, csrf=None, status=200):
        headers = {'Cookie': cookie} if cookie else {}; data = None
        if value is not None: data = json.dumps(value).encode(); headers.update({'Content-Type': 'application/json', 'X-CSRFToken': csrf})
        try:
            with urllib.request.urlopen(urllib.request.Request(f'http://127.0.0.1:{args.port}'+path, data=data, headers=headers), timeout=45) as r:
                code, raw, meta = r.status, r.read(), dict(r.headers)
        except urllib.error.HTTPError as r: code, raw, meta = r.code, r.read(), dict(r.headers)
        assert code == status, (path.split('?')[0], code, raw[:100]); return raw, meta
    try:
        for _ in range(80):
            assert child.poll() is None
            try: fetch('/api/auth'); break
            except urllib.error.URLError: time.sleep(.15)
        else: raise RuntimeError('Local server unavailable')
        _, headers = fetch('/'); csrf = headers['Set-Cookie'].split('csrftoken=')[1].split(';')[0]
        for name in ('joint_setup.js', 'joint_compare.js', 'joint_compare.css'):
            assert fetch('/static/'+name)[0] == (ROOT/'static'/name).read_bytes()
        fetch('/api/joint-comparison/'+keys[0], 'csrftoken='+csrf, {}, csrf, 401)
        fixtures = {}; roles = []
        for role in ('admin', 'analyst', 'operations', 'quality', 'finance', 'viewer'):
            client = Client(); client.force_login(get_user_model().objects.get(username='demo_'+role))
            cookie = 'sessionid='+client.cookies['sessionid'].value+'; csrftoken='+csrf
            def post(path, value=None, status=200): return json.loads(fetch(path, cookie, value or {}, csrf, status)[0])
            if role not in ('admin', 'analyst', 'operations'):
                for suffix in ('', '/sources', '/tasks/ANY', '/export'):
                    for key in keys: post('/api/joint-comparison/'+key+suffix, {'receipt': 'untrusted'}, 403)
                roles.append(dict(role=role, denied=True)); continue
            for key in keys:
                base = '/api/joint-comparison/'+key; d = post(base); counts['comparisons'] += 1; boards = []
                for policy, side in [('due', 'left'), ('priority', 'right')]:
                    board = json.loads(fetch('/api/joint-schedule/'+key+'?'+urlencode(dict(policy=policy, receipt=d['policy_receipts'][policy])), cookie)[0])
                    boards.append(board); counts['original_boards'] += 1
                    if d['summary']: assert {r['id']: r[side] for r in d['jobs']} == {r['id']: r for r in board['jobs']}
                export = post(base+'/export', dict(receipt=d['receipt'], format='json')); counts['exports'] += 1
                assert AuditEvent.objects.latest('id').detail['file_sha256'] == hashlib.sha256(export['text'].encode()).hexdigest()
                doc = json.loads(export['text']); reset_queries()
                with CaptureQueriesContext(connection) as captured:
                    projection = joint_setup.build(doc['left']['result'], doc['right']['result'], doc['left']['resource_inputs'])
                assert len(captured) == 0 and projection == d['setup_reading']; counts['zero_query_rebuilds'] += 1
                for s in doc['left']['sources']:
                    if s.get('missing'): continue
                    r = Record.objects.select_related('source_row__batch').get(dataset=s['dataset'], business_key=s['key'])
                    assert (s['filename'], s['sheet'], s['row']) == (r.source_row.batch.filename, r.source_row.sheet, r.source_row.row_number)
                counts['event_checks'] += oracle(*boards, d['setup_reading'], doc['left']['resource_inputs'])
                original = joint_comparison.compare(*boards)
                assert all(d[k] == v for k,v in original.items())
                selection = {next((e['task_id'] for e in d['setup_reading']['events'] if e['kind']==kind and e['policy']==policy),None) for kind in ('initial','change','same') for policy in ('due','priority')}-{None}
                selection = sorted(selection) or ([d['tasks'][0]['id']] if d['tasks'] else [])
                for task in selection:
                    detail = post(base+'/tasks/'+task,dict(receipt=d['receipt'])); counts['task_details'] += 1
                    for side,policy in [('left','due'),('right','priority')]:
                        assert detail['setup_reading'][side] == next((e for e in d['setup_reading']['events'] if e['policy']==policy and e['task_id']==task),None)
                names={'MP-261016-001':'mixed','MP-261009-001':'partial','MP-261002-006':'empty','MP-261002-007':'paused'}
                if role=='admin' and key in names:
                    fixtures[names[key]]=doc['comparison'] if names[key]=='mixed' else d['setup_reading']
                if key == 'MP-261009-001':
                    csv = post(base+'/export', dict(receipt=d['receipt'], format='csv')); counts['exports'] += 1
                    assert '换型准备/events' in csv['text'] and '两列共同来源' in csv['text']
            roles.append(dict(role=role, allowed=True))
        assert facts == list(Record.objects.order_by('dataset', 'business_key').values_list('dataset', 'business_key', 'record_hash'))
        assert AuditEvent.objects.count() == audits+counts['exports'] and sha(ROOT/'data/platform.sqlite3') == main_hash
        for identity, value in originals.items():
            key, policy = identity.split('/'); assert sha_result(joint_schedule_data.load(key, policy)['result']) == value
        path = ROOT/'tests/fixtures/setup_reading.json'
        assert json.loads(path.read_text()) == fixtures
        proof = dict(success=True, roles=roles, **counts, original_heuristic_outputs=26, facts_unchanged=True,
                     sources_exact=True, main_database_bytes_unchanged=True, browser_acceptance=False)
        (ROOT/'data/setup_reading_http.json').write_text(json.dumps(proof, ensure_ascii=False, indent=2)+'\n')
        print(json.dumps(proof, ensure_ascii=False))
    finally:
        child.terminate(); child.wait(timeout=10); log.close()


def sha_result(value): return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


if __name__ == '__main__': main()
