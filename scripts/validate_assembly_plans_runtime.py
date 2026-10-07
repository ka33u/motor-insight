"""Preservation audit and independent recomputation from imported Excel facts."""
import os,sys,json,copy,hashlib,sqlite3,zipfile,tempfile,csv,io
from collections import defaultdict,Counter
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings')
import django;django.setup()
from django.db import connection
from django.contrib.auth.models import User
from app.models import Record,AnalysisModel,Topic,TopicView,TopicSnapshot,ImportBatch,MetricVersion,IssueDisposition
from app import analysis_engine as engine,metric_registry as registry,targets,assembly_plans as p
from app.assembly_plan_views import FIELDS,STATES
connection.cursor().execute('PRAGMA query_only=ON')
backup=ROOT/'data/backups/motor-backup-20261004-234425.zip';report={'synthetic':True,'baseline':str(backup),'preserved_tables':{}}
expected_additions={'app_record':570,'app_importrow':570,'app_importbatch':1,'app_issuedisposition':1}
with zipfile.ZipFile(backup) as z,tempfile.TemporaryDirectory() as tmp:
    file=Path(tmp)/'before.sqlite3';file.write_bytes(z.read('data/platform.sqlite3'));report['original_files_preserved']=0
    for item in json.loads(z.read('manifest.json'))['files']:
        if item['path'].startswith(('data/imports/','data/device_files/')):
            assert hashlib.sha256((ROOT/item['path']).read_bytes()).hexdigest()==item['sha256'];report['original_files_preserved']+=1
    with sqlite3.connect(file) as old,sqlite3.connect('file:'+str(ROOT/'data/platform.sqlite3')+'?mode=ro',uri=True) as now:
        names=lambda db:{r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert names(old)==names(now)
        for table in sorted(names(old)-{'sqlite_sequence','django_session'}):
            before=old.execute('SELECT * FROM '+table+' ORDER BY rowid').fetchall();after=now.execute('SELECT * FROM '+table+' ORDER BY rowid').fetchall();lookup={r[0]:r for r in after}
            for row in before:assert lookup.get(row[0])==row,(table,'prior row changed',row[0])
            if table!='app_auditevent':assert len(after)-len(before)==expected_additions.get(table,0),(table,len(before),len(after))
            else:report['audit_additions']=dict(Counter(r[1] for r in after[len(before):]))
            report['preserved_tables'][table]={'before':len(before),'after':len(after),'prior_rows_unchanged':True}
def normalize(x):return json.loads(json.dumps(x,ensure_ascii=False,default=str))
def projection(r):
    d=copy.deepcopy(r);d.pop('metric_receipt',None)
    for part in ['pivot','scatter']:
        if d.get(part):d[part].pop('revision',None)
    return normalize(d)
admin=User.objects.get(username='demo_admin');prior=json.loads((ROOT/'data/assembly_plans_before.json').read_text())
for mid,before in prior['models'].items():
    m=AnalysisModel.objects.get(pk=mid);assert projection(engine.run_analysis(admin,m.dataset,m.definition))==projection(before),mid
report['existing_model_results_preserved']=len(prior['models'])
assert {r['id']:normalize(r) for r in targets.Targets(admin).rows.values()}=={r['id']:r for r in prior['targets']}
report['all_target_results_preserved']=len(prior['targets'])
counts=(Record.objects.count(),Record.objects.values('dataset').distinct().count(),ImportBatch.objects.exclude(status='superseded').count(),AnalysisModel.objects.count(),Topic.objects.count(),TopicView.objects.count(),TopicSnapshot.objects.count())
assert counts==(116867,79,22,52,21,6,4),counts
report['counts']=dict(zip(['records','datasets','active_workbooks','models','topics','views','snapshots'],counts))
metric=MetricVersion.objects.get(metric__key='DELIVERY_OTIF',version=8,status='published')
assert metric.calculation_hash==registry.calculation_hash(metric.metric.dataset)=='9d9a5af3d45172eca16790d628a36bc6acbe18d1e2a811a66a5b5fbff7037fe3'
report['published_metric_unchanged']={'version':metric.version,'hash':metric.calculation_hash}
raw=defaultdict(dict)
for ds,row in Record.objects.values_list('dataset','values'):raw[ds][row['id']]=row
scenario=json.loads((ROOT/'data/assembly_plans_scenario.json').read_text())
for ds,rows in scenario['tables'].items():assert raw[ds]=={r['id']:r for r in rows}
cutoff='2026-10-01T18:00:00';calc=p.Plans();independent_days={};source_keys=set()
for date_key,info in calc.days.items():
    snapshots=[h for h in raw[p.DATASETS[0]].values() if h['production_date']==date_key]
    published=[h for h in snapshots if h['status']=='已发布' and h['released']<=cutoff]
    newest=max(published,key=lambda h:h['version']);frozen=max((h for h in published if h['released']<=h['freeze_at']),key=lambda h:h['version'])
    assert info['baseline']['id']==frozen['id'] and info['current']['id']==newest['id']
    get_lines=lambda h:{line['work_order_id']:line['qty'] for line in raw[p.DATASETS[1]].values() if line['version_id']==h['id']}
    bmap=get_lines(frozen);cmap=get_lines(newest)
    all_units=[u for u in raw['units'].values() if u['assembly_at'][:10]==date_key]
    units=[u for u in all_units if u['assembly_at']<=cutoff];actual=Counter(u['work_order_id'] for u in units)
    declared=[c for c in raw[p.DATASETS[2]].values() if c['production_date']==date_key and not c['voided'] and c['confirmed']<=cutoff]
    check=max(declared,key=lambda c:c['confirmed']) if declared else None
    digest=hashlib.sha256(json.dumps(sorted(all_units,key=lambda x:x['id']),ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    complete=bool(check and check['status']=='完整' and check['through']>=date_key+'T23:59:59' and check['data_signature']==digest)
    expected_state='future' if date_key>cutoff[:10] else 'in_progress' if date_key==cutoff[:10] else 'confirmed' if complete else 'unconfirmed'
    assert info['state']==expected_state
    quantities={}
    for r in info['rows']:
        wo=r['work_order_id'];observed=None if expected_state=='future' else actual[wo]
        assert (r['baseline_qty'],r['current_qty'],r['observed_qty'])==(bmap.get(wo,0),cmap.get(wo,0),observed)
        assert r['changed']==(bmap.get(wo,0)!=cmap.get(wo,0))
        for mode,plan in [('baseline',bmap),('current',cmap)]:
            assert r[mode+'_eligible']==(expected_state=='confirmed')
            assert r[mode+'_fulfilled']==(min(actual[wo],plan.get(wo,0)) if observed is not None else None)
        expected_ids={u['id'] for u in units if u['work_order_id']==wo};assert {u['id'] for u in r['units']}==expected_ids
        refs={(ref['dataset'],ref['key']) for ref in r['sources']};assert {(ds,key) for ds,key in refs if ds=='units'}=={('units',key) for key in expected_ids}
        source_keys.update(refs)
    for mode,plan in [('baseline',bmap),('current',cmap)]:
        planned=sum(plan.values());fulfilled=sum(min(actual[wo],qty) for wo,qty in plan.items())
        q={'scheduled':planned,'fulfilled':fulfilled if expected_state=='confirmed' else None,'rate':fulfilled/planned*100 if expected_state=='confirmed' and planned else None}
        s=p.summary(info['rows']);assert s[mode+'_scheduled']==planned;assert s[mode+'_rate']==q['rate'];quantities[mode]=q
    independent_days[date_key]={'state':expected_state,'observed':sum(actual.values()) if expected_state!='future' else None,**quantities}
assert all(key in raw[ds] for ds,key in source_keys);report['source_references_verified']=len(source_keys)
report['independent_days']=independent_days
selected=calc.selected(p.params({'from':'2026-09-22','to':'2026-09-22'}));download=ROOT/'outputs/装配计划_20260922_工单日.csv';exported=list(csv.reader(io.StringIO(download.read_text(encoding='utf-8-sig'))));to_text=lambda v:'' if v is None else str(v)
assert exported[4]==[label for _,label in FIELDS]+['资料状态','核对事项']
assert exported[5:]==[[to_text(r.get(field)) for field,_ in FIELDS]+[STATES[r['state']],'；'.join(r['issues'])] for r in selected]
report['browser_csv_reconciled']={'rows':len(selected),'sha256':hashlib.sha256(download.read_bytes()).hexdigest()}
follow=IssueDisposition.objects.get(key='assembly-plan:2026-09-22~MO2609-000203');assert follow.version==1 and '模拟' in follow.note
report['coordination']={'key':follow.key,'version':follow.version,'status':follow.status}
report['snapshots']=[{'id':str(s.pk),'sha256':s.payload_hash} for s in TopicSnapshot.objects.all()]
(ROOT/'data/assembly_plans_validation.json').write_text(json.dumps(report,ensure_ascii=False,indent=2,default=str))
print(json.dumps({k:v for k,v in report.items() if k!='preserved_tables'},ensure_ascii=False,default=str))
