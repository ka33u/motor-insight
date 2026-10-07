"""Independent raw-fact reconciliation and preservation audit for BI formulas."""
import os,sys,json,hashlib,sqlite3,tempfile,zipfile,math
from collections import defaultdict
from decimal import Decimal
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings')
import django;django.setup()
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from app.models import Record,AnalysisModel,Topic,MetricVersion,AuditEvent,TraceCase
from app import analytics,metric_registry
from app.analysis_engine import run_analysis,selected_rows

baseline=ROOT/'data/backups/motor-backup-20261003-134117.zip'
h=hashlib.sha256()
for row in Record.objects.order_by('dataset','business_key').values_list('dataset','business_key','values','revision','source_row_id').iterator():h.update(json.dumps(row,sort_keys=True,ensure_ascii=False).encode())
assert Record.objects.count()==106838 and h.hexdigest()=='576ad9668e112e407eb81b9d3f58fa150f5753f7ede1fe43b2919ed4a1ec2a72'
with zipfile.ZipFile(baseline) as z,tempfile.TemporaryDirectory() as tmp:
    p=Path(tmp)/'before.sqlite3';p.write_bytes(z.read('data/platform.sqlite3'))
    with sqlite3.connect(p) as db:
        old_models=list(db.execute('select id,name,dataset,definition,version,owner,is_public from app_analysismodel'))
        old_topics=list(db.execute('select id,name,description,layout,filters,version,owner,is_public from app_topic'))
        old_versions=list(db.execute('select id,payload,evidence,calculation_hash from app_metricversion'))
        # Existing non-BI state must remain byte-for-byte unchanged in SQLite.
        with sqlite3.connect(ROOT/'data/platform.sqlite3') as current:
            tables=[x[0] for x in db.execute("select name from sqlite_master where type='table' and name like 'app_%'")]
            protected=[t for t in tables if t not in ['app_analysismodel','app_topic','app_governedmetric','app_metricversion','app_auditevent']]
            for table in protected:
                assert list(db.execute(f'SELECT * FROM {table} ORDER BY id'))==list(current.execute(f'SELECT * FROM {table} ORDER BY id')),table
    for key,name,ds,definition,version,owner,public in old_models:
        m=AnalysisModel.objects.get(pk=key);original=json.loads(definition)
        if key==44:
            original['metric_ref']['version']=3;name=name.replace('v2','v3');version+=1
        assert (m.name,m.dataset,m.definition,m.version,m.owner,m.is_public)==(name,ds,original,version,owner,bool(public))
    for key,name,description,layout,filters,version,owner,public in old_topics:
        t=Topic.objects.get(pk=key)
        assert (t.name,t.description,t.layout,t.filters,t.version,t.owner,t.is_public)==(name,description,json.loads(layout),json.loads(filters),version,owner,bool(public))
    for key,payload,evidence,fingerprint in old_versions:
        v=MetricVersion.objects.get(pk=key);assert (v.payload,v.evidence,v.calculation_hash)==(json.loads(payload),json.loads(evidence),fingerprint)

admin=User.objects.get(username='demo_admin');quality=User.objects.get(username='demo_quality')
d=analytics.tables();products={p['id']:p for p in d['products']};work_orders={w['id']:w for w in d['work_orders']}
by_wo=defaultdict(lambda:{'cost':0,'material':0,'produced':0})
for c in d['costs']:
    if c['occurred']<=analytics.DAY:
        by_wo[c['work_order_id']]['cost']+=c['amount_cents']
        if c['category']=='材料':by_wo[c['work_order_id']]['material']+=c['amount_cents']
for u in d['units']:
    if u['assembly_at']<=analytics.AS_OF:by_wo[u['work_order_id']]['produced']+=1
def independent(family=None,day=None):
    groups=defaultdict(lambda:{'cost':0,'material':0,'produced':0,'rows':0})
    for w in work_orders.values():
        f=products[w['product_id']]['family']
        if family and family!=f:continue
        if day and day!=w['planned_end']:continue
        x=groups[f];x['rows']+=1
        for key in ['cost','material','produced']:x[key]+=by_wo[w['id']][key]
    return groups
