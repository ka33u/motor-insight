"""Copy only publishable files and replay existing Excel into a NEW database."""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = Path('/private/tmp/motorinsight-first-piece-public-20261007')


def main():
    assert not TARGET.exists(), 'Do not overwrite an existing rehearsal.'
    names = subprocess.check_output(['git', 'ls-files', '-z', '--cached', '--others', '--exclude-standard'], cwd=ROOT).split(b'\0')
    TARGET.mkdir()
    for value in names:
        if not value:
            continue
        relative = Path(value.decode())
        source = ROOT/relative
        assert source.is_file() and not source.is_symlink()
        destination = TARGET/relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
    env = os.environ.copy()
    for key in ('PYTHONPATH', 'MOTOR_SQLITE_PATH', 'DJANGO_SETTINGS_MODULE'):
        env.pop(key, None)
    env['PYTHONNOUSERSITE'] = '1'
    subprocess.run([sys.executable, str(TARGET/'scripts/bootstrap_demo.py')], cwd=TARGET, env=env, check=True)
    os.environ['MOTOR_SQLITE_PATH'] = str(TARGET/'data/platform.sqlite3')
    os.environ['DJANGO_SETTINGS_MODULE'] = 'config.settings'
    sys.path.insert(0, str(TARGET))
    import django
    django.setup()
    from app.first_piece_data import load
    from app.finite_schedule import digest
    from app.models import Record, AnalysisModel, Topic, MetricVersion
    rows = list(Record.objects.order_by('dataset', 'business_key').values('dataset', 'business_key', 'record_hash'))
    expected = json.loads((ROOT/'data/first-piece-before/manifest.json').read_text())
    assert len(rows) == expected['record_count'] == 230509
    assert digest(rows) == expected['record_digest']
    d = load('LR-261001-001')
    assert d['result']['summary']['ready'] == 219
    assert d['targets']['summary'] == dict(rows=66, missing=66, candidates=0, attention=0)
    assert (AnalysisModel.objects.count(), Topic.objects.count(), MetricVersion.objects.count()) == (52, 21, 11)
    proof = dict(success=True, fresh_root=str(TARGET), workbooks=40, records=230509, all_business_facts_exact=True,
                 first_piece_summary=d['result']['summary'], analysis_models=52, topics=21, metric_versions=11,
                 browser_acceptance=False, business_inputs='Normal Excel stage and commit only')
    (ROOT/'data/first_piece_bootstrap.json').write_text(json.dumps(proof, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps(proof, ensure_ascii=False))


if __name__ == '__main__':
    main()
