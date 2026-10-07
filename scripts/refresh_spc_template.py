"""Add a newly checked private template version using the same original example."""
import json
from pathlib import Path
REASON='合成演练：新增受控采样契约后重新核对原部门字段映射，保留v1/v2；不是实际业务审批'
def refresh(user,root):
    from django.test import RequestFactory
    from django.urls import resolve
    from django.core.files.uploadedfile import SimpleUploadedFile
    from app.models import ImportTemplate,ImportTemplateVersion,Record,ImportBatch
    file=Path(root)/'outputs/01a0f580-2480-7820-bc97-8ca293421c39/32_字段映射演练_模拟.xlsx'
    template=ImportTemplate.objects.get(code='TPL-SIM-DEPTS-001');old=ImportTemplateVersion.objects.get(template=template,number=2)
    assert template.revision==4 and template.current_version==2 and old.state=='active'
    frozen={v.number:(v.content_hash,v.payload,v.state) for v in template.versions.all()}
    mapping=old.payload['mapping'];counts=(Record.objects.count(),ImportBatch.objects.count());factory=RequestFactory()
    def post(url,fields):
        request=factory.post(url,{'file':SimpleUploadedFile(file.name,file.read_bytes()),**fields});request.user=user;match=resolve(url);response=match.func(request,**match.kwargs)
        assert response.status_code==200,(url,response.status_code,response.content[:300]);return json.loads(response.content)
    review=post('/api/imports/mapping/preview',dict(mapping=json.dumps(mapping,ensure_ascii=False)))
    candidate=post('/api/import-templates',dict(mapping=json.dumps(mapping,ensure_ascii=False),inspection_receipt=review['receipt'],definition=json.dumps(dict(template_id=str(template.pk),revision=template.revision,reason=REASON),ensure_ascii=False)))
    check=post('/api/import-templates/preview',dict(version_id=candidate['version_id'],purpose='activate'));assert check['template_can_apply']
    active=post('/api/import-templates/activate',dict(template_receipt=check['template_receipt'],definition=json.dumps(dict(revision=check['template']['revision'],reason=REASON),ensure_ascii=False)))
    reuse=post('/api/import-templates/preview',dict(version_id=candidate['version_id'],purpose='use'));assert reuse['template_can_apply'] and reuse['rules_current']
    for version in template.versions.filter(number__lte=2):
        h,payload,state=frozen[version.number];assert (version.content_hash,version.payload)==(h,payload)
        assert version.state==('retired' if version.number==2 else state)
    template.refresh_from_db();assert template.current_version==3 and template.revision==6
    assert counts==(Record.objects.count(),ImportBatch.objects.count())
    return dict(success=True,synthetic=True,human_business_approval=False,template_id=str(template.pk),version=3,revision=6,
                active=active,old_payloads_preserved=True,no_business_rows_or_batches_added=True,new_version_id=candidate['version_id'])
