"""Native HTTP verification on an explicitly disposable synthetic database."""
import argparse,hashlib,json,os,socket,subprocess,sys,time,urllib.error,urllib.parse,urllib.request,uuid,zipfile
from pathlib import Path
SOURCE=Path(__file__).resolve().parents[1]
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
 parser=argparse.ArgumentParser();parser.add_argument('--root',type=Path,default=SOURCE);parser.add_argument('--db',type=Path,required=True);parser.add_argument('--port',type=int,required=True);parser.add_argument('--proof',type=Path,required=True);parser.add_argument('--archive',type=Path);a=parser.parse_args();root=a.root.resolve();db=a.db.resolve();assert db!=SOURCE/'data/platform.sqlite3';main_sha=sha(SOURCE/'data/platform.sqlite3');exact_files=0
 if a.archive:
  with zipfile.ZipFile(a.archive) as z:
   manifest=json.loads(z.read('manifest.json'))
   for item in manifest['files']:
    if item['path']!='data/platform.sqlite3':assert sha(root/item['path'])==item['sha256']==sha(SOURCE/item['path']),item['path'];exact_files+=1
 os.environ['DJANGO_SETTINGS_MODULE']='config.settings';os.environ['MOTOR_SQLITE_PATH']=str(db);sys.path.insert(0,str(root));import django;django.setup()
 from django.conf import settings
 from django.test import Client
 from django.contrib.auth import get_user_model
 from app import access
 from app.models import Record,AnalysisModel,TopicPage,TopicPageVersion,TopicPageRequest,AuditEvent
 assert settings.BASE_DIR==root
 with socket.socket() as s:assert s.connect_ex(('127.0.0.1',a.port))!=0
 env=os.environ.copy();env.pop('PYTHONPATH',None);env['PYTHONNOUSERSITE']='1';a.proof.parent.mkdir(exist_ok=True,parents=True);logpath=a.proof.with_suffix('.server.log');log=logpath.open('ab');logpath.chmod(0o600)
 child=subprocess.Popen([str(root/'.venv/bin/python'),str(root/'manage.py'),'runserver',f'127.0.0.1:{a.port}','--noreload'],cwd=root,env=env,stdout=log,stderr=subprocess.STDOUT,stdin=subprocess.DEVNULL)
 def fetch(path,cookie=None,method='GET',body=None,csrf=None,status=200):
  headers={'Cookie':cookie} if cookie else {}
  if body is not None:headers['Content-Type']='application/json'
  if csrf:headers['X-CSRFToken']=csrf
  req=urllib.request.Request(f'http://127.0.0.1:{a.port}'+path,data=json.dumps(body).encode() if body is not None else None,headers=headers,method=method)
  try:
   with urllib.request.urlopen(req,timeout=40) as r:code=r.status;raw=r.read();rh=dict(r.headers)
  except urllib.error.HTTPError as e:code=e.code;raw=e.read();rh=dict(e.headers)
  assert code==status,(path.split('?')[0],code,raw[:250]);return raw,rh
 def get(path,cookie=None,status=200):return json.loads(fetch(path,cookie,status=status)[0])
 def post(path,cookie,body,csrf=None,status=200):return json.loads(fetch(path,cookie,'POST',body,csrf,status)[0])
 try:
  for _ in range(100):
   if child.poll() is not None:raise RuntimeError('Native server failed')
   try:get('/api/auth');break
   except urllib.error.URLError:time.sleep(.1)
  else:raise RuntimeError('Native server unavailable')
  index=fetch('/')[0].decode();assert '/static/topic_pages.css?v=' in index and '/static/topic_pages.js?v=' in index
  for name in ('topic_pages.js','topic_pages.css','topics.js','app.js'):assert fetch('/static/'+name)[0]==(root/'static'/name).read_bytes()
  get('/api/topic-pages',status=401);roles={};cases=[];before_facts=list(Record.objects.values_list('id','values','revision'));base_pages=TopicPage.objects.count();base_versions=TopicPageVersion.objects.count();base_requests=TopicPageRequest.objects.count()
  for user in get_user_model().objects.all():
   role=access.role(user);client=Client();client.force_login(user);client.get('/');csrf=client.cookies['csrftoken'].value;cookie='sessionid='+client.cookies['sessionid'].value+'; csrftoken='+csrf;roles[role]=(cookie,csrf)
  admin_cookie,admin_csrf=roles['admin'];source=get('/api/topics/15/workspace',admin_cookie)
  target=post('/api/topics',admin_cookie,dict(name='隔离HTTP同口径导航目标',description='仅用于同条件导航核对',layout=[dict(model_id=c['model']['id'],span=c['span']) for c in source['cards']],is_public=True),admin_csrf)
  target_id=target['id'];options=get('/api/scopes',admin_cookie);config=dict(scope={'family':options['families'][0],'from':'2026-09-20','to':'2026-10-01'},reference_scope={'from':'2026-09-01','to':'2026-09-19'},primary_label='当前队列',reference_label='对照队列')
  for role,(cookie,csrf) in roles.items():
   ctx=get('/api/topics/15/workspace',cookie);run_before=post('/api/topics/15/run',cookie,dict(context_token=ctx['context_token'],config=config),csrf)
   definition=dict(topic_id=15,code='PAGE.HTTP.'+role.upper()+'.0001',title='隔离模拟交付阅读页 '+role,question='共同条件下交付表现如何，应该核查哪些对象？',cadence='每日模拟复查',sections=[dict(id='RESULT',title='原口径结果',role='result',note='原单位和分母保留',cards=[dict(slot=c['slot'],span=2,title='按原模型查证',note='阅读标题不改变指标定义') for c in ctx['cards']])],navigation=[dict(topic_id=target_id,label='同口径目标',mode='inherit'),dict(topic_id=2,label='订单交付重新选范围',mode='new')])
   preview=post('/api/topic-pages/preview',cookie,definition,csrf);body=dict(request_id=str(uuid.uuid4()),definition=definition,receipt=preview['receipt'],reason='保留共同条件核对个人阅读顺序')
   fetch('/api/topic-pages',cookie,'POST',body,status=403);saved=post('/api/topic-pages',cookie,body,csrf);url='/api/topic-pages/'+saved['id'];before=AuditEvent.objects.count();assert post('/api/topic-pages',cookie,body,csrf)['replayed'];assert AuditEvent.objects.count()==before
   read=get(url,cookie);assert read['ready'];assert post('/api/topics/15/run',cookie,dict(context_token=ctx['context_token'],config=config),csrf)==run_before
   nav=post(url+'/navigate',cookie,dict(version=1,receipt=read['receipt'],index=0,config=config),csrf);assert nav['config']==config and nav['topic_id']==target_id
   target_result=post('/api/topics/'+str(target_id)+'/run',cookie,dict(context_token=nav['context_token'],config=nav['config']),csrf);assert target_result['cards'][0]['primary']==run_before['cards'][0]['primary'];assert target_result['cards'][0]['reference']==run_before['cards'][0]['reference']
   reset=post(url+'/navigate',cookie,dict(version=1,receipt=read['receipt'],index=1,config=config),csrf);assert reset['config']==dict(scope={},reference_scope=None,primary_label='当前范围',reference_label='对照范围')
   raw,headers=fetch(url+'/export?'+urllib.parse.urlencode(dict(version=1,receipt=read['receipt'])),cookie);export=json.loads(raw);assert export['definition']==definition and not export['contains_business_values'] and 'receipt' not in export and headers['Cache-Control']=='no-store'
   new=definition.copy();new['question']='复查数据与定义是否仍适用？';preview=post('/api/topic-pages/preview',cookie,new,csrf);updated_body=dict(request_id=str(uuid.uuid4()),definition=new,receipt=preview['receipt'],reason='新增复查阅读问题，原口径不改',revision=1);updated=post(url,cookie,updated_body,csrf);assert updated['version']==2
   post(url,cookie,{**updated_body,'request_id':str(uuid.uuid4())},csrf,status=409);post(url+'/navigate',cookie,dict(version=1,receipt=read['receipt'],index=0,config=config),csrf,status=409)
   history=get(url+'/history',cookie);assert [x['number'] for x in history['rows']]==[2,1];assert get(url+'?version=1',cookie)['definition']['question']==definition['question']
   archive=dict(request_id=str(uuid.uuid4()),revision=2,archived=True,reason='隔离演练暂时归档个人页面');post(url+'/archive',cookie,archive,csrf);assert post(url+'/archive',cookie,archive,csrf)['replayed'];assert not get(url,cookie)['ready'];post(url+'/archive',cookie,{**archive,'request_id':str(uuid.uuid4()),'revision':3,'archived':False,'reason':'隔离核对后恢复个人页面'},csrf);assert get(url,cookie)['ready']
   if role!='admin':get(url,admin_cookie,status=404);get(url+'/history',admin_cookie,status=404);get(url+'/export?receipt=invalid',admin_cookie,status=404)
   cases.append(dict(role=role,page=saved['id'],versions=2,normal_result_unchanged=True,complete_navigation_preserved=True,explicit_new_range_verified=True))
  assert list(Record.objects.values_list('id','values','revision'))==before_facts;assert (TopicPage.objects.count()-base_pages,TopicPageVersion.objects.count()-base_versions,TopicPageRequest.objects.count()-base_requests)==(6,12,24)
  model=AnalysisModel.objects.get(pk=44);model.version+=1;model.save()
  for case in cases:
   cookie,csrf=roles[case['role']];url='/api/topic-pages/'+case['page'];d=get(url,cookie);assert d['stale'] and not d['ready'];post(url+'/navigate',cookie,dict(version=2,receipt=d['receipt'],index=0,config=config),csrf,status=409)
  assert sha(SOURCE/'data/platform.sqlite3')==main_sha
  proof=dict(success=True,native_http=True,six_roles=sorted(roles),cases=cases,source_facts_unchanged=True,main_database_unchanged=True,csrf_checked=True,private_even_admin=True,immutable_versions=True,idempotence_verified=True,pointer_and_dependency_drift_pause=True,metadata_only_export=True,assets_exact=True,non_database_package_files_exact=exact_files,restored_runtime=bool(a.archive),browser_acceptance=False,mobile_acceptance=False)
  a.proof.write_text(json.dumps(proof,ensure_ascii=False,indent=2)+'\n');print(json.dumps(proof,ensure_ascii=False))
 finally:
  child.terminate()
  try:child.wait(timeout=10)
  except subprocess.TimeoutExpired:child.kill();child.wait(timeout=10)
  log.close()
if __name__=='__main__':main()
