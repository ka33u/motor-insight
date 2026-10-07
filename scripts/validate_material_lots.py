"""Rebuild date-aware stock allocation from raw imported rows and audit preservation."""
import os,sys,json,sqlite3,tempfile,zipfile,hashlib,csv,io,copy,math
from pathlib import Path
from collections import defaultdict,Counter
from decimal import Decimal,ROUND_CEILING
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings')
import django;django.setup()
from django.db import connection
from django.contrib.auth.models import User
from app.models import Record,AnalysisModel,MetricVersion,ImportBatch,Topic,TopicView,TopicSnapshot
from app import analytics,material_planning as eng,material_planning_views as views,material_impact,analysis_engine,targets,metric_registry
connection.cursor().execute('PRAGMA query_only=ON')
result={'synthetic':True,'baseline':'data/backups/motor-backup-20261005-125119.zip','preserved_tables':{},'preserved_original_files':0}
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
    assert b[:len(a)]==a;result['audit_additions']=dict(Counter(r[1] for r in b[len(a):]));assert result['audit_additions']=={'material_lots.export':1},result['audit_additions']
   else:assert a==b,table
   result['preserved_tables'][table]={'before':len(a),'after':len(b)}
raw=defaultdict(list)
for ds,value in Record.objects.values_list('dataset','values'):raw[ds].append(value)
D=lambda v:Decimal(str(v));zero=Decimal(0);cutoff=analytics.AS_OF;day=cutoff[:10]
materials={r['id']:r for r in raw['materials']};work={r['id']:r for r in raw['work_orders']};people={r['id'] for r in raw['employees']}
key=lambda r:(r['material_id'],r['lot'],r['location'])
lots=defaultdict(lambda:{'balance':zero,'events':[],'observed':[],'opening':[]});issued=defaultdict(lambda:zero)
for r in raw['inventory_opening']:
 if r['as_of']<=day:
  l=lots[key(r)];l['balance']+=D(r['qty']);l['opening'].append(r);l['observed'].append(r['as_of'])
for r in raw['inventory_movements']:
 if r['occurred']<=cutoff:
  l=lots[key(r)];l['balance']+=D(r['qty_signed']);l['observed'].append(r['occurred'][:10])
  if r['movement']=='生产领料':issued[r['work_order_id'],r['material_id']]-=D(r['qty_signed'])
for r in raw['inventory_status_events']:
 if r['occurred']<=cutoff:lots[key(r)]['events'].append(r)
candidate={};usable=defaultdict(lambda:zero)
for ident,l in lots.items():
 mid,lot,location=ident;assert l['balance']>0 and len(l['opening'])<=1
 state=max(l['events'],key=lambda r:(r['occurred'],r['id']))['to_status'] if l['events'] else l['opening'][0]['status'] if l['opening'] else '可用'
 if state=='可用':usable[mid]+=l['balance']
 profiles=[r for r in raw['inventory_lot_dates'] if r['material_id']==mid and r['lot']==lot and not r['voided'] and r['registered']<=cutoff]
 rules=[r for r in raw['inventory_age_policies'] if r['material_id']==mid and r['status']!='草稿' and r['registered']<=cutoff and r['effective_from']<=day]
 profile=max(profiles,key=lambda r:r['version']) if profiles else None;rule=max(rules,key=lambda r:r['version']) if rules else None
 if not profile or not rule:continue
 first=profile['first_stock_date'];made=profile['manufactured'];expires=profile['expires'];mode=profile['expiry_mode']
 good_rule=rule['status']=='模拟确认' and rule['owner_id'] in people and bool(rule['reason'].strip()) and (rule['age_limit_days'] is None or rule['age_limit_days']>0) and (rule['warning_days'] is None or rule['warning_days']>=0)
 good_profile=bool(first and first<=day and first<=min(l['observed']) and profile['owner_id'] in people and profile['document_no'].strip() and (not made or made<=first) and (not made or not expires or expires>=made))
 valid_expiry=(mode=='不适用' and not expires and not rule['expiry_required']) or (mode=='固定日期' and expires and expires>=day)
 if state!='可用' or not good_rule or not good_profile or not valid_expiry:continue
 candidate[ident]={'lot':lot,'location':location,'balance_qty':l['balance'],'first_stock_date':first,'expires':expires,'date_profile_id':profile['id'],'date_version':profile['version'],'policy_id':rule['id'],'policy_version':rule['version']}
