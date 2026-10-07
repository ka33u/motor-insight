"""Prepare the two existing private demo cards through normal export APIs."""
import hashlib,json,os,shutil,sys
from pathlib import Path
from urllib.parse import urlencode
ROOT=Path(__file__).resolve().parents[1]
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
 db=ROOT/'data/model-exports-examples.sqlite3';assert not db.exists();shutil.copy2(ROOT/'data/model-exports-before/platform.sqlite3',db);before=sha(ROOT/'data/platform.sqlite3');os.environ['DJANGO_SETTINGS_MODULE']='config.settings';os.environ['MOTOR_SQLITE_PATH']=str(db);sys.path.insert(0,str(ROOT));import django;django.setup()
 from django.contrib.auth import get_user_model
 from django.test import RequestFactory
 from django.urls import resolve
 from app.models import AnalysisModelCard,AuditEvent
 factory=RequestFactory();base=AuditEvent.objects.count();files=[]
 for username,code,label,n,unit in [('demo_analyst','MODEL.ORDER.OTIF.0001','订单交付OTIF_v8',300,'%'),('demo_admin','MODEL.UNIT.POWER.0001','电机功率构成',4500,'台')]:
  u=get_user_model().objects.get(username=username);card=AnalysisModelCard.objects.get(owner=u,code=code);url='/api/model-cards/'+str(card.id)
  def get(path):
   req=factory.get(path);req.user=u;match=resolve(path.split('?')[0]);r=match.func(req,**match.kwargs);assert r.status_code==200,(path.split('?')[0],r.status_code);return r
  value=json.loads(get(url+'/run').content);s=value['reading']['summary'];assert s['source_rows']==n and s['unit']==unit
  for kind in ['csv','json']:
   response=get(url+'/result-export?'+urlencode(dict(receipt=value['reading']['receipt'],format=kind)));p=ROOT/'outputs'/('BI模型当前结果_'+label+'_模拟.'+kind);assert not p.exists();p.write_bytes(response.content)
   if kind=='json':assert 'receipt' not in json.loads(p.read_bytes())['reading']
   files.append(dict(name=p.name,sha256=sha(p),bytes=p.stat().st_size,code=code,sources=n,unit=unit))
 assert AuditEvent.objects.count()==base+4 and sha(ROOT/'data/platform.sqlite3')==before
 proof=dict(success=True,normal_api_on_disposable_copy=True,main_database_unchanged=True,examples=files,actual_download_acceptance=False)
 (ROOT/'data/model_exports_examples.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2)+'\n');print(json.dumps(proof,ensure_ascii=False))
if __name__=='__main__':main()
