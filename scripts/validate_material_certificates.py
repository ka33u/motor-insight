"""Independent receipt/document identity, file bytes and baseline audit."""
import os,sys,json,sqlite3,tempfile,zipfile,hashlib,copy,csv,io,re
from pathlib import Path
from collections import defaultdict,Counter
from decimal import Decimal
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings')
import django;django.setup()
from django.db import connection
from django.contrib.auth.models import User
from app.models import Record,ImportBatch,DeviceFile,MetricVersion,AnalysisModel,Topic,TopicView,TopicSnapshot
from app.schema import SCHEMAS
from app import analytics,material_certificates as eng,device_files,supply,purchase_commitments,receipt_flow,incoming_quality,analysis_engine,targets,metric_registry
connection.cursor().execute('PRAGMA query_only=ON');admin=User.objects.get(username='demo_admin')
result={'synthetic':True,'baseline':'data/backups/motor-backup-20261006-092642.zip','preserved_original_files':0,'preserved_tables':{}}
with zipfile.ZipFile(ROOT/result['baseline']) as z,tempfile.TemporaryDirectory() as temp:
    p=Path(temp)/'old.db';p.write_bytes(z.read('data/platform.sqlite3'))
    for item in json.loads(z.read('manifest.json'))['files']:
        if item['path'].startswith(('data/imports/','data/device_files/')):
            assert hashlib.sha256((ROOT/item['path']).read_bytes()).hexdigest()==item['sha256'];result['preserved_original_files']+=1
    with sqlite3.connect(p) as old,sqlite3.connect('file:'+str(ROOT/'data/platform.sqlite3')+'?mode=ro',uri=True) as current:
        names=lambda db:{r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")};assert names(old)==names(current)
        additions={'app_record':536,'app_importrow':536,'app_importbatch':1,'app_devicefile':132}
        for table in sorted(names(old)-{'django_session','sqlite_sequence'}):
            a=old.execute('SELECT * FROM '+table+' ORDER BY rowid').fetchall();b=current.execute('SELECT * FROM '+table+' ORDER BY rowid').fetchall()
            if table=='app_auditevent':
                assert b[:len(a)]==a;result['audit_additions']=dict(Counter(r[1] for r in b[len(a):]));assert result['audit_additions']=={'device_file.archive':132,'simulation.certificate_originals':1,'import.stage':1,'import.commit':1,'simulation.xlsx_import':1}
            elif table in additions:assert b[:len(a)]==a and len(b)-len(a)==additions[table],table
            else:assert a==b,table
            result['preserved_tables'][table]={'before':len(a),'after':len(b)}
        before_raw={k:[] for k in SCHEMAS}
        for ds,val in old.execute('SELECT dataset,"values" FROM app_record'):before_raw[ds].append(json.loads(val))
raw=analytics.tables();actual=eng.Certificates(raw,eng.resolver(admin));idx=lambda ds:{r['id']:r for r in raw[ds]}
certs=idx('material_certificates');po=idx('purchase_lines');links=defaultdict(list);properties=defaultdict(list)
for r in raw['receipt_certificate_links']:links[r['receipt_id']].append(r)
for r in raw['material_certificate_properties']:properties[r['certificate_id']].append(r)
files={str(f.pk):f for f in DeviceFile.objects.all()};observed=Counter();source_keys=set();content_rows=0
for receipt in raw['receipts']:
    active=sorted([v for v in links[receipt['id']] if v['recorded']<=analytics.AS_OF],key=lambda v:(v['recorded'],v['id']));link=None;c=None
    if not active:state='missing_link'
    elif any(n>1 for n in Counter(v['recorded'] for v in active).values()) or any(n>1 for n in Counter(v['version'] for v in active).values()):state='record_attention'
    else:
        link=active[-1];c=certs[link['certificate_id']];pp=properties[c['id']];bad=False
        bad |= any(v['version']!=i+1 or v['previous_id']!=(active[i-1]['id'] if i else None) for i,v in enumerate(active))
        bad |= not (receipt['received']<=link['recorded']<=analytics.AS_OF) or link['lot']!=receipt['lot'] or link['supplier_lot']!=c['supplier_lot']
        bad |= c['number']!=receipt['certificate'] or c['material_id']!=receipt['material_id'] or c['supplier_id']!=po[receipt['purchase_line_id']]['supplier_id']
        bad |= c['issued']>receipt['received'][:10] or c['issued']>analytics.AS_OF[:10] or c['property_count']!=len(pp)
        bad |= bool(c['file_id'] and not re.fullmatch('[0-9a-f]{64}',c['file_sha256'] or ''))
        if bad:state='record_attention'
        elif link['status']=='撤销关联':state='withdrawn'
        elif not c['file_id'] or c['file_id'] not in files:state='file_missing'
        else:
            f=files[c['file_id']]
            if f.owner_id!=admin.pk:state='no_access'
            else:
                original=device_files.path(f).read_bytes();sha=hashlib.sha256(original).hexdigest();assert (sha,len(original))==(f.file_hash,f.size)
                if c['file_sha256']!=sha:state='file_attention'
                elif f.kind!='csv':state='unparsed'
                else:
                    reader=csv.DictReader(io.StringIO(original.decode('utf-8-sig')));rr=list(reader);bad=len(reader.fieldnames)!=len(set(reader.fieldnames)) or set(reader.fieldnames)!=set(eng.HEADERS)
                    bad |= len(rr)!=len(pp) or {r['property_id'] for r in rr}!={p['id'] for p in pp}
                    bad |= any(n>1 for n in Counter(r['property_id'] for r in rr).values()) or any(n>1 for n in Counter(r['parameter'] for r in rr).values())
                    pmap={p['id']:p for p in pp};meta={'certificate_no':c['number'],'material_id':c['material_id'],'supplier_id':c['supplier_id'],'supplier_lot':c['supplier_lot'],'issued':c['issued']}
                    for row in rr:
                        p=pmap.get(row['property_id']);bad|=not p or any(row[k]!=v for k,v in meta.items())
                        if p:bad|=any(row[k]!=p[k] for k in ['parameter','unit','method','reference']) or not Decimal(row['value']).is_finite() or Decimal(row['value'])!=Decimal(str(p['value']))
                    state='content_attention' if bad else 'consistent';content_rows+=len(rr)
    r=actual.index[receipt['id']];assert r['state']==state,(receipt['id'],state,r['state'])
    assert r['link_id']==(link['id'] if link else None);assert r['raw_receipt_status']==receipt['status'];assert r['raw_certificate_number']==receipt['certificate'];observed[state]+=1;source_keys.update((x['dataset'],x['key']) for x in r['sources'])
assert sum(observed.values())==133 and observed['consistent']==108
proof=json.loads((ROOT/'data/material_certificate_scenario_build.json').read_text());assert eng.summary(actual.rows)==proof['summary']
with zipfile.ZipFile(ROOT/'outputs/材质证明_模拟原件包.zip') as z:
    assert not z.testzip()
    for item in proof['files']:
        data=z.read(item['filename']);assert (len(data),hashlib.sha256(data).hexdigest())==(item['bytes'],item['sha256'])
        if item['archived']:
            f=next(f for f in files.values() if f.filename==item['filename']);data=device_files.path(f).read_bytes();assert (len(data),hashlib.sha256(data).hexdigest())==(f.size,f.file_hash)==(item['bytes'],item['sha256'])
records={(r.dataset,r.business_key):r for r in Record.objects.select_related('source_row__batch') if (r.dataset,r.business_key) in source_keys};assert len(records)==len(source_keys)
for obj in records.values():assert Path(obj.source_row.batch.file_path).exists()
def old_results(data):
    d=supply.SupplyData(data);return {'purchase':[supply.clean(r) for r in d.po_rows],'lots':[supply.clean(r) for r in d.lots],'commitments':purchase_commitments.summary(purchase_commitments.Commitments(data).rows),'flow':receipt_flow.summary(receipt_flow.ReceiptFlow(data).rows),'characteristics':incoming_quality.summary(incoming_quality.IncomingQuality(data).rows)}
assert old_results(before_raw)==old_results(raw)
base=json.loads((ROOT/'data/assembly_plans_before.json').read_text())
def projection(value):
    value=copy.deepcopy(value);value.pop('metric_receipt',None)
    for k in ['pivot','scatter']:
        if value.get(k):value[k].pop('revision',None)
    return json.loads(json.dumps(value,ensure_ascii=False,default=str))
for mid,old in base['models'].items():
    model=AnalysisModel.objects.get(pk=mid);assert projection(analysis_engine.run_analysis(admin,model.dataset,model.definition))==projection(old),mid
assert {r['id']:json.loads(json.dumps(r,default=str)) for r in targets.Targets(admin).rows.values()}=={r['id']:r for r in base['targets']}
metric=MetricVersion.objects.get(metric__key='DELIVERY_OTIF',version=8,status='published');assert metric.calculation_hash==metric_registry.calculation_hash(metric.metric.dataset)=='9d9a5af3d45172eca16790d628a36bc6acbe18d1e2a811a66a5b5fbff7037fe3'
result.update(summary=eng.summary(actual.rows),independent_checks={'receipts':len(actual.rows),'states':dict(observed),'raw_content_rows_read':content_rows,'original_files':133,'archived_originals':132,'unique_excel_sources':len(source_keys),'original_results_unchanged':True},preserved_results={'models':52,'targets':33,'metric_version':8},browser={'rendered':False,'mobile':False,'actual_download':False,'upload_ui':False,'reason':'浏览器自动授权检查连续两次超时，待询答复尚未收到；本轮仅进行独立代码、文件及数据验证'})
result['counts']={'records':Record.objects.count(),'datasets':Record.objects.values('dataset').distinct().count(),'workbooks':ImportBatch.objects.exclude(status='superseded').count(),'models':AnalysisModel.objects.count(),'topics':Topic.objects.count(),'views':TopicView.objects.count(),'snapshots':TopicSnapshot.objects.count(),'device_files':DeviceFile.objects.count()};assert list(result['counts'].values())==[125790,96,28,52,21,6,4,135]
(ROOT/'data/material_certificate_validation.json').write_text(json.dumps(result,ensure_ascii=False,indent=2));print(json.dumps({k:v for k,v in result.items() if k!='preserved_tables'},ensure_ascii=False))
