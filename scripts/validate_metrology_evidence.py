"""Independent raw certificate/queue ledger and isolated API permission checks."""
import os,sys,json,sqlite3,csv,io,hashlib,uuid
from pathlib import Path
from collections import defaultdict
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from metrology_evidence_raw import certificates_at,instruments_at
proof=json.loads((ROOT/'data/metrology_evidence_import_rehearsal.json').read_text());dbpath=Path(proof['isolated_db']);workspace=dbpath.parent
assert dbpath.exists() and dbpath.resolve()!=(ROOT/'data/platform.sqlite3').resolve()
main_hash=hashlib.sha256((ROOT/'data/platform.sqlite3').read_bytes()).hexdigest();raw=defaultdict(list)
with sqlite3.connect(dbpath) as c:
    for ds,value in c.execute('SELECT dataset,"values" FROM app_record'):raw[ds].append(json.loads(value))
    c.row_factory=sqlite3.Row;files={r['id']:dict(r) for r in c.execute('SELECT * FROM app_devicefile')}
    admin_id=c.execute("SELECT id FROM auth_user WHERE username='demo_admin'").fetchone()[0]
os.environ['MOTOR_SQLITE_PATH']=str(dbpath);os.environ['DJANGO_SETTINGS_MODULE']='config.settings'
import django;django.setup()
from django.conf import settings
from django.test import Client,override_settings
from django.contrib.auth.models import User
from app import metrology as reg,metrology_evidence as eng,metrology_evidence_views as views,device_files as df,file_sharing as sharing,analytics
from app.models import Record,AuditEvent,FileReadGrant,DeviceFile
assert Path(settings.DATABASES['default']['NAME']).resolve()==dbpath.resolve()
admin=User.objects.get(pk=admin_id);clocks=[('2026-10-01T18:00:00','2026-10-01T18:00:00'),('2026-09-22T18:00:00','2026-09-22T18:00:00'),('2026-09-22T18:00:00','2026-10-01T18:00:00')]
build=json.loads((ROOT/'data/metrology_evidence_scenario_build.json').read_text());cases=build['cases'];reports=[]
def facts_digest():
    h=hashlib.sha256()
    with sqlite3.connect(dbpath) as c:
        for row in c.execute('SELECT * FROM app_record ORDER BY id'):h.update(repr(row).encode())
    return h.hexdigest()
before_facts=facts_digest()
def get(client,url,params=None,status=200):
    r=client.get(url,params or {});assert r.status_code==status,(url,status,r.status_code,r.content[:400]);return r
def content(r):return b''.join(r.streaming_content) if r.streaming else r.content
def grant(owner,file,recipient,action='grant',expires=''):
    value=dict(recipient_id=recipient.pk,action=action,reason='隔离副本的模拟证书协作核查',expires_at=expires)
    p=sharing.preview(owner,file.pk,value);return sharing.commit(owner,file.pk,value|dict(token=p['token'],request_id=str(uuid.uuid4())))
