"""Ten synthetic studies over actual HTTP, on a copy of the public Excel replay."""
import argparse,hashlib,json,os,socket,subprocess,sys,time,urllib.error,urllib.request
from pathlib import Path
from urllib.parse import urlencode
ROOT=Path(__file__).resolve().parents[1]
def main():
    parser=argparse.ArgumentParser();parser.add_argument('--db',type=Path,required=True);parser.add_argument('--port',type=int,required=True);args=parser.parse_args();db=args.db.resolve();assert db.is_file() and db!=ROOT/'data/platform.sqlite3'
    sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest();main_sha=sha(ROOT/'data/platform.sqlite3');sys.path.insert(0,str(ROOT));os.environ.update(DJANGO_SETTINGS_MODULE='config.settings',MOTOR_SQLITE_PATH=str(db))
    import django;django.setup()
    from django.test import Client
    from django.contrib.auth.models import User
    from app.models import Record,AuditEvent
    from app import joint_schedule_data,finite_schedule
    facts=list(Record.objects.order_by('dataset','business_key').values_list('dataset','business_key','record_hash'));audits=AuditEvent.objects.count()
    with socket.socket() as sock:assert sock.connect_ex(('127.0.0.1',args.port))!=0
    log=(ROOT/'data/joint_compare_http.server.log').open('ab');child=subprocess.Popen([sys.executable,str(ROOT/'manage.py'),'runserver',f'127.0.0.1:{args.port}','--noreload'],cwd=ROOT,env=os.environ.copy(),stdout=log,stderr=subprocess.STDOUT,stdin=subprocess.DEVNULL)
    def fetch(path,data=None,cookie=None,csrf=None,status=200):
        headers={};raw=None
        if data is not None:raw=json.dumps(data,ensure_ascii=False).encode();headers['Content-Type']='application/json'
        if cookie:headers['Cookie']=cookie
        if csrf:headers['X-CSRFToken']=csrf
        try:
            with urllib.request.urlopen(urllib.request.Request(f'http://127.0.0.1:{args.port}'+path,data=raw,headers=headers),timeout=60) as r:code,raw,h=r.status,r.read(),dict(r.headers)
        except urllib.error.HTTPError as r:code,raw,h=r.code,r.read(),dict(r.headers)
        assert code==status,(path.split('?')[0],code,raw[:120]);return raw,h
    try:
        for _ in range(80):
            assert child.poll() is None
            try:fetch('/api/auth');break
            except urllib.error.URLError:time.sleep(.15)
        else:raise RuntimeError('Native server unavailable')
        html,headers=fetch('/');assert b'joint_compare.css?v=' in html;csrf=headers['Set-Cookie'].split('csrftoken=')[1].split(';')[0]
        for name in ('joint_compare.js','joint_compare.css','joint_schedule.js'):assert fetch('/static/'+name)[0]==(ROOT/'static'/name).read_bytes()
        base='/api/joint-comparison/MP-261002-001';fetch(base,{},'csrftoken='+csrf,csrf,401);results=[];examples={};original_hashes={};total_exports=0
        for role in ('admin','analyst','operations','quality','finance','viewer'):
            client=Client();client.force_login(User.objects.get(username='demo_'+role));cookie='sessionid='+client.cookies['sessionid'].value+'; csrftoken='+csrf
            def post(path,value=None,status=200):
                raw,h=fetch(path,value or {},cookie,csrf,status)
                if status==200:assert h['Cache-Control']=='no-store'
                return json.loads(raw)
            fetch(base,{},cookie,status=403)
            if role not in ('admin','analyst','operations'):
                for suffix in ('','/sources','/tasks/ANY','/export'):post(base+suffix,{'receipt':'untrusted'},403)
                results.append(dict(role=role,denied=True));continue
            studies=[]
            for n in range(1,11):
                key=f'MP-261002-{n:03}';path='/api/joint-comparison/'+key;d=post(path);assert d['state']==('paused' if n in (7,8,9) else 'compared')
                for policy,side in [('due','left'),('priority','right')]:
                    original=json.loads(fetch('/api/joint-schedule/'+key+'?'+urlencode(dict(policy=policy,receipt=d['policy_receipts'][policy])),cookie=cookie)[0])
                    assert original['summary']==d['columns'][policy]['summary']
                    if d['summary']:
                        assert {r['id']:r[side] for r in d['jobs']}=={r['id']:r for r in original['jobs']}
                        assert {r['id']:r[side] for r in d['tasks']}=={r['id']:r for r in original['tasks']}
                        assert d['summary']['jobs']==6 and d['summary']['qty']==50 and d['summary']['tasks']==198
                    if role=='admin':original_hashes[key+'/'+policy]=finite_schedule.digest(joint_schedule_data.load(key,policy)['result'])
                if role=='admin':
                    examples[key]=dict(state=d['state'],summary=d['summary'],columns=d['columns'])
                    if n==3:(ROOT/'data/joint_compare_example.json').write_text(json.dumps(d,ensure_ascii=False)+'\n')
                studies.append(dict(study=key,state=d['state']))
            d=post(base);detail=post(base+'/tasks/'+d['tasks'][0]['id'],dict(receipt=d['receipt']));assert detail['task']==d['tasks'][0]
            sources=[]
            pages=range(1,(d['source_count']+39)//40+1) if role=='admin' else [1]
            for page in pages:sources+=post(base+'/sources',dict(receipt=d['receipt'],page=page))['rows']
            for s in sources:
                r=Record.objects.select_related('source_row__batch').get(dataset=s['dataset'],business_key=s['key']);assert (s['row'],s['sheet'],s['filename'])==(r.source_row.row_number,r.source_row.sheet,r.source_row.batch.filename)
            if role=='admin':assert len(sources)==len({(r['dataset'],r['key']) for r in sources})==d['source_count']
            for fmt in ('json','csv'):
                out=post(base+'/export',dict(receipt=d['receipt'],format=fmt));total_exports+=1;assert AuditEvent.objects.latest('id').detail['file_sha256']==hashlib.sha256(out['text'].encode()).hexdigest();assert 'hourly_cents' not in out['text'] and d['receipt'] not in out['text']
                if fmt=='json':
                    doc=json.loads(out['text']);assert len(doc['comparison']['tasks'])==198 and len(doc['left']['material_inputs']['joint_demands'])==54 and len(doc['right']['resource_inputs']['schedule_tasks'])==198
                else:assert '两列共同来源' in out['text']
            paused=post('/api/joint-comparison/MP-261002-007');doc=json.loads(post('/api/joint-comparison/MP-261002-007/export',dict(receipt=paused['receipt']))['text']);total_exports+=1;assert doc['comparison']['summary'] is None and len(doc['left']['resource_inputs']['schedule_tasks'])==198
            results.append(dict(role=role,studies=len(studies),sources_checked=len(sources),all_calculator_outputs_equal=True))
        for key,value in original_hashes.items():
            study,policy=key.split('/');assert finite_schedule.digest(joint_schedule_data.load(study,policy)['result'])==value
        assert facts==list(Record.objects.order_by('dataset','business_key').values_list('dataset','business_key','record_hash'));assert AuditEvent.objects.count()==audits+total_exports;assert sha(ROOT/'data/platform.sqlite3')==main_sha
        proof=dict(success=True,roles=results,examples=examples,exports=total_exports,old_policy_results=20,source_facts_unchanged=True,main_database_bytes_unchanged=True,browser_acceptance=False)
        (ROOT/'data/joint_compare_http.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2)+'\n');print(json.dumps({k:v for k,v in proof.items() if k!='examples'},ensure_ascii=False))
    finally:child.terminate();child.wait(timeout=10);log.close()
if __name__=='__main__':main()