scope_results=[]
for mid in [45,46]:
    m=AnalysisModel.objects.get(pk=mid);assert not m.is_public and m.version==2
    for scope,family,day in [({},None,None),({'family':'YE4'},'YE4',None),({'family':'YE4','from':'2026-09-25','to':'2026-09-25'},'YE4','2026-09-25')]:
        result=run_analysis(admin,m.dataset,m.definition,scope);raw=independent(family,day)
        assert result['matched']==sum(g['rows'] for g in raw.values())
        for row in result['rows']:
            x=raw[row['dimension']]
            assert (row['m0'],row['m1'],row['m2'],row['row_count'])==(x['cost'],x['material'],x['produced'],x['rows'])
            expected=[Decimal(x['cost'])/100/x['produced'],Decimal(x['cost']-x['material'])/100/x['produced'],Decimal(x['material'])/x['cost']*100]
            for i,value in enumerate(expected):assert math.isclose(row[f'd{i}'],float(value),rel_tol=1e-12)
        rows,_,_=selected_rows(admin,m.dataset,m.definition,scope);assert len(rows)==result['matched']
        scope_results.append({'model':mid,'scope':scope,'rows':result['rows'],'matched':result['matched'],'display_metric':result['display_metric']})
    try:run_analysis(quality,m.dataset,m.definition)
    except ValidationError:pass
    else:raise AssertionError('Financial formula must be denied')
assert Topic.objects.get(pk=16).layout==[{'model_id':45,'span':1},{'model_id':46,'span':1}]
assert not Topic.objects.get(pk=16).is_public
v3=MetricVersion.objects.select_related('metric').get(metric__key='DELIVERY_OTIF',version=3)
assert v3.status=='published' and v3.calculation_hash==metric_registry.calculation_hash(v3.metric.dataset)
assert v3.reviewed_by not in v3.contributors and v3.reviewed_by!=v3.submitted_by
assert (v3.evidence['components'][0]['numerator'],v3.evidence['components'][0]['denominator'])==(15,165)
for version in [1,2]:assert MetricVersion.objects.get(metric__key='DELIVERY_OTIF',version=version).status=='retired'
m44=AnalysisModel.objects.get(pk=44);assert run_analysis(admin,m44.dataset,m44.definition)['matched']==300
evidence={'synthetic':True,'business_rows':106838,'business_sha256':h.hexdigest(),'tests':180,
 'unchanged_existing_models':43,'explicitly_migrated_model':44,'unchanged_existing_topics':15,
 'protected_tables_unchanged':protected,'historical_metric_definitions_unchanged':len(old_versions),
 'new_private_models':[45,46],'new_private_topic':16,'metric_version':metric_registry.receipt(v3),
 'independent_scopes':scope_results,'financial_formula_access_denied':True,
 'limits':'Only bounded arithmetic over 1–5 grouped measures, up to 3 derived outputs. No arbitrary joins, nested derived dependencies, window functions or derived-metric certification. Unit contracts must exist. Synthetic unclosed costs, not factory actual unit costs.',
 'baseline':str(baseline.relative_to(ROOT))}
if len(sys.argv)>1:
    backup=Path(sys.argv[1]).resolve()
    with zipfile.ZipFile(backup) as z,tempfile.TemporaryDirectory() as tmp:
        manifest=json.loads(z.read('manifest.json'))
        for item in manifest['files']:assert hashlib.sha256(z.read(item['path'])).hexdigest()==item['sha256']
        p=Path(tmp)/'restored.sqlite3';p.write_bytes(z.read('data/platform.sqlite3'))
        with sqlite3.connect(p) as db:
            assert db.execute('pragma integrity_check').fetchone()[0]=='ok'
            assert db.execute('select count(*) from app_record').fetchone()[0]==106838
            assert db.execute('select count(*) from app_analysismodel').fetchone()[0]==46
            assert db.execute('select count(*) from app_topic').fetchone()[0]==16
            assert json.loads(db.execute('select definition from app_analysismodel where id=44').fetchone()[0])['metric_ref']['version']==3
            assert db.execute('select is_public from app_topic where id=16').fetchone()[0]==0
    evidence['backup']={'path':str(backup.relative_to(ROOT)) if backup.is_relative_to(ROOT) else str(backup),'manifest_files':len(manifest['files']),'sqlite_integrity':'ok','restored_counts':[106838,46,16]}
(ROOT/'data/derived_validation.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2,default=str))
print(json.dumps({k:v for k,v in evidence.items() if k not in ['independent_scopes','protected_tables_unchanged','limits']},ensure_ascii=False,default=str))
