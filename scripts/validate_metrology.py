"""Independent raw-register comparison and API checks in rehearsed DB only."""
import os,sys,json,sqlite3,csv,io,hashlib
from pathlib import Path
from collections import defaultdict,Counter
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from metrology_raw_register import rows_at
proof=json.loads((ROOT/'data/metrology_import_rehearsal.json').read_text());copy=Path(proof['isolated_db'])
assert copy.exists() and copy.resolve()!=(ROOT/'data/platform.sqlite3').resolve()
raw=defaultdict(list)
with sqlite3.connect(copy) as c:
    for ds,value in c.execute('SELECT dataset,"values" FROM app_record'):raw[ds].append(json.loads(value))
clocks=[('2026-10-01T18:00:00','2026-10-01T18:00:00'),('2026-09-22T18:00:00','2026-09-22T18:00:00'),('2026-09-22T18:00:00','2026-10-01T18:00:00')]
independent={key:rows_at(raw,*key) for key in clocks}
os.environ['MOTOR_SQLITE_PATH']=str(copy);os.environ['DJANGO_SETTINGS_MODULE']='config.settings'
import django;django.setup()
from django.conf import settings
assert Path(settings.DATABASES['default']['NAME']).resolve()==copy.resolve()
from app import metrology as eng,metrology_views as views,access,analytics
from app.models import Record,AuditEvent
from django.contrib.auth.models import User
from django.test import Client
reports=[];snapshots={}
for at,known in clocks:
    m=eng.Metrology(cutoff=at,known_cutoff=known);expected=independent[at,known];assert set(m.index)==set(expected)
    for key,values in expected.items():
        for field,value in values.items():
            actual=sorted(m.index[key][field]) if field=='notice_ids' else m.index[key][field]
            assert actual==value,(at,known,key,field,actual,value)
    assert not m.global_issues;snapshots[at,known]=m
    reports.append(dict(as_of=at,known_as_of=known,raw_measurements=len(expected),summary=eng.summary(m.rows),independently_checked_fields=sorted(next(iter(expected.values())))))
m=snapshots[clocks[0]];cases=json.loads((ROOT/'data/metrology_scenario_build.json').read_text())['cases']
for name in ['missing_identity','wrong_channel','wrong_time','withdrawn_usage','duplicate_latest_usage']:
    assert m.index[cases[name]]['calibration_state']=='unknown_use',name
