"""Read-only validation against pre-change SQLite and independent raw SN sets."""
import os,sys,json,copy,hashlib,sqlite3,zipfile,tempfile,csv,io
from collections import defaultdict,Counter
from datetime import datetime
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings')
import django;django.setup()
from django.db import connection
from django.contrib.auth.models import User
from app.models import Record,AnalysisModel,Topic,TopicView,TopicSnapshot,ImportBatch,MetricVersion
from app import analysis_engine as engine,metric_registry as registry,targets as k
from app.target_views import FIELDS
connection.cursor().execute('PRAGMA query_only=ON')
backup=ROOT/'data/backups/motor-backup-20261004-213800.zip';report={'synthetic':True,'baseline':str(backup),'preserved_tables':{}}
expected_additions={'app_record':62,'app_importrow':62,'app_importbatch':1,'app_issuedisposition':1}
with zipfile.ZipFile(backup) as z,tempfile.TemporaryDirectory() as tmp:
    p=Path(tmp)/'before.sqlite3';p.write_bytes(z.read('data/platform.sqlite3'));report['original_files_preserved']=0
    for f in json.loads(z.read('manifest.json'))['files']:
        if f['path'].startswith(('data/imports/','data/device_files/')):
            assert hashlib.sha256((ROOT/f['path']).read_bytes()).hexdigest()==f['sha256'];report['original_files_preserved']+=1
    with sqlite3.connect(p) as old,sqlite3.connect('file:'+str(ROOT/'data/platform.sqlite3')+'?mode=ro',uri=True) as now:
        names=lambda db:{r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert names(old)==names(now)
        for table in sorted(names(old)-{'sqlite_sequence','django_session'}):
            before=old.execute('SELECT * FROM '+table+' ORDER BY rowid').fetchall();after=now.execute('SELECT * FROM '+table+' ORDER BY rowid').fetchall();lookup={r[0]:r for r in after}
            for row in before:assert lookup.get(row[0])==row,(table,'changed or removed prior record',row[0])
            if table!='app_auditevent':assert len(after)-len(before)==expected_additions.get(table,0),(table,len(before),len(after))
            else:report['audit_additions']=dict(Counter(r[1] for r in after[len(before):]))
            report['preserved_tables'][table]={'before':len(before),'after':len(after),'prior_rows_unchanged':True}

def projection(r):
    d=copy.deepcopy(r);d.pop('metric_receipt',None)
    for part in ['pivot','scatter']:
        if d.get(part):d[part].pop('revision',None)
    return json.loads(json.dumps(d,ensure_ascii=False,default=str))
admin=User.objects.get(username='demo_admin');prior=json.loads((ROOT/'data/targets_before.json').read_text())
for mid,before in prior.items():
    m=AnalysisModel.objects.get(pk=mid);assert projection(engine.run_analysis(admin,m.dataset,m.definition))==projection(before),mid
report['existing_model_results_preserved']=len(prior)
counts=(Record.objects.count(),Record.objects.values('dataset').distinct().count(),ImportBatch.objects.exclude(status='superseded').count(),AnalysisModel.objects.count(),Topic.objects.count(),TopicView.objects.count(),TopicSnapshot.objects.count())
assert counts==(116297,76,21,52,21,6,4),counts
report['counts']=dict(zip(['records','datasets','active_workbooks','models','topics','views','snapshots'],counts))
v=MetricVersion.objects.get(metric__key='DELIVERY_OTIF',version=8,status='published');assert v.calculation_hash==registry.calculation_hash(v.metric.dataset);report['published_metric_unchanged']={'version':v.version,'hash':v.calculation_hash}
raw=defaultdict(dict)
for ds,row in Record.objects.values_list('dataset','values'):raw[ds][row['id']]=row
from decimal import Decimal,ROUND_HALF_UP
from statistics import median
from datetime import timedelta
cutoff=datetime(2026,10,1,18);cutoff_text=cutoff.isoformat();calc=k.Targets(admin)
# Independent first complete test selection from raw specs and measurements.
ms=defaultdict(list);required=defaultdict(set);complete=defaultdict(list)
for spec in raw['test_specs'].values():
    if spec['mandatory']:required[(spec['product_id'],spec['version'])].add(spec['id'])
for m in raw['measurements'].values():ms[m['session_id']].append(m)
for session in raw['test_sessions'].values():
    if session['voided'] or session['tested']>cutoff_text:continue
    pid=raw['units'][session['unit_id']]['product_id'];needed=required[(pid,session['spec_version'])];measurements=ms[session['id']];ids=[m['spec_id'] for m in measurements]
    if not needed or not needed.issubset(ids) or len(ids)!=len(set(ids)):continue
    passed=True;valid=True
    for m in measurements:
        spec=raw['test_specs'].get(m['spec_id'])
        if not spec or (spec['product_id'],spec['version'],spec['unit'])!=(pid,session['spec_version'],m['unit']):valid=False;break
        passed&=(spec['lsl'] is None or m['value']>=spec['lsl']) and (spec['usl'] is None or m['value']<=spec['usl'])
    if valid:complete[session['unit_id']].append((session['tested'],session['attempt'],session['id'],passed))
first={uid:sorted(ss)[0][-1] for uid,ss in complete.items()}

def overlaps(start,end,lo,hi):
    a=max(datetime.fromisoformat(start),lo);b=min(datetime.fromisoformat(end),hi,cutoff)
    return (a,b) if b>a else None

def downtime_hours(lo,hi):
    groups=defaultdict(list)
    for r in raw['downtime'].values():
        part=overlaps(r['started'],r['finished'],lo,hi)
        if part:groups[r['equipment_id']].append(part)
    seconds=0
    for intervals in groups.values():
        merged=[]
        for a,b in sorted(intervals):
            if merged and a<=merged[-1][1]:merged[-1]=(merged[-1][0],max(merged[-1][1],b))
            else:merged.append((a,b))
        seconds+=sum((b-a).total_seconds() for a,b in merged)
    return seconds/3600

def energy_yuan(lo,hi):
    groups=defaultdict(Decimal)
    for r in raw['energy'].values():
        part=overlaps(r['started'],r['ended'],lo,hi)
        if not part:continue
        # Generator spans at most two days; preserve per-shop/day half-up cents.
        a,b=part;duration=Decimal(str((datetime.fromisoformat(r['ended'])-datetime.fromisoformat(r['started'])).total_seconds()))
        while a<b:
            next_day=datetime.combine(a.date()+timedelta(days=1),datetime.min.time());stop=min(b,next_day)
            groups[(r['workshop'],a.date())]+=Decimal(str(r['kwh']))*Decimal(str((stop-a).total_seconds()))/duration*r['tariff_cents'];a=stop
    return float(sum(x.quantize(Decimal('1'),rounding=ROUND_HALF_UP) for x in groups.values())/100)

checks=[]
for t in raw['kpi_targets'].values():
    r=calc.detail(t['id'])
    if r['state']=='blocked':assert r['actual'] is None;continue
    lo=datetime.fromisoformat(t['period_start']);hi=datetime.fromisoformat(t['period_end'])+timedelta(days=1)
    if lo>cutoff:expected=None
    elif t['model_id'] in [5,31]:
        cohort=[u for u in raw['units'].values() if lo<=datetime.fromisoformat(u['assembly_at'])<hi and u['assembly_at']<=cutoff_text]
        if t['model_id']==5:expected=len(cohort) if cohort else None
        else:
            tested=[first[u['id']] for u in cohort if u['id'] in first];expected=sum(tested)/len(tested)*100 if tested else None
    elif t['model_id']==52:
        v=[r['minutes'] for r in raw['labor_entries'].values() if lo<=datetime.fromisoformat(r['started'])<hi and r['started']<=cutoff_text];expected=median(v) if v else None
    elif t['model_id']==39:expected=downtime_hours(lo,hi)
    elif t['model_id']==40:expected=energy_yuan(lo,hi)
    elif t['model_id']==20:expected=sum(r['net_cents'] for r in raw['invoices'].values() if t['period_start']<=r['issued']<=min(t['period_end'],'2026-10-01'))/100
    elif t['model_id']==44:
        lines={x['id'] for x in raw['order_lines'].values() if t['period_start']<=raw['orders'][x['order_id']]['order_date']<=t['period_end']}
        plans=[p for p in raw['delivery_plans'].values() if p['order_line_id'] in lines and p['due']<'2026-10-01'];passed=0
        for p in plans:
            qty=sum(s['qty'] for s in raw['shipments'].values() if s['delivery_plan_id']==p['id'] and s['shipped']<=cutoff_text and s['shipped'][:10]<=p['due']);passed+=qty>=p['qty']
        expected=passed/len(plans)*100 if plans else None
    else:raise AssertionError(t['model_id'])
    assert (r['actual'] is None and expected is None) or (r['actual'] is not None and expected is not None and abs(r['actual']-expected)<1e-7),(t['id'],r['actual'],expected)
    if expected is not None:
        gap=max(t['lower']-expected,0) if t['direction']=='gte' else max(expected-t['upper'],0) if t['direction']=='lte' else max(t['lower']-expected,expected-t['upper'],0)
        assert abs(r['gap']-gap)<1e-7
        if r['candidate_state']:assert r['state']==('met' if gap==0 else 'watch' if gap<=t['warning_margin'] else 'missed')
    checks.append({'id':t['id'],'actual':expected,'state':r['state']})
summary=k.summary(calc.selected(k.params({})));assert summary==json.loads((ROOT/'data/targets_import_rehearsal.json').read_text())['summary']
report['independent_targets']=checks;report['summary']=summary
source_keys=set()
for t in calc.targets.values():
    if calc.detail(t['id'])['state']=='blocked':continue
    for row in calc.calculate(t)['rows']:
        refs=row.get('_sources') or [{'dataset':calc.detail(t['id'])['dataset'],'key':row['id']}]
        source_keys.update((s['dataset'],s['key']) for s in refs)
assert all(key in raw[ds] for ds,key in source_keys);report['linked_source_records_verified']=len(source_keys)
download=ROOT/'outputs/BI经营目标_当前范围.csv';exported=list(csv.reader(io.StringIO(download.read_text(encoding='utf-8-sig'))));rows=calc.selected(k.params({}));to_text=lambda v:'' if v is None else str(v)
assert exported[4]==[v for _,v in FIELDS]+['状态','核对事项'];assert exported[5:]==[[to_text(r.get(field)) for field,_ in FIELDS]+[k.STATES[r['state']],'；'.join(r['issues'])] for r in rows]
report['download_reconciled_rows']=len(rows);report['snapshots']=[{'id':str(s.pk),'sha256':s.payload_hash} for s in TopicSnapshot.objects.all()]
(ROOT/'data/targets_validation.json').write_text(json.dumps(report,ensure_ascii=False,indent=2,default=str));print(json.dumps({k:v for k,v in report.items() if k not in ['preserved_tables','independent_targets']},ensure_ascii=False,default=str))
