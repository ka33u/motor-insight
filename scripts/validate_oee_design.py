"""Validate exhaustive requirement links, definitions and self-contained offline delivery."""
import copy,hashlib,json,re
from collections import Counter
from html.parser import HTMLParser
from pathlib import Path
from refine_bi_catalog import refine
from refine_bi_oee import refine_oee,remove_oee
ROOT=Path(__file__).resolve().parents[1]
class Inspect(HTMLParser):
 def __init__(self):super().__init__();self.ids=[];self.refs=[];self.assets=[];self.needs=[]
 def handle_starttag(self,tag,attrs):
  a=dict(attrs)
  if 'id' in a:self.ids.append(a['id'])
  if a.get('href','').startswith('#'):self.refs.append(a['href'][1:])
  if tag in ('script','link','img') and ('src' in a or 'href' in a):self.assets.append(a.get('src',a.get('href')))
  if a.get('data-need'):self.needs.append(a['data-need'])
def main():
 d=json.loads((ROOT/'data/bi_design.json').read_text());parent=json.loads((ROOT/'data/oee-before/data/bi_design.json').read_text());assert remove_oee(copy.deepcopy(d))==parent;assert refine_oee(copy.deepcopy(d))==d;assert refine(copy.deepcopy(d))==d
 needs=[n for g in d['domains'] for n in g['items']];counts=Counter(n['implementation'] for n in needs);assert (len(d['domains']),len(needs),len(d['metrics']),len(d['page_blueprints']),len(d['framework']['method_workshop']['methods']))==(26,382,63,17,18);assert counts==Counter({'模拟部分覆盖':118,'待建设':264});assert d['planning_summary']['implementation_counts']==dict(counts)
 assert {n['id'] for n in needs if n['implementation']!=next(x['implementation'] for g in parent['domains'] for x in g['items'] if x['id']==n['id'])}=={'O-05'}
 before_metrics={m['id']:m for m in parent['metrics']};assert {m['id'] for m in d['metrics'] if m!=before_metrics[m['id']]}=={'K18'}
 full=(ROOT/'outputs/BI完整382项需求清单.txt').read_text();business=(ROOT/'outputs/BI深化方案_业务阅读版_20261007.txt').read_text();quick=(ROOT/'outputs/BI定义与呈现_快速阅读版.txt').read_text();pages={p['id'] for p in d['page_blueprints']};metrics={m['id'] for m in d['metrics']};methods={m['id'] for m in d['framework']['method_workshop']['methods']}
 for n in needs:
  assert all(n[k] for k in ('definition','view','action','source','grain','owner','prerequisite','acceptance','gap'));assert n['id']+' · '+n['need'] in full and n['id']+' · '+n['need'] in business;assert set(n['page_ids'])<=pages and set(n['analysis_methods'])<=methods;assert n['decision_spec']['implementation']==n['implementation']
 for p in d['page_blueprints']:assert set(p['metrics'])<=metrics and set(p['analysis_methods'])<=methods;assert p['question'] in business
 for m in d['metrics']:assert m['formula'] in business and m['id']+' '+m['name'] in business
 assert '118项模拟部分覆盖、264项待建设' in business and '十四、按配置和独立资源位解释设备效率' in quick
 html=(ROOT/'outputs/BI需求与呈现方案.html').read_text();p=Inspect();p.feed(html);assert len(p.ids)==len(set(p.ids));assert set(p.refs)<=set(p.ids);assert not p.assets;assert len(p.needs)==382 and set(p.needs)=={n['id'] for n in needs};assert 'oee-design' in p.ids
 (ROOT/'data/oee_offline_script.mjs').write_text('\n'.join(re.findall(r'<script[^>]*>([\s\S]*?)</script>',html)))
 proof=dict(success=True,domains=26,requirements=382,metric_proposals=63,page_blueprints=17,methods=18,partial=118,planned=264,only_o05_promoted=True,only_unpublished_k18_proposal_clarified=True,parent_catalog_exact_after_increment_removed=True,canonical_refine_idempotent=True,all_requirements_metrics_and_pages_in_business_text=True,quick_guide_chapters=14,offline_self_contained=True,no_broken_links=True,browser_acceptance=False,mobile_acceptance=False,catalog_sha256=hashlib.sha256((ROOT/'data/bi_design.json').read_bytes()).hexdigest());(ROOT/'data/oee_design.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2)+'\n');print(json.dumps(proof,ensure_ascii=False))
if __name__=='__main__':main()
