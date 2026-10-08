import {wipBlockerReport,wipTaskSelection,wipBlockerQueue} from './wip_blockers.js';
import {scheduleSources,createScheduleReadGuard} from './schedule_reading.js';
export const taskStates={completed:'历史已完成',carried:'原人机续作',scheduled:'剩余任务已排',blocked:'未排入'};
const time=v=>v?.replace('T',' ')||'—';
const amount=(v,h)=>v==null?'—':h.esc(v);
export function selectTasks(d,filters={},report=wipBlockerReport(d)){return wipTaskSelection(d,report,filters);}
export function taskRows(rows,h,interactive=true){
 const {esc,table}=h;
 return table(['任务 / 工序 / 原状态','原处理 / 已完成 / 剩余','未来人机','准备 / 加工分钟','未来开始 → 完成','安排 / 阻断'],rows.map(t=>[
  (interactive?`<button class="row-link" data-wt-task="${esc(t.id)}">${esc(t.id)}</button>`:esc(t.id))+`<small class="block">${esc(t.process+' / '+t.branch+' · '+t.input_state)}</small>`,
  `${t.original_qty} / ${t.completed_qty} / ${t.remaining_qty}`,
  `${esc(t.resource_id||'—')}<br>${esc(t.employee_id||'—')}`,
  `${amount(t.setup_minutes,h)} / ${amount(t.process_minutes,h)}<small class="block">额外恢复 ${amount(t.recovery_minutes,h)} 分钟包含在准备内</small>`,
  t.state==='completed'?`实际完成 ${esc(time(t.actual_finished))}`:`${esc(time(t.started))}<br>${esc(time(t.finished))}`,
  `${esc(taskStates[t.state])}<small class="block">${esc(t.reason)}</small>`
 ]));
}
export function remainderGantt(d,mode,h){
 if(!['resource','worker'].includes(mode))throw Error('占用视角无效');
 if(!d.summary)return '<p class="empty">方案暂停，未生成未来人机占用。</p>';
 const {esc}=h,field=mode==='resource'?'resource_id':'employee_id',tasks=d.tasks.filter(t=>['carried','scheduled'].includes(t.state)),ids=[...new Set(tasks.map(t=>t[field]))].sort();
 if(!ids.length)return '<p class="empty">没有排入的未来任务。</p>';
 const parse=v=>Date.parse(v+'Z'),left=parse(d.resource_study.baseline),right=parse(d.resource_study.horizon_end),width=1440,label=172,plot=width-label-22,height=ids.length*44+70,x=t=>label+(parse(t)-left)/(right-left)*plot;
 let svg=`<svg width="${width}" height="${height}" role="img" aria-label="${mode==='resource'?'设备':'人员'}未来占用；蓝色原人机续作，绿色新排，橙色准备"><rect width="${width}" height="${height}" fill="#fff"/>`;
 for(let i=0;i<=8;i++){const at=left+(right-left)*i/8,xx=label+plot*i/8,text=new Date(at).toISOString().slice(5,16).replace('T',' ');svg+=`<line x1="${xx}" y1="30" x2="${xx}" y2="${height-15}" stroke="#e3e9e7"/><text x="${xx}" y="19" text-anchor="${i===8?'end':'start'}" fill="#4c625e">${text}</text>`;}
 ids.forEach((id,index)=>{const y=42+index*44;svg+=`<text x="8" y="${y+16}" fill="#2b4841">${esc(id)}</text>`;
  for(const t of tasks.filter(t=>t[field]===id)){const xx=x(t.started),w=Math.max(1,x(t.finished)-xx),setup=Math.max(0,x(t.process_started)-xx);svg+=`<g tabindex="0" role="button" data-wt-task="${esc(t.id)}" aria-label="${esc(t.id+' '+taskStates[t.state]+' '+time(t.started)+'至'+time(t.finished))}"><title>${esc(t.id+' · '+t.process+' · '+taskStates[t.state]+'\n'+time(t.started)+' → '+time(t.finished))}</title><rect x="${xx}" y="${y}" width="${w}" height="25" rx="3" fill="${t.state==='carried'?'#336bad':'#31816b'}"/>${setup?`<rect x="${xx}" y="${y}" width="${setup}" height="25" fill="#c18535"/>`:''}</g>`;}
 });
 return '<div class="finite-legend"><span>蓝：原人机续作</span><span>绿：新排剩余加工</span><span>橙：准备（含中断恢复）</span><span>仅显示未来占用；历史完成见明细</span></div><div class="finite-gantt-scroll">'+svg+'</svg></div>';
}
export function materialsMarkup(d,h){
 const {esc,table,panel}=h;
 return panel('剩余用料与预留','逐任务向上取整后的剩余定额 − 声明已投入 = 尚需投入；只在同物料、同单位内汇总。',table(['物料 / 单位','剩余定额','已投入在制品','尚需投入','已预留','池可用量','池未预留量'],d.balances.map(b=>[esc(b.material_id+' / '+b.unit),...['gross_remaining_qty','embedded_qty','required_qty','reserved_qty','usable_qty','remaining_qty'].map(k=>amount(b[k],h))])))+
 panel('独立余料池','可用量 = 已预留 + 未预留；专属线边优先，然后按可用时点与编号。尚未到料或他单专属不能据总量判断齐套。',table(['余料 / 批号 / 位置','物料 / 单位','状态 / 来源 / 专属批次','可用时点','尚未耗用 / 其中不可投入','可用 / 预留 / 剩余'],d.lots.map(l=>[
  esc(l.id)+'<small class="block">'+esc(l.lot+' / '+l.location)+'</small>',esc(l.material_id+' / '+l.unit),esc(l.status+' / '+l.kind)+'<br>'+esc(l.owner_job_id||'共享'),esc(time(l.available_from)),`${esc(l.qty)} / ${esc(l.unavailable_qty)}`,`${esc(l.usable_qty)} / ${esc(l.reserved_qty)} / ${esc(l.remaining_qty)}`])))+
 panel('逐任务用料声明','点击任务核对原报工、完整用料和预留。未预留可能是后序阻断，不能全部解释为缺料。',table(['任务','物料 / 单位','剩余定额 / 已投入 / 尚需投入','预留量 / 状态'],d.demands.map(n=>[
 `<button class="row-link" data-wt-task="${esc(n.task_id)}">${esc(n.task_id)}</button>`,esc(n.material_id+' / '+n.unit),`${esc(n.gross_remaining_qty)} / ${esc(n.embedded_qty)} / ${esc(n.required_qty)}`,`${esc(n.reserved_qty)} / ${{not_required:'无需新增投入',reserved:'已预留',unreserved:'未预留'}[n.state]}`])))+
 panel('预留流水','每笔只占一次余料；失败后序不自动释放已排前序的预留。',table(['任务 / 需求','供给批次','物料 / 单位','预留量 / 时点'],d.reservations.map(r=>[esc(r.task_id)+'<br>'+esc(r.demand_id),esc(r.supply_id),esc(r.material_id+' / '+r.unit),esc(r.qty)+'<br>'+esc(time(r.reserved_at))])));
}
export function decisionMarkup(d,h){
 const {esc,table,panel}=h;
 if(!d)return '<p class="empty">未取得当前派序解释；原报工与用料仍可核对。</p>';
 if(d.version!=='WIP_DISPATCH_EVIDENCE_1')return '<p class="empty">当前派序解释版本尚不受支持；原报工与用料仍可核对。</p>';
 const taskLink=id=>`<button class="row-link" data-wt-task="${esc(id)}">${esc(id)}</button>`;
 const links=ids=>ids.length?ids.map(taskLink).join('、'):'无前占任务';
 if(d.state!=='explained')return panel(d.state==='historical'?'历史完成依据':'派序解释不可用',d.notice,(d.issues||[]).map(i=>`<p>${esc(i)}</p>`).join(''));
 const pairs=table(['资源 / 人员候选','批量 / 资格','派序前尾部与占用任务','准备 / 最早尝试','可行时段','本次选择'],d.pairs.map(p=>[
  `${esc(p.resource_id)} / ${esc(p.employee_id)}<small class="block">${esc(p.option_id)} / ${esc(p.candidate_id)}</small>`,
  `${esc(p.capacity_basis)} ${esc(p.checked_qty)} / 上限 ${esc(p.capacity_qty)}<br>${esc(p.credential_id)} · ${p.credential.eligible?'声明有效':'声明无效'}`,
  `设备 ${esc(time(p.resource_tail))}<br>${links(p.resource_tail_tasks)}<br>人员 ${esc(time(p.worker_tail))}<br>${links(p.worker_tail_tasks)}`,
  `${esc(p.setup_minutes)} 分钟（含恢复 ${esc(p.recovery_minutes)}）<br>${esc(time(p.earliest))}`,
  `${esc(time(p.started))}<br>${esc(time(p.finished))}<details><summary>窗口、不可用时段和资格</summary><p>交集已裁剪到资格有效期；仍须扣除不可用时段并满足尾部限制。</p>${table(['共同窗口开始 → 结束','原资源 / 人员窗口'],p.windows.map(w=>[esc(time(w.started)+' → '+time(w.finished)),esc(w.resource_window_id+' / '+w.worker_window_id)]))}${table(['不可用开始 → 结束','原记录'],p.blocks.map(b=>[esc(time(b.started)+' → '+time(b.finished)),esc(b.id)]))}<p>资格区间 ${esc(time(p.credential.effective_from))} → ${esc(time(p.credential.effective_until))}（右端不含）。${esc(p.credential.reason)}</p><p>上个换型族 ${esc(p.previous_family||'无')} → 本任务 ${esc(p.task_family)}</p></details>`,
  `${p.selected?'<b>本次选中</b>':p.status==='feasible'?'可行，排序未选中':'未进入可行排序'}<small class="block">${esc(p.reasons.join('；'))}</small>${p.rank?'<details><summary>完整排序值</summary>'+esc(p.rank.join(' → '))+'</details>':''}`
 ]));
 return panel('为什么选择这组人机',d.notice,`<p class="source">完整候选组合 ${esc(d.pair_count)} 组；按 ${esc(d.rank_fields.join(' → '))} 依次升序取第一组。</p>`+pairs)+
 panel('轮到本任务前的相关余料','这是预留前余额；全方案最终余量见下方。未来供给按可用时点参与，不等于截止时已在库。',table(['余料 / 物料 / 单位','可用起点 / 专属批次','原可用 / 此任务前余量','供给资格'],d.lots.map(l=>[esc(l.id+' / '+l.material_id+' / '+l.unit),esc(time(l.available_from))+'<br>'+esc(l.owner_job_id||'共享'),esc(l.usable_qty+' / '+l.remaining_before_task),l.eligible?'可参与时点核算':esc(l.reasons.join('；'))])))+
 panel('前序、首个阻断与尾部任务','点击沿同一方案、版本和派序策略核对。',table(['任务','关系','工序 / 结果','完成时点'],d.related_tasks.map(t=>[taskLink(t.id),[d.predecessors.includes(t.id)?'直接前序':'',d.root_tasks.includes(t.id)?'首个阻断':'',d.pairs.some(p=>p.resource_tail_tasks.includes(t.id)||p.worker_tail_tasks.includes(t.id))?'尾部占用':''].filter(Boolean).join(' / '),esc(t.process+' / '+taskStates[t.state]),esc(time(t.finished))])));
}
export function remainderDetail(d,h){
 const {esc,panel,table}=h,r=d.row;
 const fields=Object.entries(d.progress).map(([k,v])=>[esc(k),amount(v,h)]);
 return taskRows([r],h,false)+`<p class="source">${esc(d.notice)}</p>`+decisionMarkup(d.decision,h)+
 panel('原报工与进度声明','报工数量逐工序保留，不相加为整机产量。',d.operation?table(['报工','对象','原开始 → 停止','原人机','投入 / 良品 / 报废 / 返工','原状态'],[[esc(d.operation.id),esc(d.operation.object_type+' / '+d.operation.object_id),esc(time(d.operation.started))+' → '+esc(time(d.operation.finished)),esc(d.operation.resource_id+' / '+d.operation.employee_id),['input_qty','good_qty','scrap_qty','rework_qty'].map(k=>esc(d.operation[k])).join(' / '),esc(d.operation.status)]]):'<p>未开始任务没有原报工。</p>')+
 panel('时点、资格与阻断','',table(['核对项','依据'],[['前序就绪',time(r.dependency_ready)],['物料就绪',time(r.material_ready)],['资格 / 候选资源',r.credential_id+' / '+r.option_id],['直接前序',r.predecessors.join('、')],['首个阻断任务',r.root_tasks.join('、')],['声明依据',d.progress.basis]].map(([k,v])=>[k,esc(v)]))+
 table(['缺料物料 / 单位','任务所需 / 仍可用 / 缺口'],r.shortages.map(s=>[esc(s.material_id+' / '+s.unit),esc(s.required_qty+' / '+s.available_qty+' / '+s.shortage_qty)])))+
 materialsMarkup({balances:[],demands:d.demands,lots:d.lots,reservations:d.reservations},h)+`<details><summary>完整进度声明字段</summary>${table(['字段','原输入'],fields)}</details>`;
}
export function exportPath(key,policy,receipt,format,taskId=null){
 if(!receipt||!['due','priority'].includes(policy)||!['json','csv'].includes(format))throw Error('请先读取当前试排');
 if(taskId!==null&&(typeof taskId!=='string'||!taskId))throw Error('任务编号无效');
 return '/api/wip-trial/'+encodeURIComponent(key)+(taskId===null?'':'/tasks/'+encodeURIComponent(taskId))+'/export?'+new URLSearchParams({policy,receipt,format});
}
export function selectionExportPath(key,policy,receipt,format,filters={}){
 exportPath(key,policy,receipt,format);
 if(Object.keys(filters).some(k=>!['job','state','root'].includes(k)))throw Error('任务筛选字段无效');
 const values=Object.fromEntries(['job','state','root'].map(k=>[k,Object.hasOwn(filters,k)?filters[k]:'']));
 if(Object.values(values).some(v=>typeof v!=='string'||v.length>200)||!['',...Object.keys(taskStates)].includes(values.state))throw Error('任务筛选值无效');
 return '/api/wip-trial/'+encodeURIComponent(key)+'/selection/export?'+new URLSearchParams({policy,receipt,format,...values});
}
export function createWipTrial(h){
 const {api,esc,header,panel,table,modal,toast,go,$,$$,on,isCurrent}=h,reads=createScheduleReadGuard(h);
 async function render(params,token){
  const {alive,attempt,read,modalRead,cancelModal,modalLease}=reads.begin(token),list=await read(()=>api('wip-trial'));if(!list)return;
  if(!list.rows.length){$('#main').innerHTML=header('在制剩余试排','')+'<p class="empty">尚无完整在制方案；导入48号模拟工作簿后可读取。</p>';return;}
  const key=params.get('study')||list.rows[0].id,policy=params.get('policy')||'due',d=await read(()=>api('wip-trial/'+encodeURIComponent(key)+'?'+new URLSearchParams({policy})));if(!d)return;
  const url=(suffix,more={})=>'wip-trial/'+encodeURIComponent(key)+suffix+'?'+new URLSearchParams({policy,receipt:d.receipt,...more}),selected=list.rows.find(x=>x.id===key);
  $('#main').innerHTML=header('在制剩余试排','核对剩余任务能否同时取得物料、设备和人员。','<a href="#wip-readiness">工单进度证据 ↗</a>')+
   `<div class="filterbar"><label>完整方案版本<select id="wt-study">${list.rows.map(s=>`<option value="${esc(s.id)}" ${s.id===key?'selected':''}>${esc(s.id+' · '+s.name+' · v'+s.version+(s.is_latest?'':'（历史版本）'))}</option>`).join('')}</select></label><label>派序策略<select id="wt-policy">${Object.entries(list.policies).map(([k,v])=>`<option value="${k}" ${k===policy?'selected':''}>${esc(v)}</option>`).join('')}</select></label><button id="wt-refresh">重新计算</button><button id="wt-json">完整输入与结果 JSON</button><button id="wt-csv">完整分区 CSV</button><button id="wt-sources">全部来源 · ${d.source_count}</button></div>`+
   `<div class="notice">合成模拟 · 进度截止 ${esc(time(d.study.cutoff))} · v${d.study.version} ${selected?.is_latest?'本系列最高版本':'历史版本，未自动替代新版'}${d.study.supersedes_id?' · 前版 '+esc(d.study.supersedes_id):''}</div><p class="source">${esc(d.notice)}</p>`+
   (d.summary?`<div class="finite-summary">${[['历史完成任务',d.summary.historical_completed_tasks],['原人机续作',d.summary.carried_tasks],['新排剩余任务',d.summary.scheduled_tasks],['未排入任务',d.summary.blocked_tasks],['整单覆盖 / 范围工单',d.summary.covered_jobs+' / '+d.summary.jobs]].map(([a,b])=>`<span>${a} <b>${b}</b></span>`).join('')}</div>`:'<p class="empty">整个方案暂停；未来排程、负载和物料预留未生成。</p>')+
   (d.issues.length?panel('先核对这些依据','',`<ul>${d.issues.map(i=>`<li>${esc(i)}</li>`).join('')}</ul>`):'')+
   (d.summary?panel('整张工单完成时间','工序处理数量不跨工序相加。完整排入才给出工单完成时间。',table(['原工单 / 试排批次','配置 / 工单台数','应完成','本次完成','状态'],d.jobs.map(j=>[esc(d.work_orders.find(w=>w.job_id===j.id)?.work_order_id||'')+'<br>'+esc(j.id),esc(j.product_id)+' / '+j.qty,esc(time(j.due)),esc(time(j.finished)),j.state==='blocked'?'有未排任务':j.state==='late'?'晚于假设交期':'整单已覆盖'])))+
   '<div class="filterbar"><button id="wt-tab-schedule">进度与未来占用</button><button id="wt-tab-material">余料与预留</button></div><div id="wt-body"></div>':'')+
   `<details><summary>原整批方案参考与算法边界</summary><p class="source">${esc(d.parent_reference.notice)} <a href="#joint-schedule?study=${encodeURIComponent(d.parent_reference.id)}">查看原参考</a></p></details>`;
  const canSelection=d.capabilities?.task_selection==='WIP_TASK_SELECTION_1',canTaskExport=d.capabilities?.task_decision==='WIP_DISPATCH_EVIDENCE_1';
  const detail=attempt(async id=>{const v=await modalRead(()=>api(url('/tasks/'+encodeURIComponent(id))));if(!v)return;modal('剩余任务与原始依据',`<div class="filterbar">${canTaskExport&&v.decision?.version==='WIP_DISPATCH_EVIDENCE_1'?'<button id="wt-task-json">本任务解释与完整依据 JSON</button><button id="wt-task-csv">本任务解释与完整依据 CSV</button>':''}<button id="wt-task-sources">全部来源</button></div>`+remainderDetail(v,h));bind();if(canTaskExport&&v.decision?.version==='WIP_DISPATCH_EVIDENCE_1'){on('#wt-task-json','click',attempt(()=>download('json',id)));on('#wt-task-csv','click',attempt(()=>download('csv',id)));}on('#wt-task-sources','click',attempt(()=>evidence()));});
  const bound=new WeakSet();
  function bind(){ $$('[data-wt-task]').forEach(el=>{if(bound.has(el))return;bound.add(el);el.addEventListener('click',()=>detail(el.dataset.wtTask));if(el.tagName?.toLowerCase()==='g')el.addEventListener('keydown',e=>{if(['Enter',' '].includes(e.key)){e.preventDefault();detail(el.dataset.wtTask);}});}); }
  let taskViewGeneration=0;
  function schedule(){
   cancelModal();const taskView=++taskViewGeneration,report=wipBlockerReport(d);let rootPage=1,selectionRevision=0;
   const filters=()=>({job:$('#wt-job').value,state:$('#wt-state').value,root:$('#wt-root').value});
   $('#wt-body').innerHTML='<div id="wt-roots"></div>'+panel('同一试排的设备与人员占用','蓝色续作任务固定原人机；历史完成不占未来产能。','<div class="filterbar"><button id="wt-resource">按设备</button><button id="wt-worker">按人员</button></div><div id="wt-chart">'+remainderGantt(d,'resource',h)+'</div>')+
    panel('逐任务进度与结果','工单、状态和首阻断取交集；只筛任务清单，全方案汇总、甘特、来源和完整导出范围不变。',`<div class="filterbar"><label>原工单 / 批次<select id="wt-job"><option value="">全部</option>${d.jobs.map(j=>`<option value="${esc(j.id)}">${esc((d.work_orders.find(w=>w.job_id===j.id)?.work_order_id||'')+' / '+j.id)}</option>`).join('')}</select></label><label>结果状态<select id="wt-state"><option value="">全部</option>${Object.entries(taskStates).map(([k,v])=>`<option value="${k}">${v}</option>`).join('')}</select></label><label>首阻断<select id="wt-root" ${report.state==='paused'?'disabled':''}><option value="">全部</option>${report.rows.map(r=>`<option value="${esc(r.id)}">${esc(r.id+' / '+r.process)}</option>`).join('')}</select></label><button id="wt-reset">重置明细</button>${canSelection?'<button id="wt-selected-csv">筛选任务 CSV</button><button id="wt-selected-json">筛选与完整依据 JSON</button>':''}</div>${canSelection?'<p class="source">筛选CSV交付当前任务清单；筛选JSON同时保留完整输入，以复算共享竞争。</p>':'<p class="source">当前服务未提供筛选导出，可使用上方完整方案导出。</p>'}<div id="wt-tasks"></div>`);
   function roots(){
    $('#wt-roots').innerHTML=wipBlockerQueue(report,h,{page:rootPage,selected:$('#wt-root').value});bind();
    $$('[data-wt-root-focus]').forEach(el=>el.addEventListener('click',attempt(()=>{$('#wt-job').value='';$('#wt-state').value='blocked';$('#wt-root').value=el.dataset.wtRootFocus;rows();})));
    on('#wt-root-prev','click',attempt(()=>{if(rootPage>1){rootPage--;roots();}}));on('#wt-root-next','click',attempt(()=>{if(rootPage*20<report.rows.length){rootPage++;roots();}}));
   }
   const rows=()=>{selectionRevision++;cancelModal();const found=selectTasks(d,filters(),report);$('#wt-tasks').innerHTML=`<p class="source">当前 ${found.length} / 全方案 ${d.tasks.length} 个任务</p>`+(found.length?taskRows(found,h):'<p class="empty">此明细交集没有任务，不代表全方案没有阻断。</p>');bind();roots();};rows();
   if(canSelection)for(const format of ['csv','json'])on('#wt-selected-'+format,'click',attempt(()=>{const revision=selectionRevision;return download(format,null,{filters:filters(),valid:()=>taskView===taskViewGeneration&&revision===selectionRevision});}));
   for(const mode of ['resource','worker'])on('#wt-'+mode,'click',()=>{$('#wt-chart').innerHTML=remainderGantt(d,mode,h);bind();});
   for(const field of ['job','state','root'])on('#wt-'+field,'change',attempt(()=>{if(field==='root')rootPage=Math.max(1,Math.floor(report.rows.findIndex(r=>r.id===$('#wt-root').value)/20)+1);rows();}));
   on('#wt-reset','click',attempt(()=>{rootPage=1;for(const field of ['job','state','root'])$('#wt-'+field).value='';rows();}));
  }
  if(d.summary){on('#wt-tab-schedule','click',schedule);on('#wt-tab-material','click',()=>{taskViewGeneration++;cancelModal();$('#wt-body').innerHTML=materialsMarkup(d,h);bind();});schedule();}
  on('#wt-study','change',e=>go('wip-trial',{study:e.target.value,policy}));on('#wt-policy','change',e=>go('wip-trial',{study:key,policy:e.target.value}));
  on('#wt-refresh','click',attempt(()=>render(new URLSearchParams({study:key,policy}),token)));
  async function evidence(page=1){const s=await modalRead(()=>api(url('/sources',{page})));if(!s)return;modal('全部 Excel 来源与版本',scheduleSources(s.rows,h)+`<p>第 ${page} 页，共 ${s.total} 条。${s.can_download_original?'管理员可在导入页读取原件。':'来源索引不授予原件下载权限。'}</p><button id="wt-prev" ${page===1?'disabled':''}>上一页</button><button id="wt-next" ${page*s.size>=s.total?'disabled':''}>下一页</button>`);on('#wt-prev','click',attempt(()=>evidence(page-1)));on('#wt-next','click',attempt(()=>evidence(page+1)));}
  on('#wt-sources','click',attempt(()=>evidence()));
  let downloadRequest=0;
  async function download(format,taskId=null,selection=null){
   const request=++downloadRequest,inScope=selection?selection.valid:taskId===null?()=>true:modalLease(),valid=()=>alive()&&request===downloadRequest&&inScope();
   const path=selection?selectionExportPath(key,policy,d.receipt,format,selection.filters):exportPath(key,policy,d.receipt,format,taskId);
   try{const r=await fetch(path,{credentials:'same-origin',cache:'no-store'});if(!valid())return;
    if(!r.ok){const e=await r.json().catch(()=>({error:'文件读取失败'}));if(!valid())return;throw Error(e.error);}
    if(!r.headers.get('Content-Disposition')?.startsWith('attachment;'))throw Error('响应不是结果文件');
    const blob=await r.blob();if(!valid())return;const objectUrl=URL.createObjectURL(blob),a=document.createElement('a');a.href=objectUrl;a.download=(selection?'wip-selected-':'wip-remainder-')+key+(taskId===null?'':'-task-'+taskId)+'.'+format;document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(objectUrl),1000);
   }catch(e){if(valid())throw e;}
  }
  on('#wt-json','click',attempt(()=>download('json')));on('#wt-csv','click',attempt(()=>download('csv')));
 }
 return {render};
}
