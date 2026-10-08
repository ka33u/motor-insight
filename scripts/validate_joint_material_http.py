"""Native HTTP material-ledger validation over a disposable public Excel replay."""
import argparse,hashlib,json,os,socket,subprocess,sys,time
import urllib.error,urllib.request
from pathlib import Path
from decimal import Decimal
from urllib.parse import urlencode,quote
ROOT=Path(__file__).resolve().parents[1]

def oracle(board,report):
    pair=report['balance']['material_id'],report['balance']['unit'];matches=lambda r:(r['material_id'],r['unit'])==pair
    needs=[r for r in board['demands'] if matches(r)];lots=[r for r in board['lots'] if matches(r)];allocations=[r for r in board['reservations'] if matches(r)]
    add=lambda rows,key:sum((Decimal(r[key]) for r in rows),Decimal(0))
    expected=dict(required_qty=add(needs,'required_qty'),reserved_qty=add(allocations,'qty'),unreserved_qty=add(needs,'required_qty')-add(allocations,'qty'),
                  total_supply_qty=add(lots,'qty'),excluded_qty=add(lots,'excluded_qty'),
                  horizon_remaining_qty=add([r for r in lots if r['available_from']<board['resource_study']['horizon_end']],'remaining_qty'),
                  outside_remaining_qty=add([r for r in lots if r['available_from']>=board['resource_study']['horizon_end']],'remaining_qty'))
    assert all(Decimal(report['summary'][k])==v for k,v in expected.items())
    assert {r['id'] for r in report['demands']}=={r['id'] for r in needs} and {r['id'] for r in report['lots']}=={r['id'] for r in lots}
    assert report['summary']['jobs']==len({r['job_id'] for r in needs})
    assert report['summary']['reserved_demands']==sum(r['state']=='reserved' for r in needs)
    assert report['summary']['allocations']==len(allocations)
    for row in report['allocations']:assert {k:v for k,v in row.items() if k!='sequence'}==board['reservations'][row['sequence']-1]
    for job in report['jobs']:
        rows=[r for r in needs if r['job_id']==job['id']]
        assert Decimal(job['required_qty'])==add(rows,'required_qty') and Decimal(job['reserved_qty'])==add(rows,'reserved_qty')
        assert Decimal(job['unreserved_qty'])==add(rows,'required_qty')-add(rows,'reserved_qty')
    for need in report['demands']:
        original=next(r for r in needs if r['id']==need['id'])
        assert set(need['task_ids'])=={t['id'] for t in board['tasks'] if t['job_id']==original['job_id'] and t['route_id']==original['route_id']}

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--db',type=Path,required=True);parser.add_argument('--port',type=int,required=True);parser.add_argument('--write-fixtures',action='store_true');args=parser.parse_args()
    db=args.db.resolve();assert db.is_file() and db!=ROOT/'data/platform.sqlite3'
    sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest();main_hash=sha(ROOT/'data/platform.sqlite3')
    os.environ.update(DJANGO_SETTINGS_MODULE='config.settings',MOTOR_SQLITE_PATH=str(db));sys.path.insert(0,str(ROOT))
    import django;django.setup()
    from django.test import Client
    from django.test.utils import CaptureQueriesContext
    from django.db import connection,reset_queries
    from django.contrib.auth import get_user_model
    from app.models import Record,AuditEvent
    from app.joint_material_evidence import build
    facts=list(Record.objects.order_by('dataset','business_key').values_list('dataset','business_key','record_hash'));audits=AuditEvent.objects.count()
    with socket.socket() as sock:assert sock.connect_ex(('127.0.0.1',args.port))!=0
    log=(ROOT/'data/joint_material_http.server.log').open('ab')
    child=subprocess.Popen([sys.executable,str(ROOT/'manage.py'),'runserver',f'127.0.0.1:{args.port}','--noreload'],cwd=ROOT,env=os.environ.copy(),stdout=log,stderr=subprocess.STDOUT,stdin=subprocess.DEVNULL)
    def fetch(path,cookie=None,status=200):
        req=urllib.request.Request(f'http://127.0.0.1:{args.port}'+path,headers={'Cookie':cookie} if cookie else {})
        try:
            with urllib.request.urlopen(req,timeout=40) as r:code,raw=r.status,r.read()
        except urllib.error.HTTPError as r:code,raw=r.code,r.read()
        assert code==status,(path.split('?')[0],code,raw[:80]);return raw
    def get(path,cookie=None,status=200):return json.loads(fetch(path,cookie,status))
    def check_sources(rows):
        assert len(rows)==len({(r['dataset'],r['key']) for r in rows})
        for s in rows:
            r=Record.objects.select_related('source_row__batch').get(dataset=s['dataset'],business_key=s['key'])
            assert (s['filename'],s['sheet'],s['row'],s['source_row_id'])==(r.source_row.batch.filename,r.source_row.sheet,r.source_row.row_number,r.source_row_id)
    def chosen(board,n):
        if n in (2,5,10):return next(b for b in board['balances'] if Decimal(b['initial_supply_gap_qty'])>0)
        if n==4:
            material=next(l['material_id'] for l in board['lots'] if l['kind']=='未来到料假设');return next(b for b in board['balances'] if b['material_id']==material)
        return board['balances'][0]
    try:
        for _ in range(80):
            assert child.poll() is None
            try:get('/api/auth');break
            except urllib.error.URLError:time.sleep(.15)
        else:raise RuntimeError('Native server unavailable')
        assert '/static/joint_material.js?v=' in fetch('/').decode()
        for name in ('joint_material.js','joint_schedule.js','joint_schedule.css','schedule_reading.js'):assert fetch('/static/'+name)==(ROOT/'static'/name).read_bytes()
        get('/api/joint-schedule/ANY/materials/ANY?unit=kg',status=401)
        results=[];fixtures={};exports=0;offline=0;all_pairs=0;details_count=0;task_count=0
        for role in ('admin','analyst','operations','quality','finance','viewer'):
            client=Client();client.force_login(get_user_model().objects.get(username='demo_'+role));cookie='sessionid='+client.cookies['sessionid'].value
            if role not in ('admin','analyst','operations'):
                get('/api/joint-schedule/MP-261002-002/materials/01.01.0001?unit=kg',cookie,403);results.append(dict(role=role,denied=True));continue
            selected={};details=0;tasks=0;pair_count=0
            for n in range(1,11):
                for policy in ('due','priority'):
                    base=f'/api/joint-schedule/MP-261002-{n:03}';board=get(base+'?policy='+policy,cookie);q=urlencode(dict(policy=policy,receipt=board['receipt']))
                    if board['state']=='paused':get(base+'/materials/ANY?'+q+'&unit=kg',cookie,404);continue
                    reset_queries()
                    with CaptureQueriesContext(connection) as captured:
                        for b in board['balances']:
                            projection,_=build(board,b['material_id'],b['unit']);oracle(board,projection);pair_count+=1
                    assert len(captured)==0
                    if n not in (1,2,4,5,6,10):continue
                    pairs=[chosen(board,n)]
                    if n==1:pairs.append(next(b for b in board['balances'] if b['unit']=='件'))
                    for b in pairs:
                        point=get(base+'/materials/'+quote(b['material_id'],safe='')+'?'+q+'&'+urlencode(dict(unit=b['unit'])),cookie);details+=1
                        projection,refs=build(board,b['material_id'],b['unit']);assert point['evidence']==projection and point['can_download_original']==(role=='admin')
                        assert refs <= {(r['dataset'],r['key']) for r in point['sources']};check_sources(point['sources']);oracle(board,point['evidence'])
                        task=point['evidence']['tasks'][0]['id'];follow=get(base+'/tasks/'+quote(task,safe='')+'?'+q,cookie);tasks+=1
                        assert follow['row']==next(t for t in board['tasks'] if t['id']==task)
                        if policy=='due' and b is pairs[0]:
                            selected[n]=(base,q,board,b,point)
                            if role=='admin':fixtures[str(n)]={k:v for k,v in point.items() if k!='receipt'}
                        if n==1 and b['unit']=='件' and policy=='due' and role=='admin':fixtures['pieces']={k:v for k,v in point.items() if k!='receipt'}
            for n in (2,5,6,10):
                base,q,board,b,point=selected[n];raw=fetch(base+'/export?'+q+'&format=json',cookie);exports+=1;doc=json.loads(raw)
                assert doc['result']['tasks']==board['tasks'] and AuditEvent.objects.latest('id').detail['file_sha256']==hashlib.sha256(raw).hexdigest()
                reset_queries()
                with CaptureQueriesContext(connection) as captured:projection,_=build(doc['result'],b['material_id'],b['unit'])
                assert len(captured)==0 and projection==point['evidence'];offline+=1
            raw=fetch(base+'/export?'+q+'&format=csv',cookie);exports+=1;assert raw.startswith(b'\xef\xbb\xbf') and AuditEvent.objects.latest('id').detail['file_sha256']==hashlib.sha256(raw).hexdigest()
            all_pairs+=pair_count;details_count+=details;task_count+=tasks;results.append(dict(role=role,studies_and_policies=20,material_details=details,task_details=tasks,pair_projections=pair_count,exports=5))
        assert facts==list(Record.objects.order_by('dataset','business_key').values_list('dataset','business_key','record_hash')) and len(facts)==232200
        assert AuditEvent.objects.count()==audits+exports and sha(ROOT/'data/platform.sqlite3')==main_hash
        path=ROOT/'tests/fixtures/joint_material_details.json'
        if args.write_fixtures:path.write_text(json.dumps(fixtures,ensure_ascii=False,indent=2)+'\n')
        else:assert json.loads(path.read_text())==fixtures
        proof=dict(success=True,roles=results,exports=exports,offline_rebuilds=offline,offline_queries=0,all_pair_checks=all_pairs,material_details=details_count,task_details=task_count,main_database_unchanged=True,facts_unchanged=True,source_rows_exact=True,browser_acceptance=False)
        (ROOT/'data/joint_material_http.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2)+'\n');print(json.dumps(proof,ensure_ascii=False),flush=True)
    finally:child.terminate();child.wait(timeout=10);log.close()

if __name__=='__main__':main()
