"""Read-only reconciliation of imported synthetic quality facts and UI exercise."""
import argparse,hashlib,json,math,os,sqlite3,sys,tempfile,zipfile
from collections import defaultdict
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings')
import django
django.setup()
from django.contrib.auth.models import User
from app import analytics,quality_board as quality,trace_cases,metric_registry
from app.models import Record,AnalysisModel,Topic,TraceCase,MetricVersion,IssueDisposition,AuditEvent,ImportBatch
from app.analysis_engine import run_analysis

parser=argparse.ArgumentParser();parser.add_argument('--backup',type=Path);args=parser.parse_args()
baseline=ROOT/'data/backups/motor-backup-20261003-123835.zip'
h=hashlib.sha256()
for row in Record.objects.order_by('dataset','business_key').values_list('dataset','business_key','values','revision','source_row_id').iterator():h.update(json.dumps(row,sort_keys=True,ensure_ascii=False).encode())
assert h.hexdigest()=='576ad9668e112e407eb81b9d3f58fa150f5753f7ede1fe43b2919ed4a1ec2a72'
with zipfile.ZipFile(baseline) as z,tempfile.TemporaryDirectory(prefix='quality-baseline-') as tmp:
    p=Path(tmp)/'before.sqlite3';p.write_bytes(z.read('data/platform.sqlite3'))
    with sqlite3.connect(p) as db:
        old_models=list(db.execute('select id,name,dataset,definition,version,owner,is_public from app_analysismodel'))
        old_topics=list(db.execute('select id,name,description,layout,filters,version,owner,is_public from app_topic'))
    for key,name,ds,definition,version,owner,public in old_models:
        m=AnalysisModel.objects.get(pk=key);assert (m.name,m.dataset,m.definition,m.version,m.owner,m.is_public)==(name,ds,json.loads(definition),version,owner,bool(public))
    for key,name,description,layout,filters,version,owner,public in old_topics:
        t=Topic.objects.get(pk=key);assert (t.name,t.description,t.layout,t.filters,t.version,t.owner,t.is_public)==(name,description,json.loads(layout),json.loads(filters),version,owner,bool(public))
assert AnalysisModel.objects.count()==len(old_models)==44 and Topic.objects.count()==len(old_topics)==15

# Recompute from raw specifications and measurement values, without quality_state.
d=analytics.tables();units={u['id']:u for u in d['units'] if u['assembly_at']<=analytics.AS_OF}
specs={s['id']:s for s in d['test_specs']};by_session=defaultdict(list);expected=defaultdict(set)
for sp in specs.values():
    assert sp['lsl'] is not None or sp['usl'] is not None
    assert all(v is None or math.isfinite(v) for v in [sp['lsl'],sp['usl']])
    assert sp['lsl'] is None or sp['usl'] is None or sp['lsl']<=sp['usl']
    if sp['mandatory']:expected[(sp['product_id'],sp['version'])].add(sp['id'])
for m in d['measurements']:by_session[m['session_id']].append(m)
sessions=defaultdict(list)
for s in d['test_sessions']:
    if s['voided'] or s['tested']>analytics.AS_OF or s['unit_id'] not in units:continue
    u=units[s['unit_id']];ms=by_session[s['id']];present={m['spec_id'] for m in ms};required=expected[u['product_id'],s['spec_version']]
    assert s['tested']>=u['assembly_at'] and len(present)==len(ms)
    complete=bool(required) and required<=present;passed=True
    for m in ms:
        sp=specs[m['spec_id']]
        assert sp['product_id']==u['product_id'] and sp['version']==s['spec_version']
        assert sp['effective']<=s['tested'][:10] and m['unit']==sp['unit'] and math.isfinite(m['value'])
        result=(sp['lsl'] is None or m['value']>=sp['lsl']) and (sp['usl'] is None or m['value']<=sp['usl'])
        assert m['result']==('合格' if result else '不合格');passed=passed and result
    result='不完整' if not complete else '合格' if passed else '不合格'
    assert s['complete']==complete and s['result']==result
    sessions[u['id']].append({**s,'complete':complete,'result':result})
