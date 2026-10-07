"""Exercise private definition cards through native HTTP on a disposable copy."""
import argparse,hashlib,json,os,socket,subprocess,sys,time,urllib.error,urllib.request,uuid,zipfile
from pathlib import Path
SOURCE=Path(__file__).resolve().parents[1]
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
 p=argparse.ArgumentParser();p.add_argument('--root',type=Path,default=SOURCE);p.add_argument('--db',type=Path,required=True);p.add_argument('--port',type=int,required=True);p.add_argument('--proof',type=Path,required=True);p.add_argument('--archive',type=Path);a=p.parse_args();root=a.root.resolve();db=a.db.resolve();assert db!=SOURCE/'data/platform.sqlite3';main_hash=sha(SOURCE/'data/platform.sqlite3');files=0
 if a.archive:
  with zipfile.ZipFile(a.archive) as z:
   manifest=json.loads(z.read('manifest.json'))
   for item in manifest['files']:
    name=item['path']
    if name!='data/platform.sqlite3':assert sha(root/name)==item['sha256']==sha(SOURCE/name),name;files+=1
   assert files==len(manifest['files'])-1
 os.environ['DJANGO_SETTINGS_MODULE']='config.settings';os.environ['MOTOR_SQLITE_PATH']=str(db);sys.path.insert(0,str(root));import django;django.setup()
 from django.conf import settings
 from django.test import Client
 from django.contrib.auth import get_user_model
 from app import access
 from app.models import Record,AuditEvent,AnalysisModel,AnalysisModelCard,AnalysisModelCardVersion,SPCResultSnapshot
 assert settings.BASE_DIR==root
 with socket.socket() as s:assert s.connect_ex(('127.0.0.1',a.port))!=0
 env=os.environ.copy();env.pop('PYTHONPATH',None);env['PYTHONNOUSERSITE']='1';log=a.proof.with_suffix('.server.log').open('ab');child=subprocess.Popen([str(root/'.venv/bin/python'),str(root/'manage.py'),'runserver',f'127.0.0.1:{a.port}','--noreload'],cwd=root,env=env,stdout=log,stderr=subprocess.STDOUT,stdin=subprocess.DEVNULL)
 def fetch(path,cookie=None,method='GET',body=None,csrf=None,status=200):
  headers={'Cookie':cookie} if cookie else {}
  if body is not None:headers['Content-Type']='application/json'
  if csrf:headers['X-CSRFToken']=csrf
  request=urllib.request.Request(f'http://127.0.0.1:{a.port}'+path,data=json.dumps(body).encode() if body is not None else None,headers=headers,method=method)
  try:
   with urllib.request.urlopen(request,timeout=30) as r:code=r.status;raw=r.read();response_headers=dict(r.headers)
  except urllib.error.HTTPError as e:code=e.code;raw=e.read();response_headers=dict(e.headers)
  assert code==status,(path,code,raw[:250]);return raw,response_headers
 def get(path,cookie=None,status=200):return json.loads(fetch(path,cookie,status=status)[0])
 def post(path,cookie,body,csrf,status=200):return json.loads(fetch(path,cookie,'POST',body,csrf,status)[0])
 try:
  for _ in range(80):
   if child.poll() is not None:raise RuntimeError('Native server failed')
   try:get('/api/auth');break
   except urllib.error.URLError:time.sleep(.15)
  else:raise RuntimeError('Native server unavailable')
  for name in ('model_cards.js','topics.js','app.js'):assert fetch('/static/'+name)[0]==(root/'static'/name).read_bytes()
  get('/api/model-cards',status=401);get('/api/model-cards/preview/1',status=401)
  facts=Record.objects.count();base_cards=AnalysisModelCard.objects.count();base_versions=AnalysisModelCardVersion.objects.count();base_audits=AuditEvent.objects.count();roles=[];created=[];accounts={}
  for user in get_user_model().objects.all():
   role=access.role(user);client=Client();client.force_login(user);client.get('/');csrf=client.cookies['csrftoken'].value;cookie='sessionid='+client.cookies['sessionid'].value+'; csrftoken='+csrf;accounts[role]=(cookie,csrf)
   before=AuditEvent.objects.count();directory=get('/api/model-cards',cookie);assert directory['total']==(1 if role in {'admin','analyst'} else 0);preview=get('/api/model-cards/preview/1',cookie);assert AuditEvent.objects.count()==before
   body=dict(request_id=str(uuid.uuid4()),code='MODEL.HTTP.'+role.upper()+'.0001',name='隔离合成模型口径卡 '+role,question='订单状态的记录分布是什么？',reader=role,object_grain='一行订单来源记录，按状态归组',time_scope='当前合成资料，实际范围由模型筛选确定',limitations='记录计数不等于电机台数，不用于实际批准',review_on=None,model_id=1,receipt=preview['receipt'])
   fetch('/api/model-cards',cookie,'POST',body,status=403);d=post('/api/model-cards',cookie,body,csrf)['card'];url='/api/model-cards/'+d['id'];before=AuditEvent.objects.count();assert post('/api/model-cards',cookie,body,csrf)['repeated'];assert AuditEvent.objects.count()==before
   run=get(url+'/run',cookie);assert run['result_mode']=='current_data' and run['result']['matched']==Record.objects.filter(dataset='orders').count();get(url,cookie);get(url+'/history',cookie);assert AuditEvent.objects.count()==before
   changed={**body,'request_id':str(uuid.uuid4()),'revision':1,'question':'复查同范围订单状态分布','receipt':get('/api/model-cards/preview/1',cookie)['receipt']};d=post(url,cookie,changed,csrf)['card'];assert d['revision']==2
   stale={**changed,'request_id':str(uuid.uuid4())};post(url,cookie,stale,csrf,status=409)
   history=get(url+'/history',cookie);assert history['total']==2 and history['rows'][0]['metadata']['question']!=history['rows'][1]['metadata']['question']
   archive=dict(request_id=str(uuid.uuid4()),revision=2,archived=True);d=post(url+'/archive',cookie,archive,csrf)['card'];assert d['revision']==3 and d['current_archived'];assert post(url+'/archive',cookie,archive,csrf)['repeated'];get(url+'/run',cookie,status=409)
   d=post(url+'/archive',cookie,dict(request_id=str(uuid.uuid4()),revision=3,archived=False),csrf)['card'];assert d['revision']==4;get(url+'/run',cookie)
   raw,headers=fetch(url+'/export',cookie);export=json.loads(raw);assert len(export['versions'])==4 and 'result' not in export and headers['Cache-Control']=='no-store' and 'attachment;' in headers['Content-Disposition']
   snap=get('/api/spc-result-snapshots',cookie);assert snap['total']==(2 if role=='quality' else 0)
   if snap['total']:assert len(get('/api/spc-result-snapshots/'+snap['rows'][0]['id'],cookie)['chart_points'])==80
   msa=get('/api/msa',cookie);assert len(msa['rows'])==11
   catalog=get('/api/catalog',cookie);assert catalog['framework']['model_cards']['href']=='#model-cards'
   roles.append(role);created.append(dict(role=role,id=d['id'],versions=4,matched=run['result']['matched']))
  admin_cookie,admin_csrf=accounts['admin'];peer=next(d for d in created if d['role']=='analyst');get('/api/model-cards/'+peer['id'],admin_cookie,status=404)
  m=AnalysisModel.objects.get(pk=1);m.version+=1;m.name+=' · 隔离定义变化演练';m.save()
  for item in created:
   cookie,_=accounts[item['role']];url='/api/model-cards/'+item['id'];assert get(url,cookie)['card']['definition_state']=='changed';get(url+'/run',cookie,status=409);assert get(url+'/history',cookie)['rows'][0]['binding']['source_model']['version']==1
  assert Record.objects.count()==facts==214523 and SPCResultSnapshot.objects.count()==2;assert AnalysisModelCard.objects.count()==base_cards+6 and AnalysisModelCardVersion.objects.count()==base_versions+24 and AuditEvent.objects.count()==base_audits+30
  assert sha(SOURCE/'data/platform.sqlite3')==main_hash
  proof=dict(success=True,native_http=True,six_roles=sorted(roles),cases=created,csrf_checked=True,private_even_admin=True,request_replay_no_duplicates=True,stale_revision_rejected=True,archive_restore_verified=True,definition_drift_pauses=True,full_json_history=True,old_spc_and_msa_readable=True,source_facts_unchanged=True,main_database_unchanged=True,assets_exact=True,non_database_package_files_exact=files,restored_runtime=bool(a.archive),browser_acceptance=False,mobile_acceptance=False)
  a.proof.write_text(json.dumps(proof,ensure_ascii=False,indent=2)+'\n');print(json.dumps(proof,ensure_ascii=False))
 finally:
  child.terminate()
  try:child.wait(timeout=10)
  except subprocess.TimeoutExpired:child.kill();child.wait(timeout=10)
  log.close()
if __name__=='__main__':main()
