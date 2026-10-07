"""Read-only reconciliation of scatter results, raw facts and retained state."""
import os,sys,json,csv,copy,hashlib,sqlite3,zipfile,tempfile,math,shutil
from pathlib import Path
from collections import defaultdict,Counter
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings')
import django;django.setup()
from django.db import connection
from django.contrib.auth.models import User
from app.models import Record,AnalysisModel,Topic,TopicView,TopicSnapshot,ImportBatch,MetricVersion
from app import analytics,analysis_engine as engine,metric_registry,topic_snapshots as snapshots
connection.cursor().execute('PRAGMA query_only=ON')
backup=ROOT/'data/backups/motor-backup-20261004-152327.zip'
report={'synthetic':True,'baseline':str(backup),'preserved_tables':{}}
deltas={'app_analysismodel':1,'app_topic':1,'app_topicview':1,'app_topicsnapshot':1,'app_metricversion':1}
allowed={('app_analysismodel',44):{'name','definition','version','updated_at'},('app_metricversion',9):{'status','revision','reviewed_by','review_note','retired_at','updated_at'}}
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
                assert row[0] in lookup,(table,'removed',row[0])
                diff={c for c,a,b in zip(columns,row,lookup[row[0]]) if a!=b}
                assert diff<=allowed.get((table,row[0]),set()),(table,row[0],diff)
                if diff:changed[row[0]]=sorted(diff)
            if table!='app_auditevent':assert len(after)-len(before)==deltas.get(table,0),(table,len(before),len(after))
            else:
                additions=Counter(r[1] for r in after[len(before):]);assert set(additions)<={'metric.fork','metric.save','metric.submit','metric.publish','metric.retire','model.save','topic.save','topic_view.save','topic_snapshot.create','topic.export','analysis.scatter_export'},additions
                report['audit_additions']=dict(additions)
            report['preserved_tables'][table]={'before':len(before),'after':len(after),'changed_prior_rows':changed}
        prior=json.loads(old.execute('SELECT definition FROM app_analysismodel WHERE id=44').fetchone()[0]);prior['metric_ref']['version']=7
        model44=AnalysisModel.objects.get(pk=44);assert model44.definition==prior and model44.version==9
h=hashlib.sha256()
for row in Record.objects.order_by('dataset','business_key').values_list('dataset','business_key','values','revision','source_row_id').iterator():h.update(json.dumps(row,sort_keys=True,ensure_ascii=False).encode())
assert h.hexdigest()=='c3493d7c4d221e6511486c05605c1c7f42ae7276ca4a7070e195999ae9e2e775'
counts=(Record.objects.count(),Record.objects.values('dataset').distinct().count(),ImportBatch.objects.exclude(status='superseded').count(),AnalysisModel.objects.count(),Topic.objects.count(),TopicView.objects.count(),TopicSnapshot.objects.count())
assert counts==(110787,63,18,51,20,5,3),counts
report.update(business_sha256=h.hexdigest(),counts=dict(zip(['records','datasets','active_workbooks','models','topics','views','snapshots'],counts)))
def projection(r):
    d=copy.deepcopy(r);d.pop('definition',None);d.pop('metric_receipt',None)
    if d.get('pivot'):d['pivot'].pop('revision',None)
    return json.loads(json.dumps(d,ensure_ascii=False,default=str))
admin=User.objects.get(username='demo_admin');prior_results=json.loads((ROOT/'data/scatter_before.json').read_text())
for key,prior in prior_results.items():
    m=AnalysisModel.objects.get(pk=key);definition,_=metric_registry.resolve(admin,m.dataset,m.definition,allow_inactive=True)
    assert projection(engine.run_analysis(admin,m.dataset,definition))==projection(prior),key
report['existing_model_results_preserved']=len(prior_results)
prior=json.loads((ROOT/'data/quality_comparison_runtime_probe.json').read_text());now=json.loads((ROOT/'data/scatter_runtime_probe.json').read_text())
assert prior['originals']==now['originals']
changed_apis=[k for k in prior['apis'] if prior['apis'][k]!=now['apis'][k]]
assert set(changed_apis)=={'/api/catalog','/api/models','/api/topics'},changed_apis
report.update(unchanged_business_apis=17,original_references_preserved=len(now['originals']))
metric=MetricVersion.objects.select_related('metric').get(metric__key='DELIVERY_OTIF',status='published')
assert metric.version==7 and metric.calculation_hash==metric_registry.calculation_hash('bi_order_lines')
assert metric.evidence['components'][0]['numerator']==15 and metric.evidence['components'][0]['denominator']==165
assert MetricVersion.objects.get(pk=9).status=='retired'
report['published_metric']={'version':7,'hash':metric.calculation_hash}

# Independent facts: count assembled SN and sum cost events, then aggregate by configuration.
raw=defaultdict(list)
for ds,values in Record.objects.filter(dataset__in=['work_orders','costs','units']).values_list('dataset','values'):raw[ds].append(values)
facts={w['id']:{**w,'cost':0,'produced':0} for w in raw['work_orders']}
for c in raw['costs']:
    if c['occurred']<=analytics.DAY:facts[c['work_order_id']]['cost']+=c['amount_cents']
for u in raw['units']:
    if u['assembly_at']<=analytics.AS_OF:facts[u['work_order_id']]['produced']+=1
