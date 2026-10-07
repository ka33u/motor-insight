"""Re-review the existing synthetic example through native template APIs."""
import json
from pathlib import Path
REASON='合成模拟演练：新增设备清单契约后重新核对原采购销售仓储表头，保留v1历史；不是实际部门审批'
def refresh(user,root):
 from django.test import RequestFactory
 from django.urls import resolve
 from django.core.files.uploadedfile import SimpleUploadedFile
 from app.models import ImportTemplate,ImportTemplateVersion,Record,ImportBatch
 file=Path(root)/'outputs/01a0f580-2480-7820-bc97-8ca293421c39/32_字段映射演练_模拟.xlsx';template=ImportTemplate.objects.get(code='TPL-SIM-DEPTS-001');old=ImportTemplateVersion.objects.get(template=template,number=1)
 assert template.revision==2 and template.current_version==1 and old.state=='active'
 original_hash=old.content_hash;original_payload=old.payload;mapping=old.payload['mapping'];counts=(Record.objects.count(),ImportBatch.objects.count());factory=RequestFactory()
 def post(url,fields):
  request=factory.post(url,{'file':SimpleUploadedFile(file.name,file.read_bytes()),**fields});request.user=user;match=resolve(url);response=match.func(request,**match.kwargs);assert response.status_code==200,(url,response.status_code,response.content[:300]);return json.loads(response.content)
 review=post('/api/imports/mapping/preview',dict(mapping=json.dumps(mapping,ensure_ascii=False)))
 new=post('/api/import-templates',dict(mapping=json.dumps(mapping,ensure_ascii=False),inspection_receipt=review['receipt'],definition=json.dumps(dict(template_id=str(template.pk),revision=template.revision,reason=REASON),ensure_ascii=False)))
 check=post('/api/import-templates/preview',dict(version_id=new['version_id'],purpose='activate'));assert check['template_can_apply']
 active=post('/api/import-templates/activate',dict(template_receipt=check['template_receipt'],definition=json.dumps(dict(revision=check['template']['revision'],reason=REASON),ensure_ascii=False)))
 new_version=ImportTemplateVersion.objects.get(pk=new['version_id']);reuse=post('/api/import-templates/preview',dict(version_id=new['version_id'],purpose='use'));assert reuse['template_can_apply'] and reuse['rules_current']
 old.refresh_from_db();assert old.content_hash==original_hash and old.payload==original_payload and old.state=='retired';assert (Record.objects.count(),ImportBatch.objects.count())==counts
 return dict(synthetic=True,human_business_approval=False,local_api_views=True,reason=REASON,template=active,new_version_payload=new_version.payload,old_content_hash=original_hash,new_version_id=new_version.pk,old_version_id=old.pk,fresh_example_can_use=True,no_business_rows_or_import_batches_added=True)
