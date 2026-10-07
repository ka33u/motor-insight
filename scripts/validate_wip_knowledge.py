"""Actual-data two-clock validation; all API mutations confined to a DB copy."""
import os,sys,json,sqlite3,tempfile,zipfile,hashlib,csv,io
from pathlib import Path
from collections import defaultdict
from urllib.parse import urlencode
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from recovery import database_inventory
from wip_raw_ledger import rows_at
prior=json.loads((ROOT/'data/wip_knowledge_before.json').read_text())
assert database_inventory(ROOT/'data/platform.sqlite3')==prior['database'],'main SQL state changed'
with sqlite3.connect(ROOT/'data/platform.sqlite3') as c:
    raw=defaultdict(list)
    for ds,v in c.execute('SELECT dataset,"values" FROM app_record'):raw[ds].append(json.loads(v))
originals=0
with zipfile.ZipFile(ROOT/'data/backups/motor-backup-20261006-120552.zip') as z:
    assert z.testzip() is None;manifest=json.loads(z.read('manifest.json'))
    for f in manifest['files']:
        b=z.read(f['path']);assert len(b)==f['size'] and hashlib.sha256(b).hexdigest()==f['sha256']
        if f['path'] not in ['data/platform.sqlite3','data/bi_design.json']:assert (ROOT/f['path']).read_bytes()==b;originals+=1
