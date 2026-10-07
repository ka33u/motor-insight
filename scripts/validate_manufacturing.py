"""Read-only reconciliation of the manufacturing increment and original XLSX.

The independent counts below use imported facts and calendar dates, not the
workbench's summary implementation. No business facts are written by this file.
"""
import os,sys,json,csv,hashlib,sqlite3,zipfile,tempfile,math
from pathlib import Path
from collections import Counter,defaultdict
from datetime import date,datetime
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT));os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings')
import django
django.setup()
from openpyxl import load_workbook
from django.contrib.auth.models import User
from app.models import Record,ImportBatch,IssueDisposition,AuditEvent,DataQualityScan,DataMonitorPolicy,MetricVersion
from app.schema import SCHEMAS
from app.ingestion import convert
from app import manufacturing as m,data_health,metric_registry

def sha(v):return hashlib.sha256(json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()

baseline=ROOT/'data/backups/motor-backup-20261003-222707.zip'
preserved={};source_files=0
expected_delta={'app_issuedisposition':1}
with zipfile.ZipFile(baseline) as z,tempfile.TemporaryDirectory() as temp:
    manifest=json.loads(z.read('manifest.json'))
    for entry in manifest['files']:
        if entry['path'].startswith(('data/imports/','data/device_files/')):
            assert hashlib.sha256((ROOT/entry['path']).read_bytes()).hexdigest()==entry['sha256']
            source_files+=1
    p=Path(temp)/'before.sqlite3';p.write_bytes(z.read('data/platform.sqlite3'))
    with sqlite3.connect(p) as old,sqlite3.connect(ROOT/'data/platform.sqlite3') as now:
        tables=[r[0] for r in now.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'app_%'")]
        assert set(tables)=={r[0] for r in old.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'app_%'")}
        assert len(tables)==25
        for table in tables:
            before=list(old.execute(f'SELECT * FROM {table} ORDER BY id'))
            current=list(now.execute(f'SELECT * FROM {table} ORDER BY id'));by_id={r[0]:r for r in current}
            assert all(by_id.get(r[0])==r for r in before),(table,'prior row changed')
            if table!='app_auditevent':assert len(current)-len(before)==expected_delta.get(table,0),(table,'unexpected row count')
            preserved[table]={'before':len(before),'after':len(current),'prior_rows_unchanged':True}

scans=list(DataQualityScan.objects.order_by('created_at'));assert len(scans)==4
latest=scans[-1];snap=latest.snapshot;cutoff=datetime.fromisoformat(snap['as_of']);as_of=cutoff.date()
assert sha(snap)==latest.snapshot_hash and latest.engine_hash==data_health.engine_hash()
assert all(s.engine_hash!=latest.engine_hash for s in scans[:-1])
assert not snap['issues'] and not snap['unknown_datasets']
projected=data_health.project(latest,User.objects.get(username='demo_admin'))
assert not projected['stale'] and len(projected['rows'])==59
assert sum(not r['freshness']['has_target'] for r in projected['rows'])==58
policy=DataMonitorPolicy.objects.get(dataset='test_sessions');assert policy.version==2 and DataMonitorPolicy.objects.count()==1

identities=set(Record.objects.values_list('dataset','business_key'))
required=0;references=0;counts=Counter();data=defaultdict(list);facts_hash=hashlib.sha256()
for rec in Record.objects.select_related('source_row').order_by('dataset','business_key').iterator(chunk_size=1000):
    ds=rec.dataset;v=rec.values;counts[ds]+=1
    if ds in m.TABLES:data[ds].append(v)
    assert v['id']==rec.business_key and v==rec.source_row.normalized
    assert sha(v)==rec.record_hash==rec.source_row.record_hash
    assert (ds,rec.business_key)==(rec.source_row.dataset,rec.source_row.business_key)
    facts_hash.update(json.dumps((ds,rec.business_key,v,rec.revision,rec.source_row_id),ensure_ascii=False,sort_keys=True).encode())
    for field in SCHEMAS[ds]['fields']:
        val=v.get(field['name']);missing=val is None or isinstance(val,str) and not val.strip()
        if field['required']:assert not missing;required+=1
        if missing:continue
        typ=field['type']
        if typ=='int':assert type(val) is int
        elif typ=='bool':assert type(val) is bool
        elif typ=='float':assert type(val) in [int,float] and math.isfinite(val)
        elif typ=='str':assert isinstance(val,str) and val==val.strip() and not val.startswith('=')
        elif typ in ['date','datetime']:
            parsed=(date if typ=='date' else datetime).fromisoformat(val);assert parsed.isoformat()==val
        if field['reference']:assert (field['reference'],val) in identities;references+=1
assert (sum(counts.values()),len(counts))==(108197,59)
for ds,n in counts.items():assert snap['datasets'][ds]['rows']==n
assert sum(r['required_cells'] for r in projected['rows'])==required
assert sum(f['reference_present'] for d in snap['datasets'].values() for f in d['fields'].values())==references

# Independent event, batch path, quantity and date checks.
from statistics import median
idx={ds:{r['id']:r for r in rows} for ds,rows in data.items()}
ops=data['operations'];units=data['units'];work=idx['work_orders'];batches=idx['batches']
wo_ops=defaultdict(list);wo_units=defaultdict(list);batch_ops=defaultdict(list);batch_units=defaultdict(set)
processes=defaultdict(list)
for r in ops:
    assert r['started']<r['finished']<=cutoff.isoformat() and r['status']=='完成'
    assert r['input_qty']==r['good_qty']+r['scrap_qty'] and 0<=r['rework_qty']<=r['input_qty']
    wo_ops[r['work_order_id']].append(r)
    kind=batches[r['object_id']]['kind'] if r['object_type']=='生产批次' else r['object_type']
    processes[kind,r['process']].append(r)
    if r['object_type']=='生产批次':batch_ops[r['object_id']].append(r)
for u in units:
    assert u['assembly_at']<=cutoff.isoformat();wo_units[u['work_order_id']].append(u)
    for f in ['stator_batch','rotor_batch','assembly_batch']:batch_units[u[f]].add(u['id'])
plan=sum(w['planned_qty'] for w in work.values());qty=len(units);gap=plan-qty
bad_dates={k for k,w in work.items() if w['planned_start']>w['planned_end']}
no_events={k for k in work if not wo_ops[k]}
late={k for k,w in work.items() if k not in bad_dates and w['planned_end']<as_of.isoformat() and w['planned_qty']>len(wo_units[k])}
assert (len(work),plan,qty,gap,len(no_events),len(late),len(bad_dates))==(300,6750,4500,2250,100,48,6)
assert bad_dates=={f'MO2609-{i:06}' for i in [208,224,240,256,272,288]}
assert len(ops)==11085 and sum(r['rework_qty']>0 for r in ops)==209
b=m.Manufacturing(data,m.filters({}),cutoff=cutoff.isoformat());assert not b.global_issues
s=b.summary(b.selected());assert (s['planned_qty'],s['assembled_qty'],s['assembly_gap'],s['attention'],s['unknown_gaps'],s['late_gap'])==(plan,qty,gap,6,0,48)
for key,w in work.items():
    r=b.work_orders[key]['row'];assert r['assembled_qty']==len(wo_units[key]);assert r['assembly_gap']==w['planned_qty']-len(wo_units[key]);assert r['events']==len(wo_ops[key])
    assert bool(r['issues'])==(key in bad_dates) and ('late_gap' in r['flags'])==(key in late)
intervals=Counter();total_intervals=0
for key,ba in batches.items():
    r=b.batches[key]['row'];assert not r['issues'];assert r['assembly_refs']==len(batch_units[key])==ba['qty']
    if ba['kind']=='装配件包':assert not r['complete'] and r['route_steps']==0 and r['unreferenced_qty'] is None;continue
    events=sorted(batch_ops[key],key=lambda x:x['started']);assert len(events)==4
    span=0
    for a,z in zip(events,events[1:]):
        assert a['good_qty']==z['input_qty'] and a['finished']<=z['started']
        span+=(datetime.fromisoformat(z['started'])-datetime.fromisoformat(a['finished'])).total_seconds()/60
    assert r['complete'] and r['done_steps']==r['route_steps']==4 and r['unreferenced_qty']==0 and r['interval_minutes']==span
    assert events[0]['input_qty']==events[-1]['good_qty']==ba['qty']
    intervals[ba['kind']]+=span;total_intervals+=3
    sourcekeys={(x['dataset'],x['key']) for x in b.batches[key]['sources']}
    for u in batch_units[key]:
        assembly=next(o for o in wo_ops[ba['work_order_id']] if o['object_type']=='整机' and o['object_id']==u and o['process']=='装配')
        assert ('operations',assembly['id']) in sourcekeys
b.f=m.filters({'tab':'operations'});actual={(r['kind'],r['process']):r for r in b.breakdown(b.selected())}
for key,events in processes.items():
    r=actual[key];times=[(datetime.fromisoformat(e['finished'])-datetime.fromisoformat(e['started'])).total_seconds()/60 for e in events]
    assert r['events']==r['done']==len(events) and r['active']==r['attention']==0
    assert r['objects']==len({e['object_id'] for e in events}) and r['median_minutes']==median(times)
    assert [r[k] for k in ['completed_input','completed_good','completed_scrap','completed_rework']]==[sum(e[k] for e in events) for k in ['input_qty','good_qty','scrap_qty','rework_qty']]
assert total_intervals==1200 and len(actual)==12
exports={}
for tab,name,stage,expected in [('work_orders','制造_未见报工工单_浏览器导出.csv','no_events',no_events),('operations','制造_返工事件_浏览器导出.csv','rework',{r['id'] for r in ops if r['rework_qty']>0})]:
    p=ROOT/'outputs'/name;rows=list(csv.reader(p.open(encoding='utf-8-sig')));f=json.loads(rows[0][4]);assert f['tab']==tab and f['stage']==stage and rows[0][2]==cutoff.isoformat()
    assert not any(f[k] for k in ['from','to','family','product','work_order','q','process','kind'])
    items=[dict(zip(rows[2],r)) for r in rows[3:]];keyname='工单号' if tab=='work_orders' else '报工事件号';assert {r[keyname] for r in items}==expected
    for item in items:
        key=item[keyname]
        if tab=='work_orders':assert int(item['已登记装配SN数'])==0 and int(item['计划减装配记录'])==work[key]['planned_qty'] and int(item['报工事件数'])==0
        else:
            original=idx['operations'][key];assert int(item['登记投入数'])==original['input_qty'] and int(item['截止可核对合格数'])==original['good_qty']
            assert float(item['截止有效自然历时分钟'])==(datetime.fromisoformat(original['finished'])-datetime.fromisoformat(original['started'])).total_seconds()/60
    exports[name]={'rows':len(items),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()}
follow=IssueDisposition.objects.get(key='manufacturing:work_orders:MO2609-000208')
assert (follow.version,follow.status,follow.owner)==(1,'待计划核对','生产计划岗位（模拟）')
event=AuditEvent.objects.get(action='manufacturing.followup',object_id=follow.key);assert event.detail['business_facts_changed'] is False
v=MetricVersion.objects.get(metric__key='DELIVERY_OTIF',version=4)
assert v.status=='published' and v.calculation_hash==metric_registry.calculation_hash('bi_order_lines')=='f6815a706b1f19c2e2be0af931c640d869b45b17bc0aa1f72d7fe2144356868f'
assert ImportBatch.objects.exclude(status='superseded').count()==16
assert facts_hash.hexdigest()=='ee0eee547d9ffd495edbce3f89591729e946467cc6ecbcac48bec8dc3b0acd4a'
report={'synthetic':True,'baseline':str(baseline.relative_to(ROOT)),'business_rows':108197,'source_categories':59,'active_workbooks':16,'business_sha256':facts_hash.hexdigest(),'preserved_tables':preserved,'preserved_source_files':source_files,'manufacturing':{'work_orders':300,'planned_qty':plan,'assembled_qty':qty,'quantity_gap':gap,'no_event_work_orders':100,'late_assembly_gap_work_orders':48,'bad_plan_dates':sorted(bad_dates),'batches':600,'component_batches':400,'assembly_kits':200,'route_intervals':total_intervals,'interval_minutes_by_branch':dict(intervals),'operation_events':11085,'rework_marked_events':209,'separate_process_groups':len(actual)},'latest_scan_preserved':str(latest.pk),'basic_issues':0,'checked_required_cells':required,'checked_references':references,'browser_exports':exports,'coordination_version':1,'metric_v4_unchanged':True,'tests':616,'new_tests':35,'limits':'No physical WIP or true queue diagnosis: six synthetic plans have reversed dates; quantity differences remain independent, deadline assessment suspended. No process parameters, split/merge movement, shift handover or real U8/MES connection.'}
if len(sys.argv)>1:
    backup=Path(sys.argv[1])
    with zipfile.ZipFile(backup) as z,tempfile.TemporaryDirectory() as temp:
        manifest=json.loads(z.read('manifest.json'))
        for item in manifest['files']:
            blob=z.read(item['path']);assert len(blob)==item['size'] and hashlib.sha256(blob).hexdigest()==item['sha256']
        p=Path(temp)/'restored.sqlite3';p.write_bytes(z.read('data/platform.sqlite3'))
        with sqlite3.connect(p) as restored,sqlite3.connect(ROOT/'data/platform.sqlite3') as now:
            assert restored.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
            for table in tables:assert list(restored.execute(f'SELECT * FROM {table} ORDER BY id'))==list(now.execute(f'SELECT * FROM {table} ORDER BY id')),table
        report['backup']={'path':str(backup),'manifest_files':len(manifest['files']),'app_tables':len(tables),'sqlite_integrity':'ok','all_app_tables_match':True}
(ROOT/'data/manufacturing_validation.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
print(json.dumps({k:v for k,v in report.items() if k!='preserved_tables'},ensure_ascii=False,indent=2))
