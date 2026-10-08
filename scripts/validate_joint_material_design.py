"""Validate this increment against the preceding published catalog, without scope inflation."""
import json,subprocess
from pathlib import Path
from copy import deepcopy
from collections import Counter
from refine_bi_joint_material import refine_material
root=Path(__file__).resolve().parents[1]
old=json.loads(subprocess.check_output(['git','show','2e0137180d5ee38fcc7c432245740fe07a0de74d:data/bi_design.json'],cwd=root))
new=json.loads((root/'data/bi_design.json').read_text())
assert new==refine_material(deepcopy(old)) and refine_material(deepcopy(new))==new
items=[n for g in new['domains'] for n in g['items']]
assert len(items)==len({n['id'] for n in items})==382
assert Counter(n['implementation'] for n in items)==dict(模拟部分覆盖=121,待建设=261)
assert old['metrics']==new['metrics'] and len(new['page_blueprints'])==17
for name in ('BI需求与呈现方案.html','BI完整382项需求清单.txt'):assert '逐物料核对：' in (root/'outputs'/name).read_text()
assert 'joint-material-design' in (root/'outputs/BI需求与呈现方案.html').read_text()
print('PASS: two needs/one page/one existing entry; original metrics and coverage counts unchanged')
