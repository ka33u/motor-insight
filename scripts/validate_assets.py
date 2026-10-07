"""Independent audit of the synthetic equipment-workbench acceptance snapshot."""
import os,sys,json,hashlib,sqlite3,zipfile,tempfile,csv,io,copy,math
from collections import Counter,defaultdict
from datetime import datetime,date,timedelta
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings')
import django;django.setup()
from app import assets,analytics,metric_registry
from app.models import Record,MetricVersion,IssueDisposition,AuditEvent
BASE=ROOT/'data/backups/motor-backup-20261003-165855.zip'
with zipfile.ZipFile(BASE) as z,tempfile.TemporaryDirectory() as tmp:
    manifest=json.loads(z.read('manifest.json'))
    for e in manifest['files']:
        if e['path'].startswith(('data/imports/','data/device_files/')):assert hashlib.sha256((ROOT/e['path']).read_bytes()).hexdigest()==e['sha256']
    p=Path(tmp)/'before.sqlite3';p.write_bytes(z.read('data/platform.sqlite3'))
    with sqlite3.connect(p) as old,sqlite3.connect(ROOT/'data/platform.sqlite3') as now:
        tables=[r[0] for r in old.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'app_%'")]
        for table in tables:
            before=list(old.execute(f'SELECT * FROM {table} ORDER BY id'))
            if table in ['app_auditevent','app_issuedisposition']:
                after=list(now.execute(f'SELECT * FROM {table} WHERE id<=? ORDER BY id',(before[-1][0] if before else 0,)))
            else:after=list(now.execute(f'SELECT * FROM {table} ORDER BY id'))
            assert before==after,table
    old_design=json.loads(z.read('data/bi_design.json'));design=json.loads((ROOT/'data/bi_design.json').read_text());cleaned=copy.deepcopy(design)
    for dom in cleaned['domains']:
        for item in dom['items']:
            if item['id'] in ['O-01','O-02','P-02','P-04']:
                prior=next(i for d in old_design['domains'] for i in d['items'] if i['id']==item['id']);item.update({k:prior[k] for k in ['gap','implementation']})
    for pg in cleaned['page_blueprints']:
        if pg['id']=='P10':pg.clear();pg.update(next(x for x in old_design['page_blueprints'] if x['id']=='P10'))
    cleaned['framework']['surfaces']=[s for s in cleaned['framework']['surfaces'] if s['href']!='#assets']
    assert cleaned==old_design
h=hashlib.sha256()
for r in Record.objects.order_by('dataset','business_key').values_list('dataset','business_key','values','revision','source_row_id').iterator():h.update(json.dumps(r,ensure_ascii=False,sort_keys=True).encode())
assert Record.objects.count()==106838 and h.hexdigest()=='576ad9668e112e407eb81b9d3f58fa150f5753f7ede1fe43b2919ed4a1ec2a72'
v=MetricVersion.objects.select_related('metric').get(metric__key='DELIVERY_OTIF',version=3)
assert v.status=='published' and v.calculation_hash==metric_registry.calculation_hash(v.metric.dataset)
raw={ds:list(Record.objects.filter(dataset=ds).values_list('values',flat=True)) for ds in assets.TABLES}
timestamp=datetime.fromisoformat;start=timestamp('2026-09-21T00:00:00');end=timestamp(analytics.AS_OF)
resource={r['id']:r for r in raw['production_resources']}
# Sweep all endpoints independently. An interval contributes only when the
# midpoint is covered; simultaneous resource stations count once per machine.
expected=[];reasons=defaultdict(float);days=defaultdict(float)
for e in raw['equipment']:
    stops=[x for x in raw['downtime'] if x['equipment_id']==e['id']]
    schedules=[x for x in raw['resource_calendars'] if resource[x['resource_id']]['equipment_id']==e['id']]
    all_edges={start,end}
    for x in stops+schedules:
        a,b=timestamp(x['started']),timestamp(x['finished']);assert a<b
        if a<end and b>start:all_edges.update([max(a,start),min(b,end)])
    point=start
    while point<end:all_edges.add(point);point+=timedelta(days=1)
    stop=calendar=inside=0
    ordered=sorted(all_edges)
    for a,b in zip(ordered,ordered[1:]):
        mid=a+(b-a)/2;hours=(b-a).total_seconds()/3600
        ss=[x for x in stops if timestamp(x['started'])<=mid<timestamp(x['finished'])]
        cc=[x for x in schedules if timestamp(x['started'])<=mid<timestamp(x['finished'])]
        if cc:calendar+=hours
        if ss:
            stop+=hours;days[a.date().isoformat()]+=hours
            labels={x['reason'] for x in ss};reasons[next(iter(labels)) if len(labels)==1 else '多原因重叠待核对']+=hours
        if ss and cc:inside+=hours
    expected.append({'id':e['id'],'stop_hours':stop,'scheduled_hours':calendar or None,'scheduled_stop_hours':inside if calendar else None})
d=assets.current(assets.filters({}));totals=assets.summary(d.rows,'equipment');close=lambda a,b:math.isclose(a,b,abs_tol=1e-8)
for e in expected:
    actual=d.index[e['id']]
    for key in ['stop_hours','scheduled_hours','scheduled_stop_hours']:
        assert e[key]==actual[key] if e[key] is None else close(e[key],actual[key]),(e,key)
assert close(sum(x['stop_hours'] for x in expected),108)
assert close(sum(x['scheduled_hours'] or 0 for x in expected),2880)
assert close(sum(x['scheduled_stop_hours'] or 0 for x in expected),107+1/3)
for r in assets.breakdown(d,d.rows)['reasons']:assert close(r['hours'],reasons[r['label']])
for r in assets.breakdown(d,d.rows)['daily']:assert close(r['hours'],days[r['day']])
repairs=[x for x in raw['maintenance'] if x['reported']<=analytics.AS_OF]
complete=[x for x in repairs if x['finished'] and x['finished']<=analytics.AS_OF];pending=[x for x in repairs if x not in complete]
assert len(complete)==24 and len(pending)==3
assert all((end-timestamp(x['reported'])).total_seconds()/3600==33 for x in pending)
mean=sum((timestamp(x['finished'])-timestamp(x['reported'])).total_seconds()/3600 for x in complete)/len(complete)
assert close(mean,94/24)
expired=[x for x in raw['tools'] if x['next_due']<analytics.DAY];usage=[x for x in raw['tools'] if x['maintenance_limit']>0 and x['uses']>=x['maintenance_limit']]
assert len(expired)==3 and len(usage)==6
source_files={}
for r in Record.objects.filter(dataset__in=assets.TABLES).select_related('source_row__batch'):
    assert r.values==r.source_row.normalized and r.record_hash==r.source_row.record_hash
    b=r.source_row.batch;source_files[str(b.pk)]=dict(filename=b.filename,path=b.file_path,sha256=b.file_hash)
for f in source_files.values():assert hashlib.sha256(Path(f['path']).read_bytes()).hexdigest()==f['sha256']
exports=[]
for name,records in [('维修未完成_浏览器导出.csv',pending),('工装到期_浏览器导出.csv',expired)]:
    rows=list(csv.reader(io.StringIO((ROOT/'outputs'/name).read_text(encoding='utf-8-sig'))));assert len(rows)-3==len(records)
    exported={r[0]:dict(zip(rows[2],r)) for r in rows[3:]};assert set(exported)=={x['id'] for x in records}
    for x in records:
        y=exported[x['id']]
        if 'finished' in x:
            assert y['截止状态']=='未完成' and y['截止已完成时间']=='' and float(y['未完成已等待小时'])==33
            assert y['设备编码']==x['equipment_id'] and close(float(y['报修至开始小时']),(timestamp(x['started'])-timestamp(x['reported'])).total_seconds()/3600)
        else:
            assert y['台账到期日']==x['next_due'] and int(y['累计使用数'])==x['uses'] and int(y['维护阈值'])==x['maintenance_limit'] and int(y['距离到期天数'])==-1
    exports.append(dict(filename=name,rows=len(records),sha256=hashlib.sha256((ROOT/'outputs'/name).read_bytes()).hexdigest()))
notes=list(IssueDisposition.objects.filter(key__startswith='asset:').values('key','version','status','owner','note','due_date'))
assert {(x['key'],x['version'],x['status']) for x in notes}=={('asset:maintenance:WX2609-0007',1,'待备件协调'),('asset:tool:GJ-0009',1,'待校准核对')}
assert AuditEvent.objects.filter(action='asset.followup').count()==2
report=dict(synthetic=True,baseline=str(BASE.relative_to(ROOT)),business_rows=106838,business_sha256=h.hexdigest(),equipment_summary=totals,repairs=dict(total=len(repairs),completed=len(complete),open=len(pending),mean_completed_elapsed_hours=mean,max_open_hours=33),tools=dict(total=len(raw['tools']),expired=len(expired),usage_threshold=len(usage)),source_records=sum(len(x) for x in raw.values()),source_workbooks=len(source_files),browser_exports=exports,coordination=notes,tests=343,new_tests=27,catalog_counts=dict(Counter(x['implementation'] for dom in design['domains'] for x in dom['items'])),limits='Synthetic imported facts only. No real equipment collection, OEE/MTBF/MTTR, calibration certificates/use history, maintenance schedule or restart approval. Preserved previous database state except two coordination records and appended audits.')
if len(sys.argv)>1:
    zp=Path(sys.argv[1])
    with zipfile.ZipFile(zp) as z,tempfile.TemporaryDirectory() as tmp:
        mm=json.loads(z.read('manifest.json'))
        for e in mm['files']:
            content=z.read(e['path']);assert len(content)==e['size'] and hashlib.sha256(content).hexdigest()==e['sha256']
        p=Path(tmp)/'restored.sqlite3';p.write_bytes(z.read('data/platform.sqlite3'))
        with sqlite3.connect(p) as restored,sqlite3.connect(ROOT/'data/platform.sqlite3') as now:
            assert restored.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
            for table in tables:assert list(restored.execute(f'SELECT * FROM {table} ORDER BY id'))==list(now.execute(f'SELECT * FROM {table} ORDER BY id')),table
        report['backup']={'path':str(zp),'manifest_files':len(mm['files']),'sqlite_integrity':'ok','all_app_tables_match':True}
(ROOT/'data/assets_validation.json').write_text(json.dumps(report,ensure_ascii=False,indent=2,default=str))
print(json.dumps({k:v for k,v in report.items() if k not in ['coordination','browser_exports']},ensure_ascii=False))
