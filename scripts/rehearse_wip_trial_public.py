"""Replay all publishable Excel inputs in a new directory; never copy a database."""
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--target', type=Path, required=True)
    args = parser.parse_args()
    target = args.target.resolve()
    if target.exists():
        parser.error('Target already exists; choose a new directory.')
    names = subprocess.check_output(['git', 'ls-files', '-z', '--cached', '--others', '--exclude-standard'], cwd=ROOT).split(b'\0')
    target.mkdir(parents=True)
    count = 0
    for value in names:
        if not value:
            continue
        relative = Path(value.decode())
        source = ROOT/relative
        assert source.is_file() and not source.is_symlink()
        assert source.suffix not in ('.sqlite3', '.db', '.log', '.zip', '.pyc')
        assert relative.parts[0] != 'data' or str(relative) == 'data/bi_design.json'
        destination = target/relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
        count += 1
    env = os.environ.copy()
    for key in ('PYTHONPATH', 'MOTOR_SQLITE_PATH', 'DJANGO_SETTINGS_MODULE'):
        env.pop(key, None)
    env['PYTHONNOUSERSITE'] = '1'
    subprocess.run([sys.executable, str(target/'scripts/bootstrap_demo.py')], cwd=target, env=env, check=True)
    subprocess.run([sys.executable, str(target/'scripts/validate_wip_trial.py')], cwd=target, env=env, check=True)
    replay = json.loads((target/'data/platform.bootstrap.json').read_text())
    assert replay['success'] and replay['workbooks'] == 47 and replay['records'] == 235614
    proof = json.loads((target/'data/wip_trial_validation.json').read_text())
    proof.update(public_files=count, fresh_xlsx_replay=True, effective_workbooks=47,
                 analysis_configuration_sha256=hashlib.sha256((target/'demo/analysis_configuration.json').read_bytes()).hexdigest())
    (ROOT/'data/wip_trial_replay.json').write_text(json.dumps(proof, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps(proof, ensure_ascii=False))


if __name__ == '__main__':
    main()
