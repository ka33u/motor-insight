"""Run each workbook in a separate process to bound spreadsheet runtime memory."""
import json, subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
NODE='/Users/zhangyu/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node'
d=json.loads((ROOT/'data/scenario.json').read_text())
for department in sorted({s['department'] for s in d['schemas'].values()}):
    print('BUILD',department,flush=True)
    scenario=ROOT/'data/ar_history_scenario.json' if department=='13_历史应收' else ROOT/'data/scenario.json'
    subprocess.run([NODE,'--max-old-space-size=8192',str(ROOT/'scripts/export_workbooks.mjs'),department,str(scenario)],cwd=ROOT,check=True)