with override_settings(BASE_DIR=workspace,DEVICE_FILE_ROOT=workspace/'data/device_files'):
    for business,known in clocks:
        checks=certificates_at(raw,known,files,workspace/'data/device_files',admin.pk)
        m=reg.Metrology(cutoff=business,known_cutoff=known);e=eng.Evidence(m,resolve=eng.resolver(admin))
        expected=instruments_at(raw,business,known,checks)
        assert set(checks)==set(e.inspections)
        for key,value in checks.items():
            for field,answer in value.items():assert e.inspections[key][field]==answer,(key,field,e.inspections[key][field],answer)
        assert set(expected)==set(e.index)
        for key,value in expected.items():
            actual=e.index[key]
            for field,answer in value.items():
                seen=actual['calibration']['id'] if field=='calibration_id' and actual['calibration'] else None if field=='calibration_id' else actual[field]
                assert seen==answer,(business,known,key,field,seen,answer)
        reports.append(dict(as_of=business,known_as_of=known,raw_calibration_checks=len(checks),raw_instrument_channels=len(expected)))
    e=eng.Evidence(reg.Metrology(),resolve=eng.resolver(admin));assert eng.summary(e.cohort({}))==build['current_summary']
    manual={'missing_link':'missing_link','withdrawn':'withdrawn','duplicate_latest':'record_attention','broken_chain':'record_attention','file_missing':'file_missing','file_attention':'file_attention','content_attention':'content_attention','record_attention':'record_attention','unparsed':'unparsed','no_access':'no_access','duplicate_content':'content_attention','issued_attention':'record_attention','late_correction':'consistent'}
    for name,state in manual.items():assert e.index[cases[name]['instrument_id']]['evidence_state']==state,name
    client=Client();get(client,'/api/metrology-evidence',status=401);client.force_login(admin);audits=AuditEvent.objects.count()
    base=get(client,'/api/metrology-evidence');assert base['Cache-Control']=='no-store';b=base.json();assert b['total']==136 and b['summary']==build['current_summary']
    assert get(client,'/api/metrology-evidence',{'archives':'1'}).json()['total']==150
    assert get(client,'/api/metrology-evidence',{'window':'90'}).json()['summary']['due_counts']['due']==121
    for bad in [{'as_of':'bad'},{'known_as_of':'2026-08-01T00:00:00'},{'stage':'bad'},{'state':'bad'},{'due':'bad'},{'archives':'2'},{'window':'0'},{'window':'366'},{'window':'３０'},{'page':'0'},{'instrument_id':'UNKNOWN'},{'extra':'1'}]:get(client,'/api/metrology-evidence',bad,400)
    get(client,'/api/metrology-evidence?state=consistent&state=no_access',status=400)
    assert client.post('/api/metrology-evidence',{}).status_code==405
    get(client,'/api/metrology-evidence/export',status=400)
    key=next(r['id'] for r in e.rows if r['evidence_state']=='consistent');cal=e.index[key]['calibration']['id'];bound={'receipt':b['receipt']}
    detail=get(client,'/api/metrology-evidence/rows/'+key,bound).json();assert detail['row']['id']==key
    assert set(detail['field_labels'])=={'metrology_instruments','metrology_calibrations',*eng.TABLES}
    get(client,'/api/metrology-evidence/rows/'+key,status=400)
    source=get(client,'/api/metrology-evidence/rows/'+key+'/evidence',bound).json();assert source['can_download_original']
    assert source['rows'] and all(not r.get('missing') and r['row']>=2 and len(r['file_hash'])==64 and len(r['record_hash'])==64 for r in source['rows'])
    assert any(r['dataset']=='metrology_certificates' for r in source['rows'])
    assert AuditEvent.objects.count()==audits,'Reading must not create audit or business events'
    filters={'state':'consistent'};fb=get(client,'/api/metrology-evidence',filters).json();q=filters|dict(receipt=fb['receipt'])
    export=get(client,'/api/metrology-evidence/export',q);assert export['Cache-Control']=='no-store'
    lines=list(csv.reader(io.StringIO(export.content.decode('utf-8-sig'))));assert len(lines)-5==fb['total']==112
    assert {r[0] for r in lines[5:]}=={r['id'] for r in e.rows if r['evidence_state']=='consistent'}
    get(client,'/api/metrology-evidence/rows/'+cases['missing_link']['instrument_id'],q,404)
    get(client,'/api/metrology-evidence/rows/'+key,bound|dict(window='90'),409)
    original=detail['row']['calibration'];file=DeviceFile.objects.get(pk=e.inspections[cal]['certificate']['file_id']);path=df.path(file);saved=path.read_bytes()
    r=get(client,f'/api/metrology-evidence/rows/{key}/original/{cal}',bound);assert content(r)==saved
    get(client,f'/api/metrology-evidence/rows/{key}/original/{cases["content_attention"]["calibration_id"]}',bound,404)
    c=cases['file_attention'];get(client,f'/api/metrology-evidence/rows/{c["instrument_id"]}/original/{c["calibration_id"]}',bound,409)
    old_audits=AuditEvent.objects.count()
    try:
        path.write_bytes(b'tampered isolated original');get(client,'/api/metrology-evidence/rows/'+key,bound,409)
        fresh=get(client,'/api/metrology-evidence').json();assert fresh['receipt']!=b['receipt']
        get(client,f'/api/metrology-evidence/rows/{key}/original/{cal}',{'receipt':fresh['receipt']},409)
    finally:path.write_bytes(saved)
    assert AuditEvent.objects.count()==old_audits
    calls=[0];factory=eng.resolver
    def change_during_read(user):
        calls[0]+=1
        if calls[0]==2:path.write_bytes(b'changed during isolated request')
        return factory(user)
    try:
        with patch('app.metrology_evidence_views.eng.resolver',side_effect=change_during_read):get(client,'/api/metrology-evidence',status=409)
    finally:path.write_bytes(saved)
    assert AuditEvent.objects.count()==old_audits
    viewer=User.objects.get(username='demo_viewer');client.force_login(viewer);vb=get(client,'/api/metrology-evidence').json();vs={'receipt':vb['receipt']}
    get(client,'/api/metrology-evidence/rows/'+key,bound,409)
    hidden=get(client,'/api/metrology-evidence/rows/'+key,vs).json();inspection=next(v for v in hidden['inspections'] if v['calibration_id']==cal)
    assert inspection['state']=='no_access' and inspection['file'] is None and inspection['parsed'] is None and file.filename not in json.dumps(hidden,ensure_ascii=False)
    get(client,f'/api/metrology-evidence/rows/{key}/original/{cal}',vs,404)
    source=get(client,'/api/metrology-evidence/rows/'+key+'/evidence',vs).json();assert not source['can_download_original']
    assert client.get('/api/imports/'+source['rows'][0]['batch_id']+'/file').status_code==403
    assert FileReadGrant.objects.count()==0
    grant(admin,file,viewer);get(client,'/api/metrology-evidence/rows/'+key,vs,409)
    allowed=get(client,'/api/metrology-evidence').json();qs={'receipt':allowed['receipt']}
    actual=get(client,f'/api/metrology-evidence/rows/{key}/original/{cal}',qs);assert content(actual)==saved
    grant(admin,file,viewer,'revoke');get(client,f'/api/metrology-evidence/rows/{key}/original/{cal}',qs,409)
    new=get(client,'/api/metrology-evidence').json();get(client,f'/api/metrology-evidence/rows/{key}/original/{cal}',{'receipt':new['receipt']},404)
    # The administrator still cannot read a quality owner's private original.
    client.force_login(admin);ab=get(client,'/api/metrology-evidence').json();c=cases['no_access']
    get(client,f'/api/metrology-evidence/rows/{c["instrument_id"]}/original/{c["calibration_id"]}',{'receipt':ab['receipt']},404)
    assert facts_digest()==before_facts
assert hashlib.sha256((ROOT/'data/platform.sqlite3').read_bytes()).hexdigest()==main_hash
report={'synthetic':True,'isolated_db':str(dbpath),'independent_raw_certificate_and_instrument_queue':True,'cutoffs':reports,'manual_edge_cases':len(manual),
        'api':{'authentication':True,'strict_filters':True,'scope_receipts':True,'readonly_facts':True,'sources_and_source_permissions':True,'complete_filtered_csv':True,
               'exact_original_download':True,'default_private_no_admin_override':True,'explicit_grant_and_revoke':True,'stale_grant_receipt_rejected':True,
               'tampered_bytes_rejected':True,'mid_read_byte_changes_rejected':True,'archive_denominator_separate':True,'reminder_window_checked':True},
        'main_database_unchanged':True,'browser':{'rendered':False,'mobile':False,'actual_download':False,'reason':'浏览器授权仍待用户答复；隔离API不能替代浏览器验收。'}}
(ROOT/'data/metrology_evidence_validation.json').write_text(json.dumps(report,ensure_ascii=False,indent=2));print(json.dumps(report,ensure_ascii=False))
