"""Check additive BI coverage against the preceding published catalog."""
import json,subprocess
from collections import Counter
from copy import deepcopy
from pathlib import Path
from refine_bi_return_stock import refine_return_stock
from refine_bi_catalog import refine
ROOT=Path(__file__).resolve().parents[1]
old=json.loads(subprocess.check_output(['git','show','afef2a3faa76616cb48fe5ed896617236335c003:data/bi_design.json'],cwd=ROOT))
current=json.loads((ROOT/'data/bi_design.json').read_text())
assert current==refine_return_stock(deepcopy(old))==refine_return_stock(deepcopy(current))
assert json.dumps(current,ensure_ascii=False,indent=2)==json.dumps(refine(deepcopy(current)),ensure_ascii=False,indent=2)
items=[r for g in current['domains'] for r in g['items']]
assert len(items)==len({r['id'] for r in items})==382
assert Counter(r['implementation'] for r in items)==dict(模拟部分覆盖=122,待建设=260)
assert current['metrics']==old['metrics'] and len(current['page_blueprints'])==17
assert current['planning_summary']['implementation_counts']==dict(Counter(r['implementation'] for r in items))
assert len([r for r in current['framework']['surfaces'] if r['href']=='#supply?tab=returns'])==1
for name in ('BI需求与呈现方案.html','BI完整382项需求清单.txt'):
    assert '退料库存状态：' in (ROOT/'outputs'/name).read_text()
assert 'return-stock-design' in (ROOT/'outputs/BI需求与呈现方案.html').read_text()
print('PASS: return-stock evidence coverage added; published metric definitions preserved; full rebuild byte-stable')
