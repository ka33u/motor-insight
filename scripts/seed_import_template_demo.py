"""Register a synthetic named template through the normal local API views."""
import hashlib,json,os,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings')
import django;django.setup()
from django.contrib.auth.models import User
from django.test import RequestFactory
from django.urls import resolve
from django.core.files.uploadedfile import SimpleUploadedFile
from app.models import ImportTemplate,ImportTemplateVersion,Record,ImportBatch
FILE=ROOT/'outputs/01a0f580-2480-7820-bc97-8ca293421c39/32_字段映射演练_模拟.xlsx'
assert not ImportTemplate.objects.exists(),'Do not overwrite existing named templates'
user=User.objects.get(username='demo_admin');factory=RequestFactory()
mapping=json.loads((ROOT/'tests/fixtures/import_mapping_exercise_expected.json').read_text())['mapping']
count=(Record.objects.count(),ImportBatch.objects.count())
def post(url,fields):
    fields={'file':SimpleUploadedFile(FILE.name,FILE.read_bytes()),**fields};request=factory.post(url,fields);request.user=user
    match=resolve(url);r=match.func(request,**match.kwargs);assert r.status_code==200,(url,r.status_code,r.content);return json.loads(r.content)
reason='合成模拟演练：核对采购、销售、仓储表头及明确忽略项；不是实际部门审批'
review=post('/api/imports/mapping/preview',{'mapping':json.dumps(mapping,ensure_ascii=False)})
new=post('/api/import-templates',{'mapping':json.dumps(mapping,ensure_ascii=False),'inspection_receipt':review['receipt'],'definition':json.dumps({'code':'TPL-SIM-DEPTS-001','name':'采购销售仓储模拟映射','department':'模拟采购/销售/仓储','reason':reason},ensure_ascii=False)})
check=post('/api/import-templates/preview',{'version_id':new['version_id'],'purpose':'activate'})
active=post('/api/import-templates/activate',{'template_receipt':check['template_receipt'],'definition':json.dumps({'revision':check['template']['revision'],'reason':reason},ensure_ascii=False)})
assert (Record.objects.count(),ImportBatch.objects.count())==count==(212466,46)
report=dict(synthetic=True,local_api_views=True,browser_submission=False,session_or_user_state_changed=False,
    no_business_import=True,human_business_approval=False,template=active,reason=reason,
    native_xlsx_sha256=hashlib.sha256(FILE.read_bytes()).hexdigest())
(ROOT/'data/import_templates_actual_setup.json').write_text(json.dumps(report,ensure_ascii=False,indent=2));print(json.dumps({k:v for k,v in report.items() if k!='template'},ensure_ascii=False,indent=2))
