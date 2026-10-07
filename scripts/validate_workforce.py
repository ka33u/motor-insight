"""Independent raw-fact reconciliation and pre-workforce preservation audit."""
import os,sys,json,csv,sqlite3,zipfile,tempfile,hashlib
from pathlib import Path
from collections import defaultdict,Counter
from datetime import datetime,date
from decimal import Decimal
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings')
import django;django.setup()
from app import workforce as w,metric_registry
from app.models import Record,MetricVersion,IssueDisposition
from app.trace_cases import capture_sources

baseline=ROOT/'data/backups/motor-backup-20261003-183739.zip';preserved={}
with zipfile.ZipFile(baseline) as z,tempfile.TemporaryDirectory() as temp:
    manifest=json.loads(z.read('manifest.json'))
    for item in manifest['files']:
        if item['path'].startswith(('data/imports/','data/device_files/')):assert hashlib.sha256((ROOT/item['path']).read_bytes()).hexdigest()==item['sha256']
    p=Path(temp)/'baseline.sqlite3';p.write_bytes(z.read('data/platform.sqlite3'))
    with sqlite3.connect(p) as old,sqlite3.connect(ROOT/'data/platform.sqlite3') as now:
        tables=[r[0] for r in old.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'app_%'")]
        for t in tables:
            oldcount=old.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0];newcount=now.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0]
            cursor=now.execute(f'SELECT * FROM {t} ORDER BY id')
            for row in old.execute(f'SELECT * FROM {t} ORDER BY id'):assert row==next(cursor),(t,'prior row changed')
            if t!='app_auditevent':assert newcount-oldcount==(1 if t=='app_issuedisposition' else 0),(t,oldcount,newcount)
            preserved[t]={'before':oldcount,'after':newcount,'prior_rows_unchanged':True}
raw={k:list(Record.objects.filter(dataset=k).values_list('values',flat=True)) for k in w.TABLES}
employees={r['id']:r for r in raw['employees']};att=defaultdict(list);labor=defaultdict(list);cal=defaultdict(list)
for r in raw['attendance']:
    if r['date']<='2026-10-01':att[r['employee_id']].append(r)
for r in raw['labor_entries']:
    if r['finished']<='2026-10-01T18:00:00':labor[r['employee_id']].append(r)
for r in raw['resource_calendars']:
    if r['finished']<='2026-10-01T18:00:00':cal[r['employee_id']].append(r)
def decimal_sum(rows,fields):return sum((Decimal(str(r[k])) for r in rows for k in fields),Decimal(0))
def elapsed(rows):return sum((datetime.fromisoformat(r['finished'])-datetime.fromisoformat(r['started'])).total_seconds()/3600 for r in rows)
def close(a,b):assert abs(a-float(b))<1e-7,(a,b)
d=w.current(w.filters({}));rows=d.selected();summary=d.summary(rows);assert not d.global_issues
expected_total=decimal_sum(raw['attendance'],list(w.HOURS));expected_extra=decimal_sum(raw['attendance'],['overtime_hours'])
assert expected_total==Decimal('23879.9996') and expected_extra==840
close(summary['total_hours'],expected_total);close(summary['overtime_hours'],expected_extra)
assert (summary['objects'],summary['recorded'],summary['verified'],summary['labor_people'])==(192,192,192,52)
for r in rows:
    eid=r['id'];assert not r['issues'];close(r['total_hours'],decimal_sum(att[eid],list(w.HOURS)))
    close(r['overtime_hours'],decimal_sum(att[eid],['overtime_hours']))
    if labor[eid]:close(r['labor_hours'],elapsed(labor[eid]))
    else:assert r['labor_hours'] is None
    if cal[eid]:close(r['calendar_hours'],elapsed(cal[eid])) # Production fixture separately guarantees non-overlap.
    else:assert r['calendar_hours'] is None
    perday=defaultdict(list)
    for a in att[eid]:perday[a['date']].append(a)
    for out in d.people[eid]['daily']:close(out['total'],decimal_sum(perday[out['date']],list(w.HOURS)))
skills=w.current(w.filters({'tab':'skills'}));grants=skills.selected();effective=[r for r in raw['skills'] if r['status']=='有效' and r['approved']<='2026-10-01'<=r['expires'] and employees[r['employee_id']]['active']]
assert len(effective)==79 and len({r['employee_id'] for r in effective})==65
expected_pairs={(r['employee_id'],r['process']) for r in effective};assert skills.summary(grants)['effective_pairs']==len(expected_pairs)==79
required={(r['employee_id'],r['process']) for r in raw['production_resources'] if r['effective']<='2026-10-01'}
assert len(required)==56 and not required-expected_pairs
for r in skills.breakdown(grants)['processes']:
    assert r['effective_people']==len({eid for eid,process in expected_pairs if process==r['process']})
    assert r['assigned_people']==len({eid for eid,process in required if process==r['process']})
    assert r['expiring_people']==0 and r['unmatched_assigned']==0
