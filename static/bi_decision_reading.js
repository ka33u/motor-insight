// Presentation design only: no operational values or formulas are calculated here.
export function decisionReadingMarkup(d,{esc,table,panel}){
 const b=d.framework.decision_reading;if(!b)return '<p>阅读指南尚未生成。</p>';
 const cells=rows=>rows.map(r=>r.map(esc));
 const domainMap=new Map(d.domains.map(g=>[g.code,g]));
 const groups=b.lenses.map(g=>panel(g.name,g.question,g.domains.map(code=>{const v=domainMap.get(code);return `<p><a href="#catalog?tab=requirements&domain=${encodeURIComponent(code)}">${esc(v.name)} · ${v.items.length}项 ↗</a></p>`}).join(''))).join('');
 return panel('BI定义：从事实到决定',b.revision,`<p>${esc(b.definition)}</p><p>${esc(b.positioning)}</p><p class="source">${esc(b.scope)}</p>`)
  +`<div class="grid">${groups}</div>`
  +panel('定义对象与复用关系','需求、模型、指标、专题与页面分别管理',table(['定义对象','必须写清','示例'],cells(b.definition_fields)))
  +panel('一页的阅读顺序','范围 → 结果 → 解释 → 对象 → 证据 → 复查',table(['层次','展示内容','规则'],cells(b.page_layers)))
  +panel('岗位与终端','同一指标口径可以在多种入口使用',table(['入口','使用场景','呈现'],cells(b.formats)))
  +panel('小批量定制的比较条件','先核对条件，再展示差异',table(['条件','内容'],cells(b.factory_rules)))
  +panel('首期四页','先围绕交付、检测、单台履历与资料缺口',b.first_pages.map(id=>{const p=d.page_blueprints.find(p=>p.id===id);return `<p><a href="#catalog?tab=pages&page=${encodeURIComponent(id)}">${esc(id+' '+p.name)} ↗</a> · ${esc(p.question)}</p>`}).join(''))
  +panel('创新候选','满足资料条件后逐项实现',table(['设计','用途'],cells(b.innovations)));
}
