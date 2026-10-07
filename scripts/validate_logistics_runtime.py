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
from app import analysis_engine as engine,metric_registry as registry,logistics as lg
from app.logistics_views import FIELDS
connection.cursor().execute('PRAGMA query_only=ON')
backup=ROOT/'data/backups/motor-backup-20261004-204858.zip';report={'synthetic':True,'baseline':str(backup),'preserved_tables':{}}
expected_additions={'app_record':4951,'app_importrow':4951,'app_importbatch':1,'app_issuedisposition':1}
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
admin=User.objects.get(username='demo_admin');prior=json.loads((ROOT/'data/logistics_before.json').read_text())
for mid,before in prior.items():
    m=AnalysisModel.objects.get(pk=mid);assert projection(engine.run_analysis(admin,m.dataset,m.definition))==projection(before),mid
report['existing_model_results_preserved']=len(prior)
counts=(Record.objects.count(),Record.objects.values('dataset').distinct().count(),ImportBatch.objects.exclude(status='superseded').count(),AnalysisModel.objects.count(),Topic.objects.count(),TopicView.objects.count(),TopicSnapshot.objects.count())
assert counts==(116235,74,20,52,21,6,4),counts
report['counts']=dict(zip(['records','datasets','active_workbooks','models','topics','views','snapshots'],counts))
v=MetricVersion.objects.get(metric__key='DELIVERY_OTIF',version=8,status='published');assert v.calculation_hash==registry.calculation_hash(v.metric.dataset);report['published_metric_unchanged']={'version':v.version,'hash':v.calculation_hash}
raw=defaultdict(dict)
for ds,row in Record.objects.values_list('dataset','values'):raw[ds][row['id']]=row
packed=defaultdict(set)
for r in raw['shipment_units'].values():packed[r['shipment_id']].add(r['unit_id'])
accepted=defaultdict(set);refused=defaultdict(set);times=defaultdict(list);excluded=0
cutoff=datetime(2026,10,1,18)
for r in raw['customer_receipt_units'].values():
    h=raw['customer_receipts'][r['receipt_id']];dispatch=raw['transport_dispatches'][h['dispatch_id']];sid=dispatch['shipment_id'];t=datetime.fromisoformat(h['received'])
    if h['voided'] or t>cutoff:excluded+=1;continue
    assert h['document'] and h['receiver'] and r['unit_id'] in packed[sid]
    if r['outcome']=='接收':accepted[sid].add(r['unit_id']);times[sid].append(t)
    else:assert r['outcome']=='拒收';refused[sid].add(r['unit_id'])
dispatch={d['shipment_id']:d for d in raw['transport_dispatches'].values()};calc=lg.current();due_count=on_time=0
for sid,s in raw['shipments'].items():
    r=calc.detail(sid);d=dispatch[sid];pending=packed[sid]-accepted[sid]-refused[sid]
    assert not accepted[sid]&refused[sid];assert s['qty']==len(packed[sid]);assert (r['accepted'],r['refused'],r['pending'])==(len(accepted[sid]),len(refused[sid]),len(pending))
    full=max(times[sid]).isoformat() if accepted[sid]==packed[sid] else None;assert r['full_received']==full
    promise=datetime.fromisoformat(d['promised']) if d['promised'] else None;hand=datetime.fromisoformat(d['handed']) if d['handed'] else None
    due=bool(hand and promise and d['reference'] and datetime.fromisoformat(s['shipped'])<=hand<=cutoff and hand<=promise<=cutoff);assert r['due']==due
    if due:
        due_count+=1;timely=bool(full and datetime.fromisoformat(full)<=promise);on_time+=timely;assert r['on_time']==timely
    else:assert r['on_time'] is None
summary=lg.summary(list(calc.rows.values()));assert (due_count,on_time)==(178,66);assert excluded==sum(r['excluded_units'] for r in calc.rows.values());assert not calc.global_issues
source_keys={(r['dataset'],r['key']) for row in calc.rows.values() for r in row['sources']}
assert all(key in raw[ds] for ds,key in source_keys)
report['linked_source_records_verified']=len(source_keys)
report['independent_reconciliation']={'shipment_rows':222,'packed_sn':sum(map(len,packed.values())),'accepted':sum(map(len,accepted.values())),'refused':sum(map(len,refused.values())),'pending':sum(len(packed[k]-accepted[k]-refused[k]) for k in packed),'excluded_receipt_lines':excluded,'due_rows':due_count,'on_time_rows':on_time,'summary':summary}
download=ROOT/'outputs/BI发运签收_模拟物流甲.csv'
assert download.exists();exported=list(csv.reader(io.StringIO(download.read_text(encoding='utf-8-sig'))));f=lg.params({'carrier':'模拟物流甲'});selected=calc.selected(f)
to_text=lambda v:'' if v is None else str(v)
assert exported[4]==[v for _,v in FIELDS]+['核对事项']
assert exported[5:]==[[to_text(r.get(k)) for k,_ in FIELDS]+['；'.join(r['issues'])] for r in selected]
report['download_reconciled_rows']=len(selected)
report['snapshots']=[{'id':str(s.pk),'sha256':s.payload_hash} for s in TopicSnapshot.objects.all()]
(ROOT/'data/logistics_validation.json').write_text(json.dumps(report,ensure_ascii=False,indent=2,default=str))
print(json.dumps({k:v for k,v in report.items() if k!='preserved_tables'},ensure_ascii=False,default=str))
