"""Exercise checked model updates through an isolated loopback HTTP service."""
import argparse
import hashlib
import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
from http.cookies import SimpleCookie
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--db',type=Path,required=True);parser.add_argument('--port',type=int,required=True);args=parser.parse_args()
    db=args.db.resolve();assert db!=ROOT/'data/platform.sqlite3' and db.is_file()
    sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest();main_hash=sha(ROOT/'data/platform.sqlite3')
    os.environ['MOTOR_SQLITE_PATH']=str(db);os.environ['DJANGO_SETTINGS_MODULE']='config.settings';sys.path.insert(0,str(ROOT))
    import django;django.setup()
    from django.test import Client
    from django.contrib.auth import get_user_model
    from app import topic_workspace as ws
    from app.models import Record,AnalysisModel,AnalysisModelChange,Topic,TopicView,TopicPageVersion,AnalysisModelCardVersion,TopicSnapshot,MetricVersion
    protected=[Record,TopicPageVersion,AnalysisModelCardVersion,TopicSnapshot,MetricVersion]
    fingerprint=lambda m:ws.digest(list(m.objects.order_by('pk').values()))
    before={m.__name__:fingerprint(m) for m in protected}
    old_models=list(AnalysisModel.objects.order_by('pk').values());old_topics=list(Topic.objects.order_by('pk').values());old_views=list(TopicView.objects.order_by('pk').values())
    with socket.socket() as sock:assert sock.connect_ex(('127.0.0.1',args.port))!=0
    log=(ROOT/'data/model_changes_http.server.log').open('ab')
    child=subprocess.Popen([sys.executable,str(ROOT/'manage.py'),'runserver',f'127.0.0.1:{args.port}','--noreload'],cwd=ROOT,env=os.environ.copy(),stdout=log,stderr=subprocess.STDOUT,stdin=subprocess.DEVNULL)
    def fetch(path,cookie='',csrf='',body=None,status=200):
        headers={'Cookie':cookie}
        if body is not None:headers.update({'Content-Type':'application/json','X-CSRFToken':csrf})
        request=urllib.request.Request(f'http://127.0.0.1:{args.port}'+path,headers=headers,data=None if body is None else json.dumps(body).encode())
        try:
            with urllib.request.urlopen(request,timeout=60) as response:code,raw,headers=response.status,response.read(),dict(response.headers)
        except urllib.error.HTTPError as response:code,raw,headers=response.code,response.read(),dict(response.headers)
        assert code==status,(path,code,raw[:250]);return raw,headers
    try:
        for _ in range(80):
            assert child.poll() is None
            try:fetch('/api/auth');break
            except urllib.error.URLError:time.sleep(.15)
        else:raise RuntimeError('Isolated server unavailable')
        for name in ('model_changes.js','app.js'):assert fetch('/static/'+name)[0]==(ROOT/'static'/name).read_bytes()
        base_rows=list(Record.objects.filter(dataset='energy').values_list('values',flat=True))
        day=sorted({r['started'][:10] for r in base_rows})[0];scoped=[r for r in base_rows if r['started'][:10]==day]
        workshop=sorted({r['workshop'] for r in scoped})[0];selected=[r for r in scoped if r['workshop']==workshop]
        assert len(scoped)>len(selected)>0
        results=[];target=None
        for role in ('admin','analyst','operations','quality','finance','viewer'):
            user=get_user_model().objects.get(username='demo_'+role);client=Client();client.force_login(user);cookie='sessionid='+client.cookies['sessionid'].value
            _,headers=fetch('/',cookie);cookies=SimpleCookie();cookies.load(headers['Set-Cookie']);csrf=cookies['csrftoken'].value;cookie+='; csrftoken='+csrf
            def post(path,body,status=200):
                raw,headers=fetch(path,cookie,csrf,body,status)
                if '/change' in path and status==200:assert headers['Cache-Control']=='no-store'
                return json.loads(raw)
            if role in ('admin','analyst'):
                model=post('/api/models',dict(name='HTTP模型预演 '+role,dataset='energy',is_public=True,definition=dict(dimension='workshop',metrics=[dict(agg='sum',field='kwh')],chart='bar')))
                topic=post('/api/topics',dict(name='HTTP依赖核对 '+role,is_public=True,layout=[dict(model_id=model['id'],span=1)]))
                ctx=ws.context(user,topic['id']);view=ws.save_view(user,topic['id'],dict(name='HTTP试算范围',context_token=ctx['context_token'],config=dict(scope={'from':day,'to':day},reference_scope=None,primary_label='本期',reference_label='对照')))
                view_before=TopicView.objects.get(pk=view['id']);view_hash=ws.digest(ws.snapshot(view_before))
                body=dict(version=1,candidate=dict(name='HTTP核对后 '+role,dataset='energy',is_public=True,definition=dict(dimension='workshop',metrics=[dict(agg='sum',field='kwh')],filters=[dict(field='workshop',op='eq',value=workshop)],chart='bar')),scope={'from':day,'to':day},links=None)
                target=f'/api/models/{model["id"]}'
                p=post(target+'/change-preview',body)
                assert abs(p['original_result']['summary']['value']-sum(r['kwh'] for r in scoped))<.0001
                assert abs(p['candidate_result']['summary']['value']-sum(r['kwh'] for r in selected))<.0001
                assert p['population']['shared']==len(selected) and p['population']['removed']==len(scoped)-len(selected)
                assert p['impact']['topics'][0]['id']==topic['id'] and p['impact']['views'][0]['id']==view['id']
                source=post(target+'/change-evidence',dict(**body,receipt=p['receipt'],side='candidate',subset='shared',page=1))
                assert {r['values']['id'] for r in source['rows']}=={r['id'] for r in selected}
                for item in source['rows']:
                    record=Record.objects.select_related('source_row__batch').get(dataset='energy',business_key=item['values']['id'])
                    assert (item['source']['filename'],item['source']['sheet'],item['source']['row'])==(record.source_row.batch.filename,record.source_row.sheet,record.source_row.row_number)
                commit=dict(**body,receipt=p['receipt'],reason='HTTP核对当前范围与来源',acknowledged=True,request_id=str(uuid.uuid4()))
                updated=post(target+'/change',commit);replay=post(target+'/change',commit)
                assert updated['model']['version']==2 and not updated['repeated'] and replay['repeated']
                history=json.loads(fetch(target+'/changes',cookie)[0]);assert history['total']==1 and history['rows'][0]['payload']['before']['version']==1
                view_before.refresh_from_db();assert ws.digest(ws.snapshot(view_before))==view_hash
                assert ws.view_info(view_before,ws.context(user,topic['id']))['stale']
                post('/api/models',dict(id=model['id'],name='legacy update'),409)
                post(target+'/change-preview',body,409)
                fetch(target+'/change-preview',cookie,'',body,403)
                results.append(dict(role=role,allowed=True,original_objects=len(scoped),candidate_objects=len(selected),independent_sum_equal=True,excel_sources=True,saved_view_unchanged_and_stale=True,idempotent=True))
            else:
                post(target+'/change-preview',body,403)
                post(target+'/change-evidence',dict(**body,receipt=p['receipt'],side='candidate',subset='shared',page=1),403)
                post(target+'/change',commit,403)
                fetch(target+'/changes',cookie,status=403);results.append(dict(role=role,allowed=False))
        fetch(target+'/changes',status=401)
        assert before=={m.__name__:fingerprint(m) for m in protected}
        for m,old in ((AnalysisModel,old_models),(Topic,old_topics),(TopicView,old_views)):
            assert list(m.objects.filter(pk__in=[r['id'] for r in old]).order_by('pk').values())==old
        assert sha(ROOT/'data/platform.sqlite3')==main_hash
        proof=dict(success=True,native_http=True,roles=results,main_unchanged=True,old_facts_and_configuration_unchanged=True,isolated_new_model_changes=AnalysisModelChange.objects.count(),assets_exact=True,browser_acceptance=False,mobile_acceptance=False)
        (ROOT/'data/model_changes_http.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2)+'\n');print(json.dumps(proof,ensure_ascii=False))
    finally:
        child.terminate()
        try:child.wait(timeout=10)
        except subprocess.TimeoutExpired:child.kill();child.wait(timeout=10)
        log.close()

if __name__=='__main__':main()
