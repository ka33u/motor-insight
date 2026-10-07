"""Independent current-snapshot reconciliation and preservation evidence.

Read-only against the application database; output is a validation receipt.
No business rows are created, repaired, or imported by this script.
"""
import os, sys, json, csv, hashlib, sqlite3, zipfile, tempfile, math
from pathlib import Path
from collections import Counter
from datetime import date, datetime

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT));os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings')
import django
django.setup()
from django.contrib.auth.models import User
from app.models import Record,DataQualityScan,DataMonitorPolicy,ImportBatch,AuditEvent,MetricVersion
from app.schema import SCHEMAS
from app import data_health,metric_registry

def sha(value):
    return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()

baseline=ROOT/'data/backups/motor-backup-20261003-201533.zip'
preserved={};source_files=0
with zipfile.ZipFile(baseline) as z,tempfile.TemporaryDirectory() as temp:
    manifest=json.loads(z.read('manifest.json'))
    for entry in manifest['files']:
        if entry['path'].startswith(('data/imports/','data/device_files/')):
            assert hashlib.sha256((ROOT/entry['path']).read_bytes()).hexdigest()==entry['sha256']
            source_files+=1
    p=Path(temp)/'before.sqlite3';p.write_bytes(z.read('data/platform.sqlite3'))
    with sqlite3.connect(p) as old,sqlite3.connect(ROOT/'data/platform.sqlite3') as now:
        old_tables=[r[0] for r in old.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'app_%'")]
        all_tables=[r[0] for r in now.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'app_%'")]
        assert set(all_tables)-set(old_tables)=={'app_dataqualityscan','app_datamonitorpolicy'}
        for table in old_tables:
            before=list(old.execute(f'SELECT * FROM {table} ORDER BY id'))
            current=list(now.execute(f'SELECT * FROM {table} ORDER BY id'));by_id={r[0]:r for r in current}
            assert all(by_id.get(r[0])==r for r in before),(table,'prior row changed')
            if table!='app_auditevent':assert len(before)==len(current),(table,'business/configuration count changed')
            preserved[table]={'before':len(before),'after':len(current),'prior_rows_unchanged':True}

scans=list(DataQualityScan.objects.order_by('created_at'))
assert len(scans)==2
latest=scans[-1];snap=latest.snapshot;cutoff=datetime.fromisoformat(snap['as_of'])
for scan in scans:
    assert sha(scan.snapshot)==scan.snapshot_hash
    event=AuditEvent.objects.get(action='data_health.scan',object_id=str(scan.pk))
    assert event.detail['snapshot_hash']==scan.snapshot_hash and event.detail['business_facts_changed'] is False
assert scans[0].engine_hash!=latest.engine_hash==data_health.engine_hash()
assert scans[0].snapshot==latest.snapshot,'same facts must produce same structural counters'
assert not snap['issues'] and not snap['unknown_datasets']

identities=set(Record.objects.values_list('dataset','business_key'))
count=Counter();batch_counts={ds:Counter() for ds in SCHEMAS};dates={};checked_references=0;required_cells=0
stats={ds:{f['name']:Counter() for f in spec['fields']} for ds,spec in SCHEMAS.items()}
for row in Record.objects.select_related('source_row').order_by('dataset','business_key').iterator(chunk_size=1000):
    ds=row.dataset;values=row.values;spec=SCHEMAS[ds];count[ds]+=1
    assert values[spec['primary_key']]==row.business_key
    assert sha(values)==row.record_hash==row.source_row.record_hash
    assert values==row.source_row.normalized and (ds,row.business_key)==(row.source_row.dataset,row.source_row.business_key)
    batch_counts[ds][str(row.source_row.batch_id)]+=1
    for field in spec['fields']:
        key=field['name'];v=values.get(key);s=stats[ds][key]
        missing=v is None or isinstance(v,str) and not v.strip()
        s['missing' if missing else 'present']+=1
        if field['required']:
            assert not missing,(ds,row.business_key,key);required_cells+=1
        if missing:continue
        kind=field['type']
        if kind=='str':assert isinstance(v,str) and v==v.strip() and not v.startswith('=')
        elif kind=='int':assert type(v) is int
        elif kind=='bool':assert type(v) is bool
        elif kind=='float':assert type(v) in [int,float] and math.isfinite(v)
        elif kind in ['date','datetime']:
            dt=date.fromisoformat(v) if kind=='date' else datetime.fromisoformat(v)
            assert dt.isoformat()==v
            if kind=='datetime':assert dt.tzinfo is None
            dates.setdefault((ds,key),[]).append(v)
        else:raise AssertionError(kind)
        if field['reference']:
            assert (field['reference'],v) in identities
            s['reference_present']+=1;checked_references+=1

for ds,spec in SCHEMAS.items():
    result=snap['datasets'][ds];assert result['rows']==count[ds]
    assert {b['id']:b['records'] for b in result['batches']}==batch_counts[ds]
    for field in spec['fields']:
        key=field['name'];result_field=result['fields'][key];expected=stats[ds][key]
        for k in ['present','missing','reference_present']:assert result_field[k]==expected[k],(ds,key,k)
        assert result_field['invalid']==result_field['reference_missing']==0
        sequence=dates.get((ds,key),[])
        if sequence:
            past=[x for x in sequence if (date.fromisoformat(x)<=cutoff.date() if field['type']=='date' else datetime.fromisoformat(x)<=cutoff)]
            assert result_field['minimum']==min(sequence) and result_field['maximum']==max(sequence)
            assert result_field['past_maximum']==(max(past) if past else None)
            assert result_field['future']==len(sequence)-len(past)

policy=DataMonitorPolicy.objects.get(dataset='test_sessions')
assert DataMonitorPolicy.objects.count()==1 and policy.version==2
assert policy.business_clock=='tested' and policy.max_business_lag_days==1 and policy.max_import_age_hours==48
assert AuditEvent.objects.filter(action='data_health.policy',object_id='test_sessions').count()==2
projected=data_health.project(latest,User.objects.get(username='demo_admin'))
assert not projected['stale'] and len(projected['rows'])==54
assert sum(r['required_cells'] for r in projected['rows'])==required_cells
assert sum(not r['freshness']['has_target'] for r in projected['rows'])==53
assert [r['dataset'] for r in projected['rows'] if 'late' in r['flags']]==['test_sessions']
conditions=list(Record.objects.filter(dataset='service_conditions').values_list('values',flat=True))
# 45 installation narratives have no numeric value; another 20 readings were
# not supplied. Optional numeric nulls are not 65 missing business documents.
assert stats['service_conditions']['value']['missing']==65
assert sum(r['status']=='未提供' for r in conditions)==20
assert sum(r['unit'] is None for r in conditions)==45

exports={}
for name,expected_rows in [('数据监测_超期源表_浏览器导出.csv',1),('数据监测_超期表基础问题_浏览器导出.csv',0)]:
    p=ROOT/'outputs'/name;rows=list(csv.reader(p.open(encoding='utf-8-sig')))
    assert rows[0][1]==str(latest.pk) and json.loads(rows[0][5])['stage']=='late'
    assert rows[1][3]=='False' and len(rows[3:])==expected_rows
    if expected_rows:
        item=dict(zip(rows[2],rows[3]));assert item['源表']=='test_sessions'
        assert (int(item['检查记录数']),int(item['已查必填单元格']),int(item['规则版本']))==(4554,54648,2)
        assert item['时效状态']=='business_late;import_within'
        latest_test=max(dates['test_sessions','tested'])
        lag=(cutoff-datetime.fromisoformat(latest_test)).total_seconds()/86400
        assert item['截至业务截止最大时点']==latest_test=='2026-09-26T11:54:00'
        assert float(item['距业务截止天数'])==lag and lag>float(item['业务最多滞后天数'])
        observed=datetime.fromisoformat(rows[1][5]);committed=datetime.fromisoformat(item['最近有效提交'])
        assert abs(float(item['距导入小时'])-(observed-committed).total_seconds()/3600)<1e-9
    exports[name]={'rows':expected_rows,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()}

assert ImportBatch.objects.exclude(status='superseded').count()==14
version=MetricVersion.objects.get(metric__key='DELIVERY_OTIF',version=4)
assert version.status=='published' and version.calculation_hash==metric_registry.calculation_hash('bi_order_lines')
h=hashlib.sha256()
for row in Record.objects.order_by('dataset','business_key').values_list('dataset','business_key','values','revision','source_row_id').iterator():
    h.update(json.dumps(row,ensure_ascii=False,sort_keys=True).encode())
assert h.hexdigest()=='2480b56100e4d517cbe21601b45214a8d1dd77fd2dcce40d6e5c94c07e31cdc5'
report={'synthetic':True,'baseline':str(baseline.relative_to(ROOT)),'business_rows':sum(count.values()),'source_categories':len(count),'business_sha256':h.hexdigest(),'preserved_tables':preserved,'preserved_source_files':source_files,'scan_ids':[str(s.pk) for s in scans],'latest_snapshot_sha256':latest.snapshot_hash,'basic_issues':0,'checked_required_cells':required_cells,'checked_references':checked_references,'policy_version':2,'no_target_tables':53,'late_tables':['test_sessions'],'browser_exports':exports,'metric_v4_unchanged':True,'tests':513,'new_tests':36,'limits':'Structural inspection of synthetic imported records only. No proof of business truth, complete periods, approved quality, continuous watermarks, automated collection, or full incident workflow.'}
assert report['business_rows']==107389 and report['source_categories']==54
if len(sys.argv)>1:
    backup=Path(sys.argv[1])
    with zipfile.ZipFile(backup) as z,tempfile.TemporaryDirectory() as temp:
        manifest=json.loads(z.read('manifest.json'))
        for item in manifest['files']:
            blob=z.read(item['path']);assert len(blob)==item['size'] and hashlib.sha256(blob).hexdigest()==item['sha256']
        p=Path(temp)/'restored.sqlite3';p.write_bytes(z.read('data/platform.sqlite3'))
        with sqlite3.connect(p) as restored,sqlite3.connect(ROOT/'data/platform.sqlite3') as now:
            assert restored.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
            for table in all_tables:
                assert list(restored.execute(f'SELECT * FROM {table} ORDER BY id'))==list(now.execute(f'SELECT * FROM {table} ORDER BY id')),table
        report['backup']={'path':str(backup),'manifest_files':len(manifest['files']),'app_tables':len(all_tables),'sqlite_integrity':'ok','all_app_tables_match':True}
(ROOT/'data/data_health_validation.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
print(json.dumps({k:v for k,v in report.items() if k!='preserved_tables'},ensure_ascii=False,indent=2))
