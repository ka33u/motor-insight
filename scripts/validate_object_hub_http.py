"""Exercise object identity, references and role boundaries through isolated native HTTP."""
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
from http.cookies import SimpleCookie
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--db', type=Path, required=True)
    parser.add_argument('--port', type=int, required=True)
    args = parser.parse_args()
    db = args.db.resolve()
    assert db != ROOT/'data/platform.sqlite3' and db.is_file()
    sha = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
    main_hash = sha(ROOT/'data/platform.sqlite3')
    os.environ['DJANGO_SETTINGS_MODULE'] = 'config.settings'
    os.environ['MOTOR_SQLITE_PATH'] = str(db)
    sys.path.insert(0, str(ROOT))
    import django
    django.setup()
    from django.test import Client
    from django.contrib.auth import get_user_model
    from app import topic_workspace as ws, object_hub as hub
    from app.schema import SCHEMAS
    from django.db.models import Count
    from app.models import Record, AnalysisModel, Topic, TopicView, TopicPage, TopicPageVersion, TopicSnapshot, MetricVersion, AuditEvent
    protected = [Record, AnalysisModel, Topic, TopicView, TopicPage, TopicPageVersion, TopicSnapshot, MetricVersion, AuditEvent]
    fingerprint = lambda model: ws.digest(list(model.objects.order_by('pk').values()))
    before = {model.__name__: fingerprint(model) for model in protected}
    with socket.socket() as sock:
        assert sock.connect_ex(('127.0.0.1', args.port)) != 0
    log = (ROOT/'data/object_hub_http.server.log').open('ab')
    child = subprocess.Popen([sys.executable, str(ROOT/'manage.py'), 'runserver', f'127.0.0.1:{args.port}', '--noreload'], cwd=ROOT, env=os.environ.copy(), stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL)

    def fetch(path, cookie='', csrf='', body=None, status=200):
        headers = {'Cookie': cookie}
        if body is not None:
            headers.update({'Content-Type': 'application/json', 'X-CSRFToken': csrf})
        request = urllib.request.Request(f'http://127.0.0.1:{args.port}'+path, headers=headers, data=None if body is None else json.dumps(body).encode())
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                code, raw, headers = response.status, response.read(), dict(response.headers)
        except urllib.error.HTTPError as response:
            code, raw, headers = response.code, response.read(), dict(response.headers)
        assert code == status, (path, code, raw[:100])
        return raw, headers

    try:
        for _ in range(80):
            assert child.poll() is None
            try:
                fetch('/api/auth'); break
            except urllib.error.URLError:
                time.sleep(.15)
        else:
            raise RuntimeError('Isolated server unavailable')
        assert 'object_hub.js?v=' in fetch('/')[0].decode() and 'object_hub.css?v=' in fetch('/')[0].decode()
        for name in ('object_hub.js', 'object_hub.css', 'app.js'):
            assert fetch('/static/'+name)[0] == (ROOT/'static'/name).read_bytes()
        results = []
        for role in ('admin', 'analyst', 'operations', 'quality', 'finance', 'viewer'):
            user = get_user_model().objects.get(username='demo_'+role)
            client = Client(); client.force_login(user)
            cookie = 'sessionid='+client.cookies['sessionid'].value
            _, headers = fetch('/', cookie)
            cookies = SimpleCookie(); cookies.load(headers['Set-Cookie']); csrf = cookies['csrftoken'].value
            cookie += '; csrftoken='+csrf
            def post(path, body, status=200):
                raw, headers = fetch(path, cookie, csrf, body, status)
                if '/object-hub/' in path and status == 200:
                    assert headers['Cache-Control'] == 'no-store'
                return json.loads(raw)
            def search(q, dataset='', mode='exact', page=1, receipt=None):
                return post('/api/object-hub/search',dict(filters=dict(q=q,dataset=dataset,mode=mode),page=page,receipt=receipt))
            samples=[]
            for dataset in hub.COMMON:
                record=Record.objects.filter(dataset=dataset).order_by('business_key').first()
                assert record is not None
                d=search(record.business_key,dataset)
                assert d['total']==1 and d['rows'][0]['record_id']==record.pk
                source=d['rows'][0]['source']
                assert source['sheet']==record.source_row.sheet and source['row']==record.source_row.row_number
                assert source['filename']==record.source_row.batch.filename and d['rows'][0]['key']==record.business_key
                samples.append(dataset)
            # Check a complete multi-page type cohort against independently read raw identifiers.
            expected=list(Record.objects.filter(dataset='materials').order_by('business_key').values_list('business_key',flat=True))
            first=search('01.','materials','prefix');seen=[r['key'] for r in first['rows']]
            for page in range(2,first['pages']+1):
                next_page=search('01.','materials','prefix',page,first['receipt']);seen.extend(r['key'] for r in next_page['rows'])
            assert seen==[key for key in expected if key.lower().startswith('01.')]
            assert len(seen)==first['total'] and all(key.startswith('0') for key in seen)
            # Choose an existing work order with at least one full page of single-unit references.
            group=Record.objects.filter(dataset='units').values('values__work_order_id').annotate(n=Count('id')).order_by('-n').first()
            root=Record.objects.get(dataset='work_orders',business_key=group['values__work_order_id'])
            d=json.loads(fetch('/api/object-hub/'+str(root.pk),cookie)[0])
            assert d['object']['key']==root.business_key
            direct=next(g for g in d['inbound'] if g['dataset']=='units')
            expected=list(Record.objects.filter(dataset='units',values__work_order_id=root.business_key).order_by('business_key').values_list('business_key',flat=True))
            assert direct['count']==len(expected)
            seen=[];page=1
            while True:
                rows=post(f'/api/object-hub/{root.pk}/related',dict(dataset='units',page=page,receipt=d['receipt']))
                assert rows['total']==len(expected)
                for row in rows['rows']:
                    assert [f['name'] for f in row['matched_fields']]==['work_order_id']
                    seen.append(row['key'])
                if page==rows['pages']:break
                page+=1
            assert seen==expected and len(seen)==len(set(seen))
            money_allowed=role in ('admin','analyst','finance')
            has_costs=Record.objects.filter(dataset='costs',values__work_order_id=root.business_key).exists()
            assert ('costs' in {g['dataset'] for g in d['inbound']})==(money_allowed and has_costs)
            material=Record.objects.filter(dataset='materials').order_by('business_key').first()
            detail=json.loads(fetch('/api/object-hub/'+str(material.pk),cookie)[0])
            assert ('unit_cost_cents' in {f['name'] for f in detail['fields']})==money_allowed
            assert detail['can_download_excel']==(role=='admin')
            cost=Record.objects.filter(dataset='costs').first()
            fetch('/api/object-hub/'+str(cost.pk),cookie,status=200 if money_allowed else 404)
            post(f'/api/object-hub/{root.pk}/related',dict(dataset='units',page=1,receipt=d['receipt']+'x'),409)
            post(f'/api/object-hub/{root.pk}/related',dict(dataset='units',page=1,receipt=detail['receipt']),409)
            if not money_allowed:post(f'/api/object-hub/{root.pk}/related',dict(dataset='costs',page=1,receipt=d['receipt']),400)
            results.append(dict(role=role,typed_exact_searches=len(samples),material_prefix_rows=first['total'],unit_references=len(expected),exact_excel_sources=True,role_boundaries=True))
        assert {m.__name__: fingerprint(m) for m in protected} == before
        assert Record.objects.count() == 230802 and sha(ROOT/'data/platform.sqlite3') == main_hash
        proof = dict(success=True, native_http=True, roles=results, protected_tables_unchanged=list(before), existing_public_replay_database=True, main_unchanged=True, assets_exact=True, browser_acceptance=False, mobile_acceptance=False, actual_download_acceptance=False)
        (ROOT/'data/object_hub_http.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2)+'\n')
        print(json.dumps(proof,ensure_ascii=False))
    finally:
        child.terminate()
        try:
            child.wait(timeout=10)
        except subprocess.TimeoutExpired:
            child.kill(); child.wait(timeout=10)
        log.close()


if __name__ == '__main__':
    main()
