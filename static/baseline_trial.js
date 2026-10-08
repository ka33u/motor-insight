import {crewGantt} from './crew_schedule.js';

const labels={scheduled:'按假设已排',late:'晚于内部目标',blocked:'未排入',paused:'资料暂停'};
const local=v=>typeof v==='string'&&v?v.replace('T',' '):'未形成时间';
const minutes=v=>typeof v==='number'&&Number.isFinite(v)?v.toLocaleString('zh-CN',{maximumFractionDigits:2}):'不可比较';
const amount=(v,esc)=>v==null?'未计算':esc(v);
const validTrial=d=>d.state==='trial'&&d.trial?.state==='trial'&&d.trial.summary;
export const TRIAL_BOUNDARY='按声明冻结用料集合试算，历史完整性/批准未核实，无正式承诺。';
const objectLabels={order_lines:'订单明细',work_orders:'生产工单',allocations:'工单订单分配',products:'产品配置',bom:'BOM 用料行',routes:'工艺路线',materials:'物料档案'};
const commonFields={id:'来源编号',order_id:'订单号',order_line_id:'订单行号',work_order_id:'生产工单号',product_id:'配置编码',material_id:'物料编码',original_due:'原承诺日期',due:'现承诺日期',planned_qty:'工单计划台数',scrap_allowance:'损耗定额',assembly_level:'用料分支',process:'工序名称',branch:'工艺分支',mandatory:'必经工序',unit:'计量单位'};
const objectFields={order_lines:{qty:'订单台数'},work_orders:{bom_version:'工单 BOM 版本',route_version:'工单路线版本',status:'工单状态'},allocations:{qty:'分配台数',effective:'分配生效日期'},products:{bom_version:'配置当前 BOM 版本',route_version:'配置当前路线版本'},bom:{qty:'单位用量',version:'BOM 版本',effective:'BOM 生效日期'},routes:{version:'路线版本'}};

export function baselineTrialChanges(changes,{esc,table}){
 if(!changes.length)return '<p>本次读取未发现已核对字段变化；不证明历史集合完整或已经批准。</p>';
 const value=v=>v==null?'缺失':typeof v==='boolean'?(v?'是':'否'):v===''?'空文本':esc(v);
 const rows=changes.flatMap(c=>{
  const frozen=c.frozen||{},current=c.current||{},changed=c.fields||[];
  // Retain all projected fields, including unchanged identity and absent values.
  const fields=[...new Set([...Object.keys(frozen),...Object.keys(current),...changed])];
  return fields.map(field=>[`${esc(c.link_id)}<small class="block">${esc(objectLabels[c.dataset]||c.dataset)} / ${esc(c.key)}</small>`,`${esc(objectFields[c.dataset]?.[field]||commonFields[field]||field)}${changed.includes(field)?'<small class="block">已变化</small>':''}`,value(frozen[field]),value(current[field])]);
 });
 return '<p class="source">逐行保留发生差异对象的全部已核对字段；变化字段明确标记，缺失不补零。</p>'+table(['基线映射 / 业务对象','业务字段','冻结值','当前值'],rows);
}

export function trialTaskRows(rows,{job='',state='',page=1,size=40}={}){
 const selected=rows.filter(r=>(!job||r.job_id===job)&&(!state||r.state===state));
 return {rows:selected.slice((page-1)*size,page*size),total:selected.length,page,size};
}

