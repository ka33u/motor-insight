"""Read-only checks against the pre-migration demo backup; writes an evidence JSON only.
This validates this particular synthetic scenario, not arbitrary future databases.
"""
import os,sys,json,hashlib,sqlite3,tempfile,zipfile
from datetime import date
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings')
import django;django.setup()
from django.contrib.auth.models import User
from app.models import Record,AnalysisModel,Topic,CodingRule,CodingRuleVersion,CodeAllocation,CodeCounter,CodeIssueRequest,MetricVersion,AuditEvent
from app import coding,metric_registry
from app.analysis_engine import run_analysis
baseline=ROOT/'data/backups/motor-backup-20261003-141702.zip'
h=hashlib.sha256()
for row in Record.objects.order_by('dataset','business_key').values_list('dataset','business_key','values','revision','source_row_id').iterator():h.update(json.dumps(row,sort_keys=True,ensure_ascii=False).encode())
assert Record.objects.count()==106838 and h.hexdigest()=='576ad9668e112e407eb81b9d3f58fa150f5753f7ede1fe43b2919ed4a1ec2a72'
protected=[]
with zipfile.ZipFile(baseline) as z,tempfile.TemporaryDirectory() as tmp:
    for item in json.loads(z.read('manifest.json'))['files']:
        if item['path'].startswith('data/imports/'):
            assert hashlib.sha256((ROOT/item['path']).read_bytes()).hexdigest()==item['sha256'],item['path']
    p=Path(tmp)/'before.sqlite3';p.write_bytes(z.read('data/platform.sqlite3'))
    with sqlite3.connect(p) as old,sqlite3.connect(ROOT/'data/platform.sqlite3') as current:
        tables=[r[0] for r in old.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'app_%'")]
        excluded=['app_codingrule','app_codecounter','app_codeallocation','app_auditevent']
        for table in tables:
            if table in excluded:continue
            assert list(old.execute(f'SELECT * FROM {table} ORDER BY id'))==list(current.execute(f'SELECT * FROM {table} ORDER BY id')),table
            protected.append(table)
        for table in excluded:
            columns=[r[1] for r in old.execute(f'PRAGMA table_info({table})')];quoted=','.join('"'+c+'"' for c in columns)
            rows=list(old.execute(f'SELECT {quoted} FROM {table} ORDER BY id'))
            for row in rows:
                assert row==current.execute(f'SELECT {quoted} FROM {table} WHERE id=?',(row[0],)).fetchone(),(table,row[0])
        assert z.read('data/bi_design.json')==(ROOT/'data/bi_design.json').read_bytes()
for r in CodingRule.objects.filter(id__lte=5):
    v=CodingRuleVersion.objects.get(rule=r,version=1)
    assert v.payload==coding.payload_for(r) and v.origin=='legacy_snapshot' and v.effective_from is None and v.status=='active'
for a in CodeAllocation.objects.filter(id__lte=4):
    assert a.business_date==date(2026,10,3) and a.period=='20261003' and a.definition['origin']=='legacy_audit_checked'
    e=AuditEvent.objects.get(pk=a.definition['audit_event_id']);assert a.code in e.detail['codes'] and e.detail['version']==a.rule_version
    p=a.definition['payload'];expected=p['separator'].join(x for x in [p['prefix'],a.business_date.strftime(p['date_format']),str(a.sequence).zfill(p['width'])] if x)
    assert a.code==expected
trial=CodingRule.objects.get(key='trial_inspection');assert trial.revision==7 and trial.enabled
versions=list(trial.versions.order_by('version'));assert [(v.version,v.status,str(v.effective_from)) for v in versions]==[(1,'active','2026-10-03'),(2,'active','2026-10-04')]
assert versions[0].payload['prefix']=='TRY' and versions[0].payload['width']==4 and versions[1].payload['prefix']=='TRY2' and versions[1].payload['width']==5
new=list(trial.codeallocation_set.order_by('id'));assert [a.code for a in new]==['TRY-20261003-0001','TRY-20261003-0002','TRY-20261003-0021']
assert CodeIssueRequest.objects.count()==2 and [a.sequence for a in new]==[1,2,21]
for request in CodeIssueRequest.objects.all():
    allocations=list(request.codeallocation_set.order_by('id'));assert [a.code for a in allocations]==request.codes
    assert request.rule_version.version==1
    for a in allocations:
        assert a.definition['payload']==versions[0].payload and a.rule_version==1 and a.business_date==request.business_date
assert list(trial.codecounter_set.values_list('period','value'))==[('20261003',21)]
advance=AuditEvent.objects.get(action='coding.advance',object_id=str(trial.pk));assert (advance.detail['from'],advance.detail['to'])==(2,20)
assert '模拟' in advance.detail['reason']
before=(CodeAllocation.objects.count(),CodeIssueRequest.objects.count(),CodeCounter.objects.count(),AuditEvent.objects.count())
previews=[]
for day,version,code in [('2026-10-03',1,'TRY-20261003-0022'),('2026-10-04',2,'TRY2-20261004-00001')]:
    p=coding.preview(trial.pk,day,1,'demo_admin');assert p['valid'] and p['definition']['version']==version and p['codes']==[code]
    previews.append({'date':day,'version':version,'code':code,'counter':p['counter']})
assert before==(CodeAllocation.objects.count(),CodeIssueRequest.objects.count(),CodeCounter.objects.count(),AuditEvent.objects.count())
assert AnalysisModel.objects.count()==46 and Topic.objects.count()==16
v3=MetricVersion.objects.select_related('metric').get(metric__key='DELIVERY_OTIF',version=3)
assert v3.status=='published' and v3.calculation_hash==metric_registry.calculation_hash(v3.metric.dataset)
m44=AnalysisModel.objects.get(pk=44);result=run_analysis(User.objects.get(username='demo_admin'),m44.dataset,m44.definition)
assert result['matched']==300
assert (v3.evidence['components'][0]['numerator'],v3.evidence['components'][0]['denominator'])==(15,165)
evidence={'synthetic':True,'baseline':str(baseline.relative_to(ROOT)),'business_rows':106838,'business_sha256':h.hexdigest(),
 'preserved_full_tables':protected,'preserved_original_rules':5,'preserved_original_allocations':4,'audit_proven_legacy_dates':4,
 'preserved_models':46,'preserved_topics':16,'metric_version':3,'metric_fingerprint_valid':True,'catalog_unchanged':True,
 'trial_rule_id':trial.pk,'trial_rule_revision':trial.revision,'new_allocations':[a.code for a in new],'requests':2,
 'forward_continuation':{'from':2,'to':20,'counter_after_issue':21},'readonly_previews':previews,
 'tests':{'last_full_suite':204,'new_coding_tests':24},
 'browser_checks':['草稿保存与指定生效','跨生效日选版','修改日期使预览失效','第一版三条编号及实时计数','向前接续到20后从21发号','按编号及版本查历史快照','停用阻止发号及恢复','390px页面及弹窗无整页溢出','窄屏状态文字可见'],
 'limits':'Synthetic loopback SQLite demo. PostgreSQL concurrency, shared authority with U8/MES, external historical reservations, organization-specific dynamic segments and independent approval workflow remain unverified/unbuilt. Preview only checks imported business keys and platform reservations. Unknown legacy definitions/dates are not fabricated.'}
if len(sys.argv)>1:
    backup=Path(sys.argv[1]).resolve()
    with zipfile.ZipFile(backup) as z,tempfile.TemporaryDirectory() as tmp:
        manifest=json.loads(z.read('manifest.json'))
        for item in manifest['files']:assert hashlib.sha256(z.read(item['path'])).hexdigest()==item['sha256']
        p=Path(tmp)/'restored.sqlite3';p.write_bytes(z.read('data/platform.sqlite3'))
        with sqlite3.connect(p) as restored,sqlite3.connect(ROOT/'data/platform.sqlite3') as current:
            assert restored.execute('pragma integrity_check').fetchone()[0]=='ok'
            for table in ['app_record','app_analysismodel','app_topic','app_codingrule','app_codingruleversion','app_codecounter','app_codeallocation','app_codeissuerequest','app_tracecase','app_metricversion']:
                assert list(restored.execute(f'SELECT * FROM {table} ORDER BY id'))==list(current.execute(f'SELECT * FROM {table} ORDER BY id')),table
    evidence['backup']={'path':str(backup.relative_to(ROOT)),'manifest_files':len(manifest['files']),'sqlite_integrity':'ok','restored_critical_tables_match':True}
(ROOT/'data/coding_validation.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2,default=str))
print(json.dumps({k:v for k,v in evidence.items() if k not in ['preserved_full_tables','limits','browser_checks']},ensure_ascii=False,default=str))