for ss in sessions.values():ss.sort(key=lambda s:(s['tested'],s['attempt'],s['id']))
first={uid:ss[0] for uid,ss in sessions.items() if ss};latest={uid:ss[-1] for uid,ss in sessions.items() if ss}
fc={uid:next(s for s in ss if s['complete']) for uid,ss in sessions.items() if any(s['complete'] for s in ss)}
independent={'units':len(units),'tested':len(first),'complete':len(fc),'first_pass':sum(s['result']=='合格' for s in first.values()),'first_complete_pass':sum(s['result']=='合格' for s in fc.values()),'retested':sum(len(ss)>1 for ss in sessions.values())}
assert independent=={'units':4500,'tested':4345,'complete':4300,'first_pass':4040,'first_complete_pass':4040,'retested':209}
data=quality.current();summary=quality.summary(data.rows)
assert all(summary[k]==v for k,v in independent.items()) and not summary['rates_paused']
expected_lists={'untested':set(units)-set(first),'incomplete':{uid for uid,s in latest.items() if s['result']=='不完整'},'failed':{uid for uid,s in latest.items() if s['result']=='不合格'}}
for stage,ids in expected_lists.items():assert {r['id'] for r in quality.selected(data.rows,stage)}==ids
assert {k:len(v) for k,v in expected_lists.items()}=={'untested':155,'incomplete':45,'failed':73}
assert len(quality.selected(data.rows,'all','HV','missing'))==45

pid='CP.00008.A';sid='JC-CP.00008.A-R-A';cohort=[r for r in data.rows if r['product_id']==pid]
raw_ids={m['id'] for uid,s in fc.items() if units[uid]['product_id']==pid for m in by_session[s['id']] if m['spec_id']==sid}
dist=quality.distribution(data,cohort,pid,sid,'first_complete')
assert {m['id'] for m in dist['observations']}==raw_ids
assert dist['stats']['n']==dist['stats']['unique_units']==97 and dist['stats']['outside']==8
assert sum(b['count'] for b in dist['bins'])==97
all_dist=quality.distribution(data,cohort,pid,sid,'all_valid');last_dist=quality.distribution(data,cohort,pid,sid,'latest')
assert all_dist['stats']['n']==105 and all_dist['stats']['unique_units']==97
assert last_dist['stats']['n']==97 and last_dist['stats']['outside']==0
device=quality.distribution(data,cohort,pid,sid,'first_complete','SB-08-02');assert (device['stats']['n'],device['stats']['outside'])==(29,5)

uid='M260921000097';detail=data.detail(uid);note=IssueDisposition.objects.get(key='quality:'+uid)
assert (note.status,note.version,note.updated_by)==('待质量复核',1,'demo_admin')
assert detail['unit']['latest_result']=='不完整' and not detail['unit']['release_valid']
assert len(detail['sessions'])==1 and len(detail['sessions'][0]['measurements'])==7
assert [c['test_code'] for c in detail['sessions'][0]['cells'] if c['result']=='缺项']==['HV']
events=list(AuditEvent.objects.filter(action='quality.followup',object_id=uid));assert len(events)==1 and events[0].detail['business_facts_changed'] is False
manifest=trace_cases.capture_sources(detail)
assert len(manifest)==19 and all(not r.get('missing') and r['row']>=2 for r in manifest)
assert any(r['dataset']=='test_specs' and '-HV-' in r['key'] for r in manifest)
assert not any(r['dataset']=='measurements' and r['key'].endswith('-HV') for r in manifest)
files={r['batch_id']:r['file_hash'] for r in manifest}
for b in ImportBatch.objects.filter(pk__in=files):assert hashlib.sha256(Path(b.file_path).read_bytes()).hexdigest()==files[str(b.pk)]
case=TraceCase.objects.get(code='PC-20261003-00001')
assert case.snapshot_hash==trace_cases.digest(case.snapshot)=='56716d7300dd607c19dfe67a008a159cfadb0d3c0f826d76421c75342c4cad89'
assert case.version==2 and case.status=='待业务核验'
v=MetricVersion.objects.select_related('metric').get(metric__key='DELIVERY_OTIF',version=2)
assert v.status=='published' and v.calculation_hash==metric_registry.calculation_hash(v.metric.dataset)
run_analysis(User.objects.get(username='demo_operations'),'bi_order_lines',AnalysisModel.objects.get(pk=44).definition)

