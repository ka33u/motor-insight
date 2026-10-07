"""Copy publishable files and rebuild all business facts from Excel in a new root."""
import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = Path('/private/tmp/motorinsight-joint-public-20261007')


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
    db = TARGET/'data/platform.sqlite3'
    with sqlite3.connect(db) as c:
        rows = c.execute('SELECT dataset,business_key,record_hash FROM app_record ORDER BY dataset,business_key').fetchall()
        assert len(rows) == 225630
        digest = hashlib.sha256(json.dumps([dict(dataset=ds, business_key=key, record_hash=h) for ds, key, h in rows if not ds.startswith('joint_')], ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        assert digest == json.loads((ROOT/'data/joint-before/manifest.json').read_text())['record_digest']
        expected = json.loads((ROOT/'data/joint_schedule_scenario.json').read_text())['tables']
        for ds, values in expected.items():
            actual = [json.loads(row[0]) for row in c.execute('SELECT "values" FROM app_record WHERE dataset=? ORDER BY business_key', (ds,))]
            assert actual == sorted(values, key=lambda r: r['id']), ds
        assert c.execute('SELECT count(*) FROM app_analysismodel').fetchone()[0] == 52
        assert c.execute('SELECT count(*) FROM app_topic').fetchone()[0] == 21
        assert c.execute('SELECT count(*) FROM app_metricversion').fetchone()[0] == 11
        assert c.execute('PRAGMA integrity_check').fetchall() == [('ok',)]
    proof = dict(success=True, fresh_root=str(TARGET), workbooks=38, records=len(rows), old_records_exact=224061, new_records_exact=1569,
                 analysis_models=52, topics=21, metric_versions=11, business_inputs='XLSX through normal import only', browser_acceptance=False)
    (ROOT/'data/joint_schedule_bootstrap.json').write_text(json.dumps(proof, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps(proof, ensure_ascii=False))


if __name__ == '__main__':
    main()