export function baselineTrialOverview(d,{esc,panel,table}){
 const trial=validTrial(d)?d.trial:null,s=trial?.summary;
 return `<div class="baseline-trial-boundary" role="note"><b>${TRIAL_BOUNDARY}</b><span>同产品的不同批次可使用不同冻结版本；整案共享当前设备、人员和供给。派生需求是计算输入，不是新增业务事实。</span></div>`+
  `<div class="baseline-trial-status ${trial?'':'paused'}"><b>${trial?'已形成条件试排':'资料暂停，未形成试排'}</b><span>${trial?'排入结果仅在声明的假设范围内成立。':'暂停不表示零需求、零缺料或已经完成。'}</span></div>`+
  (s?`<div class="finite-summary"><span>假设批次 <b>${esc(s.jobs)}</b> / ${esc(s.qty)} 台</span><span>完整排入 <b>${esc(s.complete_jobs)}</b> 批</span><span>未排入 <b>${esc(s.blocked_jobs)}</b> 批</span><span>已排任务 <b>${esc(s.scheduled_tasks)} / ${esc(s.tasks)}</b></span><span>整批需求预留 <b>${esc(s.reserved_demands)} / ${esc(s.demands)}</b></span></div>`:'<p class="empty">排程、占用、物料预留及完成差值未计算；可查看阻断依据和导出输入。</p>')+
  ((d.issues||[]).length?panel('必须先解决的资料问题','',table(['问题代码 / 对象','字段','原因'],d.issues.map(i=>[`${esc(i.code)}<small class="block">${esc(i.dataset)} / ${esc(i.key)}</small>`,esc(i.field),esc(i.message)]))):'')+
  ((d.warnings||[]).length?panel('条件试算仍需披露的差异','',`<ul>${d.warnings.map(w=>`<li>${esc(w)}</li>`).join('')}</ul>`):'')+
  panel('原基线订单覆盖 · 不由批次完成推导整单交付','',`<p class="source">以下为基线核对的覆盖范围，不合计当前与冻结两列台数。加工完成不包含质量放行、运输和签收。</p>`+((d.coverage||[]).length?table(['订单行 / 配置','基线订单 / 登记发货','基线未发需求','本方案安排 / 未覆盖','超排台数'],d.coverage.map(o=>[`${esc(o.id)}<small class="block">${esc(o.product_id)}</small>`,`${amount(o.order_qty,esc)} / ${amount(o.registered_shipped_qty,esc)}`,amount(o.baseline_open_qty,esc),`${amount(o.planned_qty,esc)} / ${amount(o.uncovered_qty,esc)}`,amount(o.overplanned_qty,esc)])):'<p class="empty">覆盖未计算；不表示订单没有需求。</p>'));
}

export function baselineTrialComparison(d,{esc,panel,table}){
 const c=d.comparison||{};
 if(!validTrial(d)||!c.available)return panel('当前 BOM 与冻结 BOM · 同一派序','',`<p class="source">${esc(c.notice||'至少一侧没有有效试排，差值不计算。')}</p><p class="empty">当前与冻结结果不可比较；未形成时间或数量差值。</p>`);
 return panel('当前 BOM 与冻结 BOM · 批次完成对照','',`<p class="source">${esc(c.notice)} 差值为冻结减当前，完成差值为负表示冻结假设下更早。只有两边均完成才计算时间差；不作为因果归因或最优性证明。</p>`+table(['批次 / 台数','当前 BOM：完成 / 状态','冻结 BOM：完成 / 状态','冻结减当前（分钟）'],(c.jobs||[]).map(j=>[`${esc(j.id)} / ${esc(j.qty)} 台`,`${esc(local(j.current_finished))}<small class="block">${esc(labels[j.current_state]||j.current_state)}</small>`,`${esc(local(j.frozen_finished))}<small class="block">${esc(labels[j.frozen_state]||j.frozen_state)}</small>`,j.current_finished&&j.frozen_finished?minutes(j.delta_minutes):'不可比较'])))+
  panel('整批需求差异 · 每种物料每种单位分别比较','',table(['物料 / 单位','当前 BOM 需求','冻结 BOM 需求','冻结减当前'],(c.materials||[]).map(m=>[`${esc(m.material_id)} / ${esc(m.unit)}`,amount(m.current_required_qty,esc),amount(m.frozen_required_qty,esc),m.delta_qty==null?'不可比较':esc(m.delta_qty)])));
}

