"""Validate this catalog delta against v0.16.0 without rewriting old checkpoints."""
import copy
import json
import re
import subprocess
from collections import Counter
from pathlib import Path
from refine_bi_model_changes import refine_changes,CONTRACT
ROOT=Path(__file__).resolve().parents[1]

def main():
    before=json.loads(subprocess.check_output(['git','show','v0.16.0:data/bi_design.json'],cwd=ROOT))
    current=json.loads((ROOT/'data/bi_design.json').read_text())
    assert refine_changes(copy.deepcopy(before))==current
    assert refine_changes(copy.deepcopy(current))==current
    items=[n for g in current['domains'] for n in g['items']]
    assert len(items)==382 and len(current['domains'])==26 and len(current['page_blueprints'])==17
    assert current['metrics']==before['metrics'] and len(current['metrics'])==63
    assert current['page_blueprints']==before['page_blueprints']
    assert Counter(n['implementation'] for n in items)=={'模拟部分覆盖':119,'待建设':263}
    assert current['planning_summary']['implementation_counts']==dict(Counter(n['implementation'] for n in items))
    text=(ROOT/'outputs/BI完整382项需求清单.txt').read_text();html=(ROOT/'outputs/BI需求与呈现方案.html').read_text()
    for item in items:
        assert item['id'] in text and 'data-need="'+item['id']+'"' in html,item['id']
        assert item['decision_spec']['implementation']==item['implementation']
    assert CONTRACT['state'] in text and CONTRACT['state'] in html
    assert not re.findall(r'<(?:script|link)[^>]+(?:src|href)=["\']https?://',html)
    allowed={'X-08','X-40'}
    for old,new in zip([n for g in before['domains'] for n in g['items']],items):
        if new['id'] not in allowed:assert new==old,new['id']
    proof=dict(success=True,baseline='v0.16.0',requirements=382,only_changed_needs=sorted(allowed),partial=119,pending=263,metric_proposals_preserved=63,page_blueprints_preserved=17,
        exact_focused_delta=True,idempotent=True,offline_contains_all_requirements=True,browser_acceptance=False)
    (ROOT/'data/model_changes_design.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2)+'\n');print(json.dumps(proof,ensure_ascii=False))

if __name__=='__main__':main()
