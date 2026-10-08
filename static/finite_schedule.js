import {scheduleSources,scheduleTaskDetail,createScheduleReadGuard} from './schedule_reading.js';
const escape=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const minute=v=>typeof v==='number'&&Number.isFinite(v)?v.toLocaleString('zh-CN',{maximumFractionDigits:2}):'未计算';
const local=v=>v?.replace('T',' ')||'未排入';
const wall=v=>Date.parse(v+'Z'); // Axis arithmetic uses plant wall time, independent of browser timezone.
export function gantt(d,{axisLabel='独立资源位'}={}){
 if(d.state!=='trial')return '<div class="empty">来源约束未通过，甘特图暂停；先处理下方原因。</div>';
 const start=wall(d.study.baseline),end=wall(d.study.horizon_end),width=1500,left=205,right=1480,top=56,line=42,height=top+d.resources.length*line+26;
 const x=v=>left+(wall(v)-start)/(end-start)*(right-left),colors={'定子':'#337d8b','转子':'#705f9e','整机':'#347458'};
 let svg=`<svg viewBox="0 0 ${width} ${height}" width="${width}" height="${height}" role="img" aria-label="试排甘特图，横轴是厂内假设时间，纵轴是${escape(axisLabel)}"><rect width="${width}" height="${height}" fill="#fff"/>`;
 for(let at=start;at<=end;at+=86400000){let xx=left+(at-start)/(end-start)*(right-left);svg+=`<line x1="${xx}" y1="35" x2="${xx}" y2="${height-10}" stroke="#d7dfe1"/><text x="${xx+5}" y="23">${new Date(at).toISOString().slice(5,10)}</text>`}
 d.resources.forEach((r,i)=>{const y=top+i*line;svg+=`<text x="8" y="${y+17}">${escape(r.id)}</text><text x="8" y="${y+32}" class="finite-gantt-sub">${escape(r.process)} · ${minute(r.load_percent)}${r.load_percent==null?'':'%假设负载'}</text>`;
  for(const w of r.windows)svg+=`<rect x="${x(w.started)}" y="${y+5}" width="${x(w.finished)-x(w.started)}" height="26" fill="#edf2f4"><title>${escape(w.id+' '+local(w.started)+' — '+local(w.finished))}</title></rect>`;
  for(const b of r.blocks){const a=Math.max(start,wall(b.started)),z=Math.min(end,wall(b.finished));if(z>a)svg+=`<rect x="${left+(a-start)/(end-start)*(right-left)}" y="${y+5}" width="${(z-a)/(end-start)*(right-left)}" height="26" fill="#e3a7a1"><title>${escape(b.reason)}</title></rect>`}
  for(const t of d.tasks.filter(t=>t.resource_id===r.id&&t.state==='scheduled')){
   const a=x(t.started),p=x(t.process_started),z=x(t.finished);svg+=`<g data-finite-task="${escape(t.id)}" tabindex="0" role="button" aria-label="${escape(t.id+' '+t.process+' '+local(t.started)+'至'+local(t.finished))}"><rect x="${a}" y="${y+8}" width="${p-a}" height="20" fill="#d7a849"/><rect x="${p}" y="${y+8}" width="${Math.max(.2,z-p)}" height="20" fill="${colors[t.branch]||'#526e8e'}"/><title>${escape(t.job_id+' '+t.process+' · '+t.qty+'台 · 换型'+minute(t.setup_minutes)+'分钟 · '+local(t.started)+' — '+local(t.finished))}</title></g>`;
  }
 });
 return '<div class="finite-gantt-scroll">'+svg+'</svg></div><div class="finite-legend"><span>蓝：定子</span><span>紫：转子</span><span>绿：整机</span><span>黄：换型占用</span><span>红：假设不可用</span><span>灰底：可用窗口</span></div>';
}
export function exportPath(key,policy,receipt,format){
 if(!['due','priority'].includes(policy)||!['csv','json'].includes(format)||!receipt)throw Error('请先获取当前试排结果');
 return '/api/finite-schedule/'+encodeURIComponent(key)+'/export?'+new URLSearchParams({policy,receipt,format});
}
export function createFiniteScheduleWorkspace(h){
 const {api,esc,header,panel,table,modal,toast,go,$,$$,on,isCurrent,getModalRevision}=h;const reads=createScheduleReadGuard(h);
 async function render(params,token){
  const {alive,attempt,read,modalRead}=reads.begin(token);
  const list=await read(()=>api('finite-schedule'));if(!list)return;
  if(!list.rows.length){$('#main').innerHTML=header('有限资源试排','导入独立模拟批次、工序依赖和未来资源窗口后开始。')+'<div class="empty">尚未登记方案。</div>';return}
  const key=params.get('study')||list.rows[0].id,policy=params.get('policy')||'due',q=new URLSearchParams({policy});
  if(params.get('receipt'))q.set('receipt',params.get('receipt'));
  const d=await read(()=>api('finite-schedule/'+encodeURIComponent(key)+'?'+q));if(!d)return;
  const base='finite-schedule/'+encodeURIComponent(key),url=(suffix,extra={})=>base+suffix+'?'+new URLSearchParams({policy,receipt:d.receipt,...extra});
  const sources=rows=>scheduleSources(rows,h);
  const change=fields=>go('finite-schedule',{study:key,policy,...fields});
  $('#main').innerHTML=header('有限资源试排','从批次假设到资源甘特图，再到交期风险和Excel依据。',`<a href="#manufacturing">制造事实 ↗</a>　<a href="#production">历史资源日历 ↗</a>`)+
   `<div class="filterbar"><label>方案<select id="finite-study">${list.rows.map(s=>`<option value="${esc(s.id)}" ${s.id===key?'selected':''}>${esc(s.id+' · '+s.name)}</option>`).join('')}</select></label><label>策略<select id="finite-policy">${Object.entries(list.policies).map(([v,n])=>`<option value="${v}" ${v===policy?'selected':''}>${esc(n)}</option>`).join('')}</select></label><button id="finite-refresh">重新读取</button><button id="finite-csv">导出全部任务 CSV</button><button id="finite-json">导出完整结果 JSON</button><button id="finite-sources">全方案来源 · ${d.source_count}</button></div>`+
   `<div class="source">${esc(d.study.version)} · ${esc(local(d.study.baseline))} — ${esc(local(d.study.horizon_end))}<br>${esc(d.study.scope)}<br>${esc(d.study.assumptions)}<br>${esc(d.notice)}<br>排程方法：按策略选择已满足前序的任务，在候选资源尾部寻找可容纳完整换型和加工的窗口，以最早完成者安排；空档不回填，不证明全局最优。</div>`+
   (d.summary?`<div class="finite-summary"><span>独立批次 <b>${d.summary.jobs}</b> / ${d.summary.qty} 台</span><span>已排任务 <b>${d.summary.scheduled_tasks}</b> / ${d.summary.tasks}</span><span>未排入批次 <b>${d.summary.blocked_jobs}</b></span><span>已排但晚于假设交期 <b>${d.summary.late_jobs}</b></span></div>`:'<div class="empty">试排已暂停；任务完成数、交期与负载均未计算。</div>')+
   (d.issues.length?panel('来源约束待核对','',`<ul>${d.issues.map(i=>`<li>${esc(i)}</li>`).join('')}</ul>`):'')+
   panel('资源窗口与工序甘特图','',gantt(d))+
   panel('独立批次的完成与风险','',table(['试排批次 / 配置','台数','优先级','应完成 / 试排完成','状态 / 晚于分钟','已排工序'],d.jobs.map(j=>[`${esc(j.id)}<small class="block">${esc(j.product_id)}</small>`,j.qty,j.priority,`${esc(local(j.due))}<br>${esc(local(j.finished))}`,`${j.state==='blocked'?'未排入':j.state==='late'?'晚于假设交期':'按假设已排'}<small class="block">${minute(j.lateness_minutes)}</small>`,j.scheduled_count+' / '+j.task_count])))+
   panel('所有工序：等待、分支与未排入原因','',table(['任务 / 批次','工序 / 分支','资源位','换型＋加工分钟','准备 / 加工 / 完成','依赖准备 / 后续等待分钟','状态 / 原因'],d.tasks.map(t=>[`<button class="row-link" data-finite-task="${esc(t.id)}">${esc(t.id)}</button><small class="block">${esc(t.job_id)}</small>`,`${esc(t.process)} / ${esc(t.branch)}`,esc(t.resource_id||'未排入'),`${minute(t.setup_minutes)} ＋ ${minute(t.process_minutes)}`,`${esc(local(t.started))}<br>${esc(local(t.process_started))}<br>${esc(local(t.finished))}`,`${esc(local(t.dependency_ready))}<br>${minute(t.wait_minutes)}`,`${t.state==='scheduled'?'已排':'未排入'}<small class="block">${esc(t.reason)}</small>`])))+
   panel('资源负载：独立窗口扣除不可用段','',table(['资源位 / 工序','可安排分钟','试排占用分钟','假设负载','任务数'],d.resources.map(r=>[`${esc(r.id)} / ${esc(r.process)}`,minute(r.available_minutes),minute(r.busy_minutes),minute(r.load_percent)+(r.load_percent==null?'':'%'),r.task_count])))+
   '<p class="source">换型与加工各自向上取整到秒。批次台数只计一次；资源负载是本方案窗口中的试排占用，不能视为实际利用率或OEE。未排入与已排但晚于交期分开；暂无正式业务审批。</p>';
  on('#finite-study','change',e=>change({study:e.target.value}));on('#finite-policy','change',e=>change({policy:e.target.value}));
  async function evidence(page=1){const s=await modalRead(()=>api(url('/sources',{page})));if(!s)return;modal('全方案Excel依据',sources(s.rows)+`<p>第 ${s.page} 页，共 ${s.total} 条。${s.can_download_original?'管理员可在导入批次页读取归档原件。':'当前岗位仅可查看来源，不授予原件下载权限。'}</p><button id="finite-prev" ${page===1?'disabled':''}>上一页</button> <button id="finite-next" ${page*(s.size||40)>=s.total?'disabled':''}>下一页</button>`);on('#finite-prev','click',attempt(()=>evidence(page-1)));on('#finite-next','click',attempt(()=>evidence(page+1)))}
  on('#finite-sources','click',attempt(()=>evidence()));
  on('#finite-refresh','click',async()=>{if(!alive())return;const fresh=new URLSearchParams(params);fresh.delete('receipt');try{await render(fresh,token)}catch(e){if(isCurrent(token))toast(e.message)}});
  const openTask=attempt(async id=>{const p=await modalRead(()=>api(url('/tasks/'+encodeURIComponent(id))));if(p)modal('任务与依赖依据',scheduleTaskDetail(p,h,'finite'))});
  $$('[data-finite-task]').forEach(el=>{el.addEventListener('click',()=>openTask(el.dataset.finiteTask));if(el.tagName.toLowerCase()==='g')el.addEventListener('keydown',e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();openTask(el.dataset.finiteTask)}})});
  let downloading=false;async function download(format){if(downloading)return;downloading=true;try{const r=await fetch(exportPath(key,policy,d.receipt,format),{credentials:'same-origin',cache:'no-store'});if(!alive())return;if(!r.ok){const e=await r.json().catch(()=>({error:'文件读取失败'}));throw Error(e.error||'文件读取失败')}if(!r.headers.get('Content-Disposition')?.startsWith('attachment;'))throw Error('响应不是结果文件');const blob=await r.blob();if(!alive())return;const path=URL.createObjectURL(blob),a=document.createElement('a');a.href=path;a.download='finite-'+key+'.'+format;document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(path),1000)}finally{downloading=false}}
  on('#finite-csv','click',attempt(()=>download('csv')));on('#finite-json','click',attempt(()=>download('json')));
 }
 return {render};
}
