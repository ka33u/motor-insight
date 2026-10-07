"""Reconcile the synthetic device-file acceptance run against originals and imported facts."""
import os,sys,json,csv,hashlib,sqlite3,tempfile,zipfile,copy
from collections import Counter,defaultdict
from decimal import Decimal
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings')
import django;django.setup()
from app.models import Record,DeviceFile,DeviceFileReview,MetricVersion
from app import metric_registry
BASE=ROOT/'data/backups/motor-backup-20261003-163638.zip'
def digest(v):return hashlib.sha256(json.dumps(v,ensure_ascii=False,sort_keys=True,default=str).encode()).hexdigest()
with zipfile.ZipFile(BASE) as z,tempfile.TemporaryDirectory() as tmp:
    manifest=json.loads(z.read('manifest.json'))
    for entry in manifest['files']:
        if entry['path'].startswith('data/imports/'):assert hashlib.sha256((ROOT/entry['path']).read_bytes()).hexdigest()==entry['sha256']
    p=Path(tmp)/'before.sqlite3';p.write_bytes(z.read('data/platform.sqlite3'))
    with sqlite3.connect(p) as old,sqlite3.connect(ROOT/'data/platform.sqlite3') as now:
        tables=[r[0] for r in old.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'app_%'")]
        for table in tables:
            before=list(old.execute(f'SELECT * FROM {table} ORDER BY id'))
            after=list(now.execute(f'SELECT * FROM {table}'+(' WHERE id<=?' if table=='app_auditevent' else '')+' ORDER BY id',(before[-1][0],) if table=='app_auditevent' else ()))
            assert before==after,table
    old_design=json.loads(z.read('data/bi_design.json'));design=json.loads((ROOT/'data/bi_design.json').read_text());cleaned=copy.deepcopy(design)
    for dom in cleaned['domains']:
        for item in dom['items']:
            if item['id'] in ['N-01','N-03','N-07','W-02']:
                prior=next(i for d in old_design['domains'] for i in d['items'] if i['id']==item['id']);item.update({k:prior[k] for k in ['gap','implementation']})
    for page in cleaned['page_blueprints']:
        if page['id'] in ['P05','P06']:page['status']=next(p for p in old_design['page_blueprints'] if p['id']==page['id'])['status']
    cleaned['framework']['surfaces']=[s for s in cleaned['framework']['surfaces'] if s['href']!='#device-files']
    for s in cleaned['framework']['surfaces']:
        if s['href'] in ['#trace','#quality']:s['status']=next(x for x in old_design['framework']['surfaces'] if x['href']==s['href'])['status']
    assert cleaned==old_design

h=hashlib.sha256()
for row in Record.objects.order_by('dataset','business_key').values_list('dataset','business_key','values','revision','source_row_id').iterator():h.update(json.dumps(row,ensure_ascii=False,sort_keys=True).encode())
assert Record.objects.count()==106838 and h.hexdigest()=='576ad9668e112e407eb81b9d3f58fa150f5753f7ede1fe43b2919ed4a1ec2a72'
v3=MetricVersion.objects.select_related('metric').get(metric__key='DELIVERY_OTIF',version=3);assert v3.status=='published' and v3.calculation_hash==metric_registry.calculation_hash(v3.metric.dataset)
records={(r.dataset,r.business_key):r for r in Record.objects.filter(dataset__in=['products','units','work_orders','test_sessions','measurements','test_specs','equipment','allocations','shipment_units','shipments','orders','order_lines']).select_related('source_row__batch')}
files=list(DeviceFile.objects.select_related('owner').order_by('created_at'));assert len(files)==3 and DeviceFileReview.objects.count()==5
samples=json.loads((ROOT/'outputs/device_samples/manifest.json').read_text());samplefiles={f['name']:f for f in samples['files']};report_files=[];source_files={};reviews_count=0
for f in files:
    raw=(ROOT/'data/device_files'/f'{f.pk}.bin').read_bytes();original=(ROOT/'outputs/device_samples'/f.filename).read_bytes()
    assert f.owner.username=='demo_admin' and raw==original and len(raw)==f.size
    assert hashlib.sha256(raw).hexdigest()==f.file_hash==samplefiles[f.filename]['sha256']
    meta={k:getattr(f,k) for k in ['filename','kind','size','file_hash','note','parsed','owner_id','request_hash']}|{'request_id':str(f.request_id),'id':str(f.pk)}
    assert digest(meta)==f.metadata_hash
    events=list(f.reviews.order_by('version'));latest={};report_reviews=[]
    for i,r in enumerate(events,1):
        p=r.payload;assert digest(p)==r.payload_hash and p['version']==r.version==i and p['file_id']==str(f.pk) and p['file_hash']==f.file_hash
        assert p['request_id']==str(r.request_id) and p['action']==r.action and p['session_id']==r.session_id
        t=p['target'];assert digest(t)==p['target_hash'];s=records['test_sessions',r.session_id].values;u=records['units',s['unit_id']].values;w=records['work_orders',u['work_order_id']].values
        for field in ['session_id','unit_id','work_order_id','product_id','equipment_id','tested','spec_version','result']:
            expected=s['id'] if field=='session_id' else w['id'] if field=='work_order_id' else u['product_id'] if field=='product_id' else s[field]
            assert t[field]==expected,(field,t[field],expected)
        ms=[r.values for (ds,_),r in records.items() if ds=='measurements' and r.values['session_id']==s['id']]
        assert {m['id'] for m in t['measurements']}=={m['id'] for m in ms}
        for m in t['measurements']:
            actual=records['measurements',m['id']].values;assert all(m[k]==actual[k] for k in m)
        candidate={r.values['order_line_id'] for (ds,_),r in records.items() if ds=='allocations' and r.values['work_order_id']==w['id'] and r.values['effective']<='2026-10-01' and r.values['qty']>0}
        shipments=set()
        for (ds,_),sr in records.items():
            if ds=='shipment_units' and sr.values['unit_id']==u['id']:
                ship=records['shipments',sr.values['shipment_id']].values
                if ship['shipped']<='2026-10-01T18:00:00':shipments.add(ship['order_line_id'])
        assert t['candidate_order_lines']==sorted(candidate|shipments)
        assert t['order_lines']==sorted(shipments if len(shipments)==1 else candidate if not shipments and len(candidate)==1 else [])
        assert ('装箱' in t['ownership'])==bool(shipments)
        for key,source in t['sources'].items():
            assert key==digest([source['dataset'],source['key']]);record=records[source['dataset'],source['key']];row=record.source_row;batch=row.batch
            assert source['values']=={k:v for k,v in record.values.items() if 'cents' not in k}
            assert (source['revision'],source['hash'],source['filename'],source['file_hash'],source['sheet'],source['row'])==(record.revision,record.record_hash,batch.filename,batch.file_hash,row.sheet,row.row_number)
            source_files[batch.file_path]=batch.file_hash
        if f.kind=='csv':
            csvrows=list(csv.DictReader(raw.decode('utf-8-sig').splitlines()));rr=[v for v in csvrows if v['session_id']==s['id']]
            assert {v['measurement_id'] for v in rr}=={m['id'] for m in ms}
            for value in rr:
                measurement=records['measurements',value['measurement_id']].values
                for k,v in value.items():
                    expected=measurement['id'] if k=='measurement_id' else measurement[k] if k in ['spec_id','raw_value','raw_unit','value','unit','result'] else t[k]
                    assert Decimal(v)==Decimal(str(expected)) if k in ['raw_value','value'] else v==str(expected)
            assert p['comparison']['ok'] and len(p['comparison']['rows'])==len(rr)
        else:assert p['mode']=='manual' and p['comparison'] is None
        latest[r.session_id]=r;report_reviews.append({'version':r.version,'action':r.action,'session_id':r.session_id,'source_rows':len(t['sources']),'unit_id':t['unit_id'],'order_lines':t['order_lines'],'ownership':t['ownership'],'payload_hash':r.payload_hash})
    active=[r.session_id for r in latest.values() if r.action=='confirm'];reviews_count+=len(events)
    if f.filename.startswith('01_'):assert len(active)==3 and len(events)==3
    elif f.filename.startswith('02_'):assert not events and not active
    else:assert [r.action for r in events]==['confirm','revoke'] and not active
    report_files.append({'id':str(f.pk),'filename':f.filename,'sha256':f.file_hash,'bytes':f.size,'active_sessions':active,'reviews':report_reviews})
for path,sha in source_files.items():assert hashlib.sha256(Path(path).read_bytes()).hexdigest()==sha
good=files[0];download=(ROOT/'outputs/检测原件_浏览器下载.csv').read_bytes();assert hashlib.sha256(download).hexdigest()==good.file_hash
for name,f in [('检测原件_关联证据.json',files[0]),('检测补充记录_确认与撤销.json',files[2])]:
    exported=json.loads((ROOT/'outputs'/name).read_text());assert exported['file_hash']==f.file_hash and exported['id']==str(f.pk)
    assert len(exported['history'])==f.reviews.count()
    for record in exported['history']:
        stored=f.reviews.get(pk=record['id']);assert stored.payload==record['payload'] and record['payload_hash']==stored.payload_hash
    assert all(not p['source_changed'] for p in exported['current_previews'])
badrows=list(csv.DictReader((ROOT/'outputs/device_samples'/files[1].filename).open(encoding='utf-8-sig')))
assert badrows[0]['unit_id']=='M260921999999' and badrows[0]['raw_unit']=='错误单位'
assert Record.objects.get(dataset='test_sessions',business_key='TS260921-000097-01').values['result']=='不完整'
assert Record.objects.get(dataset='test_sessions',business_key='TS260921-000023-01').values['result']=='不合格'
report={'synthetic':True,'baseline':str(BASE.relative_to(ROOT)),'business_rows':106838,'business_sha256':h.hexdigest(),'preserved_tables':tables,'device_files':report_files,'reviews':reviews_count,'verified_source_workbooks':len(source_files),'browser_original_roundtrip':'byte-identical','browser_evidence_exports':2,'tests':316,'new_tests':28,'catalog_counts':dict(Counter(i['implementation'] for d in design['domains'] for i in d['items'])),'limits':'Synthetic exports derived from existing Excel facts, not real device originals. Files are private to uploader. Non-standard formats are manually associated without automatic content verification. Real device collection, report/curve parsing, cross-role authorization and customer evidence bundles remain unimplemented.'}
if len(sys.argv)>1:
    backup=Path(sys.argv[1]).resolve()
    with zipfile.ZipFile(backup) as z,tempfile.TemporaryDirectory() as tmp:
        manifest=json.loads(z.read('manifest.json'))
        for entry in manifest['files']:
            raw=z.read(entry['path']);assert hashlib.sha256(raw).hexdigest()==entry['sha256'] and len(raw)==entry['size']
        for f in files:assert hashlib.sha256(z.read('data/device_files/'+str(f.pk)+'.bin')).hexdigest()==f.file_hash
        p=Path(tmp)/'restored.sqlite3';p.write_bytes(z.read('data/platform.sqlite3'))
        with sqlite3.connect(p) as restored,sqlite3.connect(ROOT/'data/platform.sqlite3') as live:
            assert restored.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
            for table in [*tables,'app_devicefile','app_devicefilereview']:
                if table=='app_auditevent':continue
                assert list(restored.execute(f'SELECT * FROM {table} ORDER BY id'))==list(live.execute(f'SELECT * FROM {table} ORDER BY id')),table
    report['backup']={'path':str(backup.relative_to(ROOT)),'manifest_files':len(manifest['files']),'device_originals':len(files),'sqlite_integrity':'ok','critical_tables_match':True}
(ROOT/'data/device_files_validation.json').write_text(json.dumps(report,ensure_ascii=False,indent=2,default=str)+'\n')
print(json.dumps({k:v for k,v in report.items() if k not in ['preserved_tables','device_files','limits']},ensure_ascii=False,default=str))
