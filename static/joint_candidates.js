const time = v => typeof v === 'string' && v ? v.replace('T',' ') : '未形成时间';
const state = v => ({scheduled:'已排入',blocked:'未排入',late:'晚于假设交期'}[v] || '未计算');

export function jointCandidateEvidence(d, {esc, table, panel}) {
 const link = row => row.id === d.task_id ? esc(row.id)+'（当前任务）' : `<button class="row-link" data-joint-related-task="${esc(row.id)}">${esc(row.id)}</button>`;
 const related = rows => rows.length ? table(['任务 / 工序','批次 / 配置','当前安排','准备开始 / 完成','未排原因'], rows.map(r => [
  `${link(r)}<small class="block">${esc(r.process)} / ${esc(r.branch)}</small>`, `${esc(r.job_id)}<br>${esc(r.product_id)}`,
  state(r.state), `${esc(time(r.started))}<br>${esc(time(r.finished))}`, esc(r.reason || (r.state === 'scheduled' ? '无阻断' : '未提供原因'))
 ])) : '<p class="empty">当前任务没有此类关联。</p>';
 const windows = (rows, identity, blocked) => rows.length ? table([blocked?'不可用段 / 原因':'输入窗口',identity==='resource_id'?'资源位':'工号','开始（包含） / 结束（不包含）','假设依据'], rows.map(r => [
  `${esc(r.id)}${blocked?'<small class="block">'+esc(r.reason)+'</small>':''}`,esc(r[identity]),`${esc(time(r.started))}<br>${esc(time(r.finished))}`,esc(r.basis)
 ])) : '<p class="empty">未登记该类输入，不表示已经具备可用容量。</p>';
 return panel('候选人机与窗口依据', d.notice,
  `<p class="source">本次试排范围：${esc(time(d.baseline))} — ${esc(time(d.horizon_end))}。候选编号按原始输入逐项保留。</p>`+
  '<h3>候选设备 · 批量上限</h3>'+ (d.resource_options.length ? table(['资源候选 / 资源位','工序 / 并行容量','任务台数 / 批量上限','批量符合 / 本次选中','首次或跨族换型分钟 / 依据'],d.resource_options.map(r=>[
   `${esc(r.id)}<small class="block">${esc(r.resource_id)}</small>`,`${esc(r.process)} / ${esc(r.capacity)}`,`${esc(r.task_qty)} / ${esc(r.max_batch_qty)}`,
   `${r.batch_fits===true?'符合批量上限':r.batch_fits===false?'超出批量上限':'批量结果缺失'}<br>${r.selected?'本次选中':'未选中'}`,`${esc(r.setup_minutes)}<small class="block">${esc(r.basis)}</small>`
  ])) : '<p class="empty">本任务没有登记候选设备。</p>')+
  '<h3>候选人员 · 资格交集</h3>'+ (d.people_candidates.length ? table(['人员候选 / 工号','资格 / 技能 / 工序','登记状态 / 日期（到期日包含）','资格假设（右侧不包含）','原计算有效交集 / 本次选中','资格结果 / 候选依据'],d.people_candidates.map(r=>[
   `${esc(r.id)}<small class="block">${esc(r.employee_id)}</small>`,`${esc(r.credential_id)}<br>${esc(r.skill_id)}<br>${esc(r.process)}`,
   `${esc(r.registered_status)}<small class="block">${esc(r.registered_approved)} — ${esc(r.registered_expires)}</small>`,`${esc(time(r.assumed_from))}<br>${esc(time(r.assumed_until))}`,
   `${esc(time(r.effective_from))}<br>${esc(time(r.effective_until))}<small class="block">${r.selected?'本次选中':'未选中'}</small>`,
   `${r.eligible===true?'资格交集可用':r.eligible===false?'资格交集不可用':'资格结果缺失'}<small class="block">${esc(r.reason)}<br>${esc(r.basis)}</small>`
  ])) : '<p class="empty">本任务没有登记候选人员。</p>')+
  `<details><summary>候选设备输入窗口 ${d.schedule_windows.length} 条 · 不可用段 ${d.schedule_blocks.length} 条</summary>`+
  windows(d.schedule_windows,'resource_id',false)+windows(d.schedule_blocks,'resource_id',true)+'</details>'+
  `<details><summary>候选人员输入窗口 ${d.crew_windows.length} 条 · 不可用段 ${d.crew_blocks.length} 条</summary>`+
  windows(d.crew_windows,'employee_id',false)+windows(d.crew_blocks,'employee_id',true)+'</details>')+
  panel('沿任务依赖核查','点击关联任务读取其当前依据；首个阻断任务不等于已经确认的现场根因。',
   '<h3>直接前序</h3>'+related(d.predecessors)+'<h3>原试排传播的首个阻断任务</h3>'+related(d.root_tasks));
}
