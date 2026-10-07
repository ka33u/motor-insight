"""Native HTTP in a disposable database. No browser, production connection or passwords."""
import argparse,hashlib,json,os,socket,subprocess,sys,time,urllib.error,urllib.parse,urllib.request,zipfile
from pathlib import Path
SOURCE=Path(__file__).resolve().parents[1]
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
 p=argparse.ArgumentParser();p.add_argument('--root',type=Path,default=SOURCE);p.add_argument('--db',type=Path,required=True);p.add_argument('--port',type=int,required=True);p.add_argument('--proof',type=Path,required=True);p.add_argument('--archive',type=Path);a=p.parse_args();root=a.root.resolve();db=a.db.resolve();assert db!=SOURCE/'data/platform.sqlite3';main_sha=sha(SOURCE/'data/platform.sqlite3');exact=0
 if a.archive:
  with zipfile.ZipFile(a.archive) as z:
   for item in json.loads(z.read('manifest.json'))['files']:
    if item['path']!='data/platform.sqlite3':assert sha(root/item['path'])==item['sha256']==sha(SOURCE/item['path']);exact+=1
 os.environ['DJANGO_SETTINGS_MODULE']='config.settings';os.environ['MOTOR_SQLITE_PATH']=str(db);sys.path.insert(0,str(root));import django;django.setup()
 from django.conf import settings
 from django.test import Client
 from django.contrib.auth import get_user_model
 from app.models import Record,AuditEvent
 from app import access
 assert settings.BASE_DIR==root
 with socket.socket() as s:assert s.connect_ex(('127.0.0.1',a.port))!=0
 env=os.environ.copy();env.pop('PYTHONPATH',None);env['PYTHONNOUSERSITE']='1';a.proof.parent.mkdir(exist_ok=True,parents=True);logpath=a.proof.with_suffix('.server.log');log=logpath.open('ab');logpath.chmod(0o600);child=subprocess.Popen([str(root/'.venv/bin/python'),str(root/'manage.py'),'runserver',f'127.0.0.1:{a.port}','--noreload'],cwd=root,env=env,stdout=log,stderr=subprocess.STDOUT,stdin=subprocess.DEVNULL)
 def fetch(path,cookie=None,status=200):
  req=urllib.request.Request(f'http://127.0.0.1:{a.port}'+path,headers={'Cookie':cookie} if cookie else {})
  try:
   with urllib.request.urlopen(req,timeout=40) as r:code=r.status;raw=r.read();headers=dict(r.headers)
  except urllib.error.HTTPError as e:code=e.code;raw=e.read();headers=dict(e.headers)
  assert code==status,(path.split('?')[0],code);return raw,headers
 def get(path,cookie=None,status=200):return json.loads(fetch(path,cookie,status)[0])
 try:
  for _ in range(100):
   if child.poll() is not None:raise RuntimeError('隔离效率服务启动失败')
   try:get('/api/auth');break
   except urllib.error.URLError:time.sleep(.1)
  else:raise RuntimeError('隔离效率服务无法连接')
  index=fetch('/')[0].decode();assert '/static/oee.css?v=' in index and '/static/oee.js?v=' in index
  for name in ('oee.js','oee.css','app.js'):assert fetch('/static/'+name)[0]==(root/'static'/name).read_bytes()
  get('/api/oee',status=401);before=list(Record.objects.values_list('id','values','revision','record_hash'));roles={};cases=[];audit_count=AuditEvent.objects.count()
  for user in get_user_model().objects.all():
   role=access.role(user);client=Client();client.force_login(user);client.get('/');roles[role]='sessionid='+client.cookies['sessionid'].value
  for role,cookie in roles.items():
   listing=get('/api/oee',cookie);assert len(listing['rows'])==10
   for study in listing['rows']:
    key=study['id'];d=get('/api/oee/'+key,cookie);q=urllib.parse.urlencode(dict(receipt=d['receipt']));sources=get('/api/oee/'+key+'/sources?'+q,cookie);assert sources['total']==d['source_count'];assert sources['can_download_original']==(role=='admin');assert 'employee_id' not in d['resource'];assert all('price_cents' not in p for p in d['products'].values())
    if d['windows']:get('/api/oee/'+key+'/windows/'+d['windows'][0]['id']+'?'+q,cookie)
    for fmt in ('csv','json'):
     raw,headers=fetch('/api/oee/'+key+'/export?'+q+'&format='+fmt,cookie);assert headers['Cache-Control']=='no-store' and 'attachment;' in headers['Content-Disposition']
     if fmt=='json':e=json.loads(raw);assert 'receipt' not in e and e['result']['summary']==d['summary'] and len(e['inputs']['oee_outputs'])==study['output_count']
     else:assert raw.startswith(b'\xef\xbb\xbf') and key in raw.decode()
   cases.append(role)
  admin=get('/api/oee/OE-260925-001',roles['admin']);get('/api/oee/OE-260925-001?'+urllib.parse.urlencode(dict(receipt=admin['receipt'])),roles['viewer'],409);get('/api/oee/OE-260925-001?family=YE3',roles['viewer'],400)
  assert list(Record.objects.values_list('id','values','revision','record_hash'))==before;assert AuditEvent.objects.count()-audit_count==120;assert sha(SOURCE/'data/platform.sqlite3')==main_sha
  proof=dict(success=True,native_http=True,six_roles=sorted(cases),case_reads=60,complete_exports=120,source_facts_unchanged=True,main_database_unchanged=True,assets_exact=True,non_database_package_files_exact=exact,restored_runtime=bool(a.archive),original_permission_separate=True,receipt_bound_to_account=True,browser_acceptance=False,mobile_acceptance=False,actual_browser_download_acceptance=False);a.proof.write_text(json.dumps(proof,ensure_ascii=False,indent=2)+'\n');print(json.dumps(proof,ensure_ascii=False))
 finally:
  child.terminate()
  try:child.wait(timeout=8)
  except subprocess.TimeoutExpired:child.kill();child.wait()
  log.close()
if __name__=='__main__':main()
