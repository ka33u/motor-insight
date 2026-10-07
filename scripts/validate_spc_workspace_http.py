"""Native HTTP on an isolated DB/runtime; does not render a browser or DOM."""
import argparse,csv,hashlib,io,json,os,socket,subprocess,sys,time,urllib.error,urllib.request,uuid,zipfile
from pathlib import Path
SOURCE=Path(__file__).resolve().parents[1]
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
 parser=argparse.ArgumentParser();parser.add_argument('--target',type=Path,default=SOURCE);parser.add_argument('--db',type=Path);parser.add_argument('--port',type=int,default=8895);parser.add_argument('--proof',type=Path,required=True);parser.add_argument('--archive',type=Path);a=parser.parse_args()
 root=a.target.resolve();db=a.db.resolve() if a.db else root/'data/platform.sqlite3';assert db!=SOURCE/'data/platform.sqlite3'
 main_hash=sha(SOURCE/'data/platform.sqlite3');archive_files=None
 if a.archive:
  with zipfile.ZipFile(a.archive) as z:
   manifest=json.loads(z.read('manifest.json'));archive_files=0
   for item in manifest['files']:
    if item['path']=='data/platform.sqlite3':continue
    assert sha(root/item['path'])==item['sha256']==sha(SOURCE/item['path']),item['path'];archive_files+=1
 os.environ['MOTOR_SQLITE_PATH']=str(db);os.environ['DJANGO_SETTINGS_MODULE']='config.settings';sys.path.insert(0,str(root))
 import django;django.setup()
 from django.conf import settings
 from django.test import Client
 from django.contrib.auth import get_user_model
 from app import access
 from app.models import Record,AuditEvent,SPCResultSnapshot
 assert settings.BASE_DIR==root
 from urllib.parse import urlencode
 with socket.socket() as s:assert s.connect_ex(('127.0.0.1',a.port))!=0
 env=os.environ.copy();env.pop('PYTHONPATH',None);env['PYTHONNOUSERSITE']='1';log=a.proof.with_suffix('.server.log').open('ab')
 child=subprocess.Popen([str(root/'.venv/bin/python'),str(root/'manage.py'),'runserver',f'127.0.0.1:{a.port}','--noreload'],cwd=root,env=env,stdout=log,stderr=subprocess.STDOUT,stdin=subprocess.DEVNULL)
 def fetch(path,cookie=None,method='GET',body=None,csrf=None,status=200):
  headers={'Cookie':cookie} if cookie else {}
  if csrf:headers.update({'X-CSRFToken':csrf,'Content-Type':'application/json'})
  request=urllib.request.Request(f'http://127.0.0.1:{a.port}'+path,data=json.dumps(body).encode() if body is not None else None,headers=headers,method=method)
  try:
   with urllib.request.urlopen(request,timeout=30) as r:actual=r.status;raw=r.read();response_headers=dict(r.headers)
  except urllib.error.HTTPError as e:actual=e.code;raw=e.read();response_headers=dict(e.headers)
  assert actual==status,(path,actual,raw[:250]);return raw,response_headers
 def get(path,cookie=None,status=200):return json.loads(fetch(path,cookie,status=status)[0])
 try:
  for _ in range(80):
   if child.poll() is not None:raise RuntimeError('Native server failed')
   try:get('/api/auth');break
   except urllib.error.URLError:time.sleep(.15)
  else:raise RuntimeError('Native server unavailable')
  index=fetch('/')[0].decode();assert '/static/spc_workspace.css?v=' in index
  for name in ('spc_workspace.js','spc_workspace.css','spc.js','topics.js','app.js'):assert fetch('/static/'+name)[0]==(root/'static'/name).read_bytes()
  get('/api/spc-analysis-views',status=401);get('/api/spc-result-snapshots',status=401)
  owner=get_user_model().objects.get(username='demo_quality');preexisting=list(SPCResultSnapshot.objects.filter(owner=owner).values_list('pk',flat=True));assert len(preexisting)==2
  facts=Record.objects.count();roles=[];captures=[]
  for user in get_user_model().objects.all():
   client=Client();client.force_login(user);client.get('/');session=client.cookies['sessionid'].value;csrf=client.cookies['csrftoken'].value;cookie='sessionid='+session+'; csrftoken='+csrf
   role=access.role(user);d=get('/api/spc/SPC2609-0004',cookie);assert d['coverage']['missing_sequences']==[54]
   before=AuditEvent.objects.count();get('/api/spc-analysis-views',cookie);get('/api/spc-result-snapshots',cookie);assert AuditEvent.objects.count()==before
   if user!=owner:get('/api/spc-result-snapshots/'+str(preexisting[0]),cookie,status=404)
   body=dict(request_id=str(uuid.uuid4()),code='SPC.HTTP.'+role.upper()+'.0004',name='合成原生HTTP检查 '+role,note='仅在隔离副本演练完整采样视角和冻结证据。',study_id=d['study']['id'],receipt=d['receipt'],display=dict(show_spec=False,decimals=8),topic_id=4)
   fetch('/api/spc-analysis-views',cookie,'POST',body,status=403)
   v=json.loads(fetch('/api/spc-analysis-views',cookie,'POST',body,csrf)[0])['view'];run=get('/api/spc-analysis-views/'+v['id']+'/run',cookie)
   body=dict(request_id=str(uuid.uuid4()),view_id=v['id'],revision=v['revision'],receipt=run['receipt'],name='合成冻结检查 '+role,note='固定整套79条观测及缺号，用于复查，不进行业务批准。')
   s=json.loads(fetch('/api/spc-result-snapshots',cookie,'POST',body,csrf)[0])['snapshot'];captured=get('/api/spc-result-snapshots/'+s['id']+'?page=2',cookie);assert captured['mode']=='snapshot' and len(captured['chart_points'])==79
   assert next(p for p in captured['chart_points'] if p['sequence']==55)['mr'] is None
   query=urlencode(dict(receipt=captured['receipt']));point=captured['chart_points'][0]['id']
   before=AuditEvent.objects.count();detail=get('/api/spc-result-snapshots/'+s['id']+'/points/'+point+'?'+query,cookie);get('/api/spc-result-snapshots/'+s['id']+'/sources?'+query,cookie)
   comparison=get('/api/spc-result-snapshots/'+s['id']+'/compare-current',cookie);assert comparison['state']=='same_observations'
   assert AuditEvent.objects.count()==before
   raw=fetch('/api/spc-result-snapshots/'+s['id']+'/export?'+query+'&page=2',cookie)[0];rows=list(csv.reader(io.StringIO(raw.decode('utf-8-sig'))));assert len(rows)==84 and len({r[0] for r in rows[5:]})==79
   exported=json.loads(fetch('/api/spc-result-snapshots/'+s['id']+'/export?'+query+'&format=json',cookie)[0]);assert len(exported['payload']['result']['points'])==79
   assert all('price_cents' not in r['values'] and 'cost_cents' not in r['values'] for r in exported['payload']['sources'])
   source=next(r for r in detail['sources'] if r['dataset']=='spc_observations' and r['key']==point)
   path=detail['original_base']+str(source['source_row_id'])+'?'+query
   if access.can_import(user):assert hashlib.sha256(fetch(path,cookie)[0]).hexdigest()==source['file_hash']
   else:fetch(path,cookie,status=403)
   catalog=get('/api/catalog',cookie);assert catalog['framework']['spc_workspace']['href']=='#spc-workspace'
   roles.append(role);captures.append(dict(role=role,points=79,source_count=s['source_count']))
  assert Record.objects.count()==facts==213441 and sha(SOURCE/'data/platform.sqlite3')==main_hash
  proof=dict(success=True,native_http=True,six_roles=sorted(roles),captures=captures,source_facts_unchanged=True,main_database_unchanged=True,
   csrf_checked=True,private_owner_enforced=True,complete_csv_json_checked=True,original_bytes_current_permission_checked=True,
   gaps_not_bridged=True,assets_exact=True,non_database_package_files_exact=archive_files,restored_runtime=bool(a.archive),
   browser_acceptance=False,mobile_acceptance=False)
  a.proof.write_text(json.dumps(proof,ensure_ascii=False,indent=2)+'\n');print(json.dumps(proof,ensure_ascii=False))
 finally:
  child.terminate()
  try:child.wait(timeout=10)
  except subprocess.TimeoutExpired:child.kill();child.wait(timeout=10)
  log.close()
if __name__=='__main__':main()
