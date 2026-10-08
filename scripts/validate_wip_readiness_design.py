"""Current BI catalog must preserve published definitions and honest coverage."""
import json,subprocess
from collections import Counter
from copy import deepcopy
from pathlib import Path
from refine_bi_catalog import refine
from refine_bi_wip_readiness import refine_readiness
ROOT=Path(__file__).resolve().parents[1]
old=json.loads(subprocess.check_output(['git','show','c06ae295ff932c203e0e6035e7e88f6adb70478b:data/bi_design.json'],cwd=ROOT))
current=json.loads((ROOT/'data/bi_design.json').read_text())
assert current==refine_readiness(deepcopy(old))==refine_readiness(deepcopy(current))
assert json.dumps(current,ensure_ascii=False,indent=2)==json.dumps(refine(deepcopy(current)),ensure_ascii=False,indent=2)
items=[i for g in current['domains'] for i in g['items']]
assert len(items)==len({i['id'] for i in items})==382
assert Counter(i['implementation'] for i in items)==dict(模拟部分覆盖=122,待建设=260)
assert current['metrics']==old['metrics']
assert len([s for s in current['framework']['surfaces'] if s['href']=='#wip-readiness'])==1
for name in ('BI需求与呈现方案.html','BI完整382项需求清单.txt'):assert '在制重排准备：' in (ROOT/'outputs'/name).read_text()
print('PASS: WIP evidence scope truthful, definitions unchanged, full refinement byte-stable')
