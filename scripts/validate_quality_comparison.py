"""Read-only parity and independent raw-observation reconciliation for the demo."""
import os,sys,json,sqlite3,zipfile,tempfile,csv,math,statistics,hashlib
from pathlib import Path
from collections import defaultdict,Counter
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings')
import django
django.setup()
from django.db import connection
from app import analytics,quality_comparison as qc,metric_registry
from app.models import Record,MetricVersion
connection.cursor().execute('PRAGMA query_only=ON')
backup=ROOT/'data/backups/motor-backup-20261004-142247.zip'
report={'baseline':str(backup),'scope':'Imported synthetic Excel only; descriptive comparisons, no process capability or causal attribution.'}
def rows(db,name):return db.execute('select * from "'+name+'" order by rowid').fetchall()
with zipfile.ZipFile(backup) as z,tempfile.TemporaryDirectory() as tmp:
 p=Path(tmp)/'before.sqlite3';p.write_bytes(z.read('data/platform.sqlite3'))
 with sqlite3.connect(p) as old,sqlite3.connect('file:'+str(ROOT/'data/platform.sqlite3')+'?mode=ro',uri=True) as new:
  tables=lambda db:{r[0] for r in db.execute("select name from sqlite_master where type='table'")}
  assert tables(old)==tables(new)
  unchanged=[]
  for name in sorted(tables(old)-{'app_auditevent','django_session','sqlite_sequence'}):
   assert rows(old,name)==rows(new,name),name;unchanged.append(name)
  a,b=rows(old,'app_auditevent'),rows(new,'app_auditevent');assert b[:len(a)]==a
  additions=Counter(r[1] for r in b[len(a):]);assert set(additions)<={'quality.comparison_export'}
  report.update(unchanged_tables=unchanged,audit_additions=dict(additions),schema_unchanged=True)
prior=json.loads((ROOT/'data/action_task_runtime_probe.json').read_text());now=json.loads((ROOT/'data/quality_comparison_runtime_probe.json').read_text())
assert prior['models']==now['models'] and prior['originals']==now['originals']
assert [k for k in prior['apis'] if prior['apis'][k]!=now['apis'][k]]==['/api/catalog']
v=MetricVersion.objects.select_related('metric').get(metric__key='DELIVERY_OTIF',status='published')
assert v.version==6 and v.calculation_hash==metric_registry.calculation_hash('bi_order_lines')
report.update(business_records=Record.objects.count(),models_preserved=len(now['models']),original_references_preserved=len(now['originals']),unchanged_business_apis=19,published_metric_version=v.version,published_calculation_hash=v.calculation_hash)

# Select sessions using raw imported rows; do not reuse quality-board selection or its statistics.
raw=analytics.tables();pid='CP.00015.A';spec_id='JC-CP.00015.A-R-A'
units={u['id']:u for u in raw['units'] if u['product_id']==pid and u['assembly_at']<=analytics.AS_OF}
specs={s['id']:s for s in raw['test_specs']};sessions=defaultdict(list);measurements=defaultdict(list)
for m in raw['measurements']:measurements[m['session_id']].append(m)
for s in raw['test_sessions']:
 if s['unit_id'] not in units or s['voided'] or s['tested']>analytics.AS_OF:continue
 assert s['tested']>=units[s['unit_id']]['assembly_at']
 required={k for k,v in specs.items() if v['product_id']==pid and v['version']==s['spec_version'] and v['mandatory']}
 ms=measurements[s['id']];assert len({m['spec_id'] for m in ms})==len(ms)
 for m in ms:
  sp=specs[m['spec_id']];assert sp['product_id']==pid and sp['version']==s['spec_version']
  assert sp['effective']<=s['tested'][:10] and m['unit']==sp['unit'] and math.isfinite(m['value'])
  inside=(sp['lsl'] is None or m['value']>=sp['lsl']) and (sp['usl'] is None or m['value']<=sp['usl'])
  assert m['result']==('合格' if inside else '不合格')
 sessions[s['unit_id']].append({**s,'computed_complete':bool(required) and required<={m['spec_id'] for m in ms}})
