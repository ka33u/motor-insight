"""Exact H-27 documentation delta relative to the previous committed catalog."""
import json,subprocess
from collections import Counter
from pathlib import Path
from copy import deepcopy
from refine_bi_curing import refine_curing,CONTRACT,STATUS
ROOT=Path(__file__).resolve().parents[1]
old=json.loads(subprocess.check_output(['git','show','bb3de29e1e858adf174a74ce3e90b24c82c889d4:data/bi_design.json'],cwd=ROOT))
actual=json.loads((ROOT/'data/bi_design.json').read_text());expected=refine_curing(deepcopy(old));assert actual==expected
assert refine_curing(deepcopy(actual))==actual
rows=[n for g in actual['domains'] for n in g['items']];assert len(rows)==382 and len({n['id'] for n in rows})==382
assert Counter(n['implementation'] for n in rows)==dict(模拟部分覆盖=120,待建设=262)
assert actual['framework']['curing_curves']==CONTRACT
for name in ('BI需求与呈现方案.html','BI完整382项需求清单.txt'):
    text=(ROOT/'outputs'/name).read_text();assert '固化曲线演练' in text and '1229' in text
proof=dict(success=True,requirements=382,metrics=len(actual['metrics']),pages=len(actual['page_blueprints']),changed_requirement='H-27',other_definitions_preserved=True,browser_acceptance=False)
(ROOT/'data/curing_design.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2)+'\n');print(json.dumps(proof,ensure_ascii=False))
