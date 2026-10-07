"""Exercise actual loopback HTTP on an isolated, freshly replayed demo database."""
import argparse,hashlib,json,os,socket,subprocess,sys,time,urllib.error,urllib.request,uuid
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def main():
    parser=argparse.ArgumentParser();parser.add_argument('--project',type=Path,required=True);parser.add_argument('--db',type=Path,required=True);parser.add_argument('--port',type=int,required=True);args=parser.parse_args()
    project=args.project.resolve();db=args.db.resolve();assert db!=ROOT/'data/platform.sqlite3' and db.is_file()
    main_sha=hashlib.sha256((ROOT/'data/platform.sqlite3').read_bytes()).hexdigest()
    sys.path.insert(0,str(project));os.environ.update(DJANGO_SETTINGS_MODULE='config.settings',MOTOR_SQLITE_PATH=str(db))
    import django;django.setup()
    from django.test import Client
    from django.contrib.auth.models import User
    from app.models import Record,AnalysisModel,Topic,CodingRule,PersonalWorkbench,WorkbenchEntry
    from app import topic_workspace as ws,topic_pages,model_cards
    assert not PersonalWorkbench.objects.exists()
    models=list(AnalysisModel.objects.values());topics=list(Topic.objects.values());codes=list(CodingRule.objects.values())
    facts=list(Record.objects.order_by('dataset','business_key').values_list('dataset','business_key','record_hash'))
    model=AnalysisModel.objects.get(pk=21);topic=Topic.objects.get(pk=12);code=CodingRule.objects.first();assert code
    with socket.socket() as sock:assert sock.connect_ex(('127.0.0.1',args.port))!=0
    log=(ROOT/'data/workbench_http.server.log').open('ab')
    child=subprocess.Popen([sys.executable,str(project/'manage.py'),'runserver',f'127.0.0.1:{args.port}','--noreload'],cwd=project,env=os.environ.copy(),stdout=log,stderr=subprocess.STDOUT,stdin=subprocess.DEVNULL)
    def fetch(path,data=None,cookie=None,csrf=None,status=200):
        headers={};raw=None
        if data is not None:raw=json.dumps(data,ensure_ascii=False).encode();headers['Content-Type']='application/json'
        if cookie:headers['Cookie']=cookie
        if csrf:headers['X-CSRFToken']=csrf
        request=urllib.request.Request(f'http://127.0.0.1:{args.port}'+path,data=raw,headers=headers)
        try:
            with urllib.request.urlopen(request,timeout=30) as response:code,body,h=response.status,response.read(),dict(response.headers)
        except urllib.error.HTTPError as response:code,body,h=response.code,response.read(),dict(response.headers)
        assert code==status,(path,code,body[:160]);return body,h
    try:
        for _ in range(80):
            assert child.poll() is None
            try:fetch('/api/auth');break
            except urllib.error.URLError:time.sleep(.15)
        else:raise RuntimeError('Isolated preview unavailable')
        html,headers=fetch('/');assert b'workbench.css?v=' in html
        csrf=headers['Set-Cookie'].split('csrftoken=')[1].split(';')[0]
        for name in ('workbench.js','workbench.css','app.js'):assert fetch('/static/'+name)[0]==(project/'static'/name).read_bytes()
        fetch('/api/workbench',status=401);results=[];foreign=None;private_target=None
        for role in ('admin','analyst','quality','operations','finance','viewer'):
            user=User.objects.get(username='demo_'+role);ctx=ws.context(user,topic.pk)
            assert all(c['available'] for c in ctx['cards'])
            view=ws.save_view(user,topic.pk,dict(name='工作台HTTP个人视角 '+role,config=dict(scope={},reference_scope=None,primary_label='当前',reference_label='对照'),context_token=ctx['context_token']))
            definition=dict(topic_id=topic.pk,code='PAGE.WB.'+role.upper(),title='工作台HTTP个人页面 '+role,question='核对当期售后登记',cadence='每日',sections=[dict(id='MAIN',title='主结果',role='result',note='',cards=[dict(slot=i,span=1,title='',note='') for i in range(len(ctx['cards']))])],navigation=[])
            preview=topic_pages.preview(user,definition);page=topic_pages.save(user,dict(request_id=str(uuid.uuid4()),definition=definition,receipt=preview['receipt'],reason='隔离合成演练'))
            preview=model_cards.preview(user,model.pk);card,_,_=model_cards.save(user,dict(request_id=str(uuid.uuid4()),code='CARD.WB.'+role.upper(),name='工作台HTTP个人口径卡 '+role,question='核对能耗',reader='车间',object_grain='能源登记',time_scope='原模型',limitations='合成资料',review_on=None,model_id=model.pk,receipt=preview['receipt']))
            client=Client();client.force_login(user);cookie='sessionid='+client.cookies['sessionid'].value+'; csrftoken='+csrf
            def get(suffix=''):
                raw,h=fetch('/api/workbench'+suffix,cookie=cookie);assert h['Cache-Control']=='no-store';return json.loads(raw)
            def post(suffix,data,status=200):
                raw,h=fetch('/api/workbench'+suffix,data,cookie,csrf,status)
                if status==200:assert h['Cache-Control']=='no-store'
                return json.loads(raw)
            fetch('/api/workbench',{},cookie,status=403);d=get();assert d['revision']==0 and not d['rows']
            partial=post('/catalog',dict(kind='topic',q='能源安环',page=1))['rows'];assert len(partial)==1
            assert partial[0]['state']==('ready' if role in ('admin','analyst','finance') else 'review')
            if private_target:assert post('/catalog',dict(kind='page',q=private_target,page=1))['total']==0
            targets=[('module','delivery'),('model',str(model.pk)),('topic',str(topic.pk)),('view',str(view['id'])),('page',page['id']),('card',str(card.pk)),('coding',str(code.pk))]
            for kind,target in targets:
                choices=post('/catalog',dict(kind=kind,q=target,page=1));assert any(r['target']==target for r in choices['rows']),(role,kind)
                d=post('',dict(action='add',revision=d['revision'],kind=kind,target=target,alias='',section='早会' if kind in ('module','topic') else '分析'))
            assert len(d['rows'])==7
            if foreign:post('/open',dict(id=foreign,revision=d['revision']),404)
            else:foreign=d['rows'][0]['id'];private_target=page['id']
            for row in d['rows']:
                opened=post('/open',dict(id=row['id'],revision=d['revision']));assert opened['state']=='ready' and opened['kind']==row['kind']
            row=d['rows'][0];d=post('',dict(action='edit',revision=d['revision'],id=row['id'],alias='早会交付核查',section='每日先看'))
            d=post('',dict(action='order',revision=d['revision'],ids=[r['id'] for r in reversed(d['rows'])]));assert d['rows'][-1]['alias']=='早会交付核查'
            post('',dict(action='home',revision=d['revision']-1,id='workbench'),409)
            d=post('',dict(action='home',revision=d['revision'],id=row['id']));assert get('/start')['route']=='delivery'
            d=post('',dict(action='home',revision=d['revision'],id='workbench'));assert get('/start')['route']=='workbench'
            d=post('',dict(action='home',revision=d['revision'],id=None));assert get('/start')['route']=='overview'
            for row in list(d['rows']):d=post('',dict(action='remove',revision=d['revision'],id=row['id']))
            assert not d['rows'] and get()['revision']==19
            results.append(dict(role=role,kinds=7,mutations=19,csrf=True,foreign_private_hidden=role!='admin'))
        assert not WorkbenchEntry.objects.exists() and PersonalWorkbench.objects.count()==6
        assert facts==list(Record.objects.order_by('dataset','business_key').values_list('dataset','business_key','record_hash'))
        assert models==list(AnalysisModel.objects.values()) and topics==list(Topic.objects.values()) and codes==list(CodingRule.objects.values())
        assert hashlib.sha256((ROOT/'data/platform.sqlite3').read_bytes()).hexdigest()==main_sha
        proof=dict(success=True,roles=results,all_seven_kinds=True,source_facts_models_topics_coding_unchanged=True,main_database_bytes_unchanged=True,browser_acceptance=False)
        (ROOT/'data/workbench_http.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2)+'\n');print(json.dumps(proof,ensure_ascii=False))
    finally:child.terminate();child.wait(timeout=10);log.close()
if __name__=='__main__':main()
