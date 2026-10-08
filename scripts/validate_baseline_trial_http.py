"""Frozen BOM studies over actual HTTP, on a copy of the public Excel replay."""
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
    from app import joint_schedule_data,order_baseline_data,baseline_trial_data,finite_schedule
    facts=list(Record.objects.order_by('dataset','business_key').values_list('dataset','business_key','record_hash'));audits=AuditEvent.objects.count()
    with socket.socket() as sock:assert sock.connect_ex(('127.0.0.1',args.port))!=0
    log=(ROOT/'data/baseline_trial_http.server.log').open('ab');child=subprocess.Popen([sys.executable,str(ROOT/'manage.py'),'runserver',f'127.0.0.1:{args.port}','--noreload'],cwd=ROOT,env=os.environ.copy(),stdout=log,stderr=subprocess.STDOUT,stdin=subprocess.DEVNULL)
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
        html,headers=fetch('/');assert b'baseline_trial.css?v=' in html;csrf=headers['Set-Cookie'].split('csrftoken=')[1].split(';')[0]
        for name in ('baseline_trial.js','baseline_trial.css','order_baseline.js'):assert fetch('/static/'+name)[0]==(ROOT/'static'/name).read_bytes()
        base='/api/baseline-trial/OB-261001-001';fetch(base,{},'csrftoken='+csrf,csrf,401)
        results=[];examples={};old_results={};total_exports=0;source_count=0
        for n in range(1,11):
            for policy in ('due','priority'):
                key=f'OB-261001-{n:03}'
                d=order_baseline_data.load(key,policy)
                old_results[key,policy]=(finite_schedule.digest(d['result']),finite_schedule.digest(d['parent']['result']))
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
            for n in range(1,11):
                key=f'OB-261001-{n:03}';path='/api/baseline-trial/'+key
                for policy in ('due','priority'):
                    d=post(path,dict(policy=policy));assert d['state']==('paused' if n in (5,6,7,9,10) else 'trial'),(key,policy,d['issues'])
                    assert d['history_verified'] is False
                    if d['trial']:
                        assert d['trial']['summary']['jobs']==6 and d['trial']['summary']['qty']==50
                        assert len(d['trial']['demands'])==54
                        if n==1:assert all(x['delta_minutes']==0 for x in d['comparison']['jobs'])
                        if n==8:
                            first=d['trial']['demands'][0];assert first['required_qty']=='50.134' and first['unit']=='kg'
                            material=next(m for m in d['comparison']['materials'] if m['material_id']==first['material_id'] and m['unit']=='kg')
                            assert material['delta_qty']=='-5.57'
                    else:assert not d['comparison']['available']
                    if role=='admin':examples[key+'/'+policy]=dict(state=d['state'],summary=d['trial']['summary'] if d['trial'] else None,issues=d['issues'],comparison=d['comparison'])
            d=post(base);detail=post(base+'/tasks/'+d['trial']['tasks'][0]['id'],dict(receipt=d['receipt']));assert detail['task']==d['trial']['tasks'][0]
            sources=[];pages=range(1,(d['source_count']+39)//40+1) if role=='admin' else [1]
            for page in pages:sources+=post(base+'/sources',dict(receipt=d['receipt'],page=page))['rows']
            for src in sources:
                row=Record.objects.select_related('source_row__batch').get(dataset=src['dataset'],business_key=src['key'])
                assert (src['row'],src['sheet'],src['filename'],src['source_row_id'])==(row.source_row.row_number,row.source_row.sheet,row.source_row.batch.filename,row.source_row_id)
            if role=='admin':assert len(sources)==len({(r['dataset'],r['key']) for r in sources})==d['source_count'];source_count=len(sources)
            for fmt in ('json','csv'):
                out=post(base+'/export',dict(receipt=d['receipt'],format=fmt));total_exports+=1
                assert AuditEvent.objects.latest('id').detail['file_sha256']==hashlib.sha256(out['text'].encode()).hexdigest()
                for denied in ('hourly_cents','unit_cost_cents','unit_price_cents',d['receipt']):assert denied not in out['text']
                if fmt=='json':
                    doc=json.loads(out['text']);assert len(doc['result']['trial']['tasks'])==198
                    assert len(doc['baseline_inputs']['order_baseline_bom'])==54 and len(doc['current_trial']['resource_inputs']['schedule_tasks'])==198
                    assert set(doc['planning_references'])=={'employees','skills','routes','route_dependencies','production_resources'}
                    reconstructed=baseline_trial_data.load('OB-261001-001')['result'];assert doc['result']==reconstructed
                else:assert out['text'].startswith('\ufeff') and 'planning_references/skills' in out['text']
            paused=post('/api/baseline-trial/OB-261001-009');doc=json.loads(post('/api/baseline-trial/OB-261001-009/export',dict(receipt=paused['receipt']))['text']);total_exports+=1
            assert doc['result']['trial'] is None and len(doc['baseline_inputs']['order_baseline_bom'])==54
            results.append(dict(role=role,studies=10,policies=2,sources_checked=len(sources)))
        for (key,policy),value in old_results.items():
            d=order_baseline_data.load(key,policy);assert (finite_schedule.digest(d['result']),finite_schedule.digest(d['parent']['result']))==value
        assert facts==list(Record.objects.order_by('dataset','business_key').values_list('dataset','business_key','record_hash'))
        assert AuditEvent.objects.count()==audits+total_exports;assert sha(ROOT/'data/platform.sqlite3')==main_sha
        proof=dict(success=True,roles=results,examples=examples,exports=total_exports,source_count=source_count,old_baseline_results=20,old_joint_results=20,
                   source_facts_unchanged=True,main_database_bytes_unchanged=True,browser_acceptance=False)
        (ROOT/'data/baseline_trial_http.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2)+'\n')
        print(json.dumps({k:v for k,v in proof.items() if k!='examples'},ensure_ascii=False))
    finally:child.terminate();child.wait(timeout=10);log.close()
if __name__=='__main__':main()
