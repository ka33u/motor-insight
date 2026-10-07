"""Normal API writes on a checkpoint copy, or release after a passing rehearsal."""
import argparse,copy,hashlib,json,os,sqlite3,sys,uuid
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
BEFORE=ROOT/'data/spc-workspace-before'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def write(p,value):p.write_text(json.dumps(value,ensure_ascii=False,indent=2,default=str)+'\n')
def legacy_check(db):
 m=json.loads((BEFORE/'manifest.json').read_text());assert sha(BEFORE/'platform.sqlite3')==m['database_sha256']
 for name,digest in {**m['physical'],**m['protected']}.items():assert sha(ROOT/name)==digest,name
 old_models=(BEFORE/'app/models.py').read_bytes();assert (ROOT/'app/models.py').read_bytes().startswith(old_models)
 with sqlite3.connect(db) as c:
  c.execute('ATTACH DATABASE ? AS parent',(str(BEFORE/'platform.sqlite3'),))
  assert c.execute('PRAGMA integrity_check').fetchall()==[('ok',)];assert c.execute('PRAGMA foreign_key_check').fetchall()==[]
  tables=[r[0] for r in c.execute("SELECT name FROM parent.sqlite_master WHERE type='table' AND name!='sqlite_sequence'")]
  for name in tables:
   for direction in [('parent','main')]+([] if name in {'django_migrations','django_content_type','auth_permission','app_auditevent'} else [('main','parent')]):
    a,b=direction;assert c.execute('SELECT count(*) FROM (SELECT * FROM '+a+'."'+name+'" EXCEPT SELECT * FROM '+b+'."'+name+'")').fetchone()[0]==0,(name,direction)
  for name,extra in {'django_migrations':1,'django_content_type':2,'auth_permission':8,'app_auditevent':4}.items():
   assert c.execute('SELECT (SELECT count(*) FROM main."'+name+'")-(SELECT count(*) FROM parent."'+name+'")').fetchone()[0]==extra,(name,extra)
  actual={r[0] for r in c.execute("SELECT name FROM main.sqlite_master WHERE type='table' AND name!='sqlite_sequence'")}
  assert actual-set(tables)=={'app_spcanalysisview','app_spcresultsnapshot'} and len(actual)==50
  for name in ('app_spcanalysisview','app_spcresultsnapshot'):assert c.execute('SELECT count(*) FROM '+name).fetchone()[0]==2
 sys.path.insert(0,str(ROOT/'scripts'));from refine_bi_spc_workspace import remove_exact_workspace
 from refine_bi_catalog import refine
 d=json.loads((ROOT/'data/bi_design.json').read_text());assert remove_exact_workspace(copy.deepcopy(d))==m['catalog']
 assert refine(copy.deepcopy(d))==d
 return dict(old_tables=48,protected_files=len(m['protected']),physical_files=len(m['physical']),new_tables=2,
  source_facts_unchanged=True,old_analysis_and_topics_and_snapshots_unchanged=True,catalog_exact_additive=True)

