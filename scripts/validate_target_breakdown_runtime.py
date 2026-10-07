"""Read-only preservation audit and independent raw-fact breakdown checks.

This stage reuses existing synthetic Excel facts. It changes one explicitly
reviewed coordination note; no target, model or source fact is rewritten.
"""
import os,sys,json,copy,hashlib,sqlite3,zipfile,tempfile,csv,io
from collections import defaultdict,Counter
from statistics import median
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings')
import django;django.setup()
from django.db import connection
from django.contrib.auth.models import User
from app.models import Record,AnalysisModel,Topic,TopicView,TopicSnapshot,ImportBatch,MetricVersion,IssueDisposition
from app import analysis_engine as engine,metric_registry as registry,targets as k
from app.target_breakdown import Breakdown
from app.target_breakdown_views import FIELDS
connection.cursor().execute('PRAGMA query_only=ON')
backup=ROOT/'data/backups/motor-backup-20261004-224551.zip'
report={'synthetic':True,'baseline':str(backup),'preserved_tables':{}}
coordination_key='target:MB-ZP-260922-V02'
with zipfile.ZipFile(backup) as z,tempfile.TemporaryDirectory() as tmp:
    p=Path(tmp)/'before.sqlite3';p.write_bytes(z.read('data/platform.sqlite3'));report['original_files_preserved']=0
    for f in json.loads(z.read('manifest.json'))['files']:
        if f['path'].startswith(('data/imports/','data/device_files/')):
            assert hashlib.sha256((ROOT/f['path']).read_bytes()).hexdigest()==f['sha256'];report['original_files_preserved']+=1
    with sqlite3.connect(p) as old,sqlite3.connect('file:'+str(ROOT/'data/platform.sqlite3')+'?mode=ro',uri=True) as now:
        names=lambda db:{r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert names(old)==names(now)
        for table in sorted(names(old)-{'sqlite_sequence','django_session'}):
            before=old.execute('SELECT * FROM '+table+' ORDER BY rowid').fetchall();after=now.execute('SELECT * FROM '+table+' ORDER BY rowid').fetchall();lookup={r[0]:r for r in after};changed=[]
            for row in before:
                if lookup.get(row[0])==row:continue
                assert table=='app_issuedisposition', (table,'changed prior row',row[0])
                cols=[r[1] for r in old.execute('PRAGMA table_info('+table+')')];a=dict(zip(cols,row));b=dict(zip(cols,lookup[row[0]]))
                assert a['key']==b['key']==coordination_key and a['version']==1 and b['version']==2
                assert b['note'].startswith(a['note']+'\n分组观察（原因待核实）：')
                assert all(a[c]==b[c] for c in cols if c not in ['note','version','updated_at'])
                changed.append(a['key'])
            if table!='app_auditevent':assert len(after)==len(before),(table,len(before),len(after))
            else:
                additions=after[len(before):];report['audit_additions']=dict(Counter(r[1] for r in additions))
                assert set(report['audit_additions'])<={'target.breakdown.export','target.followup'}
                assert report['audit_additions'].get('target.followup')==1
            report['preserved_tables'][table]={'before':len(before),'after':len(after),'changed_prior_keys':changed}

def normalize(x):return json.loads(json.dumps(x,ensure_ascii=False,default=str))
def projection(r):
    d=copy.deepcopy(r);d.pop('metric_receipt',None)
    for part in ['pivot','scatter']:
        if d.get(part):d[part].pop('revision',None)
    return normalize(d)
admin=User.objects.get(username='demo_admin');prior=json.loads((ROOT/'data/target_breakdown_before.json').read_text())
for mid,before in prior['models'].items():
    m=AnalysisModel.objects.get(pk=mid);assert projection(engine.run_analysis(admin,m.dataset,m.definition))==projection(before),mid
report['existing_model_results_preserved']=len(prior['models'])
calc=k.Targets(admin)
assert {r['id']:normalize(r) for r in calc.rows.values()}=={r['id']:r for r in prior['targets']}
report['all_target_results_preserved']=len(prior['targets'])
counts=(Record.objects.count(),Record.objects.values('dataset').distinct().count(),ImportBatch.objects.exclude(status='superseded').count(),AnalysisModel.objects.count(),Topic.objects.count(),TopicView.objects.count(),TopicSnapshot.objects.count())
assert counts==(116297,76,21,52,21,6,4),counts
report['counts']=dict(zip(['records','datasets','active_workbooks','models','topics','views','snapshots'],counts))
v=MetricVersion.objects.get(metric__key='DELIVERY_OTIF',version=8,status='published')
assert v.calculation_hash==registry.calculation_hash(v.metric.dataset)=='9d9a5af3d45172eca16790d628a36bc6acbe18d1e2a811a66a5b5fbff7037fe3'
report['published_metric_unchanged']={'version':v.version,'hash':v.calculation_hash}
raw=defaultdict(dict)
for ds,row in Record.objects.values_list('dataset','values'):raw[ds][row['id']]=row
cohort=[u for u in raw['units'].values() if u['assembly_at'][:10]=='2026-09-22']
family=lambda u:raw['products'][u['product_id']]['family']
expected_family=Counter(family(u) for u in cohort);expected_config=Counter(u['product_id'] for u in cohort)
assert expected_family=={'YE3':315,'YE4':315,'YVF2':270} and sum(expected_config.values())==900
prod=Breakdown(admin,'MB-ZP-260922-V02',calc);root=prod.calculate({})
assert {r['label']:r['actual'] for r in root['rows']}==expected_family
for r in root['rows']:assert r['share_pct']==expected_family[r['label']]/900*100
config=prod.calculate({'dimension':'product_id'})
assert {r['label']:r['actual'] for r in config['rows']}==expected_config
group=next(r for r in root['rows'] if r['label']=='YE3');path=[dict(dimension='product.family',grain='value',token=group['token'])]
nested=prod.calculate({'path':json.dumps(path),'dimension':'product_id'})
assert {r['label']:r['actual'] for r in nested['rows']}==Counter(u['product_id'] for u in cohort if family(u)=='YE3')
group=next(r for r in nested['rows'] if r['label']=='CP.00002.A')
params={'path':json.dumps(path),'dimension':'product_id','group':group['token']}
facts,axis,_,_=prod.evidence(params);expected_ids={u['id'] for u in cohort if family(u)=='YE3' and u['product_id']=='CP.00002.A'}
assert {r['id'] for r in facts}==expected_ids and len(facts)==30
for row in facts:
    assert set((r['dataset'],r['key']) for r in prod.source_refs(row,params,axis))=={('units',row['id']),('products','CP.00002.A')}
report['independent_count_checks']={'family':dict(expected_family),'config_groups':len(expected_config),'nested_configs':nested['groups'],'nested_evidence_ids':sorted(expected_ids)}

# Rebuild first complete valid test from raw spec limits and measurement values.
ms=defaultdict(list);required=defaultdict(set);complete=defaultdict(list)
for spec in raw['test_specs'].values():
    if spec['mandatory']:required[(spec['product_id'],spec['version'])].add(spec['id'])
for m in raw['measurements'].values():ms[m['session_id']].append(m)
for s in raw['test_sessions'].values():
    if s['voided'] or s['tested']>'2026-10-01T18:00:00':continue
    pid=raw['units'][s['unit_id']]['product_id'];needed=required[(pid,s['spec_version'])];measurements=ms[s['id']];ids=[m['spec_id'] for m in measurements]
    if not needed or not needed.issubset(ids) or len(ids)!=len(set(ids)):continue
    passed=True;valid=True
    for m in measurements:
        spec=raw['test_specs'].get(m['spec_id'])
        if not spec or (spec['product_id'],spec['version'],spec['unit'])!=(pid,s['spec_version'],m['unit']):valid=False;break
        passed&=(spec['lsl'] is None or m['value']>=spec['lsl']) and (spec['usl'] is None or m['value']<=spec['usl'])
    if valid:complete[s['unit_id']].append((s['tested'],s['attempt'],s['id'],passed))
first={uid:sorted(sessions)[0][-1] for uid,sessions in complete.items()}
quality=Breakdown(admin,'MB-ZL-260922-V01',calc).calculate({});ratio_checks=[]
for r in quality['rows']:
    tests=[first[u['id']] for u in cohort if family(u)==r['label'] and u['id'] in first];num=sum(tests);den=len(tests)
    assert (r['numerator'],r['denominator'])==(num,den)
    assert abs(r['actual']-num/den*100)<1e-9 and r['share_pct'] is None
    assert abs(r['difference']-(r['actual']-quality['parent']['actual']))<1e-9
    ratio_checks.append({'family':r['label'],'numerator':num,'denominator':den,'actual':r['actual']})
assert abs(quality['parent']['actual']-sum(x['numerator'] for x in ratio_checks)/sum(x['denominator'] for x in ratio_checks)*100)<1e-9
report['independent_ratio_checks']=ratio_checks
labor=[r for r in raw['labor_entries'].values() if r['started'][:10]=='2026-09-22'];by_activity=defaultdict(list)
for r in labor:by_activity[r['activity']].append(r['minutes'])
quantile=Breakdown(admin,'MB-GS-260922-V01',calc).calculate({})
assert quantile['parent']['actual']==median(r['minutes'] for r in labor)
for r in quantile['rows']:
    values=by_activity[r['label']];assert r['actual']==median(values) and r['valid_rows']==len(values) and r['share_pct'] is None
report['independent_median_checks']={'whole':quantile['parent']['actual'],'rows':len(labor),'groups':{a:{'median':median(v),'count':len(v)} for a,v in by_activity.items()}}

# All executable target roots retain their value and a disjoint source partition.
checks=[]
for target in calc.rows.values():
    if target['state']=='blocked':continue
    b=Breakdown(admin,target['id'],calc);result=b.calculate({});parts=b.partition(b.rows,result['axis'])
    ids=[r['id'] for p in parts.values() for r in p['rows']]
    assert len(ids)==len(set(ids))==len(b.rows)
    assert set(ids)=={r['id'] for r in b.rows}
    assert result['parent']['actual']==target['actual']
    checks.append({'target':target['id'],'axis':result['axis']['dimension'],'groups':result['groups'],'sources':len(ids),'actual':result['parent']['actual']})
report['scope_conservation_checks']=checks
download=ROOT/'outputs/BI目标分组_配置构成.csv';exported=list(csv.reader(io.StringIO(download.read_text(encoding='utf-8-sig'))))
to_text=lambda v:'' if v is None else str(v)
assert exported[5]==[label for _,label in FIELDS]+['分位数依据','计算提示']
assert exported[6:]==[[to_text(r.get(f)) for f,_ in FIELDS]+[json.dumps(r['quantile'],ensure_ascii=False) if r['quantile'] else '', '；'.join(r['notes'])] for r in config['rows']]
report['browser_csv_reconciled']={'file':str(download),'groups':len(exported)-6,'sha256':hashlib.sha256(download.read_bytes()).hexdigest()}
follow=IssueDisposition.objects.get(key=coordination_key)
assert follow.version==2 and 'YE3：315台' in follow.note and '原因待核实' in follow.note
report['coordination']={'key':follow.key,'version':follow.version,'status':follow.status}
report['snapshots']=[{'id':str(s.pk),'sha256':s.payload_hash} for s in TopicSnapshot.objects.all()]
(ROOT/'data/target_breakdown_validation.json').write_text(json.dumps(report,ensure_ascii=False,indent=2,default=str))
print(json.dumps({key:value for key,value in report.items() if key not in ['preserved_tables','scope_conservation_checks']},ensure_ascii=False,default=str))
