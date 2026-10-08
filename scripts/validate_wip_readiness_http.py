"""Check native HTTP against an isolated database made by public Excel replay."""
import argparse,csv,hashlib,io,json,os,socket,subprocess,sys,time
import urllib.error,urllib.request
from pathlib import Path
from urllib.parse import urlencode
ROOT=Path(__file__).resolve().parents[1]

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--db',type=Path,required=True);parser.add_argument('--port',type=int,required=True);args=parser.parse_args()
    db=args.db.resolve();assert db.is_file() and db!=(ROOT/'data/platform.sqlite3').resolve()
    sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest();main_hash=sha(ROOT/'data/platform.sqlite3')
    sys.path.insert(0,str(ROOT));os.environ.update(DJANGO_SETTINGS_MODULE='config.settings',MOTOR_SQLITE_PATH=str(db))
    import django;django.setup()
    from django.test import Client
    from django.contrib.auth import get_user_model
    from app.models import Record,AuditEvent
    from app import wip_readiness as engine
    from validate_wip_readiness import verify
    independent=verify();expected,rev=engine.current()
    facts=list(Record.objects.order_by('dataset','business_key').values_list('dataset','business_key','record_hash'))
    audits=AuditEvent.objects.count();counts=dict(boards=0,details=0,exports=0,source_rows=0)
    with socket.socket() as s:assert s.connect_ex(('127.0.0.1',args.port))!=0
    log=(ROOT/'data/wip_readiness_http.server.log').open('ab')
    child=subprocess.Popen([sys.executable,str(ROOT/'manage.py'),'runserver',f'127.0.0.1:{args.port}','--noreload'],cwd=ROOT,env=os.environ.copy(),stdout=log,stderr=subprocess.STDOUT,stdin=subprocess.DEVNULL)
    def fetch(path,cookie=None,status=200):
        try:
            with urllib.request.urlopen(urllib.request.Request(f'http://127.0.0.1:{args.port}'+path,headers={'Cookie':cookie} if cookie else {}),timeout=60) as r:code,raw,headers=r.status,r.read(),dict(r.headers)
        except urllib.error.HTTPError as r:code,raw,headers=r.code,r.read(),dict(r.headers)
        assert code==status,(path.split('?')[0],code,raw[:160]);return raw,headers
    try:
        for _ in range(80):
            assert child.poll() is None
            try:fetch('/api/auth');break
            except urllib.error.URLError:time.sleep(.15)
        else:raise RuntimeError('Local server unavailable')
        assert fetch('/static/wip_readiness.js')[0]==(ROOT/'static/wip_readiness.js').read_bytes()
        fetch('/api/wip-readiness',status=401);roles=[]
        for role in ('admin','analyst','operations','quality','finance','viewer'):
            client=Client();client.force_login(get_user_model().objects.get(username='demo_'+role));cookie='sessionid='+client.cookies['sessionid'].value
            board=json.loads(fetch('/api/wip-readiness',cookie)[0]);counts['boards']+=1
            assert board['summary']==independent['summary'] and board['total']==312 and len(board['rows'])==25
            for key in ('MO2609-000001','MO-260928-Q002'):
                q=dict(work_order_id=key);board=json.loads(fetch('/api/wip-readiness?'+urlencode(q),cookie)[0]);counts['boards']+=1
                assert board['rows']==expected.selected(engine.filters(q));q['receipt']=board['receipt']
                base='/api/wip-readiness/rows/'+key
                detail=json.loads(fetch(base+'?'+urlencode(q),cookie)[0]);counts['details']+=1
                assert all(detail[k]==v for k,v in expected.details[key].items()),[k for k,v in expected.details[key].items() if detail[k]!=v]
                assert 'cents' not in json.dumps(detail) and 'hourly_' not in json.dumps(detail)
                seen=0
                for page in range(1,100):
                    evidence=json.loads(fetch(base+'/evidence?'+urlencode(q|dict(page=page)),cookie)[0])
                    assert evidence['can_download_original']==(role=='admin')
                    for row in evidence['rows']:
                        assert not row.get('missing'),row
                        r=Record.objects.select_related('source_row__batch').get(dataset=row['dataset'],business_key=row['key']);source=r.source_row
                        assert (row['filename'],row['sheet'],row['row'])==(source.batch.filename,source.sheet,source.row_number)
                        counts['source_rows']+=1;seen+=1
                    if page*evidence['size']>=evidence['total']:break
                else:raise AssertionError('Source pagination incomplete')
                assert seen==evidence['total']
                raw,headers=fetch('/api/wip-readiness/export?'+urlencode(q|dict(page=99)),cookie);counts['exports']+=1
                assert headers.get('Cache-Control')=='no-store' and raw.startswith(b'\xef\xbb\xbf')
                text=raw.decode('utf-8-sig');assert 'cents' not in text and '原良品' in text and '来源对象' in text
                parsed=list(csv.reader(io.StringIO(text)))
                summary=[r for r in parsed if len(r)==16 and r[0]==key];assert len(summary)==1 and summary[0][-1]=='not_computed'
                assert summary[0][-4:-1]==['','','']
                audit=AuditEvent.objects.latest('id');assert audit.action=='wip_readiness.export' and audit.detail['file_sha256']==hashlib.sha256(raw).hexdigest()
                assert audit.detail['work_orders']==1
            fetch('/api/wip-readiness/export?'+urlencode(q|dict(receipt='obsolete')),cookie,status=409)
            fetch('/api/wip-readiness/export',cookie,status=400)
            fetch('/api/wip-readiness/rows/MO2609-000001?'+urlencode(q),cookie,status=404)
            roles.append(dict(role=role,allowed=True,no_financial_fields=True))
        assert facts==list(Record.objects.order_by('dataset','business_key').values_list('dataset','business_key','record_hash'))
        assert AuditEvent.objects.count()==audits+counts['exports'] and sha(ROOT/'data/platform.sqlite3')==main_hash
        proof=dict(success=True,roles=roles,**counts,independent_material_checks=8,facts_unchanged=True,sources_exact=True,main_database_bytes_unchanged=True,browser_acceptance=False)
        (ROOT/'data/wip_readiness_http.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2)+'\n');print(json.dumps(proof,ensure_ascii=False))
    finally:
        child.terminate()
        try:child.wait(timeout=10)
        except subprocess.TimeoutExpired:child.kill();child.wait(timeout=10)
        log.close()

if __name__=='__main__':main()