function sourceTable(rows,{esc,table}){
 return table(['对象','Excel / 表 / 行','当前版本'],(rows||[]).map(s=>[`${esc(s.dataset)}<small class="block">${esc(s.key)}</small>`,s.missing?'来源缺失':`${esc(s.filename)}<br>${esc(s.sheet)} · 第 ${esc(s.row)} 行`,s.missing?'缺失':`v${esc(s.revision)} · 源行 ${esc(s.source_row_id)}`]));
}

export function baselineTrialTask(d,{esc,table}){
 const t=d.task;
 return `<p>${esc(d.notice)}</p><p><b>${esc(t.id)}</b> · ${esc(t.process)} / ${esc(t.branch)}</p>`+
  table(['任务依据与结果','冻结 BOM 假设'],[
   ['安排状态',esc(labels[t.state]||t.state)],['设备 / 人员',`${esc(t.resource_id||'未安排')} / ${esc(t.employee_id||'未安排')}`],
   ['准备开始 / 加工开始',`${esc(local(t.started))} / ${esc(local(t.process_started))}`],['完成',esc(local(t.finished))],
   ['资格 / 人员窗口',`${esc(t.credential_id||'未安排')} / ${esc(t.worker_window_id||'未安排')}`],
   ['共同等待 / 物料就绪等待分钟',`${minutes(t.wait_minutes)} / ${minutes(t.material_readiness_delay_minutes)}`],
   ['阻断原因',esc(t.reason||'无阻断')],['首个阻断任务',esc((t.root_tasks||[]).join('、')||'无')]])+
  '<h3>冻结整批需求与触发任务</h3>'+table(['需求 / 批次','冻结 BOM / 版本 / 工序','物料 / 单位','应需 / 已预留','触发任务 / 时点'],(d.demands||[]).map(n=>[`${esc(n.id)}<small class="block">${esc(n.job_id)}</small>`,`${esc(n.source_bom_id||n.bom_id)} / ${esc(n.bom_version)}<small class="block">${esc(n.route_id)}</small>`,`${esc(n.material_id)} / ${esc(n.unit)}`,`${amount(n.required_qty,esc)} / ${amount(n.reserved_qty,esc)}`,n.reservation?`${esc(n.reservation.task_id)} / ${esc(local(n.reservation.reserved_at))}`:'未预留']))+
  '<h3>共享供给预留</h3>'+table(['需求 / 供给','预留量 / 单位','触发任务 / 可用起点 / 预留时点'],(d.reservations||[]).map(r=>[`${esc(r.demand_id)} / ${esc(r.supply_id)}`,`${amount(r.qty,esc)} / ${esc(r.unit)}`,`${esc(r.task_id)}<br>${esc(local(r.available_from))}<br>${esc(local(r.reserved_at))}`]))+
  '<h3>任务及整案共享来源</h3>'+sourceTable(d.sources,{esc,table});
}

