"""Native HTTP verification on an isolated database; never browser automation."""
import argparse
import csv
import hashlib
import io
import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlencode

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--db', type=Path, required=True)
    parser.add_argument('--port', type=int, required=True)
    args = parser.parse_args()
    db = args.db.resolve()
    assert db != ROOT/'data/platform.sqlite3' and db.is_file()
    digest = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
    main_hash = digest(ROOT/'data/platform.sqlite3')
    os.environ['DJANGO_SETTINGS_MODULE'] = 'config.settings'
    os.environ['MOTOR_SQLITE_PATH'] = str(db)
    sys.path.insert(0, str(ROOT))
    import django
    django.setup()
    from django.test import Client
    from django.contrib.auth import get_user_model
    from app.models import Record, AuditEvent
    with socket.socket() as sock:
        assert sock.connect_ex(('127.0.0.1', args.port)) != 0
    log = (ROOT/'data/first_piece_http.server.log').open('ab')
    child = subprocess.Popen([sys.executable, str(ROOT/'manage.py'), 'runserver', f'127.0.0.1:{args.port}', '--noreload'], cwd=ROOT, env=os.environ.copy(), stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL)

    def fetch(path, cookie=None, status=200):
        req = urllib.request.Request(f'http://127.0.0.1:{args.port}'+path, headers={'Cookie': cookie} if cookie else {})
        try:
            with urllib.request.urlopen(req, timeout=30) as response:
                code, raw, headers = response.status, response.read(), dict(response.headers)
        except urllib.error.HTTPError as response:
            code, raw, headers = response.code, response.read(), dict(response.headers)
        assert code == status, (path.split('?')[0], code, raw[:80])
        return raw, headers

    def get(path, cookie=None, status=200):
        return json.loads(fetch(path, cookie, status)[0])

    try:
        for _ in range(80):
            if child.poll() is not None:
                raise RuntimeError('Isolated native server failed')
            try:
                get('/api/auth')
                break
            except urllib.error.URLError:
                time.sleep(.15)
        else:
            raise RuntimeError('Isolated native server unavailable')
        assert 'first_piece.css?v=' in fetch('/')[0].decode()
        for name in ('first_piece.js', 'first_piece.css', 'app.js'):
            assert fetch('/static/'+name)[0] == (ROOT/'static'/name).read_bytes()
        count, audits = Record.objects.count(), AuditEvent.objects.count()
        get('/api/first-piece', status=401)
        results = []
        for role in ('admin', 'analyst', 'operations', 'quality', 'finance', 'viewer'):
            client = Client()
            client.force_login(get_user_model().objects.get(username='demo_'+role))
            cookie = 'sessionid='+client.cookies['sessionid'].value
            allowed = role in ('admin', 'analyst', 'operations')
            d = get('/api/first-piece', cookie)
            assert d['summary'] == dict(plans=288, ready=219, waiting=17, future=0, out=19, missing=12, metrology=13, attention=8, work_orders=32, measurements=529)
            assert d['total'] == 288 and len(d['rows']) == 25
            query = urlencode(dict(receipt=d['receipt']))
            detail = get('/api/first-piece/'+d['rows'][0]['id']+'?'+query, cookie)
            assert detail['source_total'] > 0 and all(not s.get('missing') for s in detail['sources'])
            for source in detail['sources']:
                row = Record.objects.select_related('source_row__batch').get(dataset=source['dataset'], business_key=source['key'])
                assert row.source_row.row_number == source['row'] and row.source_row.sheet == source['sheet']
            for fmt in ('json','csv'):
                raw, headers = fetch('/api/first-piece/export?'+query+'&format='+fmt, cookie)
                assert headers['Cache-Control'] == 'no-store' and headers['Content-Disposition'].startswith('attachment;')
                assert b'cents' not in raw
                if fmt == 'json':
                    document = json.loads(raw)
                    assert document['summary'] == d['summary'] and len(document['rows']) == 288
                    assert len(document['details']) == 288 and 'receipt' not in document
                else:
                    rows = list(csv.reader(io.StringIO(raw.decode('utf-8-sig'))))
                    assert len(rows) == 293
                assert AuditEvent.objects.latest('id').detail['file_sha256'] == hashlib.sha256(raw).hexdigest()
            fetch('/api/first-piece/export?'+query+'&state=ready', cookie, 409)
            selected = get('/api/first-piece?state=metrology', cookie)
            assert selected['total'] == 13 and selected['all_summary']['plans'] == 288
            target = get('/api/first-piece?study=LR-261001-001', cookie, 200 if allowed else 403)
            if allowed:
                assert target['targets']['summary'] == dict(rows=66, missing=66, candidates=0, attention=0)
            results.append(dict(role=role, plans=288, ready=219, target_allowed=allowed, exports=2))
        assert Record.objects.count() == count == 230509
        assert AuditEvent.objects.count() == audits+12
        assert digest(ROOT/'data/platform.sqlite3') == main_hash
        proof = dict(success=True, native_http=True, isolated_database=True, roles=results, assets_exact=True, source_rows_exact=True, main_unchanged=True,
                     browser_acceptance=False, mobile_acceptance=False, actual_download_acceptance=False)
        (ROOT/'data/first_piece_http.json').write_text(json.dumps(proof, ensure_ascii=False, indent=2)+'\n')
        print(json.dumps(proof, ensure_ascii=False))
    finally:
        child.terminate()
        try:
            child.wait(timeout=10)
        except subprocess.TimeoutExpired:
            child.kill()
            child.wait(timeout=10)
        log.close()


if __name__ == '__main__':
    main()
