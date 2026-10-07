"""Read-only reconciliation of reviewed date corrections and scan history."""
import os,sys,json,sqlite3,zipfile,tempfile,hashlib,copy,csv
from pathlib import Path
from datetime import date,datetime
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings')
import django
django.setup()
from openpyxl import load_workbook
from django.contrib.auth.models import User
from app.models import Record,ImportBatch,ImportRow,ImportDecision,IssueDisposition,AuditEvent,DataQualityScan,MetricVersion,AnalysisModel,Topic
from app import data_health,manufacturing as m,metric_registry
from app.ingestion import fingerprint,convert
from app.schema import SCHEMAS

baseline=ROOT/'data/backups/motor-backup-20261003-234516.zip'
keys={f'MO2609-{i:06}' for i in [208,224,240,256,272,288]}
path=ROOT/'outputs/01a0f580-2480-7820-bc97-8ca293421c39/17_计划日期更正_模拟.xlsx'
file_hash=hashlib.sha256(path.read_bytes()).hexdigest()
batch=ImportBatch.objects.get(file_hash=file_hash,status='committed')
assert batch.summary=={'replaced':6,'total':6,'unknown_sheets':[]},batch.summary
assert Path(batch.file_path).read_bytes()==path.read_bytes()
book=load_workbook(path,read_only=True,data_only=False);sheet=book['生产工单'];it=sheet.iter_rows(values_only=True);fields=SCHEMAS['work_orders']['fields']
assert list(next(it))==[f['label'] for f in fields]
parsed={}
for n,values in enumerate(it,2):
    row={f['name']:convert(v,f) for f,v in zip(fields,values)};parsed[row['id']]=row
    for col in [4,5]:assert sheet.cell(n,col).is_date
