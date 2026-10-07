"""Run all 52 inherited models via private cards on a disposable parent copy."""
import hashlib,json,os,shutil,sqlite3,sys,uuid
from collections import Counter
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];BEFORE=ROOT/'data/model-results-before'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def preservation():
 m=json.loads((BEFORE/'manifest.json').read_text());assert sha(ROOT/'data/platform.sqlite3')==sha(BEFORE/'platform.sqlite3')==m['database_sha256']
 for name,h in {**m['physical'],**m['protected']}.items():assert sha(ROOT/name)==h,name
 with sqlite3.connect(ROOT/'data/platform.sqlite3') as c:assert c.execute('PRAGMA integrity_check').fetchall()==[('ok',)] and c.execute('PRAGMA foreign_key_check').fetchall()==[]
 return dict(main_database_unchanged=True,all_52_tables_unchanged=True,all_214523_facts_unchanged=True,old_454_physical_files_unchanged=True,protected_modules_unchanged=len(m['protected']))
def main():
 db=ROOT/'data/model-results-rehearsal-v2.sqlite3';assert not db.exists();shutil.copy2(BEFORE/'platform.sqlite3',db);before=sha(ROOT/'data/platform.sqlite3');os.environ['DJANGO_SETTINGS_MODULE']='config.settings';os.environ['MOTOR_SQLITE_PATH']=str(db);sys.path.insert(0,str(ROOT));import django;django.setup()
 from django.test import RequestFactory
 from django.urls import resolve
 from django.contrib.auth import get_user_model
 from app.models import AnalysisModel,Record,AuditEvent,AnalysisModelCard
 from app import model_cards
 u=get_user_model().objects.get(username='demo_admin');factory=RequestFactory();results=[];audit=AuditEvent.objects.count()
 def request(method,path,body=None):
  req=factory.post(path,json.dumps(body),content_type='application/json') if method=='POST' else factory.get(path);req.user=u;match=resolve(path.split('?')[0]);r=match.func(req,**match.kwargs);assert r.status_code==200,(path.split('?')[0],r.status_code,r.content[:150]);return json.loads(r.content)
 for m in AnalysisModel.objects.order_by('id'):
  preview=request('GET','/api/model-cards/preview/'+str(m.id));body=dict(request_id=str(uuid.uuid4()),code='MODEL.READ.SIM.'+str(m.id).zfill(4),name='合成结果阅读核对 · '+m.name,question='按原模型核对主结果、分组与来源',reader='隔离演练',object_grain=preview['binding']['dataset_contract']['grain'],time_scope='同一当前合成资料，不重放历史状态',limitations='沿用已登记定义；核对不是业务审批',review_on=None,model_id=m.id,receipt=preview['receipt']);card=request('POST','/api/model-cards',body)['card'];v=request('GET','/api/model-cards/'+card['id']+'/run');s=v['reading']['summary'];r=v['result']
  assert s['source_rows']==r['matched'] and v['reading']['chart']==m.definition.get('chart','bar')
  from urllib.parse import urlencode
  query=urlencode(dict(receipt=v['reading']['receipt']));d=request('GET','/api/model-cards/'+card['id']+'/evidence?'+query);assert d['total']==r['matched']
  if m.id==44:
   assert s['measure']['agg']=='ratio' and s['metric_receipt']['version']==8 and s['value']==s['numerator']/s['denominator']*100
  if m.id==47:assert s['value']==4500 and s['unit']=='台'
  results.append(dict(model_id=m.id,dataset=m.dataset,chart=v['reading']['chart'],summary_state=s['state'],summary_value=s['value'],unit=s['unit'],source_rows=s['source_rows'],groups=r['groups'],truncated=r['truncated'],same_scope_evidence=True))
 assert len(results)==52 and Record.objects.count()==214523 and AuditEvent.objects.count()==audit+52 and AnalysisModel.objects.count()==52
 proof=dict(success=True,models=52,charts=dict(Counter(r['chart'] for r in results)),summary_states=dict(Counter(r['summary_state'] for r in results)),results=results,normal_api_on_disposable_copy=True,**preservation(),browser_acceptance=False,mobile_acceptance=False)
 (ROOT/'data/model_results_rehearsal.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2)+'\n');print(json.dumps({k:v for k,v in proof.items() if k!='results'},ensure_ascii=False))
if __name__=='__main__':main()
