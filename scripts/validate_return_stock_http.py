"""Verify native HTTP responses on an isolated public-Excel replay database."""
import argparse,csv,hashlib,io,json,os,socket,subprocess,sys,time
import urllib.error,urllib.request
from pathlib import Path
from urllib.parse import urlencode
ROOT=Path(__file__).resolve().parents[1]


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--db',type=Path,required=True);parser.add_argument('--port',type=int,required=True);args=parser.parse_args()
    db=args.db.resolve();assert db.is_file() and db!=ROOT/'data/platform.sqlite3'
    sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest();main_hash=sha(ROOT/'data/platform.sqlite3')
    sys.path.insert(0,str(ROOT));os.environ.update(DJANGO_SETTINGS_MODULE='config.settings',MOTOR_SQLITE_PATH=str(db))
    import django;django.setup()
    from django.test import Client
    from django.contrib.auth import get_user_model
    from app.models import Record,AuditEvent
    from app import return_stock,analytics,supply
    from validate_return_stock import verify
    independent=verify();facts=list(Record.objects.order_by('dataset','business_key').values_list('dataset','business_key','record_hash'));assert len(facts)==234037
    audits=AuditEvent.objects.count();counts=dict(boards=0,details=0,exports=0,source_rows=0)
    with socket.socket() as sock:assert sock.connect_ex(('127.0.0.1',args.port))!=0
    log=(ROOT/'data/return_stock_http.server.log').open('ab')
    child=subprocess.Popen([sys.executable,str(ROOT/'manage.py'),'runserver',f'127.0.0.1:{args.port}','--noreload'],cwd=ROOT,env=os.environ.copy(),stdout=log,stderr=subprocess.STDOUT,stdin=subprocess.DEVNULL)
    def fetch(path,cookie=None,status=200):
        try:
            with urllib.request.urlopen(urllib.request.Request(f'http://127.0.0.1:{args.port}'+path,headers={'Cookie':cookie} if cookie else {}),timeout=45) as response:
                code,raw,headers=response.status,response.read(),dict(response.headers)
        except urllib.error.HTTPError as response:code,raw,headers=response.code,response.read(),dict(response.headers)
        assert code==status,(path.split('?')[0],code,raw[:120]);return raw,headers
    try:
        for _ in range(80):
            assert child.poll() is None
            try:fetch('/api/auth');break
            except urllib.error.URLError:time.sleep(.15)
        else:raise RuntimeError('Local server unavailable')
        for name in ('return_stock.js','supply.js'):assert fetch('/static/'+name)[0]==(ROOT/'static'/name).read_bytes()
        fetch('/api/return-stock',status=401);fetch('/api/return-stock/export',status=401)
        expected=return_stock.ReturnStock(supply.SupplyData(analytics._tables(analytics.revision())))
        roles=[];fixtures={}
        for role in ('admin','analyst','operations','quality','finance','viewer'):
            client=Client();client.force_login(get_user_model().objects.get(username='demo_'+role));cookie='sessionid='+client.cookies['sessionid'].value
            for stage in ('all','available','restricted','attention'):
                query=dict(q='MO-260928-Q',stage=stage);f=return_stock.filters(query);chosen=expected.selected(f)
                board=json.loads(fetch('/api/return-stock?'+urlencode(query),cookie)[0]);counts['boards']+=1
                assert board['summary']==expected.summary(expected.cohort(f)) and board['rows']==chosen
                assert board['matrix']==expected.matrix(expected.cohort(f)) and board['units']==expected.units(expected.cohort(f))
                query['receipt']=board['receipt']
                raw,headers=fetch('/api/return-stock/export?'+urlencode(query|dict(page=2)),cookie);counts['exports']+=1
                assert headers.get('Cache-Control')=='no-store' and raw.startswith(b'\xef\xbb\xbf')
                audit=AuditEvent.objects.latest('id');assert audit.action=='return_stock.export' and audit.detail['file_sha256']==hashlib.sha256(raw).hexdigest()
                assert audit.detail['returns']==len(chosen) and audit.detail['target_lots']==len(expected.unique_lots(chosen))
                text=raw.decode('utf-8-sig');assert 'cents' not in text and '475000' not in text and '来源对象' in text
                parsed=list(csv.reader(io.StringIO(text)))
                csv_returns=[r for r in parsed if r and r[0].startswith('TL-260930-Q')]
                assert [r[0] for r in csv_returns]==[r['id'] for r in chosen]
                csv_lots=[r for r in parsed if r and r[0] in expected.lots]
                assert len(csv_lots)==len({r['lot_id'] for r in chosen})
                if stage!='all':continue
                for row in chosen:
                    key=row['id'];base='/api/return-stock/rows/'+key
                    detail=json.loads(fetch(base+'?'+urlencode(query),cookie)[0]);counts['details']+=1
                    assert all(detail[k]==v for k,v in expected.details[key].items())
                    assert 'cents' not in json.dumps(detail) and 'hourly_' not in json.dumps(detail)
                    if role=='admin':fixtures[key]=detail
                    seen=0
                    for page in range(1,100):
                        evidence=json.loads(fetch(base+'/evidence?'+urlencode(query|dict(page=page)),cookie)[0])
                        assert evidence['can_download_original']==(role=='admin')
                        for r in evidence['rows']:
                            record=Record.objects.select_related('source_row__batch').get(dataset=r['dataset'],business_key=r['key']);source=record.source_row
                            assert (r['filename'],r['sheet'],r['row'])==(source.batch.filename,source.sheet,source.row_number);counts['source_rows']+=1;seen+=1
                        if page*evidence['size']>=evidence['total']:break
                    else:raise AssertionError('Source pagination did not finish')
                    assert seen==evidence['total']
            fetch('/api/return-stock/export?'+urlencode(query|dict(receipt='obsolete')),cookie,status=409)
            fetch('/api/return-stock/export?'+urlencode(dict(q='MO-260928-Q')),cookie,status=400)
            fetch('/api/return-stock/rows/TL-260930-Q001-01?'+urlencode(query),cookie,status=404)
            roles.append(dict(role=role,allowed=True,no_financial_fields=True))
        assert facts==list(Record.objects.order_by('dataset','business_key').values_list('dataset','business_key','record_hash'))
        assert AuditEvent.objects.count()==audits+counts['exports'];assert sha(ROOT/'data/platform.sqlite3')==main_hash
        proof=dict(success=True,roles=roles,**counts,independent_target_lot_checks=independent['independent_target_lot_checks'],
                   facts_unchanged=True,sources_exact=True,main_database_bytes_unchanged=True,browser_acceptance=False)
        (ROOT/'data/return_stock_http.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2)+'\n')
        (ROOT/'data/return_stock_http_fixtures.json').write_text(json.dumps(fixtures,ensure_ascii=False,indent=2)+'\n')
        print(json.dumps(proof,ensure_ascii=False))
    finally:
        child.terminate()
        try:child.wait(timeout=10)
        except subprocess.TimeoutExpired:child.kill();child.wait(timeout=10)
        log.close()


if __name__=='__main__':main()
