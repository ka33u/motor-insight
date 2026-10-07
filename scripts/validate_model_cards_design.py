"""Verify this additive BI definition increment against its own parent."""
import copy,hashlib,json,re
from collections import Counter
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
from refine_bi_model_cards import remove_exact_cards,CONTRACT
from refine_bi_catalog import refine
def main():
 d=json.loads((ROOT/'data/bi_design.json').read_text());old=json.loads((ROOT/'data/model-cards-before/data/bi_design.json').read_text());assert remove_exact_cards(copy.deepcopy(d))==old and refine(copy.deepcopy(d))==d
 needs=[n for g in d['domains'] for n in g['items']];assert (len(d['domains']),len(needs),len(d['metrics']),len(d['page_blueprints']),len(d['framework']['method_workshop']['methods']))==(26,382,63,17,18)
 assert dict(Counter(n['implementation'] for n in needs))=={'模拟部分覆盖':114,'待建设':268};assert d['framework']['model_cards']==CONTRACT
 text=(ROOT/'outputs/BI完整382项需求清单.txt').read_text();html=(ROOT/'outputs/BI需求与呈现方案.html').read_text();guide=(ROOT/'outputs/BI定义与呈现_快速阅读版.txt').read_text()
 for n in needs:
  assert n['id']+' · '+n['need'] in text and 'data-need="'+n['id']+'"' in html,n['id']
  assert n['decision_spec']['implementation']==n['implementation'] and n['presentation_contract']['object_grain']==n['grain'] and n['presentation_contract']['data_gate']==n['prerequisite']
 assert '分析模型：业务口径、定义版本与当前结果' in html and '分析模型的业务口径与版本' in guide
 for m in d['metrics']:assert m['id']+' · '+m['name'] in text
 for p in d['page_blueprints']:assert p['id']+' · '+p['name'] in text
 assert not re.search(r'<script[^>]+src=|<link[^>]+href=',html);ids=re.findall(r'\bid="([^"]+)"',html);assert len(ids)==len(set(ids)) and set(re.findall(r'href="#([^"]+)"',html))<=set(ids)
 (ROOT/'data/model_cards_offline_script.mjs').write_text('\n'.join(re.findall(r'<script[^>]*>([\s\S]*?)</script>',html)))
 proof=dict(success=True,requirements=382,domains=26,metrics=63,pages=17,methods=18,partial=114,planned=268,old_catalog_exact_after_removing_declared_increment=True,canonical_refinement_idempotent=True,all_need_metric_page_text_covered=True,offline_no_external_assets=True,no_broken_anchors=True,sha256=hashlib.sha256((ROOT/'data/bi_design.json').read_bytes()).hexdigest(),browser_acceptance=False,mobile_acceptance=False)
 (ROOT/'data/model_cards_design_validation.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2)+'\n');print(json.dumps(proof,ensure_ascii=False))
if __name__=='__main__':main()
