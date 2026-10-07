"""Independently reconcile procurement promises and preserve the existing demo."""
import os,sys,json,sqlite3,tempfile,zipfile,hashlib,csv,io,copy
from pathlib import Path
from collections import defaultdict,Counter
from decimal import Decimal
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings')
import django;django.setup()
from django.db import connection
from django.contrib.auth.models import User
from app.models import Record,MetricVersion,AnalysisModel,ImportBatch,Topic,TopicView,TopicSnapshot
from app.schema import SCHEMAS
from app import analytics,purchase_commitments as eng,purchase_commitment_views as views,supply,analysis_engine,targets,metric_registry
connection.cursor().execute('PRAGMA query_only=ON')
result={'synthetic':True,'baseline':'data/backups/motor-backup-20261005-183625.zip','preserved_tables':{},'preserved_original_files':0}
with zipfile.ZipFile(ROOT/result['baseline']) as z,tempfile.TemporaryDirectory() as temp:
 p=Path(temp)/'old.db';p.write_bytes(z.read('data/platform.sqlite3'))
 for item in json.loads(z.read('manifest.json'))['files']:
  if item['path'].startswith(('data/imports/','data/device_files/')):
   assert hashlib.sha256((ROOT/item['path']).read_bytes()).hexdigest()==item['sha256'];result['preserved_original_files']+=1
 with sqlite3.connect(p) as old,sqlite3.connect('file:'+str(ROOT/'data/platform.sqlite3')+'?mode=ro',uri=True) as current:
  names=lambda db:{r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")};assert names(old)==names(current)
  allowed={'app_record':518,'app_importrow':518,'app_importbatch':1}
  for table in sorted(names(old)-{'django_session','sqlite_sequence'}):
   a=old.execute('SELECT * FROM '+table+' ORDER BY rowid').fetchall();b=current.execute('SELECT * FROM '+table+' ORDER BY rowid').fetchall()
   if table=='app_auditevent':
    assert b[:len(a)]==a;result['audit_additions']=dict(Counter(r[1] for r in b[len(a):]));assert set(result['audit_additions'])<={'import.stage','import.upload','import.commit','import.approve','purchase_commitments.export','purchase_commitments.segments_export'},result['audit_additions']
   elif table in allowed:assert b[:len(a)]==a and len(b)-len(a)==allowed[table],table
   else:assert a==b,table
   result['preserved_tables'][table]={'before':len(a),'after':len(b)}
  before_raw={k:[] for k in SCHEMAS}
  for ds,val in old.execute('SELECT dataset,"values" FROM app_record'):before_raw[ds].append(json.loads(val))
raw=defaultdict(list)
for record in Record.objects.all():raw[record.dataset].append(record.values)
cutoff=analytics.AS_OF;today=cutoff[:10];D=lambda v:Decimal(str(v));cases=json.loads((ROOT/'data/purchase_commitments_scenario.json').read_text())['cases']
versions=defaultdict(list);segments=defaultdict(list);receipts=defaultdict(list)
for v in raw['purchase_commitment_versions']:versions[v['purchase_line_id']].append(v)
for s in raw['purchase_commitment_lines']:segments[s['version_id']].append(s)
for r in raw['receipts']:
 if r['received']<=cutoff:receipts[r['purchase_line_id']].append(r)
actual=eng.Commitments();due=ontime=current_due=current_ontime=changed=late=0;source_keys=set();allocation_slices=0
for p in raw['purchase_lines']:
 r=actual.index[p['id']];arrivals=sorted(receipts[p['id']],key=lambda x:(x['received'],x['id']));received=sum((D(x['qty']) for x in arrivals),Decimal(0));mature=p['due']<today;timely=sum((D(x['qty']) for x in arrivals if x['received'][:10]<=p['due']),Decimal(0))>=D(p['qty'])
 assert (r['original_due_sample'],r['original_on_time_full'])==(int(mature),int(mature and timely));assert D(r['received_qty'])==received
 due+=mature;ontime+=mature and timely
 active=[v for v in versions[p['id']] if v['status']=='模拟确认' and all(not v.get(k) or v[k]<=cutoff for k in ['confirmed','effective','registered'])]
 chosen=max(active,key=lambda v:(v['version'],v['registered'],v['id'])) if active else None
 assert r['version_id']==(chosen['id'] if chosen else None)
 assert r['valid']==(p['id'] not in cases)
 if p['id'] in cases:
  assert r['issues'] and r['segments']==[] and r['overdue_unreceived'] is None
 else:
  ss=sorted(segments[chosen['id']],key=lambda x:(x['due'],x['sequence'],x['id']));assert sum(D(s['qty']) for s in ss)==D(p['qty']);assert len(ss)==chosen['line_count']
  remaining={x['id']:D(x['qty']) for x in arrivals};expected_slices=[]
  for source,s in zip(ss,r['segments']):
   left=D(source['qty']);timelyqty=Decimal(0);xs=[]
   for rec in arrivals:
    take=min(left,remaining[rec['id']])
    if take<=0:continue
    before=remaining[rec['id']];remaining[rec['id']]-=take;left-=take;is_due=rec['received'][:10]<=source['due'];timelyqty+=take if is_due else 0
    xs.append((rec['id'],take,before,remaining[rec['id']],is_due));allocation_slices+=1
   assert [(x['receipt_id'],D(x['qty']),D(x['receipt_before']),D(x['receipt_after']),x['by_due']) for x in s['slices']]==xs
   matureseg=source['due']<today;complete=timelyqty==D(source['qty']);current_due+=matureseg;current_ontime+=matureseg and complete
   assert (s['due_sample'],s['on_time_full'])==(matureseg,matureseg and complete)
   assert D(s['arrived_qty'])==D(source['qty'])-left and D(s['remaining_qty'])==left and D(s['on_time_qty'])==timelyqty
  assert all(x==0 for x in remaining.values());changed+=chosen['version']>1 or len(ss)>1 or ss[0]['due']!=p['due'];late+=(chosen['version']>1 or len(ss)>1 or ss[0]['due']!=p['due']) and chosen['effective'][:10]>p['due']
 for ref in r['sources']:
  obj=Record.objects.select_related('source_row__batch').get(dataset=ref['dataset'],business_key=ref['key']);assert obj.source_row_id and (ROOT/obj.source_row.batch.file_path).exists();source_keys.add((ref['dataset'],ref['key']))
assert (ontime,due,current_ontime,current_due,changed,late)==(114,144,155,177,52,25)
old_supply=supply.SupplyData(before_raw);new_supply=supply.SupplyData(raw)
assert [supply.clean(r) for r in old_supply.po_rows]==[supply.clean(r) for r in new_supply.po_rows]
assert [supply.clean(r) for r in old_supply.lots]==[supply.clean(r) for r in new_supply.lots]
sorter=lambda r:(not bool(r['issues']),not ('overdue' in r['flags']),r['id']);selected=sorted(actual.rows,key=sorter);string=lambda v:'' if v is None else str(v)
file=ROOT/'outputs/采购承诺_全部采购行.csv';rows=list(csv.reader(io.StringIO(file.read_text(encoding='utf-8-sig'))));assert rows[4]==[label for _,label in views.FIELDS]+['核对事项'];assert rows[5:]==[[string(r.get(k)) for k,_ in views.FIELDS]+['；'.join(r['issues'])] for r in selected]
file=ROOT/'outputs/采购承诺_全部当前分段.csv';rows=list(csv.reader(io.StringIO(file.read_text(encoding='utf-8-sig'))));expected=[]
for r in selected:
 for s in r['segments'] if r['valid'] else [{}]:expected.append([string(x) for x in [r['id'],r['unit'],r['version_id'],r['valid']]]+[string(s.get(k)) for k,_ in views.SEGMENTS]+['；'.join(r['issues'])])
assert rows[5:]==expected and len(expected)==196
base=json.loads((ROOT/'data/assembly_plans_before.json').read_text());admin=User.objects.get(username='demo_admin')
def projection(value):
 value=copy.deepcopy(value);value.pop('metric_receipt',None)
 for k in ['pivot','scatter']:
  if value.get(k):value[k].pop('revision',None)
 return json.loads(json.dumps(value,ensure_ascii=False,default=str))
for mid,old in base['models'].items():
 model=AnalysisModel.objects.get(pk=mid);assert projection(analysis_engine.run_analysis(admin,model.dataset,model.definition))==projection(old),mid
assert {r['id']:json.loads(json.dumps(r,default=str)) for r in targets.Targets(admin).rows.values()}=={r['id']:r for r in base['targets']}
metric=MetricVersion.objects.get(metric__key='DELIVERY_OTIF',version=8,status='published');assert metric.calculation_hash==metric_registry.calculation_hash(metric.metric.dataset)=='9d9a5af3d45172eca16790d628a36bc6acbe18d1e2a811a66a5b5fbff7037fe3'
result.update(summary=eng.summary(actual.rows),independent_checks={'purchase_lines':144,'mature_original':due,'mature_current_segments':current_due,'allocation_slices':allocation_slices,'unique_source_records':len(source_keys),'csv_purchase_rows':144,'csv_segment_rows':196,'original_purchase_and_stock_unchanged':True},preserved_results={'models':52,'targets':33,'metric_version':8})
result['counts']={'records':Record.objects.count(),'datasets':Record.objects.values('dataset').distinct().count(),'workbooks':ImportBatch.objects.exclude(status='superseded').count(),'models':AnalysisModel.objects.count(),'topics':Topic.objects.count(),'views':TopicView.objects.count(),'snapshots':TopicSnapshot.objects.count()};assert tuple(result['counts'].values())==(117935,87,25,52,21,6,4)
(ROOT/'data/purchase_commitments_validation.json').write_text(json.dumps(result,ensure_ascii=False,indent=2));print(json.dumps({k:v for k,v in result.items() if k!='preserved_tables'},ensure_ascii=False))
