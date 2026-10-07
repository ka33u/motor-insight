"""Reinspect an existing synthetic mapping after additive source contracts."""
import json
from pathlib import Path
def refresh(user,root):
 from django.test import RequestFactory
 from django.urls import resolve
 from django.core.files.uploadedfile import SimpleUploadedFile
 from app.models import ImportTemplate,ImportTemplateVersion,Record,ImportBatch
 file=Path(root)/'outputs/01a0f580-2480-7820-bc97-8ca293421c39/32_字段映射演练_模拟.xlsx'
 template=ImportTemplate.objects.get(code='TPL-SIM-DEPTS-001');old=ImportTemplateVersion.objects.get(template=template,number=5)
 assert (template.current_version,template.revision,old.state)==(5,10,'active')
 frozen={v.number:(v.content_hash,v.payload,v.state) for v in template.versions.all()};mapping=old.payload['mapping'];counts=(Record.objects.count(),ImportBatch.objects.count());factory=RequestFactory();reason='合成演练：新增资源与人员联立试排契约后，正常重新核对原字段映射；旧v1至v5载荷保留，不是实际业务审批。'
 def post(url,fields):
  request=factory.post(url,{'file':SimpleUploadedFile(file.name,file.read_bytes()),**fields});request.user=user;match=resolve(url);r=match.func(request,**match.kwargs)
  assert r.status_code==200,(url,r.status_code,r.content[:180]);return json.loads(r.content)
 review=post('/api/imports/mapping/preview',dict(mapping=json.dumps(mapping,ensure_ascii=False)))
 candidate=post('/api/import-templates',dict(mapping=json.dumps(mapping,ensure_ascii=False),inspection_receipt=review['receipt'],definition=json.dumps(dict(template_id=str(template.pk),revision=template.revision,reason=reason),ensure_ascii=False)))
 check=post('/api/import-templates/preview',dict(version_id=candidate['version_id'],purpose='activate'));assert check['template_can_apply']
 post('/api/import-templates/activate',dict(template_receipt=check['template_receipt'],definition=json.dumps(dict(revision=check['template']['revision'],reason=reason),ensure_ascii=False)))
 reuse=post('/api/import-templates/preview',dict(version_id=candidate['version_id'],purpose='use'));assert reuse['template_can_apply'] and reuse['rules_current']
 for v in template.versions.filter(number__lte=5):
  h,p,state=frozen[v.number];assert (v.content_hash,v.payload)==(h,p);assert v.state==('retired' if v.number==5 else state)
 template.refresh_from_db();assert (template.current_version,template.revision)==(6,12);assert counts==(Record.objects.count(),ImportBatch.objects.count())
 return dict(version=6,revision=12,old_payloads_preserved=True,normal_api=True,human_business_approval=False)
