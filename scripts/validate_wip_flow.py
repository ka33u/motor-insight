"""Independent raw-journal ledger, immutable baseline and isolated API exercise.

The independent calculation below does not call Wip or any Wip rule helper.
It checks the actual synthetic data contract, not real manufacturing approval.
"""
import os,sys,json,sqlite3,tempfile,zipfile,hashlib
from pathlib import Path
from collections import defaultdict,Counter
from datetime import datetime
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
BASELINE=ROOT/'data/backups/motor-backup-20261006-113310.zip'
NEW=['wip_locations','wip_lots','wip_openings','wip_event_versions','wip_event_lines']
ACTIVE={'生产缓冲','返工区','隔离区'}
def digest(v):return hashlib.sha256(json.dumps(v,ensure_ascii=False,sort_keys=True,default=str).encode()).hexdigest()
def ro(p):
    c=sqlite3.connect(Path(p).resolve().as_uri()+'?mode=ro',uri=True);c.row_factory=sqlite3.Row;return c
from wip_raw_ledger import rows_at

with tempfile.TemporaryDirectory(prefix='wip-independent-review-') as directory:
    temp=Path(directory);baseline=temp/'before.sqlite3';copy=temp/'exercise.sqlite3'
    with zipfile.ZipFile(BASELINE) as z:
        assert z.testzip() is None;baseline.write_bytes(z.read('data/platform.sqlite3'));manifest=json.loads(z.read('manifest.json'))
        originals=0
        for f in manifest['files']:
            raw=z.read(f['path']);assert len(raw)==f['size'] and hashlib.sha256(raw).hexdigest()==f['sha256']
            if f['path'] not in ['data/platform.sqlite3','data/bi_design.json']:assert (ROOT/f['path']).read_bytes()==raw;originals+=1
    with ro(baseline) as old,ro(ROOT/'data/platform.sqlite3') as live:
        preserved={};additions={}
        for (name,) in old.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"):
            keys=[r['name'] for r in sorted(old.execute('PRAGMA table_info("'+name+'")'),key=lambda r:r['pk']) if r['pk']];assert keys
            before={tuple(r[k] for k in keys):digest(dict(r)) for r in old.execute('SELECT * FROM "'+name+'"')};seen=set();new=[]
            for r in live.execute('SELECT * FROM "'+name+'"'):
                key=tuple(r[k] for k in keys)
                if key in before:assert before[key]==digest(dict(r)),(name,key);seen.add(key)
                else:new.append(dict(r))
            assert len(seen)==len(before),name;preserved[name]=len(before)
            if new:
                assert name in ['app_record','app_importbatch','app_importrow','app_auditevent'],name
                additions[name]=len(new)
                if name=='app_record':assert all(r['dataset'] in NEW for r in new)
        assert additions=={'app_importbatch':1,'app_importrow':41899,'app_record':41899,'app_auditevent':3},additions
        raw=defaultdict(list)
        for row in live.execute('SELECT dataset,"values" FROM app_record'):raw[row['dataset']].append(json.loads(row['values']))
    comparisons=[]
    independent={}
    for at in ['2026-09-20T18:00:00','2026-09-22T12:00:00','2026-10-01T18:00:00']:
        independent[at]=rows_at(raw,at)
    with sqlite3.connect(ROOT/'data/platform.sqlite3') as src,sqlite3.connect(copy) as dst:src.backup(dst)
    os.environ['MOTOR_SQLITE_PATH']=str(copy);os.environ['DJANGO_SETTINGS_MODULE']='config.settings'
    import django;django.setup()
    from django.conf import settings
    assert Path(settings.DATABASES['default']['NAME']).resolve()==copy.resolve()
    from app import wip_flow as eng,wip_views,analytics,targets,metric_registry
    from app.models import Record,AnalysisModel,MetricVersion,ImportBatch,ImportRow
    from app.analysis_engine import run_analysis
    from django.contrib.auth.models import User
    from django.test import Client
    from urllib.parse import urlencode
    import csv,io
    for at,(ind,applied) in independent.items():
        w=eng.Wip(cutoff=at);assert set(ind)==set(w.index)
        for key,r in ind.items():
            for field,value in r.items():
                actual=w.index[key][field]
                if field=='positions':
                    actual=[{k:p[k] for k in value[0]} for p in actual] if value else actual
                    actual=sorted(actual,key=lambda p:(p['lot_id'],p['location_id']));value=sorted(value,key=lambda p:(p['lot_id'],p['location_id']))
                assert actual==value,(at,key,field,actual,value)
        assert sum(e['applied'] for e in w.events)==applied
        comparisons.append(dict(as_of=at,roots=len(ind),applied_events=applied,summary=eng.summary(w.rows)))
    imported=json.loads((ROOT/'data/wip_actual_import.json').read_text());batch=ImportBatch.objects.get(pk=imported['batch_id'])
    assert hashlib.sha256(Path(batch.file_path).read_bytes()).hexdigest()==imported['sha256'];assert ImportRow.objects.filter(batch=batch).count()==41899
    source_refs=set()
    w=eng.Wip()
    for key in w.index:
        for ref in w.evidence(key):
            identity=(ref['dataset'],ref['key'])
            if identity in source_refs:continue
            record=Record.objects.select_related('source_row__batch').get(dataset=ref['dataset'],business_key=ref['key'])
            assert record.source_row_id and record.source_row.status=='committed'
            assert record.values==record.source_row.normalized and record.record_hash==record.source_row.record_hash
            source_refs.add(identity)
    admin=User.objects.get(username='demo_admin');client=Client();client.force_login(admin)
    facts=digest(list(Record.objects.order_by('id').values()))
    board=client.get('/api/wip-flow').json();assert board['summary']==comparisons[-1]['summary'];assert board['plan_context']['total']==100
    decoded=list(csv.reader(io.StringIO(client.get('/api/wip-flow/export?'+urlencode({'receipt':board['receipt']})).content.decode('utf-8-sig'))))
    assert len(decoded)-5==400
    at='2026-09-20T18:00:00';scope={'as_of':at,'work_order_id':'MO2609-000001','kind':'定子'};b=client.get('/api/wip-flow?'+urlencode(scope)).json();assert b['total']==1
    key='DZ2609210001';params=scope|{'receipt':b['receipt']};detail=client.get('/api/wip-flow/rows/'+key+'?'+urlencode(params));assert detail.status_code==200
    positions=detail.json()['row']['positions'];assert len(positions)==1 and positions[0]['qty']==20 and positions[0]['whole_lot_qty']==40 and positions[0]['root_count']==2
    evidence=client.get('/api/wip-flow/rows/'+key+'/evidence?'+urlencode(params)).json();assert evidence['total']>40 and all(not r.get('missing') for r in evidence['rows'])
    export=client.get('/api/wip-flow/positions-export?'+urlencode(params));assert export.status_code==200
    position_csv=list(csv.reader(io.StringIO(export.content.decode('utf-8-sig'))));assert len(position_csv)-5==1 and position_csv[-1][6:8]==['20','40']
    assert client.get('/api/wip-flow/export?'+urlencode(params|{'kind':'转子'})).status_code==409
    assert client.get('/api/wip-flow/rows/DZ2609220049?'+urlencode(params)).status_code==404
    assert digest(list(Record.objects.order_by('id').values()))==facts
    prior=json.loads((ROOT/'data/assembly_plans_before.json').read_text())
    def projection(v):
        v=json.loads(json.dumps(v,default=str));v.pop('metric_receipt',None)
        for k in ['pivot','scatter']:
            if isinstance(v.get(k),dict):v[k].pop('revision',None)
        return v
    for mid,result in prior['models'].items():
        model=AnalysisModel.objects.get(pk=mid);assert projection(run_analysis(admin,model.dataset,model.definition))==projection(result),mid
    assert len(prior['models'])==52
    assert {r['id']:json.loads(json.dumps(r,default=str)) for r in targets.Targets(admin).rows.values()}=={r['id']:r for r in prior['targets']}
    metric=MetricVersion.objects.get(status='published',metric__key='DELIVERY_OTIF',version=8)
    assert metric.calculation_hash==metric_registry.calculation_hash(metric.metric.dataset)=='9d9a5af3d45172eca16790d628a36bc6acbe18d1e2a811a66a5b5fbff7037fe3'
    report=dict(synthetic=True,baseline=BASELINE.name,main_tables_preserved=preserved,permitted_additions=additions,old_original_files_preserved=originals,
      independent_raw_ledger=True,cutoff_comparisons=comparisons,source_refs_checked=len(source_refs),source_sha256=imported['sha256'],source_rows=41899,
      models_preserved=52,targets_preserved=33,published_metric_version=8,records=Record.objects.count(),isolated_api=dict(current=True,historical=True,cross_work_order_share=True,same_scope_csv=True,stale_scope=True,evidence=True),
      browser=dict(rendered=False,mobile=False,actual_download=False,reason='此前浏览器自动授权连续两次超时，待询未获答复；本报告为独立台账及隔离API客户端核验。'))
    (ROOT/'data/wip_validation.json').write_text(json.dumps(report,ensure_ascii=False,indent=2));print(json.dumps({k:v for k,v in report.items() if k!='main_tables_preserved'},ensure_ascii=False))
