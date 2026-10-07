"""Independent raw-record stage reconstruction and preservation for the supply bridge."""
import os,sys,json,sqlite3,tempfile,zipfile,hashlib,csv,io,copy
from pathlib import Path
from collections import defaultdict,Counter
from decimal import Decimal
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings')
import django;django.setup()
from django.db import connection
from django.contrib.auth.models import User
from app.models import Record,AnalysisModel,MetricVersion,ImportBatch,Topic,TopicView,TopicSnapshot
from app import analytics,material_planning as prep,material_supply as flow,analysis_engine,targets,metric_registry
from app.material_supply_views import FIELDS
connection.cursor().execute('PRAGMA query_only=ON')
result={'synthetic':True,'baseline':'data/backups/motor-backup-20261005-074329.zip','preserved_tables':{},'preserved_original_files':0}
with zipfile.ZipFile(ROOT/result['baseline']) as z,tempfile.TemporaryDirectory() as temp:
 p=Path(temp)/'old.db';p.write_bytes(z.read('data/platform.sqlite3'))
 for item in json.loads(z.read('manifest.json'))['files']:
  if item['path'].startswith(('data/imports/','data/device_files/')):
   assert hashlib.sha256((ROOT/item['path']).read_bytes()).hexdigest()==item['sha256'];result['preserved_original_files']+=1
 with sqlite3.connect(p) as old,sqlite3.connect('file:'+str(ROOT/'data/platform.sqlite3')+'?mode=ro',uri=True) as current:
  names=lambda db:{r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")};assert names(old)==names(current)
  for table in sorted(names(old)-{'django_session','sqlite_sequence'}):
   a=old.execute('SELECT * FROM '+table+' ORDER BY rowid').fetchall();b=current.execute('SELECT * FROM '+table+' ORDER BY rowid').fetchall()
   if table=='app_auditevent':
    assert b[:len(a)]==a;result['audit_additions']=dict(Counter(r[1] for r in b[len(a):]));assert result['audit_additions']=={'material_supply.export':1}
   else:assert a==b,table
   result['preserved_tables'][table]={'before':len(a),'after':len(b)}
raw=defaultdict(list)
for record in Record.objects.all():raw[record.dataset].append(record.values)
cutoff=analytics.AS_OF;num=lambda v:Decimal(str(v));expected={};all_refs=set();plan,rev=prep.current(prep.filters({'tab':'materials','stage':'short'}))
for key in plan.material_rows:
 out=flow.build(plan,key);rows={p['id']:p for p in out['purchases']};totals={k:Decimal(0) for k in flow.STAGES};ordered=Decimal(0);late=Decimal(0);date_qty=defaultdict(lambda:Decimal(0))
 purchases=[p for p in raw['purchase_lines'] if p['material_id']==key and p['ordered']<=cutoff[:10]]
 assert set(rows)=={p['id'] for p in purchases}
 for p in purchases:
  stages={k:Decimal(0) for k in flow.STAGES};arrived=Decimal(0)
  for r in [r for r in raw['receipts'] if r['purchase_line_id']==p['id'] and r['received']<=cutoff]:
   arrived+=num(r['qty']);inspections=sorted([q for q in raw['incoming_inspections'] if q['receipt_id']==r['id'] and q['inspected']<=cutoff],key=lambda q:(q['inspected'],q['id']))
   last=inspections[-1] if inspections else None;approved=bool(last and last['result']=='合格' and last['disposition']=='批准入库' and r['status']=='检验合格')
   posted=sum((num(m['qty_signed']) for m in raw['inventory_movements'] if m['reference']==r['id'] and m['occurred']<=cutoff),Decimal(0));assert 0<=posted<=num(r['qty'])
   stages['posted']+=posted;stages['approved_unposted' if approved else 'held']+=num(r['qty'])-posted
  stages['unreceived']=num(p['qty'])-arrived;assert sum(stages.values())==num(p['qty'])
  assert rows[p['id']]['valid'],p['id']
  for k in stages:assert num(rows[p['id']][k])==stages[k],(p['id'],k);totals[k]+=stages[k]
  ordered+=num(p['qty'])
  if stages['unreceived']:
   date_qty[p['due']]+=stages['unreceived']
   if p['due']<cutoff[:10]:late+=stages['unreceived']
 assert num(out['summary']['ordered'])==ordered
 assert all(num(out['summary'][k])==v for k,v in totals.items())
 assert num(out['summary']['overdue_unreceived'])==late
 assert {r['due']:num(r['qty']) for r in out['promises']}==date_qty
 for ref in out['sources']:
  rec=Record.objects.get(dataset=ref['dataset'],business_key=ref['key']);assert rec.source_row_id and rec.source_row.batch.file_path and (ROOT/rec.source_row.batch.file_path).exists();all_refs.add((ref['dataset'],ref['key']))
 expected[key]={'summary':out['summary'],'sources':len(out['sources'])}
result['independent_checks']={'materials':len(expected),'purchase_lines':sum(x['summary']['purchase_lines'] for x in expected.values()),'unique_source_records':len(all_refs)};result['material_results']=expected
key='02.01.0006';out=flow.build(plan,key);rows=list(csv.reader(io.StringIO((ROOT/'outputs/物料供应进度_轴承06.csv').read_text(encoding='utf-8-sig'))))
assert rows[3]==[label for _,label in FIELDS]+['纳入数量核对','资料问题']
string=lambda v:'' if v is None else str(v)
assert rows[4:]==[[string(p.get(k)) for k,_ in FIELDS]+['是',''] for p in out['purchases']]
result['browser_csv']={'material':key,'rows':len(rows)-4,'sha256':hashlib.sha256((ROOT/'outputs/物料供应进度_轴承06.csv').read_bytes()).hexdigest()}
admin=User.objects.get(username='demo_admin');base=json.loads((ROOT/'data/assembly_plans_before.json').read_text())
def projection(value):
 value=copy.deepcopy(value);value.pop('metric_receipt',None)
 for k in ['pivot','scatter']:
  if value.get(k):value[k].pop('revision',None)
 return json.loads(json.dumps(value,ensure_ascii=False,default=str))
for mid,old in base['models'].items():
 model=AnalysisModel.objects.get(pk=mid);assert projection(analysis_engine.run_analysis(admin,model.dataset,model.definition))==projection(old),mid
assert {r['id']:json.loads(json.dumps(r,default=str)) for r in targets.Targets(admin).rows.values()}=={r['id']:r for r in base['targets']}
result['preserved_results']={'models':52,'targets':33}
metric=MetricVersion.objects.get(metric__key='DELIVERY_OTIF',version=8,status='published');assert metric.calculation_hash==metric_registry.calculation_hash(metric.metric.dataset)=='9d9a5af3d45172eca16790d628a36bc6acbe18d1e2a811a66a5b5fbff7037fe3';result['metric_version']=8
result['counts']={'records':Record.objects.count(),'datasets':Record.objects.values('dataset').distinct().count(),'workbooks':ImportBatch.objects.exclude(status='superseded').count(),'models':AnalysisModel.objects.count(),'topics':Topic.objects.count(),'views':TopicView.objects.count(),'snapshots':TopicSnapshot.objects.count()};assert tuple(result['counts'].values())==(116867,79,22,52,21,6,4)
(ROOT/'data/material_supply_validation.json').write_text(json.dumps(result,ensure_ascii=False,indent=2));print(json.dumps({k:v for k,v in result.items() if k not in ['material_results','preserved_tables']},ensure_ascii=False))
