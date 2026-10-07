"""Current catalog proof; old phase validators and checkpoints stay immutable."""
import copy,hashlib,json,re
from collections import Counter
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
from refine_bi_msa import remove_exact_msa,CONTRACT
from refine_bi_catalog import refine
def main():
 d=json.loads((ROOT/'data/bi_design.json').read_text());old=json.loads((ROOT/'data/msa-before/data/bi_design.json').read_text());assert remove_exact_msa(copy.deepcopy(d))==old;assert refine(copy.deepcopy(d))==d
 needs=[n for g in d['domains'] for n in g['items']];assert (len(d['domains']),len(needs),len(d['metrics']),len(d['page_blueprints']),len(d['framework']['method_workshop']['methods']))==(26,382,63,17,18)
 assert dict(Counter(n['implementation'] for n in needs))=={'模拟部分覆盖':114,'待建设':268};assert d['framework']['msa_trial']==CONTRACT
 text=(ROOT/'outputs/BI完整382项需求清单.txt').read_text();html=(ROOT/'outputs/BI需求与呈现方案.html').read_text()
 for n in needs:
  assert n['id']+' · '+n['need'] in text and 'data-need="'+n['id']+'"' in html,n['id']
  assert n['decision_spec']['implementation']==n['implementation']
  assert n['presentation_contract']['object_grain']==n['grain'] and n['presentation_contract']['data_gate']==n['prerequisite'],n['id']
 assert '测量系统：交叉采样与变异分解' in html and '930条重复观测' in html
 assert not re.search(r'<script[^>]+src=|<link[^>]+href=',html)
 ids=re.findall(r'\bid="([^"]+)"',html);assert len(ids)==len(set(ids));anchors=re.findall(r'href="#([^"]+)"',html);assert set(anchors)<=set(ids)
 script='\n'.join(re.findall(r'<script[^>]*>([\s\S]*?)</script>',html));(ROOT/'data/msa_offline_script.mjs').write_text(script)
 report=dict(success=True,requirements=382,domains=26,metrics=63,page_blueprints=17,methods=18,partial=114,planned=268,old_catalog_exact_after_removing_declared_msa=True,refinement_idempotent=True,offline_all_requirements=True,offline_no_external_assets=True,browser_acceptance=False,sha256=hashlib.sha256((ROOT/'data/bi_design.json').read_bytes()).hexdigest())
 (ROOT/'data/msa_design_validation.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n');print(json.dumps(report,ensure_ascii=False))
if __name__=='__main__':main()
