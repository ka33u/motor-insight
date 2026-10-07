"""Embed the same metadata and component used online into the portable document."""
import json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]

def render_planning(d):
    sections='<section id="content-design"><div id="offline-content-design"></div></section><section id="method-workshop"><div id="offline-method-workshop"></div></section><section id="decision-design"><div id="offline-decision-design"></div></section><section id="review-design"><div id="offline-review-design"></div></section><section id="coverage"><h2>需求覆盖矩阵</h2><div id="offline-coverage"></div></section><section id="specification"><h2>分析定义设计</h2><div id="offline-specification"></div></section>'
    css=(ROOT/'static/catalog_planning.css').read_text()
    js=(ROOT/'static/catalog_planning.js').read_text().replace('export function ','function ')
    data=json.dumps(d,ensure_ascii=False,separators=(',',':')).replace('<','\\u003c').replace('\u2028','\\u2028').replace('\u2029','\\u2029')
    js+='\nconst designCatalog='+data+';\n'
    js+=r'''
const designEsc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const designTable=(headers,rows)=>'<div class="scroll"><table><thead><tr>'+headers.map(h=>'<th>'+designEsc(h)+'</th>').join('')+'</tr></thead><tbody>'+(rows.length?rows.map(row=>'<tr>'+row.map(c=>'<td>'+c+'</td>').join('')+'</tr>').join(''):'<tr><td colspan="'+headers.length+'">暂无符合条件的需求</td></tr>')+'</tbody></table></div>';
const designPanel=(title,note,body)=>'<div class="planning-panel"><h3>'+designEsc(title)+'</h3><p class="note">'+designEsc(note)+'</p>'+body+'</div>';
const controls='<select id="offline-domain" aria-label="需求领域"><option value="">所有领域</option>'+designCatalog.domains.map(d=>'<option value="'+designEsc(d.code)+'">'+designEsc(d.name)+'</option>').join('')+'</select><select id="offline-priority" aria-label="需求阶段"><option value="">所有阶段</option>'+[...new Set(designCatalog.domains.flatMap(d=>d.items.map(i=>i.priority)))].map(p=>'<option>'+designEsc(p)+'</option>').join('')+'</select><select id="offline-status" aria-label="需求实施状态"><option value="">所有状态</option><option>模拟部分覆盖</option><option>待建设</option></select><button id="offline-reset">清除筛选</button>';
document.querySelector('#requirements .filters').insertAdjacentHTML('beforeend',controls);
const requirements=designCatalog.domains.flatMap(dom=>dom.items.map(i=>({...i,code:dom.code,domain:dom.name})));
function filterDesignNeeds(){
 const q=document.querySelector('#search').value.trim().toLowerCase(),dom=document.querySelector('#offline-domain').value,phase=document.querySelector('#offline-priority').value,status=document.querySelector('#offline-status').value;
 let n=0;const byId=new Map(requirements.map(i=>[i.id,i]));
 document.querySelectorAll('.domain').forEach(section=>{let count=0;section.querySelectorAll('.need').forEach(el=>{const i=byId.get(el.dataset.need);el.hidden=!!((dom&&i.code!==dom)||(phase&&i.priority!==phase)||(status&&i.implementation!==status)||(q&&!JSON.stringify([i.domain,i.code,i]).toLowerCase().includes(q)));if(!el.hidden)count++});section.hidden=!count;if(q||dom||phase||status)section.open=true;n+=count});
 document.querySelector('#count').textContent=n+' / '+requirements.length+' 项';
}
document.querySelector('#search').addEventListener('input',filterDesignNeeds);
['#offline-domain','#offline-priority','#offline-status'].forEach(s=>document.querySelector(s).addEventListener('change',filterDesignNeeds));
document.querySelector('#offline-reset').onclick=()=>{['#search','#offline-domain','#offline-priority','#offline-status'].forEach(s=>document.querySelector(s).value='');filterDesignNeeds()};
const helpers={esc:designEsc,table:designTable,panel:designPanel,onOpenRequirements:filters=>{document.querySelector('#search').value=filters.q;document.querySelector('#offline-domain').value=filters.domain;document.querySelector('#offline-priority').value=filters.priority;document.querySelector('#offline-status').value=filters.status;filterDesignNeeds();location.hash='requirements';document.querySelector('#requirements').scrollIntoView()}};
renderPlanningCatalog(document.querySelector('#offline-coverage'),'coverage',designCatalog,helpers);
renderPlanningCatalog(document.querySelector('#offline-specification'),'specification',designCatalog,helpers);
renderBiContentPlanner(document.querySelector('#offline-content-design'),designCatalog,helpers);
renderBiMethodWorkshop(document.querySelector('#offline-method-workshop'),designCatalog,helpers);
renderBiDecisionDesign(document.querySelector('#offline-decision-design'),designCatalog,helpers);
renderBiReviewDesign(document.querySelector('#offline-review-design'),designCatalog,helpers);
filterDesignNeeds();
'''
    return sections,css,js
