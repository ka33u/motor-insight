"""Native HTTP verification using only a fresh public Excel replay database."""
import argparse,hashlib,json,os,socket,subprocess,sys,time
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
    from app import wip_trial_data,wip_trial_replay
    facts=list(Record.objects.order_by('dataset','business_key').values_list('dataset','business_key','record_hash'));audit_count=AuditEvent.objects.count()
    expected={(n,policy):wip_trial_data.load(f'WR-261001-{n:03d}',policy)['result'] for n in range(1,9) for policy in ('due','priority')}
    counts=dict(boards=0,details=0,exports=0,source_rows=0);roles=[]
    with socket.socket() as s:assert s.connect_ex(('127.0.0.1',a.port))!=0
    log=(ROOT/'data/wip_trial_http.server.log').open('ab');child=subprocess.Popen([sys.executable,str(ROOT/'manage.py'),'runserver',f'127.0.0.1:{a.port}','--noreload'],cwd=ROOT,env=os.environ.copy(),stdout=log,stderr=subprocess.STDOUT,stdin=subprocess.DEVNULL)
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
        assert fetch('/static/wip_trial.js')[0]==(ROOT/'static/wip_trial.js').read_bytes();fetch('/api/wip-trial',status=401)
        for role in ('admin','analyst','operations','quality','finance','viewer'):
            c=Client();c.force_login(get_user_model().objects.get(username='demo_'+role));cookie='sessionid='+c.cookies['sessionid'].value;allowed=role in ('admin','analyst','operations')
            roles.append(dict(role=role,allowed=allowed));status=200 if allowed else 403
            raw,_=fetch('/api/wip-trial',cookie,status)
            if not allowed:
                for suffix in ('','/sources','/tasks/anything','/export'):fetch('/api/wip-trial/WR-261001-001'+suffix,cookie,403)
                for ds in ('studies','jobs','tasks','materials','supplies'):fetch('/api/records/wip_trial_'+ds,cookie,403)
                continue
            listing=json.loads(raw);assert len(listing['rows'])==8 and listing['rows'][0]['id']=='WR-261001-006'
            for n in range(1,9):
                for policy in ('due','priority'):
                    key=f'WR-261001-{n:03d}';base='/api/wip-trial/'+key;b=json.loads(fetch(base+'?'+urlencode(dict(policy=policy)),cookie)[0]);counts['boards']+=1
                    assert all(b[k]==v for k,v in expected[n,policy].items()),(role,n,policy)
                    q=dict(policy=policy,receipt=b['receipt'])
                    for fmt in ('json','csv'):
                        raw,headers=fetch(base+'/export?'+urlencode(q|dict(format=fmt)),cookie);counts['exports']+=1
                        assert headers.get('Cache-Control')=='no-store' and headers['Content-Disposition'].startswith('attachment;')
                        if fmt=='json':
                            doc=json.loads(raw);assert wip_trial_replay.replay(doc)==doc['result'];assert 'receipt' not in doc
                        else:assert raw.startswith(b'\xef\xbb\xbf') and 'wip_trial_tasks' in raw.decode('utf-8-sig')
                        assert 'hourly_cents' not in raw.decode() and 'unit_cost_cents' not in raw.decode()
                        audit=AuditEvent.objects.latest('id');assert audit.action=='wip_trial.export' and audit.detail['file_sha256']==hashlib.sha256(raw).hexdigest()
                    if n==1 and policy=='due':
                        for task in [b['tasks'][0],next(t for t in b['tasks'] if t['state']=='carried'),next(t for t in b['tasks'] if t['input_state']=='中断待续')]:
                            d=json.loads(fetch(base+'/tasks/'+task['id']+'?'+urlencode(q),cookie)[0]);assert d['row']==task;counts['details']+=1
                        seen=0
                        for page in range(1,100):
                            ev=json.loads(fetch(base+'/sources?'+urlencode(q|dict(page=page)),cookie)[0]);assert ev['can_download_original']==(role=='admin')
                            for s in ev['rows']:
                                r=Record.objects.select_related('source_row__batch').get(dataset=s['dataset'],business_key=s['key']);source=r.source_row
                                assert (s['filename'],s['sheet'],s['row'],s['file_hash'])==(source.batch.filename,source.sheet,source.row_number,source.batch.file_hash);counts['source_rows']+=1;seen+=1
                            if page*ev['size']>=ev['total']:break
                        else:raise AssertionError('incomplete source pages')
                        assert seen==b['source_count']
            fetch(base+'/export?'+urlencode(q|dict(receipt='obsolete')),cookie,409);fetch(base+'/export',cookie,400)
        assert facts==list(Record.objects.order_by('dataset','business_key').values_list('dataset','business_key','record_hash'))
        assert AuditEvent.objects.count()==audit_count+counts['exports'] and sha(ROOT/'data/platform.sqlite3')==protected
        proof=dict(success=True,roles=roles,**counts,facts_unchanged=True,main_database_bytes_unchanged=True,browser_acceptance=False,export_replayed=True)
        (ROOT/'data/wip_trial_http.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2)+'\n');print(json.dumps(proof,ensure_ascii=False))
    finally:
        child.terminate()
        try:child.wait(timeout=10)
        except subprocess.TimeoutExpired:child.kill();child.wait(timeout=10)
        log.close()


if __name__=='__main__':main()
