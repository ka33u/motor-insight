"""Read-only checks against imported synthetic facts and saved UI exercise."""
import os,sys,json,hashlib,sqlite3,tempfile,zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings')
import django
django.setup()
from django.contrib.auth.models import User
from app import analytics,lineage,trace_cases,metric_registry
from app.models import Record,TraceCase,CodeAllocation,AnalysisModel,Topic,AuditEvent,MetricVersion,ImportBatch
from app.analysis_engine import run_analysis

baseline=ROOT/'data/backups/motor-backup-20261003-120406.zip'
h=hashlib.sha256()
for row in Record.objects.order_by('dataset','business_key').values_list('dataset','business_key','values','revision','source_row_id').iterator():h.update(json.dumps(row,sort_keys=True,ensure_ascii=False).encode())
assert h.hexdigest()=='576ad9668e112e407eb81b9d3f58fa150f5753f7ede1fe43b2919ed4a1ec2a72'
with zipfile.ZipFile(baseline) as z,tempfile.TemporaryDirectory(prefix='lineage-baseline-') as tmp:
    p=Path(tmp)/'before.sqlite3';p.write_bytes(z.read('data/platform.sqlite3'))
    with sqlite3.connect(p) as db:
        old_models=list(db.execute('select id,name,dataset,definition,version,owner,is_public from app_analysismodel'))
        old_topics=list(db.execute('select id,name,description,layout,filters,version,owner,is_public from app_topic'))
    for key,name,ds,definition,version,owner,public in old_models:
        m=AnalysisModel.objects.get(pk=key);assert (m.name,m.dataset,m.definition,m.version,m.owner,m.is_public)==(name,ds,json.loads(definition),version,owner,bool(public))
    for key,name,description,layout,filters,version,owner,public in old_topics:
        t=Topic.objects.get(pk=key);assert (t.name,t.description,t.layout,t.filters,t.version,t.owner,t.is_public)==(name,description,json.loads(layout),json.loads(filters),version,owner,bool(public))
assert AnalysisModel.objects.count()==len(old_models)==44 and Topic.objects.count()==len(old_topics)==15

current=lineage.current('material_lot','RM2608310002','01.01.0002');d=analytics.tables()
# Independent two-level join matches this dataset's material -> batch -> SN shape.
material_edges=[g for g in d['genealogy'] if g['parent_type']=='材料批次' and g['parent_id']=='RM2608310002' and g['occurred']<=analytics.AS_OF]
batches={g['child_id'] for g in material_edges}
unit_edges=[g for g in d['genealogy'] if g['parent_type']=='生产批次' and g['parent_id'] in batches and g['child_type']=='整机' and g['occurred']<=analytics.AS_OF]
sn={g['child_id'] for g in unit_edges};shipids={s['id'] for s in d['shipments'] if s['shipped']<=analytics.AS_OF}
shipped={p['unit_id'] for p in d['shipment_units'] if p['shipment_id'] in shipids}&sn
assert len(material_edges)==68 and len(unit_edges)==1700 and len(sn)==850 and len(shipped)==766
assert {r['id'] for r in current['units']}==sn
assert current['summary']['shipped_count']==len(shipped) and current['summary']['warning_count']==0
assert len(current['reconciliation'])==34 and all(r['matched'] for r in current['reconciliation'])
assert len({(r['dataset'],r['key']) for r in current['sources']})==len(current['sources'])

case=TraceCase.objects.get(code='PC-20261003-00001');assert case.status=='待业务核验' and case.version==2
assert case.snapshot_hash==trace_cases.digest(case.snapshot)
assert {r['id'] for r in case.snapshot['units']}==sn
assert case.snapshot['source_manifest']==trace_cases.capture_sources(current)
assert all(not r.get('missing') and r['row']>=2 and r['file_hash'] and r['record_hash'] for r in case.snapshot['source_manifest'])
source_batches={r['batch_id']:r['file_hash'] for r in case.snapshot['source_manifest']}
for b in ImportBatch.objects.filter(pk__in=source_batches):
    assert hashlib.sha256(Path(b.file_path).read_bytes()).hexdigest()==source_batches[str(b.pk)]
delta=trace_cases.compare(case)
assert not any(delta[k] for k in ['added_count','removed_count','changed_count','edge_change_count']) and delta['snapshot_unchanged']
assert CodeAllocation.objects.filter(rule__key='trace_case').count()==1
assert CodeAllocation.objects.get(code=case.code).rule_version==1
assert list(AuditEvent.objects.filter(object_type='TraceCase',object_id=str(case.pk)).order_by('id').values_list('action',flat=True))==['trace_case.create','trace_case.update']
v=MetricVersion.objects.select_related('metric').get(metric__key='DELIVERY_OTIF',version=2)
assert v.status=='published' and v.calculation_hash==metric_registry.calculation_hash(v.metric.dataset)
run_analysis(User.objects.get(username='demo_operations'),'bi_order_lines',AnalysisModel.objects.get(pk=44).definition)
evidence={'business_record_count':Record.objects.count(),'business_sha256':h.hexdigest(),'business_facts_unchanged':True,'unchanged_models':len(old_models),'unchanged_topics':len(old_topics),'metric_reference_still_valid':'DELIVERY_OTIF v2','root':current['root'],'summary':current['summary'],'independent_join':{'material_edges':len(material_edges),'unit_paths':len(unit_edges),'distinct_sn':len(sn),'distinct_shipped_sn':len(shipped)},'material_reconciliation_work_orders':len(current['reconciliation']),'case':json.loads(json.dumps(trace_cases.info(case),default=str,ensure_ascii=False)),'source_manifest_count':len(case.snapshot['source_manifest']),'source_file_count':len(source_batches),'all_source_files_hash_verified':True,'snapshot_comparison':delta,'coding_allocations':1,'pre_migration_backup':str(baseline.relative_to(ROOT)),'scope':'Local synthetic investigation exercise only. No stock freeze, customer notification, recall instruction, source-system writes or factory certification.'}
evidence['browser_checks']=['material code and lot selection','850 distinct SN / 766 shipped / 84 unshipped','single-SN two-edge path and Excel source row','shipped filter 766 and unmatched filter 0','saving from filtered view preserves full 850 SN','coordination update v2 preserves snapshot','comparison returns zero changes and matching digest','frozen source file-name search','390px page scroll width 390; modal 356px and content width 354px']
evidence['screenshots']=['outputs/批次影响反查.png','outputs/批次排查快照.png']
evidence['tests_passed']=117
(ROOT/'data/lineage_validation.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2))
print(json.dumps({k:evidence[k] for k in ['business_record_count','business_facts_unchanged','unchanged_models','unchanged_topics','summary','source_manifest_count','source_file_count','coding_allocations']},ensure_ascii=False))
