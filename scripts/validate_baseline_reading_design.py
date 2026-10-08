"""Verify the scoped catalog reading change against v0.21.0; coverage is unchanged."""
import json, subprocess
from copy import deepcopy
from collections import Counter
from pathlib import Path
from refine_bi_baseline_reading import refine_baseline_reading
root = Path(__file__).resolve().parents[1]
old = json.loads(subprocess.check_output(['git','show','30371bf0b71f626ceef00eeffc831d083864771c:data/bi_design.json'],cwd=root))
new = json.loads((root/'data/bi_design.json').read_text())
assert new == refine_baseline_reading(deepcopy(old))
assert refine_baseline_reading(deepcopy(new)) == new
items = [n for g in new['domains'] for n in g['items']]
assert len(items) == len({n['id'] for n in items}) == 382
assert Counter(n['implementation'] for n in items) == dict(模拟部分覆盖=121,待建设=261)
assert old['metrics'] == new['metrics'] and len(new['page_blueprints']) == 17
for name in ('BI需求与呈现方案.html','BI完整382项需求清单.txt'):
    assert '基线联动阅读：' in (root/'outputs'/name).read_text()
print('PASS: 382 needs; three needs/three pages refined; 121 partial + 261 planned; metrics unchanged')
