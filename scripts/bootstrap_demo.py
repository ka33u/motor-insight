"""Initialize a NEW database by normally importing the published synthetic XLSX.

Never resets an existing database; never imports business facts from JSON.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', default=str(ROOT / 'data/platform.sqlite3'))
    args = parser.parse_args()
    target = Path(args.database).resolve()
    if target.exists():
        parser.error('数据库已存在；请选择新的路径，初始化不会清空或覆盖现有数据。')
    manifest = json.loads((ROOT/'demo/workbook_manifest.json').read_text())
    books = [(ROOT/'demo/workbooks'/row['filename'],row) for row in manifest['workbooks']]
    for book, row in books:
        if not book.is_file() or hashlib.sha256(book.read_bytes()).hexdigest()!=row['sha256']:
            parser.error('原始模拟Excel缺失或摘要不一致：'+book.name)
    target.parent.mkdir(parents=True, exist_ok=True)
    os.environ['MOTOR_SQLITE_PATH'] = str(target)
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
    import django
    django.setup()
    from django.core.management import call_command
    from app.ingestion import stage_file, commit_batch
    from app.models import Record
    from scripts.seed_xlsx import metadata
    call_command('migrate', interactive=False, verbosity=0)
    metadata()
    results = []
    for book, definition in books:
        batch, repeated = stage_file(book, mapping=definition['mapping'])
        if not repeated:
            batch = commit_batch(batch.pk)
        row = dict(filename=book.name, status=batch.status, summary=batch.summary)
        results.append(row)
        print(json.dumps(row, ensure_ascii=False), flush=True)
        invalid = list(batch.rows.filter(status='invalid'))
        superseded = []
        for source in invalid:
            old = source.normalized
            current = Record.objects.filter(dataset='work_orders',business_key=source.business_key).first()
            if (book.name=='04_计划生产_模拟.xlsx' and source.dataset=='work_orders'
                and source.business_key in manifest['legacy_plan_rows'] and current
                and current.source_row.batch.filename=='17_计划日期更正_模拟.xlsx'
                and all(i.get('code')=='WO_PLAN_ORDER' for i in source.issues)
                and {k:v for k,v in old.items() if k not in {'planned_start','planned_end'}}
                    == {k:v for k,v in current.values.items() if k not in {'planned_start','planned_end'}}):
                superseded.append(source.business_key)
        row['superseded_invalid_rows'] = superseded
        if len(invalid)!=len(superseded) or batch.summary.get('conflict') or batch.summary.get('unknown_sheets'):
            raise RuntimeError('导入中有待核对记录，保留现场并停止；不静默跳过或批准冲突。')
    configuration = ROOT / 'demo/analysis_configuration.json'
    if configuration.exists():
        call_command('loaddata', str(configuration), verbosity=0)
    proof = dict(success=True, workbooks=len(results), records=Record.objects.count(),
                 business_source='XLSX only', database=str(target), imports=results,
                 original_device_files='Not restored by XLSX import; archive service requires new upload.',
                 superseded_invalid_rows=sum(len(r['superseded_invalid_rows']) for r in results))
    target.with_suffix('.bootstrap.json').write_text(json.dumps(proof, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps({k:v for k,v in proof.items() if k!='imports'}, ensure_ascii=False))

if __name__ == '__main__':
    main()
