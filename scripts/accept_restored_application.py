"""Exercise a separately restored local demo over real HTTP, with bounded writes.

Only the restored installation receives logins, duplicate Excel upload and a
personal BI view/snapshot. The source installation is checked byte-exact.
No browser, UI rendering, real-system access, business approval or code issuing.
"""
import argparse,csv,hashlib,http.cookiejar,io,json,sqlite3,sys,time,urllib.error,urllib.parse,urllib.request,uuid
from collections import Counter
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'scripts'))
import recovery
EXPECTED='cc1e22daf15ffeb1858d946dc1698a5ed9769c41e97a2d32885337a279c131bf'
MAIN_SHA='cc17088ff8da71770975a599da397faee8ae074f6efd85dc83a825f7ea0d4866'

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):raise RuntimeError('Unexpected redirect during local acceptance')
class Client:
    def __init__(self,port):
        self.base='http://127.0.0.1:'+str(port);self.jar=http.cookiejar.CookieJar();self.opener=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar),NoRedirect())
    def call(self,path,payload=None,*,raw=None,content_type=None,expected=200,csrf=True,binary=False):
        assert path.startswith('/') and not path.startswith('//')
        headers={};data=None
        if payload is not None:data=json.dumps(payload,ensure_ascii=False).encode();headers['Content-Type']='application/json'
        if raw is not None:data=raw;headers['Content-Type']=content_type
        if data is not None and csrf:
            token=next((c.value for c in self.jar if c.name=='csrftoken'),None)
            if token:headers['X-CSRFToken']=token
        req=urllib.request.Request(self.base+path,data=data,headers=headers)
        try:
            with self.opener.open(req,timeout=45) as response:body=response.read(60*1024*1024);status=response.status
        except urllib.error.HTTPError as ex:body=ex.read(1024*1024);status=ex.code
        if status!=expected:
            message=body.decode(errors='replace')[:1000];raise RuntimeError(f'{path}: expected {expected}, got {status}: {message}')
        return body if binary or expected!=200 else json.loads(body)
    def login(self,user):
        self.call('/',binary=True)
        result=self.call('/api/auth',dict(username=user,password='MotorDemo!2026'))
        assert result['authenticated'] and result['username']==user;return result
