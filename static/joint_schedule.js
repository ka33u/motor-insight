import {crewGantt} from './crew_schedule.js';
export const canJoint=role=>['admin','analyst','operations'].includes(role);
const minute=v=>typeof v==='number'&&Number.isFinite(v)?v.toLocaleString('zh-CN',{maximumFractionDigits:2}):'未计算';
const local=v=>v?.replace('T',' ')||'未形成时间';
export function exportPath(key,policy,receipt,format){
 if(!receipt||!['due','priority'].includes(policy)||!['csv','json'].includes(format))throw Error('请先获取当前物料联立结果');
 return '/api/joint-schedule/'+encodeURIComponent(key)+'/export?'+new URLSearchParams({policy,receipt,format});
}
export function jointOverview(d,{esc,table,panel}){
 const summary=d.summary;
 return (summary?`<div class="finite-summary"><span>批次 / 台数 <b>${summary.jobs} / ${summary.qty}</b></span><span>已排任务 <b>${summary.scheduled_tasks} / ${summary.tasks}</b></span><span>未排入批次 <b>${summary.blocked_jobs}</b></span><span>已排但晚交 <b>${summary.late_jobs}</b></span><span>已预留需求行 <b>${summary.reserved_demands} / ${summary.demands}</b></span></div>`:'<div class="empty">资料约束未通过；排程和物料预留均未计算。</div>')+
 (d.issues.length?panel('先核对这些资料',`<ul>${d.issues.map(v=>`<li>${esc(v)}</li>`).join('')}</ul>`):'')+
 `<div class="joint-reading"><div><b>1 · 看能否完成</b><p>完整批次才计算交期。未排入不记为准时；暂停计算不显示零延误。</p></div><div><b>2 · 找首个阻断</b><p>物料短缺与无共同窗口分开呈现；后续工序保留首个阻断任务。</p></div><div><b>3 · 对照物料依据</b><p>查整批需求、供给时间和预留流水；未排完批次的已有预留继续保留。</p></div></div>`+
 panel('批次交期 · 与设备人员参考对照',`<p class="source">${esc(d.crew_reference.notice)}</p>`+table(['批次 / 配置','台数','应完成','设备人员参考','物料人机联立完成','差值分钟','状态'],d.jobs.map(j=>[`${esc(j.id)}<small class="block">${esc(j.product_id)}</small>`,j.qty,esc(local(j.due)),esc(local(j.crew_reference_finished)),esc(local(j.finished)),minute(j.completion_delta_minutes),`<span class="joint-state ${j.state==='blocked'?'blocked':j.state==='late'?'late':''}">${j.state==='blocked'?'未排入':j.state==='late'?'晚于交期':'按假设已排'}</span>`])))+
 '<p class="source">物料就绪等待是前序就绪到用料可用的时间；共同等待还包含设备、人员与资格窗口。两者不能相加，也不是现场停工损失或因果归因。</p>';
}
export function createJointScheduleWorkspace(h){
 const {api,esc,header,panel,table,modal,toast,go,$,$$,on,isCurrent,getModalRevision}=h;let serial=0;
 const attempt=fn=>async(...args)=>{try{await fn(...args)}catch(e){toast(e.message)}};
 const sourceTable=rows=>table(['对象','Excel / 表 / 行','当前版本'],rows.map(s=>[`${esc(s.dataset)}<small class="block">${esc(s.key)}</small>`,s.missing?'来源缺失':`${esc(s.filename)}<br>${esc(s.sheet)} · 第 ${s.row} 行`,s.missing?'未计算':`v${s.revision} · 源行 ${s.source_row_id}`]));
 async function render(params,token){
  const list=await api('joint-schedule');if(!isCurrent(token))return;
  if(!list.rows.length){$('#main').innerHTML=header('物料、人机联立试排','在同一份未来假设中，核对用料、设备与人员是否同时可用。')+'<div class="empty">导入39号模拟工作簿后可选择联立方案。</div>';return}
  const key=params.get('study')||list.rows[0].id,policy=params.get('policy')||'due',query=new URLSearchParams({policy});if(params.get('receipt'))query.set('receipt',params.get('receipt'));
  const d=await api('joint-schedule/'+encodeURIComponent(key)+'?'+query);if(!isCurrent(token))return;
  const current=++serial,alive=()=>isCurrent(token)&&serial===current,base='joint-schedule/'+encodeURIComponent(key),url=(suffix,more={})=>base+suffix+'?'+new URLSearchParams({policy,receipt:d.receipt,...more});
  $('#main').innerHTML=header('物料、人机联立试排','从“排得下”走到“料、人、机同时具备”。全部为独立合成假设。',`<a href="#crew-schedule?study=${encodeURIComponent(d.crew_study.id)}&policy=${policy}">设备人员参考 ↗</a>`)+
   `<div class="filterbar"><label>方案<select id="joint-study">${list.rows.map(s=>`<option value="${esc(s.id)}" ${s.id===key?'selected':''}>${esc(s.id+' · '+s.name)}</option>`).join('')}</select></label><label>派序策略<select id="joint-policy">${Object.entries(list.policies).map(([v,n])=>`<option value="${v}" ${v===policy?'selected':''}>${esc(n)}</option>`).join('')}</select></label><button id="joint-csv">完整分区 CSV</button><button id="joint-json">假设与结果 JSON</button><button id="joint-sources">全部来源 · ${d.source_count}</button></div>`+
   `<div class="source">${esc(d.study.version)} · 人机方案 ${esc(d.crew_study.id)}<br>${esc(local(d.resource_study.baseline))} — ${esc(local(d.resource_study.horizon_end))}<br>${esc(d.study.scope)}<br>${esc(d.study.assumptions)}</div>`+
   jointOverview(d,h)+
   `<div class="filterbar joint-tabs"><button id="joint-tab-schedule">排程与阻断</button><button id="joint-tab-material">物料与预留</button></div><div id="joint-body"></div>`+
   `<details class="source"><summary>计算边界与预留规则</summary><p>${esc(d.notice)}</p><p>总量缺口只比较同物料同单位的需求与范围内可用供给；不证明时间齐套。总剩余供给包括范围外到料，未预留需求也可能是人机受阻。不同方案的供给彼此独立，不合并计算。</p></details>`;
  on('#joint-study','change',e=>go('joint-schedule',{study:e.target.value,policy}));on('#joint-policy','change',e=>go('joint-schedule',{study:key,policy:e.target.value}));
  const detail=attempt(async id=>{const revision=getModalRevision(),p=await api(url('/tasks/'+encodeURIComponent(id)));if(!alive()||revision!==getModalRevision())return;modal('任务、整批用料与预留依据',`<p>${esc(p.notice)}</p><pre class="code-block">${esc(JSON.stringify({任务:p.row,用料:p.demands,预留:p.reservations},null,2))}</pre>`+sourceTable(p.sources))});
  function bindTasks(){
   $$('[data-joint-task]').forEach(el=>el.addEventListener('click',()=>detail(el.dataset.jointTask)));
   on('#joint-chart','click',e=>{const el=e.target.closest('[data-finite-task]');if(el)detail(el.dataset.finiteTask)});
   on('#joint-chart','keydown',e=>{const el=e.target.closest('[data-finite-task]');if(el&&(e.key==='Enter'||e.key===' ')){e.preventDefault();detail(el.dataset.finiteTask)}});
  }
  function schedule(){
   $('#joint-body').innerHTML=panel('同一排程 · 设备与人员占用','<div class="filterbar"><button id="joint-device">按设备</button><button id="joint-worker">按人员</button></div><div id="joint-chart">'+crewGantt(d)+'</div>')+
    panel('任务明细与阻断链',`<div class="filterbar"><label>批次<select id="joint-job"><option value="">全部批次</option>${d.jobs.map(j=>`<option value="${esc(j.id)}">${esc(j.id)}</option>`).join('')}</select></label><label>任务状态<select id="joint-state"><option value="">全部任务</option><option value="blocked">未排入</option><option value="scheduled">已排入</option></select></label></div><div id="joint-tasks"></div>`);
   function rows(){
    const job=$('#joint-job').value,state=$('#joint-state').value,selected=d.tasks.filter(t=>(!job||t.job_id===job)&&(!state||t.state===state));
    $('#joint-tasks').innerHTML=table(['任务 / 工序','设备 / 人员','准备开始 / 完成','物料就绪 / 共同等待分钟','预留需求行','状态 / 首个阻断'],selected.map(t=>[`<button class="row-link" data-joint-task="${esc(t.id)}">${esc(t.id)}</button><small class="block">${esc(t.process+' / '+t.branch)}</small>`,`${esc(t.resource_id||'未排入')}<br>${esc(t.employee_id||'未指派')}`,`${esc(local(t.started))}<br>${esc(local(t.finished))}`,`${minute(t.material_readiness_delay_minutes)} / ${minute(t.wait_minutes)}`,esc(t.new_reservation_ids.join('、')||'本任务未新增'),`${t.state==='scheduled'?'已排':'未排入'}<small class="block">${esc(t.reason)}</small>${t.root_tasks.length?`<small class="block">${esc(t.root_tasks.join('、'))}</small>`:''}`]));
    $$('[data-joint-task]').forEach(el=>el.addEventListener('click',()=>detail(el.dataset.jointTask)));
   }
   rows();on('#joint-job','change',rows);on('#joint-state','change',rows);
   on('#joint-device','click',()=>{$('#joint-chart').innerHTML=crewGantt(d,'resource')});on('#joint-worker','click',()=>{$('#joint-chart').innerHTML=crewGantt(d,'worker')});
   // Chart listeners survive changes to its inner markup.
   on('#joint-chart','click',e=>{const el=e.target.closest('[data-finite-task]');if(el)detail(el.dataset.finiteTask)});
   on('#joint-chart','keydown',e=>{const el=e.target.closest('[data-finite-task]');if(el&&(e.key==='Enter'||e.key===' ')){e.preventDefault();detail(el.dataset.finiteTask)}});
  }
  function material(){
   $('#joint-body').innerHTML=panel('物料总量核对',`<p class="source">同物料同单位分别核对，不合计kg和件。范围内可用供给仍需满足具体任务开始时间。隔离量按整批排除，避免与“其中不可预留量”重复扣除。</p>`+table(['物料 / 单位','整批需求','范围内可用供给','总量缺口','已预留','总排除量','总剩余（含范围外）'],d.balances.map(b=>[`${esc(b.material_id+' · '+b.material_name)}<small class="block">${esc(b.unit)}</small>`,esc(b.required_qty),esc(b.horizon_usable_qty),esc(b.initial_supply_gap_qty),esc(b.reserved_qty),esc(b.total_excluded_qty),esc(b.total_remaining_qty)])))+
    panel('整批需求与触发任务',table(['需求 / 批次','BOM / 工序','物料 / 单位','用量与损耗 / 步长','整批需求','预留状态 / 时间'],d.demands.map(n=>[`${esc(n.id)}<small class="block">${esc(n.job_id)}</small>`,`${esc(n.bom_id)}<br>${esc(n.route_id)}`,`${esc(n.material_id)} / ${esc(n.unit)}`,`${esc(n.bom_qty)} × (1 + ${esc(n.scrap_allowance)})<small class="block">向上取整步长 ${esc(n.quantum)}</small>`,esc(n.required_qty),n.reservation?`<button class="row-link" data-joint-task="${esc(n.reservation.task_id)}">${esc(n.reservation.task_id)}</button><small class="block">${esc(local(n.reservation.reserved_at))}</small>`:'未预留；结合任务阻断核查'])))+
    panel('供给批次账 · 可用 = 预留 + 剩余',table(['供给 / 模拟批号','物料 / 单位','假设可用时间','账面 / 排除','可用 / 预留 / 剩余','状态 / 假设类型'],d.lots.map(l=>[`${esc(l.id)}<small class="block">${esc(l.lot)}</small>`,`${esc(l.material_id)} / ${esc(l.unit)}`,esc(local(l.available_from)),`${esc(l.qty)} / ${esc(l.excluded_qty)}`,`${esc(l.usable_qty)} / ${esc(l.reserved_qty)} / ${esc(l.remaining_qty)}`,`${esc(l.status)}<br>${esc(l.kind)}`])))+
    panel('FIFO预留流水',table(['需求 / 供给批次','触发任务','物料 / 单位','预留量','可用起点 / 预留时点'],d.reservations.map(a=>[`${esc(a.demand_id)}<br>${esc(a.supply_id)}`,`<button class="row-link" data-joint-task="${esc(a.task_id)}">${esc(a.task_id)}</button>`,`${esc(a.material_id)} / ${esc(a.unit)}`,esc(a.qty),`${esc(local(a.available_from))}<br>${esc(local(a.reserved_at))}`])));
   bindTasks();
  }
  on('#joint-tab-schedule','click',schedule);on('#joint-tab-material','click',material);schedule();
  async function evidence(page=1){const revision=getModalRevision(),s=await api(url('/sources',{page}));if(!alive()||revision!==getModalRevision())return;modal('共享供给、人机与BOM全部来源',sourceTable(s.rows)+`<p>第 ${page} 页，共 ${s.total} 条。${s.can_download_original?'管理员可在导入页读取归档原件。':'来源索引不授予原件下载权限。'}</p><button id="joint-prev" ${page===1?'disabled':''}>上一页</button> <button id="joint-next" ${page*40>=s.total?'disabled':''}>下一页</button>`);on('#joint-prev','click',attempt(()=>evidence(page-1)));on('#joint-next','click',attempt(()=>evidence(page+1)))}
  on('#joint-sources','click',attempt(()=>evidence()));
  async function download(format){const response=await fetch(exportPath(key,policy,d.receipt,format),{credentials:'same-origin',cache:'no-store'});if(!alive())return;if(!response.ok){const e=await response.json().catch(()=>({error:'联立文件读取失败'}));throw Error(e.error||'联立文件读取失败')}if(!response.headers.get('Content-Disposition')?.startsWith('attachment;'))throw Error('响应不是结果文件');const blob=await response.blob();if(!alive())return;const path=URL.createObjectURL(blob),a=document.createElement('a');a.href=path;a.download='joint-'+key+'.'+format;document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(path),1000)}
  on('#joint-csv','click',attempt(()=>download('csv')));on('#joint-json','click',attempt(()=>download('json')));
 }
 return {render};
}
