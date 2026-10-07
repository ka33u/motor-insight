"""Validate explicit order relationships and actual browser exports, preserving prior facts."""
import os,sys,json,csv,hashlib,sqlite3,zipfile,tempfile,math
from pathlib import Path
from collections import defaultdict,Counter
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings')
import django;django.setup()
from django.contrib.auth.models import User
from app.models import Record,AnalysisModel,Topic,TopicView,TopicSnapshot,ImportBatch,MetricVersion,IssueDisposition,AuditEvent,DataQualityScan
from app import analytics,material_planning as mp,material_impact as mi,metric_registry,analysis_engine,topic_snapshots
baseline=ROOT/'data/backups/motor-backup-20261004-053212.zip';preserved={};originals=0
with zipfile.ZipFile(baseline) as z,tempfile.TemporaryDirectory() as tmp:
 for f in json.loads(z.read('manifest.json'))['files']:
  if f['path'].startswith(('data/imports/','data/device_files/')):
   assert hashlib.sha256((ROOT/f['path']).read_bytes()).hexdigest()==f['sha256'];originals+=1
 path=Path(tmp)/'before.sqlite3';path.write_bytes(z.read('data/platform.sqlite3'))
 with sqlite3.connect(path) as old,sqlite3.connect(ROOT/'data/platform.sqlite3') as now:
  tables=[r[0] for r in old.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'app_%'")];assert len(tables)==25
  for table in tables:
   before=list(old.execute(f'SELECT * FROM {table} ORDER BY id'));after=list(now.execute(f'SELECT * FROM {table} ORDER BY id'));lookup={r[0]:r for r in after};assert all(lookup.get(r[0])==r for r in before),(table,'prior rows changed')
   if table!='app_auditevent':assert len(after)-len(before)==(1 if table=='app_issuedisposition' else 0),(table,len(before),len(after))
   preserved[table]={'before':len(before),'after':len(after),'all_prior_rows_unchanged':True}
h=hashlib.sha256();raw=defaultdict(list)
for row in Record.objects.order_by('dataset','business_key').values_list('dataset','business_key','values','revision','source_row_id').iterator():
 h.update(json.dumps(row,sort_keys=True,ensure_ascii=False).encode());raw[row[0]].append(row[2])
assert h.hexdigest()=='c3493d7c4d221e6511486c05605c1c7f42ae7276ca4a7070e195999ae9e2e775'
assert (Record.objects.count(),Record.objects.values('dataset').distinct().count(),ImportBatch.objects.exclude(status='superseded').count(),AnalysisModel.objects.count(),Topic.objects.count(),TopicView.objects.count(),TopicSnapshot.objects.count(),DataQualityScan.objects.count())==(110787,63,18,50,19,4,2,7)
# Reuse independently verified stock/BOM baseline, and prove every current planning row is unchanged.
before_path=ROOT/'data/material_impact_before.json';before=json.loads(before_path.read_text());planning,_=mp.current(mp.filters({}))
assert mp.clean({'summary':planning.summary(),'ordered':planning.ordered,'material_rows':planning.material_rows})==before
prior=json.loads((ROOT/'data/material_planning_validation.json').read_text());assert prior['independently_checked_lots']==173 and prior['independently_checked_order_materials']==4088
for scenario in prior['scenarios']:
 d,_=mp.current(mp.filters(scenario['filters']));assert d.summary()=={k:v for k,v in scenario.items() if k!='filters'}
states={w['id']:w['state'] for w in before['ordered']};old_all=ROOT/'outputs/备料试配_全部可用库存缺料工单_浏览器导出.csv'
assert hashlib.sha256(old_all.read_bytes()).hexdigest()==prior['browser_csv'][old_all.name]['sha256'];old_rows=list(csv.reader(old_all.open(encoding='utf-8-sig')));old_short={r[1] for r in old_rows[5:]};assert len(old_short)==20
all_states={wid:('excluded' if v=='excluded' else 'short' if wid in old_short else 'covered') for wid,v in states.items()}
lines={r['id']:r for r in raw['order_lines']};orders={r['id']:r for r in raw['orders']};customers={r['id']:r for r in raw['customers']};work={r['id']:r for r in raw['work_orders']};by_line=defaultdict(list);by_wo=defaultdict(list);shipped=Counter()
for a in raw['allocations']:
 assert a['effective']<=analytics.DAY and type(a['qty']) is int and a['qty']>0;assert work[a['work_order_id']]['product_id']==lines[a['order_line_id']]['product_id'];by_line[a['order_line_id']].append(a);by_wo[a['work_order_id']].append(a)
assert len(by_line)==len(by_wo)==300 and all(sum(a['qty'] for a in aa)==work[wid]['planned_qty'] for wid,aa in by_wo.items())
for s in raw['shipments']:
 if s['shipped']<=analytics.AS_OF:assert s['qty']>0;shipped[s['order_line_id']]+=s['qty']

def expected(verdict):
 out={}
 for lid,line in lines.items():
  aa=by_line[lid];order=orders[line['order_id']];assert sum(a['qty'] for a in aa)==line['qty'] and order['order_date']<=analytics.DAY
  qtys={state:sum(a['qty'] for a in aa if verdict[a['work_order_id']]==state) for state in ['short','covered','excluded']};remaining=line['qty']-shipped[lid];assert remaining>=0
  out[lid]={'id':lid,'order_id':line['order_id'],'customer_id':order['customer_id'],'customer':customers[order['customer_id']]['name'],'product_id':line['product_id'],'due':line['due'],'qty':line['qty'],'shipped_qty':shipped[lid],'remaining_qty':remaining,'overdue_remaining_qty':remaining if line['due']<analytics.DAY else 0,'selected_allocated_qty':sum(a['qty'] for a in aa),'all_allocated_qty':line['qty'],'short_link_qty':qtys['short'],'covered_link_qty':qtys['covered'],'excluded_link_qty':qtys['excluded'],'outside_link_qty':0,'unallocated_qty':0,'plan_after_due_count':len({a['work_order_id'] for a in aa if work[a['work_order_id']]['planned_end']>line['due']})}
 return out

cases={};all_expected={}
for policy,verdict in [('protect_safety',states),('all_usable',all_states)]:
 p,_=mp.current(mp.filters({'stock_policy':policy}));assert {w['id']:w['state'] for w in p.ordered}==verdict
 result=mi.OrderImpact(p);want=expected(verdict);all_expected[policy]=want;assert set(result.index)==set(want) and result.unlinked==[]
 for lid,e in want.items():
  actual=result.index[lid]
  for k,v in e.items():assert actual[k]==v,(lid,k,actual[k],v)
  assert not actual['issues'] and ('short' in actual['flags'])==(e['remaining_qty']>0 and e['short_link_qty']>0)
  assert {a['id'] for a in actual['links']}=={a['id'] for a in by_line[lid]}
  for a in actual['links']:
   assert a['state']==verdict[a['work_order_id']] and a['selected']
   row=p.orders[a['work_order_id']];assert {m['id'] for m in a['short_materials']}=={m['material_id'] for m in row['items'] if m['gap']}
 cases[policy]={'summary':result.summary(),'independent_remaining_qty':sum(x['remaining_qty'] for x in want.values()),'order_line_due_overdue_qty':sum(x['overdue_remaining_qty'] for x in want.values()),'allocation_count':sum(len(a) for a in by_line.values())}
assert cases['protect_safety']['summary']['short_lines']==27 and cases['protect_safety']['summary']['short_link_qty']==685
assert cases['all_usable']['summary']['short_lines']==20 and cases['all_usable']['summary']['short_link_qty']==480
changes=[{'id':lid,'before':r['short_link_qty'],'after':all_expected['all_usable'][lid]['short_link_qty']} for lid,r in all_expected['protect_safety'].items() if r['short_link_qty']!=all_expected['all_usable'][lid]['short_link_qty']]
assert len(changes)==13 and sum(r['before']>r['after'] for r in changes)==10 and sum(r['before']<r['after'] for r in changes)==3
# Actual browser files, all numeric fields reconciled to raw explicit allocations and shipment events.
titles={'订单行':'id','订单':'order_id','客户编码':'customer_id','客户':'customer','配置':'product_id','现承诺日':'due','订单数量台':'qty','登记发货台数':'shipped_qty','未交台数':'remaining_qty','按现承诺逾期未交台数':'overdue_remaining_qty','选中工单分配计划台数':'selected_allocated_qty','缺料工单关联计划台数':'short_link_qty','可覆盖工单关联计划台数':'covered_link_qty','完工取消工单关联计划台数':'excluded_link_qty','范围外工单分配计划台数':'outside_link_qty','未分配工单台数':'unallocated_qty','选中工单计划晚于现承诺的工单数':'plan_after_due_count'}
files={}
for name,policy,stage in [('订单影响_缺料关联订单_浏览器导出.csv','protect_safety','short'),('订单影响_对照策略关联订单_浏览器导出.csv','all_usable','short'),('订单影响_全部关联订单_浏览器导出.csv','protect_safety','all')]:
 path=ROOT/'outputs'/name;rows=list(csv.reader(path.open(encoding='utf-8-sig',newline='')));f=json.loads(rows[0][4]);assert f['tab']=='impact' and f['stock_policy']==policy and f['stage']==stage
 assert rows[3][1]==mp.receipt(mp.filters(f),analytics.revision());actual=[dict(zip(rows[4],r,strict=True)) for r in rows[5:]];want={lid:r for lid,r in all_expected[policy].items() if stage=='all' or r['short_link_qty']>0 and r['remaining_qty']>0}
 assert {r['订单行'] for r in actual}==set(want) and len(actual)==len(want)
 for r in actual:
  assert not r['资料问题']
  for title,key in titles.items():assert r[title]==str(want[r['订单行']][key]),(name,r['订单行'],key)
 files[name]={'rows':len(actual),'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
admin=User.objects.get(username='demo_admin');regression={};old_models=json.loads((ROOT/'data/pivot_before.json').read_text())
for key,old in old_models.items():
 m=AnalysisModel.objects.get(pk=key);r=analysis_engine.run_analysis(admin,m.dataset,m.definition);fields=['rows','matched','scanned','groups','components','derived_notes','truncated','dimension_label','labels','display_metric'];assert all(r.get(k)==old['result'].get(k) for k in fields),key;regression[key]={'unchanged':True}
m=AnalysisModel.objects.get(pk=50);r=analysis_engine.run_analysis(admin,m.dataset,m.definition);old=json.loads((ROOT/'data/pivot_validation.json').read_text())['grand_total'];assert all(math.isclose(r['pivot']['grand_total'][k],v,rel_tol=1e-11,abs_tol=1e-8) for k,v in old.items());regression['50']={'grand_total_unchanged':True}
metric=MetricVersion.objects.get(pk=9);assert metric.status=='published' and metric.version==6 and metric.calculation_hash==metric_registry.calculation_hash('bi_order_lines')=='aeb8f5c1183aac4f6c229bf08214b65079e3a9dbe5504d31f4113fc3e8bf82a9'
for s in TopicSnapshot.objects.all():topic_snapshots.verify(s)
note=IssueDisposition.objects.get(key='material_planning:impact:SO202609160117-001');assert note.version==1 and note.status=='待计划协调'
audit=AuditEvent.objects.get(action='material_planning.followup',object_id=note.key);assert audit.detail['business_facts_changed'] is False and audit.detail['before']['version']==0 and audit.detail['after']['version']==1
out={'baseline':str(baseline.relative_to(ROOT)),'business_sha256':h.hexdigest(),'records':110787,'source_categories':63,'active_workbooks':18,'unchanged_original_files':originals,'preserved_tables':preserved,'planning_before_sha256':hashlib.sha256(before_path.read_bytes()).hexdigest(),'all_planning_rows_unchanged':True,'prior_independent_scenarios_preserved':11,'order_relationships':cases,'policy_order_changes':changes,'browser_csv':files,'existing_models':regression,'published_metric':{'version':metric.version,'hash':metric.calculation_hash},'coordination':{'key':note.key,'version':1,'business_facts_changed':False},'test_count':850}
if len(sys.argv)>1:
 backup=Path(sys.argv[1])
 with zipfile.ZipFile(backup) as z,tempfile.TemporaryDirectory() as tmp:
  manifest=json.loads(z.read('manifest.json'))
  for f in manifest['files']:
   content=z.read(f['path']);assert len(content)==f['size'] and hashlib.sha256(content).hexdigest()==f['sha256']
  db=Path(tmp)/'restore.sqlite3';db.write_bytes(z.read('data/platform.sqlite3'))
  with sqlite3.connect(db) as restored,sqlite3.connect(ROOT/'data/platform.sqlite3') as now:
   assert restored.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
   for table in preserved:assert list(restored.execute(f'SELECT * FROM {table} ORDER BY id'))==list(now.execute(f'SELECT * FROM {table} ORDER BY id'))
  assert z.read('data/bi_design.json')==(ROOT/'data/bi_design.json').read_bytes();out['backup']={'path':str(backup),'manifest_files':len(manifest['files']),'app_tables':len(preserved),'integrity':'ok','restored_content_matches_current':True}
(ROOT/'data/material_impact_validation.json').write_text(json.dumps(out,ensure_ascii=False,indent=2));print(json.dumps({k:v for k,v in out.items() if k not in ['preserved_tables','existing_models','policy_order_changes']},ensure_ascii=False,indent=2))