def quote(v):return urllib.parse.quote(str(v),safe='')
def multipart(filename,raw):
    boundary='motor-restore-'+uuid.uuid4().hex
    assert '"' not in filename and '\n' not in filename and '\r' not in filename
    head=(f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{filename}"\r\nContent-Type: application/vnd.openxmlformats-officedocument.spreadsheetml.sheet\r\n\r\n').encode()
    return head+raw+f'\r\n--{boundary}--\r\n'.encode(),'multipart/form-data; boundary='+boundary
def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--target',type=Path,required=True);parser.add_argument('--port',type=int,required=True);args=parser.parse_args();target=args.target.resolve()
    assert target!=ROOT and target.is_relative_to(ROOT/'data/recovery-rehearsals') and 1024<=args.port<=65535 and args.port!=8765
    ready=json.loads((target/'data/recovery-restore.json').read_text());assert ready['status']=='ready' and ready['archive_sha256']==EXPECTED and Path(ready['target'])==target
    assert recovery.sha_file(ROOT/'data/platform.sqlite3')==MAIN_SHA
    base=json.loads((ROOT/'data/topic_linkage_recovery_verify.json').read_text())['database'];initial=recovery.database_inventory(target/'data/platform.sqlite3')
    # Restarting a preflight after an HTTP observation failure may have left
    # only native login events. Preserve them and report the entire delta.
    prechanged={k for k,v in initial['tables'].items() if v!=base['tables'][k]}
    assert prechanged<={'auth_user','django_session','app_auditevent'},prechanged
    with recovery.connect_readonly(target/'data/platform.sqlite3') as db:
        old=db.execute('SELECT action FROM app_auditevent WHERE id>780').fetchall();assert all(x[0]=='auth.login' for x in old)
        rows={}
        for ds,values in db.execute('SELECT dataset,"values" FROM app_record'):rows.setdefault(ds,[]).append(json.loads(values))
        batch=next((str(uuid.UUID(k)),n,h) for k,n,h,m,s in db.execute('SELECT id,filename,file_hash,mapping,status FROM app_importbatch') if json.loads(m)=={} and s in ('committed','partial'))
        transform_id=str(uuid.UUID(db.execute('SELECT id FROM app_devicetransformreceipt').fetchone()[0]))
        collector_id=str(uuid.UUID(db.execute('SELECT id FROM app_devicecollectionrun').fetchone()[0]))
    report=dict(restore_archive_sha256=EXPECTED,restored_target=str(target),port=args.port,transport='Native local HTTP, no browser',boards=[],roles=[],checks={},success=False)
    out=ROOT/'data/application_restore_http_validation.json'
    try:
        admin=Client(args.port);admin.login('demo_admin');print('Restored demo admin login passed',flush=True)
        paths=['overview','production','delivery','quality','manufacturing','process-quality','wip-flow','metrology','metrology-evidence','supply','stocktake','inventory-age','material-planning','receivables','payables','logistics','assets','workforce','energy','service','engineering','sales','targets','assembly-plans','device-intake','device-collection','device-transform','device-files','action-tasks','coordination-hub','issue-workspace','bi-field-catalog','coding','catalog']
        for path in paths:
            value=admin.call('/api/'+path);report['boards'].append(dict(path=path,status=200));print('Board passed: '+path,flush=True)
        ctx=admin.call('/api/topics/3/workspace');conf=dict(scope={},reference_scope={},primary_label='恢复后当前范围',reference_label='恢复后相同参照')
        result=admin.call('/api/topics/3/run',dict(context_token=ctx['context_token'],config=conf))
        result=admin.call('/api/topics/3/link-select',dict(context_token=result['context_token'],facts_token=result['facts_token'],config=result['config'],slot=3,side='primary',group='MO2609-000001'))
        result=admin.call('/api/topics/3/run',dict(context_token=ctx['context_token'],config=result['config']));conf=result['config']
        expected=[{r['id'] for r in rows['units'] if r['work_order_id']=='MO2609-000001'},{r['id'] for r in rows['operations'] if r['work_order_id']=='MO2609-000001'},{'MO2609-000001'},{'MO2609-000001'}]
        for slot,wanted in enumerate(expected):
            for side in ('primary','reference'):
                ids=[];page=1
                while True:
                    data=admin.call('/api/topics/3/evidence',dict(context_token=result['context_token'],facts_token=result['facts_token'],config=conf,slot=slot,side=side,group=None,page=page));ids.extend(r['values']['id'] for r in data['rows'])
                    if page*30>=data['total']:break
                    page+=1
                assert len(ids)==len(set(ids)) and set(ids)==wanted
        assert result['cards'][0]['scope_summary']['primary']['value']==20
        report['checks']['linked_sources']=dict(counts=[len(x) for x in expected],both_sides_and_all_pages_match=True)
        view=admin.call('/api/topics/3/views',dict(context_token=ctx['context_token'],config=conf,name='恢复验收 · 工单跨卡复盘'))
        reopened=admin.call('/api/topics/3/workspace');assert next(v for v in reopened['views'] if v['id']==view['id'])['config']==conf
        snapshot=admin.call('/api/topics/3/snapshots',dict(request_id=str(uuid.uuid4()),context_token=ctx['context_token'],facts_token=result['facts_token'],summary_token=result['summary_token'],config=conf,name='恢复验收 · 工单结果',note='仅在独立还原目录验证分析配置与来源，未更改业务事实'))
        frozen=admin.call('/api/topics/3/snapshots/'+snapshot['id']);assert frozen['result']['config']==conf
        compared=admin.call('/api/topics/3/snapshots/'+snapshot['id']+'/compare',{});assert not compared['blocked']
        for slot in range(4):
            q=urllib.parse.urlencode(dict(context_token=result['context_token'],facts_token=result['facts_token'],config=json.dumps(conf),slot=slot));raw=admin.call('/api/topics/3/export?'+q,binary=True)
            csv_rows=list(csv.reader(io.StringIO(raw.decode('utf-8-sig'))));assert '专题联动条件与直接字段' in csv_rows[0]
        q=urllib.parse.urlencode(dict(context_token=result['context_token'],facts_token=result['facts_token'],summary_token=result['summary_token'],config=json.dumps(conf)));raw=admin.call('/api/topics/3/summary/export?'+q,binary=True);assert json.loads(list(csv.reader(io.StringIO(raw.decode('utf-8-sig'))))[2][1])==conf
        frozen_csv=admin.call('/api/topics/3/snapshots/'+snapshot['id']+'/export',binary=True);assert '保存的联动条件与逐卡直接字段' in list(csv.reader(io.StringIO(frozen_csv.decode('utf-8-sig'))))[0]
        report['checks']['native_saved_view_snapshot_exports']=dict(view_id=view['id'],snapshot_id=snapshot['id'],reopen_and_current_compare=True,all_card_and_summary_csv=True)
        # Paths now resolve to the restored originals. Re-upload the exact
        # archive through the real multipart endpoint; never commit new facts.
        workbook=admin.call('/api/imports/'+batch[0]+'/file',binary=True);assert hashlib.sha256(workbook).hexdigest()==batch[2]
        payload,ctype=multipart(batch[1],workbook);upload=admin.call('/api/imports',raw=payload,content_type=ctype);assert upload['repeated'] and upload['id']==batch[0]
        report['checks']['excel_archive']=dict(file_hash_matches=True,duplicate_upload_reuses_original_batch=True,no_commit_called=True)
        receipt=admin.call('/api/device-transform/receipts/'+transform_id);assert receipt['source']['current_integrity']==receipt['output']['current_integrity']=='ok' and all(c['current_target_unchanged'] for c in receipt['current_targets'])
        binary=admin.call('/api/device-files/'+receipt['output']['id']+'/original',binary=True);assert hashlib.sha256(binary).hexdigest()==receipt['payload']['preview']['output_sha256']
        raw=admin.call('/api/device-transform/receipts/'+transform_id+'/export?'+urllib.parse.urlencode(dict(receipt=receipt['receipt'])),binary=True);assert len(list(csv.reader(io.StringIO(raw.decode('utf-8-sig')))))-4==24
        history=admin.call('/api/device-collection/runs/'+collector_id);assert len(history['rows'])==5 and all(r['archive']['current_integrity']=='ok' for r in history['rows'])
        first=admin.call('/api/device-collection/preview',dict(source_id='DS-PC-2026-001',prior_receipt=None));time.sleep(2.1)
        second=admin.call('/api/device-collection/preview',dict(source_id='DS-PC-2026-001',prior_receipt=first['receipt']));assert sum(r['eligible'] for r in second['items'])==5
        report['checks']['device_original_and_transformation']=dict(native_binary_download_hash_matches=True,transformation_rows=24,current_session_targets_match=True,historical_collection_originals=5,new_root_stable_observation=True,no_collection_or_association_called=True)
        roles=[('demo_quality','quality'),('demo_operations','operations'),('demo_finance','finance'),('demo_analyst','analyst'),('demo_viewer','viewer')]
        for name,role in roles:
            client=Client(args.port);info=client.login(name);assert info['role']==role
            current=client.call('/api/topics/3/workspace');card=client.call('/api/topics/3/run',dict(context_token=current['context_token'],config=conf));assert card['cards'][0]['primary']['matched']==20
            if role!='finance' and role!='analyst':client.call('/api/records/costs',expected=403,binary=True)
            if role=='quality':assert client.call('/api/device-transform')['receipts']==[]
            else:client.call('/api/device-transform',expected=403,binary=True)
            report['roles'].append(dict(username=name,role=role,native_login_and_scope=True,access_boundaries=True))
        outsider=Client(args.port);outsider.call('/api/topics/3/workspace',expected=401,binary=True)
        admin.call('/api/topics/3/link-select',{},expected=403,csrf=False,binary=True)
        report['checks']['auth_csrf']=dict(unauthenticated_rejected=True,csrf_missing_rejected=True,private_templates_not_shared=True)
        report['success']=True
    except Exception as ex:report['failure']=str(ex);raise
    finally:
        final=recovery.database_inventory(target/'data/platform.sqlite3');changed={k for k,v in final['tables'].items() if v!=base['tables'][k]};allowed={'auth_user','django_session','app_auditevent','app_topicview','app_topicsnapshot'}
        assert changed<=allowed,changed
        assert final['tables']['app_record']==base['tables']['app_record'] and final['tables']['app_importrow']==base['tables']['app_importrow'] and final['tables']['app_importbatch']==base['tables']['app_importbatch']
        with recovery.connect_readonly(target/'data/platform.sqlite3') as db:events=Counter(r[0] for r in db.execute('SELECT action FROM app_auditevent WHERE id>780'))
        permitted={'auth.login','topic_view.save','topic_snapshot.create','topic_scope_summary.export','import.source_download','import.upload','device_file.download','device_transform.export'};assert set(events)<=permitted,events
        report['restored_database_changes']=dict(tables=sorted(changed),audit_actions=dict(events),all_other_tables_and_business_rows_unchanged=True)
        report['main_database_unchanged']=recovery.sha_file(ROOT/'data/platform.sqlite3')==MAIN_SHA;assert report['main_database_unchanged']
        report.update(browser_rendered_verified=False,mobile_verified=False,real_systems_connected=False)
        out.write_text(json.dumps(report,ensure_ascii=False,indent=2));print(json.dumps(dict(success=report['success'],boards=len(report['boards']),roles=len(report['roles']),main_database_unchanged=True),ensure_ascii=False),flush=True)
if __name__=='__main__':main()
