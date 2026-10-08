"""Validate the scoped candidate-reading addition to the published BI catalog."""
import json,subprocess
from pathlib import Path
from copy import deepcopy
from collections import Counter
from refine_bi_joint_candidates import refine_candidates
root=Path(__file__).resolve().parents[1]
old=json.loads(subprocess.check_output(['git','show','4fc039a1bde5bba48f0ffbbc2e4b182e77dd405d:data/bi_design.json'],cwd=root))
new=json.loads((root/'data/bi_design.json').read_text())
assert new==refine_candidates(deepcopy(old)) and refine_candidates(deepcopy(new))==new
items=[n for g in new['domains'] for n in g['items']]
assert len(items)==len({n['id'] for n in items})==382
assert Counter(n['implementation'] for n in items)==dict(模拟部分覆盖=121,待建设=261)
assert old['metrics']==new['metrics'] and len(new['page_blueprints'])==17
for name in ('BI需求与呈现方案.html','BI完整382项需求清单.txt'):
    assert '候选人机依据：' in (root/'outputs'/name).read_text()
print('PASS: four needs/two pages/one existing entry; all metric definitions and coverage counts unchanged')
