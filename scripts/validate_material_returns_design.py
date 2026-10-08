"""Check additive BI definitions without changing published KPI definitions."""
import json,subprocess
from collections import Counter
from copy import deepcopy
from pathlib import Path
from refine_bi_material_returns import refine_material_returns
from refine_bi_catalog import refine
ROOT=Path(__file__).resolve().parents[1]
old=json.loads(subprocess.check_output(['git','show','4837a413ffa568b734561a540de21d3c25cf26ac:data/bi_design.json'],cwd=ROOT))
current=json.loads((ROOT/'data/bi_design.json').read_text())
assert current==refine_material_returns(deepcopy(old))==refine_material_returns(deepcopy(current))
assert json.dumps(current,ensure_ascii=False,indent=2)==json.dumps(refine(deepcopy(current)),ensure_ascii=False,indent=2), 'Full BI rebuild changed serialized section order or content'
items=[n for g in current['domains'] for n in g['items']]
assert len(items)==len({n['id'] for n in items})==382
assert Counter(n['implementation'] for n in items)==dict(模拟部分覆盖=121,待建设=261)
assert current['metrics']==old['metrics'] and len(current['page_blueprints'])==17
for name in ('BI需求与呈现方案.html','BI完整382项需求清单.txt'):
    assert '生产领退料核对：' in (ROOT/'outputs'/name).read_text()
assert 'material-return-design' in (ROOT/'outputs/BI需求与呈现方案.html').read_text()
print('PASS: return reconciliation definitions added; published metric definitions and coverage preserved')
