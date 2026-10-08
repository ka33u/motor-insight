"""Verify the exact scoped BI contract change from the previous release."""
import json, subprocess
from collections import Counter
from copy import deepcopy
from pathlib import Path
from refine_bi_schedule_reading import refine_schedule_reading

root = Path(__file__).resolve().parents[1]
old = json.loads(subprocess.check_output(['git','show','2243f7b49aad4ad19c61d9e38341512f44f6e155:data/bi_design.json'],cwd=root))
new = json.loads((root/'data/bi_design.json').read_text())
assert new == refine_schedule_reading(deepcopy(old))
assert refine_schedule_reading(deepcopy(new)) == new
needs = [n for g in new['domains'] for n in g['items']]
assert len(needs) == len({n['id'] for n in needs}) == 382
assert Counter(n['implementation'] for n in needs) == dict(模拟部分覆盖=121,待建设=261)
assert new['metrics'] == old['metrics'] and len(new['page_blueprints']) == 17
for name in ('BI需求与呈现方案.html','BI完整382项需求清单.txt'):
    assert '试排依据阅读：' in (root/'outputs'/name).read_text()
print('PASS: 382 needs; five needs/two pages/four existing surfaces refined; metrics and coverage unchanged')