assert len(lots)==173 and len(candidate)==156
boms=defaultdict(list);assembled=Counter()
for r in raw['bom']:boms[r['product_id'],r['version']].append(r)
for r in raw['units']:
 if r['assembly_at']<=cutoff:assembled[r['work_order_id']]+=1
base=json.loads((ROOT/'data/material_lots_before.json').read_text());result['legacy_cases']=[];result['date_cases']=[];checked=0;selected_sources=set();csv_expectation=None
def close(a,b):assert a is not None and b is not None and math.isclose(float(a),float(b),rel_tol=1e-11,abs_tol=1e-8),(a,b)
for previous in base:
 conf=previous['scope'];legacy=eng.MaterialPlanning(raw,eng.filters(conf))
 actual={'scope':conf,'summary':legacy.summary(),'orders':eng.clean(legacy.ordered),'materials':eng.clean(legacy.material_rows),'pool':eng.clean(legacy.pool),'impact':eng.clean(material_impact.OrderImpact(legacy).rows)}
 assert actual==previous,conf;result['legacy_cases'].append({'filters':conf,'unchanged':True})
 for policy in ['fifo','fefo']:
  f=eng.filters({**conf,'lot_policy':policy});actual=eng.MaterialPlanning(raw,f);pool={};initial={};slices={};allocations=[];states=Counter();net=defaultdict(lambda:zero)
  required={i['material_id'] for w in previous['orders'] for i in w['items']}
  for mid in required:
   rs=[copy.deepcopy(r) for ident,r in candidate.items() if ident[0]==mid]
   rs.sort(key=lambda r:(r['first_stock_date'],r['lot'],r['location']) if policy=='fifo' else (r['expires'] or '9999-12-31',r['first_stock_date'],r['lot'],r['location']))
   buffer=D(materials[mid]['safety_qty']) if f['stock_policy']=='protect_safety' else zero
   for rank,r in enumerate(rs,1):r.update(reference_rank=rank,retained=zero,initial=r['balance_qty'],remaining=r['balance_qty'])
   for r in reversed(rs):keep=min(buffer,r['initial']);r['retained']=keep;r['initial']-=keep;r['remaining']-=keep;buffer-=keep
   slices[mid]=rs;pool[mid]=initial[mid]=sum((r['initial'] for r in rs),zero)
  for order in previous['orders']:
   w=work[order['id']];a=actual.orders[w['id']];excluded=w['status'] in ['已取消','完工待清尾','已完工','已关闭'] or assembled[w['id']]>=w['planned_qty']
   assert excluded==order['excluded'];assert a['sequence']==order['sequence'] and not a['issues']
   if excluded:assert a['state']=='excluded';states['excluded']+=1;continue
   use=max(day,w['planned_start']);gross=defaultdict(lambda:zero)
   for b in boms[w['product_id'],w['bom_version']]:gross[b['material_id']]+=D(w['planned_qty'])*D(b['qty'])*(1+D(b['scrap_allowance']))
   wants={mid:max(zero,(g.to_integral_value(rounding=ROUND_CEILING) if materials[mid]['unit']=='件' else g)-issued[w['id'],mid]) for mid,g in gross.items()}
   available={mid:sum((r['remaining'] for r in slices[mid] if not r['expires'] or r['expires']>=use),zero) for mid in wants}
   state='short' if any(wants[mid]>available[mid] for mid in wants) else 'covered';states[state]+=1;assert a['state']==state
   for item in a['items']:
    mid=item['material_id'];need=wants[mid];net[mid]+=need;assert item['use_day']==use
    for k,v in [('gross_unrounded',gross[mid]),('issued_qty',issued[w['id'],mid]),('remaining_required',need),('before_pool',pool[mid]),('date_available_pool',available[mid]),('date_excluded_at_use',pool[mid]-available[mid]),('gap',max(zero,need-available[mid]))]:close(item[k],v)
    parts=[];left=need
    if state=='covered':
     for r in slices[mid]:
      if r['expires'] and r['expires']<use:continue
      take=min(left,r['remaining'])
      if take>0:
       p={**r,'qty':take,'before':r['remaining'],'after':r['remaining']-take,'use_day':use};parts.append(p);r['remaining']-=take;left-=take
      if left==0:break
     assert left==0;pool[mid]-=need
    assert len(parts)==len(item['lot_allocations'])
    for p,ap in zip(parts,item['lot_allocations']):
     for k,v in p.items():
      if isinstance(v,Decimal):close(ap[k],v)
      else:assert ap[k]==v,(k,ap[k],v)
     allocations.append({'sequence':a['sequence'],'work_order_id':w['id'],'product_id':w['product_id'],'material_id':mid,'material':materials[mid]['name'],'unit':materials[mid]['unit'],**p})
    close(item['simulated_allocated'],need if state=='covered' else zero);close(item['after_pool'],pool[mid]);checked+=1
   for ref in actual.detail('orders',w['id'])['sources']:
    source_key=(ref['dataset'],ref['key'])
    if source_key not in selected_sources:
     obj=Record.objects.select_related('source_row__batch').get(dataset=ref['dataset'],business_key=ref['key']);assert obj.source_row_id and (ROOT/obj.source_row.batch.file_path).exists();selected_sources.add(source_key)
  for mid,m in actual.material_rows.items():
   for k,v in [('usable_state_qty',usable[mid]),('date_candidate_qty',sum((r['balance_qty'] for r in slices[mid]),zero)),('initial_pool',initial[mid]),('net_demand',net[mid]),('simulated_allocated',initial[mid]-pool[mid]),('remaining_pool',pool[mid])]:close(m[k],v)
   close(sum((r['remaining'] for r in slices[mid]),zero),pool[mid]);close(sum((p['qty'] for p in allocations if p['material_id']==mid),zero),initial[mid]-pool[mid])
  summary=actual.summary();assert all(summary[s]==states[s] for s in ['covered','short','excluded','attention'])
  result['date_cases'].append({'filters':{**conf,'lot_policy':policy},'summary':summary,'batch_slices':len(allocations)})
  if conf=={'order':'start','stock_policy':'protect_safety'} and policy=='fefo':csv_expectation=allocations
