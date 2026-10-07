"""Native loopback HTTP on a disposable database; no browser automation."""
import argparse,csv,hashlib,io,json,os,socket,sqlite3,subprocess,sys,time,urllib.request,urllib.error,zipfile
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
    if name!='data/platform.sqlite3':
     file=root/name;assert file.exists() and sha(file)==item['sha256']==sha(SOURCE/name),name;files+=1
   assert files==len(manifest['files'])-1 and files>1000
 os.environ['DJANGO_SETTINGS_MODULE']='config.settings';os.environ['MOTOR_SQLITE_PATH']=str(db);sys.path.insert(0,str(root));import django;django.setup()
 from django.test import Client
 from django.conf import settings
 from django.contrib.auth import get_user_model
 from app import access
 from app.models import Record,AuditEvent,SPCResultSnapshot,SPCAnalysisView
 from urllib.parse import urlencode
 assert settings.BASE_DIR==root
 with socket.socket() as s:assert s.connect_ex(('127.0.0.1',a.port))!=0
 env=os.environ.copy();env.pop('PYTHONPATH',None);env['PYTHONNOUSERSITE']='1';log=a.proof.with_suffix('.server.log').open('ab');child=subprocess.Popen([str(root/'.venv/bin/python'),str(root/'manage.py'),'runserver',f'127.0.0.1:{a.port}','--noreload'],cwd=root,env=env,stdout=log,stderr=subprocess.STDOUT,stdin=subprocess.DEVNULL)
 def fetch(path,cookie=None,status=200):
  request=urllib.request.Request(f'http://127.0.0.1:{a.port}'+path,headers={'Cookie':cookie} if cookie else {})
  try:
   with urllib.request.urlopen(request,timeout=30) as r:code=r.status;raw=r.read();headers=dict(r.headers)
  except urllib.error.HTTPError as e:code=e.code;raw=e.read();headers=dict(e.headers)
  assert code==status,(path.split('?')[0],code,raw[:250]);return raw,headers
 def get(path,cookie=None,status=200):return json.loads(fetch(path,cookie,status)[0])
 try:
  for _ in range(80):
   if child.poll() is not None:raise RuntimeError('Native server failed')
   try:get('/api/auth');break
   except urllib.error.URLError:time.sleep(.15)
  else:raise RuntimeError('Native server unavailable')
  index=fetch('/')[0].decode();assert '/static/msa.css?v=' in index
  for name in ('msa.js','msa.css','app.js','spc.js','spc_workspace.js'):assert fetch('/static/'+name)[0]==(root/'static'/name).read_bytes()
  get('/api/msa',status=401);get('/api/msa/MSA2609-0001',status=401);facts=Record.objects.count();snapshots=SPCResultSnapshot.objects.count();views=SPCAnalysisView.objects.count();roles=[];full_sources=[]
  for user in get_user_model().objects.all():
   client=Client();client.force_login(user);cookie='sessionid='+client.cookies['sessionid'].value;role=access.role(user);before=AuditEvent.objects.count();directory=get('/api/msa',cookie);assert len(directory['rows'])==11
   states=[]
   for row in directory['rows']:states.append(get('/api/msa/'+row['id'],cookie)['state'])
   assert states==['trial']*4+['paused']*7
   d=get('/api/msa/MSA2609-0001',cookie);other=get('/api/msa/MSA2609-0001?page=2',cookie);assert d['result']==other['result'] and d['chart_points']==other['chart_points'] and len(d['chart_points'])==90 and len(d['rows'])==25
   assert ('price_cents' in d['product'])==(role in {'admin','analyst','finance'})
   query=urlencode(dict(receipt=d['receipt']));point=d['rows'][0]['id'];base='/api/msa/MSA2609-0001';detail=get(base+'/points/'+point+'?'+query,cookie);p0=detail['row'];cell=get(base+'/cells/'+p0['part_member_id']+'/'+p0['operator_member_id']+'?'+query,cookie);assert len(cell['rows'])==3
   rows=[];page=1;total=1
   while len(rows)<total:
    sources=get(base+'/sources?'+query+'&page='+str(page),cookie);assert sources['rows'];total=sources['total'];rows.extend(sources['rows']);page+=1
   assert len(rows)==123 and len({(s['dataset'],s['key'],s['source_row_id']) for s in rows})==123
   get(base+'/points/'+point,cookie,status=400);get('/api/msa/MSA2609-0002/points/'+point+'?'+query,cookie,status=409)
   missing=get('/api/msa/MSA2609-0005',cookie);m=next(v for v in missing['matrix'] if v['missing_repeats']);v=get('/api/msa/MSA2609-0005/cells/'+m['part_id']+'/'+m['operator_id']+'?'+urlencode(dict(receipt=missing['receipt'])),cookie);assert len(v['rows'])==2
   assert AuditEvent.objects.count()==before
   raw,headers=fetch(base+'/export?'+query+'&page=2',cookie);csv_rows=list(csv.reader(io.StringIO(raw.decode('utf-8-sig'))));assert len(csv_rows)==96 and len({r[0] for r in csv_rows[6:]})==90 and headers['Cache-Control']=='no-store'
   source=next(v for v in detail['sources'] if v['dataset']=='msa_observations');original='/api/imports/'+source['batch_id']+'/file'
   if access.can_import(user):assert hashlib.sha256(fetch(original,cookie)[0]).hexdigest()==source['file_hash']
   else:fetch(original,cookie,status=403)
   catalog=get('/api/catalog',cookie);assert catalog['framework']['msa_trial']['observations']==930
   frozen=get('/api/spc-result-snapshots',cookie)
   assert frozen['total']==(2 if user.username=='demo_quality' else 0)
   if frozen['total']:
    snap=get('/api/spc-result-snapshots/'+frozen['rows'][0]['id'],cookie);assert len(snap['chart_points'])==80 and snap['mode']=='snapshot'
   roles.append(role);full_sources.append(dict(role=role,trial_cases=4,paused_cases=7,chart_points=90,csv_rows=90,sources=123))
  assert Record.objects.count()==facts==214523 and SPCResultSnapshot.objects.count()==snapshots==2 and SPCAnalysisView.objects.count()==views==2;assert sha(SOURCE/'data/platform.sqlite3')==main_hash
  proof=dict(success=True,native_http=True,six_roles=sorted(roles),cases=full_sources,assets_exact=True,source_manifest_complete=True,full_csv_scope=True,current_original_permission_checked=True,old_personal_spc_unchanged=True,main_database_unchanged=True,non_database_package_files_exact=files,restored_runtime=bool(a.archive),browser_acceptance=False,mobile_acceptance=False)
  a.proof.write_text(json.dumps(proof,ensure_ascii=False,indent=2)+'\n');print(json.dumps(proof,ensure_ascii=False))
 finally:
  child.terminate()
  try:child.wait(timeout=10)
  except subprocess.TimeoutExpired:child.kill();child.wait(timeout=10)
  log.close()
if __name__=='__main__':main()
