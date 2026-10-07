"""Recheck original mapping through the normal private template API."""
import json
from pathlib import Path
REASON='合成演练：新增测量试验契约后重新核对原部门字段映射，保留v1/v2/v3；不是实际业务审批'
def refresh(user,root):
 from django.test import RequestFactory
 from django.urls import resolve
 from django.core.files.uploadedfile import SimpleUploadedFile
 from app.models import ImportTemplate,ImportTemplateVersion,Record,ImportBatch
 file=Path(root)/'outputs/01a0f580-2480-7820-bc97-8ca293421c39/32_字段映射演练_模拟.xlsx'
 template=ImportTemplate.objects.get(code='TPL-SIM-DEPTS-001');old=ImportTemplateVersion.objects.get(template=template,number=3)
 assert template.revision==6 and template.current_version==3 and old.state=='active'
 frozen={v.number:(v.content_hash,v.payload,v.state) for v in template.versions.all()};mapping=old.payload['mapping'];counts=(Record.objects.count(),ImportBatch.objects.count());factory=RequestFactory()
 def post(url,fields):
  request=factory.post(url,{'file':SimpleUploadedFile(file.name,file.read_bytes()),**fields});request.user=user;match=resolve(url);r=match.func(request,**match.kwargs)
  assert r.status_code==200,(url,r.status_code,r.content[:300]);return json.loads(r.content)
 review=post('/api/imports/mapping/preview',dict(mapping=json.dumps(mapping,ensure_ascii=False)))
 candidate=post('/api/import-templates',dict(mapping=json.dumps(mapping,ensure_ascii=False),inspection_receipt=review['receipt'],definition=json.dumps(dict(template_id=str(template.pk),revision=template.revision,reason=REASON),ensure_ascii=False)))
 check=post('/api/import-templates/preview',dict(version_id=candidate['version_id'],purpose='activate'));assert check['template_can_apply']
 post('/api/import-templates/activate',dict(template_receipt=check['template_receipt'],definition=json.dumps(dict(revision=check['template']['revision'],reason=REASON),ensure_ascii=False)))
 reuse=post('/api/import-templates/preview',dict(version_id=candidate['version_id'],purpose='use'));assert reuse['template_can_apply'] and reuse['rules_current']
 for v in template.versions.filter(number__lte=3):
  h,p,state=frozen[v.number];assert (v.content_hash,v.payload)==(h,p);assert v.state==('retired' if v.number==3 else state)
 template.refresh_from_db();assert (template.current_version,template.revision)==(4,8);assert counts==(Record.objects.count(),ImportBatch.objects.count())
 return dict(version=4,revision=8,old_payloads_preserved=True,normal_api=True,human_business_approval=False)
