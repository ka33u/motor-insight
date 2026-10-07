"""Raw-Excel energy/EHS reconciliation, browser exports and preservation audit."""
import os,sys,json,csv,hashlib,sqlite3,zipfile,tempfile
from pathlib import Path
from decimal import Decimal,ROUND_HALF_UP
from datetime import datetime,date
from collections import defaultdict,Counter
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings')
import django;django.setup()
from app import energy_board as e,metric_registry
from app.models import Record,IssueDisposition,MetricVersion
from app.trace_cases import capture_sources

baseline=ROOT/'data/backups/motor-backup-20261003-191152.zip';preserved={}
with zipfile.ZipFile(baseline) as z,tempfile.TemporaryDirectory() as temp:
    manifest=json.loads(z.read('manifest.json'))
    for item in manifest['files']:
        if item['path'].startswith(('data/imports/','data/device_files/')):assert hashlib.sha256((ROOT/item['path']).read_bytes()).hexdigest()==item['sha256']
    p=Path(temp)/'old.sqlite3';p.write_bytes(z.read('data/platform.sqlite3'))
    with sqlite3.connect(p) as old,sqlite3.connect(ROOT/'data/platform.sqlite3') as now:
        tables=[r[0] for r in old.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'app_%'")]
        for t in tables:
            previous=list(old.execute(f'SELECT * FROM {t} ORDER BY id'));current=list(now.execute(f'SELECT * FROM {t} ORDER BY id'));assert current[:len(previous)]==previous,(t,'old row changed')
            if t!='app_auditevent':assert len(current)-len(previous)==(1 if t=='app_issuedisposition' else 0),(t,len(previous),len(current))
            preserved[t]={'before':len(previous),'after':len(current),'prior_rows_unchanged':True}
raw={k:list(Record.objects.filter(dataset=k).values_list('values',flat=True)) for k in e.TABLES}
totals=defaultdict(Decimal);daily=defaultdict(Decimal);hourly=defaultdict(Decimal);costs=defaultdict(Decimal);spans=defaultdict(list);shopmap=defaultdict(set)
for r in raw['energy']:
    a,b=datetime.fromisoformat(r['started']),datetime.fromisoformat(r['ended']);assert (b-a).total_seconds()==3600 and a.minute==0 and a.second==0
    spans[r['meter']].append((a,b));shopmap[r['meter']].add(r['workshop']);kwh=Decimal(str(r['kwh']));assert kwh>=0
    totals[r['meter']]+=kwh;daily[a.date().isoformat()]+=kwh;hourly[a.hour]+=kwh;costs[r['meter']]+=kwh*Decimal(r['tariff_cents'])
for meter,intervals in spans.items():
    ordered=sorted(intervals);assert len(shopmap[meter])==1 and len(ordered)==120
    assert ordered[0][0]==datetime(2026,9,21) and ordered[-1][1]==datetime(2026,9,26)
    assert all(left[1]==right[0] for left,right in zip(ordered,ordered[1:])),meter
assert sum(totals.values())==Decimal('40484.43')
def close(a,b):assert abs(a-float(b))<1e-7,(a,b)
d=e.current(e.filters({}));rows=d.selected();s=d.summary(rows);b=d.breakdown(rows);assert not d.global_issues and not b['assembly_issues']
assert (s['objects'],s['verified'],s['complete'],s['attention'])==(6,6,6,0);close(s['kwh'],sum(totals.values()));assert s['covered_hours']==s['expected_hours']==720
expected_cost=sum(int(c.quantize(Decimal(1),rounding=ROUND_HALF_UP)) for c in costs.values());assert s['cost_cents']==expected_cost==3356984
for r in rows:close(r['kwh'],totals[r['id']]);assert r['coverage_pct']==100 and not r['issues'];assert r['cost_cents']==int(costs[r['id']].quantize(Decimal(1),rounding=ROUND_HALF_UP))
for r in b['daily']:close(r['kwh'],daily[r['date']]);assert r['complete_meters']==6
for r in b['hourly']:close(r['kwh'],hourly[int(r['hour'][:2])])
equipment={r['id']:r for r in raw['equipment']};ops=defaultdict(list)
for r in raw['operations']:
    if r['process']=='装配' and r['object_type']=='整机':ops[r['object_id']].append(r)
sn_by_day=defaultdict(list)
for u in raw['units']:
    match=ops[u['id']];assert len(match)==1;op=match[0];assert op['finished']==u['assembly_at'] and op['work_order_id']==u['work_order_id'] and op['status']=='完成'
    assert equipment[op['equipment_id']]['workshop']=='装配车间';sn_by_day[u['assembly_at'][:10]].append(u)
for r in b['assembly']:
    original=[a for a in raw['energy'] if a['workshop']=='装配车间' and a['started'][:10]==r['date']];total=sum((Decimal(str(x['kwh'])) for x in original),Decimal(0));units=sn_by_day[r['date']]
    assert r['units']==len(units)==900 and r['configurations']==len({u['product_id'] for u in units})==40;close(r['kwh'],total);close(r['kwh_per_assembly'],total/len(units))
ehs=e.current(e.filters({'tab':'ehs'}));cases=ehs.selected();cutoff=date(2026,10,1);open_ids=[];closed_ids=[];elapsed=[]
for original in raw['ehs']:
    found=date.fromisoformat(original['found']);due=date.fromisoformat(original['due']);closed=date.fromisoformat(original['closed']) if original['closed'] else None
    assert found<=cutoff and found<=due
    output=ehs.cases[original['id']];assert not output['issues']
    if closed and closed<=cutoff:
        closed_ids.append(original['id']);elapsed.append((closed-found).days);assert output['elapsed_days']==(closed-found).days
    else:
        open_ids.append(original['id']);assert due<cutoff;assert output['overdue_days']==(cutoff-due).days
es=ehs.summary(cases);assert (es['objects'],es['open'],es['overdue'],es['closed'])==(24,8,8,16);assert es['closed_days']==sum(elapsed)/len(elapsed)==3
sources=[]
for day in sorted(sn_by_day):sources+=capture_sources(d.detail('assembly',day))
for mid in d.meters:sources+=capture_sources(d.detail('meter',mid))
for key in ehs.cases:sources+=capture_sources(ehs.detail('ehs',key))
sources={(r['dataset'],r['key']):r for r in sources};files={}
for (ds,key),src in sources.items():
    assert not src.get('missing');r=Record.objects.select_related('source_row__batch').get(dataset=ds,business_key=key)
    assert r.values==r.source_row.normalized and r.record_hash==r.source_row.record_hash;bch=r.source_row.batch;files[str(bch.pk)]=(bch.file_path,bch.file_hash)
for path,sha in files.values():assert hashlib.sha256(Path(path).read_bytes()).hexdigest()==sha
exports={}
p=ROOT/'outputs/能源_装配单日分表_浏览器导出.csv';csvrows=list(csv.reader(p.open(encoding='utf-8-sig')));f=json.loads(csvrows[0][4]);assert f['workshop']=='装配车间' and f['from']==f['to']=='2026-09-21'
assert len(csvrows)==4 and csvrows[3][0]=='EM-05';close(float(csvrows[3][3]),Decimal('1387.27'));assert float(csvrows[3][4])==float(csvrows[3][5])==24
exports[p.name]={'rows':1,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()}
p=ROOT/'outputs/安环_逾期未关闭_浏览器导出.csv';csvrows=list(csv.reader(p.open(encoding='utf-8-sig')));f=json.loads(csvrows[0][4]);assert f['tab']=='ehs' and f['stage']=='overdue' and not f['workshop']
assert len(csvrows)==11 and {r[0] for r in csvrows[3:]}==set(open_ids)
for r in csvrows[3:]:assert int(r[10])==ehs.cases[r[0]]['overdue_days']
exports[p.name]={'rows':8,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()}
note=IssueDisposition.objects.get(key='energy:ehs:AH2609-0001');assert note.version==1 and note.status=='待现场核查';assert ehs.cases['AH2609-0001']['status']=='整改中'
v=MetricVersion.objects.get(metric__key='DELIVERY_OTIF',version=4);assert v.status=='published' and v.calculation_hash==metric_registry.calculation_hash('bi_order_lines')
h=hashlib.sha256()
for r in Record.objects.order_by('dataset','business_key').values_list('dataset','business_key','values','revision','source_row_id').iterator():h.update(json.dumps(r,ensure_ascii=False,sort_keys=True).encode())
assert h.hexdigest()=='298b65fd282b1b8c05fc78a549d95058fd46b83984165275958ad16d080eba3f'
report={'synthetic':True,'baseline':str(baseline.relative_to(ROOT)),'business_rows':Record.objects.count(),'business_sha256':h.hexdigest(),'preserved_tables':preserved,'energy':s,'assembly_reference':b['assembly'],'ehs':es,'sources':len(sources),'source_files':len(files),'browser_exports':exports,'metric_v4_unchanged':True,'tests':447,'new_tests':27,'limits':'Imported submeter intervals only; no certified meter hierarchy, factory balance, product actual energy or EHS approval/closure. Cost uses meter-level cent rounding.'}
if len(sys.argv)>1:
    backup=Path(sys.argv[1])
    with zipfile.ZipFile(backup) as z,tempfile.TemporaryDirectory() as temp:
        manifest=json.loads(z.read('manifest.json'))
        for item in manifest['files']:
            blob=z.read(item['path']);assert len(blob)==item['size'] and hashlib.sha256(blob).hexdigest()==item['sha256']
        p=Path(temp)/'restored.sqlite3';p.write_bytes(z.read('data/platform.sqlite3'))
        with sqlite3.connect(p) as restored,sqlite3.connect(ROOT/'data/platform.sqlite3') as now:
            assert restored.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
            for t in tables:assert list(restored.execute(f'SELECT * FROM {t} ORDER BY id'))==list(now.execute(f'SELECT * FROM {t} ORDER BY id')),t
        report['backup']={'path':str(backup),'manifest_files':len(manifest['files']),'app_tables':len(tables),'sqlite_integrity':'ok','all_app_tables_match':True}
(ROOT/'data/energy_validation.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
print(json.dumps({k:v for k,v in report.items() if k not in ['preserved_tables','assembly_reference']},ensure_ascii=False))
