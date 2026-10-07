"""Evidence for this synthetic metric lifecycle rollout (read-only DB audit)."""
import os,sys,json,hashlib,sqlite3,tempfile,zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings')
import django
django.setup()
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from app import analytics,metric_registry as registry
from app.analysis_engine import run_analysis
from app.models import Record,AnalysisModel,Topic,MetricVersion,AuditEvent

baseline=ROOT/'data/backups/motor-backup-20261003-112050.zip'
h=hashlib.sha256()
for row in Record.objects.order_by('dataset','business_key').values_list('dataset','business_key','values','revision','source_row_id').iterator():h.update(json.dumps(row,sort_keys=True,ensure_ascii=False).encode())
prior=json.loads((ROOT/'data/delivery_validation.json').read_text())
assert h.hexdigest()==prior['business_digest_after_browser_followup']
with zipfile.ZipFile(baseline) as z,tempfile.TemporaryDirectory(prefix='metric-baseline-check-') as tmp:
    p=Path(tmp)/'before.sqlite3';p.write_bytes(z.read('data/platform.sqlite3'))
    with sqlite3.connect(p) as db:
        previous_models=list(db.execute('select id,name,dataset,definition,version,owner,is_public from app_analysismodel'))
        previous_topics=list(db.execute('select id,name,description,layout,filters,version,owner,is_public from app_topic'))
    for key,name,ds,definition,version,owner,public in previous_models:
        m=AnalysisModel.objects.get(pk=key);assert (m.name,m.dataset,m.definition,m.version,m.owner,m.is_public)==(name,ds,json.loads(definition),version,owner,bool(public))
    for key,name,description,layout,filters,version,owner,public in previous_topics:
        t=Topic.objects.get(pk=key);assert (t.name,t.description,t.layout,t.filters,t.version,t.owner,t.is_public)==(name,description,json.loads(layout),json.loads(filters),version,owner,bool(public))
admin=User.objects.get(username='demo_admin');ops=User.objects.get(username='demo_operations');quality=User.objects.get(username='demo_quality')
v1=MetricVersion.objects.select_related('metric').get(metric__key='DELIVERY_OTIF',version=1)
v2=MetricVersion.objects.select_related('metric').get(metric__key='DELIVERY_OTIF',version=2)
assert v1.status=='retired' and v2.status=='published'
assert v2.reviewed_by not in v2.contributors and v2.reviewed_by!=v2.submitted_by
assert v2.calculation_hash==registry.calculation_hash(v2.metric.dataset)
assert '下单日' in v2.payload['clock'] and registry.info(admin,v2)['scope_date']=='下单日'
d=analytics.tables();plans=[p for p in d['delivery_plans'] if p['due']<analytics.DAY]
on_time=sum(sum(s['qty'] for s in d['shipments'] if s['delivery_plan_id']==p['id'] and s['shipped']<=analytics.AS_OF and s['shipped'][:10]<=p['due'])>=p['qty'] for p in plans)
definition={'metric_ref':{'key':'DELIVERY_OTIF','version':2},'filters':[],'chart':'table'}
r=run_analysis(ops,'bi_order_lines',definition)
assert (on_time,len(plans))==(15,165)
assert r['rows'][0]['m0']==on_time/len(plans)*100
assert (r['components'][0]['numerator'],r['components'][0]['denominator'])==(15,165)
try:run_analysis(ops,'bi_order_lines',{**definition,'metric_ref':{'key':'DELIVERY_OTIF','version':1}})
except ValidationError as ex:assert '停用' in str(ex)
else:raise AssertionError('Retired metric must not run')
m=AnalysisModel.objects.get(pk=44);t=Topic.objects.get(pk=15)
assert m.definition['metric_ref']==definition['metric_ref'] and m.version==2
assert t.layout==[{'model_id':44,'span':2}]
grouped=run_analysis(ops,m.dataset,m.definition);scoped=run_analysis(ops,m.dataset,m.definition,{'family':'YE4'})
assert scoped['matched']==100 and len(scoped['rows'])==1 and abs(scoped['rows'][0]['m0']-4/54*100)<1e-9
finance=MetricVersion.objects.select_related('metric').get(metric__key='RECEIVABLE_BALANCE',version=1)
assert not registry.can_read(quality,finance) and not registry.can_read(ops,finance)
assert registry.info(admin,v2,True)['impact']['model_count']==1
versions=list(MetricVersion.objects.values('id','metric__key','version','status','revision'))
assert len(versions)==5 and sum(v['status']=='draft' for v in versions)==3
evidence={'business_record_count':Record.objects.count(),'business_sha256':h.hexdigest(),'business_facts_unchanged':True,'unchanged_existing_models':len(previous_models),'unchanged_existing_topics':len(previous_topics),'new_model_id':m.pk,'new_model_version':m.version,'new_topic_id':t.pk,'new_topic_version':t.version,'metric_versions':versions,'released_metric':registry.receipt(v2),'independent_order_plan_check':{'on_time':on_time,'due':len(plans),'ratio_pct':r['rows'][0]['m0']},'grouped_result':grouped['rows'],'YE4_scope':{'matched':scoped['matched'],'rows':scoped['rows']},'retired_reference_pauses':True,'financial_definition_permissions_passed':True,'lifecycle_audit_count':AuditEvent.objects.filter(object_type='MetricVersion').count(),'browser_checks':['draft preview shows numerator and denominator','independent demo_operations publication','v2 correction preserves v1 definition','v1 retirement impact shows 1 model and 1 topic','retired topic explicitly pauses','model editor stays editable when old version stops','explicit model migration to v2 restores topic','topic YE4 scope and same-scope source drill','390px document width 390 and modal width/scroll width 354'],'screenshots':['outputs/指标版本审核.png','outputs/发布指标专题.png'],'pre_migration_backup':str(baseline.relative_to(ROOT)),'scope':'Synthetic local workflow only; no real factory certification or source-system changes.'}
(ROOT/'data/metric_registry_validation.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2,default=str))
print(json.dumps({'business_records':evidence['business_record_count'],'unchanged_models':len(previous_models),'unchanged_topics':len(previous_topics),'versions':versions,'OTIF':evidence['independent_order_plan_check'],'checks':'passed'},ensure_ascii=False))