path=ROOT/'outputs/备料批次_FEFO_完整计划.csv';lines=list(csv.reader(io.StringIO(path.read_text(encoding='utf-8-sig'))));f=json.loads(lines[0][4]);assert (f['lot_policy'],f['order'],f['stock_policy'],f['tab'],f['stage'])==('fefo','start','protect_safety','orders','active')
assert lines[4]==[label for _,label in views.LOT_FIELDS];string=lambda v:'' if v is None else str(eng.clean(v))
assert lines[5:]==[[string(r.get(k)) for k,_ in views.LOT_FIELDS] for r in csv_expectation]
assert lines[3][1]==eng.receipt(eng.filters(f),analytics.revision())
result['independent_checks']={'ledger_lots':len(lots),'candidate_lots':len(candidate),'order_material_checks':checked,'unique_source_records':len(selected_sources),'csv_rows':len(lines)-5,'csv_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'no_facts_or_coordination_changed':True}
admin=User.objects.get(username='demo_admin');base_results=json.loads((ROOT/'data/assembly_plans_before.json').read_text())
def projection(value):
 value=copy.deepcopy(value);value.pop('metric_receipt',None)
 for k in ['pivot','scatter']:
  if value.get(k):value[k].pop('revision',None)
 return json.loads(json.dumps(value,ensure_ascii=False,default=str))
for mid,old in base_results['models'].items():
 model=AnalysisModel.objects.get(pk=mid);assert projection(analysis_engine.run_analysis(admin,model.dataset,model.definition))==projection(old),mid
assert {r['id']:json.loads(json.dumps(r,default=str)) for r in targets.Targets(admin).rows.values()}=={r['id']:r for r in base_results['targets']};result['preserved_results']={'models':52,'targets':33}
metric=MetricVersion.objects.get(metric__key='DELIVERY_OTIF',version=8,status='published');assert metric.calculation_hash==metric_registry.calculation_hash(metric.metric.dataset)=='9d9a5af3d45172eca16790d628a36bc6acbe18d1e2a811a66a5b5fbff7037fe3';result['metric_version']=8
result['counts']={'records':Record.objects.count(),'datasets':Record.objects.values('dataset').distinct().count(),'workbooks':ImportBatch.objects.exclude(status='superseded').count(),'models':AnalysisModel.objects.count(),'topics':Topic.objects.count(),'views':TopicView.objects.count(),'snapshots':TopicSnapshot.objects.count()};assert tuple(result['counts'].values())==(117417,85,24,52,21,6,4)
(ROOT/'data/material_lots_validation.json').write_text(json.dumps(result,ensure_ascii=False,indent=2));print(json.dumps({k:v for k,v in result.items() if k not in ['preserved_tables','legacy_cases','date_cases']},ensure_ascii=False))