export function createBaselineTrialWorkspace(h){
 const {api,esc,header,panel,table,modal,toast,go,$,$$,on,isCurrent,getModalRevision}=h;
 let serial=0,modalRequest=0;
 on('#detail','close',()=>{modalRequest++});
 const cancel=()=>{serial++;modalRequest++};
 async function render(params,token){
  const id=++serial,alive=()=>id===serial&&isCurrent(token);
  let list,d;
  const policy=params.get('policy')||'due';
  if(!['due','priority'].includes(policy))throw Error('试排策略无效');
  try{list=await api('order-baselines')}catch(e){if(alive())throw e;return}
  if(!alive())return;
  if(!list.rows.length){$('#main').innerHTML=header('基线 BOM 假设试排','')+'<p class="empty">没有已导入的订单 BOM 基线。</p>';return}
  const key=params.get('study')||list.rows[0].id,base='baseline-trial/'+encodeURIComponent(key);
  const post=(suffix,body={})=>api(base+suffix,{method:'POST',body:{policy,...body}});
  try{d=await post('',params.get('receipt')?{receipt:params.get('receipt')}:{})}catch(e){if(alive())throw e;return}
  if(!alive())return;
  const attempt=fn=>async(...args)=>{if(!alive())return;try{await fn(...args)}catch(e){if(alive())toast(e.message)}};
  const trial=validTrial(d)?d.trial:null;
  $('#main').innerHTML='<div class="baseline-trial-workspace">'+header('基线 BOM 假设试排','逐批使用声明的冻结用料，整案共享当前人机与供给；不改变原基线核对或当前 BOM 试排。','<button id="baseline-trial-return">返回订单与 BOM 基线核对</button>')+
   `<div class="filterbar"><label>冻结基线<select id="baseline-trial-study">${list.rows.map(s=>`<option value="${esc(s.id)}" ${s.id===key?'selected':''}>${esc(s.id+' · '+s.name)}</option>`).join('')}</select></label><label>共同派序<select id="baseline-trial-policy">${Object.entries(list.policies||{due:'应完成时间优先',priority:'批次优先级优先'}).map(([p,n])=>`<option value="${esc(p)}" ${p===policy?'selected':''}>${esc(n)}</option>`).join('')}</select></label><button id="baseline-trial-refresh">重新读取</button><button id="baseline-trial-sources">全部来源 · ${esc(d.source_count)}</button><button id="baseline-trial-json">完整假设 JSON</button><button id="baseline-trial-csv">完整分区 CSV</button></div>`+
   `<p class="source">${esc(d.study.id)} · ${esc(d.study.name)} · 第 ${esc(d.study.version)} 版<br>资料截止 ${esc(local(d.cutoff))}<br>${esc(d.notice)}</p>`+
   baselineTrialOverview(d,h)+baselineTrialComparison(d,h)+
   (trial?panel('冻结假设下的全部批次','',table(['批次 / 配置','台数 / 内部目标','完成 / 状态','已排任务 / 全部任务'],trial.jobs.map(j=>[`${esc(j.id)}<small class="block">${esc(j.product_id)}</small>`,`${esc(j.qty)} 台 / ${esc(local(j.due))}`,`${esc(local(j.finished))}<small class="block">${esc(labels[j.state]||j.state)}</small>`,`${esc(j.scheduled_count)} / ${esc(j.task_count)}`])))+
    '<div class="filterbar"><button id="baseline-trial-schedule">设备、人员与任务</button><button id="baseline-trial-material">物料需求与余额</button></div><div id="baseline-trial-body"></div>':'')+
   panel('冻结快照与当前字段差异','',baselineTrialChanges(d.changes||[],h))+'</div>';
  on('#baseline-trial-return','click',()=>go('order-baselines',{study:key,policy}));
  on('#baseline-trial-study','change',e=>go('order-baselines',{view:'trial',study:e.target.value,policy}));
  on('#baseline-trial-policy','change',e=>go('order-baselines',{view:'trial',study:key,policy:e.target.value}));
  on('#baseline-trial-refresh','click',async()=>{if(!alive())return;const fresh=new URLSearchParams(params);fresh.delete('receipt');try{await render(fresh,token)}catch(e){if(isCurrent(token))toast(e.message)}});
  async function readModal(suffix,body){
   const request=++modalRequest,revision=getModalRevision(),current=()=>alive()&&request===modalRequest&&revision===getModalRevision();
   try{const value=await post(suffix,{receipt:d.receipt,...body});return current()?value:null}catch(e){if(current())throw e;return null}
  }
  const detail=attempt(async taskId=>{const p=await readModal('/tasks/'+encodeURIComponent(taskId));if(p)modal('冻结 BOM 任务与共享预留依据',baselineTrialTask(p,h))});
  const bindTasks=()=>$$('[data-baseline-trial-task]').forEach(el=>el.addEventListener('click',()=>detail(el.dataset.baselineTrialTask)));
  function schedule(){
   if(!alive())return;modalRequest++;
   $('#baseline-trial-body').innerHTML=panel('同一排程 · 设备与人员占用','',`<div class="filterbar"><button id="baseline-trial-device">按设备</button><button id="baseline-trial-worker">按人员</button></div><div id="baseline-trial-chart">${crewGantt(trial)}</div>`)+
    panel('任务明细 · 清单筛选不改变整案汇总','',`<div class="filterbar"><label>批次<select id="baseline-trial-job"><option value="">全部批次</option>${trial.jobs.map(j=>`<option value="${esc(j.id)}">${esc(j.id)}</option>`).join('')}</select></label><label>任务状态<select id="baseline-trial-state"><option value="">全部</option><option value="blocked">未排入</option><option value="scheduled">已排入</option></select></label></div><div id="baseline-trial-tasks"></div><div class="toolbar"><button id="baseline-trial-prev">上一页</button><span id="baseline-trial-page"></span><button id="baseline-trial-next">下一页</button></div>`);
   let page=1;
   function draw(){const selected=trialTaskRows(trial.tasks,{job:$('#baseline-trial-job').value,state:$('#baseline-trial-state').value,page});$('#baseline-trial-tasks').innerHTML=table(['任务 / 工序 / 批次','设备 / 人员','准备开始 / 完成','状态 / 阻断原因','首个阻断 / 新预留需求'],selected.rows.map(t=>[`<button class="row-link" data-baseline-trial-task="${esc(t.id)}">${esc(t.id)}</button><small class="block">${esc(t.process)} / ${esc(t.branch)}<br>${esc(t.job_id)}</small>`,`${esc(t.resource_id||'未安排')} / ${esc(t.employee_id||'未安排')}`,`${esc(local(t.started))}<br>${esc(local(t.finished))}`,`${esc(labels[t.state]||t.state)}<small class="block">${esc(t.reason)}</small>`,`${esc((t.root_tasks||[]).join('、')||'无')}<small class="block">${esc((t.new_reservation_ids||[]).join('、')||'本任务未新增')}</small>`]));$('#baseline-trial-page').textContent=`${page} / ${Math.max(1,Math.ceil(selected.total/40))} 页 · 当前 ${selected.total} 项 / 全案 ${trial.tasks.length} 项`;$('#baseline-trial-prev').disabled=page===1;$('#baseline-trial-next').disabled=page*40>=selected.total;bindTasks()}
   on('#baseline-trial-job','change',()=>{page=1;draw()});on('#baseline-trial-state','change',()=>{page=1;draw()});on('#baseline-trial-prev','click',()=>{page--;draw()});on('#baseline-trial-next','click',()=>{page++;draw()});draw();
   on('#baseline-trial-device','click',()=>{$('#baseline-trial-chart').innerHTML=crewGantt(trial,'resource')});on('#baseline-trial-worker','click',()=>{$('#baseline-trial-chart').innerHTML=crewGantt(trial,'worker')});
   on('#baseline-trial-chart','click',e=>{const el=e.target.closest('[data-finite-task]');if(el)detail(el.dataset.finiteTask)});
   on('#baseline-trial-chart','keydown',e=>{const el=e.target.closest('[data-finite-task]');if(el&&['Enter',' '].includes(e.key)){e.preventDefault();detail(el.dataset.finiteTask)}});
  }
  function material(){
   if(!alive())return;modalRequest++;
   $('#baseline-trial-body').innerHTML=panel('同物料、同单位的整案余额','',`<p class="source">kg、件等单位不合计。范围内可用不代表按时齐套；总剩余包含范围外到料，未预留也可能因为人机受阻。</p>`+table(['物料 / 单位','冻结需求','范围内可用 / 总量缺口','已预留','总排除 / 总剩余'],trial.balances.map(b=>[`${esc(b.material_id)} · ${esc(b.material_name)} / ${esc(b.unit)}`,amount(b.required_qty,esc),`${amount(b.horizon_usable_qty,esc)} / ${amount(b.initial_supply_gap_qty,esc)}`,amount(b.reserved_qty,esc),`${amount(b.total_excluded_qty,esc)} / ${amount(b.total_remaining_qty,esc)}`])))+
    panel('逐批冻结需求 · 不按产品合并版本','',table(['需求 / 批次','原 BOM / 冻结版本 / 工序','物料 / 单位','单耗 × (1+损耗) / 步长','应需 / 已预留','触发任务 / 时点'],trial.demands.map(n=>[`${esc(n.id)}<small class="block">${esc(n.job_id)}</small>`,`${esc(n.source_bom_id||n.bom_id)} / ${esc(n.bom_version)}<small class="block">${esc(n.route_id)}</small>`,`${esc(n.material_id)} / ${esc(n.unit)}`,`${amount(n.bom_qty,esc)} × (1+${amount(n.scrap_allowance,esc)})<small class="block">步长 ${amount(n.quantum,esc)}</small>`,`${amount(n.required_qty,esc)} / ${amount(n.reserved_qty,esc)}`,n.reservation?`<button class="row-link" data-baseline-trial-task="${esc(n.reservation.task_id)}">${esc(n.reservation.task_id)}</button><small class="block">${esc(local(n.reservation.reserved_at))}</small>`:'未预留；结合任务阻断核查'])))+
    panel('共享供给批次 · 可用 = 预留 + 剩余','',table(['供给 / 模拟批号','物料 / 单位','可用起点','账面 / 排除','可用 / 预留 / 剩余','状态 / 类型'],trial.lots.map(l=>[`${esc(l.id)}<small class="block">${esc(l.lot)}</small>`,`${esc(l.material_id)} / ${esc(l.unit)}`,esc(local(l.available_from)),`${amount(l.qty,esc)} / ${amount(l.excluded_qty,esc)}`,`${amount(l.usable_qty,esc)} / ${amount(l.reserved_qty,esc)} / ${amount(l.remaining_qty,esc)}`,`${esc(l.status)} / ${esc(l.kind)}`])))+
    panel('FIFO 预留流水','',table(['需求 / 供给','触发任务','物料 / 单位','预留量','可用起点 / 预留时点'],trial.reservations.map(r=>[`${esc(r.demand_id)} / ${esc(r.supply_id)}`,`<button class="row-link" data-baseline-trial-task="${esc(r.task_id)}">${esc(r.task_id)}</button>`,`${esc(r.material_id)} / ${esc(r.unit)}`,amount(r.qty,esc),`${esc(local(r.available_from))}<br>${esc(local(r.reserved_at))}`])));bindTasks();
  }
  if(trial){on('#baseline-trial-schedule','click',schedule);on('#baseline-trial-material','click',material);schedule()}
  async function evidence(page=1){const s=await readModal('/sources',{page});if(!s)return;const size=s.size||40;modal('冻结依据与整案共享来源',sourceTable(s.rows,h)+`<p>第 ${esc(s.page||page)} 页，共 ${esc(s.total)} 条。来源索引不授予原件下载权限。</p><button id="baseline-trial-source-prev" ${page===1?'disabled':''}>上一页</button><button id="baseline-trial-source-next" ${page*size>=s.total?'disabled':''}>下一页</button>`);on('#baseline-trial-source-prev','click',attempt(()=>evidence(page-1)));on('#baseline-trial-source-next','click',attempt(()=>evidence(page+1)))}
  on('#baseline-trial-sources','click',attempt(()=>evidence()));
  let downloading=false;
  async function download(format){if(downloading)return;downloading=true;try{const file=await post('/export',{receipt:d.receipt,format});if(!alive())return;const blob=new Blob([file.text],{type:file.mime+';charset=utf-8'}),url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download=file.filename;document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),1000)}finally{downloading=false}}
  on('#baseline-trial-json','click',attempt(()=>download('json')));on('#baseline-trial-csv','click',attempt(()=>download('csv')));
 }
 return {render,cancel};
}
