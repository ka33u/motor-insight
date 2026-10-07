"""Native HTTP result/evidence checks on a disposable database, without a browser."""
import argparse,hashlib,json,os,socket,sqlite3,subprocess,sys,time,urllib.error,urllib.request,uuid,zipfile
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
 from app.models import Record,AuditEvent,AnalysisModelCard,AnalysisModelCardVersion
 from urllib.parse import urlencode
 assert settings.BASE_DIR==root
 with socket.socket() as s:assert s.connect_ex(('127.0.0.1',a.port))!=0
 env=os.environ.copy();env.pop('PYTHONPATH',None);env['PYTHONNOUSERSITE']='1';log_path=a.proof.with_suffix('.server.log');log=log_path.open('ab');log_path.chmod(0o600);child=subprocess.Popen([str(root/'.venv/bin/python'),str(root/'manage.py'),'runserver',f'127.0.0.1:{a.port}','--noreload'],cwd=root,env=env,stdout=log,stderr=subprocess.STDOUT,stdin=subprocess.DEVNULL)
 def fetch(path,cookie=None,method='GET',body=None,csrf=None,status=200):
  headers={'Cookie':cookie} if cookie else {}
  if body is not None:headers['Content-Type']='application/json'
  if csrf:headers['X-CSRFToken']=csrf
  request=urllib.request.Request(f'http://127.0.0.1:{a.port}'+path,data=json.dumps(body).encode() if body is not None else None,headers=headers,method=method)
  try:
   with urllib.request.urlopen(request,timeout=30) as r:code=r.status;raw=r.read();response_headers=dict(r.headers)
  except urllib.error.HTTPError as e:code=e.code;raw=e.read();response_headers=dict(e.headers)
  assert code==status,(path.split('?')[0],code,raw[:120]);return raw,response_headers
 def get(path,cookie=None,status=200):return json.loads(fetch(path,cookie,status=status)[0])
 try:
  for _ in range(80):
   if child.poll() is not None:raise RuntimeError('Native server failed')
   try:get('/api/auth');break
   except urllib.error.URLError:time.sleep(.15)
  else:raise RuntimeError('Native server unavailable')
  assert 'model_card_results.css?v=' in fetch('/')[0].decode()
  for name in ('model_card_results.js','model_card_results.css','model_cards.js','app.js'):assert fetch('/static/'+name)[0]==(root/'static'/name).read_bytes()
  facts=Record.objects.count();base=(AnalysisModelCard.objects.count(),AnalysisModelCardVersion.objects.count(),AuditEvent.objects.count());get('/api/model-cards',status=401);roles=[];last=None;accounts={}
  for user in get_user_model().objects.all():
   role=access.role(user);client=Client();client.force_login(user);client.get('/');csrf=client.cookies['csrftoken'].value;cookie='sessionid='+client.cookies['sessionid'].value+'; csrftoken='+csrf;accounts[role]=cookie
   pv=get('/api/model-cards/preview/1',cookie);body=dict(request_id=str(uuid.uuid4()),code='MODEL.RESULT.HTTP.'+role.upper(),name='隔离结果阅读检查',question='同范围订单状态、数量与来源怎样对应？',reader=role,object_grain='订单来源行',time_scope='当前合成资料，保留实际模型条件',limitations='记录数不当作整机台数，不用于审批',review_on=None,model_id=1,receipt=pv['receipt'])
   fetch('/api/model-cards',cookie,'POST',body,status=403);c=json.loads(fetch('/api/model-cards',cookie,'POST',body,csrf)[0])['card'];url='/api/model-cards/'+c['id'];before=AuditEvent.objects.count();v=get(url+'/run',cookie);s=v['reading']['summary'];assert s['value']==150 and s['source_rows']==v['result']['matched']==150
   query=urlencode(dict(receipt=v['reading']['receipt']));rows=[]
   for page in range(1,6):
    d=get(url+'/evidence?'+query+'&page='+str(page),cookie);assert d['total']==150;rows.extend(d['rows'])
   assert len(rows)==len({r['values']['id'] for r in rows})==150
   provenance={rec.business_key:dict(file=rec.source_row.batch.filename,sheet=rec.source_row.sheet,row=rec.source_row.row_number) for rec in Record.objects.filter(dataset='orders').select_related('source_row__batch')}
   assert all(r['source']==provenance[r['values']['id']] for r in rows)
   group=v['result']['rows'][0];d=get(url+'/evidence?'+query+'&'+urlencode(dict(group=group['dimension'])),cookie);assert d['total']==group['row_count'];get(url+'/evidence',cookie,status=400);get(url+'/evidence?'+query+'&group=unknown',cookie,status=400);assert AuditEvent.objects.count()==before
   catalog=get('/api/catalog',cookie);assert catalog['framework']['model_result_reading']['href']=='#model-cards';roles.append(dict(role=role,source_rows=150,group_sources_match=True));last=(url,query,cookie)
  url,query,cookie=last;get(url+'/evidence?'+query,accounts['admin'],status=404)
  # Inject and undo a source-value change on this copy. It must invalidate the
  # old scope even when the source count and the card definition do not change.
  with sqlite3.connect(db) as con:
   key,raw=con.execute("SELECT id,\"values\" FROM app_record WHERE dataset='orders' LIMIT 1").fetchone();changed=json.loads(raw);changed['status']='隔离资料更正演练';con.execute('UPDATE app_record SET "values"=? WHERE id=?',(json.dumps(changed,ensure_ascii=False),key))
  try:get(url+'/evidence?'+query,cookie,status=409)
  finally:
   with sqlite3.connect(db) as con:con.execute('UPDATE app_record SET "values"=? WHERE id=?',(raw,key))
  get(url+'/evidence?'+query,cookie)
  assert Record.objects.count()==facts==214523 and (AnalysisModelCard.objects.count(),AnalysisModelCardVersion.objects.count(),AuditEvent.objects.count())==(base[0]+6,base[1]+6,base[2]+6) and sha(SOURCE/'data/platform.sqlite3')==main_hash
  proof=dict(success=True,native_http=True,six_roles=roles,csrf_checked=True,private_even_admin=True,all_150_sources_paginated=True,group_source_scope_exact=True,current_data_change_rejects_old_receipt=True,injected_change_undone=True,read_does_not_create_audit=True,assets_exact=True,main_database_unchanged=True,non_database_package_files_exact=files,restored_runtime=bool(a.archive),browser_acceptance=False,mobile_acceptance=False)
  a.proof.write_text(json.dumps(proof,ensure_ascii=False,indent=2)+'\n');print(json.dumps(proof,ensure_ascii=False))
 finally:
  child.terminate()
  try:child.wait(timeout=10)
  except subprocess.TimeoutExpired:child.kill();child.wait(timeout=10)
  log.close()
if __name__=='__main__':main()
