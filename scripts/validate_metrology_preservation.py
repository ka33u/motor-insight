"""Verify every old SQL row, original bytes, models, targets and published hash."""
import os,sys,json,sqlite3,hashlib
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings')
before=json.loads((ROOT/'data/metrology-before/manifest.json').read_text());added=json.loads((ROOT/'data/metrology_actual_import.json').read_text())
tables=[];additions={}
with sqlite3.connect('file:'+str(ROOT/'data/platform.sqlite3')+'?mode=ro',uri=True) as c:
    c.execute('ATTACH DATABASE ? AS prior',(before['database'],))
    for (name,) in c.execute("SELECT name FROM prior.sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'").fetchall():
        assert name.replace('_','').isalnum()
        missing=c.execute(f'SELECT COUNT(*) FROM (SELECT * FROM prior."{name}" EXCEPT SELECT * FROM main."{name}")').fetchone()[0]
        assert missing==0,(name,missing)
        increase=c.execute(f'SELECT COUNT(*) FROM (SELECT * FROM main."{name}" EXCEPT SELECT * FROM prior."{name}")').fetchone()[0]
        additions[name]=increase;tables.append(name)
        if name not in ['app_record','app_importrow','app_importbatch','app_auditevent']:assert increase==0,(name,increase)
    assert additions['app_record']==additions['app_importrow']==44253 and additions['app_importbatch']==1
    assert c.execute('SELECT COUNT(*) FROM app_record').fetchone()[0]==211942
for name,sha in before['files'].items():assert hashlib.sha256((ROOT/name).read_bytes()).hexdigest()==sha,name
for name,sha in before['calculation_files'].items():assert hashlib.sha256((ROOT/name).read_bytes()).hexdigest()==sha,name
import django;django.setup()
from app.models import AnalysisModel,MetricVersion,Record
from app import targets,metric_registry
from app.analysis_engine import run_analysis
from app.metrology import TABLES,Metrology,summary
from django.contrib.auth.models import User
defaults=json.loads((ROOT/'data/assembly_plans_before.json').read_text());admin=User.objects.get(username='demo_admin')
def projection(v):
    v=json.loads(json.dumps(v,default=str));v.pop('metric_receipt',None)
    for k in ['pivot','scatter']:
        if isinstance(v.get(k),dict):v[k].pop('revision',None)
    return v
for mid,v in defaults['models'].items():
    m=AnalysisModel.objects.get(pk=mid);assert projection(run_analysis(admin,m.dataset,m.definition))==projection(v),mid
assert len(defaults['models'])==52
assert {r['id']:json.loads(json.dumps(r,default=str)) for r in targets.Targets(admin).rows.values()}=={r['id']:r for r in defaults['targets']}
metric=MetricVersion.objects.get(status='published',metric__key='DELIVERY_OTIF',version=8)
assert metric.calculation_hash==metric_registry.calculation_hash(metric.metric.dataset)=='9d9a5af3d45172eca16790d628a36bc6acbe18d1e2a811a66a5b5fbff7037fe3'
assert Record.objects.filter(dataset__in=TABLES).count()==44253
build=json.loads((ROOT/'data/metrology_scenario_build.json').read_text());assert summary(Metrology().rows)==build['summary']
report=dict(synthetic=True,old_sql_tables=len(tables),all_old_sql_rows_unchanged=True,additions=additions,old_facts=167689,new_register_rows=44253,records_after=211942,
            old_physical_files=len(before['files']),old_files_unchanged=True,protected_calculations=len(before['calculation_files']),models_unchanged=52,targets_unchanged=33,published_otif_version=8,published_hash=metric.calculation_hash,new_metric_publication=False)
report['database_sha256']=hashlib.sha256((ROOT/'data/platform.sqlite3').read_bytes()).hexdigest()
report['baseline_database_sha256']=hashlib.sha256(Path(before['database']).read_bytes()).hexdigest()
(ROOT/'data/metrology_preservation.json').write_text(json.dumps(report,ensure_ascii=False,indent=2));print(json.dumps({k:v for k,v in report.items() if k!='additions'},ensure_ascii=False))
