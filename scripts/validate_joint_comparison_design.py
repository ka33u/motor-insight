"""The previous published catalog plus one explicit scheduling-comparison contract."""
import json,subprocess
from collections import Counter
from copy import deepcopy
from pathlib import Path
from refine_bi_joint_comparison import refine_comparison
ROOT=Path(__file__).resolve().parents[1]
old=json.loads(subprocess.check_output(['git','show','e272f0aed75a6a76b2732733cc05ba3d1bef9333:data/bi_design.json'],cwd=ROOT));current=json.loads((ROOT/'data/bi_design.json').read_text())
assert current==refine_comparison(deepcopy(old)) and refine_comparison(deepcopy(current))==current
items=[n for g in current['domains'] for n in g['items']]
assert len(items)==len({n['id'] for n in items})==382
assert Counter(n['implementation'] for n in items)==dict(模拟部分覆盖=121,待建设=261)
assert current['metrics']==old['metrics'] and len(current['page_blueprints'])==17
for filename in ('BI需求与呈现方案.html','BI完整382项需求清单.txt'):assert '联立派序对照：' in (ROOT/'outputs'/filename).read_text()
print(json.dumps(dict(success=True,requirements=382,coverage_unchanged=True,changed_needs=['F-03','F-06','F-07']),ensure_ascii=False))
