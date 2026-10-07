"""Exercise real native XLSX through template/import APIs in a database copy."""
import copy,hashlib,json,os,sqlite3,sys,tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
FILE=ROOT/'outputs/01a0f580-2480-7820-bc97-8ca293421c39/32_字段映射演练_模拟.xlsx'
BASE=ROOT/'data/platform.sqlite3'
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
before=sha(BASE);workspace=Path(tempfile.mkdtemp(prefix='motor-import-templates-'));database=workspace/'platform.sqlite3'
with sqlite3.connect('file:'+str(BASE)+'?mode=ro',uri=True) as src,sqlite3.connect(database) as dst:src.backup(dst)
(workspace/'app').symlink_to(ROOT/'app',target_is_directory=True)
os.environ['MOTOR_SQLITE_PATH']=str(database);os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings')
import django;django.setup()
from django.core.management import call_command
call_command('migrate',verbosity=0,interactive=False)
from django.test import Client,override_settings
from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from app.models import ImportBatch,ImportTemplate,ImportTemplateVersion,ImportTemplateUse,Record,AuditEvent
client=Client();client.force_login(User.objects.get(username='demo_admin'))
mapping=json.loads((ROOT/'tests/fixtures/import_mapping_exercise_expected.json').read_text())['mapping']
def post(url,data=None):
    fields={'file':SimpleUploadedFile(FILE.name,FILE.read_bytes())};fields.update(data or {})
    r=client.post(url,fields);assert r.status_code==200,(url,r.status_code,r.content);return r.json()
def digest_records():
    h=hashlib.sha256()
    for r in Record.objects.order_by('id').values():h.update(json.dumps(r,ensure_ascii=False,sort_keys=True,default=str).encode()+b'\n')
    return h.hexdigest()
with override_settings(BASE_DIR=workspace):
    original=digest_records();count=Record.objects.count();batch_count=ImportBatch.objects.count()
    pre=post('/api/imports/mapping/preview',{'mapping':json.dumps(mapping,ensure_ascii=False)})
    new=post('/api/import-templates',{'mapping':json.dumps(mapping,ensure_ascii=False),'inspection_receipt':pre['receipt'],'definition':json.dumps({'code':'TPL-REHEARSAL-001','name':'采购销售仓储模拟模板','department':'采购/销售/仓储','reason':'隔离副本核对4张业务/备注页及原生类型'},ensure_ascii=False)})
    vid=new['version_id'];first_payload=copy.deepcopy(ImportTemplateVersion.objects.get(pk=vid).payload)
    assert not post('/api/import-templates/preview',{'version_id':vid,'purpose':'use'})['template_can_apply']
    approved=post('/api/import-templates/preview',{'version_id':vid,'purpose':'activate'})
    active=post('/api/import-templates/activate',{'template_receipt':approved['template_receipt'],'definition':json.dumps({'revision':approved['template']['revision'],'reason':'本地模拟表头核对后启用'},ensure_ascii=False)})
    assert ImportBatch.objects.count()==batch_count and digest_records()==original
    uses=ImportTemplateUse.objects.count();audits=AuditEvent.objects.count()
    review=post('/api/import-templates/preview',{'version_id':vid,'purpose':'use'})
    assert review['template_can_apply'] and not review['drift']
    assert AuditEvent.objects.count()==audits and ImportTemplateUse.objects.count()==uses
    stage=post('/api/imports',{'mapping':json.dumps(mapping,ensure_ascii=False),'inspection_receipt':review['receipt'],'template_receipt':review['template_receipt']})
    assert stage['summary']==dict(duplicate=15,conflict=1,invalid=1,total=17,unknown_sheets=[],skipped_sheets=['个人备注_不导入'])
    bid=stage['id'];r=client.post('/api/imports/'+bid+'/commit',json.dumps({}),content_type='application/json');assert r.status_code==200
    repeat=post('/api/imports',{'mapping':json.dumps(mapping,ensure_ascii=False),'inspection_receipt':review['receipt'],'template_receipt':review['template_receipt']})
    assert repeat['repeated'] and repeat['id']==bid and ImportTemplateUse.objects.count()==uses+1
    changed=copy.deepcopy(mapping);changed['采购部_供方清单']['fields']['供方编号']='供应商编码'
    next_pre=post('/api/imports/mapping/preview',{'mapping':json.dumps(changed,ensure_ascii=False)})
    next_version=post('/api/import-templates',{'mapping':json.dumps(changed,ensure_ascii=False),'inspection_receipt':next_pre['receipt'],'definition':json.dumps({'template_id':active['id'],'revision':active['revision'],'reason':'同一供方编号显式对应中文字段标签'},ensure_ascii=False)})
    next_review=post('/api/import-templates/preview',{'version_id':next_version['version_id'],'purpose':'activate'})
    post('/api/import-templates/activate',{'template_receipt':next_review['template_receipt'],'definition':json.dumps({'revision':next_review['template']['revision'],'reason':'核对新映射后启用版本2'},ensure_ascii=False)})
    old=ImportTemplateVersion.objects.get(pk=vid);assert old.state=='retired' and old.payload==first_payload
    stale=client.post('/api/imports',{'file':SimpleUploadedFile(FILE.name,FILE.read_bytes()),'mapping':json.dumps(mapping,ensure_ascii=False),'inspection_receipt':review['receipt'],'template_receipt':review['template_receipt']});assert stale.status_code==409
    assert ImportBatch.objects.count()==batch_count+1
    recheck=client.post('/api/imports/'+bid+'/recheck',json.dumps({}),content_type='application/json');assert recheck.status_code==200
    reference=recheck.json()['template_uses'][0];assert reference['version']==1 and reference['evidence']['fresh_template_activation'] is False
    assert Record.objects.count()==count==212466 and digest_records()==original
assert sha(BASE)==before
manifest=json.loads((ROOT/'data/import-templates-before/manifest.json').read_text())
for n,d in manifest['physical'].items():assert sha(ROOT/n)==d,n
for n,d in manifest['protected'].items():assert sha(ROOT/n)==d,n
proof=dict(synthetic=True,native_xlsx_sha256=sha(FILE),isolated_workspace=str(workspace),
    named_template_created_by_api=True,two_immutable_versions=True,fresh_header_review_required_for_activation=True,
    old_use_receipt_rejected_after_new_version=True,preview_did_not_write=True,
    normal_full_stage_commit_replay=True,duplicate=15,conflict=1,invalid=1,
    historical_recheck_keeps_version_without_reactivation=True,all_formal_records_preserved=212466,
    main_database_unchanged=True,main_database_sha256=before,old_physical_files_unchanged=442,protected_files_unchanged=16,
    browser_rendered=False,mobile_interaction=False,actual_browser_upload_download=False)
(ROOT/'data/import_templates_validation.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2));print(json.dumps(proof,ensure_ascii=False,indent=2))
