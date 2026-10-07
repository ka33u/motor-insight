"""Verify CSV/JSON for all inherited models on a disposable parent copy."""
import hashlib,json,os,shutil,sqlite3,sys,uuid,csv,io
from pathlib import Path
from collections import Counter
ROOT=Path(__file__).resolve().parents[1];BEFORE=ROOT/'data/model-exports-before'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def preservation():
 m=json.loads((BEFORE/'manifest.json').read_text());assert sha(ROOT/'data/platform.sqlite3')==sha(BEFORE/'platform.sqlite3')==m['database_sha256']
 for name,h in {**m['physical'],**m['protected']}.items():assert sha(ROOT/name)==h,name
 with sqlite3.connect(ROOT/'data/platform.sqlite3') as c:assert c.execute('PRAGMA integrity_check').fetchall()==[('ok',)] and c.execute('PRAGMA foreign_key_check').fetchall()==[]
 return dict(main_database_unchanged=True,all_52_tables_unchanged=True,all_214523_facts_unchanged=True,old_454_physical_files_unchanged=True,protected_modules_unchanged=len(m['protected']))
def main():
 db=ROOT/'data/model-exports-rehearsal.sqlite3';assert not db.exists();shutil.copy2(BEFORE/'platform.sqlite3',db);os.environ['DJANGO_SETTINGS_MODULE']='config.settings';os.environ['MOTOR_SQLITE_PATH']=str(db);sys.path.insert(0,str(ROOT));import django;django.setup()
 from django.test import RequestFactory
 from django.urls import resolve
 from django.contrib.auth import get_user_model
 from app.models import AnalysisModel,Record,AuditEvent,AnalysisModelCard,AnalysisModelCardVersion
 from urllib.parse import urlencode
 u=get_user_model().objects.get(username='demo_admin');factory=RequestFactory();items=[];audit=AuditEvent.objects.count();versions=AnalysisModelCardVersion.objects.count()
 def request(method,path,body=None):
  req=factory.post(path,json.dumps(body),content_type='application/json') if method=='POST' else factory.get(path);req.user=u;match=resolve(path.split('?')[0]);r=match.func(req,**match.kwargs);assert r.status_code==200,(path.split('?')[0],r.status_code,r.content[:150]);return r
 def get(path):return json.loads(request('GET',path).content)
 for m in AnalysisModel.objects.order_by('id'):
  p=get('/api/model-cards/preview/'+str(m.id));body=dict(request_id=str(uuid.uuid4()),code='MODEL.EXPORT.SIM.'+str(m.id).zfill(4),name='合成完整结果核对 · '+m.name,question='同一范围结果能否带口径完整导出',reader='隔离演练',object_grain=p['binding']['dataset_contract']['grain'],time_scope='当前合成资料；不是历史事实重放',limitations='文件不代替审批、质量放行或原件授权',review_on=None,model_id=m.id,receipt=p['receipt']);card=json.loads(request('POST','/api/model-cards',body).content)['card'];base='/api/model-cards/'+card['id'];v=get(base+'/run');q=urlencode(dict(receipt=v['reading']['receipt'],format='json'));jr=request('GET',base+'/result-export?'+q);doc=json.loads(jr.content);r=v['result'];s=v['reading']['summary']
  assert doc['reading']['summary']==s and doc['card']==v['card'] and 'receipt' not in doc['reading'] and not doc['result']['truncated']
  assert doc['result']['rows'][:len(r['rows'])]==r['rows'] and len(doc['result']['rows'])==r['groups'] and doc['reading']['exported_groups']==r['groups']
  cr=request('GET',base+'/result-export?'+urlencode(dict(receipt=v['reading']['receipt'],format='csv')));assert cr.content.startswith(b'\xef\xbb\xbf');rows=list(csv.reader(io.StringIO(cr.content.decode('utf-8-sig'))));header=next(x for x in rows if x and x[0]=='主结果');assert header[3]==('' if s['value'] is None else str(s['value'])) and header[7]==s['state'];assert cr['Cache-Control']=='no-store' and cr['Content-Disposition'].endswith('.csv"')
  event=AuditEvent.objects.latest('id');assert event.detail['file_sha256']==hashlib.sha256(cr.content).hexdigest() and 'receipt' not in event.detail
  if m.id==44:assert s['metric_receipt']['version']==8 and s['value']==s['numerator']/s['denominator']*100
  if m.id==47:assert s['value']==4500 and s['unit']=='台'
  items.append(dict(model_id=m.id,dataset=m.dataset,chart=v['reading']['chart'],summary_state=s['state'],sources=s['source_rows'],exported_groups=len(doc['result']['rows']),csv_bytes=len(cr.content),json_bytes=len(jr.content),unit=s['unit']))
 assert len(items)==52 and Record.objects.count()==214523 and AnalysisModel.objects.count()==52 and AuditEvent.objects.count()==audit+156 and AnalysisModelCardVersion.objects.count()==versions+52
 proof=dict(success=True,models=52,result_exports=104,summary_states=dict(Counter(x['summary_state'] for x in items)),normal_api_on_disposable_copy=True,all_csv_json_same_viewed_scope=True,results=items,**preservation(),browser_acceptance=False,mobile_acceptance=False,actual_download_acceptance=False)
 (ROOT/'data/model_exports_rehearsal.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2)+'\n');print(json.dumps({k:v for k,v in proof.items() if k!='results'},ensure_ascii=False))
if __name__=='__main__':main()
