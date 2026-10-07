"""Native HTTP rehearsal only; no browser, DOM or mobile acceptance claim."""
import csv,hashlib,io,json,os,shutil,socket,subprocess,sys,time,urllib.request,urllib.error
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
DB=ROOT/'data/spc-rehearsal/platform.sqlite3'
HTTP_APP=ROOT/'data/spc-http-app'
PORT=8893
BASE=f'http://127.0.0.1:{PORT}'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()

def main():
    main_before=sha(ROOT/'data/platform.sqlite3');HTTP_APP.mkdir(exist_ok=False)
    for folder in ('app','config','static','templates'):shutil.copytree(ROOT/folder,HTTP_APP/folder,ignore=shutil.ignore_patterns('__pycache__'))
    shutil.copy2(ROOT/'manage.py',HTTP_APP/'manage.py');(HTTP_APP/'data').mkdir();shutil.copy2(ROOT/'data/bi_design.json',HTTP_APP/'data/bi_design.json')
    http_db=HTTP_APP/'data/platform.sqlite3';shutil.copy2(DB,http_db)
    os.environ['MOTOR_SQLITE_PATH']=str(http_db);os.environ['DJANGO_SETTINGS_MODULE']='config.settings';sys.path.insert(0,str(ROOT))
    import django;django.setup()
    from django.test import Client
    from django.contrib.auth import get_user_model
    from app import access
    from app.models import AuditEvent,Record,ImportBatch
    archive=HTTP_APP/'data/imports';archive.mkdir()
    batch=ImportBatch.objects.get(filename='34_过程稳定性采样_模拟.xlsx');destination=archive/(str(batch.pk)+'.xlsx')
    shutil.copy2(Path(batch.file_path),destination);assert sha(destination)==batch.file_hash
    batch.file_path=str(destination);batch.save(update_fields=['file_path']) # Relocate copy paths only, as in an application restore.
    from urllib.parse import urlencode
    with socket.socket() as s:assert s.connect_ex(('127.0.0.1',PORT))!=0,'Port occupied'
    env=os.environ.copy();env['PYTHONNOUSERSITE']='1';log=(ROOT/'data/spc_http_server.log').open('ab')
    child=subprocess.Popen([str(ROOT/'.venv/bin/python'),str(HTTP_APP/'manage.py'),'runserver',f'127.0.0.1:{PORT}','--noreload'],cwd=HTTP_APP,env=env,stdout=log,stderr=subprocess.STDOUT,stdin=subprocess.DEVNULL)
    def fetch(path,cookie=None):
        req=urllib.request.Request(BASE+path,headers={'Cookie':'sessionid='+cookie} if cookie else {})
        with urllib.request.urlopen(req,timeout=20) as r:return r.status,r.read(),dict(r.headers)
    try:
        for _ in range(60):
            if child.poll() is not None:raise RuntimeError('Native rehearsal server failed')
            try:fetch('/api/auth');break
            except (urllib.error.URLError,ConnectionError):time.sleep(.15)
        else:raise RuntimeError('Native rehearsal server did not become healthy')
        index=fetch('/')[1].decode();assert '/static/spc.css?v=' in index and '/static/spc.js?v=' in index
        for name in ('spc.js','spc.css','app.js'):
            raw=fetch('/static/'+name)[1];assert raw==(ROOT/'static'/name).read_bytes()
        try:fetch('/api/spc')
        except urllib.error.HTTPError as ex:assert ex.code==401
        else:raise AssertionError('Anonymous read succeeded')
        read_counts=(Record.objects.count(),AuditEvent.objects.count());roles=[]
        for user in get_user_model().objects.all():
            client=Client();client.force_login(user);cookie=client.cookies['sessionid'].value
            directory=json.loads(fetch('/api/spc',cookie)[1]);assert len(directory['rows'])==10
            d=json.loads(fetch('/api/spc/SPC2609-0002',cookie)[1]);assert d['signal_counts']==dict(baseline=dict(i=1,mr=0),monitor=dict(i=40,mr=3))
            assert ('price_cents' in d['product'])==access.can_money(user)
            second=json.loads(fetch('/api/spc/SPC2609-0002?'+urlencode(dict(receipt=d['receipt'],page=2)),cookie)[1]);assert d['limits']==second['limits'] and d['chart_points']==second['chart_points']
            point=second['rows'][0]['id'];detail=json.loads(fetch('/api/spc/SPC2609-0002/points/'+point+'?'+urlencode(dict(receipt=d['receipt'])),cookie)[1]);assert detail['row']['id']==point
            assert read_counts==(Record.objects.count(),AuditEvent.objects.count())
            raw=fetch('/api/spc/SPC2609-0002/export?'+urlencode(dict(receipt=d['receipt'],page=2)),cookie)[1]
            rows=list(csv.reader(io.StringIO(raw.decode('utf-8-sig'))));assert len(rows)==88 and {r[0] for r in rows[8:]}=={p['id'] for p in d['chart_points']}
            read_counts=(Record.objects.count(),AuditEvent.objects.count())
            binary=json.loads(fetch('/api/spc/SPC2609-0007',cookie)[1]);assert binary['limits'] is None and binary['category_counts']=={'0':1,'1':79};assert all(p['mr'] is None for p in binary['chart_points'])
            unknown=json.loads(fetch('/api/spc/SPC2609-0010',cookie)[1]);assert unknown['limits'] is None and unknown['coverage']['held']==80
            if access.can_import(user):
                source=next(s for s in detail['sources'] if s['dataset']=='spc_observations')
                content=fetch('/api/imports/'+source['batch_id']+'/file',cookie)[1]
                assert hashlib.sha256(content).hexdigest()==source['file_hash'];read_counts=(Record.objects.count(),AuditEvent.objects.count())
            roles.append(access.role(user))
        assert sha(ROOT/'data/platform.sqlite3')==main_before
        proof=dict(success=True,native_http=True,browser_acceptance=False,mobile_acceptance=False,synthetic=True,
                   all_six_roles=sorted(roles),formula_signal_case=True,binary_counts_no_mr=True,unknown_order_paused=True,
                   original_xlsx_bytes_match=True,csv_complete_80_points_not_current_page=True,
                   assets_exact=True,read_endpoints_do_not_audit=True,main_database_unchanged=True)
        (ROOT/'data/spc_http_validation.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2)+'\n');print(json.dumps(proof,ensure_ascii=False))
    finally:
        child.terminate()
        try:child.wait(timeout=10)
        except subprocess.TimeoutExpired:child.kill();child.wait(timeout=10)
        log.close()

if __name__=='__main__':main()
