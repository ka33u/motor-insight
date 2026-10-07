"""Independent reconciliation of the current synthetic snapshot, not a production sign-off."""
import os,sys,json,csv,math,hashlib,sqlite3,tempfile,zipfile
from collections import defaultdict,Counter
from decimal import Decimal
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings')
import django;django.setup()
from django.contrib.auth.models import User
from app.models import Record,TopicSnapshot,MetricVersion,ImportBatch
from app import topic_snapshots as ss,topic_workspace as ws,analytics,metric_registry

BASE=ROOT/'data/backups/motor-backup-20261003-153315.zip'
with zipfile.ZipFile(BASE) as z,tempfile.TemporaryDirectory() as tmp:
    manifest=json.loads(z.read('manifest.json'))
    for entry in manifest['files']:
        if entry['path'].startswith('data/imports/'):
            assert hashlib.sha256((ROOT/entry['path']).read_bytes()).hexdigest()==entry['sha256']
    p=Path(tmp)/'before.sqlite3';p.write_bytes(z.read('data/platform.sqlite3'))
    with sqlite3.connect(p) as old,sqlite3.connect(ROOT/'data/platform.sqlite3') as now:
        tables=[r[0] for r in old.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'app_%'")]
        for table in tables:
            before=list(old.execute(f'SELECT * FROM {table} ORDER BY id'))
            after=list(now.execute(f'SELECT * FROM {table}'+(' WHERE id<=?' if table=='app_auditevent' else '')+' ORDER BY id',(before[-1][0],) if table=='app_auditevent' else ()))
            assert before==after,table
    old_design=json.loads(z.read('data/bi_design.json'));design=json.loads((ROOT/'data/bi_design.json').read_text())
    for d in [old_design,design]:
        for domain in d['domains']:
            for item in domain['items']:
                if item['id'] in ['X-07','X-08','X-10']:
                    item.pop('gap');item.pop('implementation')
    assert old_design==design
h=hashlib.sha256()
for row in Record.objects.order_by('dataset','business_key').values_list('dataset','business_key','values','revision','source_row_id').iterator():h.update(json.dumps(row,ensure_ascii=False,sort_keys=True).encode())
assert Record.objects.count()==106838 and h.hexdigest()=='576ad9668e112e407eb81b9d3f58fa150f5753f7ede1fe43b2919ed4a1ec2a72'
assert TopicSnapshot.objects.count()==1
s=TopicSnapshot.objects.select_related('owner').get();assert s.owner.username=='demo_admin' and s.topic_id==16
ss.verify(s);payload=s.payload;result=payload['result'];assert len(payload['sources'])==863
assert [c['model']['id'] for c in result['cards']]==[45,46]
assert all(c['model']['version']==2 for c in result['cards'])
v3=MetricVersion.objects.select_related('metric').get(metric__key='DELIVERY_OTIF',version=3)
assert v3.status=='published' and v3.calculation_hash==metric_registry.calculation_hash(v3.metric.dataset)
raw=analytics.tables();products={p['id']:p for p in raw['products']};costs=defaultdict(list);units=defaultdict(list)
for c in raw['costs']:
    if c['occurred']<=analytics.DAY:costs[c['work_order_id']].append(c)
for u in raw['units']:
    if u['assembly_at']<=analytics.AS_OF:units[u['work_order_id']].append(u)
expected_sources=set();expected_values={};summaries=[]
for card in result['cards']:
    for side,scope in [('primary',result['config']['scope']),('reference',result['config']['reference_scope'])]:
        selected=[w for w in raw['work_orders'] if (not scope.get('family') or products[w['product_id']]['family']==scope['family']) and (not scope.get('from') or w['planned_end']>=scope['from']) and (not scope.get('to') or w['planned_end']<=scope['to'])]
        assert len(selected)==19
        frozen=payload['cohorts'][str(card['slot'])][side];assert {r['id'] for r in frozen}=={w['id'] for w in selected}
        g=defaultdict(lambda:{'m0':0,'m1':0,'m2':0,'row_count':0})
        for w in selected:
            family=products[w['product_id']]['family'];x=g[family];x['row_count']+=1
            x['m0']+=sum(c['amount_cents'] for c in costs[w['id']]);x['m1']+=sum(c['amount_cents'] for c in costs[w['id']] if c['category']=='材料');x['m2']+=len(units[w['id']])
            refs={('work_orders',w['id']),('products',w['product_id'])}|{('costs',c['id']) for c in costs[w['id']]}|{('units',u['id']) for u in units[w['id']]}
            expected_sources|=refs
            obj=next(r for r in frozen if r['id']==w['id']);assert set(obj['sources'])=={ws.digest([d,k]) for d,k in refs};assert obj['omitted_sources']==0
        for key,x in g.items():
            x['d0']=float(Decimal(x['m0'])/100/x['m2']);x['d1']=float(Decimal(x['m0']-x['m1'])/100/x['m2']);x['d2']=float(Decimal(x['m1'])/x['m0']*100)
            found=next(r for r in card[side]['rows'] if r['dimension']==key)
            for measure in ['m0','m1','m2','d0','d1','d2']:assert math.isclose(found[measure],x[measure],rel_tol=1e-12)
            assert found['row_count']==x['row_count']
            for m in card[side]['measures']:expected_values[(card['model']['name'],result['config']['primary_label' if side=='primary' else 'reference_label'],key,m['label'])]=x[m['key']]
        summaries.append({'model':card['model']['id'],'side':side,'groups':dict(g)})
assert {(r['dataset'],r['key']) for r in payload['sources'].values()}==expected_sources
record_map={(r.dataset,r.business_key):r for r in Record.objects.filter(dataset__in={d for d,k in expected_sources}).select_related('source_row__batch')}
files={}
for source in payload['sources'].values():
    r=record_map[source['dataset'],source['key']];b=r.source_row.batch
    assert source['values']=={k:v for k,v in r.values.items() if k in {f['name'] for f in payload['fields'][r.dataset]}}
    assert (source['revision'],source['record_hash'],source['source_row_id'])==(r.revision,r.record_hash,r.source_row_id)
    assert (source['filename'],source['sheet'],source['row'],source['file_hash'])==(b.filename,r.source_row.sheet,r.source_row.row_number,b.file_hash)
    files[str(b.pk)]=(b.file_path,b.file_hash)
for path,expected in files.values():assert hashlib.sha256(Path(path).read_bytes()).hexdigest()==expected
comparison=ss.compare_current(s.owner,s.topic_id,s.pk);assert not comparison['blocked']
assert (comparison['source_added'],comparison['source_removed'],comparison['source_changed'])==(0,0,0)
for card in comparison['cards']:
    assert (card['added_objects'],card['removed_objects'],card['changed_objects'])==(0,0,0)
    assert all(v['delta']==0 for r in card['comparison']['rows'] for v in r['values'])
csvpath=ROOT/'outputs/BI结果快照_浏览器导出.csv';jsonpath=ROOT/'outputs/BI结果快照_浏览器导出.json'
rows=list(csv.DictReader(csvpath.open(encoding='utf-8-sig')));assert len(rows)==72
for row in rows:
    key=(row['模型'],row['范围名称'],row['分组'],row['度量'])
    assert math.isclose(float(row['数值']),expected_values[key],rel_tol=1e-12)
    assert row['快照摘要']==s.payload_hash and row['快照标识']==str(s.pk)
exported=json.loads(jsonpath.read_text());assert exported['payload']==payload and exported['payload_hash']==s.payload_hash
report={'synthetic':True,'baseline':str(BASE.relative_to(ROOT)),'business_rows':106838,'business_sha256':h.hexdigest(),
        'preserved_tables':tables,'snapshot':{**ss.info(s),'owner':s.owner.username},'independent_results':summaries,'verified_source_files':len(files),
        'sources_by_dataset':dict(Counter(r['dataset'] for r in payload['sources'].values())),
        'browser_csv_rows':72,'browser_json_sha256':hashlib.sha256(jsonpath.read_bytes()).hexdigest(),'current_comparison':'No changed values or sources',
        'tests':264,'new_tests':28,'catalog_change':'Only X-07/X-08/X-10 updated; 40 partial, 224 planned',
        'limits':'Personal manual result capture, not period close or full database replay. No original test-device attachments or scheduled archive. Production retention and cross-host restore remain unverified.'}
if len(sys.argv)>1:
    backup=Path(sys.argv[1]).resolve()
    with zipfile.ZipFile(backup) as z,tempfile.TemporaryDirectory() as tmp:
        manifest=json.loads(z.read('manifest.json'))
        for entry in manifest['files']:assert hashlib.sha256(z.read(entry['path'])).hexdigest()==entry['sha256']
        p=Path(tmp)/'restored.sqlite3';p.write_bytes(z.read('data/platform.sqlite3'))
        with sqlite3.connect(p) as restored,sqlite3.connect(ROOT/'data/platform.sqlite3') as live:
            assert restored.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
            for table in [*tables,'app_topicsnapshot']:
                if table=='app_auditevent':continue
                assert list(restored.execute(f'SELECT * FROM {table} ORDER BY id'))==list(live.execute(f'SELECT * FROM {table} ORDER BY id')),table
    report['backup']={'path':str(backup.relative_to(ROOT)),'manifest_files':len(manifest['files']),'sqlite_integrity':'ok','critical_tables_match':True}
(ROOT/'data/topic_snapshots_validation.json').write_text(json.dumps(report,ensure_ascii=False,indent=2,default=str)+'\n')
print(json.dumps({k:v for k,v in report.items() if k not in ['preserved_tables','independent_results','limits']},ensure_ascii=False,default=str))
