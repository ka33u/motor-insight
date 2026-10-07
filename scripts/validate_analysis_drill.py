"""Read-only drill reconciliation, real browser CSV and preservation verification."""
import os,sys,json,csv,hashlib,sqlite3,zipfile,tempfile,math
from pathlib import Path
from collections import defaultdict,Counter
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings')
import django;django.setup()
from django.contrib.auth.models import User
from app.models import Record,AnalysisModel,Topic,TopicView,ImportBatch,MetricVersion,AuditEvent
from app import analytics,analysis_engine as engine,metric_registry,topic_workspace

baseline=ROOT/'data/backups/motor-backup-20261004-021610.zip'
deltas={'app_analysismodel':1,'app_topic':1,'app_topicview':1,'app_metricversion':1}
allowed_changes={('app_analysismodel',44):{'name','definition','version','updated_at'},('app_metricversion',7):{'status','revision','reviewed_by','review_note','retired_at','updated_at'}}
preserved={};originals=0
with zipfile.ZipFile(baseline) as z,tempfile.TemporaryDirectory() as tmp:
    for entry in json.loads(z.read('manifest.json'))['files']:
        if entry['path'].startswith(('data/imports/','data/device_files/')):
            assert hashlib.sha256((ROOT/entry['path']).read_bytes()).hexdigest()==entry['sha256'];originals+=1
    path=Path(tmp)/'before.sqlite3';path.write_bytes(z.read('data/platform.sqlite3'))
    with sqlite3.connect(path) as old,sqlite3.connect(ROOT/'data/platform.sqlite3') as now:
        tables=[r[0] for r in old.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'app_%'")];assert len(tables)==25
        for table in tables:
            columns=[r[1] for r in old.execute(f'PRAGMA table_info({table})')]
            before=list(old.execute(f'SELECT * FROM {table} ORDER BY id'));after=list(now.execute(f'SELECT * FROM {table} ORDER BY id'));lookup={r[0]:r for r in after};changed={}
            for row in before:
                assert row[0] in lookup,(table,'removed',row[0])
                diff={c for c,a,b in zip(columns,row,lookup[row[0]]) if a!=b}
                assert diff<=allowed_changes.get((table,row[0]),set()),(table,row[0],diff)
                if diff:changed[row[0]]=sorted(diff)
            if table!='app_auditevent':assert len(after)-len(before)==deltas.get(table,0),(table,len(before),len(after))
            preserved[table]={'before':len(before),'after':len(after),'changed_prior_rows':changed}
        old44=json.loads(old.execute('SELECT definition FROM app_analysismodel WHERE id=44').fetchone()[0])
        old44['metric_ref']['version']=5;old44.update(drilldown=[],derived=[],display_metric='m0')
        m44=AnalysisModel.objects.get(pk=44);assert m44.definition==old44 and m44.version==6 and m44.is_public
h=hashlib.sha256()
for row in Record.objects.order_by('dataset','business_key').values_list('dataset','business_key','values','revision','source_row_id').iterator():h.update(json.dumps(row,sort_keys=True,ensure_ascii=False).encode())
assert h.hexdigest()=='c3493d7c4d221e6511486c05605c1c7f42ae7276ca4a7070e195999ae9e2e775'
assert (Record.objects.count(),Record.objects.values('dataset').distinct().count(),ImportBatch.objects.exclude(status='superseded').count(),AnalysisModel.objects.count(),Topic.objects.count())==(110787,63,18,49,18)
admin=User.objects.get(username='demo_admin');model=AnalysisModel.objects.get(pk=49)
assert model.definition['drilldown']==[{'dimension':'product_id','grain':'value'},{'dimension':'id','grain':'value'}]
topic=Topic.objects.get(pk=18);assert topic.layout==[{'model_id':49,'span':1}]
view=TopicView.objects.get(pk=3);assert view.topic_id==18 and view.config['scope']=={'family':'YE3'} and view.config['reference_scope']=={'family':'YE4'}
assert view.binding['cards'][0]['calculation_hash']==metric_registry.calculation_hash(model.dataset)
# Old personal views and frozen results are deliberately retained, not rebound.
assert all(v.binding['cards'][0]['calculation_hash']!=metric_registry.calculation_hash('bi_work_orders') for v in TopicView.objects.filter(pk__in=[1,2]))

before=json.loads((ROOT/'data/analysis_drill_before.json').read_text());regression={}
for key,old in before.items():
    m=AnalysisModel.objects.get(pk=key);r=engine.run_analysis(admin,m.dataset,m.definition)
    keys=['rows','matched','scanned','groups','components','derived_notes','truncated','dimension_label','labels','display_metric']
    assert all(r.get(k)==old['result'].get(k) for k in keys),key
    regression[key]={'groups':r['groups'],'matched':r['matched'],'unchanged':True}
assert len(regression)==48

raw=defaultdict(list)
for ds,values in Record.objects.filter(dataset__in=['products','work_orders','costs','units']).values_list('dataset','values'):raw[ds].append(values)
products={r['id']:r for r in raw['products']};facts={w['id']:{'id':w['id'],'family':products[w['product_id']]['family'],'product_id':w['product_id'],'cost':0,'material':0,'produced':0} for w in raw['work_orders']}
for c in raw['costs']:
    if c['occurred']<=analytics.DAY:
        facts[c['work_order_id']]['cost']+=c['amount_cents']
        if c['category']=='材料':facts[c['work_order_id']]['material']+=c['amount_cents']
for u in raw['units']:
    if u['assembly_at']<=analytics.AS_OF:facts[u['work_order_id']]['produced']+=1
paths=[[]]+[[family] for family in sorted({r['family'] for r in facts.values()})]+[[products[p]['family'],p] for p in sorted({r['product_id'] for r in facts.values()})]
def close(a,b):assert (a is None and b is None) or (a is not None and b is not None and math.isclose(a,b,rel_tol=1e-10,abs_tol=1e-9)),(a,b)
for path in paths:
    rows=[r for r in facts.values() if (not path or r['family']==path[0]) and (len(path)<2 or r['product_id']==path[1])]
    field=['family','product_id','id'][len(path)];groups=defaultdict(list)
    for row in rows:groups[row[field]].append(row)
    result=engine.run_analysis(admin,model.dataset,model.definition,{},path)
    assert result['matched']==len(rows) and result['groups']==len(groups)
    assert {r['dimension'] for r in result['rows']}==set(groups)
    for x in result['rows']:
        rr=groups[x['dimension']];cost=sum(v['cost'] for v in rr);material=sum(v['material'] for v in rr);qty=sum(v['produced'] for v in rr)
        assert (x['row_count'],x['m0'],x['m1'],x['m2'])==(len(rr),cost,material,qty)
        for key,expected in [('d0',cost/qty/100 if qty else None),('d1',(cost-material)/qty/100 if qty else None),('d2',material/cost*100 if cost else None)]:close(x[key],expected)
exports={}
for kind,name in [('result','逐层分析_工单结果_浏览器导出.csv'),('evidence','逐层分析_工单来源_浏览器导出.csv')]:
    p=ROOT/'outputs'/name;data=list(csv.reader(p.open(encoding='utf-8-sig')));path=json.loads(data[0][4]);assert path==['YE3','CP.00016.A']
    assert json.loads(data[1][1])==model.definition and json.loads(data[1][3])=={}
    receipt=json.loads(data[-1][1]);assert receipt['calculation']==metric_registry.calculation_hash(model.dataset)
    assert receipt['data']==list(analytics.revision()) and receipt['definition']==topic_workspace.digest(model.definition)
    records=[dict(zip(data[4],row)) for row in data[5:-1]]
    expected={r['id']:r for r in facts.values() if r['family']==path[0] and r['product_id']==path[1]}
    assert {r['生产工单号'] for r in records}==set(expected) and len(records)==7
    for r in records:
        e=expected[r['生产工单号']];assert int(r['装配台数'])==e['produced']
        assert int(r['暂估总成本（分）' if kind=='result' else '暂估总成本分'])==e['cost']
        if kind=='result':close(float(r['暂估单位成本 (元/台)']) if r['暂估单位成本 (元/台)'] else None,e['cost']/e['produced']/100 if e['produced'] else None)
    exports[kind]={'rows':len(records),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()}
v5=MetricVersion.objects.get(metric__key='DELIVERY_OTIF',version=5);v4=MetricVersion.objects.get(metric__key='DELIVERY_OTIF',version=4)
assert v5.status=='published' and v5.contributors==['demo_admin'] and v5.submitted_by=='demo_admin' and v5.reviewed_by=='demo_operations'
assert v5.calculation_hash==metric_registry.calculation_hash('bi_order_lines')
assert v4.status=='retired' and v4.calculation_hash=='f6815a706b1f19c2e2be0af931c640d869b45b17bc0aa1f72d7fe2144356868f'
assert (v5.evidence['components'][0]['numerator'],v5.evidence['components'][0]['denominator'])==(15,165)
assert AuditEvent.objects.filter(action='analysis.explore_export').count()==3
report={'synthetic':True,'baseline':str(baseline.relative_to(ROOT)),'records':110787,'active_workbooks':18,'source_categories':63,'models':49,'topics':18,'business_sha256':h.hexdigest(),'preserved_original_files':originals,'preserved_tables':preserved,'prior_models_verified':regression,'independent_paths_checked':len(paths),'browser_exports':exports,'metric_v5_id':v5.pk,'metric_v5_hash':v5.calculation_hash,'model44_version':6,'new_model':49,'new_topic':18,'new_view':3,'old_personal_views_need_explicit_rebind':[1,2],'tests':723,'new_tests':40,'limits':'Same-grain grouping only. No cross-fact-grain switch or certified hierarchy. Synthetic unclosed costs; two compared product families are not efficiency-controlled samples. Download tokens expire after 5 minutes and stay bound to the requesting account.'}
if len(sys.argv)>1:
    backup=Path(sys.argv[1])
    with zipfile.ZipFile(backup) as z,tempfile.TemporaryDirectory() as tmp:
        manifest=json.loads(z.read('manifest.json'))
        for e in manifest['files']:
            b=z.read(e['path']);assert len(b)==e['size'] and hashlib.sha256(b).hexdigest()==e['sha256']
        p=Path(tmp)/'restore.sqlite3';p.write_bytes(z.read('data/platform.sqlite3'))
        with sqlite3.connect(p) as recovered,sqlite3.connect(ROOT/'data/platform.sqlite3') as now:
            assert recovered.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
            for table in tables:assert list(recovered.execute(f'SELECT * FROM {table} ORDER BY id'))==list(now.execute(f'SELECT * FROM {table} ORDER BY id'))
        report['backup']={'path':str(backup),'files':len(manifest['files']),'app_tables':len(tables),'sqlite_integrity':'ok','all_app_tables_match':True}
(ROOT/'data/analysis_drill_validation.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
print(json.dumps({k:v for k,v in report.items() if k not in ['preserved_tables','prior_models_verified']},ensure_ascii=False,indent=2))
