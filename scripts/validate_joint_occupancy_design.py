"""Validate the new recipient view against v0.28.0, with no coverage inflation."""
import json, subprocess
from collections import Counter
from copy import deepcopy
from pathlib import Path
from refine_bi_joint_occupancy import refine_occupancy
ROOT=Path(__file__).resolve().parents[1]
old=json.loads(subprocess.check_output(['git','show','bd48a1601400174bcb1e86ff0e5d297af6f8f104:data/bi_design.json'],cwd=ROOT))
current=json.loads((ROOT/'data/bi_design.json').read_text())
assert current==refine_occupancy(deepcopy(old)) and refine_occupancy(deepcopy(current))==current
items=[n for group in current['domains'] for n in group['items']]
assert len(items)==len({n['id'] for n in items})==382
assert Counter(n['implementation'] for n in items)==dict(模拟部分覆盖=121,待建设=261)
assert current['metrics']==old['metrics'] and len(current['page_blueprints'])==17
for name in ('BI需求与呈现方案.html','BI完整382项需求清单.txt'):
    assert '人机占用对照：' in (ROOT/'outputs'/name).read_text()
assert 'occupancy-design' in (ROOT/'outputs/BI需求与呈现方案.html').read_text()
print('PASS: original metrics and coverage unchanged; paired occupancy added to three existing needs and one page')
