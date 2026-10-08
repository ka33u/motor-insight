const states={scheduled:'按假设已排完',late:'已排完但晚交',blocked:'未排完'};
export function initialBatchMaterial(report){
 if(report?.state!=='ready')return -1;
 const changed=report.materials.findIndex(m=>m.more_jobs||m.less_jobs);
 if(changed>=0)return changed;
 const flow=report.materials.findIndex(m=>m.allocation_only_jobs);
 return flow>=0?flow:report.materials.length?0:-1;
}
export function batchMaterialRows(report,index,{changed=false,page=1,size=20}={}){
 const material=report?.state==='ready'?report.materials[index]:null;
 if(!material)return {material:null,rows:[],total:0,all:0,page,size};
 const all=report.rows.filter(r=>r.material_id===material.material_id&&r.unit===material.unit);
 const selected=all.filter(r=>!changed||r.quantity_change!=='same'||r.allocation_changed);
 return {material,rows:selected.slice((page-1)*size,page*size),total:selected.length,all:all.length,page,size};
}
export function batchMaterialChange(material,esc){
 if(!material)return '';
 const same=material.reserved_delta_qty==='0',recipients=material.more_jobs||material.less_jobs;
 const message=same&&recipients?'总预留量相同，获配批次有变化':same&&material.allocation_only_jobs?'获配量相同，预留流水有变化':'逐批次核对两列获配量';
 return `<p class="batch-material-change"><b>${message}</b> · 增加获配 ${material.more_jobs} 批 / 减少获配 ${material.less_jobs} 批 / 仅流水变化 ${material.allocation_only_jobs} 批<br>增加量 ${esc(material.increased_qty)} ${esc(material.unit)} − 减少量 ${esc(material.decreased_qty)} ${esc(material.unit)} = 总预留差值 ${esc(material.reserved_delta_qty)} ${esc(material.unit)}</p>`;
}
function amount(row,side,esc){
 const d=row[side],valid=[d.reserved_percent,d.unreserved_percent].every(n=>typeof n==='number'&&Number.isFinite(n)&&n>=0&&n<=100);
 const label=`已预留 ${d.reserved_qty} ${row.unit}，未预留 ${d.unreserved_qty} ${row.unit}`;
 return `<div class="batch-material-amount"><b>${esc(d.reserved_qty)}</b> / ${esc(d.unreserved_qty)} ${esc(row.unit)}</div>`+
 (valid?`<div class="batch-material-bar ${side}" role="img" aria-label="${esc(label)}"><span class="reserved" style="width:${d.reserved_percent}%"></span><span class="unreserved" style="width:${d.unreserved_percent}%"></span></div>`:'<small>数量比例不可显示</small>')+
 `<small class="block">整批需求已预留 ${d.reserved_demands} / ${d.demands} 行 · ${esc(states[d.job_state]||'状态待核对')}</small>`;
}
export function batchMaterialTable(rows,{esc,table}){
 return table(['批次 / 配置 / 台数','本物料所需量','应完成时间优先：已预留 / 未预留','优先级优先：已预留 / 未预留','获配变化 / 关联任务'],rows.map(r=>[
  `${esc(r.job_id)}<small class="block">${esc(r.product_id)} · ${r.qty} 台</small><small class="block">内部目标 ${esc(r.due.replace('T',' '))}</small>`,
  `${esc(r.required_qty)} ${esc(r.unit)}`,amount(r,'left',esc),amount(r,'right',esc),
  `${r.quantity_change==='more'?'增加':r.quantity_change==='less'?'减少':'数量不变'} · ${esc(r.reserved_delta_qty)} ${esc(r.unit)}<small class="block">${r.allocation_changed?'数量、供给或触发任务/时点有变化':'预留流水相同'}</small><button class="row-link" data-batch-material-job="${esc(r.job_id)}" data-batch-material-id="${esc(r.material_id)}" data-batch-material-unit="${esc(r.unit)}">核对 ${r.task_ids.length} 项关联任务 ↗</button>`]));
}
export function batchMaterialShell(report,index,{esc,panel}){
 if(!report||report.state!=='ready')return '<p class="empty">批次获料对照未计算；请重新读取完整两列。</p>';
 return panel('批次获料对照','',`<div class="filterbar"><label>物料与原单位<select id="batch-material-select">${report.materials.map((m,i)=>`<option value="${i}" ${i===index?'selected':''}>${esc(m.material_id+' · '+m.material_name+' / '+m.unit)}</option>`).join('')}</select></label><label><input type="checkbox" id="batch-material-changed">只看获配量或流水有变化</label></div><div id="batch-material-context"></div><div id="batch-material-rows"></div><div class="toolbar"><button id="batch-material-prev">上一页</button><span id="batch-material-page"></span><button id="batch-material-next">下一页</button></div><p class="source">${esc(report.notice)} 各物料的批次数有交叠，不能相加。这里仅筛选阅读明细，顶部整案汇总、共同来源及完整两列导出保持不变。</p>`);
}
