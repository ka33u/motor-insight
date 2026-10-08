"""Native HTTP checks for task evidence, using an isolated public-Excel database."""
import argparse,csv,hashlib,io,json,os,socket,subprocess,sys,time
import urllib.error,urllib.request
from pathlib import Path
from urllib.parse import urlencode
ROOT=Path(__file__).resolve().parents[1]


def main():
    p=argparse.ArgumentParser();p.add_argument('--db',type=Path,required=True);p.add_argument('--port',type=int,required=True);a=p.parse_args();db=a.db.resolve()
    assert db.is_file() and db!=(ROOT/'data/platform.sqlite3').resolve()
    sha=lambda f:hashlib.sha256(f.read_bytes()).hexdigest();protected=sha(ROOT/'data/platform.sqlite3')
    sys.path.insert(0,str(ROOT));os.environ.update(DJANGO_SETTINGS_MODULE='config.settings',MOTOR_SQLITE_PATH=str(db))
    import django;django.setup()
    from django.test import Client
    from django.contrib.auth import get_user_model
    from app.models import Record,AuditEvent
    from app import wip_trial_data,wip_trial_decision,wip_trial_replay,analytics
    facts=list(Record.objects.order_by('dataset','business_key').values_list('dataset','business_key','record_hash'));audits=AuditEvent.objects.count()
    counts=dict(boards=0,details=0,exports=0,json_replays=0);roles=[]
    with socket.socket() as s:assert s.connect_ex(('127.0.0.1',a.port))!=0
    log=(ROOT/'data/wip_decision_http.server.log').open('ab');child=subprocess.Popen([sys.executable,str(ROOT/'manage.py'),'runserver',f'127.0.0.1:{a.port}','--noreload'],cwd=ROOT,env=os.environ.copy(),stdout=log,stderr=subprocess.STDOUT,stdin=subprocess.DEVNULL)
    def fetch(path,cookie=None,status=200):
        try:
            with urllib.request.urlopen(urllib.request.Request(f'http://127.0.0.1:{a.port}'+path,headers={'Cookie':cookie} if cookie else {}),timeout=60) as r:code,raw,headers=r.status,r.read(),dict(r.headers)
        except urllib.error.HTTPError as r:code,raw,headers=r.code,r.read(),dict(r.headers)
        assert code==status,(path.split('?')[0],code,raw[:180]);return raw,headers
    try:
        for _ in range(80):
            assert child.poll() is None
            try:fetch('/api/auth');break
            except urllib.error.URLError:time.sleep(.15)
        else:raise RuntimeError('local server unavailable')
        assert fetch('/static/wip_trial.js')[0]==(ROOT/'static/wip_trial.js').read_bytes()
        fetch('/api/wip-trial/WR-261001-001/tasks/anything/export',status=401)
        for role in ('admin','analyst','operations','quality','finance','viewer'):
            c=Client();c.force_login(get_user_model().objects.get(username='demo_'+role));cookie='sessionid='+c.cookies['sessionid'].value;allowed=role in ('admin','analyst','operations')
            roles.append(dict(role=role,allowed=allowed))
            if not allowed:
                for suffix in ('/tasks/anything','/tasks/anything/export'):fetch('/api/wip-trial/WR-261001-001'+suffix,cookie,403)
                continue
            for n in (1,2):
                for policy in ('due','priority'):
                    key=f'WR-261001-{n:03}';base='/api/wip-trial/'+key;context=wip_trial_data.load(key,policy)
                    b=json.loads(fetch(base+'?'+urlencode(dict(policy=policy)),cookie)[0]);counts['boards']+=1;q=dict(policy=policy,receipt=b['receipt'])
                    if n==1:
                        selected=[next(t for t in b['tasks'] if t['state']==state) for state in ('completed','carried','scheduled')]
                        selected.append(next(t for t in b['tasks'] if t['input_state']=='中断待续'))
                    else:selected=[next(t for t in b['tasks'] if t['state']=='blocked' and (t['id'] in t['root_tasks'])==root) for root in (True,False)]
                    for task in selected:
                        expected=wip_trial_decision.build(context,task['id'],analytics.AS_OF);path=base+'/tasks/'+task['id']
                        d=json.loads(fetch(path+'?'+urlencode(q),cookie)[0]);assert d['decision']==expected;counts['details']+=1
                        for fmt in ('json','csv'):
                            raw,headers=fetch(path+'/export?'+urlencode(q|dict(format=fmt)),cookie);counts['exports']+=1
                            assert headers.get('Cache-Control')=='no-store' and headers['Content-Disposition'].startswith('attachment;')
                            if fmt=='json':
                                doc=json.loads(raw);assert doc['decision']==expected;assert wip_trial_replay.replay_decision(doc)==expected;counts['json_replays']+=1
                                assert 'receipt' not in doc and doc['sources']==context['sources']
                            else:
                                rows=list(csv.reader(io.StringIO(raw.decode('utf-8-sig'))));i=next(i for i,r in enumerate(rows) if r==['任务派序解释'])
                                row=dict(zip(rows[i+1],rows[i+2]));assert row['task_id']==task['id'];assert json.loads(row['pairs'])==expected['pairs']
                            for forbidden in ('hourly_cents','unit_cost_cents','joint_context'):assert forbidden not in raw.decode()
                            audit=AuditEvent.objects.latest('id');assert audit.action=='wip_trial.export' and audit.detail['file_sha256']==hashlib.sha256(raw).hexdigest()
                            assert audit.detail['task_id']==task['id'] and not audit.detail['business_facts_changed']
                    fetch(path+'/export?'+urlencode(q|dict(receipt='obsolete')),cookie,409);fetch(path+'/export',cookie,400)
        assert facts==list(Record.objects.order_by('dataset','business_key').values_list('dataset','business_key','record_hash'))
        assert AuditEvent.objects.count()==audits+counts['exports'] and sha(ROOT/'data/platform.sqlite3')==protected
        proof=dict(success=True,roles=roles,**counts,facts_unchanged=True,main_database_bytes_unchanged=True,browser_acceptance=False)
        (ROOT/'data/wip_decision_http.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2)+'\n');print(json.dumps(proof,ensure_ascii=False))
    finally:
        child.terminate()
        try:child.wait(timeout=10)
        except subprocess.TimeoutExpired:child.kill();child.wait(timeout=10)
        log.close()


if __name__=='__main__':main()
