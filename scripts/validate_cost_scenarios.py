"""Independent reconciliation for the synthetic cost-scenario acceptance snapshot."""
import os,sys,json,csv,math,hashlib,sqlite3,tempfile,zipfile,copy
from collections import Counter,defaultdict
from decimal import Decimal,ROUND_HALF_UP
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings')
import django;django.setup()
from app.models import Record,CostScenario,MetricVersion,TopicSnapshot
from app import analytics,metric_registry

BASE=ROOT/'data/backups/motor-backup-20261003-155904.zip'
AS_OF='2026-10-01T18:00:00';DAY=AS_OF[:10]
def digest(v):return hashlib.sha256(json.dumps(v,ensure_ascii=False,sort_keys=True,default=str).encode()).hexdigest()
def cents(v):return int(v.quantize(Decimal('1'),rounding=ROUND_HALF_UP))

with zipfile.ZipFile(BASE) as z,tempfile.TemporaryDirectory() as tmp:
    manifest=json.loads(z.read('manifest.json'))
    for entry in manifest['files']:
        if entry['path'].startswith('data/imports/'):
            assert hashlib.sha256((ROOT/entry['path']).read_bytes()).hexdigest()==entry['sha256']
    before_path=Path(tmp)/'before.sqlite3';before_path.write_bytes(z.read('data/platform.sqlite3'))
    with sqlite3.connect(before_path) as old,sqlite3.connect(ROOT/'data/platform.sqlite3') as now:
        tables=[r[0] for r in old.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'app_%'")]
        for table in tables:
            before=list(old.execute(f'SELECT * FROM {table} ORDER BY id'))
            after=list(now.execute(f'SELECT * FROM {table}'+(' WHERE id<=?' if table=='app_auditevent' else '')+' ORDER BY id',(before[-1][0],) if table=='app_auditevent' else ()))
            assert before==after,table
    old_design=json.loads(z.read('data/bi_design.json'));design=json.loads((ROOT/'data/bi_design.json').read_text())
    cleaned=copy.deepcopy(design)
    for dom in cleaned['domains']:
        for item in dom['items']:
            if item['id']=='Y-07':
                prior=next(i for d in old_design['domains'] for i in d['items'] if i['id']=='Y-07')
                item.update({k:prior[k] for k in ['gap','implementation']})
    page=next(p for p in cleaned['page_blueprints'] if p['id']=='P16');page.pop('actual_href')
    page['status']=next(p for p in old_design['page_blueprints'] if p['id']=='P16')['status']
    cleaned['framework']['surfaces']=[s for s in cleaned['framework']['surfaces'] if s['href']!='#scenarios']
    next(r for r in cleaned['framework']['presentation'] if r[0]=='情景比较页')[3]=next(r for r in old_design['framework']['presentation'] if r[0]=='情景比较页')[3]
    assert cleaned==old_design

h=hashlib.sha256()
for row in Record.objects.order_by('dataset','business_key').values_list('dataset','business_key','values','revision','source_row_id').iterator():h.update(json.dumps(row,ensure_ascii=False,sort_keys=True).encode())
assert Record.objects.count()==106838 and h.hexdigest()=='576ad9668e112e407eb81b9d3f58fa150f5753f7ede1fe43b2919ed4a1ec2a72'
assert TopicSnapshot.objects.get().payload_hash=='6768e9603cda8d0506378e9ba8e4405e9560482cb25f41e211dc73b0ad4ee818'
v3=MetricVersion.objects.select_related('metric').get(metric__key='DELIVERY_OTIF',version=3)
assert v3.status=='published' and v3.calculation_hash==metric_registry.calculation_hash(v3.metric.dataset)
records={(r.dataset,r.business_key):r for r in Record.objects.filter(dataset__in=['products','work_orders','units','costs','materials','inventory_movements']).select_related('source_row__batch')}
raw=defaultdict(dict)
for (ds,key),r in records.items():raw[ds][key]=r.values
costs=defaultdict(list);units=defaultdict(list);moves=defaultdict(list)
for c in raw['costs'].values():
    if c['occurred']<=DAY:costs[c['work_order_id']].append(c)
for u in raw['units'].values():
    if u['assembly_at']<=AS_OF:units[u['work_order_id']].append(u)
for m in raw['inventory_movements'].values():
    if m.get('work_order_id') and m['occurred']<=AS_OF:moves[m['work_order_id']].append(m)
runs=list(CostScenario.objects.select_related('owner').order_by('created_at'));assert len(runs)==2
assert runs[0].parent_id is None and runs[1].parent_id==runs[0].pk
assert runs[0].payload['baseline']==runs[1].payload['baseline']
files={};summaries=[];expected_export={}
for saved in runs:
    assert saved.owner.username=='demo_admin' and digest(saved.payload)==saved.payload_hash
    p=saved.payload;b=p['baseline'];scope=b['scope']
    assert scope=={'family':'YE4','from':'2026-09-25','to':'2026-09-25'}
    assert b['as_of']==AS_OF and b['calculation_hash']==hashlib.sha256((ROOT/'app/cost_scenarios.py').read_bytes()).hexdigest()
    assert not b['problems'] and len(b['sources'])==226
    assert p['receipt']==dict(name=saved.name,note=saved.note,owner_id=saved.owner_id,parent_id=str(saved.parent_id) if saved.parent_id else None,request_id=str(saved.request_id))
    unhashed={k:v for k,v in p.items() if k not in ['calculation_token','receipt']};assert digest(unhashed)==p['calculation_token']
    selected=[w for w in raw['work_orders'].values() if raw['products'][w['product_id']]['family']==scope['family'] and scope['from']<=w['planned_end']<=scope['to']]
    assert len(selected)==7 and {r['id'] for r in b['rows']}=={w['id'] for w in selected}
    ready=[];expected_sources=set()
    for row in b['rows']:
        wid=row['id'];w=raw['work_orders'][wid];wc=costs[wid];wu=units[wid];wm=moves[wid]
        refs={('work_orders',wid),('products',w['product_id'])}|{('costs',c['id']) for c in wc}|{('units',u['id']) for u in wu}|{('inventory_movements',m['id']) for m in wm}|{('materials',m['material_id']) for m in wm}
        expected_sources|=refs;assert set(row['source_keys'])=={digest([ds,key]) for ds,key in refs}
        assert row['produced_qty']==len(wu) and row['product_id']==w['product_id'] and row['planned_end']==w['planned_end'] and row['family']=='YE4'
        components={kind:sum(c['amount_cents'] for c in wc if c['category']==kind) for kind in ['材料','直接人工','制造费用','返工增耗']}
        assert row['components']==components and row['base_cents']==sum(components.values())
        assert {c['id']:c for c in row['costs']}=={c['id']:{k:c[k] for k in ['id','category','amount_cents','status','basis']} for c in wc}
        assert row['eligible']==bool(wu) and not row['errors']
        if not wu:assert not wc and not wm and row['excluded_reason'];continue
        ready.append(row);material_base=0
        assert len(row['materials'])==len(wm)==8
        for m in wm:
            material=raw['materials'][m['material_id']];qty=-Decimal(str(m['qty_signed']));price=material['unit_cost_cents'];base=cents(qty*price)
            frozen=next(x for x in row['materials'] if x['id']==m['id'])
            assert Decimal(frozen['qty'])==qty and frozen['unit_cost_cents']==price and frozen['base_cents']==base
            assert (frozen['material_id'],frozen['category'],frozen['unit'],frozen['material'])==(material['id'],material['category'],material['unit'],material['name'])
            material_base+=base
        assert material_base==row['material_recomputed_cents']==components['材料']
    assert len(ready)==5 and sum(r['produced_qty'] for r in ready)==150
    assert expected_sources=={(s['dataset'],s['key']) for s in b['sources'].values()}
    for key,s in b['sources'].items():
        assert key==digest([s['dataset'],s['key']]);r=records[s['dataset'],s['key']];batch=r.source_row.batch
        assert s['values']=={k:r.values[k] for k in s['values']}
        assert (s['revision'],s['record_hash'])==(r.revision,r.record_hash)
        assert (s['batch_id'],s['filename'],s['file_hash'],s['sheet'],s['row'])==(str(batch.pk),batch.filename,batch.file_hash,r.source_row.sheet,r.source_row.row_number)
        files[batch.file_path]=batch.file_hash
    for case,params in zip(p['results'],p['assumptions']):
        contributions=defaultdict(lambda:[0,0]);total_base=total_new=qty=0
        for row in case['rows']:
            wid=row['id'];base=sum(c['amount_cents'] for c in costs[wid]);new=0;row_bridge=defaultdict(lambda:[0,0])
            for m in moves[wid]:
                mat=raw['materials'][m['material_id']];q=-Decimal(str(m['qty_signed']));price=mat['unit_cost_cents']
                mb=cents(q*price);mn=cents(q*price*(1+Decimal(params['material_rates'][mat['category']])/100));new+=mn
                ml=next(x for x in row['material_lines'] if x['id']==m['id']);assert (ml['baseline_cents'],ml['scenario_cents'],ml['delta_cents'])==(mb,mn,mn-mb)
                row_bridge['材料 · '+mat['category']][0]+=mb;row_bridge['材料 · '+mat['category']][1]+=mn
            for c in costs[wid]:
                if c['category']=='材料':continue
                rate=params['labor_rate'] if c['category']=='直接人工' else params['overhead_rate'] if c['category']=='制造费用' else '0'
                amount=cents(Decimal(c['amount_cents'])*(1+Decimal(rate)/100));new+=amount
                row_bridge[c['category']][0]+=c['amount_cents'];row_bridge[c['category']][1]+=amount
            assert (row['baseline_cents'],row['scenario_cents'],row['delta_cents'],row['produced_qty'])==(base,new,new-base,len(units[wid]))
            assert math.isclose(row['scenario_unit_yuan'],new/100/len(units[wid]),rel_tol=1e-12)
            assert {v['label']:[v['base_cents'],v['scenario_cents']] for v in row['contributions']}==dict(row_bridge)
            for label,(mb,mn) in row_bridge.items():contributions[label][0]+=mb;contributions[label][1]+=mn
            total_base+=base;total_new+=new;qty+=len(units[wid])
            expected_export[str(saved.pk),case['name'],wid]=(base,new,new-base,qty,params)
        t=case['totals'];assert (t['baseline_cents'],t['scenario_cents'],t['delta_cents'],t['produced_qty'])==(total_base,total_new,total_new-total_base,qty)
        assert total_base==6644134 and qty==150 and math.isclose(t['scenario_unit_yuan'],total_new/100/qty,rel_tol=1e-12)
        assert math.isclose(t['relative_pct'],(total_new-total_base)/total_base*100,rel_tol=1e-12)
        assert {v['label']:[v['base_cents'],v['scenario_cents']] for v in case['bridge']}==dict(contributions)
        assert sum(v['delta_cents'] for v in case['bridge'])==total_new-total_base
        assert len(case['by_config'])==1 and case['by_config'][0]['product_id']=='CP.00022.A'
        config=case['by_config'][0];assert (config['qty'],config['orders'],config['scenario_cents'])==(150,5,total_new)
    summaries.append({'id':str(saved.pk),'parent':str(saved.parent_id) if saved.parent_id else None,'hash':saved.payload_hash,'name':saved.name,'sources_by_dataset':dict(Counter(s['dataset'] for s in b['sources'].values())),'results':[{'name':c['name'],**c['totals']} for c in p['results']]})
for path,sha in files.items():assert hashlib.sha256(Path(path).read_bytes()).hexdigest()==sha
csvpath=ROOT/'outputs/成本情景_浏览器导出.csv';jsonpath=ROOT/'outputs/成本情景_浏览器导出.json'
exported=json.loads(jsonpath.read_text());assert exported['payload']==runs[0].payload and exported['payload_hash']==runs[0].payload_hash
csvrows=list(csv.DictReader(csvpath.open(encoding='utf-8-sig')));assert len(csvrows)==10
for row in csvrows:
    base,new,delta,_,params=expected_export[row['情景标识'],row['方案'],row['工单']]
    assert (int(row['基线金额分']),int(row['假设金额分']),int(row['差额分']))==(base,new,delta)
    assert int(row['固定装配台数'])==30 and row['完整性摘要']==runs[0].payload_hash
    assert json.loads(row['假设参数'])==params and math.isclose(float(row['假设元每台']),new/100/30,rel_tol=1e-12)
report={'synthetic':True,'baseline':str(BASE.relative_to(ROOT)),'business_rows':106838,'business_sha256':h.hexdigest(),'preserved_tables':tables,'runs':summaries,'verified_source_files':len(files),'browser_csv_rows':10,'browser_json_sha256':hashlib.sha256(jsonpath.read_bytes()).hexdigest(),'tests':288,'new_tests':24,'catalog_change':'Y-07 partial; P16 and scenario surface linked; 41 partial, 223 planned','limits':'Fixed quantities and reference prices only. No capacity, overtime, scrap yield, actual inventory valuation, cash flow, margin or approved budget prediction.'}
if len(sys.argv)>1:
    backup=Path(sys.argv[1]).resolve()
    with zipfile.ZipFile(backup) as z,tempfile.TemporaryDirectory() as tmp:
        manifest=json.loads(z.read('manifest.json'))
        for entry in manifest['files']:assert hashlib.sha256(z.read(entry['path'])).hexdigest()==entry['sha256']
        restored_path=Path(tmp)/'restored.sqlite3';restored_path.write_bytes(z.read('data/platform.sqlite3'))
        with sqlite3.connect(restored_path) as restored,sqlite3.connect(ROOT/'data/platform.sqlite3') as live:
            assert restored.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
            for table in [*tables,'app_costscenario']:
                if table=='app_auditevent':continue
                assert list(restored.execute(f'SELECT * FROM {table} ORDER BY id'))==list(live.execute(f'SELECT * FROM {table} ORDER BY id')),table
    report['backup']={'path':str(backup.relative_to(ROOT)),'manifest_files':len(manifest['files']),'sqlite_integrity':'ok','critical_tables_match':True}
(ROOT/'data/cost_scenarios_validation.json').write_text(json.dumps(report,ensure_ascii=False,indent=2,default=str)+'\n')
print(json.dumps({k:v for k,v in report.items() if k not in ['preserved_tables','limits']},ensure_ascii=False,default=str))
