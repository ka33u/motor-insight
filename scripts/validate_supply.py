"""Reconcile the supply workspace with immutable imported synthetic records."""
import os,sys,json,hashlib,zipfile,tempfile,sqlite3,csv
from pathlib import Path
from decimal import Decimal
from collections import defaultdict
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings')
import django
django.setup()
from django.contrib.auth.models import User
from app import analytics,supply,metric_registry,trace_cases
from app.analysis_engine import run_analysis
from app.models import Record,AnalysisModel,Topic,TraceCase,MetricVersion,IssueDisposition,AuditEvent,ImportBatch

h=hashlib.sha256()
for r in Record.objects.order_by('dataset','business_key').values_list('dataset','business_key','values','revision','source_row_id').iterator():h.update(json.dumps(r,sort_keys=True,ensure_ascii=False).encode())
assert h.hexdigest()=='576ad9668e112e407eb81b9d3f58fa150f5753f7ede1fe43b2919ed4a1ec2a72'
baseline=ROOT/'data/backups/motor-backup-20261003-125603.zip'
with zipfile.ZipFile(baseline) as z,tempfile.TemporaryDirectory(prefix='supply-before-') as tmp:
    p=Path(tmp)/'before.sqlite3';p.write_bytes(z.read('data/platform.sqlite3'))
    with sqlite3.connect(p) as db:
        models=list(db.execute('select id,name,dataset,definition,version,owner,is_public from app_analysismodel'))
        topics=list(db.execute('select id,name,description,layout,filters,version,owner,is_public from app_topic'))
    for pk,name,ds,definition,version,owner,public in models:
        m=AnalysisModel.objects.get(pk=pk);assert (m.name,m.dataset,m.definition,m.version,m.owner,m.is_public)==(name,ds,json.loads(definition),version,owner,bool(public))
    for pk,name,description,layout,filters,version,owner,public in topics:
        t=Topic.objects.get(pk=pk);assert (t.name,t.description,t.layout,t.filters,t.version,t.owner,t.is_public)==(name,description,json.loads(layout),json.loads(filters),version,owner,bool(public))
assert AnalysisModel.objects.count()==len(models)==44 and Topic.objects.count()==len(topics)==15

d=analytics.tables();balances=defaultdict(Decimal);unit_totals=defaultdict(Decimal);materials={m['id']:m for m in d['materials']}
for r in d['inventory_opening']:
    if r['as_of']<=analytics.DAY:balances[(r['material_id'],r['lot'],r['location'])]+=Decimal(str(r['qty']))
for r in d['inventory_movements']:
    if r['occurred']<=analytics.AS_OF:balances[(r['material_id'],r['lot'],r['location'])]+=Decimal(str(r['qty_signed']))
data=supply.current();assert not data.global_issues and len(data.lots)==len(balances)==173
for l in data.lots:assert Decimal(str(l['balance_qty']))==balances[l['material_id'],l['lot'],l['location']] and not l['issues']
for (mid,_,_),qty in balances.items():unit_totals[materials[mid]['unit']]+=qty
assert dict(unit_totals)=={'kg':Decimal('93192.400'),'件':Decimal('11540')}
raw_receipts=[r for r in d['receipts'] if r['received']<=analytics.AS_OF];by_po=defaultdict(list)
for r in raw_receipts:by_po[r['purchase_line_id']].append(r)
due=[p for p in d['purchase_lines'] if p['ordered']<=analytics.DAY and p['due']<analytics.DAY]
remaining={p['id'] for p in due if sum(Decimal(str(r['qty'])) for r in by_po[p['id']])<Decimal(str(p['qty']))}
ontime={p['id'] for p in due if sum(Decimal(str(r['qty'])) for r in by_po[p['id']] if r['received'][:10]<=p['due'])>=Decimal(str(p['qty']))}
assert len(due)==144 and len(remaining)==11 and len(ontime)==114
assert remaining=={p['id'] for p in data.po_rows if 'overdue' in p['flags']}
assert ontime=={p['id'] for p in data.po_rows if p['ontime_count']}
inspections=defaultdict(list)
for q in d['incoming_inspections']:
    if q['inspected']<=analytics.AS_OF:inspections[q['receipt_id']].append(q)
approved=set();isolated=set()
for r in raw_receipts:
    q=max(inspections[r['id']],key=lambda q:(q['inspected'],q['id']))
    if r['status']=='检验合格' and q['result']=='合格' and q['disposition']=='批准入库':approved.add(r['id'])
    else:isolated.add(r['id'])
