"""Read-only baseline preservation and independent sample/numeric reconciliation."""
import os,sys,json,sqlite3,tempfile,zipfile,hashlib,copy,statistics,math
from pathlib import Path
from collections import defaultdict,Counter
from datetime import datetime
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings')
import django;django.setup()
from django.db import connection
from django.contrib.auth.models import User
from app.models import Record,ImportBatch,MetricVersion,AnalysisModel,Topic,TopicView,TopicSnapshot
from app.schema import SCHEMAS
from app import analytics,incoming_quality as eng,supply,purchase_commitments,receipt_flow,analysis_engine,targets,metric_registry
connection.cursor().execute('PRAGMA query_only=ON')
result={'synthetic':True,'baseline':'data/backups/motor-backup-20261005-224546.zip','preserved_tables':{},'preserved_original_files':0}
with zipfile.ZipFile(ROOT/result['baseline']) as z,tempfile.TemporaryDirectory() as temp:
    p=Path(temp)/'old.db';p.write_bytes(z.read('data/platform.sqlite3'))
    for item in json.loads(z.read('manifest.json'))['files']:
        if item['path'].startswith(('data/imports/','data/device_files/')):
            assert hashlib.sha256((ROOT/item['path']).read_bytes()).hexdigest()==item['sha256'];result['preserved_original_files']+=1
    with sqlite3.connect(p) as old,sqlite3.connect('file:'+str(ROOT/'data/platform.sqlite3')+'?mode=ro',uri=True) as current:
        names=lambda db:{r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")};assert names(old)==names(current)
        additions={'app_record':6817,'app_importrow':6817,'app_importbatch':1}
        for table in sorted(names(old)-{'django_session','sqlite_sequence'}):
            a=old.execute('SELECT * FROM '+table+' ORDER BY rowid').fetchall();b=current.execute('SELECT * FROM '+table+' ORDER BY rowid').fetchall()
            if table=='app_auditevent':
                assert b[:len(a)]==a;result['audit_additions']=dict(Counter(r[1] for r in b[len(a):]));assert result['audit_additions']=={'import.stage':1,'import.commit':1,'simulation.xlsx_import':1}
            elif table in additions:assert b[:len(a)]==a and len(b)-len(a)==additions[table],table
            else:assert a==b,table
            result['preserved_tables'][table]={'before':len(a),'after':len(b)}
        before_raw={k:[] for k in SCHEMAS}
        for ds,val in old.execute('SELECT dataset,"values" FROM app_record'):before_raw[ds].append(json.loads(val))
raw=analytics.tables();actual=eng.IncomingQuality(raw);cutoff=analytics.AS_OF
index=lambda ds:{r['id']:r for r in raw[ds]}
group=lambda ds,key:{v:[r for r in raw[ds] if r[key]==v] for v in {r[key] for r in raw[ds]}}
plans=group('incoming_check_plans','inspection_id');checks=group('incoming_checks','plan_id');values=group('incoming_readings','check_id');receipts=index('receipts');specs=index('incoming_specs')
independent={};states=Counter();source_keys=set();T=datetime.fromisoformat
def norms(material,version,clock):return [s for s in specs.values() if s['material_id']==material and s['version']==version and s['effective']<=clock[:10] and (not s['expires'] or clock[:10]<s['expires'])]
def inspect(c,p,material,plan_bad):
    wanted=norms(material,p['spec_version'],c['checked']);si={s['id']:s for s in wanted};vv=values.get(c['id'],[])
    bad=plan_bad or not wanted or not any(s['mandatory'] for s in wanted) or c['checked']>c['registered'] or c['checked']<p['created']
    duplicates=Counter((v['sample_no'],v['spec_id']) for v in vv)
    for v in vv:
        s=si.get(v['spec_id']);bad=bad or not s or not 1<=v['sample_no']<=p['sample_count'] or duplicates[v['sample_no'],v['spec_id']]>1 or not math.isfinite(v['value']) or s and v['unit']!=s['unit'] or not v['instrument'] or not v['file_reference']
    if bad:return {'state':'attention','defects':None,'values':[]}
    missing=False;out_samples=set();valid=[]
    for n in range(1,p['sample_count']+1):
        present={v['spec_id'] for v in vv if v['sample_no']==n};missing|=any(s['mandatory'] and s['id'] not in present for s in wanted)
    for v in vv:
        s=si[v['spec_id']];outside=(s['lsl'] is not None and v['value']<s['lsl']) or (s['usl'] is not None and v['value']>s['usl'])
        if outside:out_samples.add(v['sample_no'])
        valid.append(v|{'outside':outside})
    return {'state':'missing' if missing else 'out' if out_samples else 'pass','defects':None if missing else len(out_samples),'values':valid}
for q in raw['incoming_inspections']:
    r=actual.index[q['id']];p=plans[q['id']];assert len(p)==1;p=p[0];material=receipts[q['receipt_id']]['material_id']
    pp=not (receipts[q['receipt_id']]['received']<=p['created']<=p['due']<=q['inspected']) or p['sample_count']!=q['sample_size'] or not norms(material,p['spec_version'],p['due'])
    cc=sorted([c for c in checks.get(p['id'],[]) if not c['voided'] and c['checked']<=cutoff and c['registered']<=cutoff],key=lambda c:(c['checked'],c['id']))
    ties=any(n>1 for n in Counter(c['checked'] for c in cc).values());first=cc[0]['id'] if cc and not ties else None;latest=cc[-1]['id'] if cc and not ties else None
    ee={c['id']:inspect(c,p,material,pp) for c in cc};selected=ee.get(latest)
    state='attention' if pp or ties else selected['state'] if selected else 'pending';defects=selected['defects'] if selected and not pp and not ties else None
    assert (r['state'],r['latest_defect_count'],r['first_id'],r['latest_id'])==(state,defects,first,latest),q['id']
    assert r['disagreement']==(defects is not None and defects!=q['defect_count']);states[state]+=1
    independent[q['id']]={'plan':p,'first':first,'latest':latest,'executions':ee}
    source_keys.update((x['dataset'],x['key']) for x in r['sources'])
checks_count=0
for spec in specs.values():
    for mode in ['first','latest','all']:
        expected=[]
        for qid,item in independent.items():
            p=item['plan'];r=actual.index[qid]
            if r['material_id']!=spec['material_id'] or p['spec_version']!=spec['version']:continue
            chosen=[item[mode]] if mode!='all' else list(item['executions'])
            for cid in chosen:
                if cid:expected.extend(v for v in item['executions'][cid]['values'] if v['spec_id']==spec['id'])
        d=actual.distribution(actual.rows,spec['id'],mode);xx=[v['value'] for v in expected]
        assert {v['id'] for v in d['observations']}=={v['id'] for v in expected};assert d['n']==len(xx) and sum(b['count'] for b in d['bins'])==len(xx)
        assert d['mean']==(statistics.mean(xx) if xx else None) and d['median']==(statistics.median(xx) if xx else None)
        assert d['out']==sum(v['outside'] for v in expected);checks_count+=1
records={(r.dataset,r.business_key):r for r in Record.objects.select_related('source_row__batch') if (r.dataset,r.business_key) in source_keys}
assert len(records)==len(source_keys)
for key,obj in records.items():assert obj.source_row_id and Path(obj.source_row.batch.file_path).exists()
old_supply=supply.SupplyData(before_raw);new_supply=supply.SupplyData(raw)
assert [supply.clean(r) for r in old_supply.po_rows]==[supply.clean(r) for r in new_supply.po_rows]
assert [supply.clean(r) for r in old_supply.lots]==[supply.clean(r) for r in new_supply.lots]
assert purchase_commitments.summary(purchase_commitments.Commitments(before_raw).rows)==purchase_commitments.summary(purchase_commitments.Commitments(raw).rows)
assert receipt_flow.summary(receipt_flow.ReceiptFlow(before_raw).rows)==receipt_flow.summary(receipt_flow.ReceiptFlow(raw).rows)
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
result.update(summary=eng.summary(actual.rows),independent_checks={'inspections':len(actual.rows),'norms':len(specs),'distribution_scopes':checks_count,'states':dict(states),'unique_source_records':len(source_keys),'original_purchase_stock_commitments_flow_unchanged':True},preserved_results={'models':52,'targets':33,'metric_version':8},browser={'rendered':False,'mobile':False,'actual_csv_download':False,'reason':'上一轮浏览器自动授权检查连续两次超时；未再次尝试，继续独立的数据及服务端验证'})
result['counts']={'records':Record.objects.count(),'datasets':Record.objects.values('dataset').distinct().count(),'workbooks':ImportBatch.objects.exclude(status='superseded').count(),'models':AnalysisModel.objects.count(),'topics':Topic.objects.count(),'views':TopicView.objects.count(),'snapshots':TopicSnapshot.objects.count()};assert tuple(result['counts'].values())==(125254,93,27,52,21,6,4)
(ROOT/'data/incoming_quality_validation.json').write_text(json.dumps(result,ensure_ascii=False,indent=2));print(json.dumps({k:v for k,v in result.items() if k not in ['preserved_tables']},ensure_ascii=False))
