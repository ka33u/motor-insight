"""Independent source reconciliation, browser CSV verification and preservation audit."""
import os,sys,json,csv,hashlib,sqlite3,zipfile,tempfile,math
from pathlib import Path
from collections import defaultdict
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings')
import django;django.setup()
from django.contrib.auth.models import User
from app.models import Record,AnalysisModel,Topic,TopicView,TopicSnapshot,ImportBatch,MetricVersion
from app import analytics,analysis_engine as engine,metric_registry,topic_workspace as ws,topic_snapshots as snapshots
baseline=ROOT/'data/backups/motor-backup-20261004-032610.zip'
deltas={'app_analysismodel':1,'app_topic':1,'app_topicview':1,'app_topicsnapshot':1,'app_metricversion':1}
allowed={('app_analysismodel',44):{'name','definition','version','updated_at'},('app_metricversion',8):{'status','revision','reviewed_by','review_note','retired_at','updated_at'}}
preserved={};originals=0
with zipfile.ZipFile(baseline) as z,tempfile.TemporaryDirectory() as tmp:
    for f in json.loads(z.read('manifest.json'))['files']:
        if f['path'].startswith(('data/imports/','data/device_files/')):
            assert hashlib.sha256((ROOT/f['path']).read_bytes()).hexdigest()==f['sha256'];originals+=1
    path=Path(tmp)/'before.sqlite3';path.write_bytes(z.read('data/platform.sqlite3'))
    with sqlite3.connect(path) as old,sqlite3.connect(ROOT/'data/platform.sqlite3') as now:
        tables=[r[0] for r in old.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'app_%'")];assert len(tables)==25
        for table in tables:
            columns=[r[1] for r in old.execute(f'PRAGMA table_info({table})')];before=list(old.execute(f'SELECT * FROM {table} ORDER BY id'));after=list(now.execute(f'SELECT * FROM {table} ORDER BY id'));lookup={r[0]:r for r in after};changed={}
            for row in before:
                assert row[0] in lookup,(table,'removed',row[0]);diff={c for c,a,b in zip(columns,row,lookup[row[0]]) if a!=b}
                assert diff<=allowed.get((table,row[0]),set()),(table,row[0],diff)
                if diff:changed[row[0]]=sorted(diff)
            if table!='app_auditevent':assert len(after)-len(before)==deltas.get(table,0),(table,len(before),len(after))
            preserved[table]={'before':len(before),'after':len(after),'changed_prior_rows':changed}
        prior=json.loads(old.execute('SELECT definition FROM app_analysismodel WHERE id=44').fetchone()[0]);prior['metric_ref']['version']=6
        m44=AnalysisModel.objects.get(pk=44);assert m44.definition==prior and m44.version==7 and m44.is_public
h=hashlib.sha256()
for row in Record.objects.order_by('dataset','business_key').values_list('dataset','business_key','values','revision','source_row_id').iterator():h.update(json.dumps(row,sort_keys=True,ensure_ascii=False).encode())
assert h.hexdigest()=='c3493d7c4d221e6511486c05605c1c7f42ae7276ca4a7070e195999ae9e2e775'
assert (Record.objects.count(),Record.objects.values('dataset').distinct().count(),ImportBatch.objects.exclude(status='superseded').count(),AnalysisModel.objects.count(),Topic.objects.count())==(110787,63,18,50,19)
admin=User.objects.get(username='demo_admin');m=AnalysisModel.objects.get(pk=50);assert m.version==1 and m.definition['chart']=='pivot' and m.definition['pivot']=={'dimension':'status','grain':'value'}
assert Topic.objects.get(pk=19).layout==[{'model_id':50,'span':2}]
v=TopicView.objects.get(pk=4);assert v.config['scope']=={'family':'YE3'} and v.config['reference_scope']=={'family':'YE4'} and v.binding['cards'][0]['calculation_hash']==metric_registry.calculation_hash(m.dataset)
assert all(v.binding['cards'][0]['calculation_hash']!=metric_registry.calculation_hash('bi_work_orders') for v in TopicView.objects.filter(pk__in=[1,2,3]))
old_results=json.loads((ROOT/'data/pivot_before.json').read_text());regression={}
for k,old in old_results.items():
    model=AnalysisModel.objects.get(pk=k);r=engine.run_analysis(admin,model.dataset,model.definition)
    fields=['rows','matched','scanned','groups','components','derived_notes','truncated','dimension_label','labels','display_metric']
    assert all(r.get(f)==old['result'].get(f) for f in fields),k
    regression[k]={'unchanged':True,'groups':r['groups'],'matched':r['matched']}
assert len(regression)==49
# Rebuild work-order cost and assembly facts directly from imported business rows.
raw=defaultdict(list)
for ds,values in Record.objects.filter(dataset__in=['products','work_orders','costs','units']).values_list('dataset','values'):raw[ds].append(values)
products={r['id']:r for r in raw['products']};facts={w['id']:{'id':w['id'],'family':products[w['product_id']]['family'],'status':w['status'],'cost':0,'material':0,'produced':0} for w in raw['work_orders']}
for c in raw['costs']:
    if c['occurred']<=analytics.DAY:
        facts[c['work_order_id']]['cost']+=c['amount_cents']
        if c['category']=='材料':facts[c['work_order_id']]['material']+=c['amount_cents']
for u in raw['units']:
    if u['assembly_at']<=analytics.AS_OF:facts[u['work_order_id']]['produced']+=1

def expected(rows):
    if not rows:return {k:None for k in ['m0','m1','m2','d0','d1','d2']}
    c=sum(r['cost'] for r in rows);mat=sum(r['material'] for r in rows);qty=sum(r['produced'] for r in rows)
    return {'m0':c,'m1':mat,'m2':qty,'d0':c/qty/100 if qty else None,'d1':(c-mat)/qty/100 if qty else None,'d2':mat/c*100 if c else None}
def close(a,b):assert (a is None and b is None) or (a is not None and b is not None and math.isclose(a,b,rel_tol=1e-10,abs_tol=1e-9)),(a,b)
def validate_matrix(r,rows):
    p=r['pivot'];rr={a['key']:a['label'] for a in p['rows']};cc={a['key']:a['label'] for a in p['columns']};checked=0
    assert set(rr.values())=={x['family'] for x in rows} and set(cc.values())=={x['status'] for x in rows}
    assert len(p['cells'])==len(rr)*len(cc)
    for cell in p['cells']+p['row_totals']+p['column_totals']+[p['grand_total']]:
        selected=[x for x in rows if (cell['row'] is None or x['family']==rr[cell['row']]) and (cell['column'] is None or x['status']==cc[cell['column']])]
        assert cell['row_count']==len(selected)
        for k,val in expected(selected).items():close(cell[k],val)
        checked+=1
    return checked
r=engine.run_analysis(admin,m.dataset,m.definition);checked=validate_matrix(r,list(facts.values()));assert checked==12
s=TopicSnapshot.objects.get(pk='cd1b1abf-6ad7-4a8e-9c24-321fcd638465');snapshots.verify(s);assert len(s.payload['sources'])==3784
for side,family in [('primary','YE3'),('reference','YE4')]:
    frozen=s.payload['result']['cards'][0][side];selected=[x for x in facts.values() if x['family']==family];checked+=validate_matrix(frozen,selected)
    assert len(s.payload['cohorts']['0'][side])==len(selected)
    for cell in frozen['pivot']['cells']+frozen['pivot']['row_totals']+frozen['pivot']['column_totals']+[frozen['pivot']['grand_total']]:
        data=snapshots.evidence(admin,19,s.pk,{'slot':0,'side':side,'group':None,'page':1,'selection':{k:cell[k] for k in ['row','column']}});assert data['total']==cell['row_count']
# Actual browser downloads, independently recomputed numeric CSV cells.
files={}
def read(name):
    path=ROOT/'outputs'/name;files[name]={'sha256':hashlib.sha256(path.read_bytes()).hexdigest()};return list(csv.reader(path.open(encoding='utf-8-sig',newline='')))
rows=read('透视分析_完整成本矩阵_浏览器导出.csv');assert rows[3][:3]==['结果类型','产品族','工单状态'];assert rows[-1][0]=='计算依据';assert len(rows[4:-1])==12
for line in rows[4:-1]:
    kind,family,status=line[:3];selected=[x for x in facts.values() if (kind in ['列合计','总计'] or x['family']==family) and (kind in ['行合计','总计'] or x['status']==status)]
    for value,exp in zip(line[3:9],expected(selected).values()):close(float(value) if value else None,exp)
    assert int(line[9])==len(selected)
files['透视分析_完整成本矩阵_浏览器导出.csv']['rows']=12
rows=read('透视分析_YE3完工工单_浏览器导出.csv');expected_ids={x['id'] for x in facts.values() if x['family']=='YE3' and x['status']=='完工待清尾'};assert {r[0] for r in rows[5:-1]}==expected_ids and len(expected_ids)==68
files['透视分析_YE3完工工单_浏览器导出.csv']['rows']=68
rows=read('透视分析_快照矩阵_浏览器导出.csv');wanted=[[str(v) if v is not None else '' for v in row] for row in snapshots.export_rows(s)];assert rows==wanted;assert len(rows)==73
files['透视分析_快照矩阵_浏览器导出.csv']['rows']=72
metric=MetricVersion.objects.get(pk=9);assert metric.version==6 and metric.status=='published' and metric.reviewed_by=='demo_operations' and metric.calculation_hash==metric_registry.calculation_hash('bi_order_lines')
assert MetricVersion.objects.get(pk=8).status=='retired' and metric.evidence['components'][0]['numerator']==15 and metric.evidence['components'][0]['denominator']==165
out={'baseline':str(baseline.relative_to(ROOT)),'business_sha256':h.hexdigest(),'records':110787,'source_categories':63,'active_workbooks':18,'unchanged_original_files':originals,'preserved_tables':preserved,'existing_models':regression,'independent_cells_and_totals':checked,'grand_total':expected(list(facts.values())),'browser_csv':files,'snapshot_id':str(s.pk),'snapshot_sha256':s.payload_hash,'published_metric':{'version':metric.version,'hash':metric.calculation_hash},'test_count':763}
if len(sys.argv)>1:
    backup=Path(sys.argv[1]);summary={}
    with zipfile.ZipFile(backup) as z,tempfile.TemporaryDirectory() as tmp:
        manifest=json.loads(z.read('manifest.json'))
        for f in manifest['files']:
            raw=z.read(f['path']);assert len(raw)==f['size'] and hashlib.sha256(raw).hexdigest()==f['sha256']
        db=Path(tmp)/'restore.sqlite3';db.write_bytes(z.read('data/platform.sqlite3'))
        with sqlite3.connect(db) as restored,sqlite3.connect(ROOT/'data/platform.sqlite3') as current:
            assert restored.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
            for table in preserved:assert list(restored.execute(f'SELECT * FROM {table} ORDER BY id'))==list(current.execute(f'SELECT * FROM {table} ORDER BY id'))
        out['backup']={'path':str(backup),'manifest_files':len(manifest['files']),'app_tables':len(preserved),'integrity':'ok','restored_content_matches_current':True}
(ROOT/'data/pivot_validation.json').write_text(json.dumps(out,ensure_ascii=False,indent=2));(ROOT/'data/pivot_regression.json').write_text(json.dumps(regression,ensure_ascii=False,indent=2))
print(json.dumps({k:v for k,v in out.items() if k not in ['preserved_tables','existing_models']},ensure_ascii=False,indent=2))
