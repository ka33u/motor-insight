"""Independently reconcile imported material planning facts, CSVs and preservation."""
import os,sys,json,csv,hashlib,sqlite3,zipfile,tempfile,math
from collections import defaultdict,Counter
from decimal import Decimal,ROUND_CEILING
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings')
import django;django.setup()
from django.contrib.auth.models import User
from app.models import Record,AnalysisModel,Topic,TopicView,TopicSnapshot,ImportBatch,MetricVersion,IssueDisposition,AuditEvent,DataQualityScan
from app import analytics,material_planning as engine,analysis_engine,metric_registry,topic_snapshots

baseline=ROOT/'data/backups/motor-backup-20261004-043422.zip';preserved={};originals=0
with zipfile.ZipFile(baseline) as z,tempfile.TemporaryDirectory() as tmp:
    for f in json.loads(z.read('manifest.json'))['files']:
        if f['path'].startswith(('data/imports/','data/device_files/')):
            assert hashlib.sha256((ROOT/f['path']).read_bytes()).hexdigest()==f['sha256'];originals+=1
    path=Path(tmp)/'before.sqlite3';path.write_bytes(z.read('data/platform.sqlite3'))
    with sqlite3.connect(path) as old,sqlite3.connect(ROOT/'data/platform.sqlite3') as now:
        tables=[r[0] for r in old.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'app_%'")];assert len(tables)==25
        for table in tables:
            before=list(old.execute(f'SELECT * FROM {table} ORDER BY id'));after=list(now.execute(f'SELECT * FROM {table} ORDER BY id'));lookup={r[0]:r for r in after}
            assert all(lookup.get(r[0])==r for r in before),(table,'existing rows changed')
            if table!='app_auditevent':assert len(after)-len(before)==(1 if table=='app_issuedisposition' else 0),(table,len(before),len(after))
            preserved[table]={'before':len(before),'after':len(after),'all_prior_rows_unchanged':True}
h=hashlib.sha256()
for row in Record.objects.order_by('dataset','business_key').values_list('dataset','business_key','values','revision','source_row_id').iterator():h.update(json.dumps(row,sort_keys=True,ensure_ascii=False).encode())
assert h.hexdigest()=='c3493d7c4d221e6511486c05605c1c7f42ae7276ca4a7070e195999ae9e2e775'
assert (Record.objects.count(),Record.objects.values('dataset').distinct().count(),ImportBatch.objects.exclude(status='superseded').count(),AnalysisModel.objects.count(),Topic.objects.count(),TopicView.objects.count(),TopicSnapshot.objects.count(),DataQualityScan.objects.count())==(110787,63,18,50,19,4,2,7)
metric=MetricVersion.objects.get(pk=9);assert metric.status=='published' and metric.version==6 and metric.calculation_hash==metric_registry.calculation_hash('bi_order_lines')=='aeb8f5c1183aac4f6c229bf08214b65079e3a9dbe5504d31f4113fc3e8bf82a9'

# Expected quantities are rebuilt from raw records, without SupplyData or the planning engine.
raw=defaultdict(list)
for ds,value in Record.objects.values_list('dataset','values'):raw[ds].append(value)
D=lambda v:Decimal(str(v));zero=Decimal(0);cutoff=analytics.AS_OF
materials={r['id']:r for r in raw['materials']};products={r['id']:r for r in raw['products']};work={r['id']:r for r in raw['work_orders']}
receipts={r['id']:r for r in raw['receipts'] if r['received']<=cutoff};purchases={r['id']:r for r in raw['purchase_lines'] if r['ordered']<=cutoff[:10]}
employees={r['id'] for r in raw['employees']};inspections=defaultdict(list)
for r in raw['incoming_inspections']:
    if r['inspected']<=cutoff:inspections[r['receipt_id']].append(r)
lotkey=lambda r:(r['material_id'],r['lot'],r['location'])
lots={};events=defaultdict(list);received=defaultdict(lambda:zero)
for r in receipts.values():received[r['purchase_line_id']]+=D(r['qty'])
open_po=defaultdict(lambda:zero)
for p in purchases.values():open_po[p['material_id']]+=max(zero,D(p['qty'])-received[p['id']])
for r in raw['inventory_opening']:
    if r['as_of']<=cutoff[:10]:
        key=lotkey(r);assert key not in lots;lots[key]={'balance':D(r['qty']),'state':r['status'],'as_of':r['as_of']+'T00:00:00'}
for ds,kind in [('inventory_status_events',0),('inventory_movements',1)]:
    for r in raw[ds]:
        if r['occurred']<=cutoff:events[lotkey(r)].append((r['occurred'],kind,r['id'],r))
putaway=defaultdict(lambda:zero);issued=defaultdict(lambda:zero)
for key,ev in events.items():
    for stamp,kind,_,r in sorted(ev):
        if kind==0:
            assert key in lots and lots[key]['state']==r['from_status'] and r['approver_id'] in employees
            lots[key]['state']=r['to_status'];continue
        qty=D(r['qty_signed'])
        if r['movement']=='采购入库':
            rr=receipts[r['reference']];p=purchases[rr['purchase_line_id']]
            assert qty>0 and rr['material_id']==key[0] and rr['lot']==key[1] and p['material_id']==key[0]
            qq=max(inspections[rr['id']],key=lambda q:(q['inspected'],q['id']))
            assert qq['disposition']=='批准入库' and qq['result']=='合格' and rr['received']<=qq['inspected']<=stamp and qq['inspector_id'] in employees
            putaway[rr['id']]+=qty
            if key not in lots:lots[key]={'balance':zero,'state':'可用','as_of':stamp}
        else:
            assert r['movement']=='生产领料' and qty<0 and r['reference']==r['work_order_id'] and r['work_order_id'] in work and lots[key]['state']=='可用'
            issued[r['work_order_id'],key[0]]-=qty
        assert stamp>=lots[key]['as_of'];lots[key]['balance']+=qty;assert lots[key]['balance']>=0
for rid,qty in putaway.items():assert qty<=D(receipts[rid]['qty'])
usable=defaultdict(lambda:zero)
for (mid,_,_),lot in lots.items():
    if lot['state']=='可用':usable[mid]+=lot['balance']
assert len(usable)==48
boms=defaultdict(list);assembled=Counter()
for r in raw['bom']:boms[r['product_id'],r['version']].append(r)
for r in raw['units']:
    if r['assembly_at']<=cutoff:assert r['product_id']==work[r['work_order_id']]['product_id'];assembled[r['work_order_id']]+=1

def expected(conf):
    f={'family':'','product':'','work_order':'','from':'','to':'','q':'','order':'start','stock_policy':'protect_safety',**conf}
    cohort=[]
    for w in work.values():
        p=products[w['product_id']]
        if f['family'] and f['family']!=p['family'] or f['product'] and f['product']!=p['id'] or f['work_order'] and f['work_order']!=w['id']:continue
        if f['from'] and w['planned_start']<f['from'] or f['to'] and w['planned_start']>f['to']:continue
        if f['q'] and f['q'].lower() not in ' '.join([w['id'],p['id'],p['model'],p['family']]).lower():continue
        cohort.append(w)
    priorities={'紧急':0,'加急':1,'普通':2}
    cohort.sort(key=lambda w:((priorities[w['priority']],w['planned_start']) if f['order']=='priority' else (w['planned_start'],priorities[w['priority']]))+(w['planned_end'],w['id']))
    start={mid:max(zero,v-(D(materials[mid]['safety_qty']) if f['stock_policy']=='protect_safety' else zero)) for mid,v in usable.items()};pool=start.copy();rows={};totals=defaultdict(lambda:zero);allocations=defaultdict(list);demand_orders=defaultdict(list)
    for seq,w in enumerate(cohort,1):
        wid=w['id'];excluded=w['status'] in ['已取消','完工待清尾','已完工','已关闭'] or assembled[wid]>=w['planned_qty'];items={}
        assert w['planned_start']<=w['planned_end']
        if excluded:assert assembled[wid]==w['planned_qty'];rows[wid]={'state':'excluded','sequence':seq,'items':{},'assembled_qty':assembled[wid]};continue
        lines=boms[w['product_id'],w['bom_version']];assert len(lines)==9
        gross=defaultdict(lambda:zero)
        for b in lines:
            assert b['effective']<=min(w['planned_start'],cutoff[:10]);gross[b['material_id']]+=D(w['planned_qty'])*D(b['qty'])*(1+D(b['scrap_allowance']))
        for mid,g in gross.items():
            rounded=g.to_integral_value(rounding=ROUND_CEILING) if materials[mid]['unit']=='件' else g;net=max(zero,rounded-issued[wid,mid]);totals[mid]+=net;demand_orders[mid].append(wid)
            items[mid]={'gross_unrounded':g,'gross_required':rounded,'issued_qty':issued[wid,mid],'remaining_required':net,'before_pool':pool[mid],'gap':max(zero,net-pool[mid]),'simulated_allocated':zero}
        state='short' if any(i['gap'] for i in items.values()) else 'covered'
        for mid,i in items.items():
            if state=='covered':
                qty=i['remaining_required'];pool[mid]-=qty;i['simulated_allocated']=qty
                if qty:allocations[mid].append({'work_order_id':wid,'sequence':seq,'qty':qty,'before':i['before_pool'],'after':pool[mid]})
            i['after_pool']=pool[mid];assert pool[mid]>=0
        rows[wid]={'state':state,'sequence':seq,'items':items,'assembled_qty':assembled[wid]}
    mats={mid:{'unit':materials[mid]['unit'],'usable_state_qty':usable[mid],'safety_buffer':D(materials[mid]['safety_qty']) if f['stock_policy']=='protect_safety' else zero,'initial_pool':start[mid],'net_demand':total,'known_gap':max(zero,total-start[mid]),'simulated_allocated':start[mid]-pool[mid],'remaining_pool':pool[mid],'open_purchase_qty':open_po[mid],'allocations':allocations[mid],'demand_work_orders':sorted(demand_orders[mid])} for mid,total in totals.items()}
    counts=Counter(r['state'] for r in rows.values())
    summary={'orders':len(rows),'active':len(rows)-counts['excluded'],'covered':counts['covered'],'short':counts['short'],'attention':0,'excluded':counts['excluded'],'materials':len(mats),'short_materials':sum(bool(m['known_gap']) for m in mats.values()),'covered_planned_qty':sum(work[k]['planned_qty'] for k,v in rows.items() if v['state']=='covered'),'unknown_demand_orders':0}
    return rows,mats,summary

def close(a,b):assert a is not None and b is not None and math.isclose(float(a),float(b),rel_tol=1e-11,abs_tol=1e-8),(a,b)
cases=[{'order':o,'stock_policy':p} for o in ['start','priority'] for p in ['protect_safety','all_usable']]+[{'family':f} for f in ['YE3','YE4','YVF2']]+[{'work_order':'MO2609-000233'},{'from':'2026-09-19','to':'2026-09-19'},{'q':'YE4-80M'},{'work_order':'MO-NOT-FOUND'}]
checked_items=0;scenarios=[]
for conf in cases:
    rows,mats,summary=expected(conf);result,_=engine.current(engine.filters(conf));assert result.summary()==summary,(conf,result.summary(),summary)
    assert set(result.orders)==set(rows) and set(result.material_rows)==set(mats)
    for wid,e in rows.items():
        a=result.orders[wid];assert (a['state'],a['sequence'],a['assembled_qty'])==(e['state'],e['sequence'],e['assembled_qty']) and not a['issues']
        items={i['material_id']:i for i in a['items']};assert set(items)==set(e['items'])
        for mid,fields in e['items'].items():
            for k,value in fields.items():close(items[mid][k],value)
            checked_items+=1
    for mid,e in mats.items():
        a=result.material_rows[mid];assert not a['issues'] and not a['unknown_work_orders'] and a['unit']==e['unit'] and a['demand_work_orders']==e['demand_work_orders']
        for k,value in e.items():
            if k not in ['unit','allocations','demand_work_orders']:close(a[k],value)
        assert len(a['allocations'])==len(e['allocations'])
        for aa,ee in zip(a['allocations'],e['allocations']):
            assert (aa['work_order_id'],aa['sequence'])==(ee['work_order_id'],ee['sequence'])
            for k in ['qty','before','after']:close(aa[k],ee[k])
    scenarios.append({'filters':conf,**summary})

files={}
for name,conf,tab in [('备料试配_缺料工单_浏览器导出.csv',{},'orders'),('备料试配_缺口物料_浏览器导出.csv',{},'materials'),('备料试配_全部可用库存缺料工单_浏览器导出.csv',{'stock_policy':'all_usable'},'orders')]:
    p=ROOT/'outputs'/name;lines=list(csv.reader(p.open(encoding='utf-8-sig',newline='')));f=json.loads(lines[0][4]);assert f['stock_policy']==conf.get('stock_policy','protect_safety') and f['tab']==tab and f['stage']=='short'
    assert lines[3][1]==engine.receipt(engine.filters(f),analytics.revision());rows,mats,_=expected(conf);actual=[dict(zip(lines[4],line,strict=True)) for line in lines[5:]];assert all(not r['资料问题'] for r in actual)
    if tab=='orders':
        wanted={wid:r for wid,r in rows.items() if r['state']=='short'};assert {r['工单号'] for r in actual}==set(wanted)
        for r in actual:
            e=wanted[r['工单号']];assert r['试配状态']=='已知物料不足' and int(r['全队列序号'])==e['sequence'];assert int(r['队列位置缺口物料种类'])==sum(bool(i['gap']) for i in e['items'].values())
    else:
        wanted={mid:r for mid,r in mats.items() if r['known_gap']};assert {r['物料编码'] for r in actual}==set(wanted)
        cols={'可用状态库存':'usable_state_qty','本次安全库存缓冲':'safety_buffer','试配池起点':'initial_pool','已知工单净需求':'net_demand','已知需求余额缺口':'known_gap','整单试配占用':'simulated_allocated','试配后剩余池':'remaining_pool','采购未到参考量':'open_purchase_qty'}
        for r in actual:
            e=wanted[r['物料编码']];assert r['单位']==e['unit'] and int(r['已知需求工单数'])==len(e['demand_work_orders']) and int(r['需求待核对工单数'])==0
            for title,key in cols.items():close(r[title],e[key])
    assert len(actual)==len(wanted);files[name]={'rows':len(actual),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()}

admin=User.objects.get(username='demo_admin');old_results=json.loads((ROOT/'data/pivot_before.json').read_text());regression={}
for key,old in old_results.items():
    m=AnalysisModel.objects.get(pk=key);r=analysis_engine.run_analysis(admin,m.dataset,m.definition)
    fields=['rows','matched','scanned','groups','components','derived_notes','truncated','dimension_label','labels','display_metric']
    assert all(r.get(k)==old['result'].get(k) for k in fields),key;regression[key]={'unchanged':True,'matched':r['matched']}
m=AnalysisModel.objects.get(pk=50);r=analysis_engine.run_analysis(admin,m.dataset,m.definition);prior=json.loads((ROOT/'data/pivot_validation.json').read_text())['grand_total']
for key,value in prior.items():close(r['pivot']['grand_total'][key],value)
regression['50']={'grand_total_unchanged':True,'matched':r['matched']}
for s in TopicSnapshot.objects.all():topic_snapshots.verify(s)
note=IssueDisposition.objects.get(key='material_planning:orders:MO2609-000233');assert note.version==1 and note.status=='待采购核对' and note.owner=='模拟计划 / 采购组'
audit=AuditEvent.objects.get(action='material_planning.followup',object_id=note.key);assert audit.detail['before']['version']==0 and audit.detail['after']['version']==1 and audit.detail['business_facts_changed'] is False
catalog=json.loads((ROOT/'data/bi_design.json').read_text());needs={i['id']:i for dom in catalog['domains'] for i in dom['items']};assert len(needs)==296 and needs['F-03']['implementation']=='模拟部分覆盖' and all(needs[i]['implementation']=='待建设' for i in ['F-08','J-07'])
assert Counter(i['implementation'] for i in needs.values())=={'模拟部分覆盖':75,'待建设':221}
out={'baseline':str(baseline.relative_to(ROOT)),'business_sha256':h.hexdigest(),'records':110787,'source_categories':63,'active_workbooks':18,'unchanged_original_files':originals,'preserved_tables':preserved,'scenarios':scenarios,'independently_checked_order_materials':checked_items,'independently_checked_lots':len(lots),'browser_csv':files,'existing_models':regression,'published_metric':{'version':metric.version,'hash':metric.calculation_hash},'coordination':{'key':note.key,'version':note.version,'business_facts_changed':False},'test_count':811}
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
        assert z.read('data/bi_design.json')==(ROOT/'data/bi_design.json').read_bytes()
        out['backup']={'path':str(backup),'manifest_files':len(manifest['files']),'app_tables':len(preserved),'integrity':'ok','restored_content_matches_current':True}
(ROOT/'data/material_planning_validation.json').write_text(json.dumps(out,ensure_ascii=False,indent=2))
print(json.dumps({k:v for k,v in out.items() if k not in ['preserved_tables','existing_models']},ensure_ascii=False,indent=2))