cases=[(at,at) for at in prior['default_wip_snapshots']]+[(at,'2026-10-01T18:00:00') for at in ['2026-09-20T18:00:00','2026-09-22T12:00:00']]
independent={(at,known):rows_at(raw,at,known) for at,known in cases}
with tempfile.TemporaryDirectory(prefix='wip-registration-review-') as directory:
    copy=Path(directory)/'platform.sqlite3'
    with sqlite3.connect(ROOT/'data/platform.sqlite3') as src,sqlite3.connect(copy) as dst:src.backup(dst)
    os.environ['MOTOR_SQLITE_PATH']=str(copy);os.environ['DJANGO_SETTINGS_MODULE']='config.settings'
    import django;django.setup()
    from django.conf import settings
    assert Path(settings.DATABASES['default']['NAME']).resolve()==copy.resolve()
    from app import wip_flow as eng,wip_comparison as comp,targets,metric_registry
    from app.models import Record,AnalysisModel,MetricVersion
    from app.analysis_engine import run_analysis
    from django.contrib.auth.models import User
    from django.test import Client
    reports=[];engines={}
    for (at,known),(expected,applied) in independent.items():
        w=eng.Wip(cutoff=at,known_cutoff=known);engines[at,known]=w;assert set(w.index)==set(expected)
        for key,r in expected.items():
            for field,value in r.items():
                actual=w.index[key][field]
                if field=='positions':
                    actual=[{k:p[k] for k in value[0]} for p in actual] if value else actual
                    actual=sorted(actual,key=lambda p:(p['lot_id'],p['location_id']));value=sorted(value,key=lambda p:(p['lot_id'],p['location_id']))
                assert actual==value,(at,known,key,field)
        assert sum(e['applied'] for e in w.events)==applied
        if at==known:
            assert sorted(w.rows,key=lambda r:r['id'])==prior['default_wip_snapshots'][at]['rows']
            assert eng.summary(w.rows)==prior['default_wip_snapshots'][at]['summary']
        reports.append(dict(as_of=at,known_as_of=known,roots=len(expected),applied=applied,summary=eng.summary(w.rows)))
    at='2026-09-20T18:00:00';known='2026-10-01T18:00:00';a=engines[at,at];b=engines[at,known];comparison=comp.comparison(a,b,b.rows)
    # Manual case identities from the source XLSX, separate from engine results.
    changed={r['id']:r for r in comparison['changed']}
    assert set(changed)=={'ZZ2609210001','ZZ2609210002','DZ2609210002'},set(changed)
    assert comparison['summary']['outcome_changed']==2 and comparison['summary']['evidence_only']==1
    for key in ['ZZ2609210001','ZZ2609210002']:
        assert changed[key]['before']['state']=='active' and changed[key]['after']['state']=='attention';assert changed[key]['wip_delta'] is None
    assert changed['DZ2609210002']['change_type']=='仅依据改变' and changed['DZ2609210002']['wip_delta']==0
    admin=User.objects.get(username='demo_admin');client=Client();client.force_login(admin)
    scope=dict(as_of=at,known_as_of=known);board=client.get('/api/wip-flow',scope).json();bound=scope|dict(receipt=board['receipt'])
    api=client.get('/api/wip-flow/comparison',bound);assert api.status_code==200;data=api.json();assert data['summary']==comparison['summary']
    assert data['total']==3 and data['rows']==comparison['changed']
    export=client.get('/api/wip-flow/comparison/export',bound);assert export.status_code==200
    csvrows=list(csv.reader(io.StringIO(export.content.decode('utf-8-sig'))));assert len(csvrows)-5==290
    fields={v:i for i,v in enumerate(csvrows[4])};allrows={r[0]:r for r in csvrows[5:]}
    assert allrows['ZZ2609210001'][fields['同批次可比在制差']]==''
    assert allrows['DZ2609210002'][fields['同批次可比在制差']]=='0'
    subset=scope|dict(kind='转子',stage='attention');sb=client.get('/api/wip-flow',subset).json();sq=subset|dict(receipt=sb['receipt'])
    sd=client.get('/api/wip-flow/comparison',sq).json();assert sd['summary']['objects']==len([r for r in b.rows if r['kind']=='转子' and r['state']=='attention'])
    assert client.get('/api/wip-flow/comparison/rows/DZ2609210002',sq).status_code==404
    assert client.get('/api/wip-flow/comparison',bound|dict(known_as_of=at)).status_code==409
    key='ZZ2609210001';detail=client.get('/api/wip-flow/comparison/rows/'+key,bound).json();assert detail['row']==changed[key]
    sources=client.get('/api/wip-flow/rows/'+key+'/evidence',bound).json();assert sources['total']>40 and all(not r.get('missing') for r in sources['rows'])
    defaults=json.loads((ROOT/'data/assembly_plans_before.json').read_text())
    def projection(v):
        v=json.loads(json.dumps(v,default=str));v.pop('metric_receipt',None)
        for k in ['pivot','scatter']:
            if isinstance(v.get(k),dict):v[k].pop('revision',None)
        return v
    for mid,v in defaults['models'].items():
        m=AnalysisModel.objects.get(pk=mid);assert projection(run_analysis(admin,m.dataset,m.definition))==projection(v)
    assert len(defaults['models'])==52
    assert {r['id']:json.loads(json.dumps(r,default=str)) for r in targets.Targets(admin).rows.values()}=={r['id']:r for r in defaults['targets']}
    metric=MetricVersion.objects.get(status='published',metric__key='DELIVERY_OTIF',version=8)
    assert metric.calculation_hash==metric_registry.calculation_hash(metric.metric.dataset)=='9d9a5af3d45172eca16790d628a36bc6acbe18d1e2a811a66a5b5fbff7037fe3'
    report=dict(synthetic=True,main_sql_tables_unchanged=40,main_records_unchanged=167689,old_files_preserved=originals,source_rows_added=0,
        independent_raw_ledger=True,cutoff_comparisons=reports,original_default_replays_unchanged=3,
        actual_comparison=dict(summary=comparison['summary'],changed_ids=sorted(changed),csv_scope_roots=290),
        models_preserved=52,targets_preserved=33,metric_version_preserved=8,isolated_api=dict(comparison=True,detail=True,source=True,full_scope_csv=True,stale_scope=True,right_state_scope=True),
        browser=dict(rendered=False,mobile=False,actual_download=False,reason='此前浏览器自动授权连续两次超时；待询未获答复。本报告为独立台账和隔离API测试，不代表浏览器验收。'))
    (ROOT/'data/wip_knowledge_validation.json').write_text(json.dumps(report,ensure_ascii=False,indent=2));print(json.dumps({k:v for k,v in report.items() if k!='cutoff_comparisons'},ensure_ascii=False))
assert database_inventory(ROOT/'data/platform.sqlite3')==prior['database'],'main state changed during review'