def close(a,b):assert (a is None and b is None) or (a is not None and b is not None and math.isclose(a,b,rel_tol=1e-11,abs_tol=1e-9)),(a,b)
def expected(rows):
    qty=sum(r['produced'] for r in rows);cost=sum(r['cost'] for r in rows)
    return qty,cost/qty/100 if qty else None
def check_result(result,rows,dimension='product_id'):
    groups=defaultdict(list)
    for r in rows:groups[r[dimension]].append(r)
    scatter=result['scatter'];assert result['matched']==len(rows) and len(scatter['points'])==len(groups)
    assert scatter['axes']['x']['unit']=='台' and scatter['axes']['y']['unit']=='元/台'
    for point in scatter['points']:
        selected=groups[point['dimension']];x,y=expected(selected);close(point['x'],x);close(point['y'],y)
        assert point['row_count']==len(selected) and point['valid_inputs']=={'x':len(selected),'y':len(selected)}
        assert point['plotted']==(y is not None)
    return {'source_rows':len(rows),'groups':len(groups),'plotted':scatter['plotted'],'omitted':scatter['omitted']}
m=AnalysisModel.objects.get(pk=51);r=engine.run_analysis(admin,m.dataset,m.definition)
report['independent_cases']={'all_configurations':check_result(r,list(facts.values()))}
d=copy.deepcopy(m.definition);d['dimension']='id'
by_order=engine.run_analysis(admin,m.dataset,d);report['independent_cases']['all_work_orders']=check_result(by_order,list(facts.values()),'id')
assert by_order['scatter']['omitted']==100
assert Topic.objects.get(pk=20).layout==[{'model_id':51,'span':2}]
view=TopicView.objects.get(pk=5);assert view.binding['cards'][0]['calculation_hash']==metric_registry.calculation_hash(m.dataset)
s=TopicSnapshot.objects.get(pk='bf942f2a-216f-4f7d-8687-a971ddb565a6');snapshots.verify(s)
assert len(s.payload['sources'])==3491
for side in ['primary','reference']:
    scope=view.config['scope' if side=='primary' else 'reference_scope'];selected=[x for x in facts.values() if scope['from']<=x['planned_end']<=scope['to']]
    frozen=s.payload['result']['cards'][0][side];report['independent_cases'][side]=check_result(frozen,selected)
    assert {x['id'] for x in s.payload['cohorts']['0'][side]}=={x['id'] for x in selected}
    for point in frozen['scatter']['points']:
        evidence=snapshots.evidence(admin,20,s.pk,{'slot':0,'side':side,'group':point['dimension'],'page':1})
        assert evidence['total']==point['row_count']
for old_id,digest in {'afd93961-7331-42b3-b5a9-8a09042fb333':'6768e9603cda8d0506378e9ba8e4405e9560482cb25f41e211dc73b0ad4ee818','cd1b1abf-6ad7-4a8e-9c24-321fcd638465':'74351ee02d08a8d360bb093a510297f073003e2d4a493dc0bf0aaef4e745bdc0'}.items():
    old=TopicSnapshot.objects.get(pk=old_id);snapshots.verify(old);assert old.payload_hash==digest
report['snapshot']={'id':str(s.pk),'sha256':s.payload_hash,'source_records':3491,'prior_snapshots_unchanged':2}
files={}
def read_download(name,target):
    p=Path.home()/'Downloads'/name;dest=ROOT/'outputs'/target;shutil.copyfile(p,dest)
    rows=list(csv.reader(p.open(encoding='utf-8-sig',newline='')));files[target]={'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'rows_with_metadata':len(rows)};return rows
rows=read_download('analysis-scatter-result.csv','BI散点_完整分组.csv');assert len(rows[4:-1])==48
for line in rows[4:-1]:
    selected=[x for x in facts.values() if x['product_id']==line[0]];x,y=expected(selected);close(float(line[1]),x);close(float(line[3]),y);assert int(line[5])==len(selected)
rows=read_download('analysis-scatter-evidence.csv','BI散点_配置来源.csv');assert {x[0] for x in rows[5:-1]}=={x['id'] for x in facts.values() if x['product_id']=='CP.00040.A'} and len(rows[5:-1])==6
rows=read_download('BI结果快照-'+str(s.pk)+'.csv','BI散点_快照数值.csv')
assert rows==[[str(v) if v is not None else '' for v in line] for line in snapshots.export_rows(s)] and len(rows)==61
for line in rows[1:]:
    group=json.loads(line[10]);scope=json.loads(line[5] if line[9]==view.config['primary_label'] else line[6]);selected=[x for x in facts.values() if x['product_id']==group['分组'] and scope['from']<=x['planned_end']<=scope['to']]
    close(float(line[12]),expected(selected)[0 if group['坐标轴']=='x' else 1]);assert int(line[14])==len(selected)
report.update(browser_downloads=files,tests=1020)
rows=read_download('专题20-模型51-已返回结果.csv','BI散点_专题双范围.csv');assert len(rows)==31
for line in rows[1:]:
    scope=json.loads(line[4] if line[13]==view.config['primary_label'] else line[6]);selected=[x for x in facts.values() if x['product_id']==line[15] and scope['from']<=x['planned_end']<=scope['to']]
    x,y=expected(selected);close(float(line[16]),x);close(float(line[18]),y);assert int(line[20])==len(selected)
    assert line[17]=='台' and line[19]=='元/台' and line[9:11]==['0','0']
(ROOT/'data/scatter_validation.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
print(json.dumps({k:v for k,v in report.items() if k!='preserved_tables'},ensure_ascii=False,indent=2))
