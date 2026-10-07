"""Replace named generator-owned departments through XLSX with recovery history."""
import os,sys,json,sqlite3
from pathlib import Path
from datetime import datetime
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings')
import django
django.setup()
from django.db import transaction
from app.models import Record,ImportBatch,AuditEvent
from app.schema import SCHEMAS
from app.ingestion import stage_file,commit_batch

def replace(departments):
    allowed={s['department'] for s in SCHEMAS.values()}
    if not departments or not set(departments).issubset(allowed):raise ValueError('必须明确指定已知的模拟数据部门')
    backup_dir=ROOT/'data/backups';backup_dir.mkdir(exist_ok=True);backup=backup_dir/('before-demo-reimport-'+datetime.now().strftime('%Y%m%d-%H%M%S')+'.sqlite3')
    with sqlite3.connect(ROOT/'data/platform.sqlite3') as source,sqlite3.connect(backup) as target:source.backup(target)
    result=[]
    with transaction.atomic():
        for department in departments:
            keys=[k for k,s in SCHEMAS.items() if s['department']==department];filename=department+'_模拟.xlsx'
            unexpected=Record.objects.filter(dataset__in=keys).exclude(source_row__batch__filename=filename)
            if unexpected.exists():raise ValueError(f'{department}存在其他来源记录，拒绝覆盖；请在独立演示库重建')
            Record.objects.filter(dataset__in=keys).delete()
            ImportBatch.objects.filter(filename=filename,status__in=['committed','partial']).update(status='superseded')
            path=next((ROOT/'outputs').glob('*/'+filename));batch,repeated=stage_file(path)
            if repeated:raise RuntimeError('重建意外复用已提交批次')
            batch=commit_batch(batch.pk)
            if batch.status!='committed':raise RuntimeError(f'{filename}校验未通过：{batch.summary}')
            result.append({'file':filename,'batch':str(batch.pk),'summary':batch.summary});print(json.dumps(result[-1],ensure_ascii=False),flush=True)
        AuditEvent.objects.create(action='demo.rebuild',object_type='Dataset',object_id=','.join(departments),detail={'backup':str(backup),'business_source':'regenerated XLSX only','prior_batches':'retained as superseded','batches':result})
    return result

if __name__=='__main__':
    replace(sys.argv[1:])
    expected=json.loads((ROOT/'data/scenario.json').read_text())['tables'];expected={k:{r['id']:r for r in rows} for k,rows in expected.items()};diff=[]
    for r in Record.objects.iterator():
        if r.business_key not in expected.get(r.dataset,{}):diff.append([r.dataset,r.business_key,'not in generator']);continue
        for field,value in r.values.items():
            if value!=expected[r.dataset][r.business_key][field]:diff.append([r.dataset,r.business_key,field])
    counts={k:Record.objects.filter(dataset=k).count() for k in expected}
    assert all(counts[k]==len(expected[k]) for k in expected),counts
    assert not diff,diff[:10]
    evidence={'records':Record.objects.count(),'datasets':len(expected),'field_differences':0,'counts':counts,'source':'actual XLSX round trip; no JSON insertion'}
    (ROOT/'data/excel_roundtrip_validation.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2));print('ROUNDTRIP',evidence['records'],'records, zero differences')