def main():
 parser=argparse.ArgumentParser();parser.add_argument('mode',choices=['rehearse','release']);a=parser.parse_args()
 manifest=json.loads((BEFORE/'manifest.json').read_text());main_before=sha(ROOT/'data/platform.sqlite3')
 if a.mode=='rehearse':
  folder=ROOT/'data/spc-workspace-rehearsal';folder.mkdir(exist_ok=False);db=folder/'platform.sqlite3'
  with sqlite3.connect(BEFORE/'platform.sqlite3') as source,sqlite3.connect(db) as target:source.backup(target)
 else:
  rehearsal=json.loads((ROOT/'data/spc_workspace_rehearsal.json').read_text());assert rehearsal['success'] is True
  assert main_before==manifest['database_sha256'],'Release parent changed; inspect before migration';db=ROOT/'data/platform.sqlite3'
 os.environ['MOTOR_SQLITE_PATH']=str(db);os.environ['DJANGO_SETTINGS_MODULE']='config.settings';sys.path.insert(0,str(ROOT))
 import django;django.setup()
 from django.core.management import call_command
 from django.test import RequestFactory
 from django.urls import resolve
 from django.contrib.auth import get_user_model
 from app.models import Record,SPCAnalysisView,SPCResultSnapshot,AuditEvent,MetricVersion,AnalysisModel
 from app.metric_registry import calculation_hash
 from app import access
 factory=RequestFactory();user=get_user_model().objects.get(username='demo_quality')
 def request(method,path,data=None,actor=user):
  r=factory.post(path,json.dumps(data),content_type='application/json') if method=='POST' else factory.get(path,data or {})
  r.user=actor;match=resolve(path);return match.func(r,**match.kwargs)
 def get(path,data=None,actor=user):
  r=request('GET',path,data,actor);assert r.status_code==200,(path,r.status_code,r.content[:200]);return json.loads(r.content)
 def post(path,data):
  r=request('POST',path,data);assert r.status_code==200,(path,r.status_code,r.content[:200]);return json.loads(r.content)
 call_command('migrate',verbosity=0)
 cases=[];requests=[]
 for number,code,name in [(1,'SPC.R.BASELINE.0008','阻值受控采样 · 基线方案'),(2,'SPC.R.SHIFT.0008','阻值受控采样 · 波动调查')]:
  study=f'SPC2609-{number:04}';d=get('/api/spc/'+study)
  body=dict(request_id=str(uuid.uuid5(uuid.NAMESPACE_URL,'motor-spc-view-20261007-'+study)),code=code,name=name,note='固定合成试验采样、规范和显示定义，供质量专题个人复核。',
   study_id=study,receipt=d['receipt'],display=dict(show_spec=True,decimals=6),topic_id=4)
  v=post('/api/spc-analysis-views',body)['view'];requests.append(dict(path='/api/spc-analysis-views',body=body))
  before=AuditEvent.objects.count();assert post('/api/spc-analysis-views',body)['repeated'];assert AuditEvent.objects.count()==before
  run=get('/api/spc-analysis-views/'+v['id']+'/run')
  body=dict(request_id=str(uuid.uuid5(uuid.NAMESPACE_URL,'motor-spc-snapshot-20261007-'+study)),view_id=v['id'],revision=v['revision'],receipt=run['receipt'],name=name+' · 冻结结果',note='固定全部合成观测和Excel来源，后续资料核对不自动认定改善或批准。')
  s=post('/api/spc-result-snapshots',body)['snapshot'];requests.append(dict(path='/api/spc-result-snapshots',body=body))
  before=AuditEvent.objects.count();assert post('/api/spc-result-snapshots',body)['repeated'];assert AuditEvent.objects.count()==before
  frozen=get('/api/spc-result-snapshots/'+s['id'],dict(page=2));assert len(frozen['rows'])==25 and len(frozen['chart_points'])==80
  assert frozen['limits']==run['limits'] and frozen['chart_points']==run['chart_points'] and frozen['formal_qualification'] is False
  all_sources=get('/api/spc-result-snapshots/'+s['id']+'/sources',dict(receipt=frozen['receipt']));assert all_sources['total']>80
  compare=get('/api/spc-result-snapshots/'+s['id']+'/compare-current');assert compare['state']=='same_observations' and compare['total']==0
  cases.append(dict(code=code,study_id=study,view_id=v['id'],snapshot_id=s['id'],points=80,source_count=s['source_count'],baseline_signals=run['signal_counts']['baseline'],monitor_signals=run['signal_counts']['monitor'],snapshot_hash=s['payload_hash']))
 roles=[];before=AuditEvent.objects.count()
 for other in get_user_model().objects.all():
  rows=get('/api/spc-analysis-views',actor=other);snaps=get('/api/spc-result-snapshots',actor=other)
  if other!=user:
   assert rows['total']==snaps['total']==0
   assert request('GET','/api/spc-result-snapshots/'+cases[0]['snapshot_id'],actor=other).status_code==404
  else:assert rows['total']==snaps['total']==2
  roles.append(access.role(other))
 assert AuditEvent.objects.count()==before and Record.objects.count()==213441
 version=MetricVersion.objects.get(pk=11);assert version.calculation_hash==calculation_hash(version.metric.dataset)=='9d9a5af3d45172eca16790d628a36bc6acbe18d1e2a811a66a5b5fbff7037fe3'
 assert AnalysisModel.objects.count()==52
 proof=dict(success=True,mode=a.mode,database_sha256=sha(db),parent_sha256=manifest['database_sha256'],**legacy_check(db),
  raw_excel_facts=213441,personal_views=2,personal_snapshots=2,new_audits=4,six_roles=sorted(roles),owner='demo_quality',personal_topic_id=4,cases=cases,
  browser_acceptance=False,mobile_acceptance=False,real_erp_mes_connected=False)
 if a.mode=='rehearse':assert sha(ROOT/'data/platform.sqlite3')==main_before;proof['main_database_unchanged']=True
 else:
  # Store exact bodies privately for request-id replay; do not log signed receipts.
  destination=ROOT/'data/spc_workspace_main_requests.json';write(destination,requests);destination.chmod(0o600)
 write(ROOT/('data/spc_workspace_rehearsal.json' if a.mode=='rehearse' else 'data/spc_workspace_release.json'),proof)
 print(json.dumps(proof,ensure_ascii=False))
if __name__=='__main__':main()
