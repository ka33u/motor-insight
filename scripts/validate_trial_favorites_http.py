"""Exercise personal trial favorites on a disposable normally imported Excel database."""
import argparse,hashlib,json,os,socket,subprocess,sys,time
from pathlib import Path
from urllib.parse import urlencode,quote
import urllib.request,urllib.error
ROOT=Path(__file__).resolve().parents[1]

def main():
    p=argparse.ArgumentParser();p.add_argument('--db',type=Path,required=True);p.add_argument('--port',type=int,required=True);a=p.parse_args()
    db=a.db.resolve();assert db.is_file() and db!=ROOT/'data/platform.sqlite3'
    sha=lambda path:hashlib.sha256(path.read_bytes()).hexdigest();main_hash=sha(ROOT/'data/platform.sqlite3')
    sys.path.insert(0,str(ROOT));os.environ.update(DJANGO_SETTINGS_MODULE='config.settings',MOTOR_SQLITE_PATH=str(db))
    import django;django.setup()
    from django.test import Client
    from django.contrib.auth import get_user_model
    from app.models import Record,WorkbenchEntry,PersonalWorkbench,AuditEvent
    from app import workbench_trials as trials,spc_data
    facts=list(Record.objects.order_by('dataset','business_key').values_list('dataset','business_key','record_hash'))
    assert len(facts)==232941
    before_entries=list(WorkbenchEntry.objects.order_by('pk').values())
    counts=dict(catalog_targets=0,saved_reopened=0,destination_reads=0,home_checks=0,removed=0);roles=[]
    with socket.socket() as sock:assert sock.connect_ex(('127.0.0.1',a.port))!=0
    log=(ROOT/'data/trial_favorites_http.server.log').open('ab')
    child=subprocess.Popen([sys.executable,str(ROOT/'manage.py'),'runserver',f'127.0.0.1:{a.port}','--noreload'],cwd=ROOT,env=os.environ.copy(),stdout=log,stderr=subprocess.STDOUT,stdin=subprocess.DEVNULL)
    def fetch(path,cookie=None,value=None,csrf=None,status=200):
        headers={'Cookie':cookie} if cookie else {};data=None
        if value is not None:data=json.dumps(value).encode();headers.update({'Content-Type':'application/json','X-CSRFToken':csrf})
        try:
            with urllib.request.urlopen(urllib.request.Request(f'http://127.0.0.1:{a.port}'+path,data=data,headers=headers),timeout=45) as r:code,raw,meta=r.status,r.read(),dict(r.headers)
        except urllib.error.HTTPError as r:code,raw,meta=r.code,r.read(),dict(r.headers)
        assert code==status,(path,code,raw[:160]);return raw,meta
    try:
        for _ in range(80):
            assert child.poll() is None
            try:fetch('/api/auth');break
            except urllib.error.URLError:time.sleep(.15)
        else:raise RuntimeError('HTTP preview not ready')
        _,headers=fetch('/');csrf=headers['Set-Cookie'].split('csrftoken=')[1].split(';')[0]
        assert fetch('/static/workbench.js')[0]==(ROOT/'static/workbench.js').read_bytes()
        fetch('/api/workbench/trial-target','csrftoken='+csrf,dict(route='joint-schedule',study='MP-261002-001',policy='due',view=''),csrf,401)
        for role in ('admin','analyst','operations','quality','finance','viewer'):
            user=get_user_model().objects.get(username='demo_'+role);client=Client();client.force_login(user);cookie='sessionid='+client.cookies['sessionid'].value+'; csrftoken='+csrf
            def post(path,value,status=200):return json.loads(fetch(path,cookie,value,csrf,status)[0])
            def get(path):return json.loads(fetch(path,cookie)[0])
            original=get('/api/workbench');rows=[];page=1
            while True:
                result=post('/api/workbench/catalog',dict(kind='trial',q='',page=page));rows+=result['rows']
                if len(rows)>=result['total']:break
                page+=1
            expected=[]
            for family,(_,dataset,_,_) in trials.FAMILIES.items():
                if family!='finite' and role not in ('admin','analyst','operations'):continue
                for r in Record.objects.filter(dataset=dataset):
                    source=spc_data.source(r);assert source['filename'].endswith('.xlsx')
                    expected += [f'{family}:{r.pk}:{mode}' for mode in trials.modes(family)]
            assert {r['target'] for r in rows}==set(expected) and len(rows)==len(expected)
            counts['catalog_targets']+=len(rows)
            for r in rows:
                family,key,mode=trials.parse(r['target']);record=Record.objects.get(pk=key)
                assert r['params']['study']==record.business_key and record.values['name'] in r['label']
                assert not set(r['params'])-{'study','policy','view'} and r['kind']=='trial'
            # One normal source study per family, every supported reading mode.
            chosen=[r for r in rows if r['params']['study'].endswith('-001')]
            # Two joint 001 scenarios have different dates; keep the established source study only.
            chosen=[r for r in chosen if r['params']['study']!='MP-261009-001' and r['params']['study'] not in ('SP-261009-001','CR-261009-001')]
            assert len(chosen)==(11 if role in ('admin','analyst','operations') else 2)
            current=original;created=[]
            for r in chosen:
                conf=dict(route=r['route'],study=r['params']['study'],policy=r['params'].get('policy','due'),view=r['params'].get('view',''))
                resolved=post('/api/workbench/trial-target',conf);assert resolved==r
                current=post('/api/workbench',dict(action='add',revision=current['revision'],kind='trial',target=r['target'],alias='模拟早会方案',section='试排核查'))
                saved=next(x for x in current['rows'] if x['kind']=='trial' and x['target']==r['target']);created.append(saved['id'])
                opened=post('/api/workbench/open',dict(id=saved['id'],revision=current['revision']));assert opened['route']==r['route'] and opened['params']==r['params'];counts['saved_reopened']+=1
                params=opened['params'];path='/api/'+opened['route']+'/'+quote(params['study'],safe='')
                if params.get('view')=='compare':result=post('/api/joint-comparison/'+quote(params['study'],safe=''),{})
                elif params.get('view')=='trial':result=post('/api/baseline-trial/'+quote(params['study'],safe=''),{'policy':params['policy']})
                else:result=get(path+'?'+urlencode({'policy':params.get('policy','due')}))
                assert result['study']['id']==params['study'];counts['destination_reads']+=1
                if 'policy' in params:assert result['policy']==params['policy']
            assert {r['id'] for r in get('/api/workbench')['rows']}=={r['id'] for r in original['rows']}|set(created)
            current=post('/api/workbench',dict(action='home',revision=current['revision'],id=created[-1]));start=get('/api/workbench/start');assert start['route']==chosen[-1]['route'] and start['params']==chosen[-1]['params'];counts['home_checks']+=1
            post('/api/workbench',dict(action='home',revision=current['revision']-1,id=None),409)
            # Restore this disposable account's original home preference before removing added favorites.
            home=original['home_entry'] if original['home_mode']=='favorite' else 'workbench' if original['home_mode']=='workbench' else None
            current=post('/api/workbench',dict(action='home',revision=current['revision'],id=home))
            for identity in created:
                current=post('/api/workbench',dict(action='remove',revision=current['revision'],id=identity));counts['removed']+=1
            assert current['rows']==original['rows'] and current['home_mode']==original['home_mode']
            if role not in ('admin','analyst','operations'):
                for study in ('MP-261002-001','MISSING'):
                    post('/api/workbench/trial-target',dict(route='joint-schedule',study=study,policy='due',view='compare'),403)
            roles.append(dict(role=role,catalog_targets=len(rows),reopened=len(chosen)))
        assert facts==list(Record.objects.order_by('dataset','business_key').values_list('dataset','business_key','record_hash'))
        assert before_entries==list(WorkbenchEntry.objects.order_by('pk').values())
        assert sha(ROOT/'data/platform.sqlite3')==main_hash
        proof=dict(success=True,roles=roles,**counts,facts_unchanged=True,source_identifiers_exact=True,disposable_preferences_restored=True,main_database_bytes_unchanged=True,browser_acceptance=False)
        (ROOT/'data/trial_favorites_http.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2)+'\n');print(json.dumps(proof,ensure_ascii=False))
    finally:child.terminate();child.wait(timeout=10);log.close()

if __name__=='__main__':main()
