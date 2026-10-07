import copy,hashlib,json,re
from collections import Counter
from pathlib import Path
from refine_bi_catalog import refine
from refine_bi_finite_schedule import remove_schedule
ROOT=Path(__file__).resolve().parents[1]
def main():
 d=json.loads((ROOT/'data/bi_design.json').read_text());old=json.loads((ROOT/'data/finite-schedule-before/data/bi_design.json').read_text());assert remove_schedule(copy.deepcopy(d))==old;assert refine(copy.deepcopy(d))==d
 needs=[n for g in d['domains'] for n in g['items']];assert (len(d['domains']),len(needs),len(d['metrics']),len(d['page_blueprints']))==(26,382,63,17);assert Counter(n['implementation'] for n in needs)==Counter({'模拟部分覆盖':116,'待建设':266})
 html=(ROOT/'outputs/BI需求与呈现方案.html').read_text();text=(ROOT/'outputs/BI完整382项需求清单.txt').read_text();guide=(ROOT/'outputs/BI定义与呈现_快速阅读版.txt').read_text();assert '有限资源试排' in html;assert '十一、生产计划怎样做有限资源试排' in guide
 for n in needs:assert n['id']+' · '+n['need'] in text and 'data-need="'+n['id']+'"' in html
 ids=re.findall(r'\bid="([^"]+)"',html);assert len(ids)==len(set(ids));assert set(re.findall(r'href="#([^"]+)"',html))<=set(ids);assert not re.search(r'<script[^>]+src=|<link[^>]+href=',html)
 (ROOT/'data/finite_schedule_offline_script.mjs').write_text('\n'.join(re.findall(r'<script[^>]*>([\s\S]*?)</script>',html)))
 proof=dict(success=True,requirements=382,domains=26,metrics=63,pages=17,methods=18,partial=116,planned=266,parent_catalog_exact_after_increment_removed=True,canonical_idempotent=True,all_needs_in_text_and_html=True,offline_assets_self_contained=True,catalog_sha256=hashlib.sha256((ROOT/'data/bi_design.json').read_bytes()).hexdigest(),browser_acceptance=False,mobile_acceptance=False)
 (ROOT/'data/finite_schedule_design.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2)+'\n');print(json.dumps(proof))
if __name__=='__main__':main()
