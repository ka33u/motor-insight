import {gantt} from './finite_schedule.js';
export const canCrew=role=>['admin','analyst','operations'].includes(role);
const minute=v=>typeof v==='number'&&Number.isFinite(v)?v.toLocaleString('zh-CN',{maximumFractionDigits:2}):'未计算',local=v=>v?.replace('T',' ')||'未形成完成时间';
export function crewGantt(d,mode='resource'){
 if(!['resource','worker'].includes(mode))throw Error('联立甘特视角无效');
 const view={...d,study:d.resource_study};
 if(mode==='worker'){view.resources=d.workers.map(w=>({...w,process:'人员',station:w.name}));view.tasks=d.tasks.map(t=>({...t,resource_id:t.employee_id}))}
 return gantt(view);
}
export function exportPath(key,policy,receipt,format){
 if(!receipt||!['due','priority'].includes(policy)||!['csv','json'].includes(format))throw Error('请先获取当前联立结果');
 return '/api/crew-schedule/'+encodeURIComponent(key)+'/export?'+new URLSearchParams({policy,receipt,format});
}
export function createCrewScheduleWorkspace(h){
 const {api,esc,header,panel,table,modal,toast,go,$,$$,on,isCurrent,getModalRevision}=h;let serial=0;
 const attempt=fn=>async(...a)=>{try{await fn(...a)}catch(e){toast(e.message)}};
 async function render(params,token){
  const list=await api('crew-schedule');if(!isCurrent(token))return;
  if(!list.rows.length){$('#main').innerHTML=header('设备与人员联立试排','导入独立未来人员假设后，与资源方案共同试排。')+'<div class="empty">尚未登记联立方案。</div>';return}
  const key=params.get('study')||list.rows[0].id,policy=params.get('policy')||'due',q=new URLSearchParams({policy});if(params.get('receipt'))q.set('receipt',params.get('receipt'));
  const d=await api('crew-schedule/'+encodeURIComponent(key)+'?'+q);if(!isCurrent(token))return;const current=++serial,alive=()=>isCurrent(token)&&serial===current,base='crew-schedule/'+encodeURIComponent(key),url=(suffix,more={})=>base+suffix+'?'+new URLSearchParams({policy,receipt:d.receipt,...more});
  const sources=rows=>table(['对象','Excel / 表 / 行','当前版本'],rows.map(s=>[`${esc(s.dataset)}<small class="block">${esc(s.key)}</small>`,s.missing?'来源缺失':`${esc(s.filename)}<br>${esc(s.sheet)} · 第 ${s.row} 行`,s.missing?'未计算':`v${s.revision} · 源行 ${s.source_row_id}`]));
  $('#main').innerHTML=header('设备与人员联立试排','同一工号跨设备、跨工序只占一份容量；资格覆盖整个换型与加工窗口。',`<a href="#finite-schedule?study=${encodeURIComponent(d.resource_study.id)}">资源试排参考 ↗</a>　<a href="#workforce">人员与技能登记 ↗</a>`)+
   `<div class="filterbar"><label>方案<select id="crew-study">${list.rows.map(s=>`<option value="${esc(s.id)}" ${s.id===key?'selected':''}>${esc(s.id+' · '+s.name)}</option>`).join('')}</select></label><label>策略<select id="crew-policy">${Object.entries(list.policies).map(([v,n])=>`<option value="${v}" ${v===policy?'selected':''}>${esc(n)}</option>`).join('')}</select></label><button id="crew-csv">全部任务 CSV</button><button id="crew-json">完整假设与结果 JSON</button><button id="crew-sources">全部来源 · ${d.source_count}</button></div>`+
   `<div class="source">${esc(d.study.version)} · 资源输入 ${esc(d.resource_study.id)}<br>${esc(local(d.resource_study.baseline))} — ${esc(local(d.resource_study.horizon_end))}<br>${esc(d.study.assumptions)}<br>${esc(d.notice)}</div>`+
   (d.summary?`<div class="finite-summary"><span>独立批次 <b>${d.summary.jobs}</b> / ${d.summary.qty} 台</span><span>已排任务 <b>${d.summary.scheduled_tasks}</b> / ${d.summary.tasks}</span><span>未排入批次 <b>${d.summary.blocked_jobs}</b></span><span>已排但晚于交期 <b>${d.summary.late_jobs}</b></span><span>同资源状态出现人员等待 <b>${d.summary.staff_delayed_tasks}</b></span></div>`:'<div class="empty">来源约束未通过；联立排程、负载和交期未计算。</div>')+
   (d.issues.length?panel('整个方案暂停原因',`<ul>${d.issues.map(i=>`<li>${esc(i)}</li>`).join('')}</ul>`):'')+
   panel('一组排程，两种占用视角','<div class="filterbar"><button id="crew-by-resource">按设备</button><button id="crew-by-worker">按人员</button></div><div id="crew-chart">'+crewGantt(d)+'</div>')+
   panel('批次完成与资源参考',`<p class="source">${esc(d.resource_reference.notice)}</p>`+table(['批次 / 配置','台数','应完成','资源试排参考完成','人员联立完成','完成差值分钟','联立状态'],d.jobs.map(j=>[`${esc(j.id)}<small class="block">${esc(j.product_id)}</small>`,j.qty,esc(local(j.due)),esc(local(j.resource_reference_finished)),esc(local(j.finished)),minute(j.completion_delta_minutes),j.state==='blocked'?'未排入':j.state==='late'?'晚于假设交期':'按假设已排'])))+
   panel('全部任务、人员与等待',table(['任务 / 工序','设备 / 工号','资格 / 人员窗口','开始 / 完成','换型＋加工分钟','共同等待 / 同资源状态人员新增等待','状态 / 原因'],d.tasks.map(t=>[`<button class="row-link" data-crew-task="${esc(t.id)}">${esc(t.id)}</button><small class="block">${esc(t.process+' / '+t.branch)}</small>`,`${esc(t.resource_id||'未排入')}<br>${esc(t.employee_id||'未指派')}`,`${esc(t.credential_id||'未计算')}<br>${esc(t.worker_window_id||'未计算')}`,`${esc(local(t.started))}<br>${esc(local(t.finished))}`,`${minute(t.setup_minutes)} ＋ ${minute(t.process_minutes)}`,`${minute(t.wait_minutes)} / ${minute(t.staff_additional_wait_minutes)}`,`${t.state==='scheduled'?'已排':'未排入'}<small class="block">${esc(t.reason)}</small>`])))+
   panel('人员假设窗口与占用',table(['工号 / 姓名','假设可用分钟','试排占用分钟','假设占用比例','任务数'],d.workers.map(w=>[`${esc(w.id)} / ${esc(w.name)}`,minute(w.available_minutes),minute(w.busy_minutes),minute(w.load_percent)+(w.load_percent==null?'':'%'),w.task_count])))+
   panel('资格登记与未来假设的交集',table(['资格假设 / 工号','工序 / 技能依据','登记状态 / 日期（到期日包含）','本方案假设窗口（右侧不包含）','有效交集 / 状态'],d.credentials.map(c=>[`${esc(c.id)}<br>${esc(c.employee_id)}`,`${esc(c.process)}<br>${esc(c.skill_id)}`,`${esc(c.registered_status)}<br>${esc(c.registered_approved)} — ${esc(c.registered_expires)}`,`${esc(local(c.assumed_from))}<br>${esc(local(c.assumed_until))}`,c.eligible?`${esc(local(c.effective_from))}<br>${esc(local(c.effective_until))}`:esc(c.reason)])))+
   '<p class="source">同资源状态人员新增等待：固定此前已排资源、工序准备与当前选中设备，比较含人员与资格后的开始时间。不代表现场人员效率或因果损失；批次差值来自两个启发式结果。人员占用是假设，不是考勤、绩效、加班或人工成本。没有物料、模具联立或正式计划批准。</p>';
  on('#crew-study','change',e=>go('crew-schedule',{study:e.target.value,policy}));on('#crew-policy','change',e=>go('crew-schedule',{study:key,policy:e.target.value}));
  on('#crew-by-resource','click',()=>{$('#crew-chart').innerHTML=crewGantt(d,'resource')});on('#crew-by-worker','click',()=>{$('#crew-chart').innerHTML=crewGantt(d,'worker')});
  const detail=attempt(async id=>{const rev=getModalRevision(),p=await api(url('/tasks/'+encodeURIComponent(id)));if(!alive()||rev!==getModalRevision())return;modal('联立任务、资格与窗口依据',`<p>${esc(p.notice)}</p><pre class="code-block">${esc(JSON.stringify(p.row,null,2))}</pre>`+sources(p.sources))});
  $$('[data-crew-task]').forEach(el=>el.addEventListener('click',()=>detail(el.dataset.crewTask)));
  on('#crew-chart','click',e=>{const el=e.target.closest('[data-finite-task]');if(el)detail(el.dataset.finiteTask)});on('#crew-chart','keydown',e=>{const el=e.target.closest('[data-finite-task]');if(el&&(e.key==='Enter'||e.key===' ')){e.preventDefault();detail(el.dataset.finiteTask)}});
  async function evidence(page=1){const rev=getModalRevision(),s=await api(url('/sources',{page}));if(!alive()||rev!==getModalRevision())return;modal('全方案来源，包括共享人员和设备竞争',sources(s.rows)+`<p>第 ${page} 页，共 ${s.total} 条。原件权限独立核对；${s.can_download_original?'管理员可在导入页读取归档原件。':'本页来源不授予原件下载权限。'}</p><button id="crew-prev" ${page===1?'disabled':''}>上一页</button> <button id="crew-next" ${page*40>=s.total?'disabled':''}>下一页</button>`);on('#crew-prev','click',attempt(()=>evidence(page-1)));on('#crew-next','click',attempt(()=>evidence(page+1)))}
  on('#crew-sources','click',attempt(()=>evidence()));
  async function download(format){const r=await fetch(exportPath(key,policy,d.receipt,format),{credentials:'same-origin',cache:'no-store'});if(!alive())return;if(!r.ok){const e=await r.json().catch(()=>({error:'联立文件读取失败'}));throw Error(e.error||'联立文件读取失败')}if(!r.headers.get('Content-Disposition')?.startsWith('attachment;'))throw Error('响应不是结果文件');const blob=await r.blob();if(!alive())return;const path=URL.createObjectURL(blob),a=document.createElement('a');a.href=path;a.download='crew-'+key+'.'+format;document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(path),1000)}
  on('#crew-csv','click',attempt(()=>download('csv')));on('#crew-json','click',attempt(()=>download('json')));
 }
 return {render};
}
