"""Validate root association over native HTTP against independent sets/counts.

Use a disposable copy of a normal public Excel replay, never the main database.
This script does not perform browser/DOM automation or load new business facts.
"""
import argparse, hashlib, json, os, socket, subprocess, sys, time
import urllib.error, urllib.request
from pathlib import Path
from urllib.parse import urlencode
ROOT=Path(__file__).resolve().parents[1]


def oracle(board):
    if board['state']!='trial':return dict(state='paused',summary=None,rows=[])
    jobs={j['id']:j for j in board['jobs']};tasks={t['id']:t for t in board['tasks']}
    blocked={k for k,t in tasks.items() if t['state']=='blocked'}
    memberships={}
    for key in blocked:
        for root in tasks[key]['root_tasks']:memberships.setdefault(root,set()).add(key)
    affected={tasks[key]['job_id'] for key in blocked}
    multiple={key for key in blocked if len(tasks[key]['root_tasks'])>1}
    rows=[]
    for key,member_ids in memberships.items():
        task=tasks[key];job_ids={tasks[k]['job_id'] for k in member_ids}
        rows.append(dict(id=key,job_id=task['job_id'],process=task['process'],branch=task['branch'],reason=task['reason'],
                         task_ids=sorted(member_ids),job_ids=sorted(job_ids),tasks=len(member_ids),jobs=len(job_ids),
                         batch_qty=sum(jobs[j]['qty'] for j in job_ids),earliest_due=min(jobs[j]['due'] for j in job_ids),
                         overlapping_tasks=len(member_ids & multiple)))
    rows.sort(key=lambda r:(r['earliest_due'],-r['jobs'],-r['tasks'],r['id']))
    return dict(state='blocked' if rows else 'clear',summary=dict(roots=len(rows),tasks=len(blocked),jobs=len(affected),
                batch_qty=sum(jobs[j]['qty'] for j in affected),overlapping_tasks=len(multiple)),rows=rows)


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--db',type=Path,required=True);parser.add_argument('--port',type=int,required=True);parser.add_argument('--node',default='node');args=parser.parse_args()
    db=args.db.resolve();assert db.is_file() and db!=ROOT/'data/platform.sqlite3'
    sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest();main_hash=sha(ROOT/'data/platform.sqlite3')
    os.environ.update(DJANGO_SETTINGS_MODULE='config.settings',MOTOR_SQLITE_PATH=str(db));sys.path.insert(0,str(ROOT))
    import django;django.setup()
    from django.test import Client
    from django.contrib.auth import get_user_model
    from app.models import Record,AuditEvent
    facts=list(Record.objects.order_by('dataset','business_key').values_list('dataset','business_key','record_hash'));audits=AuditEvent.objects.count()
    with socket.socket() as sock:assert sock.connect_ex(('127.0.0.1',args.port))!=0
    log=(ROOT/'data/joint_blockers_http.server.log').open('ab')
    child=subprocess.Popen([sys.executable,str(ROOT/'manage.py'),'runserver',f'127.0.0.1:{args.port}','--noreload'],cwd=ROOT,env=os.environ.copy(),stdout=log,stderr=subprocess.STDOUT,stdin=subprocess.DEVNULL)
    def fetch(path,cookie=None,status=200):
        req=urllib.request.Request(f'http://127.0.0.1:{args.port}'+path,headers={'Cookie':cookie} if cookie else {})
        try:
            with urllib.request.urlopen(req,timeout=40) as r:code,raw=r.status,r.read()
        except urllib.error.HTTPError as r:code,raw=r.code,r.read()
        assert code==status,(path.split('?')[0],code,raw[:80]);return raw
    def get(path,cookie=None,status=200):return json.loads(fetch(path,cookie,status))
    def exact_sources(rows):
        pairs={(r['dataset'],r['key']) for r in rows};assert len(pairs)==len(rows)
        for s in rows:
            r=Record.objects.select_related('source_row__batch').get(dataset=s['dataset'],business_key=s['key'])
            assert (s['filename'],s['sheet'],s['row'],s['source_row_id'])==(r.source_row.batch.filename,r.source_row.sheet,r.source_row.row_number,r.source_row_id)
    try:
        for _ in range(80):
            assert child.poll() is None
            try:get('/api/auth');break
            except urllib.error.URLError:time.sleep(.15)
        else:raise RuntimeError('Native server unavailable')
        for name in ('joint_blockers.js','joint_schedule.js'):assert fetch('/static/'+name)==(ROOT/'static'/name).read_bytes()
        get('/api/joint-schedule',status=401);cases=[];results=[];exports=0;root_details=0
        for role in ('admin','analyst','operations','quality','finance','viewer'):
            client=Client();client.force_login(get_user_model().objects.get(username='demo_'+role));cookie='sessionid='+client.cookies['sessionid'].value
            if role not in ('admin','analyst','operations'):
                get('/api/joint-schedule/MP-261002-006',cookie,403);results.append(dict(role=role,denied=True));continue
            selected={};details=0
            for n in range(1,11):
                for policy in ('due','priority'):
                    base=f'/api/joint-schedule/MP-261002-{n:03}';board=get(base+'?policy='+policy,cookie);expected=oracle(board)
                    cases.append(dict(key=f'{role}:{n}:{policy}',result=board,expected=expected))
                    if n in (5,6) and policy=='due':
                        fixture=json.loads((ROOT/f'tests/fixtures/joint_blocker_board_{n:03}_due.json').read_text());assert all(board[k]==v for k,v in fixture.items())
                        q=urlencode(dict(policy=policy,receipt=board['receipt']));selected[n]=(base,q,board)
                        for row in expected['rows']:
                            for identity in (row['id'],next(t for t in row['task_ids'] if t!=row['id'])):
                                detail=get(base+'/tasks/'+identity+'?'+q,cookie)
                                assert detail['row']==next(t for t in board['tasks'] if t['id']==identity)
                                assert row['id'] in detail['row']['root_tasks'] and detail['can_download_original']==(role=='admin')
                                assert any(t['id']==row['id'] for t in detail['candidate_evidence']['root_tasks'])
                                exact_sources(detail['sources']);details+=1
            for n,(base,q,board) in selected.items():
                raw=fetch(base+'/export?'+q+'&format=json',cookie);doc=json.loads(raw);exports+=1
                assert doc['result']['tasks']==board['tasks'] and doc['result']['jobs']==board['jobs']
                assert AuditEvent.objects.latest('id').detail['file_sha256']==hashlib.sha256(raw).hexdigest()
                cases.append(dict(key=f'{role}:{n}:export',result=doc['result'],expected=oracle(board)))
                if n==6:
                    raw=fetch(base+'/export?'+q+'&format=csv',cookie);exports+=1;assert raw.startswith(b'\xef\xbb\xbf')
                    assert AuditEvent.objects.latest('id').detail['file_sha256']==hashlib.sha256(raw).hexdigest()
                    sources=[]
                    for page in range(1,(board['source_count']+39)//40+1):sources+=get(base+'/sources?'+q+'&page='+str(page),cookie)['rows']
                    assert len(sources)==board['source_count']==2014;exact_sources(sources)
            root_details+=details;results.append(dict(role=role,studies_and_policies=20,root_and_member_details=details,sources=2014,exports=3))
        node=subprocess.run([args.node,str(ROOT/'scripts/verify_joint_blocker_results.mjs')],input=json.dumps(cases),text=True,capture_output=True,check=True,cwd=ROOT)
        cross=json.loads(node.stdout);assert cross['success'] and cross['cases']==66
        assert facts==list(Record.objects.order_by('dataset','business_key').values_list('dataset','business_key','record_hash'))
        assert len(facts)==232200 and AuditEvent.objects.count()==audits+exports and sha(ROOT/'data/platform.sqlite3')==main_hash
        proof=dict(success=True,roles=results,exports=exports,root_and_member_details=root_details,cross_language=cross,main_database_unchanged=True,facts_unchanged=True,source_rows_exact=True,browser_acceptance=False)
        (ROOT/'data/joint_blockers_http.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2)+'\n');print(json.dumps(proof,ensure_ascii=False),flush=True)
    finally:child.terminate();child.wait(timeout=10);log.close()

if __name__=='__main__':main()
