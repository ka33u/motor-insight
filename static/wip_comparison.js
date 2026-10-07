export function createWipComparison({api,esc,num,tag,table,modal,toast,go,$,on,isCurrent,getModalRevision,query,getScope,openDetail,openEvidence,getToken}){
 let serial=0,lastPage=1;
 const n=(v,d=0)=>v==null?'待核查':num(v,d);
 const t=v=>esc(v.replace('T',' '));
 const safe=fn=>async()=>{try{await fn()}catch(e){toast(e.message)}};
 async function read(path){const i=++serial,route=getToken(),mr=getModalRevision(),d=await api(path);return i===serial&&isCurrent(route)&&mr===getModalRevision()&&$('#detail').open?d:null}
 const state=v=>v?`${esc(v.selected_id||'未选定')} · ${v.withdrawn?'撤销':v.applied?'应用':'待核查'}`:'未纳入业务或登记截止';
 const position=p=>`${esc(p.lot_id)} / ${esc(p.location)}：本份额 ${n(p.qty)} 件，整批 ${n(p.whole_lot_qty)} 件`;
 async function detail(key){
  modal('同批次前后构成 · '+key,'<p class="empty">正在读取两侧结果与依据…</p>');
  const d=await read('wip-flow/comparison/rows/'+encodeURIComponent(key)+'?'+query());if(!d)return;const r=d.row,a=r.before,b=r.after;
  const fields=[['核对状态',a.state_label,b.state_label],['有效基准件数',n(a.baseline_qty),n(b.baseline_qty)],['可核对在制件数',n(a.wip_qty),n(b.wip_qty)],['有效前缀耗用件数',n(a.prefix_consumed_qty),n(b.prefix_consumed_qty)],['有效前缀报废件数',n(a.prefix_scrap_qty),n(b.prefix_scrap_qty)],['基准后未核定件数',n(a.unknown_remainder),n(b.unknown_remainder)],['缺有效耗用SN数',n(a.missing_consumption_count),n(b.missing_consumption_count)],['位置与份额',a.positions.map(position).join('<br>')||'无可核对位置',b.positions.map(position).join('<br>')||'无可核对位置'],['核查原因',a.issues.map(esc).join('<br>')||'无',b.issues.map(esc).join('<br>')||'无']];
  $('#dialog-content').innerHTML=`<p>${esc(r.kind)} · ${esc(r.work_order_id)} · ${tag(r.change_type)}</p><p>业务截止 ${t(d.as_of)}；左登记截止 ${t(d.before_known_as_of)}；右登记截止 ${t(d.after_known_as_of)}。</p>${table(['构成','当时登记','右侧登记'],fields)}<p>同批次可比在制差：${r.wip_delta==null?'不可比较，两侧并非均可核对':n(r.wip_delta)+' 件'}。变化项：${r.differences.map(esc).join('、')||'结果未变'}。</p><h3>改变的流转依据</h3>${table(['系列','左选择 / 应用','右选择 / 应用'],r.version_changes.map(v=>[esc(v.series),state(v.before),state(v.after)]))}<h3>基准依据</h3><p>左：${r.opening_before.map(esc).join('、')||'缺有效基准'}<br>右：${r.opening_after.map(esc).join('、')||'缺有效基准'}</p><p class="source">${esc(d.note)}</p><div class="toolbar"><button id="wc-left">进入当时登记视角</button><button id="wc-right">查看右侧完整履历</button><button id="wc-source">查看Excel来源</button><button id="wc-back">返回变化清单</button></div>`;
  on('#wc-left','click',()=>go('wip-flow',{...Object.fromEntries(getScope()),known_as_of:d.before_known_as_of,stage:'all',q:key,page:1}));
  on('#wc-right','click',safe(()=>openDetail(key)));on('#wc-source','click',safe(()=>openEvidence(key)));on('#wc-back','click',safe(()=>show(lastPage)));
 }
 async function show(page=1){
  modal('在制历史重述 · 登记截止对照','<p class="empty">正在固定原批次并核对两侧…</p>');
  const d=await read('wip-flow/comparison?'+query({page}));if(!d)return;lastPage=page;const s=d.summary;
  const groups=s.groups.map(g=>[esc(g.kind),n(g.objects),n(g.both_verified),n(g.before_comparable_wip)+' → '+n(g.after_comparable_wip),n(g.comparable_delta),n(g.before_unknown)+' → '+n(g.after_unknown),n(g.gained_verification)+' / '+n(g.lost_verification)]);
  $('#dialog-content').innerHTML=`<p>同一业务截止 ${t(d.as_of)}；左采用截至 ${t(d.before_known_as_of)} 的登记，右采用截至 ${t(d.after_known_as_of)} 的登记。</p><div class="wip-detail-kpis">${[['固定原批次',s.objects],['结果改变',s.outcome_changed],['仅依据改变',s.evidence_only],['未改变',s.unchanged]].map(([k,v])=>`<div><small>${k}</small><strong>${n(v)}</strong></div>`).join('')}</div>${table(['分支','本范围原批次','两侧均可核对','同批次在制 左→右','可比差件数','未知原批次 左→右','恢复 / 失去可核对'],groups)}<p class="source">${esc(d.note)}</p><p>清单列结果或依据改变的对象；CSV包含当前筛选及右侧状态命中的全部 ${n(s.objects)} 个原批次。</p>${table(['原批次 / 工单','变化 / 分支','核对状态 左→右','在制件数 左→右','同批次差 / 变化项'],d.rows.map(r=>[`<button class="row-link" data-wc-key="${esc(r.id)}">${esc(r.id)}</button><br>${esc(r.work_order_id)}`,tag(r.change_type)+' / '+esc(r.kind),esc(r.before.state_label)+' → '+esc(r.after.state_label),n(r.before.wip_qty)+' → '+n(r.after.wip_qty),n(r.wip_delta)+'<br>'+r.differences.map(esc).join('、')]))}<div class="pagination"><span>${n(d.total)}条变化 · 第${page}页</span><button id="wc-prev" ${page<=1?'disabled':''}>上一页</button><button id="wc-next" ${page*d.size>=d.total?'disabled':''}>下一页</button><a href="/api/wip-flow/comparison/export?${query()}">导出全部同范围对照 ↓</a></div>`;
  on('#wc-prev','click',safe(()=>show(page-1)));on('#wc-next','click',safe(()=>show(page+1)));document.querySelectorAll('[data-wc-key]').forEach(b=>b.onclick=safe(()=>detail(b.dataset.wcKey)));
 }
 return {show};
}
