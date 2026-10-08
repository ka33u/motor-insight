"""Validate only this increment's BI scope against the preceding release."""
import json, subprocess
from pathlib import Path
from copy import deepcopy
from collections import Counter
from refine_bi_joint_blockers import refine_blockers
root=Path(__file__).resolve().parents[1]
old=json.loads(subprocess.check_output(['git','show','3c7da28495c6af4cdc0eb07604dd26b4d672430a:data/bi_design.json'],cwd=root))
new=json.loads((root/'data/bi_design.json').read_text())
assert new==refine_blockers(deepcopy(old)) and refine_blockers(deepcopy(new))==new
items=[n for g in new['domains'] for n in g['items']]
assert len(items)==len({n['id'] for n in items})==382
assert Counter(n['implementation'] for n in items)==dict(模拟部分覆盖=121,待建设=261)
assert old['metrics']==new['metrics'] and len(new['page_blueprints'])==17
for name in ('BI需求与呈现方案.html','BI完整382项需求清单.txt'):
    assert '首阻断关联：' in (root/'outputs'/name).read_text()
assert 'joint-blocker-design' in (root/'outputs/BI需求与呈现方案.html').read_text()
print('PASS: three needs/one page/one existing entry; metric definitions and coverage counts unchanged')