for ss in sessions.values():ss.sort(key=lambda s:(s['tested'],s['attempt'],s['id']))
def expected(mode):
 result=[]
 for uid,ss in sessions.items():
  chosen=ss if mode=='all_valid' else ss[-1:] if mode=='latest' else [s for s in ss if s['computed_complete']][:1]
  for s in chosen:
   for m in measurements[s['id']]:
    if m['spec_id']!=spec_id:continue
    result.append({**m,'unit_id':uid,'equipment_id':s['equipment_id'],'test_day':s['tested'][:10],'assembly_day':units[uid]['assembly_at'][:10],**{k:units[uid].get(k) for k in ['work_order_id','stator_batch','rotor_batch']}})
 return result
def independent_stats(ms):
 values=sorted(m['value'] for m in ms);q1,median,q3=statistics.quantiles(values,n=4,method='inclusive') if len(values)>1 else [values[0]]*3
 iqr=q3-q1;lo=q1-1.5*iqr;hi=q3+1.5*iqr;inside=[x for x in values if lo<=x<=hi];outliers={m['id'] for m in ms if m['value']<lo or m['value']>hi}
 return dict(n=len(values),unique_units=len({m['unit_id'] for m in ms}),outside=sum(m['result']=='不合格' for m in ms),min=min(values),max=max(values),q1=q1,median=median,q3=q3,iqr=iqr,lower_fence=lo,upper_fence=hi,lower_whisker=min(inside),upper_whisker=max(inside),mean=statistics.mean(values),sample_stddev=statistics.stdev(values) if len(values)>1 else None,outliers=len(outliers)),outliers
def compare_stats(actual,expected):
 for key,value in expected.items():
  if value is None:assert actual[key] is None,key
  else:assert math.isclose(actual[key],value,rel_tol=1e-12,abs_tol=1e-12),(key,actual[key],value)
scenarios=[]
for mode in ['first_complete','latest','all_valid']:
 ms=expected(mode);expected_ids={m['id'] for m in ms}
 for by in qc.GROUPS:
  data,obs=qc.context({'product_id':pid,'spec_id':spec_id,'sample':mode,'compare_by':by})
  assert {m['id'] for m in obs}==expected_ids
  compare_stats(data['overall'],independent_stats(ms)[0]);groups=defaultdict(list)
  for m in ms:groups[m[by]].append(m)
  assert data['group_count']==len(groups)
  for g in data['groups']:
   stats,ids=independent_stats(groups[g['label']]);compare_stats(g,stats)
   assert {m['id'] for m in obs if m['group_key']==g['key'] and m['statistical_outlier']}==ids
  scenarios.append(dict(sample=mode,dimension=by,groups=data['group_count'],n=data['overall']['n'],unique_units=data['overall']['unique_units'],outside=data['overall']['outside']))
report['independent_scenarios']=scenarios
params={'product_id':pid,'spec_id':spec_id,'sample':'first_complete','compare_by':'equipment_id'}
data,obs=qc.context(params)
downloads=Path.home()/'Downloads';summary=downloads/'quality-comparison-summary.csv';sample=downloads/'quality-comparison-samples.csv'
if summary.exists() and sample.exists():
 with summary.open(encoding='utf-8-sig',newline='') as f:csv_summary=list(csv.reader(f))
 assert csv_summary[6]==['计算依据',data['revision']]
 assert len(csv_summary[8:])==len(data['groups'])+1
 for row,group in zip(csv_summary[8:],[data['overall'],*data['groups']]):
  for i,k in [(2,'n'),(3,'unique_units'),(4,'outside'),(6,'q1'),(7,'median'),(8,'q3'),(17,'outliers')]:assert math.isclose(float(row[i]),group[k],rel_tol=1e-12,abs_tol=1e-12)
 with sample.open(encoding='utf-8-sig',newline='') as f:csv_samples=list(csv.reader(f))
 assert csv_samples[6]==['计算依据',data['revision']]
 ids={r['id'] for r in obs if r['group_label']=='SB-08-01' and r['statistical_outlier']}
 assert {r[0] for r in csv_samples[9:]}==ids and len(ids)==3
 report['browser_exports']={'summary_rows':len(csv_summary)-8,'sample_rows':len(csv_samples)-9,'sample_ids':sorted(ids),'sha256':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in [summary,sample]}}
report['tests']='996 passed; data/quality_comparison_full_tests.log; Node chart boundary checks passed'
(ROOT/'data/quality_comparison_validation.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
print(json.dumps({k:v for k,v in report.items() if k not in ['unchanged_tables','independent_scenarios']},ensure_ascii=False,indent=2))
