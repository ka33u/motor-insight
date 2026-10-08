"""Native HTTP validation of candidate evidence on an isolated public Excel replay."""
import argparse, hashlib, json, os, socket, subprocess, sys, time
import urllib.error, urllib.request
from pathlib import Path
from urllib.parse import urlencode
ROOT=Path(__file__).resolve().parents[1]

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--db',type=Path,required=True);parser.add_argument('--port',type=int,required=True);parser.add_argument('--write-fixtures',action='store_true');args=parser.parse_args()
    db=args.db.resolve();assert db.is_file() and db!=ROOT/'data/platform.sqlite3'
    sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest();main_hash=sha(ROOT/'data/platform.sqlite3')
    os.environ.update(DJANGO_SETTINGS_MODULE='config.settings',MOTOR_SQLITE_PATH=str(db));sys.path.insert(0,str(ROOT))
    import django;django.setup()
    from django.test import Client
    from django.test.utils import CaptureQueriesContext
    from django.db import connection, reset_queries
    from django.contrib.auth import get_user_model
    from app.models import Record,AuditEvent
    from app.joint_candidate_evidence import build
    facts=list(Record.objects.order_by('dataset','business_key').values_list('dataset','business_key','record_hash'));audits=AuditEvent.objects.count()
    with socket.socket() as sock:assert sock.connect_ex(('127.0.0.1',args.port))!=0
    log=(ROOT/'data/joint_candidates_http.server.log').open('ab')
    child=subprocess.Popen([sys.executable,str(ROOT/'manage.py'),'runserver',f'127.0.0.1:{args.port}','--noreload'],cwd=ROOT,env=os.environ.copy(),stdout=log,stderr=subprocess.STDOUT,stdin=subprocess.DEVNULL)
    def fetch(path,cookie=None,status=200):
        req=urllib.request.Request(f'http://127.0.0.1:{args.port}'+path,headers={'Cookie':cookie} if cookie else {})
        try:
            with urllib.request.urlopen(req,timeout=40) as r:code,raw,headers=r.status,r.read(),dict(r.headers)
        except urllib.error.HTTPError as r:code,raw,headers=r.code,r.read(),dict(r.headers)
        assert code==status,(path.split('?')[0],code,raw[:80]);return raw,headers
    def get(path,cookie=None,status=200):return json.loads(fetch(path,cookie,status)[0])
    def check_sources(rows):
        assert len(rows)==len({(s['dataset'],s['key']) for s in rows})
        for s in rows:
            r=Record.objects.select_related('source_row__batch').get(dataset=s['dataset'],business_key=s['key'])
            assert (s['filename'],s['sheet'],s['row'],s['source_row_id'])==(r.source_row.batch.filename,r.source_row.sheet,r.source_row.row_number,r.source_row_id)
    def check_candidates(board,detail):
        task=detail['row'];d=detail['candidate_evidence'];assert d['task_id']==task['id'];refs={(s['dataset'],s['key']) for s in detail['sources']}
        assert {r['id'] for r in d['resource_options']}==set(Record.objects.filter(dataset='schedule_options',values__task_id=task['id']).values_list('business_key',flat=True))
        assert {r['id'] for r in d['people_candidates']}==set(Record.objects.filter(dataset='crew_candidates',values__study_id=board['crew_study']['id'],values__task_id=task['id']).values_list('business_key',flat=True))
        for option in d['resource_options']:
            resource=Record.objects.get(dataset='production_resources',business_key=option['resource_id']).values
            assert option['max_batch_qty']==resource['max_batch_qty'] and option['batch_fits']==(task['qty']<=resource['max_batch_qty'])
            assert option['selected']==(option['id']==task['option_id']);assert ('schedule_options',option['id']) in refs
        qualifications={q['id']:q for q in board['credentials']}
        for candidate in d['people_candidates']:
            q=qualifications[candidate['credential_id']]
            for key in ('employee_id','skill_id','eligible','effective_from','effective_until','reason'):assert candidate[key]==q[key]
            assert candidate['selected']==(candidate['id']==task['candidate_id'])
            for pair in [('crew_candidates',candidate['id']),('crew_credentials',q['id']),('employees',q['employee_id']),('skills',q['skill_id'])]:assert pair in refs
        for ds,identity,ids,study in [('schedule_windows','resource_id',{r['resource_id'] for r in d['resource_options']},board['resource_study']['id']),('schedule_blocks','resource_id',{r['resource_id'] for r in d['resource_options']},board['resource_study']['id']),('crew_windows','employee_id',{r['employee_id'] for r in d['people_candidates']},board['crew_study']['id']),('crew_blocks','employee_id',{r['employee_id'] for r in d['people_candidates']},board['crew_study']['id'])]:
            raw=list(Record.objects.filter(dataset=ds,values__study_id=study).values_list('values',flat=True));expected={r['id']:r for r in raw if r[identity] in ids}
            assert {r['id'] for r in d[ds]}==set(expected)
            for row in d[ds]:
                assert all(expected[row['id']][k]==v for k,v in row.items());assert (ds,row['id']) in refs
        for kind in ('predecessors','root_tasks'):
            assert [r['id'] for r in d[kind]]==task[kind]
            for row in d[kind]:
                original=next(t for t in board['tasks'] if t['id']==row['id']);assert all(original[k]==v for k,v in row.items());assert ('schedule_tasks',row['id']) in refs
        assert not any(word in json.dumps(d) for word in ('hourly_cents','price_cents','phone','salary'))
        check_sources(detail['sources'])
    try:
        for _ in range(80):
            assert child.poll() is None
            try:get('/api/auth');break
            except urllib.error.URLError:time.sleep(.15)
        else:raise RuntimeError('Native server unavailable')
        assert '/static/joint_candidates.js?v=' in fetch('/')[0].decode()
        for name in ('joint_candidates.js','schedule_reading.js','joint_schedule.js'):assert fetch('/static/'+name)[0]==(ROOT/'static'/name).read_bytes()
        get('/api/joint-schedule',status=401);fixtures={};results=[];exports=0;rebuilt=0
        for role in ('admin','analyst','operations','quality','finance','viewer'):
            client=Client();client.force_login(get_user_model().objects.get(username='demo_'+role));cookie='sessionid='+client.cookies['sessionid'].value
            if role not in ('admin','analyst','operations'):
                get('/api/joint-schedule/MP-261002-001/tasks/ANY',cookie,403);results.append(dict(role=role,denied=True));continue
            checked=0;selected={}
            for n in range(1,11):
                for policy in ('due','priority'):
                    base=f'/api/joint-schedule/MP-261002-{n:03}';board=get(base+'?policy='+policy,cookie)
                    q=urlencode(dict(policy=policy,receipt=board['receipt']))
                    assert board['state']==('paused' if n in (7,8,9) else 'trial')
                    if n==2 and policy=='due':
                        fixture=json.loads((ROOT/'tests/fixtures/joint_candidate_board_002_due.json').read_text())
                        assert all(board[k]==v for k,v in fixture.items())
                    if not board['tasks']:
                        get(base+'/tasks/ANY?'+q,cookie,404);continue
                    task=next((t for t in board['tasks'] if t['state']=='blocked'),board['tasks'][0])
                    point=get(base+'/tasks/'+task['id']+'?'+q,cookie);assert point['row']==task and point['can_download_original']==(role=='admin')
                    check_candidates(board,point);checked+=1
                    if policy=='due' and n in (1,2,6):
                        selected[n]=(base,q,board,point)
                        if role=='admin':fixtures[{1:'scheduled',2:'shortage',6:'no_window'}[n]]={k:v for k,v in point.items() if k!='receipt'}
                        if n==2:
                            downstream=next(t for t in board['tasks'] if t['state']=='blocked' and t['root_tasks'] and t['id'] not in t['root_tasks'])
                            linked=get(base+'/tasks/'+downstream['id']+'?'+q,cookie);check_candidates(board,linked);checked+=1
                            for root in linked['candidate_evidence']['root_tasks']:
                                follow=get(base+'/tasks/'+root['id']+'?'+q,cookie);assert follow['row']['id']==root['id'];check_candidates(board,follow)
                            if role=='admin':fixtures['downstream']={k:v for k,v in linked.items() if k!='receipt'}
            base,q,board,point=selected[1];rows=[]
            for page in range(1,(board['source_count']+39)//40+1):rows+=get(base+'/sources?'+q+'&page='+str(page),cookie)['rows']
            assert len(rows)==board['source_count']==2030;check_sources(rows)
            for n in (1,2,6):
                base,q,board,point=selected[n]
                raw,_=fetch(base+'/export?'+q+'&format=json',cookie);doc=json.loads(raw);exports+=1
                assert doc['result']['tasks']==board['tasks'] and AuditEvent.objects.latest('id').detail['file_sha256']==hashlib.sha256(raw).hexdigest()
                replay=dict(result=doc['result'],references=doc['references'],parent=dict(tables=doc['crew_inputs'],base=dict(tables=doc['resource_inputs'])))
                reset_queries()  # Avoid the debug query log cap hiding a query delta.
                with CaptureQueriesContext(connection) as captured:copy,_=build(replay,point['row'])
                assert len(captured)==0 and copy==point['candidate_evidence'];rebuilt+=1
            raw,_=fetch(base+'/export?'+q+'&format=csv',cookie);exports+=1;assert raw.startswith(b'\xef\xbb\xbf')
            assert AuditEvent.objects.latest('id').detail['file_sha256']==hashlib.sha256(raw).hexdigest()
            results.append(dict(role=role,policies_and_studies=20,details_checked=checked,sources=2030,exports=4,offline_rebuilds=3))
        assert facts==list(Record.objects.order_by('dataset','business_key').values_list('dataset','business_key','record_hash'))
        assert len(facts)==232200 and AuditEvent.objects.count()==audits+exports and sha(ROOT/'data/platform.sqlite3')==main_hash
        p=ROOT/'tests/fixtures/joint_candidate_details.json'
        if args.write_fixtures:p.write_text(json.dumps(fixtures,ensure_ascii=False,indent=2)+'\n')
        else:assert json.loads(p.read_text())==fixtures
        proof=dict(success=True,roles=results,exports=exports,offline_rebuilds=rebuilt,offline_rebuild_queries=0,main_database_unchanged=True,facts_unchanged=True,source_rows_exact=True,browser_acceptance=False)
        (ROOT/'data/joint_candidates_http.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2)+'\n');print(json.dumps(proof,ensure_ascii=False),flush=True)
    finally:child.terminate();child.wait(timeout=10);log.close()

if __name__=='__main__':main()