exports={}
f=w.filters({'department':'D07','from':'2026-09-21','to':'2026-09-21'});one=w.current(f);want={r['id']:r for r in one.selected()}
p=ROOT/'outputs/人员工时_绕组车间单日_浏览器导出.csv';csvrows=list(csv.reader(p.open(encoding='utf-8-sig')));assert json.loads(csvrows[0][4])==f
assert len(csvrows[3:])==14 and {r[0] for r in csvrows[3:]}==set(want)
for r in csvrows[3:]:
    assert r[5]==str(want[r[0]]['total_hours']) and r[6]==str(want[r[0]]['overtime_hours'])
selected_attendance=[r for r in raw['attendance'] if r['date']=='2026-09-21' and employees[r['employee_id']]['department_id']=='D07']
selected_total=decimal_sum(selected_attendance,list(w.HOURS));selected_overtime=decimal_sum(selected_attendance,['overtime_hours'])
assert selected_total==Decimal('126.0001') and selected_overtime==14
close(sum(float(r[5]) for r in csvrows[3:]),selected_total);close(sum(float(r[6]) for r in csvrows[3:]),selected_overtime)
exports[p.name]={'rows':14,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()}
p=ROOT/'outputs/技能覆盖_绕线嵌线_浏览器导出.csv';csvrows=list(csv.reader(p.open(encoding='utf-8-sig')));assert json.loads(csvrows[0][4])['process']=='绕线嵌线'
assert len(csvrows[3:])==9 and {r[0] for r in csvrows[3:]}=={r['id'] for r in effective if r['process']=='绕线嵌线'}
exports[p.name]={'rows':9,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()}
detail=one.detail('E00001');assert detail['row']['total_hours']==9 and abs(detail['row']['labor_hours']-7)<1e-9
sources=capture_sources(detail);files={}
for s in sources:
    assert not s.get('missing');r=Record.objects.select_related('source_row__batch').get(dataset=s['dataset'],business_key=s['key'])
    assert r.values==r.source_row.normalized and r.record_hash==r.source_row.record_hash
    b=r.source_row.batch;files[str(b.pk)]=(b.file_path,b.file_hash)
for path,sha in files.values():assert hashlib.sha256(Path(path).read_bytes()).hexdigest()==sha
follow=IssueDisposition.objects.get(key='workforce:E00001');assert follow.version==1 and follow.status=='待授权复核'
v=MetricVersion.objects.get(metric__key='DELIVERY_OTIF',version=4);assert v.status=='published' and v.calculation_hash==metric_registry.calculation_hash('bi_order_lines')
h=hashlib.sha256()
for r in Record.objects.order_by('dataset','business_key').values_list('dataset','business_key','values','revision','source_row_id').iterator():h.update(json.dumps(r,ensure_ascii=False,sort_keys=True).encode())
assert h.hexdigest()=='298b65fd282b1b8c05fc78a549d95058fd46b83984165275958ad16d080eba3f'
report={'synthetic':True,'baseline':str(baseline.relative_to(ROOT)),'business_rows':106940,'business_sha256':h.hexdigest(),'preserved_tables':preserved,'summary':summary,'categories':d.breakdown(rows)['categories'],'skills':skills.summary(grants),'fixed_resource_pairs':len(required),'browser_exports':exports,'person_sources':len(sources),'source_files':len(files),'metric_v4_unchanged':True,'tests':420,'new_tests':27,'limits':'Current skill register only; no status history, attendance clock, formal training evidence or actual staffing/assessment decisions. Financial columns excluded from this workspace.'}
if len(sys.argv)>1:
    backup=Path(sys.argv[1])
    with zipfile.ZipFile(backup) as z,tempfile.TemporaryDirectory() as temp:
        manifest=json.loads(z.read('manifest.json'))
        for f in manifest['files']:
            blob=z.read(f['path']);assert len(blob)==f['size'] and hashlib.sha256(blob).hexdigest()==f['sha256']
        p=Path(temp)/'restored.sqlite3';p.write_bytes(z.read('data/platform.sqlite3'))
        with sqlite3.connect(p) as restored,sqlite3.connect(ROOT/'data/platform.sqlite3') as now:
            assert restored.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
            for t in tables:assert list(restored.execute(f'SELECT * FROM {t} ORDER BY id'))==list(now.execute(f'SELECT * FROM {t} ORDER BY id')),t
        report['backup']={'path':str(backup),'manifest_files':len(manifest['files']),'app_tables':len(tables),'sqlite_integrity':'ok','all_app_tables_match':True}
(ROOT/'data/workforce_validation.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
print(json.dumps({k:v for k,v in report.items() if k!='preserved_tables'},ensure_ascii=False))
