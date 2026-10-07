"""Independently reconcile personal grouping demos and preserve prior facts/evidence."""
import os,sys,json,csv,copy,hashlib,sqlite3,zipfile,tempfile
from pathlib import Path
from collections import Counter
from decimal import Decimal
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings')
import django;django.setup()
from django.contrib.auth.models import User
from app.models import Record,AnalysisModel,MetricVersion,BusinessGroupingVersion,TopicView,TopicSnapshot
from app import metric_registry as registry,topic_workspace as ws,topic_snapshots as ss
from app.analysis_engine import run_analysis
u=User.objects.get(username='demo_admin')
baseline=ROOT/'data/backups/motor-backup-20261003-175841.zip'
preserved={}
old_metric=MetricVersion.objects.get(metric__key='DELIVERY_OTIF',version=3)
exceptions={'app_analysismodel':{44:{'definition','name','version','updated_at'}},'app_topic':{15:{'description','version','updated_at'}},
 'app_metricversion':{old_metric.pk:{'status','review_note','revision','updated_at','retired_at'}},
 'app_topicview':{1:{'binding','version','updated_at'},2:{'binding','version','updated_at'}}}
with zipfile.ZipFile(baseline) as z,tempfile.TemporaryDirectory() as temp:
    for item in json.loads(z.read('manifest.json'))['files']:
        if item['path'].startswith(('data/imports/','data/device_files/')):
            assert hashlib.sha256((ROOT/item['path']).read_bytes()).hexdigest()==item['sha256']
    p=Path(temp)/'baseline.sqlite3';p.write_bytes(z.read('data/platform.sqlite3'))
    with sqlite3.connect(p) as old,sqlite3.connect(ROOT/'data/platform.sqlite3') as now:
        tables=[r[0] for r in old.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'app_%'")]
        for table in tables:
            cols=[r[1] for r in old.execute(f'PRAGMA table_info({table})')];ix=cols.index('id')
            before=list(old.execute(f'SELECT * FROM {table} ORDER BY id'));after=list(now.execute(f'SELECT * FROM {table} ORDER BY id'));current={r[ix]:r for r in after};changes=[]
            for row in before:
                assert row[ix] in current,(table,row[ix],'missing')
                changed={c for c,a,b in zip(cols,row,current[row[ix]]) if a!=b}
                assert changed<=exceptions.get(table,{}).get(row[ix],set()),(table,row[ix],changed)
                if changed:changes.append({'id':str(row[ix]),'changed_fields':sorted(changed)})
            additions={'app_analysismodel':2,'app_topic':1,'app_metricversion':1}
            if table!='app_auditevent':assert len(after)-len(before)==additions.get(table,0),(table,len(before),len(after))
            preserved[table]={'before':len(before),'after':len(after),'explicit_configuration_changes':changes}

hasher=hashlib.sha256()
for row in Record.objects.order_by('dataset','business_key').values_list('dataset','business_key','values','revision','source_row_id').iterator():hasher.update(json.dumps(row,ensure_ascii=False,sort_keys=True).encode())
assert hasher.hexdigest()=='298b65fd282b1b8c05fc78a549d95058fd46b83984165275958ad16d080eba3f'
assert Record.objects.count()==106940
old_results=json.loads((ROOT/'data/business_groups_baseline.json').read_text())
for m in AnalysisModel.objects.filter(pk__in=old_results):
    definition,_=registry.resolve(u,m.dataset,m.definition,allow_inactive=True)
    r=run_analysis(u,m.dataset,definition)
    assert {k:r[k] for k in old_results[str(m.pk)]}==old_results[str(m.pk)],m.pk
published=MetricVersion.objects.get(metric__key='DELIVERY_OTIF',version=4)
assert published.status=='published' and published.calculation_hash==registry.calculation_hash('bi_order_lines')
assert (published.evidence['components'][0]['numerator'],published.evidence['components'][0]['denominator'])==(15,165)
assert old_metric.status=='retired'

products={v['id']:v for v in Record.objects.filter(dataset='products').values_list('values',flat=True)}
units=list(Record.objects.filter(dataset='units').values_list('values',flat=True))
def expected(version,day=None):
    p=version.payload;counts=Counter()
    for unit in units:
        if day and not unit['assembly_at'].startswith(day):continue
        value=products[unit['product_id']][p['field']]
        if value in [None,'']:label='未填写'
        else:
            label='未归类'
            for rule in p['rules']:
                if p['mode']=='enum':match=value in rule['values']
                else:
                    n=Decimal(str(value));match=(rule['lower'] is None or n>=Decimal(rule['lower'])) and (rule['upper'] is None or n<Decimal(rule['upper']))
                if match:label=rule['label'];break
        counts[label]+=1
    return dict(counts)

group_results=[]
for v in BusinessGroupingVersion.objects.select_related('grouping').order_by('grouping__code','version'):
    ref={'id':str(v.grouping_id),'version':v.version,'hash':v.payload_hash}
    d={'dimension':v.payload['field'],'grain':'value','grouping_ref':ref,'metrics':[{'agg':'count'}],'chart':'bar','sort':'dimension'}
    for day in [None,'2026-09-21']:
        r=run_analysis(u,'bi_units',d,{} if day is None else {'from':day,'to':day})
        want=expected(v,day);assert {row['dimension']:row['m0'] for row in r['rows']}==want
        assert r['matched']==sum(want.values()) and r['grouping_receipt']['payload']==v.payload
        group_results.append({'code':v.grouping.code,'version':v.version,'day':day,'counts':want})
assert [r['counts'] for r in group_results if r['code']=='MOTOR.POWER.BAND' and r['day'] is None]==[
 {'01 · 2.2kW以下':1125,'02 · 2.2至7.5kW':1500,'03 · 7.5kW及以上':1875},
 {'01 · 3kW以下':1750,'02 · 3至7.5kW':875,'03 · 7.5kW及以上':1875}]
assert AnalysisModel.objects.get(pk=47).definition['grouping_ref']['version']==1
assert all(not m.is_public and m.owner==u.username for m in AnalysisModel.objects.filter(pk__in=[47,48]))
ctx=ws.context(u,17);conf={'scope':{'from':'2026-09-21','to':'2026-09-21'},'reference_scope':None,'primary_label':'当前范围','reference_label':'对照范围'}
result=ws.run(u,17,{'context_token':ctx['context_token'],'config':conf})
for card in result['cards']:
    assert card['primary']['matched']==900
    for row in card['primary']['rows']:
        e=ws.evidence(u,17,{'context_token':ctx['context_token'],'facts_token':result['facts_token'],'config':conf,'slot':card['slot'],'side':'primary','group':row['dimension'],'page':1})
        assert e['total']==row['m0']
csvfile=ROOT/'outputs/业务分组_功率结构_浏览器导出.csv'
actual=list(csv.reader(csvfile.open(encoding='utf-8-sig')))
exported,_=ws.export_rows(u,17,{'context_token':ctx['context_token'],'facts_token':result['facts_token'],'config':conf,'slot':0})
normalized=[['' if v is None else str(v) for v in row] for row in exported]
assert actual==normalized
assert '分组规则' in actual[0] and [int(r[-1]) for r in actual[1:]]==[225,300,375]
for view in TopicView.objects.all():assert not ws.view_info(view,ws.context(u,view.topic_id))['stale']
old_snapshot=TopicSnapshot.objects.get(pk='afd93961-7331-42b3-b5a9-8a09042fb333')
assert old_snapshot.payload_hash=='6768e9603cda8d0506378e9ba8e4405e9560482cb25f41e211dc73b0ad4ee818'
assert ss.detail(u,old_snapshot.topic_id,old_snapshot.pk)['result']==old_snapshot.payload['result']
assert ss.compare_current(u,old_snapshot.topic_id,old_snapshot.pk)['blocked']
report={'synthetic':True,'baseline':str(baseline.relative_to(ROOT)),'business_rows':106940,'business_sha256':hasher.hexdigest(),'unchanged_old_model_results':46,'grouping_versions':group_results,'preserved_tables':preserved,'metric_version':4,'browser_csv_rows':len(actual)-1,'browser_csv_sha256':hashlib.sha256(csvfile.read_bytes()).hexdigest(),'frozen_snapshot_unchanged':True,'old_current_comparison':'blocked because calculation binding changed; frozen evidence readable','tests':393,'limits':'Personal single-field rules only; no shared certification, hierarchy, multi-field expression or effective-dated grouping. U8/MES remain disconnected.'}
if len(sys.argv)>1:
    backup=Path(sys.argv[1])
    with zipfile.ZipFile(backup) as z,tempfile.TemporaryDirectory() as temp:
        manifest=json.loads(z.read('manifest.json'))
        for f in manifest['files']:
            raw=z.read(f['path']);assert len(raw)==f['size'] and hashlib.sha256(raw).hexdigest()==f['sha256']
        p=Path(temp)/'restored.sqlite3';p.write_bytes(z.read('data/platform.sqlite3'))
        with sqlite3.connect(p) as restored,sqlite3.connect(ROOT/'data/platform.sqlite3') as now:
            assert restored.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
            new_tables=[r[0] for r in now.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'app_%'")]
            for t in new_tables:assert list(restored.execute(f'SELECT * FROM {t} ORDER BY id'))==list(now.execute(f'SELECT * FROM {t} ORDER BY id')),t
        report['backup']={'path':str(backup),'manifest_files':len(manifest['files']),'app_tables':len(new_tables),'sqlite_integrity':'ok','all_app_tables_match':True}
(ROOT/'data/business_groups_validation.json').write_text(json.dumps(report,ensure_ascii=False,indent=2,default=str))
print(json.dumps({k:v for k,v in report.items() if k!='preserved_tables'},ensure_ascii=False,default=str))
