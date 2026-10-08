"""Order/batch/BOM reading: unchanged native API and new client asset verification."""
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
    log = (ROOT/'data/baseline_reading_http.server.log').open('ab')
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
        assert 'order_baseline.css?v=' in fetch('/')[0].decode()
        for name in ('order_baseline.js', 'order_baseline_reading.js', 'order_baseline.css', 'app.js'):
            assert fetch('/static/'+name)[0] == (ROOT/'static'/name).read_bytes()
        count, audits = Record.objects.count(), AuditEvent.objects.count()
        facts=list(Record.objects.order_by('dataset','business_key').values_list('dataset','business_key','record_hash'))
        get('/api/order-baselines', status=401)
        results = []
        for role in ('admin', 'analyst', 'operations', 'quality', 'finance', 'viewer'):
            client = Client()
            client.force_login(get_user_model().objects.get(username='demo_'+role))
            cookie = 'sessionid='+client.cookies['sessionid'].value
            allowed = role in ('admin', 'analyst', 'operations')
            if not allowed:
                for path in ('/api/order-baselines', '/api/order-baselines/OB-261001-001', '/api/records/order_baseline_bom', '/api/records/order_baseline_bom/export', '/api/bi-field-catalog?dataset=order_baseline_bom'):
                    fetch(path, cookie, 403)
                fields = get('/api/bi-field-catalog', cookie)
                assert not any(r['key'].startswith('order_baseline') for r in fields['datasets'])
                results.append(dict(role=role, denied=True))
                continue
            assert len(get('/api/order-baselines', cookie)['rows']) == 10
            url = '/api/order-baselines/OB-261001-001'
            d = get(url, cookie)
            fixture=json.loads((ROOT/'tests/fixtures/order_baseline_board_001_due.json').read_text())
            assert all(d[k]==v for k,v in fixture.items())
            assert d['summary']['order_qty'] == 135 and d['summary']['planned_qty'] == 50 and d['summary']['uncovered_qty'] == 85
            assert d['summary']['customer_late_jobs'] == d['summary']['scheduled_jobs'] == 6
            assert all(o['order_finish'] is None for o in d['orders'])
            query = urlencode(dict(receipt=d['receipt'], policy='due'))
            task = get(url+'/links/'+d['links'][0]['id']+'?'+query, cookie)
            assert task['row'] == d['links'][0]
            assert task['can_download_original'] == (role == 'admin')
            for page in range(1, (d['source_count']+39)//40+1):
                source = get(url+'/sources?'+query+'&page='+str(page), cookie)
                assert source['total'] == d['source_count'] and source['rows']
                for row in source['rows']:
                    record = Record.objects.select_related('source_row__batch').get(dataset=row['dataset'], business_key=row['key'])
                    assert (row['filename'], row['sheet'], row['row']) == (record.source_row.batch.filename, record.source_row.sheet, record.source_row.row_number)
            for number in range(1, 11):
                trial = get('/api/order-baselines/OB-261001-'+f'{number:03}', cookie)
                assert trial['state'] == ('paused' if number in (5, 6, 7, 10) else 'review' if number in (8, 9) else 'aligned')
                if number == 8:
                    fixture=json.loads((ROOT/'tests/fixtures/order_baseline_board_008_due.json').read_text())
                    assert all(trial[k]==v for k,v in fixture.items())
                if number == 4:
                    assert trial['summary']['scheduled_jobs'] == 0 and all(o['order_finish'] is None for o in trial['orders'])
            priority = get('/api/order-baselines/OB-261001-002?policy=priority', cookie)
            assert priority['summary']['uncovered_qty'] == 85
            raw, headers = fetch(url+'/export?'+query+'&format=json', cookie)
            document = json.loads(raw)
            assert len(document['trial']['resource_inputs']['schedule_tasks']) == 198 and len(document['baseline_inputs']['order_baseline_bom']) == 54
            assert document['result']['orders'] == d['orders'] and 'receipt' not in document and headers['Cache-Control'] == 'no-store'
            raw, _ = fetch(url+'/export?'+query+'&format=csv', cookie)
            rows = list(csv.reader(io.StringIO(raw.decode('utf-8-sig'))))
            assert ['order_baseline_bom'] in rows and ['全部来源'] in rows
            assert AuditEvent.objects.latest('id').detail['file_sha256'] == hashlib.sha256(raw).hexdigest()
            fetch(url+'/export?'+query+'&filter=unknown', cookie, 400)
            fetch(url+'/export?'+urlencode(dict(receipt=d['receipt'], policy='priority')), cookie, 409)
            results.append(dict(role=role, orders=6, planned_qty=50, uncovered_qty=85, bom_rows=54, sources=d['source_count'], exports=2))
        assert Record.objects.count() == count == 232200
        assert facts == list(Record.objects.order_by('dataset','business_key').values_list('dataset','business_key','record_hash'))
        assert AuditEvent.objects.count() == audits+6
        assert digest(ROOT/'data/platform.sqlite3') == main_hash
        proof = dict(success=True, native_http=True, isolated_database=True, roles=results, assets_exact=True, source_rows_exact=True, main_unchanged=True,
                     browser_acceptance=False, mobile_acceptance=False, actual_download_acceptance=False)
        (ROOT/'data/baseline_reading_http.json').write_text(json.dumps(proof, ensure_ascii=False, indent=2)+'\n')
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
