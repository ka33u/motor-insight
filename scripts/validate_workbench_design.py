"""Check the precise X-21 delta against the published v0.18 catalog."""
import json,subprocess
from collections import Counter
from copy import deepcopy
from pathlib import Path
from refine_bi_workbench import refine_workbench
ROOT=Path(__file__).resolve().parents[1]
old=json.loads(subprocess.check_output(['git','show','c3e5f70d470c2aeffa97f5a2ab4880b5e2ed6b29:data/bi_design.json'],cwd=ROOT))
current=json.loads((ROOT/'data/bi_design.json').read_text())
assert current==refine_workbench(deepcopy(old))
assert current==refine_workbench(deepcopy(current))
items=[n for g in current['domains'] for n in g['items']]
assert len(items)==len({n['id'] for n in items})==382
assert Counter(n['implementation'] for n in items)==dict(模拟部分覆盖=121,待建设=261)
assert current['metrics']==old['metrics'] and current['page_blueprints']==old['page_blueprints']
for name in ('BI需求与呈现方案.html','BI完整382项需求清单.txt'):
    text=(ROOT/'outputs'/name).read_text();assert '个人工作台：' in text and '最多100项' in text
print(json.dumps(dict(success=True,changed_requirement='X-21',requirements=382,other_definitions_preserved=True),ensure_ascii=False))
