"""Audit tracked public-release files without printing secret values."""
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATTERNS = {
    'private-key': rb'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----',
    'github-token': rb'\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,})\b',
    'aws-access-key': rb'\b(?:AKIA|ASIA)[A-Z0-9]{16}\b',
}

def main():
    result = subprocess.run(['git','ls-files','-z'], cwd=ROOT, check=True, capture_output=True)
    files = [Path(v.decode()) for v in result.stdout.split(b'\0') if v]
    problems = []
    for relative in files:
        path = ROOT / relative
        if path.is_symlink():
            problems.append((str(relative), 'symlink'))
            continue
        if any(p in {'.venv','node_modules','__pycache__'} for p in relative.parts):
            problems.append((str(relative), 'local-runtime'))
        if path.suffix in {'.sqlite3','.db','.log','.pid','.zip','.whl','.pyc'}:
            problems.append((str(relative), 'runtime-or-backup'))
        if relative.parts[0]=='data' and str(relative)!='data/bi_design.json':
            problems.append((str(relative), 'local-data'))
        if path.stat().st_size > 25*1024*1024:
            problems.append((str(relative), 'oversized-file'))
        for label, pattern in PATTERNS.items():
            if re.search(pattern, path.read_bytes()): problems.append((str(relative), label))
    if problems:
        for name, reason in problems: print(f'{reason}: {name}')
        raise SystemExit(1)
    print(f'Public repository audit passed: {len(files)} files; no runtime databases, backups or recognized credentials.')

if __name__=='__main__': main()
