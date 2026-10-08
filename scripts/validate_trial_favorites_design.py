"""Validate the new recipient view against v0.29.0, with no coverage inflation."""
import json, subprocess
from collections import Counter
from copy import deepcopy
from pathlib import Path
from refine_bi_trial_favorites import refine_trial_favorites
ROOT=Path(__file__).resolve().parents[1]
old=json.loads(subprocess.check_output(['git','show','23568679df72adbb63156a08eb4351452cd78d99:data/bi_design.json'],cwd=ROOT))
current=json.loads((ROOT/'data/bi_design.json').read_text())
assert current==refine_trial_favorites(deepcopy(old)) and refine_trial_favorites(deepcopy(current))==current
items=[n for group in current['domains'] for n in group['items']]
assert len(items)==len({n['id'] for n in items})==382
assert Counter(n['implementation'] for n in items)==dict(模拟部分覆盖=121,待建设=261)
assert current['metrics']==old['metrics'] and len(current['page_blueprints'])==17
for name in ('BI需求与呈现方案.html','BI完整382项需求清单.txt'):
    assert '方案收藏：' in (ROOT/'outputs'/name).read_text()
assert 'trial-favorites-design' in (ROOT/'outputs/BI需求与呈现方案.html').read_text()
print('PASS: original metrics and coverage unchanged; typed trial favorites added without changing existing metric definitions')
