"""Native HTTP evidence checks using an isolated public-Excel replay database."""
import argparse,csv,hashlib,io,json,os,socket,subprocess,sys,time
import urllib.error,urllib.request
from pathlib import Path
from urllib.parse import urlencode
ROOT=Path(__file__).resolve().parents[1]

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--db',type=Path,required=True);parser.add_argument('--port',type=int,required=True);args=parser.parse_args()
    db=args.db.resolve();assert db.is_file() and db!=ROOT/'data/platform.sqlite3';sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest();main_hash=sha(ROOT/'data/platform.sqlite3')
    sys.path.insert(0,str(ROOT));os.environ.update(DJANGO_SETTINGS_MODULE='config.settings',MOTOR_SQLITE_PATH=str(db))
    import django;django.setup()
    from django.test import Client
    from django.contrib.auth import get_user_model
    from app.models import Record,AuditEvent
    from app import material_planning,analytics,supply
    from validate_material_returns import verify,WORKS
    independent=verify();facts=list(Record.objects.order_by('dataset','business_key').values_list('dataset','business_key','record_hash'))
    assert len(facts)==233902
    audits=AuditEvent.objects.count();counts=dict(boards=0,details=0,exports=0,source_rows=0)
    with socket.socket() as sock:assert sock.connect_ex(('127.0.0.1',args.port))!=0
    log=(ROOT/'data/material_returns_http.server.log').open('ab')
    child=subprocess.Popen([sys.executable,str(ROOT/'manage.py'),'runserver',f'127.0.0.1:{args.port}','--noreload'],cwd=ROOT,env=os.environ.copy(),stdout=log,stderr=subprocess.STDOUT,stdin=subprocess.DEVNULL)
    def fetch(path,cookie=None,status=200):
        try:
            with urllib.request.urlopen(urllib.request.Request(f'http://127.0.0.1:{args.port}'+path,headers={'Cookie':cookie} if cookie else {}),timeout=45) as response:
                code,raw,headers=response.status,response.read(),dict(response.headers)
        except urllib.error.HTTPError as response:code,raw,headers=response.code,response.read(),dict(response.headers)
        assert code==status,(path.split('?')[0],code,raw[:100]);return raw,headers
    try:
        for _ in range(80):
            assert child.poll() is None
            try:fetch('/api/auth');break
            except urllib.error.URLError:time.sleep(.15)
        else:raise RuntimeError('Local server unavailable')
        for name in ('material_returns.js','material_planning.js'):assert fetch('/static/'+name)[0]==(ROOT/'static'/name).read_bytes()
        fetch('/api/material-planning',status=401);fetch('/api/material-planning/orders/'+WORKS[0]+'/issue-returns.csv',status=401)
        source_data=analytics._tables(analytics.revision());expected=material_planning.MaterialPlanning(source_data,material_planning.filters({'q':'MO-260928-R','stock_policy':'all_usable'}))
        roles=[];fixtures={}
        for role in ('admin','analyst','operations','quality','finance','viewer'):
            client=Client();client.force_login(get_user_model().objects.get(username='demo_'+role));cookie='sessionid='+client.cookies['sessionid'].value
            query=dict(q='MO-260928-R',stock_policy='all_usable');board=json.loads(fetch('/api/material-planning?'+urlencode(query),cookie)[0]);counts['boards']+=1
            assert board['summary']==expected.summary() and len(board['rows'])==5
            query['receipt']=board['receipt']
            for work in WORKS:
                base='/api/material-planning/orders/'+work;detail=json.loads(fetch(base+'?'+urlencode(query),cookie)[0]);counts['details']+=1
                local=material_planning.clean(expected.detail('orders',work))
                assert detail['row']==local['row'] and detail['return_reconciliation']==local['return_reconciliation']
                if role=='admin':fixtures[work]=dict(row=detail['row'],return_reconciliation=detail['return_reconciliation'])
                for page in range(1,100):
                    evidence=json.loads(fetch(base+'/evidence?'+urlencode(query|dict(page=page)),cookie)[0])
                    for row in evidence['rows']:
                        record=Record.objects.select_related('source_row__batch').get(dataset=row['dataset'],business_key=row['key']);source=record.source_row
                        assert (row['filename'],row['sheet'],row['row'])==(source.batch.filename,source.sheet,source.row_number);counts['source_rows']+=1
                    if page*40>=evidence['total']:break
                else:raise AssertionError('Source pagination did not finish')
                raw,headers=fetch(base+'/issue-returns.csv?'+urlencode(query|dict(stage='short')),cookie);counts['exports']+=1
                assert headers.get('Cache-Control')=='no-store' and raw.startswith(b'\xef\xbb\xbf')
                assert hashlib.sha256(raw).hexdigest()==AuditEvent.objects.latest('id').detail['file_sha256']
                text=raw.decode('utf-8-sig');assert 'Excel来源对象' in text and '累计领料' in text and 'cents' not in text and '475000' not in text
                parsed=list(csv.reader(io.StringIO(text)));assert parsed[0][2]==work
                if work.endswith('005'):assert '累计退料超过领料量' in text
                if work.endswith('004'):assert 'TL-260930-R004-01' not in text
            fetch('/api/material-planning/orders/'+WORKS[0]+'/issue-returns.csv?'+urlencode(query|dict(receipt='obsolete')),cookie,status=409)
            fetch('/api/material-planning/orders/'+WORKS[0]+'/issue-returns.csv?'+urlencode(dict(q='MO-260928-R',stock_policy='all_usable')),cookie,status=400)
            roles.append(dict(role=role,allowed=True,no_financial_fields=True))
        assert facts==list(Record.objects.order_by('dataset','business_key').values_list('dataset','business_key','record_hash'))
        assert AuditEvent.objects.count()==audits+counts['exports'] and sha(ROOT/'data/platform.sqlite3')==main_hash
        (ROOT/'data/material_returns_http_fixtures.json').write_text(json.dumps(fixtures,ensure_ascii=False,indent=2)+'\n')
        proof=dict(success=True,roles=roles,**counts,independent_material_checks=independent['independent_material_checks'],facts_unchanged=True,
                   sources_exact=True,main_database_bytes_unchanged=True,browser_acceptance=False)
        (ROOT/'data/material_returns_http.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2)+'\n');print(json.dumps(proof,ensure_ascii=False))
    finally:
        child.terminate();child.wait(timeout=10);log.close()

if __name__=='__main__':main()
