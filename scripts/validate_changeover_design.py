"""Check the additive mixed-product BI definition against v0.30.0."""
import json
import subprocess
from collections import Counter
from copy import deepcopy
from pathlib import Path
from refine_bi_changeover import refine_changeover
ROOT = Path(__file__).resolve().parents[1]
old = json.loads(subprocess.check_output(['git', 'show', 'acdcab12fffdf206c71af61ab54062630b830997:data/bi_design.json'], cwd=ROOT))
current = json.loads((ROOT/'data/bi_design.json').read_text())
assert current == refine_changeover(deepcopy(old)) == refine_changeover(deepcopy(current))
items = [n for group in current['domains'] for n in group['items']]
assert len(items) == len({n['id'] for n in items}) == 382
assert Counter(n['implementation'] for n in items) == dict(模拟部分覆盖=121, 待建设=261)
assert current['metrics'] == old['metrics'] and len(current['page_blueprints']) == 17
for name in ('BI需求与呈现方案.html', 'BI完整382项需求清单.txt'):
    assert '三品种换型演练：' in (ROOT/'outputs'/name).read_text()
assert 'changeover-design' in (ROOT/'outputs/BI需求与呈现方案.html').read_text()
print('PASS: additive scenario definition; original metrics and coverage preserved; refinement idempotent')
