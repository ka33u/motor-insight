"""Independent raw-data reconstruction and preservation audit for inventory age."""
import os,sys,json,sqlite3,tempfile,zipfile,hashlib,csv,io,copy,bisect
from pathlib import Path
from collections import defaultdict,Counter
from datetime import date
from decimal import Decimal
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings')
import django;django.setup()
from django.db import connection
from django.contrib.auth.models import User
from app.models import Record,AnalysisModel,MetricVersion,ImportBatch,Topic,TopicView,TopicSnapshot
from app import analytics,inventory_age as eng,inventory_age_views as views,analysis_engine,targets,metric_registry
connection.cursor().execute('PRAGMA query_only=ON')
result={'synthetic':True,'baseline':'data/backups/motor-backup-20261005-114926.zip','preserved_tables':{},'preserved_original_files':0}
with zipfile.ZipFile(ROOT/result['baseline']) as z,tempfile.TemporaryDirectory() as temp:
 p=Path(temp)/'old.db';p.write_bytes(z.read('data/platform.sqlite3'))
 for item in json.loads(z.read('manifest.json'))['files']:
  if item['path'].startswith(('data/imports/','data/device_files/')):
   assert hashlib.sha256((ROOT/item['path']).read_bytes()).hexdigest()==item['sha256'];result['preserved_original_files']+=1
 with sqlite3.connect(p) as old,sqlite3.connect('file:'+str(ROOT/'data/platform.sqlite3')+'?mode=ro',uri=True) as current:
  names=lambda db:{r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")};assert names(old)==names(current)
  allowed={'app_record':232,'app_importrow':232,'app_importbatch':1}
  for table in sorted(names(old)-{'django_session','sqlite_sequence'}):
   a=old.execute('SELECT * FROM '+table+' ORDER BY rowid').fetchall();b=current.execute('SELECT * FROM '+table+' ORDER BY rowid').fetchall()
   if table=='app_auditevent':
    assert b[:len(a)]==a;result['audit_additions']=dict(Counter(r[1] for r in b[len(a):]));assert result['audit_additions']=={'import.stage':1,'import.upload':1,'import.commit':1,'import.approve':1,'inventory_age.export':1},result['audit_additions']
   elif table in allowed:assert b[:len(a)]==a and len(b)-len(a)==allowed[table],table
   else:assert a==b,table
   result['preserved_tables'][table]={'before':len(a),'after':len(b)}
raw=defaultdict(list)
for record in Record.objects.select_related('source_row__batch').all():raw[record.dataset].append(record.values)
cutoff=analytics.AS_OF;day=date.fromisoformat(cutoff[:10]);num=lambda v:Decimal(str(v));facts=defaultdict(lambda:dict(open=[],move=[],status=[]));expected={};source_keys=set()
key=lambda r:(r['material_id'],r['lot'],r['location'])
for ds,col,stamp in [('inventory_opening','open','as_of'),('inventory_movements','move','occurred'),('inventory_status_events','status','occurred')]:
 for r in raw[ds]:
  if r[stamp]<=(cutoff[:10] if stamp=='as_of' else cutoff):facts[key(r)][col].append(r)
materials={r['id']:r for r in raw['materials']}
for ident,items in facts.items():
 mid,lot,loc=ident;qty=sum((num(r['qty']) for r in items['open']),Decimal(0))+sum((num(r['qty_signed']) for r in items['move']),Decimal(0));assert qty>0
 profiles=sorted([r for r in raw['inventory_lot_dates'] if r['material_id']==mid and r['lot']==lot and not r['voided'] and r['registered']<=cutoff],key=lambda r:r['version'])
 policies=sorted([r for r in raw['inventory_age_policies'] if r['material_id']==mid and r['status']!='草稿' and r['registered']<=cutoff and r['effective_from']<=cutoff[:10]],key=lambda r:r['version'])
 profile=profiles[-1] if profiles else None;rule=policies[-1];first=profile['first_stock_date'] if profile else None;exp=profile['expires'] if profile else None
 age=(day-date.fromisoformat(first)).days if first else None;remaining=(date.fromisoformat(exp)-day).days if exp else None
 expiry='不适用' if profile and profile['expiry_mode']=='不适用' else '未知' if remaining is None else '过期' if remaining<0 else '临期' if remaining<=rule['warning_days'] else '有效'
 state=sorted(items['status'],key=lambda r:(r['occurred'],r['id']))[-1]['to_status'] if items['status'] else items['open'][0]['status'] if items['open'] else '可用'
 bucket='日期未知' if age is None else ['0—30天','31—60天','61—90天','91—180天','181—365天','超过365天'][bisect.bisect_right([31,61,91,181,366],age)]
 overage=bool(age is not None and age>rule['age_limit_days']);ranked=bool(state=='可用' and age is not None and expiry in ['不适用','有效','临期']);unknown=bool(age is None or expiry=='未知')
 last_out=max((r['occurred'] for r in items['move'] if r['qty_signed']<0),default=None)
 expected[ident]={'balance_qty':qty,'state':state,'age_days':age,'age_bucket':bucket,'expires':exp,'first_stock_date':first,'expiry_days':remaining,'expiry_state':expiry,'overage':overage,'rank_eligible':ranked,'last_outbound':last_out,'date_profile_id':profile['id'] if profile else None,'date_version':profile['version'] if profile else None,'policy_id':rule['id'],'policy_version':rule['version'],'unknown':unknown,'unit':materials[mid]['unit']}
for order in ['fifo','fefo']:
 actual=eng.InventoryAge(order=order);ranks={};groups=defaultdict(list)
 for ident,r in expected.items():
  if r['rank_eligible']:groups[ident[0]].append((ident,r))
 for rows in groups.values():
  sorting=(lambda pair:(pair[1]['first_stock_date'],pair[0][1],pair[0][2])) if order=='fifo' else (lambda pair:(pair[1]['expires'] or '9999-12-31',pair[1]['first_stock_date'],pair[0][1],pair[0][2]))
  for rank,(ident,_) in enumerate(sorted(rows,key=sorting),1):ranks[ident]=rank
 assert len(actual.rows)==len(expected)==173
 for r in actual.rows:
  ident=key(r);e=expected[ident]
  for field,value in e.items():
   if field=='unknown':assert ('unknown' in r['flags'])==value
   elif field=='balance_qty':assert num(r[field])==value
   else:assert r[field]==value,(ident,field,r[field],value)
  assert r['reference_rank']==ranks.get(ident)
  for ref in r['sources']:
   obj=Record.objects.get(dataset=ref['dataset'],business_key=ref['key']);assert obj.source_row_id and (ROOT/obj.source_row.batch.file_path).exists();source_keys.add((ref['dataset'],ref['key']))
 summary=eng.summary(actual.rows)
 for u in summary['units']:
  grouped=[e for e in expected.values() if e['unit']==u['unit']];balance=sum((e['balance_qty'] for e in grouped),Decimal(0));assert num(u['known_balance'])==balance
  for col,field in [('buckets','age_bucket'),('expiry','expiry_state')]:
   assert sum((num(x['qty']) for x in u[col]),Decimal(0))==balance
   for b in u[col]:
    selected=[e for e in grouped if e[field]==b['name']];assert b['rows']==len(selected);assert num(b['qty'])==sum((e['balance_qty'] for e in selected),Decimal(0))
assert (summary['overage'],summary['near'],summary['expired'],summary['unknown'],summary['ranked'])==(30,6,7,10,156)
actual=eng.InventoryAge();rows=list(csv.reader(io.StringIO((ROOT/'outputs/库存库龄_全部批次.csv').read_text(encoding='utf-8-sig'))));assert rows[4]==[label for _,label in views.FIELDS]+['核对事项']
string=lambda v:'' if v is None else str(v)
assert rows[5:]==[[string(r.get(k)) for k,_ in views.FIELDS]+['；'.join(r['issues'])] for r in actual.rows]
result['independent_checks']={'lots':len(expected),'ranking_methods':['fifo','fefo'],'csv_rows':len(rows)-5,'unique_source_records':len(source_keys),'unit_partitions_reconcile':True};result['summary']=summary;result['csv_sha256']=hashlib.sha256((ROOT/'outputs/库存库龄_全部批次.csv').read_bytes()).hexdigest()
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
result['counts']={'records':Record.objects.count(),'datasets':Record.objects.values('dataset').distinct().count(),'workbooks':ImportBatch.objects.exclude(status='superseded').count(),'models':AnalysisModel.objects.count(),'topics':Topic.objects.count(),'views':TopicView.objects.count(),'snapshots':TopicSnapshot.objects.count()};assert tuple(result['counts'].values())==(117417,85,24,52,21,6,4)
(ROOT/'data/inventory_age_validation.json').write_text(json.dumps(result,ensure_ascii=False,indent=2));print(json.dumps({k:v for k,v in result.items() if k!='preserved_tables'},ensure_ascii=False))
