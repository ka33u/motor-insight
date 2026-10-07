"""Reconstruct every stocktake from raw imported values, audit preserved state."""
import os,sys,json,sqlite3,tempfile,zipfile,hashlib,csv,io,copy
from pathlib import Path
from collections import defaultdict,Counter
from decimal import Decimal
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings')
import django;django.setup()
from django.db import connection
from django.contrib.auth.models import User
from app.models import Record,AnalysisModel,MetricVersion,ImportBatch,Topic,TopicView,TopicSnapshot
from app import analytics,stocktake,stocktake_views,analysis_engine,targets,metric_registry
connection.cursor().execute('PRAGMA query_only=ON')
result={'synthetic':True,'baseline':'data/backups/motor-backup-20261005-095653.zip','preserved_tables':{},'preserved_original_files':0}
with zipfile.ZipFile(ROOT/result['baseline']) as z,tempfile.TemporaryDirectory() as temp:
 p=Path(temp)/'old.db';p.write_bytes(z.read('data/platform.sqlite3'))
 for item in json.loads(z.read('manifest.json'))['files']:
  if item['path'].startswith(('data/imports/','data/device_files/')):
   assert hashlib.sha256((ROOT/item['path']).read_bytes()).hexdigest()==item['sha256'];result['preserved_original_files']+=1
 with sqlite3.connect(p) as old,sqlite3.connect('file:'+str(ROOT/'data/platform.sqlite3')+'?mode=ro',uri=True) as current:
  names=lambda db:{r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")};assert names(old)==names(current)
  allowed={'app_record':318,'app_importrow':318,'app_importbatch':1}
  for table in sorted(names(old)-{'django_session','sqlite_sequence'}):
   a=old.execute('SELECT * FROM '+table+' ORDER BY rowid').fetchall();b=current.execute('SELECT * FROM '+table+' ORDER BY rowid').fetchall()
   if table=='app_auditevent':
    assert b[:len(a)]==a;result['audit_additions']=dict(Counter(r[1] for r in b[len(a):]));assert result['audit_additions']=={'import.stage':1,'import.upload':1,'import.commit':1,'import.approve':1,'stocktake.export':1},result['audit_additions']
   elif table in allowed:assert b[:len(a)]==a and len(b)-len(a)==allowed[table],table
   else:assert a==b,table
   result['preserved_tables'][table]={'before':len(a),'after':len(b)}
raw=defaultdict(list)
for record in Record.objects.all():raw[record.dataset].append(record.values)
actual=stocktake.Stocktakes();cutoff=analytics.AS_OF;num=lambda v:Decimal(str(v));expected={};source_keys=set()
key=lambda r:(r['material_id'],r['lot'],r['location'])
for run in raw['stocktake_runs']:
 lines=[r for r in raw['stocktake_lines'] if r['run_id']==run['id']];known=set()
 for o in raw['inventory_opening']:
  if o['as_of']<=run['book_at'][:10] and o['location'].startswith(run['location_prefix']):known.add(key(o))
 for m in raw['inventory_movements']:
  if m['occurred']<=run['book_at'] and m['location'].startswith(run['location_prefix']):known.add(key(m))
 unplanned=known-{key(r) for r in lines} if run['kind']=='范围全盘' else set()
 plan=next(r for r in actual.runs if r['id']==run['id']);assert {key(r) for r in plan['unplanned_lots']}==unplanned
 for line in lines:
  opens=[r for r in raw['inventory_opening'] if key(r)==key(line) and r['as_of']<=run['book_at'][:10]]
  moves=[r for r in raw['inventory_movements'] if key(r)==key(line) and r['occurred']<=run['book_at']]
  bookqty=sum((num(o['qty']) for o in opens),Decimal(0))+sum((num(m['qty_signed']) for m in moves),Decimal(0)) if opens or moves else None
  recs=sorted([r for r in raw['stocktake_recounts'] if r['line_id']==line['id'] and not r['voided'] and r['counted']<=cutoff],key=lambda r:(r['attempt'],r['counted'],r['id']))
  qty=recs[-1]['qty'] if recs else line['initial_qty'];eligible=line['initial_qty'] is not None and bookqty is not None
  variance=num(qty)-bookqty if eligible else None;initial=num(line['initial_qty'])-bookqty if eligible else None
  basis=recs[-1]['id'] if recs else None
  disps=sorted([r for r in raw['stocktake_dispositions'] if r['line_id']==line['id'] and r['recorded']<=cutoff],key=lambda r:(r['recorded'],r['id']));last=disps[-1] if disps else None
  valid_disp=bool(last and eligible and last['recount_id']==basis and num(last['confirmed_qty'])==num(qty) and (last['status']!='复核无差异' or variance==0))
  confirmed=bool(valid_disp and last['status'] in ['已确认','复核无差异']);r=actual.index[line['id']]
  assert r['eligible']==eligible and r['confirmed']==confirmed,line['id']
  for field,value in [('book_qty',bookqty),('initial_delta',initial),('variance',variance),('effective_qty',num(qty) if eligible else None)]:
   assert r[field] is None if value is None else abs(num(r[field])-value)<Decimal('.00000001'),(line['id'],field)
  expected[line['id']]={'variance':str(variance) if variance is not None else None,'initial_delta':str(initial) if initial is not None else None,'eligible':eligible,'confirmed':confirmed,'recount_id':basis}
  for ref in r['sources']:
   obj=Record.objects.get(dataset=ref['dataset'],business_key=ref['key']);assert obj.source_row_id and (ROOT/obj.source_row.batch.file_path).exists();source_keys.add((ref['dataset'],ref['key']))
assert len(expected)==195 and len(actual.rows)==195
rows=list(csv.reader(io.StringIO((ROOT/'outputs/库存盘点_有效盘差.csv').read_text(encoding='utf-8-sig'))));assert rows[4]==[label for _,label in stocktake_views.FIELDS]+['账实核对事项','处置核对事项']
selected=[r for r in actual.rows if expected[r['id']]['eligible'] and num(expected[r['id']]['variance'])!=0]
string=lambda v:'' if v is None else str(v)
assert rows[5:]==[[string(r.get(k)) for k,_ in stocktake_views.FIELDS]+['；'.join(r['issues']),'；'.join(r['disposition_issues'])] for r in selected]
result['independent_checks']={'runs':2,'lines':len(expected),'csv_variance_rows':len(selected),'unique_source_records':len(source_keys),'scope_unplanned_lots':sum(len(r['unplanned_lots']) for r in actual.runs)}
result['line_results']=expected;result['summary']=stocktake.summary(actual.rows);result['csv_sha256']=hashlib.sha256((ROOT/'outputs/库存盘点_有效盘差.csv').read_bytes()).hexdigest()
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
result['counts']={'records':Record.objects.count(),'datasets':Record.objects.values('dataset').distinct().count(),'workbooks':ImportBatch.objects.exclude(status='superseded').count(),'models':AnalysisModel.objects.count(),'topics':Topic.objects.count(),'views':TopicView.objects.count(),'snapshots':TopicSnapshot.objects.count()};assert tuple(result['counts'].values())==(117185,83,23,52,21,6,4)
(ROOT/'data/stocktake_validation.json').write_text(json.dumps(result,ensure_ascii=False,indent=2));print(json.dumps({k:v for k,v in result.items() if k not in ['line_results','preserved_tables']},ensure_ascii=False))
