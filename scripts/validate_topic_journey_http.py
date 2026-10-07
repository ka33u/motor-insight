"""Exercise existing public-demo topics through isolated native HTTP, not a browser."""
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
    from app import topic_workspace as ws, topic_journey as journey
    from app.models import Record, AnalysisModel, Topic, TopicView, TopicPage, TopicPageVersion, TopicSnapshot, MetricVersion, AuditEvent
    protected = [Record, AnalysisModel, Topic, TopicView, TopicPage, TopicPageVersion, TopicSnapshot, MetricVersion, AuditEvent]
    fingerprint = lambda model: ws.digest(list(model.objects.order_by('pk').values()))
    before = {model.__name__: fingerprint(model) for model in protected}
    with socket.socket() as sock:
        assert sock.connect_ex(('127.0.0.1', args.port)) != 0
    log = (ROOT/'data/topic_journey_http.server.log').open('ab')
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
        assert 'topic_journey.js?v=' in fetch('/')[0].decode()
        for name in ('topic_journey.js', 'topics.js', 'app.js'):
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
                if '/journey/' in path and status == 200:
                    assert headers['Cache-Control'] == 'no-store'
                return json.loads(raw)
            contexts = [ws.context(user, topic.pk) for topic in ws.visible(user, Topic.objects.order_by('id'))]
            ready = [ctx for ctx in contexts if ctx['cards'] and all(c['ready'] for c in [journey.inspect_card(user, card, journey.defaults()) for card in ctx['cards']])]
            assert len(ready) >= 2
            source, target = ready[0], ready[1]
            source_id, target_id = source['topic']['id'], target['topic']['id']
            root = f'/api/topics/{source_id}/journey/'
            config = dict(journey.defaults(), primary_label='临时当前范围', reference_label='未启用的对照名称')
            body = dict(target_id=target_id, context_token=source['context_token'], config=config)
            preview = post(root+'preview', body)
            assert next(o for o in preview['options'] if o['mode']=='inherit')['allowed']
            assert not next(o for o in preview['options'] if o['mode']=='objects')['allowed']
            baseline = post(f'/api/topics/{target_id}/run', dict(config=config, context_token=target['context_token']))
            opened = post(root+'open', dict(**body, mode='inherit', receipt=preview['receipt']))
            arrived = post(f'/api/topics/{target_id}/journey/resolve', dict(receipt=opened['receipt'], direction='forward'))
            assert arrived['config'] == config
            current = post(f'/api/topics/{target_id}/run', {k: arrived[k] for k in ('config','context_token')})
            assert current['cards'] == baseline['cards']
            returned = post(root+'resolve', dict(receipt=opened['receipt'], direction='return'))
            assert returned['config'] == config and returned['context_token'] == source['context_token']
            post(root+'resolve', dict(receipt=opened['receipt'], direction='forward'), 400)
            post(root+'open', dict(**body, mode='inherit', receipt=preview['receipt']+'x'), 409)
            post(root+'open', dict(**body, mode='objects', receipt=preview['receipt']), 400)
            reset = post(root+'open', dict(**body, mode='new', receipt=preview['receipt']))
            assert post(f'/api/topics/{target_id}/journey/resolve', dict(receipt=reset['receipt'],direction='forward'))['config'] == journey.defaults()
            # Existing real topic layouts expose different business date roles.
            pair = next((a,b) for a in ready for b in ready if a!=b and journey.date_roles(a)!=journey.date_roles(b))
            a,b = pair
            date_body = dict(target_id=b['topic']['id'], context_token=a['context_token'], config=dict(config,scope={'from':'2026-09-24','to':'2026-09-25'}))
            dated = post(f'/api/topics/{a["topic"]["id"]}/journey/preview',date_body)
            assert not next(o for o in dated['options'] if o['mode']=='inherit')['allowed']
            fetch(root+'preview', body=body, status=403)  # CSRF protection precedes authentication.
            results.append(dict(role=role, source=source_id, target=target_id, cards=len(current['cards']), numeric_results_equal=True, original_scope_restored=True, date_role_mismatch_blocked=True))
        assert {m.__name__: fingerprint(m) for m in protected} == before
        assert Record.objects.count() == 230802 and sha(ROOT/'data/platform.sqlite3') == main_hash
        proof = dict(success=True, native_http=True, roles=results, protected_tables_unchanged=list(before), existing_public_replay_database=True, main_unchanged=True, assets_exact=True, browser_acceptance=False, mobile_acceptance=False, actual_download_acceptance=False)
        (ROOT/'data/topic_journey_http.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2)+'\n')
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