for key in cases['missing_usage_readings']:assert m.index[key]['calibration_state']=='unknown_use',key
assert m.index[cases['late_corrected_usage']]['calibration_state']=='valid'
assert Counter(r['calibration_state'] for r in m.rows if r['required'] and not r['voided'])=={'valid':30293,'invalid':3012,'unknown_use':23,'withdrawn':1557,'expired':2356,'failed':1046,'pending':80,'missing':60,'conflict':30}
old_facts=list(Record.objects.order_by('id').values());before=AuditEvent.objects.count();client=Client();assert client.get('/api/metrology').status_code==401
admin=User.objects.get(username='demo_admin');client.force_login(admin)
board=client.get('/api/metrology');assert board.status_code==200,board.content;assert board['Cache-Control']=='no-store';b=board.json();assert b['summary']==eng.summary(m.rows);assert b['total']==43782
scope={'receipt':b['receipt']};key=next(r['id'] for r in m.rows if r['review_state']=='stale');detail=client.get('/api/metrology/rows/'+key,scope);assert detail.status_code==200,detail.content
assert detail.json()['row']['source_result']==m.index[key]['source_result'];assert detail.json()['row']['review_state']=='stale'
sources=client.get('/api/metrology/rows/'+key+'/evidence',scope).json();assert sources['can_download_original'] and all(not s.get('missing') for s in sources['rows'])
assert sources['total']>=len(sources['rows'])>0
all_sources=[]
for p in range(1,(sources['total']+39)//40+1):all_sources+=client.get('/api/metrology/rows/'+key+'/evidence',scope|dict(page=p)).json()['rows']
assert len({(s['dataset'],s['key']) for s in all_sources})==sources['total'];assert all(not s.get('missing') for s in all_sources)
assert all(s['row']>=2 and len(s['file_hash'])==64 and len(s['record_hash'])==64 for s in all_sources)
assert client.get('/api/metrology/rows/'+key,{}).status_code==400
assert client.get('/api/metrology/export').status_code==400
assert client.post('/api/metrology',{}).status_code==405
for bad in [{'as_of':'bad'},{'known_as_of':'2026-08-01T00:00:00'},{'from':'20260922'},{'from':'2026-09-23','to':'2026-09-22'},{'instrument_id':'UNKNOWN'},{'parameter':'UNKNOWN'},{'cal':'UNKNOWN'},{'impact':'UNKNOWN'},{'review':'UNKNOWN'},{'extra':'1'},{'page':'0'}]:assert client.get('/api/metrology',bad).status_code==400,bad
assert client.get('/api/metrology?stage=test&stage=process').status_code==400
assert client.get('/api/metrology/rows/'+key,scope|dict(stage='test')).status_code==409
with patch('app.metrology_views.analytics.revision',side_effect=[tuple(analytics.revision()),('changed',)]):assert client.get('/api/metrology').status_code==409
assert AuditEvent.objects.count()==before
filtered={'stage':'test','cal':'expired','from':'2026-09-22','to':'2026-09-25'};fb=client.get('/api/metrology',filtered).json();bound=filtered|dict(receipt=fb['receipt'])
expected=[r for r in m.cohort(filtered) if r['calibration_state']=='expired'];assert fb['total']==len(expected)
export=client.get('/api/metrology/export',bound);assert export.status_code==200;assert export['Cache-Control']=='no-store';assert export.content.startswith(b'\xef\xbb\xbf')
lines=list(csv.reader(io.StringIO(export.content.decode('utf-8-sig'))));assert len(lines)-5==len(expected);assert {r[0] for r in lines[5:]}=={r['id'] for r in expected}
assert AuditEvent.objects.count()==before+1 and AuditEvent.objects.latest('id').action=='metrology.export'
assert client.get('/api/metrology/rows/'+key,bound).status_code==404
inst=client.get('/api/metrology/instruments',scope).json();assert inst['total']==150
archived=[]
for p in range(1,7):archived+=client.get('/api/metrology/instruments',scope|dict(page=p)).json()['rows']
assert sum(x['instrument']['stage']=='档案' and x['no_use_in_scope'] for x in archived)==14
at,known=clocks[2];q={'as_of':at,'known_as_of':known};cb=client.get('/api/metrology',q).json();changed=[r for r in snapshots[at,known].rows if any(r[k]!=snapshots[at,at].index[r['id']][k] for k in ['required','use_id','instrument_id','calibration_id','calibration_state','impact_state','notice_ids','review_state'])]
comp=client.get('/api/metrology/comparison',q|dict(receipt=cb['receipt']));assert comp.status_code==200,comp.content;assert comp.json()['total']==len(changed)>0
other=next(u for u in User.objects.filter(is_active=True) if access.role(u) and not access.can_import(u));client.force_login(other)
assert client.get('/api/metrology/rows/'+key,scope).status_code==409
ob=client.get('/api/metrology').json();oe=client.get('/api/metrology/rows/'+key+'/evidence',dict(receipt=ob['receipt'])).json();assert not oe['can_download_original']
assert client.get('/api/imports/'+oe['rows'][0]['batch_id']+'/file').status_code==403
assert list(Record.objects.order_by('id').values())==old_facts
report={'synthetic':True,'isolated_db':str(copy),'independent_raw_register':True,'cutoffs':reports,'manual_edge_cases':True,'api':{'read_auth':True,'strict_filters':True,'scope_receipts':True,'changed_source_rejected':True,'readonly_facts':True,'source_metadata':True,'source_original_permissions':True,'full_filtered_csv_rows':len(expected),'registration_comparison_changes':len(changed)},'browser':{'rendered':False,'mobile':False,'actual_download':False,'reason':'此前浏览器自动授权连续两次超时；待询未获答复。隔离API检查不能代替浏览器验收。'}}
(ROOT/'data/metrology_validation.json').write_text(json.dumps(report,ensure_ascii=False,indent=2));print(json.dumps({k:v for k,v in report.items() if k!='cutoffs'},ensure_ascii=False))
