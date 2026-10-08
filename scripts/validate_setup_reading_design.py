"""Validate additive BI setup definitions against v0.31.0."""
import json, subprocess
from collections import Counter
from copy import deepcopy
from pathlib import Path
from refine_bi_setup_reading import refine_setup_reading
ROOT = Path(__file__).resolve().parents[1]
old = json.loads(subprocess.check_output(['git','show','3f05192b602a37c9befef91a04afecaaf909d29f:data/bi_design.json'],cwd=ROOT))
current = json.loads((ROOT/'data/bi_design.json').read_text())
assert current == refine_setup_reading(deepcopy(old)) == refine_setup_reading(deepcopy(current))
items = [n for group in current['domains'] for n in group['items']]
assert len(items) == len({n['id'] for n in items}) == 382
assert Counter(n['implementation'] for n in items) == dict(模拟部分覆盖=121,待建设=261)
assert current['metrics'] == old['metrics'] and len(current['page_blueprints']) == 17
for name in ('BI需求与呈现方案.html','BI完整382项需求清单.txt'):
    assert '换型准备核对：' in (ROOT/'outputs'/name).read_text()
assert 'setup-reading-design' in (ROOT/'outputs/BI需求与呈现方案.html').read_text()
print('PASS: setup reading definitions added; original metrics and coverage preserved')