evidence={'business_records':Record.objects.count(),'business_sha256':h.hexdigest(),'business_facts_unchanged':True,'unchanged_models':len(old_models),'unchanged_topics':len(old_topics),'metric_reference_valid':'DELIVERY_OTIF v2','prior_case_snapshot_unchanged':case.snapshot_hash,'raw_counts':{k:len(d[k]) for k in ['test_specs','test_sessions','measurements','nonconformities']},'independent_summary':independent,'summary':summary,'latest_status_counts':{k:len(v) for k,v in expected_lists.items()},'distribution':{'product_id':pid,'spec_id':sid,'first_complete':dist['stats'],'all_valid':all_dist['stats'],'latest':last_dist['stats'],'device_SB_08_02':device['stats'],'bins':dist['bins']},'follow_up':{'unit_id':uid,'status':note.status,'version':note.version,'source_refs':len(manifest),'source_files_hash_verified':len(files),'audit_events':len(events)},'pre_quality_backup':str(baseline.relative_to(ROOT)),'tests_passed':139,'scope':'Imported synthetic data only; descriptive distributions and coordination notes. No device attachments, capability estimate, real quality approval or U8/MES writes.'}
evidence['browser_checks']=['global 4500-SN cohort and separate first-event/first-complete rates','latest missing HV list 45 SN; detailed missing required item and Excel row','persisted simulated follow-up v1 without altering detection or release','first-fail plus passing retest retained in two sessions','same-config first-complete 97 / 8 outside; all-valid 105 measurements / 97 SN; latest 97 / 0 outside','empty histogram bin retains full 97 observations and returns zero selected rows','SB-08-02 first-complete filter returns 29 observations / 5 outside']
evidence['browser_checks']+=['binary project shows 0/1 categories without numeric average','390px viewport: page width 390, dialog width 356, content width 354','browser console errors: none captured']
evidence['screenshots']=['outputs/质量与试验中心.png','outputs/质量漏项协调.png','outputs/同配置检测分布.png']
if args.backup:
    path=args.backup.resolve()
    with zipfile.ZipFile(path) as z,tempfile.TemporaryDirectory(prefix='quality-restore-') as tmp:
        listed=json.loads(z.read('manifest.json'))['files']
        for f in listed:
            payload=z.read(f['path']);assert len(payload)==f['size'] and hashlib.sha256(payload).hexdigest()==f['sha256']
        p=Path(tmp)/'restored.sqlite3';p.write_bytes(z.read('data/platform.sqlite3'))
        with sqlite3.connect(p) as db:
            assert db.execute('pragma integrity_check').fetchone()[0]=='ok'
            assert db.execute('select count(*) from app_record').fetchone()[0]==106838
            assert db.execute('select status,version from app_issuedisposition where key=?',('quality:'+uid,)).fetchone()==('待质量复核',1)
            assert db.execute('select snapshot_hash from app_tracecase where code=?',(case.code,)).fetchone()[0]==case.snapshot_hash
    evidence['verified_backup']={'path':str(path.relative_to(ROOT)),'files':len(listed),'checksums':True,'sqlite_integrity':'ok','restored_quality_follow_up':True,'prior_trace_snapshot_preserved':True}
(ROOT/'data/quality_validation.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2))
print(json.dumps({k:evidence[k] for k in ['business_records','business_facts_unchanged','unchanged_models','unchanged_topics','independent_summary','latest_status_counts','follow_up']},ensure_ascii=False))
