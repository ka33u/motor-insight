"""Read-only trial presentation checks over native HTTP on a replay DB copy."""
import argparse, hashlib, json, os, socket, subprocess, sys, time
import urllib.error, urllib.request
from pathlib import Path
from urllib.parse import urlencode

ROOT = Path(__file__).resolve().parents[1]

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--db', type=Path, required=True)
    parser.add_argument('--port', type=int, required=True)
    parser.add_argument('--write-fixtures', action='store_true')
    args = parser.parse_args()
    db = args.db.resolve()
    assert db.is_file() and db != ROOT/'data/platform.sqlite3'
    sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
    main_hash = sha(ROOT/'data/platform.sqlite3')
    os.environ.update(DJANGO_SETTINGS_MODULE='config.settings', MOTOR_SQLITE_PATH=str(db))
    sys.path.insert(0, str(ROOT))
    import django
    django.setup()
    from django.test import Client
    from django.contrib.auth import get_user_model
    from app.models import Record, AuditEvent
    facts = list(Record.objects.order_by('dataset','business_key').values_list('dataset','business_key','record_hash'))
    audit_start = AuditEvent.objects.count()
    with socket.socket() as sock:
        assert sock.connect_ex(('127.0.0.1', args.port)) != 0
    log = (ROOT/'data/schedule_reading_http.server.log').open('ab')
    child = subprocess.Popen([sys.executable, str(ROOT/'manage.py'), 'runserver', f'127.0.0.1:{args.port}', '--noreload'], cwd=ROOT, env=os.environ.copy(), stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL)
    def fetch(path, cookie=None, data=None, csrf=None, status=200):
        headers = {'Cookie':cookie} if cookie else {}
        if csrf: headers['X-CSRFToken'] = csrf
        payload = None
        if data is not None:
            headers['Content-Type'] = 'application/json'
            payload = json.dumps(data).encode()
        try:
            with urllib.request.urlopen(urllib.request.Request(f'http://127.0.0.1:{args.port}'+path, data=payload, headers=headers), timeout=40) as r:
                code, raw, result_headers = r.status, r.read(), dict(r.headers)
        except urllib.error.HTTPError as r:
            code, raw, result_headers = r.code, r.read(), dict(r.headers)
        assert code == status, (path.split('?')[0], code, raw[:90])
        return raw, result_headers
    def get(path, cookie=None, status=200): return json.loads(fetch(path, cookie, status=status)[0])
    def check_sources(rows):
        for s in rows:
            r = Record.objects.select_related('source_row__batch').get(dataset=s['dataset'],business_key=s['key'])
            assert (s['filename'],s['sheet'],s['row'],s['source_row_id']) == (r.source_row.batch.filename,r.source_row.sheet,r.source_row.row_number,r.source_row_id)
    def public_detail(d): return {k:v for k,v in d.items() if k != 'receipt'}
    try:
        for _ in range(80):
            assert child.poll() is None
            try: get('/api/auth'); break
            except urllib.error.URLError: time.sleep(.15)
        else: raise RuntimeError('Native server unavailable')
        html, headers = fetch('/')
        assert b'/static/schedule_reading.js?v=' in html
        csrf = headers['Set-Cookie'].split('csrftoken=')[1].split(';')[0]
        for name in ('finite_schedule.js','crew_schedule.js','joint_schedule.js','joint_compare.js','schedule_reading.js'):
            assert fetch('/static/'+name)[0] == (ROOT/'static'/name).read_bytes()
        results, fixtures, exports = [], {}, 0
        for role in ('admin','analyst','operations','quality','finance','viewer'):
            client = Client(); client.force_login(get_user_model().objects.get(username='demo_'+role))
            cookie = 'sessionid='+client.cookies['sessionid'].value+'; csrftoken='+csrf
            for mode,prefix,blocked_case in [('finite','SP',4),('crew','CR',4),('joint','MP',2)]:
                base = '/api/'+mode+'-schedule/'+prefix+'-261002-001'
                allowed = mode == 'finite' or role in ('admin','analyst','operations')
                if not allowed:
                    for suffix in ('','/sources','/tasks/ANY','/export'): get(base+suffix,cookie,403)
                    results.append(dict(role=role,mode=mode,denied=True)); continue
                d = get(base,cookie)
                fixture = json.loads((ROOT/f'tests/fixtures/{mode}_schedule_board_001_due.json').read_text())
                assert all(d[k] == v for k,v in fixture.items())
                assert d['summary']['qty'] == 50 and len(d['tasks']) == 198
                q = urlencode(dict(receipt=d['receipt'],policy='due'))
                detail = get(base+'/tasks/'+d['tasks'][0]['id']+'?'+q,cookie)
                assert detail['row'] == d['tasks'][0] and detail['can_download_original'] == (role == 'admin')
                check_sources(detail['sources'])
                blocked_base = '/api/'+mode+'-schedule/'+prefix+f'-261002-{blocked_case:03}'
                blocked = get(blocked_base,cookie)
                task = next(t for t in blocked['tasks'] if t['state']=='blocked')
                bd = get(blocked_base+'/tasks/'+task['id']+'?'+urlencode(dict(receipt=blocked['receipt'],policy='due')),cookie)
                assert bd['row'] == task and task['finished'] is None
                check_sources(bd['sources'])
                if role == 'admin': fixtures[mode] = dict(scheduled=public_detail(detail),blocked=public_detail(bd))
                rows = []
                for page in range(1,(d['source_count']+39)//40+1):
                    s = get(base+'/sources?'+q+'&page='+str(page),cookie)
                    assert s['total'] == d['source_count']; rows += s['rows']
                assert len(rows) == len({(r['dataset'],r['key']) for r in rows}) == d['source_count']
                check_sources(rows)
                for fmt in ('json','csv'):
                    raw, h = fetch(base+'/export?'+q+'&format='+fmt,cookie)
                    assert h['Content-Disposition'].startswith('attachment;') and h['Cache-Control']=='no-store'
                    assert AuditEvent.objects.latest('id').detail['file_sha256'] == hashlib.sha256(raw).hexdigest()
                    if fmt=='json': assert json.loads(raw)['result']['tasks'] == d['tasks']
                    else: assert raw.startswith(b'\xef\xbb\xbf') and d['tasks'][0]['id'] in raw.decode('utf-8-sig')
                    exports += 1
                get(base+'/export?'+q+'&filter=unknown',cookie,400)
                results.append(dict(role=role,mode=mode,sources=len(rows),tasks=198,exports=2))
            # Comparison remains a POST contract with CSRF and complete scope.
            base = '/api/joint-comparison/MP-261002-001'
            def post(path, data): return json.loads(fetch(path,cookie,data,csrf)[0])
            if role not in ('admin','analyst','operations'):
                fetch(base,cookie,{},csrf,403); continue
            d = post(base,{})
            assert d['summary']['qty'] == 50 and len(d['tasks']) == 198
            t = post(base+'/tasks/'+d['tasks'][0]['id'],dict(receipt=d['receipt']))
            assert t['task'] == d['tasks'][0]
            if role == 'admin':
                comparison = {k:v for k,v in d.items() if k not in ('receipt','policy_receipts','receipt_seconds')}
                fixtures['comparison_detail'] = public_detail(t)
            rows = []
            for page in range(1,(d['source_count']+39)//40+1):
                rows += post(base+'/sources',dict(receipt=d['receipt'],page=page))['rows']
            assert len(rows) == len({(r['dataset'],r['key']) for r in rows}) == d['source_count']; check_sources(rows)
            for fmt in ('json','csv'):
                file = post(base+'/export',dict(receipt=d['receipt'],format=fmt)); exports += 1
                assert AuditEvent.objects.latest('id').detail['file_sha256'] == hashlib.sha256(file['text'].encode()).hexdigest()
                if fmt == 'json': assert len(json.loads(file['text'])['comparison']['tasks']) == 198
            results.append(dict(role=role,mode='comparison',sources=len(rows),tasks=198,exports=2))
        assert facts == list(Record.objects.order_by('dataset','business_key').values_list('dataset','business_key','record_hash'))
        assert len(facts)==232200 and AuditEvent.objects.count()==audit_start+exports
        assert sha(ROOT/'data/platform.sqlite3')==main_hash
        for name, data in [('schedule_task_reading.json',fixtures),('joint_comparison_board_001.json',comparison)]:
            p = ROOT/'tests/fixtures'/name
            if args.write_fixtures: p.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n')
            else: assert json.loads(p.read_text()) == data
        proof = dict(success=True,roles=results,exports=exports,facts_unchanged=True,main_database_unchanged=True,assets_exact=True,sources_exact=True,fixtures_exact=True,browser_acceptance=False)
        (ROOT/'data/schedule_reading_http.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2)+'\n')
        print(json.dumps(proof,ensure_ascii=False),flush=True)
    finally:
        child.terminate(); child.wait(timeout=10); log.close()

if __name__ == '__main__': main()
