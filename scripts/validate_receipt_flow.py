"""Read-only independent node/window reconciliation and baseline preservation."""
import os,sys,json,sqlite3,tempfile,zipfile,hashlib,csv,copy,statistics
from pathlib import Path
from collections import defaultdict,Counter
from decimal import Decimal
from datetime import datetime
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings')
import django;django.setup()
from django.db import connection
from django.contrib.auth.models import User
from app.models import Record,MetricVersion,AnalysisModel,ImportBatch,Topic,TopicView,TopicSnapshot
from app.schema import SCHEMAS
from app import analytics,receipt_flow as eng,receipt_flow_views as views,supply,purchase_commitments,analysis_engine,targets,metric_registry
connection.cursor().execute('PRAGMA query_only=ON')
result={'synthetic':True,'baseline':'data/backups/motor-backup-20261005-193415.zip','preserved_tables':{},'preserved_original_files':0}
with zipfile.ZipFile(ROOT/result['baseline']) as z,tempfile.TemporaryDirectory() as temp:
    p=Path(temp)/'old.db';p.write_bytes(z.read('data/platform.sqlite3'))
    for item in json.loads(z.read('manifest.json'))['files']:
        if item['path'].startswith(('data/imports/','data/device_files/')):
            assert hashlib.sha256((ROOT/item['path']).read_bytes()).hexdigest()==item['sha256'];result['preserved_original_files']+=1
    with sqlite3.connect(p) as old,sqlite3.connect('file:'+str(ROOT/'data/platform.sqlite3')+'?mode=ro',uri=True) as current:
        names=lambda db:{r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")};assert names(old)==names(current)
        allowed={'app_record':502,'app_importrow':502,'app_importbatch':1}
        for table in sorted(names(old)-{'django_session','sqlite_sequence'}):
            a=old.execute('SELECT * FROM '+table+' ORDER BY rowid').fetchall();b=current.execute('SELECT * FROM '+table+' ORDER BY rowid').fetchall()
            if table=='app_auditevent':
                assert b[:len(a)]==a;result['audit_additions']=dict(Counter(r[1] for r in b[len(a):]));assert set(result['audit_additions'])<={'import.stage','import.upload','import.commit','import.approve','receipt_flow.export','receipt_flow.jobs_export'},result['audit_additions']
            elif table in allowed:assert b[:len(a)]==a and len(b)-len(a)==allowed[table],table
            else:assert a==b,table
            result['preserved_tables'][table]={'before':len(a),'after':len(b)}
        before_raw={k:[] for k in SCHEMAS}
        for ds,val in old.execute('SELECT dataset,"values" FROM app_record'):before_raw[ds].append(json.loads(val))
raw=analytics.tables();cutoff=analytics.AS_OF;D=lambda v:Decimal(str(v));T=datetime.fromisoformat
hours=lambda a,b:(T(b)-T(a)).total_seconds()/3600
cases=json.loads((ROOT/'data/receipt_flow_scenario.json').read_text())['cases'];actual=eng.ReceiptFlow(raw);qs=defaultdict(list);moves=defaultdict(list);headers=defaultdict(list);versions=defaultdict(list)
for q in raw['incoming_inspections']:
    if q['inspected']<=cutoff:qs[q['receipt_id']].append(q)
for m in raw['inventory_movements']:
    if m['occurred']<=cutoff:moves[m['reference']].append(m)
for h in raw['receipt_jobs']:
    if h['created']<=cutoff:headers[h['receipt_id']].append(h)
for v in raw['receipt_job_versions']:versions[v['job_id']].append(v)
def union(windows):
    events=defaultdict(int)
    for a,b in windows:events[T(a)]+=1;events[T(b)]-=1
    level=0;last=None;seconds=0
    for when,change in sorted(events.items()):
        if last is not None and level:seconds+=(when-last).total_seconds()
        level+=change;last=when
    assert level==0
    return seconds/3600
def distribution(values):
    values=sorted(values);n=len(values)
    def quantile(p):
        i=(n-1)*p;left=int(i);return values[left]+(values[min(left+1,n-1)]-values[left])*(i-left)
    return dict(n=n,median=statistics.median(values) if n else None,p90=quantile(.9) if n else None,minimum=min(values) if n else None,maximum=max(values) if n else None)
source_keys=set();states=Counter();closed_first=[];closed_stock=[];open_values=defaultdict(list);parts=defaultdict(list);eligible_parts=Counter();invalid=set();positive_gap=Counter()
for source in raw['receipts']:
    if source['received']>cutoff:continue
    r=actual.index[source['id']];qq=sorted(qs[source['id']],key=lambda q:(q['inspected'],q['id']));mm=sorted(moves[source['id']],key=lambda m:(m['occurred'],m['id']));latest=qq[-1] if qq else None
    assert not r['issues'];first=qq[0] if qq else None;approved=bool(latest and latest['result']=='合格' and latest['disposition']=='批准入库' and source['status']=='检验合格');running=D(0);full=None
    for m in mm:
        assert m['material_id']==source['material_id'] and m['lot']==source['lot'] and m['movement']=='采购入库' and D(m['qty_signed'])>0
        prior=[q for q in qq if q['inspected']<=m['occurred']][-1];assert prior['result']=='合格' and prior['disposition']=='批准入库'
        running+=D(m['qty_signed'])
        if full is None and running>=D(source['qty']):full=m['occurred']
    state='waiting_inspection' if not first else 'disposition' if not approved else 'putaway' if not full else 'complete';states[state]+=1
    assert r['state']==state and D(r['putaway_qty'])==running and D(r['unposted_qty'])==max(D(0),D(source['qty'])-running)
    first_hours=hours(source['received'],first['inspected']) if first else None;stock_hours=hours(source['received'],full) if full else None
    assert r['inspection_hours']==first_hours and r['stock_hours']==stock_hours and r['full_stock_at']==full
    if first:closed_first.append(first_hours)
    if full:closed_stock.append(stock_hours)
    observed_from=source['received'] if state=='waiting_inspection' else latest['inspected'] if state in ['disposition','putaway'] else None
    assert r['observation_from']==observed_from and r['open_observation_hours']==(hours(observed_from,cutoff) if observed_from else None)
    if observed_from:open_values[state].append(hours(observed_from,cutoff))
    jobs={j['id']:j for j in r['jobs']}
    for h in headers[source['id']]:
        history=versions[h['id']];candidate=[v for v in history if v['status']=='模拟确认' and v['registered']<=cutoff];chosen=max(candidate,key=lambda v:(v['version'],v['registered'],v['id'])) if candidate else None;j=jobs[h['id']]
        assert j['selected']==chosen and {v['id'] for v in j['versions']}=={v['id'] for v in history}
        if h['id'] in cases:invalid.add(h['id']);assert not j['valid'] and j['work_hours'] is None
        else:
            assert j['valid'] and chosen;assert h['created']<=chosen['assigned']<=chosen['started']<=chosen['finished']<=chosen['registered']<=cutoff
            assert j['work_hours']==hours(chosen['started'],chosen['finished'])
    approval=[q for q in qq if mm and q['inspected']<=mm[0]['occurred'] and q['result']=='合格' and q['disposition']=='批准入库'];start_stock=approval[-1]['inspected'] if approval else None
    assert r['approval_before_first_stock']==start_stock
    for stage,key,field,start,end,expected in [('来料检验','inspection_decomposition','inspection_id',source['received'],first['inspected'] if first else None,{first['id']} if first else set()),('入库上架','putaway_decomposition','movement_id',start_stock,full,{m['id'] for m in mm if full and m['occurred']<=full})]:
        if end:eligible_parts[key]+=1
        relevant=[h for h in headers[source['id']] if h['stage']==stage];chosen_jobs=[jobs[h['id']] for h in relevant if jobs[h['id']]['selected'] and jobs[h['id']]['selected'].get(field) in expected]
        known=bool(expected and chosen_jobs and {j['selected'][field] for j in chosen_jobs}==expected and not any(h['id'] in cases for h in relevant));p=r[key];assert p['known']==known
        if known:
            windows=[(j['selected']['started'],j['selected']['finished']) for j in chosen_jobs];begin=min(a for a,b in windows);work=union(windows);before=hours(start,begin);total=hours(start,end);gap=total-before-work
            assert gap>=-1e-8
            values=dict(total_hours=total,before_start_hours=before,work_hours=work,gap_hours=max(0,gap))
            for k,v in values.items():assert abs(p[k]-v)<1e-9,(r['id'],key,k,p[k],v)
            parts[key].append(values);positive_gap[key]+=gap>1e-8
        else:assert all(p[k] is None for k in ['before_start_hours','work_hours','gap_hours'])
    for ref in r['sources']:source_keys.add((ref['dataset'],ref['key']))
assert invalid==set(cases);s=eng.summary(actual.rows);assert s['inspection_elapsed']==distribution(closed_first) and s['stock_elapsed']==distribution(closed_stock)
for item in s['open_states']:assert {k:item[k] for k in ['n','median','p90','minimum','maximum']}==distribution(open_values[item['state']])
for item in s['decompositions']:
    key=item['key'];assert item['n']==len(parts[key]) and item['eligible']==eligible_parts[key]
    for k,v in item['means'].items():assert abs(v-statistics.mean(p[k] for p in parts[key]))<1e-9
for unit in s['units']:
    for bucket in unit['states']:
        group=[r for r in actual.rows if r['unit']==unit['unit'] and r['state']==bucket['state']];assert bucket['rows']==len(group) and D(bucket['qty'])==sum((D(r['qty']) for r in group),D(0))
records={(r.dataset,r.business_key):r for r in Record.objects.select_related('source_row__batch') if (r.dataset,r.business_key) in source_keys}
for key in source_keys:
    obj=records[key];assert obj.source_row_id and (ROOT/obj.source_row.batch.file_path).exists()
old_supply=supply.SupplyData(before_raw);new_supply=supply.SupplyData(raw)
assert [supply.clean(r) for r in old_supply.po_rows]==[supply.clean(r) for r in new_supply.po_rows]
assert [supply.clean(r) for r in old_supply.lots]==[supply.clean(r) for r in new_supply.lots]
assert purchase_commitments.summary(purchase_commitments.Commitments(before_raw).rows)==purchase_commitments.summary(purchase_commitments.Commitments(raw).rows)
result['browser_csv']={};ordered=sorted(actual.rows,key=lambda r:(r['state']=='complete',not bool(r['issues']),not bool(r['work_issues']),-(r['open_observation_hours'] or 0),r['id']));string=lambda v:'' if v is None else str(v)
for name,filename in [('nodes','来料流程_全部来料队列.csv'),('jobs','来料流程_当前作业版本.csv')]:
    file=ROOT/'outputs'/filename
    if not file.exists():result['browser_csv'][name]={'verified':False,'reason':'实际浏览器下载尚未完成'};continue
    rows=list(csv.reader(file.open(encoding='utf-8-sig')));expected=[]
    if name=='nodes':
        assert rows[4]==[label for _,label in views.FIELDS]+[prefix+label+'小时' for prefix in ['首检分解：','入库分解：'] for label in views.PART_LABELS]+['实物核对','作业登记核对']
        expected=[[r.get(k) for k,_ in views.FIELDS]+[r[part][k] if r[part]['known'] else None for part in ['inspection_decomposition','putaway_decomposition'] for k in views.PARTS]+['；'.join(r['issues']),'；'.join(r['work_issues'])] for r in ordered]
    else:
        fields=['id','job_id','version','status','assigned','started','finished','inspection_id','movement_id','registered','owner_id','station']
        for r in ordered:
            for j in r['jobs']:
                if j['created']>cutoff:continue
                v=j['selected'] or {};expected.append([r['id'],j['id'],j['stage'],j['valid']]+[v.get(k) for k in fields]+[j['work_hours'],j['open_work_hours'],'；'.join(j['issues'])])
    assert rows[5:]==[[string(v) for v in r] for r in expected];result['browser_csv'][name]={'verified':True,'rows':len(expected)}
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
assert (s['objects'],s['completed'],s['disposition'],s['attention'],s['work_attention'])==(133,125,8,0,36) and [x['n'] for x in s['decompositions']]==[111,111]
result.update(summary=s,independent_checks={'receipts':len(actual.rows),'tasks':227,'versions':275,'invalid_jobs':len(invalid),'positive_gap_batches':dict(positive_gap),'unique_source_records':len(source_keys),'original_purchase_stock_commitments_unchanged':True},preserved_results={'models':52,'targets':33,'metric_version':8})
result['counts']={'records':Record.objects.count(),'datasets':Record.objects.values('dataset').distinct().count(),'workbooks':ImportBatch.objects.exclude(status='superseded').count(),'models':AnalysisModel.objects.count(),'topics':Topic.objects.count(),'views':TopicView.objects.count(),'snapshots':TopicSnapshot.objects.count()};assert tuple(result['counts'].values())==(118437,89,26,52,21,6,4)
(ROOT/'data/receipt_flow_validation.json').write_text(json.dumps(result,ensure_ascii=False,indent=2));print(json.dumps({k:v for k,v in result.items() if k not in ['preserved_tables','summary']},ensure_ascii=False))
