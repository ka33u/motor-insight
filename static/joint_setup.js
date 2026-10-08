const names={due:'应完成时间优先',priority:'批次优先级优先'},kinds={initial:'首次上机',change:'跨族换型',same:'同族延续'};
const n=v=>v==null?'不可比较':Number(v).toLocaleString('zh-CN',{maximumFractionDigits:2});
const time=v=>v?v.replace('T',' '):'未全部排入';
const signed=v=>v==null?'不可比较':(v>0?'+':'')+n(v);
export function setupSummary(report,{esc,panel,table}){
 if(report?.state!=='ready')return panel('准备与交期取舍','','<p class="empty">原试排或换型依据不可用，准备与交期差值未计算。</p>');
 const {columns,summary}=report,max=summary.chart_max_minutes;
 const bars=Object.entries(names).map(([policy,name])=>{const row=columns[policy],part=key=>max?row[key]/max*100:0;
  return `<div class="setup-bar-row"><b>${name}</b><div><div class="setup-bar" role="img" aria-label="${esc(`${name}，首次上机准备${n(row.initial_minutes)}分钟，跨族准备${n(row.change_minutes)}分钟，总准备${n(row.setup_minutes)}分钟，已排${row.scheduled_tasks}/${row.tasks}项任务`)}"><span class="setup-initial" style="width:${part('initial_minutes')}%"></span><span class="setup-change" style="width:${part('change_minutes')}%"></span></div><small>首次 ${n(row.initial_minutes)} / 跨族 ${n(row.change_minutes)} · 合计 ${n(row.setup_minutes)} 分钟</small><small>已排 ${row.scheduled_tasks} / ${row.tasks} 项；首次 ${row.initial_tasks} 次、跨族 ${row.change_tasks} 次</small></div></div>`}).join('');
 return panel('准备与交期取舍','',`<div class="setup-overview"><div><h3>已排任务的准备时间</h3><p class="source">同一刻度从0至 ${n(max)} 分钟。<span class="setup-key initial"></span>首次上机 <span class="setup-key change"></span>跨族换型</p>${bars}<p class="source">0分钟的首次或跨族仍计次数。同族延续不增加准备时间。</p></div><div>`+
 table(['整案结果','应完成时间优先','批次优先级优先'],[
  ['全部任务结束',...['due','priority'].map(p=>esc(time(columns[p].finished)))],
  ['已完成批次中晚交',...['due','priority'].map(p=>`${columns[p].late_jobs} 批 / 完成 ${columns[p].complete_jobs} 批`)],
  ['未排完批次',...['due','priority'].map(p=>`${columns[p].blocked_jobs} 批`)]] )+
 `<p class="setup-deltas">优先级策略减交期策略：准备 <b>${signed(summary.setup_delta_minutes)}${summary.setup_delta_minutes==null?'':' 分钟'}</b>；整案结束 <b>${signed(summary.finish_delta_minutes)}${summary.finish_delta_minutes==null?'':' 分钟'}</b>；晚交 <b>${signed(summary.late_jobs_delta)}${summary.late_jobs_delta==null?'':' 批'}</b>。</p><p class="source">${summary.setup_comparison_reason?esc(summary.setup_comparison_reason)+'，准备差值不计算。':''}整案结束与晚交差值须两列全部排入；时间差包含休息及夜间。少准备不保证更早交付。</p></div></div>`);
}
export function setupEventRows(report,{resource='',policy='',kind='change',page=1,size=30}={}){
 const all=report?.state==='ready'?report.events:[];
 const rows=all.filter(r=>(!resource||r.resource_id===resource)&&(!policy||r.policy===policy)&&(!kind||r.kind===kind));
 return {rows:rows.slice((page-1)*size,page*size),total:rows.length,all:all.length};
}
export function setupEventTable(rows,{esc,table}){
 return table(['策略 / 原设备','原任务 / 当前批次','换型类型 / 准备分钟','前一任务 / 批次 / 族','当前族 / 候选依据','准备开始 / 加工开始'],rows.map(r=>[
  `${names[r.policy]}<small class="block">${esc(r.resource_id)}</small>`,
  `<button class="row-link" data-setup-task="${esc(r.task_id)}">${esc(r.task_id)}</button><small class="block">${esc(r.job_id)}</small>`,
  `${kinds[r.kind]}<small class="block">${n(r.setup_minutes)} 分钟</small>`,
  r.previous_task_id?`<button class="row-link" data-setup-task="${esc(r.previous_task_id)}">${esc(r.previous_task_id)}</button><small class="block">${esc(r.previous_job_id)} / ${esc(r.previous_family)}</small>`:'无已排前一任务；初始族未登记',
  `${esc(r.family)}<small class="block">${esc(r.option_id)} · 声明 ${n(r.declared_setup_minutes)} 分钟</small>`,
  `${esc(r.started.replace('T',' '))}<small class="block">${esc(r.process_started.replace('T',' '))}</small>`]));
}
export function setupDetails(report,{esc,table,panel}){
 if(report?.state!=='ready')return '<p class="empty">没有可核查的换型资料。</p>';
 return panel('逐设备准备与原序任务','',`<p class="source">${esc(report.notice)}下方筛选只影响事件清单；上方整案结果、共同来源及完整导出不变。</p><details><summary>查看各设备的两种策略准备构成</summary>`+
 table(['原设备','交期策略：首次 / 跨族 / 总分钟','优先级策略：首次 / 跨族 / 总分钟','两列已排任务'],report.resources.map(r=>[
  `<button class="row-link" data-setup-resource="${esc(r.id)}">${esc(r.id)}</button>`,...['due','priority'].map(p=>`${n(r[p].initial_minutes)} / ${n(r[p].change_minutes)} / ${n(r[p].setup_minutes)}`),`${r.due.scheduled_tasks} / ${r.priority.scheduled_tasks}`]))+
 `</details><div class="filterbar"><label>设备<select id="setup-resource"><option value="">全部已使用资源</option>${report.resources.map(r=>`<option value="${esc(r.id)}">${esc(r.id)}</option>`).join('')}</select></label><label>策略<select id="setup-policy"><option value="">两种策略</option><option value="due">应完成时间优先</option><option value="priority">批次优先级优先</option></select></label><label>事件<select id="setup-kind"><option value="change">跨族换型</option><option value="initial">首次上机</option><option value="same">同族延续</option><option value="">全部已排任务</option></select></label><button id="setup-reset">重置为全部已排任务</button></div><div id="setup-events"></div><div class="toolbar"><button id="setup-prev">上一页</button><span id="setup-page"></span><button id="setup-next">下一页</button></div>`);
}
export function setupTaskEvidence(report,{esc,table}){
 if(!report)return '';
 return '<h3>原设备换型依据</h3>'+table(['核对项','应完成时间优先','批次优先级优先'],[
  ['事件',...['left','right'].map(side=>report[side]?kinds[report[side].kind]:'未排入，无准备事件')],
  ['前一任务 / 族',...['left','right'].map(side=>{const r=report[side];return r?esc(r.previous_task_id?(r.previous_task_id+' / '+r.previous_family):'无已排前一任务；初始族未登记'):'未形成'})],
  ['当前族 / 候选',...['left','right'].map(side=>{const r=report[side];return r?esc(r.family+' / '+r.option_id):'未形成'})],
  ['准备分钟（声明 / 原结果）',...['left','right'].map(side=>{const r=report[side];return r?n(r.declared_setup_minutes)+' / '+n(r.setup_minutes):'未形成'})]]);
}
