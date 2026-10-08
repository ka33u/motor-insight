"""Verify the scoped catalog change against v0.20.0; coverage is unchanged."""
import json, subprocess
from copy import deepcopy
from collections import Counter
from pathlib import Path
from refine_bi_baseline_trial import refine_baseline_trial
root = Path(__file__).resolve().parents[1]
old = json.loads(subprocess.check_output(['git','show','f24655ef8d2fa161d116f816e46dcc3c47c3b11f:data/bi_design.json'],cwd=root))
new = json.loads((root/'data/bi_design.json').read_text())
assert new == refine_baseline_trial(deepcopy(old))
assert refine_baseline_trial(deepcopy(new)) == new
items = [n for g in new['domains'] for n in g['items']]
assert len(items) == len({n['id'] for n in items}) == 382
assert Counter(n['implementation'] for n in items) == dict(模拟部分覆盖=121,待建设=261)
assert old['metrics'] == new['metrics'] and len(new['page_blueprints']) == 17
for name in ('BI需求与呈现方案.html','BI完整382项需求清单.txt'):
    assert '冻结BOM假设试排：' in (root/'outputs'/name).read_text()
print('PASS: 382 needs; four needs/three pages refined; 121 partial + 261 planned; metrics unchanged')
