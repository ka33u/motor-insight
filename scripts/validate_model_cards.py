"""Normal private model-card API on the current checkpoint copy or main."""
import argparse,hashlib,json,os,shutil,sqlite3,sys,uuid
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];BEFORE=ROOT/'data/model-cards-before'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def write(p,d):p.write_text(json.dumps(d,ensure_ascii=False,indent=2,default=str)+'\n')
def legacy(db):
 m=json.loads((BEFORE/'manifest.json').read_text());assert sha(BEFORE/'platform.sqlite3')==m['database_sha256']
 for name,h in {**m['physical'],**m['protected']}.items():assert sha(ROOT/name)==h,name
 assert (ROOT/'app/models.py').read_bytes().startswith((BEFORE/'app/models.py').read_bytes())
 with sqlite3.connect(db) as c:
  c.execute('ATTACH DATABASE ? AS parent',(str(BEFORE/'platform.sqlite3'),));assert c.execute('PRAGMA integrity_check').fetchall()==[('ok',)];assert c.execute('PRAGMA foreign_key_check').fetchall()==[]
  names=[r[0] for r in c.execute("SELECT name FROM parent.sqlite_master WHERE type='table' AND name!='sqlite_sequence'")]
  additions={'django_migrations':1,'django_content_type':2,'auth_permission':8,'app_auditevent':2}
  for name in names:
   assert c.execute('SELECT count(*) FROM (SELECT * FROM parent."'+name+'" EXCEPT SELECT * FROM main."'+name+'")').fetchone()[0]==0,name
   extra=c.execute('SELECT (SELECT count(*) FROM main."'+name+'")-(SELECT count(*) FROM parent."'+name+'")').fetchone()[0];assert extra==additions.get(name,0),(name,extra)
  actual={r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name!='sqlite_sequence'")};assert actual-set(names)=={'app_analysismodelcard','app_analysismodelcardversion'} and len(actual)==52
  for name in ('app_analysismodelcard','app_analysismodelcardversion'):assert c.execute('SELECT count(*) FROM '+name).fetchone()[0]==2
 from app.models import MetricVersion,Record,AnalysisModel,ImportTemplate
 from app.metric_registry import calculation_hash
 assert Record.objects.count()==214523 and AnalysisModel.objects.count()==52
 assert calculation_hash('bi_order_lines')==MetricVersion.objects.get(pk=11).calculation_hash==m['delivery_v8_hash'];t=ImportTemplate.objects.get(code='TPL-SIM-DEPTS-001');assert (t.current_version,t.revision)==(4,8)
 return dict(old_tables_retained=50,new_tables=2,old_facts_retained=214523,old_physical_retained=len(m['physical']),protected_modules_retained=len(m['protected']),published_v8_unchanged=True,template_v4_unchanged=True)
def main():
 p=argparse.ArgumentParser();p.add_argument('mode',choices=['rehearse','release']);p.add_argument('--rehearsal-db',type=Path,default=ROOT/'data/model-cards-rehearsal-v3.sqlite3');a=p.parse_args();m=json.loads((BEFORE/'manifest.json').read_text());main_before=sha(ROOT/'data/platform.sqlite3');db=a.rehearsal_db.resolve() if a.mode=='rehearse' else ROOT/'data/platform.sqlite3'
 if a.mode=='rehearse':assert not db.exists();shutil.copy2(BEFORE/'platform.sqlite3',db)
 else:
  assert main_before==m['database_sha256'];assert json.loads((ROOT/'data/model_cards_rehearsal.json').read_text())['success'];assert json.loads((ROOT/'data/model_cards_http_validation.json').read_text())['success'];assert '\nOK\n' in (ROOT/'data/model_cards_full_tests.log').read_text()
 os.environ['MOTOR_SQLITE_PATH']=str(db);os.environ['DJANGO_SETTINGS_MODULE']='config.settings';sys.path.insert(0,str(ROOT));import django;django.setup()
 from django.core.management import call_command
 call_command('migrate',verbosity=0,interactive=False)
 from django.contrib.auth import get_user_model
 from django.test import RequestFactory
 from django.urls import resolve
 from app.models import AuditEvent,Record,AnalysisModelCard,AnalysisModelCardVersion
 u=get_user_model().objects.get(username='demo_analyst');factory=RequestFactory();requests=[];cases=[]
 def req(method,path,body=None,user=u):
  request=factory.post(path,json.dumps(body),content_type='application/json') if method=='POST' else factory.get(path);request.user=user;match=resolve(path.split('?')[0]);response=match.func(request,**match.kwargs)
  assert response.status_code==200,(path,response.status_code,response.content[:300]);return json.loads(response.content)
 for owner,model_id,code,question,grain,boundary in [('demo_analyst',44,'MODEL.ORDER.OTIF.0001','不同产品族的交付兑现如何分布？','同一已发布指标下的订单行分组','固定引用交付v8；不能将分组百分比直接取平均，无法按此模型确认实际合同承诺'),('demo_admin',47,'MODEL.UNIT.POWER.0001','整机功率结构及固定分组如何分布？','同一整机身份、声明功率与本人固定分组版本','分类口径保存为个人分组版本；记录数不表示订单量或可售库存')]:
  user=get_user_model().objects.get(username=owner)
  preview=req('GET','/api/model-cards/preview/'+str(model_id),user=user);body=dict(request_id=str(uuid.uuid4()),code=code,name='合成模型口径卡 · '+question,question=question,reader='经营分析岗位',object_grain=grain,time_scope='业务截止2026-10-01T18:00:00下当前合成资料；实际范围由登记定义的筛选确定',limitations=boundary,review_on='2026-10-08',model_id=model_id,receipt=preview['receipt']);result=req('POST','/api/model-cards',body,user=user);card=result['card'];before=AuditEvent.objects.count();assert req('POST','/api/model-cards',body,user=user)['repeated'];assert AuditEvent.objects.count()==before
  run=req('GET','/api/model-cards/'+card['id']+'/run',user=user);assert run['result_mode']=='current_data' and card['definition_state']=='same';history=req('GET','/api/model-cards/'+card['id']+'/history',user=user);assert history['total']==1
  cases.append(dict(id=card['id'],owner=owner,code=code,model_id=model_id,registered_model_version=card['binding']['source_model']['version'],metric=card['binding']['metric'],grouping_version=card['binding']['grouping']['version'] if card['binding']['grouping'] else None,matched=run['result']['matched']));requests.append(dict(owner=owner,body=body))
 for user in get_user_model().objects.all():
  rows=req('GET','/api/model-cards',user=user);assert rows['total']==(1 if user.username in {'demo_admin','demo_analyst'} else 0)
 assert AnalysisModelCard.objects.count()==AnalysisModelCardVersion.objects.count()==2 and Record.objects.count()==214523
 proof=dict(success=True,mode=a.mode,**legacy(db),database_sha256=sha(db),owners=['demo_admin','demo_analyst'],cards=cases,new_audits=2,normal_api=True,browser_acceptance=False,mobile_acceptance=False)
 if a.mode=='rehearse':assert sha(ROOT/'data/platform.sqlite3')==main_before;proof['main_database_unchanged']=True
 else:
  file=ROOT/'data/model_cards_main_requests.json';write(file,requests);file.chmod(0o600)
 write(ROOT/('data/model_cards_rehearsal.json' if a.mode=='rehearse' else 'data/model_cards_release.json'),proof);print(json.dumps(proof,ensure_ascii=False,default=str))
if __name__=='__main__':main()