assert len(approved)==125 and len(isolated)==8
posted={m['reference'] for m in d['inventory_movements'] if m['movement']=='采购入库' and m['occurred']<=analytics.AS_OF}
assert approved==posted and not (isolated&posted)
assert len([p for p in data.po_rows if 'quality' in p['flags']])==8
lot=next(l for l in data.lots if l['material_id']=='04.02.0006' and l['lot']=='RM2608310048')
assert lot['opening_qty']==700 and lot['outbound_qty']==203.406 and lot['balance_qty']==496.594
assert lot['_timeline'][0]['id']=='ZT260918-00001' and all(r['state']=='可用' for r in lot['_timeline'])
assert all(r['occurred']>'2026-09-18T07:30:00' for r in lot['_moves'])
key='supply:purchase:PO2609-00013-01';note=IssueDisposition.objects.get(key=key)
assert (note.version,note.status,note.updated_by)==(1,'催交中','demo_admin')
assert AuditEvent.objects.filter(action='supply.followup',object_id=key).count()==1
p=data.po_index['PO2609-00013-01'];assert p['due']=='2026-09-17' and p['remaining_qty']==1000 and p['received_qty']==0
manifest=trace_cases.capture_sources(data.detail('purchase','PO2609-00017-01'))
assert len(manifest)==5 and all(not r.get('missing') and r['row']>=2 for r in manifest)
files={r['batch_id']:r['file_hash'] for r in manifest}
for b in ImportBatch.objects.filter(pk__in=files):assert hashlib.sha256(Path(b.file_path).read_bytes()).hexdigest()==files[str(b.pk)]
case=TraceCase.objects.get(code='PC-20261003-00001')
assert case.snapshot_hash==trace_cases.digest(case.snapshot)=='56716d7300dd607c19dfe67a008a159cfadb0d3c0f826d76421c75342c4cad89'
assert IssueDisposition.objects.get(key='quality:M260921000097').version==1
v=MetricVersion.objects.select_related('metric').get(metric__key='DELIVERY_OTIF',version=2)
assert v.status=='published' and v.calculation_hash==metric_registry.calculation_hash(v.metric.dataset)
run_analysis(User.objects.get(username='demo_operations'),'bi_order_lines',AnalysisModel.objects.get(pk=44).definition)
evidence={'business_records':Record.objects.count(),'business_sha256':h.hexdigest(),'business_facts_unchanged':True,'unchanged_models':len(models),'unchanged_topics':len(topics),'prior_case_hash':case.snapshot_hash,'published_metric_valid':'DELIVERY_OTIF v2','stock':supply.summary(data.stock_rows,'stock'),'purchase':supply.summary(data.po_rows,'purchase'),'independent_balance_by_unit':{k:str(v) for k,v in unit_totals.items()},'receipts_approved':len(approved),'receipts_unapproved':len(isolated),'posted_receipt_count':len(posted),'isolated_receipts_not_in_stock':True,'freeze_release_example':supply.clean(lot),'follow_up':{'key':key,'version':note.version,'status':note.status,'business_due_unchanged':p['due']},'verified_source_refs':len(manifest),'verified_source_files':len(files),'tests_passed':163,'baseline_backup':str(baseline.relative_to(ROOT)),'scope':'Synthetic Excel facts only; no reservation/ATP/MRP, historical valuation, actual purchase or quality approval, or ERP/MES writes.'}
evidence['browser_checks']=['stock totals 48 materials / 173 material-lot-locations','kg and pieces remain separate','purchase 144 lines / 133 receipts / 11 overdue / 8 quality pending / 114 of 144 on time','isolated receipt DH2609-00017: 1000kg received, zero approved and posted; IQC Excel row 17','11 overdue lines exported from actual browser link','PO2609-00013-01 coordination persisted v1; original due and zero received retained','frozen opening 700kg then unlock 07:30 before 08:00 issues, ending 496.594kg','empty query zero results; reset returns 48','390px page width 390; dialog 356; content 354; console errors none']
evidence['screenshots']=['outputs/库存与物料保障.png','outputs/采购与来料工作台.png','outputs/采购催交证据.png','outputs/库存收发与状态流水.png']
if len(sys.argv)>1:
    path=Path(sys.argv[1]).resolve()
    with zipfile.ZipFile(path) as z,tempfile.TemporaryDirectory(prefix='supply-restore-') as tmp:
        listed=json.loads(z.read('manifest.json'))['files']
        for f in listed:
            blob=z.read(f['path']);assert len(blob)==f['size'] and hashlib.sha256(blob).hexdigest()==f['sha256']
        p=Path(tmp)/'restore.sqlite3';p.write_bytes(z.read('data/platform.sqlite3'))
        with sqlite3.connect(p) as db:
            assert db.execute('pragma integrity_check').fetchone()[0]=='ok'
            assert db.execute('select count(*) from app_record').fetchone()[0]==106838
            assert db.execute('select status,version from app_issuedisposition where key=?',(key,)).fetchone()==('催交中',1)
            assert db.execute('select snapshot_hash from app_tracecase where code=?',(case.code,)).fetchone()[0]==case.snapshot_hash
    evidence['verified_backup']={'path':str(path.relative_to(ROOT)),'files':len(listed),'all_hashes_match':True,'sqlite_integrity':'ok','coordination_restored':True}
(ROOT/'data/supply_validation.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2))
print(json.dumps({k:evidence[k] for k in ['business_records','business_facts_unchanged','stock','purchase','independent_balance_by_unit','follow_up']},ensure_ascii=False))
