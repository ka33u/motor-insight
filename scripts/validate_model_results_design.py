import copy,hashlib,json,re
from pathlib import Path
from collections import Counter
from refine_bi_model_results import remove_exact_results
from refine_bi_catalog import refine
ROOT=Path(__file__).resolve().parents[1]
def main():
 d=json.loads((ROOT/'data/bi_design.json').read_text());old=json.loads((ROOT/'data/model-results-before/data/bi_design.json').read_text());assert remove_exact_results(copy.deepcopy(d))==old and refine(copy.deepcopy(d))==d
 needs=[n for g in d['domains'] for n in g['items']];assert (len(d['domains']),len(needs),len(d['metrics']),len(d['page_blueprints']))==(26,382,63,17) and Counter(n['implementation'] for n in needs)==Counter({'模拟部分覆盖':114,'待建设':268})
 html=(ROOT/'outputs/BI需求与呈现方案.html').read_text();text=(ROOT/'outputs/BI完整382项需求清单.txt').read_text();guide=(ROOT/'outputs/BI定义与呈现_快速阅读版.txt').read_text();assert '个人模型当前结果阅读' in html and '九、从模型口径直接读当前结果' in guide
 for n in needs:assert n['id']+' · '+n['need'] in text and 'data-need="'+n['id']+'"' in html
 ids=re.findall(r'\bid="([^"]+)"',html);assert len(ids)==len(set(ids)) and set(re.findall(r'href="#([^"]+)"',html))<=set(ids);assert not re.search(r'<script[^>]+src=|<link[^>]+href=',html)
 (ROOT/'data/model_results_offline_script.mjs').write_text('\n'.join(re.findall(r'<script[^>]*>([\s\S]*?)</script>',html)))
 proof=dict(success=True,requirements=382,domains=26,metrics=63,pages=17,methods=18,partial=114,planned=268,old_catalog_exact_after_removing_increment=True,canonical_refinement_idempotent=True,all_requirements_in_offline_text=True,offline_no_external_assets_or_broken_anchors=True,catalog_sha256=hashlib.sha256((ROOT/'data/bi_design.json').read_bytes()).hexdigest(),browser_acceptance=False,mobile_acceptance=False)
 (ROOT/'data/model_results_design_validation.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2)+'\n');print(json.dumps(proof,ensure_ascii=False))
if __name__=='__main__':main()
