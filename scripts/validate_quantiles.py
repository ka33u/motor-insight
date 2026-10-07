"""Read-only reconciliation: original facts, old analyses, quantiles and frozen exports."""
import os,sys,json,copy,hashlib,sqlite3,zipfile,tempfile,csv,io,statistics,math
from fractions import Fraction
from collections import defaultdict,Counter
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings')
import django;django.setup()
from django.db import connection
from django.contrib.auth.models import User
from app.models import Record,AnalysisModel,Topic,TopicView,TopicSnapshot,ImportBatch,MetricVersion
from app import analysis_engine as engine,metric_registry as registry,topic_workspace as ws,topic_snapshots as ss,analysis_pivot as pv
connection.cursor().execute('PRAGMA query_only=ON')
admin=User.objects.get(username='demo_admin');backup=ROOT/'data/backups/motor-backup-20261004-194206.zip'
report={'synthetic':True,'baseline':str(backup),'preserved_tables':{}}
deltas={'app_analysismodel':1,'app_topic':1,'app_topicview':1,'app_topicsnapshot':1,'app_metricversion':1}
allowed={('app_analysismodel',44):{'definition','version','updated_at'},('app_metricversion',10):{'status','revision','reviewed_by','review_note','retired_at','updated_at'}}
with zipfile.ZipFile(backup) as z,tempfile.TemporaryDirectory() as tmp:
    p=Path(tmp)/'before.sqlite3';p.write_bytes(z.read('data/platform.sqlite3'))
    report['original_files_preserved']=0
    for f in json.loads(z.read('manifest.json'))['files']:
        if f['path'].startswith(('data/imports/','data/device_files/')):
            assert hashlib.sha256((ROOT/f['path']).read_bytes()).hexdigest()==f['sha256'];report['original_files_preserved']+=1
    with sqlite3.connect(p) as old,sqlite3.connect('file:'+str(ROOT/'data/platform.sqlite3')+'?mode=ro',uri=True) as now:
        names=lambda db:{r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert names(old)==names(now)
        for table in sorted(names(old)-{'sqlite_sequence','django_session'}):
            columns=[r[1] for r in old.execute('PRAGMA table_info('+table+')')]
            before=old.execute('SELECT * FROM '+table+' ORDER BY rowid').fetchall();after=now.execute('SELECT * FROM '+table+' ORDER BY rowid').fetchall();lookup={r[0]:r for r in after};changed={}
            for row in before:
                assert row[0] in lookup,(table,'removed',row[0]);diff={c for c,a,b in zip(columns,row,lookup[row[0]]) if a!=b}
                assert diff<=allowed.get((table,row[0]),set()),(table,row[0],diff)
                if diff:changed[row[0]]=sorted(diff)
            if table!='app_auditevent':assert len(after)-len(before)==deltas.get(table,0),(table,len(before),len(after))
            else:report['audit_additions']=dict(Counter(r[1] for r in after[len(before):]))
            report['preserved_tables'][table]={'before':len(before),'after':len(after),'changed_prior_rows':changed}
        d=json.loads(old.execute('SELECT definition FROM app_analysismodel WHERE id=44').fetchone()[0]);d['metric_ref']['version']=8
        assert AnalysisModel.objects.get(pk=44).definition==d

def projection(r):
    d=copy.deepcopy(r);d.pop('definition',None);d.pop('metric_receipt',None)
    for part in ['pivot','scatter']:
        if d.get(part):d[part].pop('revision',None);d[part].pop('notice',None)
    return json.loads(json.dumps(d,ensure_ascii=False,default=str))
prior=json.loads((ROOT/'data/percentile_before.json').read_text())
for mid,before in prior.items():
    m=AnalysisModel.objects.get(pk=mid);assert projection(engine.run_analysis(admin,m.dataset,m.definition))==projection(before),mid
report['existing_model_results_preserved']=len(prior)
counts=(Record.objects.count(),Record.objects.values('dataset').distinct().count(),ImportBatch.objects.exclude(status='superseded').count(),AnalysisModel.objects.count(),Topic.objects.count(),TopicView.objects.count(),TopicSnapshot.objects.count())
assert counts==(111284,70,19,52,21,6,4),counts
report['counts']=dict(zip(['records','datasets','active_workbooks','models','topics','views','snapshots'],counts))
v=MetricVersion.objects.get(metric__key='DELIVERY_OTIF',version=8,status='published');assert v.calculation_hash==registry.calculation_hash(v.metric.dataset)
assert MetricVersion.objects.get(metric__key='DELIVERY_OTIF',version=7).status=='retired';report['published_metric']=registry.receipt(v)

# Recompute from JSON fact rows independently using exact rational ranks and Python median.
raw=list(Record.objects.filter(dataset='labor_entries').values_list('values',flat=True));m=AnalysisModel.objects.get(pk=52)
assert m.definition['metrics'][3]['percentile']==90 and m.definition['metrics'][4]['percentile']==95
checks=0

def verify(cell,source):
    global checks
    assert cell['row_count']==len(source)
    if not source:assert all(cell['m'+str(i)] is None for i in range(5));return
    values=sorted(Fraction(str(r['minutes'])) for r in source if r.get('minutes') is not None)
    assert cell['m0']==len(source);assert math.isclose(cell['m1'],float(sum(values)/len(values)),rel_tol=1e-12)
    for key,p in [('m2',50),('m3',90),('m4',95)]:
        rank=(len(values)-1)*Fraction(p,100);lo=rank.numerator//rank.denominator;hi=math.ceil(rank)
        expected=values[lo]+(values[hi]-values[lo])*(rank-lo)
        assert math.isclose(cell[key],float(expected),rel_tol=1e-12),(cell['dimension'],key,cell[key],expected)
        meta=cell['quantiles'][key];assert (meta['source_rows'],meta['valid_rows'],meta['missing_rows'])==(len(source),len(values),len(source)-len(values))
        assert (meta['lower_rank'],meta['upper_rank'])==(lo+1,hi+1);assert meta['percentile']==p and meta['method']=='linear_n_minus_1'
        assert float(values[lo])==meta['lower_value'] and float(values[hi])==meta['upper_value'];checks+=1
    assert cell['m2']==statistics.median([float(x) for x in values])

def check_result(r,source):
    for cell in r['rows']:verify(cell,[x for x in source if x['activity']==cell['dimension']])

full=engine.run_analysis(admin,m.dataset,m.definition);check_result(full,raw)
view=TopicView.objects.get(pk=6);ctx=ws.context(admin,21);conf=view.config
result=ws.run(admin,21,{'context_token':ctx['context_token'],'config':conf});report['scopes']={}
for side,sk in [('primary','scope'),('reference','reference_scope')]:
    scope=conf[sk];selected=[x for x in raw if scope['from']<=x['started'][:10]<=scope['to']];check_result(result['cards'][0][side],selected)
    report['scopes'][side]={'records':len(selected),'groups':len(result['cards'][0][side]['rows'])}
# A temporary two-axis result proves all cell and margin percentiles use source populations.
d={**m.definition,'chart':'pivot','pivot':{'dimension':'started','grain':'day'}};r=engine.run_analysis(admin,m.dataset,d);p=r['pivot'];rows={a['key']:a['label'] for a in p['rows']};cols={a['key']:a['label'] for a in p['columns']}
for cell in [*p['cells'],*p['row_totals'],*p['column_totals'],p['grand_total']]:
    selected=[x for x in raw if (cell['row'] is None or x['activity']==rows[cell['row']]) and (cell['column'] is None or x['started'][:10]==cols[cell['column']])];verify(cell,selected)
report['pivot']={'rows':len(rows),'columns':len(cols),'cells':len(p['cells']),'source_rows':p['grand_total']['row_count'],'total_p50':p['grand_total']['m2'],'total_p90':p['grand_total']['m3'],'total_p95':p['grand_total']['m4']}
report['independently_recomputed_quantiles']=checks
report['full_groups']=full['rows']
s=TopicSnapshot.objects.get(pk='2e472e22-15d6-45dd-91bd-bbbc93c4011b');assert ss.export_rows(s)
expected=ss.export_rows(s);downloaded=list(csv.reader(io.StringIO((ROOT/'outputs/BI分位数_冻结结果.csv').read_text(encoding='utf-8-sig'))))
assert downloaded==[['' if v is None else str(v) for v in row] for row in expected]
assert len(downloaded)==36 and all(len(row)==16 for row in downloaded)
report['snapshot']={'id':str(s.pk),'sha256':s.payload_hash,'objects':sum(len(rows) for card in s.payload['cohorts'].values() for rows in card.values()),'sources':len(s.payload['sources']),'csv_data_rows':len(downloaded)-1}
(ROOT/'data/quantile_validation.json').write_text(json.dumps(report,ensure_ascii=False,indent=2,default=str))
print(json.dumps({k:v for k,v in report.items() if k not in ['preserved_tables','full_groups','published_metric']},ensure_ascii=False,default=str))
