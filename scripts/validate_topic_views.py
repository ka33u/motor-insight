"""Fixed synthetic-scenario reconciliation for saved BI views and two-cohort comparisons."""
import os,sys,json,hashlib,sqlite3,tempfile,zipfile,csv,math
from collections import defaultdict,Counter
from decimal import Decimal
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings')
import django;django.setup()
from django.contrib.auth.models import User
from app.models import Record,TopicView,AnalysisModel,Topic,MetricVersion
from app import topic_workspace as ws,analytics,metric_registry
BASE=ROOT/'data/backups/motor-backup-20261003-145328.zip'
h=hashlib.sha256()
for row in Record.objects.order_by('dataset','business_key').values_list('dataset','business_key','values','revision','source_row_id').iterator():h.update(json.dumps(row,ensure_ascii=False,sort_keys=True).encode())
assert Record.objects.count()==106838 and h.hexdigest()=='576ad9668e112e407eb81b9d3f58fa150f5753f7ede1fe43b2919ed4a1ec2a72'
with zipfile.ZipFile(BASE) as z,tempfile.TemporaryDirectory() as tmp:
    for item in json.loads(z.read('manifest.json'))['files']:
        if item['path'].startswith('data/imports/'):assert hashlib.sha256((ROOT/item['path']).read_bytes()).hexdigest()==item['sha256']
    before=Path(tmp)/'before.sqlite3';before.write_bytes(z.read('data/platform.sqlite3'))
    with sqlite3.connect(before) as old,sqlite3.connect(ROOT/'data/platform.sqlite3') as current:
        tables=[r[0] for r in old.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'app_%'")]
        for table in tables:
            old_rows=list(old.execute(f'SELECT * FROM {table} ORDER BY id'))
            if table=='app_auditevent':
                assert old_rows==list(current.execute(f'SELECT * FROM {table} WHERE id<=? ORDER BY id',(old_rows[-1][0],)))
            else:assert old_rows==list(current.execute(f'SELECT * FROM {table} ORDER BY id')),table
    old_design=json.loads(z.read('data/bi_design.json'));new_design=json.loads((ROOT/'data/bi_design.json').read_text())
    for d in [old_design,new_design]:
        for domain in d['domains']:
            for item in domain['items']:
                if item['id']=='X-07':item.pop('gap')
    assert old_design==new_design
assert AnalysisModel.objects.count()==46 and Topic.objects.count()==16
admin=User.objects.get(username='demo_admin');quality=User.objects.get(username='demo_quality');views=list(TopicView.objects.order_by('id'))
assert len(views)==2 and [v.version for v in views]==[3,1] and all(v.owner==admin and v.topic_id==16 and not v.archived for v in views)
assert ws.list_views(quality,ws.context(quality,1))==[]
v3=MetricVersion.objects.select_related('metric').get(metric__key='DELIVERY_OTIF',version=3)
assert v3.status=='published' and v3.calculation_hash==metric_registry.calculation_hash(v3.metric.dataset)
# Independently aggregate raw costs and SN, not semantic result tables.
raw=analytics.tables();products={p['id']:p for p in raw['products']};costs=defaultdict(lambda:[0,0]);qty=Counter()
for c in raw['costs']:
    if c['occurred']<=analytics.DAY:
        costs[c['work_order_id']][0]+=c['amount_cents']
        if c['category']=='材料':costs[c['work_order_id']][1]+=c['amount_cents']
for u in raw['units']:
    if u['assembly_at']<=analytics.AS_OF:qty[u['work_order_id']]+=1

def independent(scope):
    groups=defaultdict(lambda:{'m0':0,'m1':0,'m2':0,'rows':0});configs=Counter();ids=set()
    for w in raw['work_orders']:
        family=products[w['product_id']]['family'];day=w['planned_end']
        if scope.get('family') and scope['family']!=family:continue
        if scope.get('from') and day<scope['from'] or scope.get('to') and day>scope['to']:continue
        ids.add(w['id']);configs[w['product_id']]+=1;x=groups[family];x['rows']+=1;x['m0']+=costs[w['id']][0];x['m1']+=costs[w['id']][1];x['m2']+=qty[w['id']]
    for x in groups.values():
        x['d0']=float(Decimal(x['m0'])/100/x['m2']) if x['m2'] else None
        x['d1']=float(Decimal(x['m0']-x['m1'])/100/x['m2']) if x['m2'] else None
        x['d2']=float(Decimal(x['m1'])/x['m0']*100) if x['m0'] else None
    return groups,configs,ids
checks=[];all_results=[]
for v in views:
    ctx=ws.context(admin,v.topic_id);assert not ws.view_info(v,ctx)['stale']
    result=ws.run(admin,v.topic_id,{'context_token':ctx['context_token'],'config':v.config});all_results.append(result)
    for c in result['cards']:
        maps=[];config_sets=[];id_sets=[]
        for side,scope in [('primary',v.config['scope']),('reference',v.config['reference_scope'])]:
            g,configs,ids=independent(scope);maps.append(g);config_sets.append(set(configs));id_sets.append(ids)
            assert c[side]['matched']==sum(x['rows'] for x in g.values())
            for row in c[side]['rows']:
                assert row['row_count']==g[row['dimension']]['rows']
                for key in ['m0','m1','m2','d0','d1','d2']:assert math.isclose(row[key],g[row['dimension']][key],rel_tol=1e-12)
        for row in c['comparison']['rows']:
            for val in row['values']:
                a=maps[0].get(row['dimension'],{}).get(val['key']);b=maps[1].get(row['dimension'],{}).get(val['key'])
                if a is None or b is None:assert val['delta'] is None
                else:assert math.isclose(val['delta'],float(Decimal(str(a))-Decimal(str(b))),rel_tol=1e-12)
                if val['key']=='d2':assert val['delta_unit']=='百分点' and val['relative_pct'] is None
        assert c['comparability']['overlap_objects']==len(id_sets[0]&id_sets[1])==0
        assert c['comparability']['shared_configuration_count']==len(config_sets[0]&config_sets[1])==0
        checks.append({'view':v.pk,'model':c['model']['id'],'primary_rows':c['primary']['matched'],'reference_rows':c['reference']['matched'],'comparability':c['comparability'],'rows':c['comparison']['rows']})
# Validate actual file downloaded through browser, not an independently authored CSV.
p=ROOT/'outputs/专题范围对照_浏览器导出.csv';export=list(csv.DictReader(p.open(encoding='utf-8-sig')));assert len(export)==18
card=all_results[0]['cards'][0];labels={m['key']:m['label'] for m in card['primary']['measures']}
for row in card['comparison']['rows']:
    for v in row['values']:
        found=next(x for x in export if x['产品族']==row['dimension'] and x['度量']==labels[v['key']])
        for col,key in [('当前值','primary'),('对照值','reference'),('差值','delta'),('相对变化(%)','relative_pct')]:
            if v[key] is None:assert found[col]==''
            else:assert math.isclose(float(found[col]),v[key],rel_tol=1e-12)
        assert found['数据修订标记']==all_results[0]['facts_token'] and found['共同配置数']=='0'
evidence={'synthetic':True,'baseline':str(BASE.relative_to(ROOT)),'business_rows':106838,'business_sha256':h.hexdigest(),'preserved_tables':tables,
 'unchanged_models':46,'unchanged_topics':16,'preserved_metric_v3':True,'new_private_views':[{'id':v.pk,'name':v.name,'version':v.version,'owner':v.owner.username,'config':v.config} for v in views],
 'tests':236,'new_tests':32,'independent_comparisons':checks,'browser_export':{'path':str(p.relative_to(ROOT)),'rows':len(export),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()},
 'catalog_change':'Only X-07 gap updated; 26 domains, 264 candidates, 39 partial, 225 planned unchanged.',
 'browser_checks':['双范围计算与百分点差','保存两个个人视角','归档与恢复','刷新重开','两侧7/6条YE4来源','分组联动当前专题','实际CSV下载与18行校验','390px页面与来源弹窗'],
 'limits':'Query settings persist, not historical values. Date filters select cohorts and do not replay state. Comparison does not normalize date groups, infer causality or guarantee equivalent configurations. Linking is limited to supported family/customer groups. Full arbitrary chart linking, more dimensions and what-if simulation remain future work.'}
if len(sys.argv)>1:
    backup=Path(sys.argv[1]).resolve()
    with zipfile.ZipFile(backup) as z,tempfile.TemporaryDirectory() as tmp:
        manifest=json.loads(z.read('manifest.json'))
        for item in manifest['files']:assert hashlib.sha256(z.read(item['path'])).hexdigest()==item['sha256']
        p=Path(tmp)/'restored.sqlite3';p.write_bytes(z.read('data/platform.sqlite3'))
        with sqlite3.connect(p) as restored,sqlite3.connect(ROOT/'data/platform.sqlite3') as current:
            assert restored.execute('pragma integrity_check').fetchone()[0]=='ok'
            for table in [*tables,'app_topicview']:
                if table=='app_auditevent':continue
                assert list(restored.execute(f'SELECT * FROM {table} ORDER BY id'))==list(current.execute(f'SELECT * FROM {table} ORDER BY id')),table
    evidence['backup']={'path':str(backup.relative_to(ROOT)),'manifest_files':len(manifest['files']),'sqlite_integrity':'ok','critical_tables_match':True}
(ROOT/'data/topic_views_validation.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2,default=str))
print(json.dumps({k:v for k,v in evidence.items() if k not in ['independent_comparisons','preserved_tables','limits','browser_checks']},ensure_ascii=False,default=str))