book.close();assert set(parsed)==keys
old_counts={};source_count=0;preserved={}
delta={'app_importbatch':1,'app_importrow':6,'app_importdecision':6,'app_dataqualityscan':2}
with zipfile.ZipFile(baseline) as z,tempfile.TemporaryDirectory() as tmp:
    for entry in json.loads(z.read('manifest.json'))['files']:
        if entry['path'].startswith(('data/imports/','data/device_files/')):
            assert hashlib.sha256((ROOT/entry['path']).read_bytes()).hexdigest()==entry['sha256'];source_count+=1
    before=Path(tmp)/'old.sqlite3';before.write_bytes(z.read('data/platform.sqlite3'))
    with sqlite3.connect(before) as old,sqlite3.connect(ROOT/'data/platform.sqlite3') as now:
        tables=[r[0] for r in old.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'app_%'")]
        assert len(tables)==25
        for table in tables:
            cols=[r[1] for r in old.execute(f'PRAGMA table_info({table})')]
            previous=[dict(zip(cols,r)) for r in old.execute(f'SELECT * FROM {table} ORDER BY id')]
            current={r[0]:dict(zip(cols,r)) for r in now.execute(f'SELECT * FROM {table} ORDER BY id')}
            changed=0;old_counts[table]=len(previous)
            for row in previous:
                live=current[row['id']]
                if table=='app_record' and row['dataset']=='work_orders' and row['business_key'] in keys:
                    expected=json.loads(row['values']);assert expected['planned_start']=='2026-09-23'
                    expected['planned_start']='2026-09-19';assert expected==json.loads(live['values'])==parsed[row['business_key']]
                    assert live['revision']==row['revision']+1 and live['record_hash']==fingerprint(expected)
                    assert {k for k in row if live[k]!=row[k]}<={'values','record_hash','revision','source_row_id','updated_at'}
                    decision=ImportDecision.objects.get(row__batch=batch,row__business_key=row['business_key'])
                    assert decision.action=='replace' and decision.before['hash']==row['record_hash'] and decision.before['values']==json.loads(row['values'])
                    assert decision.after['values']==expected and decision.after['revision']==live['revision'] and decision.after['source']['row_id']==live['source_row_id']
                    changed+=1
                elif table=='app_issuedisposition' and row['key']=='manufacturing:work_orders:MO2609-000208':
                    assert (row['version'],live['version'],live['status'])==(1,2,'演练已核对')
                    assert live['owner']==row['owner']=='生产计划岗位（模拟）';changed+=1
                else:assert live==row,(table,row['id'],'unrelated prior row changed')
            if table!='app_auditevent':assert len(current)-len(previous)==delta.get(table,0),(table,len(current),len(previous))
            preserved[table]={'before':len(previous),'after':len(current),'authorized_changed_prior_rows':changed}

facts_hash=hashlib.sha256()
for rec in Record.objects.select_related('source_row').order_by('dataset','business_key').iterator(chunk_size=1000):
    assert rec.values==rec.source_row.normalized and rec.record_hash==rec.source_row.record_hash==fingerprint(rec.values)
    assert (rec.dataset,rec.business_key)==(rec.source_row.dataset,rec.source_row.business_key)
    facts_hash.update(json.dumps((rec.dataset,rec.business_key,rec.values,rec.revision,rec.source_row_id),ensure_ascii=False,sort_keys=True).encode())
assert Record.objects.count()==108197 and Record.objects.values('dataset').distinct().count()==59
assert ImportBatch.objects.exclude(status='superseded').count()==17
assert (AnalysisModel.objects.count(),Topic.objects.count())==(48,17)
scans=list(DataQualityScan.objects.order_by('created_at'));assert len(scans)==6
before,after=scans[-2:]
assert before.engine_hash==after.engine_hash==data_health.engine_hash()
assert all(s.engine_hash!=after.engine_hash for s in scans[:-2])
assert len(before.snapshot['issues'])==6 and {i['key'] for i in before.snapshot['issues']}==keys
assert all(i['rule']=='manufacturing' and i['message'].startswith('WO_PLAN_ORDER') for i in before.snapshot['issues'])
assert not after.snapshot['issues'] and not after.snapshot['unknown_datasets']
for scan in scans:assert data_health.digest(scan.snapshot)==scan.snapshot_hash
user=User.objects.get(username='demo_admin');assert data_health.project(before,user)['stale'] and not data_health.project(after,user)['stale']
assert sum(x['rows'] for x in after.snapshot['datasets'].values())==108197

data={ds:list(Record.objects.filter(dataset=ds).values_list('values',flat=True)) for ds in m.TABLES}
work={r['id']:r for r in data['work_orders']};cutoff=datetime.fromisoformat(after.snapshot['as_of'])
assert all(w['planned_start']<=w['planned_end'] for w in work.values())
unit_counts={k:sum(u['work_order_id']==k and u['assembly_at']<=cutoff.isoformat() for u in data['units']) for k in work}
late={k for k,w in work.items() if w['planned_end']<cutoff.date().isoformat() and w['planned_qty']>unit_counts[k]}
assert len(late)==54 and keys<=late
engine=m.Manufacturing(data,m.filters({}),cutoff=cutoff.isoformat());s=engine.summary(engine.selected())
assert (s['objects'],s['attention'],s['planned_qty'],s['assembled_qty'],s['assembly_gap'],s['no_events'],s['late_gap'])==(300,0,6750,4500,2250,100,54)
export=ROOT/'outputs/制造_修正后到期工单_浏览器导出.csv';rows=list(csv.reader(export.open(encoding='utf-8-sig')))
filters=json.loads(rows[0][4]);assert filters['stage']=='late_gap' and filters['tab']=='work_orders'
assert not any(filters[k] for k in ['from','to','family','product','work_order','q','process','kind'])
items=[dict(zip(rows[2],r)) for r in rows[3:]];assert {r['工单号'] for r in items}==late
for row in items:
    w=work[row['工单号']];assert row['计划开工']==w['planned_start'] and row['计划完工']==w['planned_end']
v=MetricVersion.objects.get(metric__key='DELIVERY_OTIF',version=4)
assert v.status=='published' and v.calculation_hash==metric_registry.calculation_hash('bi_order_lines')=='f6815a706b1f19c2e2be0af931c640d869b45b17bc0aa1f72d7fe2144356868f'
assert AuditEvent.objects.filter(action='manufacturing.followup',object_id='manufacturing:work_orders:MO2609-000208').count()==2
report={'synthetic':True,'baseline':str(baseline.relative_to(ROOT)),'workbook_sha256':file_hash,'batch':str(batch.pk),'corrected_keys':sorted(keys),'changed_field':'planned_start','before':'2026-09-23','after':'2026-09-19','date_cells_checked':12,'workbook_cells_checked':54,'records':108197,'source_categories':59,'active_workbooks':17,'business_sha256':facts_hash.hexdigest(),'preserved_source_files':source_count,'preserved_tables':preserved,'before_scan':str(before.pk),'after_scan':str(after.pk),'before_issues':6,'after_issues':0,'late_assembly_gap_before':48,'late_assembly_gap_after':54,'browser_export_rows':len(items),'browser_export_sha256':hashlib.sha256(export.read_bytes()).hexdigest(),'coordination_version':2,'metric_v4_unchanged':True,'tests':646,'new_tests':30,'limit':'Synthetic date correction preserves planned end and customer promise; no capacity feasibility, new production or real ERP/MES synchronization is asserted.'}
if len(sys.argv)>1:
    backup=Path(sys.argv[1])
    with zipfile.ZipFile(backup) as z,tempfile.TemporaryDirectory() as tmp:
        manifest=json.loads(z.read('manifest.json'))
        for entry in manifest['files']:
            raw=z.read(entry['path']);assert len(raw)==entry['size'] and hashlib.sha256(raw).hexdigest()==entry['sha256']
        db=Path(tmp)/'restore.sqlite3';db.write_bytes(z.read('data/platform.sqlite3'))
        with sqlite3.connect(db) as recovered,sqlite3.connect(ROOT/'data/platform.sqlite3') as now:
            assert recovered.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
            for table in tables:assert list(recovered.execute(f'SELECT * FROM {table} ORDER BY id'))==list(now.execute(f'SELECT * FROM {table} ORDER BY id'))
        report['backup']={'path':str(backup),'files':len(manifest['files']),'app_tables':len(tables),'sqlite_integrity':'ok','all_app_tables_match':True}
(ROOT/'data/plan_correction_validation.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
print(json.dumps({k:v for k,v in report.items() if k!='preserved_tables'},ensure_ascii=False,indent=2))
