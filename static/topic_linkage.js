export const linkLabel=(ctx,kind)=>ctx.cards.map(c=>c.link_contract?.[kind]?.label).find(Boolean)||kind;
export function linkText(ctx,conf){return (conf.links?.selections||[]).map(s=>`${linkLabel(ctx,s.kind)} = ${s.value}`).join(' · ')}
export function linkMarkup(ctx,conf,esc){
 const items=conf.links?.selections||[];
 return `<section class="panel topic-link-controls" aria-label="专题业务身份联动"><div class="toolbar"><b>点选联动</b><span class="muted">${items.length?'同时筛选当前和对照范围':'点击支持联动的图形，或选择卡片下方的业务身份'}</span>${items.length?'<button class="ghost" data-link-clear>清除全部联动</button>':''}</div>${items.length?`<div class="topic-link-chips">${items.map(s=>`<button class="ghost" data-link-remove="${esc(s.kind)}" aria-label="移除${esc(linkLabel(ctx,s.kind)+' '+s.value)}">${esc(linkLabel(ctx,s.kind))} = ${esc(s.value)} ×</button>`).join('')}</div>`:''}<details><summary>联动关系及未计算卡片</summary><p class="source">${esc(ctx.linkage.notice)} 最多同时保留3种身份；此处清除联动保留日期、产品族、客户及原模型局部条件。</p><div class="topic-link-contracts">${ctx.cards.map(c=>`<div><b>${esc(c.model?.name||'受限卡片')}</b><small>${!c.available?'未读取字段关系':items.length?items.map(s=>c.link_contract?.[s.kind]?esc(linkLabel(ctx,s.kind))+' → '+esc(c.link_contract[s.kind].field):esc(linkLabel(ctx,s.kind))+'：无直接字段，暂停').join('；'):Object.values(c.link_contract||{}).map(x=>esc(x.label)+' → '+esc(x.field)).join('；')||'没有已声明的直接身份关系'}</small></div>`).join('')}</div></details></section>`;
}
export function markRows(rows,choices){return rows.map(row=>{const i=choices.findIndex(c=>c.group===row.dimension);return i>=0?{...row,_topic_link_i:i}:row})}
export function linkPicker(card,esc){return card.link_choices?.length?`<div class="toolbar topic-link-picker"><label>业务身份联动<select class="topic-link-choice" aria-label="选择${esc(card.model.name)}的联动身份"><option value="">选择分组编码…</option>${card.link_choices.map((c,i)=>`<option value="${i}">${esc(c.label+' · '+c.group)}</option>`).join('')}</select></label><button class="topic-link-apply" disabled>筛选整个专题</button><small>同时应用两侧范围；最多3种身份</small></div>`:''}
export function bindMarks(root,choose){
 root.querySelectorAll('[data-topic-link-index]').forEach(mark=>{
  const invoke=()=>choose(Number(mark.dataset.topicLinkIndex),mark.dataset.topicLinkSide);
  mark.addEventListener('click',invoke);mark.addEventListener('keydown',e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();invoke()}});
 });
}
