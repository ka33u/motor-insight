"""Rehearse native APIs against an isolated backup of the complete simulated DB."""
import csv,hashlib,io,json,os,sqlite3,sys,tempfile,time,uuid
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def facts(db):
 h=hashlib.sha256()
 for r in db.execute('SELECT id,dataset,business_key,"values",record_hash,revision,source_row_id,updated_at FROM app_record ORDER BY id'):h.update(json.dumps(r,ensure_ascii=False).encode())
 return h.hexdigest()
def validate():
 before=sha(ROOT/'data/platform.sqlite3')
 with tempfile.TemporaryDirectory(prefix='motor-issue-rehearsal-') as temp:
  copy=Path(temp)/'platform.sqlite3'
  with sqlite3.connect('file:'+str(ROOT/'data/platform.sqlite3')+'?mode=ro',uri=True) as source,sqlite3.connect(copy) as target:source.backup(target)
  os.environ['MOTOR_SQLITE_PATH']=str(copy);os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings')
  import django;django.setup()
  from django.test import RequestFactory
  from django.contrib.auth.models import User
  from app import issue_workspace_views as views,views as main,coordination_hub as hub
  from app.models import IssueDisposition,AuditEvent,Record
  from django.db import connection
  factory=RequestFactory();admin=User.objects.get(username='demo_admin')
  def api(fn,path,user=None,data=None,**kwargs):
   r=factory.post(path,json.dumps(data),content_type='application/json') if data is not None else factory.get(path)
   r.user=user or admin;response=fn(r,**kwargs);assert response.status_code==200,(fn.__name__,response.status_code,response.content[:500]);return response
  with sqlite3.connect(copy) as db:original=facts(db)
  started=time.monotonic();board=json.loads(api(views.board,'/api/issue-workspace').content);elapsed=time.monotonic()-started
  scope=board['filters'];receipt=board['receipt'];total=board['total'];assert total>150
  page_keys=[]
  from urllib.parse import urlencode
  for page in range(1,(total+29)//30+1):
   d=json.loads(api(views.board,'/api/issue-workspace?'+urlencode({**scope,'page':page})).content);page_keys.extend(r['key'] for r in d['rows'])
  assert len(page_keys)==len(set(page_keys))==total
  exported=api(views.export,'/api/issue-workspace/export?'+urlencode({**scope,'receipt':receipt}));csvrows=list(csv.reader(io.StringIO(exported.content.decode('utf-8-sig'))));assert len(csvrows)==total+4;assert {r[0] for r in csvrows[4:]}==set(page_keys)
  row=next(r for r in board['rows'] if r['dataset']=='units');key=row['key']
  info=json.loads(api(views.detail,'/api/issue-workspace/rows/'+key+'?'+urlencode({**scope,'receipt':receipt}),key=key).content);assert len(info['sources'])>1;assert all(s['file'] and s['sheet'] and s['row'] for s in info['sources'])
  p=dict(scope=scope,receipt=receipt,version=0,status='处理中',owner='合成质量岗位',note='隔离副本核查演练，等待源业务岗位复核',due_date='2026-10-05',request_id=str(uuid.uuid4()))
  saved=json.loads(api(views.follow_up,'/api/issue-workspace/rows/'+key+'/follow-up',data=p,key=key).content);repeated=json.loads(api(views.follow_up,'/api/issue-workspace/rows/'+key+'/follow-up',data=p,key=key).content);assert saved['saved']['version']==1 and repeated['repeated']
  request=factory.get('/api/issue-workspace/export?'+urlencode({**scope,'receipt':receipt}));request.user=admin;assert views.export(request).status_code==409
  h=hub.Hub(admin);note=next(r for r in h.rows if r['domain']=='overview-issue');assert h.detail(note['id'],1)['history_total']==1 and 'focus=' in note['href']
  profiles=[]
  for role in ['admin','analyst','quality','operations','finance','viewer']:
   user=User.objects.filter(groups__name=role,is_active=True).first();assert user
   d=json.loads(api(main.overview,'/api/overview',user=user).content);profiles.append({'role':role,'preset':d['presentation']['preset'],'primary':d['presentation']['primary']})
   if role in ['quality','operations','viewer']:assert 'finance' not in d and 'finance' not in [c['key'] for c in d['presentation']['choices']]
  with sqlite3.connect(copy) as db:assert facts(db)==original
  assert sha(ROOT/'data/platform.sqlite3')==before
  r=dict(synthetic=True,isolated_complete_database=True,all_pages_unique_and_complete=True,total_observations=total,kind_counts=board['kind_counts'],distinct_objects=board['summary']['distinct_objects'],full_scope_csv_matches_all_pages=True,csv_business_rows=total,source_files_sheets_and_rows_checked=len(info['sources']),followup_version_and_idempotent_replay=True,old_scope_export_rejected=True,hub_source_and_history_linked=True,role_profiles=profiles,isolated_business_facts_unchanged=True,first_board_seconds=round(elapsed,3),main_database_sha256=before,browser_mobile_and_actual_download_accepted=False,real_systems_connected=False)
  (ROOT/'data/issue_workspace_validation.json').write_text(json.dumps(r,ensure_ascii=False,indent=2));print(json.dumps(r,ensure_ascii=False,indent=2));connection.close();return r
if __name__=='__main__':validate()
