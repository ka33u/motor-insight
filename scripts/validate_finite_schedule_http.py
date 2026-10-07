"""Native HTTP only, disposable DB, no browser/DOM/download automation."""
import argparse,csv,hashlib,io,json,os,socket,sqlite3,subprocess,sys,time,urllib.error,urllib.request,zipfile
from pathlib import Path
from urllib.parse import urlencode
SOURCE=Path(__file__).resolve().parents[1]
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
 p=argparse.ArgumentParser();p.add_argument('--root',type=Path,default=SOURCE);p.add_argument('--db',type=Path,required=True);p.add_argument('--port',type=int,required=True);p.add_argument('--proof',type=Path,required=True);p.add_argument('--archive',type=Path);a=p.parse_args();root=a.root.resolve();db=a.db.resolve();assert db!=SOURCE/'data/platform.sqlite3';main_hash=sha(SOURCE/'data/platform.sqlite3');files=0
 if a.archive:
  with zipfile.ZipFile(a.archive) as z:
   for item in json.loads(z.read('manifest.json'))['files']:
    if item['path']!='data/platform.sqlite3':assert sha(root/item['path'])==item['sha256']==sha(SOURCE/item['path']);files+=1
 os.environ['DJANGO_SETTINGS_MODULE']='config.settings';os.environ['MOTOR_SQLITE_PATH']=str(db);sys.path.insert(0,str(root));import django;django.setup()
 from django.conf import settings
 from django.test import Client
 from django.contrib.auth import get_user_model
 from app import access
 from app.models import Record,AuditEvent
 assert settings.BASE_DIR==root
 with socket.socket() as s:assert s.connect_ex(('127.0.0.1',a.port))!=0
 env=os.environ.copy();env.pop('PYTHONPATH',None);env['PYTHONNOUSERSITE']='1';log_path=a.proof.with_suffix('.server.log');log=log_path.open('ab');log_path.chmod(0o600);child=subprocess.Popen([str(root/'.venv/bin/python'),str(root/'manage.py'),'runserver',f'127.0.0.1:{a.port}','--noreload'],cwd=root,env=env,stdout=log,stderr=subprocess.STDOUT,stdin=subprocess.DEVNULL)
 def fetch(path,cookie=None,method='GET',status=200):
  request=urllib.request.Request(f'http://127.0.0.1:{a.port}'+path,headers={'Cookie':cookie} if cookie else {},method=method,data=b'{}' if method=='POST' else None)
  try:
   with urllib.request.urlopen(request,timeout=30) as r:code=r.status;raw=r.read();headers=dict(r.headers)
  except urllib.error.HTTPError as e:code=e.code;raw=e.read();headers=dict(e.headers)
  assert code==status,(path.split('?')[0],code,raw[:100]);return raw,headers
 def get(path,cookie=None,status=200):return json.loads(fetch(path,cookie,status=status)[0])
 try:
  for _ in range(80):
   if child.poll() is not None:raise RuntimeError('Native server failed')
   try:get('/api/auth');break
   except urllib.error.URLError:time.sleep(.15)
  else:raise RuntimeError('Native server unavailable')
  assert 'finite_schedule.css?v=' in fetch('/')[0].decode()
  for name in ('finite_schedule.js','finite_schedule.css','app.js'):assert fetch('/static/'+name)[0]==(root/'static'/name).read_bytes()
  facts=Record.objects.count();initial=AuditEvent.objects.count();get('/api/finite-schedule',status=401);roles=[];exported=0;last=None
  for user in get_user_model().objects.all():
   role=access.role(user);client=Client();client.force_login(user);client.get('/');cookie='sessionid='+client.cookies['sessionid'].value+'; csrftoken='+client.cookies['csrftoken'].value
   assert len(get('/api/finite-schedule',cookie)['rows'])==6;url='/api/finite-schedule/SP-261002-001';v=get(url,cookie);assert v['summary']['qty']==50 and v['summary']['scheduled_tasks']==198;query=urlencode(dict(receipt=v['receipt'],policy=v['policy']));before=AuditEvent.objects.count()
   t=v['tasks'][0];point=get(url+'/tasks/'+t['id']+'?'+query,cookie);assert point['row']==t;assert point['can_download_original']==(role=='admin')
   sources=[]
   for page in range(1,(v['source_count']+39)//40+1):sources.extend(get(url+'/sources?'+query+'&page='+str(page),cookie)['rows'])
   assert len(sources)==len({(s['dataset'],s['key']) for s in sources})==v['source_count']
   for s in sources:
    r=Record.objects.select_related('source_row__batch').get(dataset=s['dataset'],business_key=s['key']);assert (s['filename'],s['sheet'],s['row'],s['source_row_id'])==(r.source_row.batch.filename,r.source_row.sheet,r.source_row.row_number,r.source_row_id)
   assert AuditEvent.objects.count()==before
   for n in range(1,7):
    r=get('/api/finite-schedule/SP-261002-'+f'{n:03}',cookie);assert r['state']==('paused' if n>=5 else 'trial')
   tight=get('/api/finite-schedule/SP-261002-002',cookie);assert tight['summary']['late_jobs']==6 and tight['summary']['blocked_jobs']==0
   missing=get('/api/finite-schedule/SP-261002-004',cookie);assert missing['summary']['blocked_tasks']==3 and missing['summary']['blocked_jobs']==1
   jr,jh=fetch(url+'/export?'+query+'&format=json',cookie);doc=json.loads(jr);assert doc['result']['tasks']==v['tasks'] and 'receipt' not in doc and jh['Cache-Control']=='no-store'
   cr,ch=fetch(url+'/export?'+query+'&format=csv',cookie);rows=list(csv.reader(io.StringIO(cr.decode('utf-8-sig'))));assert len(rows[6:-1])==198 and cr.startswith(b'\xef\xbb\xbf');assert AuditEvent.objects.count()==before+2;exported+=2
   event=AuditEvent.objects.latest('id');assert event.detail['file_sha256']==hashlib.sha256(cr).hexdigest()
   fetch(url+'/export?'+query+'&filter=unbounded',cookie,status=400);fetch(url+'/export?'+query,cookie,'POST',status=403);fetch(url+'/export?'+query+'&policy=priority',cookie,status=400);fetch(url+'/export?'+urlencode(dict(receipt=v['receipt'],policy='priority')),cookie,status=409)
   assert AuditEvent.objects.count()==before+2;roles.append(dict(role=role,sources=len(sources),tasks=198,original_privilege=role=='admin'));last=(url,query,cookie)
   paused_url='/api/finite-schedule/SP-261002-005';paused=get(paused_url,cookie);pq=urlencode(dict(receipt=paused['receipt'],policy=paused['policy']));pr,_=fetch(paused_url+'/export?'+pq+'&format=json',cookie);pd=json.loads(pr);assert pd['result']['summary'] is None and len(pd['inputs']['schedule_tasks'])==198
   pc,_=fetch(paused_url+'/export?'+pq+'&format=csv',cookie);assert '排程、完成、等待与负载未计算' in pc.decode('utf-8-sig');exported+=2
  url,query,cookie=last
  with sqlite3.connect(db) as c:
   key,name=c.execute("SELECT id,filename FROM app_importbatch WHERE filename='36_有限资源试排_模拟.xlsx'").fetchone();c.execute('UPDATE app_importbatch SET filename=? WHERE id=?',('changed-synthetic.xlsx',key))
  try:fetch(url+'/export?'+query,cookie,status=409)
  finally:
   with sqlite3.connect(db) as c:c.execute('UPDATE app_importbatch SET filename=? WHERE id=?',(name,key))
  get(url+'?'+query,cookie);assert Record.objects.count()==facts==220529;assert AuditEvent.objects.count()==initial+24;assert sha(SOURCE/'data/platform.sqlite3')==main_hash
  proof=dict(success=True,native_http=True,roles=roles,result_exports=exported,all_tasks_and_sources_exact=True,failed_exports_no_audit=True,csrf_checked=True,source_file_change_rejects_old_receipt=True,injected_change_undone=True,source_roles_original_guard=True,assets_exact=True,main_unchanged=True,non_database_package_files_exact=files,restored_runtime=bool(a.archive),browser_acceptance=False,mobile_acceptance=False,actual_download_acceptance=False)
  a.proof.write_text(json.dumps(proof,ensure_ascii=False,indent=2)+'\n');print(json.dumps(proof,ensure_ascii=False))
 finally:
  child.terminate()
  try:child.wait(timeout=10)
  except subprocess.TimeoutExpired:child.kill();child.wait(timeout=10)
  log.close()
if __name__=='__main__':main()
