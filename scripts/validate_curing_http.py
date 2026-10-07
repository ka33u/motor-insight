"""Native HTTP, role/CSRF/source/export checks in an isolated replay only."""
import argparse,hashlib,http.cookiejar,json,os,socket,subprocess,sys,time,urllib.error,urllib.request
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def main():
    parser=argparse.ArgumentParser();parser.add_argument('--project',type=Path,required=True);parser.add_argument('--db',type=Path,required=True);parser.add_argument('--port',type=int,required=True);args=parser.parse_args()
    project=args.project.resolve();db=args.db.resolve();assert db!=ROOT/'data/platform.sqlite3' and db.is_file()
    main_sha=hashlib.sha256((ROOT/'data/platform.sqlite3').read_bytes()).hexdigest();sys.path.insert(0,str(project));os.environ.update(DJANGO_SETTINGS_MODULE='config.settings',MOTOR_SQLITE_PATH=str(db))
    import django;django.setup()
    from django.test import Client
    from django.contrib.auth.models import User
    from app.models import Record,AuditEvent
    from app import curing_data,curing
    with socket.socket() as sock:assert sock.connect_ex(('127.0.0.1',args.port))!=0
    log=(ROOT/'data/curing_http.server.log').open('ab');child=subprocess.Popen([sys.executable,str(project/'manage.py'),'runserver',f'127.0.0.1:{args.port}','--noreload'],cwd=project,env=os.environ.copy(),stdout=log,stderr=subprocess.STDOUT,stdin=subprocess.DEVNULL)
    def fetch(path,data=None,cookie=None,csrf=None,status=200):
        headers={};raw=None
        if data is not None:raw=json.dumps(data,ensure_ascii=False).encode();headers['Content-Type']='application/json'
        if cookie:headers['Cookie']=cookie
        if csrf:headers['X-CSRFToken']=csrf
        req=urllib.request.Request(f'http://127.0.0.1:{args.port}'+path,data=raw,headers=headers)
        try:
            with urllib.request.urlopen(req,timeout=30) as r:code,body,h=r.status,r.read(),dict(r.headers)
        except urllib.error.HTTPError as r:code,body,h=r.code,r.read(),dict(r.headers)
        assert code==status,(path,code,body[:100]);return body,h
    try:
        for _ in range(80):
            assert child.poll() is None
            try:fetch('/api/auth');break
            except urllib.error.URLError:time.sleep(.15)
        else:raise RuntimeError('Native isolated server unavailable')
        html,headers=fetch('/');assert b'curing.css?v=' in html
        csrf=headers['Set-Cookie'].split('csrftoken=')[1].split(';')[0]
        for name in ('curing.js','curing.css','app.js'):assert fetch('/static/'+name)[0]==(project/'static'/name).read_bytes()
        fetch('/api/curing',{},cookie='csrftoken='+csrf,csrf=csrf,status=401)
        facts=list(Record.objects.order_by('dataset','business_key').values_list('dataset','business_key','record_hash'));audit_count=AuditEvent.objects.count()
        expected=curing.scoped(curing_data.load()['result'],curing.filters({}))['summary'];results=[]
        for role in ('admin','analyst','quality','operations','finance','viewer'):
            client=Client();client.force_login(User.objects.get(username='demo_'+role));cookie='sessionid='+client.cookies['sessionid'].value+'; csrftoken='+csrf
            def post(path,data,status=200):return json.loads(fetch(path,data,cookie,csrf,status)[0])
            fetch('/api/curing',{},cookie,status=403)
            d=post('/api/curing',{});assert d['summary']==expected and d['total']==34 and len(d['rows'])==25
            q=dict(scope=d['scope'],receipt=d['receipt']);page2=post('/api/curing',{**q,'page':2});assert len(page2['rows'])==9
            keys={r['run']['id'] for r in d['rows']+page2['rows']};assert len(keys)==34
            key=d['rows'][0]['run']['id'];detail=post('/api/curing/runs/'+key,q);assert detail['total']==38
            for source in detail['sources']:
                record=Record.objects.select_related('source_row__batch').get(dataset=source['dataset'],business_key=source['key'])
                assert record.source_row.row_number==source['row'] and record.source_row.sheet==source['sheet'] and record.record_hash==source['record_hash']
            sources=post('/api/curing/sources',q);all_sources=list(sources['rows'])
            for p in range(2,(sources['total']+39)//40+1):all_sources+=post('/api/curing/sources',{**q,'page':p})['rows']
            assert len(all_sources)==sources['total']==len({(s['dataset'],s['key']) for s in all_sources})
            assert sources['can_download_original']==(role=='admin')
            for fmt in ('json','csv'):
                out=post('/api/curing/export',{**q,'format':fmt});assert 'cents' not in out['text'];assert AuditEvent.objects.latest('id').detail['file_sha256']==hashlib.sha256(out['text'].encode()).hexdigest()
                if fmt=='json':
                    doc=json.loads(out['text']);assert doc['result']['summary']==d['summary'];assert len(doc['result']['rows'])==34;assert len(doc['inputs']['cure_samples'])==1229;assert len(doc['inputs']['cure_runs'])==34
                else:assert '完整所选原始采集' in out['text'] and 'WD-CURE-26-0020-T99-0001' in out['text']
            selected=post('/api/curing',{'scope':{'state':'ready'}});out=post('/api/curing/export',dict(scope=selected['scope'],receipt=selected['receipt']));doc=json.loads(out['text']);assert doc['result']['summary']['runs']==5 and len(doc['inputs']['cure_samples'])==190
            post('/api/curing/export',{**q,'scope':{'state':'ready'}},409)
            empty=post('/api/curing',{'scope':{'q':'NO-SUCH-CYCLE'}});assert empty['total']==0
            results.append(dict(role=role,runs=34,samples=1229,sources=len(all_sources),ready_subset=5,csrf_checked=True))
        assert facts==list(Record.objects.order_by('dataset','business_key').values_list('dataset','business_key','record_hash'))
        assert AuditEvent.objects.count()==audit_count+18
        assert hashlib.sha256((ROOT/'data/platform.sqlite3').read_bytes()).hexdigest()==main_sha
        proof=dict(success=True,roles=results,business_facts_changed=False,all_source_pages=True,all_exports_complete=True,browser_acceptance=False,actual_browser_download=False)
        (ROOT/'data/curing_http.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2)+'\n');print(json.dumps(proof,ensure_ascii=False))
    finally:child.terminate();child.wait(timeout=10);log.close()
if __name__=='__main__':main()
