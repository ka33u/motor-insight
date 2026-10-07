export function createMaterialLots({load,endpoint,query,esc,num,panel,table,link,stateTag,amount,$,$$,on,navigate,bind}){
 const policies={ledger:'账面可用余额 · 不指定批次',fifo:'日期核对 · FIFO先入先用',fefo:'日期核对 · FEFO先到期先用'};
 const day=v=>v?esc(v):'未核对';
 const batchText=x=>x.lot_allocations?.length?x.lot_allocations.map(p=>`<div class="prep-lot-copy"><b>${esc(p.lot)}</b> · ${esc(p.location)}<br>本单 ${amount(p.qty,x.unit)} · 池 ${amount(p.before)} → ${amount(p.after)}<br>有效截至 ${p.expires?esc(p.expires):'不适用'} · 同物料位次 ${p.reference_rank}<br>日期 ${esc(p.date_profile_id)} / 规则 ${esc(p.policy_id)}</div>`).join(''):'<span class="muted">本单没有批次占用</span>';
 function order(r,d){
  if(d.filters.lot_policy==='ledger')return '';
  const desktop=table(['物料 / 有效期核对至','轮到本单池 / 该日候选量','本单拟配批次'],r.items.map(x=>[`${esc(x.material_id)} · ${esc(x.unit)}<br>${day(x.use_day)}`,`${amount(x.before_pool)} / ${amount(x.date_available_pool)}<br><small>该日有效期排除 ${amount(x.date_excluded_at_use,x.unit)}</small>`,batchText(x)]));
  const mobile=r.items.map(x=>`<article class="prep-lot-card"><h3>${esc(x.material_id)} · ${esc(x.material)}</h3><p>有效期核对至 ${day(x.use_day)}<br>轮到本单池 ${amount(x.before_pool,x.unit)}<br>该日候选量 ${amount(x.date_available_pool,x.unit)} · 该日有效期排除 ${amount(x.date_excluded_at_use,x.unit)}</p><b>本单拟配批次</b>${batchText(x)}</article>`).join('');
  return panel('工单使用日期与批次计划',d.lot_policy_label+'；核对至库存截止日与计划开工日中较晚一天；仅整单可覆盖后才占用本次模拟池。',`<div class="prep-lot-desktop">${desktop}</div><div class="prep-lot-mobile">${mobile}</div>`)+`<p class="source">${esc(d.lot_note)}</p>`;
 }
 function material(d){
  if(d.filters.lot_policy==='ledger')return '';
  const r=d.row;
  return panel('日期候选与批次池',d.lot_policy_label+'；原账面量、日期候选量与本次模拟池分开核对；剩余量为完整队列试配后的值。',`<p>日期候选 ${amount(r.date_candidate_qty,r.unit)} · 可用状态库存中未纳入 ${amount(r.date_excluded_usable_qty,r.unit)}</p>${table(['批次 / 库位','纳入理由 / 日期','原账面量','模拟保留缓冲','池起点 → 队列后剩余'],d.date_lots.map(l=>[`${esc(l.lot)}<br>${esc(l.location)}`,`${esc(l.selection_reason)}<br>${esc(l.expiry_state)} · ${l.expires?esc(l.expires):l.expiry_state==='不适用'?'不适用':'未核对有效截至'}<br>${l.reference_rank==null?'未纳入参考':'同物料位次 '+l.reference_rank}`,amount(l.balance_qty,l.unit),amount(l.simulated_buffer,l.unit),`${amount(l.initial_pool)} → ${amount(l.remaining_pool)} ${esc(l.unit)}`]))}<h3>各工单使用日期门槛</h3>${table(['位置 / 工单','核对至','该日可用候选 / 排除量','本单模拟用量','整单结论'],d.work_orders.map(w=>[`${w.sequence} · ${link('orders',w.id)}`,day(w.item.use_day),`${amount(w.item.date_available_pool)} / ${amount(w.item.date_excluded_at_use)} ${esc(r.unit)}`,amount(w.item.simulated_allocated,r.unit),stateTag(w.state)]))}<p><a data-prep-nav href="#inventory-age?material_id=${encodeURIComponent(r.id)}">核查物料日期版本与有效期 ↗</a></p><p class="source">${esc(d.lot_note)}</p>`);
 }
 async function compare(){await load('批次日期策略对照',endpoint('/lot-compare'),d=>{
  $('#dialog-content').innerHTML=`<p class="source">${esc(d.note)}</p>${table(['批次策略','整单可覆盖','候选库存不足','资料待核对','覆盖工单计划台数'],d.results.map(r=>[esc(r.label)+(r.key===d.primary_policy?' · 当前':''),num(r.summary.covered),num(r.summary.short),num(r.summary.attention),num(r.summary.covered_planned_qty)]))}${d.results.map(r=>`<section class="prep-lot-comparison"><h3>${esc(r.label)}</h3><p class="source">相对当前策略 ${r.changes.length}张工单结论变化；点击工单查看当前策略依据。</p>${table(['工单 / 配置','计划台数','当前结论','本策略结论'],r.changes.map(w=>[link('orders',w.id)+`<br>${esc(w.product_id)}`,num(w.planned_qty),stateTag(w.before),stateTag(w.after)]))}${r.key!==d.primary_policy?`<button data-lot-apply="${r.key}">按${esc(r.label)}重新运行</button>`:''}</section>`).join('')}<p class="source">${esc(d.boundary)}</p>`;
  bind($('#dialog-content'));$$('[data-lot-apply]').forEach(b=>b.onclick=()=>{$('#detail').close();navigate({lot_policy:b.dataset.lotApply,page:1})});
 });}
 function mount(d){
  const f=d.filters,dated=f.lot_policy!=='ledger';
  $('#prep-scope select[name="stock_policy"]').closest('label').insertAdjacentHTML('afterend',`<label>批次日期策略<select name="lot_policy">${Object.entries(policies).map(([key,label])=>`<option value="${key}" ${f.lot_policy===key?'selected':''}>${esc(label)}</option>`).join('')}</select></label>`);
  $('#prep-compare').insertAdjacentHTML('afterend','<button id="prep-lot-compare">对照批次日期策略</button>');on('#prep-lot-compare','click',compare);
  const content=dated?panel('日期候选与共享池数量','只汇总本队列所需物料的已知数量；各单位分别核对，未核对物料单列。',table(['单位 / 已知与未知物料','账面可用状态量','日期候选 / 未纳入','扣缓冲后池起点','整单占用 / 剩余池'],d.lot_summary.map(r=>[`${esc(r.unit)} · ${r.known_materials}已知 / ${r.unknown_materials}未知`,amount(r.usable_state_qty),`${amount(r.date_candidate_qty)} / ${amount(r.date_excluded_usable_qty)}`,amount(r.initial_pool),`${amount(r.simulated_allocated)} / ${amount(r.remaining_pool)}`]))+`<p class="source">${esc(d.lot_note)}</p>`):'<p class="source prep-date-note">当前账面策略按可用状态余额计算，未核对批次日期或指定拟用批次。</p>';
  $('#main .quality-kpis').insertAdjacentHTML('beforebegin',content);
  if(dated)$('#prep-list').previousElementSibling.insertAdjacentHTML('beforeend',`<a href="/api/material-lots/export?${esc(query())}" download>导出当前关联批次计划 ↓</a>`);
 }
 return {order,material,mount};
}
