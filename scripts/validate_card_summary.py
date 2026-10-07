"""Native topic/summary/snapshot APIs on an isolated full synthetic database."""
import csv,hashlib,io,json,os,sqlite3,sys,tempfile,time,uuid,math
from collections import Counter
from decimal import Decimal
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def facts(db):
 h=hashlib.sha256()
 for r in db.execute('SELECT * FROM app_record ORDER BY id'):h.update(json.dumps(r,ensure_ascii=False).encode())
 return h.hexdigest()
def validate():
 before=sha(ROOT/'data/platform.sqlite3');started=time.monotonic()
 with tempfile.TemporaryDirectory(prefix='motor-summary-rehearsal-') as temp:
  copy=Path(temp)/'platform.sqlite3'
  with sqlite3.connect('file:'+str(ROOT/'data/platform.sqlite3')+'?mode=ro',uri=True) as source,sqlite3.connect(copy) as target:source.backup(target)
  os.environ['MOTOR_SQLITE_PATH']=str(copy);os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings')
  import django;django.setup()
  from django.test import RequestFactory
  from django.contrib.auth.models import User
  from django.core.exceptions import ValidationError
  from app import topic_workspace as ws,topic_snapshots as ss,bi_card_summary as bc,bi_card_summary_views as views
  from app.analysis_engine import run_analysis,selected_rows
  from app.models import AnalysisModel,Topic,TopicSnapshot,Record,MetricVersion
  from django.db import connection
  factory=RequestFactory();admin=User.objects.get(username='demo_admin');conf=dict(scope={},reference_scope=None,primary_label='全部模拟对象',reference_label='未启用对照')
  with sqlite3.connect(copy) as db:original=facts(db)
  published=MetricVersion.objects.get(metric__key='DELIVERY_OTIF',version=8);published_hash=ws.digest(published.payload)
  states=Counter();independent=[];models=[]
  for m in AnalysisModel.objects.order_by('id'):
   model=dict(id=m.pk,version=m.version,dataset=m.dataset,definition=m.definition,name=m.name)
   try:r=run_analysis(admin,m.dataset,m.definition,{})
   except ValidationError as ex:models.append(dict(id=m.pk,state='existing_calculation_paused',reason='；'.join(ex.messages)));continue
   summary=bc.build(admin,model,r,{});states[summary['state']]+=1;models.append(dict(id=m.pk,state=summary['state'],value=summary['value'],unit=summary['unit'],source_rows=summary['source_rows'],reason=summary['reason']))
   if summary['state'] not in ('ready','empty') or summary['measure']['agg']=='derived':continue
   rows=selected_rows(admin,m.dataset,m.definition,{})[0];measure=summary['measure'];agg=measure['agg'];field=measure.get('field');values=[x[field] for x in rows if x.get(field) is not None]
   expected=None
   if agg=='count':expected=len(rows)
   elif agg=='distinct':expected=len(set(values))
   elif agg in ['sum','avg','min','max'] and values:
    if agg=='min':expected=min(values)
    elif agg=='max':expected=max(values)
    else:
     total=sum(Decimal(str(x)) for x in values);expected=float(total if agg=='sum' else total/len(values))
   elif agg=='ratio':
    paired=[x for x in rows if x.get(field) is not None and x.get(measure['denominator']) is not None];a=sum(Decimal(str(x[field])) for x in paired);b=sum(Decimal(str(x[measure['denominator']])) for x in paired);expected=float(a/b*100) if b else None
   elif agg in ['median','percentile'] and values:
    values=sorted(Decimal(str(x)) for x in values);position=Decimal(len(values)-1)*Decimal(str(50 if agg=='median' else measure['percentile']))/100;lo=int(position);hi=min(lo+1,len(values)-1);expected=float(values[lo]+(position-lo)*(values[hi]-values[lo]))
   actual=summary['value']
   assert actual==expected if not isinstance(expected,(int,float)) else math.isclose(actual,expected,rel_tol=1e-12,abs_tol=1e-9),(m.pk,actual,expected)
   independent.append(m.pk)
  topics=[];published_result=None
  for t in Topic.objects.order_by('id'):
   ctx=ws.context(admin,t.pk);r=ws.run(admin,t.pk,dict(context_token=ctx['context_token'],config=conf));topics.append(dict(id=t.pk,cards=len(r['cards']),ready=sum(c.get('scope_summary',{}).get('primary',{}).get('state')=='ready' for c in r['cards'])))
   for card in r['cards']:
    if not card.get('primary'):continue
    fresh=run_analysis(admin,card['model']['dataset'],card['model']['definition'],{});assert bc.digest(card['primary'])==bc.digest(fresh),'Original grouped result changed'
    receipt=card['primary'].get('metric_receipt')
    if receipt and receipt['key']=='DELIVERY_OTIF' and receipt['version']==8:published_result=(t,r,card)
  assert len(models)==52 and len(topics)==21 and published_result
  t,r,card=published_result;summary=card['scope_summary']['primary'];assert summary['state']=='ready' and summary['metric_receipt']['version']==8
  request=factory.get('/api/topics/'+str(t.pk)+'/summary/export',dict(context_token=r['context_token'],facts_token=r['facts_token'],summary_token=r['summary_token'],config=json.dumps(conf)));request.user=admin;response=views.export(request,topic_id=t.pk);assert response.status_code==200
  csvrows=list(csv.reader(io.StringIO(response.content.decode('utf-8-sig'))));assert len(csvrows)==len(r['cards'])+4
  body=dict(request_id=str(uuid.uuid4()),context_token=r['context_token'],facts_token=r['facts_token'],summary_token=r['summary_token'],config=conf,name='隔离副本已发布指标摘要',note='核对发布v8时间、来源和整范围数值，仅使用合成副本')
  frozen=ss.create(admin,t.pk,body);value=frozen.payload['result']['cards'][card['slot']]['scope_summary']['primary'];assert value==summary
  assert ss.create(admin,t.pk,body).pk==frozen.pk;assert isinstance(value['metric_receipt']['published_at'],str)
  current=ss.compare_current(admin,t.pk,frozen.pk);assert not current['blocked'];assert all(not c['scope_summary_comparison']['blocked'] and c['scope_summary_comparison']['delta']==0 for c in current['cards'])
  request=factory.get('/api/topics/'+str(t.pk)+'/snapshots/'+str(frozen.pk)+'/summary/export');request.user=admin;response=views.frozen_export(request,topic_id=t.pk,snapshot_id=frozen.pk);assert response.status_code==200
  legacy=[]
  for s in TopicSnapshot.objects.exclude(pk=frozen.pk).select_related('owner'):
   oldhash=s.payload_hash;assert all('scope_summary' not in c for c in s.payload['result']['cards']);ss.get(s.owner,s.topic_id,s.pk)
   d=ss.compare_current(s.owner,s.topic_id,s.pk)
   if not d['blocked']:assert all(c['scope_summary_comparison']['blocked'] for c in d['cards'])
   s.refresh_from_db();assert s.payload_hash==oldhash;legacy.append(str(s.pk))
  assert len(legacy)==4
  with sqlite3.connect(copy) as db:assert facts(db)==original
  published.refresh_from_db();assert ws.digest(published.payload)==published_hash
  assert sha(ROOT/'data/platform.sqlite3')==before
  result=dict(synthetic=True,isolated_complete_database=True,main_database_sha256=before,models_checked=len(models),topics_checked=len(topics),summary_states=dict(states),independent_population_calculations=len(independent),independent_model_ids=independent,original_group_results_unchanged=True,existing_models_targets_and_published_payload_untouched=True,published_v8=dict(topic_id=t.pk,model_id=card['model']['id'],value=summary['value'],unit=summary['unit'],numerator=summary['numerator'],denominator=summary['denominator'],source_rows=summary['source_rows'],published_at_json_safe=True),full_topic_csv_exact_scope=True,published_snapshot_capture_and_idempotency=True,new_frozen_summary_compare_zero=True,legacy_snapshots_unchanged=len(legacy),no_historical_summary_fabricated=True,isolated_business_facts_unchanged=True,elapsed_seconds=round(time.monotonic()-started,3),models=models,browser_mobile_and_actual_download_accepted=False,real_systems_connected=False)
  (ROOT/'data/card_summary_validation.json').write_text(json.dumps(result,ensure_ascii=False,indent=2));print(json.dumps({k:v for k,v in result.items() if k!='models'},ensure_ascii=False,indent=2));connection.close();return result
if __name__=='__main__':validate()
