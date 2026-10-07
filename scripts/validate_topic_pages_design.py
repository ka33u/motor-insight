"""Verify current additive catalog, all delivered content and offline structure."""
import copy,hashlib,json,re
from collections import Counter
from html.parser import HTMLParser
from pathlib import Path
from refine_bi_catalog import refine
from refine_bi_topic_pages import remove_pages
ROOT=Path(__file__).resolve().parents[1]
class Inspect(HTMLParser):
 def __init__(self):super().__init__();self.ids=[];self.refs=[];self.assets=[];self.needids=[]
 def handle_starttag(self,tag,attrs):
  a=dict(attrs)
  if 'id' in a:self.ids.append(a['id'])
  if a.get('href','').startswith('#'):self.refs.append(a['href'][1:])
  if tag in ('script','link','img') and ('src' in a or 'href' in a):self.assets.append(a.get('src',a.get('href')))
  if a.get('data-need'):self.needids.append(a['data-need'])
def main():
 d=json.loads((ROOT/'data/bi_design.json').read_text());old=json.loads((ROOT/'data/topic-pages-before/data/bi_design.json').read_text());assert remove_pages(copy.deepcopy(d))==old;assert refine(copy.deepcopy(d))==d
 needs=[n for g in d['domains'] for n in g['items']];assert (len(d['domains']),len(needs),len(d['metrics']),len(d['page_blueprints']))==(26,382,63,17);assert Counter(n['implementation'] for n in needs)==Counter({'模拟部分覆盖':117,'待建设':265});assert d['planning_summary']['implementation_counts']==dict(Counter(n['implementation'] for n in needs));assert len(d['framework']['method_workshop']['methods'])==18
 ids={n['id'] for n in needs};assert len(ids)==382;pages={p['id'] for p in d['page_blueprints']};metrics={m['id'] for m in d['metrics']};methods={m['id'] for m in d['framework']['method_workshop']['methods']}
 for n in needs:
  assert all(n[k] for k in ('need','definition','view','action','source','grain','priority','owner','prerequisite','acceptance','gap'));assert set(n['page_ids'])<=pages;assert set(n['analysis_methods'])<=methods
  for key,field in [('object_grain','grain'),('implementation','implementation'),('action','action')]:assert n['decision_spec'][key]==n[field],n['id']
 for p in d['page_blueprints']:assert set(p['metrics'])<=metrics and set(p['analysis_methods'])<=methods
 html=(ROOT/'outputs/BI需求与呈现方案.html').read_text();v=Inspect();v.feed(html);assert len(v.ids)==len(set(v.ids));assert set(v.refs)<=set(v.ids);assert v.assets==[];assert len(v.needids)==382 and set(v.needids)==ids;assert 'topic-page-composition' in v.ids
 full=(ROOT/'outputs/BI完整382项需求清单.txt').read_text();business=(ROOT/'outputs/BI深化方案_业务阅读版_20261007.txt').read_text();quick=(ROOT/'outputs/BI定义与呈现_快速阅读版.txt').read_text()
 for n in needs:assert n['id']+' · '+n['need'] in full and n['id']+' · '+n['need'] in business
 for p in d['page_blueprints']:assert p['id']+' '+p['name'] in business and p['question'] in business
 for m in d['metrics']:assert m['id']+' '+m['name'] in business and m['formula'] in business
 assert '十三、按业务问题编排自己的工作页' in quick;assert '117项模拟部分覆盖、265项待建设' in business;assert (ROOT/'docs/BI深化方案_业务阅读版.txt').read_text()==business
 (ROOT/'data/topic_pages_offline_script.mjs').write_text('\n'.join(re.findall(r'<script[^>]*>([\s\S]*?)</script>',html)))
 proof=dict(success=True,domains=26,requirements=382,metric_proposals=63,page_blueprints=17,method_proposals=18,partial=117,planned=265,only_x23_promoted_to_partial=True,parent_catalog_exact_after_increment_removed=True,canonical_idempotent=True,legacy_summary_count_lag_corrected=True,all_requirements_in_business_and_full_text=True,all_metric_formulas_and_page_questions_in_business_text=True,offline_html_self_contained=True,no_broken_internal_links=True,quick_guide_chapters=13,catalog_sha256=hashlib.sha256((ROOT/'data/bi_design.json').read_bytes()).hexdigest(),browser_acceptance=False,mobile_acceptance=False)
 (ROOT/'data/topic_pages_design.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2)+'\n');print(json.dumps(proof))
if __name__=='__main__':main()
