const local=v=>v?.replace('T',' ')||'未形成时间';
const numeric=v=>typeof v==='number'&&Number.isFinite(v)?v.toLocaleString('zh-CN',{maximumFractionDigits:2}):'未计算';
export const canOrderBaseline=role=>['admin','analyst','operations'].includes(role);
export function exportPath(key,policy,receipt,format){
 if(!receipt||!['due','priority'].includes(policy)||!['csv','json'].includes(format))throw Error('请先读取当前基线核对');
 return '/api/order-baselines/'+encodeURIComponent(key)+'/export?'+new URLSearchParams({policy,receipt,format});
}
export function baselineOverview(d,{esc,table,panel}){
 const s=d.summary,label=d.state==='aligned'?'基线资料对齐':d.state==='review'?'需要重新核对':'基线资料暂停';
 return `<div class="baseline-state ${d.state==='aligned'?'':d.state==='review'?'review':'paused'}"><b>${label}</b><span>资料对齐不等于批准生产或客户订单完成。</span></div>`+
  (s?`<div class="finite-summary"><span>订单基线 <b>${s.order_qty}</b> 台 / ${s.order_lines} 行</span><span>本方案安排 <b>${s.planned_qty}</b> 台</span><span>尚未覆盖 <b>${s.uncovered_qty}</b> 台</span><span>全量覆盖订单行 <b>${s.fully_covered_lines} / ${s.order_lines}</b></span><span>客户交期后完成 <b>${s.scheduled_jobs?`${s.customer_late_jobs} / ${s.scheduled_jobs}`:'无完成时点'}</b><small>仅已形成完成时点的批次</small></span></div>`:'<div class="empty">基线完整性尚未通过，覆盖、用料与交期不计算。</div>')+
  (d.issues.length?panel('先修正基线资料',`<ul>${d.issues.map(v=>`<li>${esc(v)}</li>`).join('')}</ul>`):'')+
  (d.warnings.length?panel('需要业务复核的差异',`<ul>${d.warnings.map(v=>`<li>${esc(v)}</li>`).join('')}</ul>`):'')+
  panel('订单覆盖 · 批次完成不能代替整单完成',table(['订单行 / 配置','基线订单 / 登记发货','基线未发需求','本方案安排 / 未覆盖','覆盖范围','客户现承诺 / 映射批次完成','整单覆盖后的加工完成'],d.orders.map(o=>{
   const percent=o.coverage_percent==null?0:Math.max(0,Math.min(100,o.coverage_percent));
   return [`${esc(o.id)}<small class="block">${esc(o.product_id)}</small>`,`${o.order_qty} / ${o.registered_shipped_qty}`,o.baseline_open_qty,`${o.planned_qty} / ${o.uncovered_qty}`,`<div class="baseline-coverage" aria-label="登记需求覆盖 ${esc(numeric(o.coverage_percent))}%"><i style="width:${percent}%"></i></div><small>${numeric(o.coverage_percent)}${o.coverage_percent==null?'':'%'}${o.overplanned_qty?` · 超排 ${o.overplanned_qty} 台`:''}</small>`,`${esc(o.due)}<br>${esc(local(o.mapped_jobs_finish))}`,o.order_finish?esc(local(o.order_finish)):d.state==='review'?'基线待重核，不确认整单参考完工':'未形成；可能尚未全量覆盖或存在未排批次'];
  })))+'<p class="source">客户日期按当日23:59:59比较加工完成，不包含检测放行、运输或签收；不能作为OTIF。登记发货按模拟基线时点取数，历史资料补录会提示重新读取。</p>';
}
export function createOrderBaselineWorkspace(h){
 const {api,esc,header,panel,table,modal,toast,go,$,$$,on,isCurrent,getModalRevision}=h;let serial=0;
 const attempt=fn=>async(...a)=>{try{await fn(...a)}catch(e){toast(e.message)}};
 const sources=rows=>table(['对象','Excel / 表 / 行','当前版本'],rows.map(s=>[`${esc(s.dataset)}<small class="block">${esc(s.key)}</small>`,s.missing?'来源缺失':`${esc(s.filename)}<br>${esc(s.sheet)} · 第 ${s.row} 行`,s.missing?'未计算':`v${s.revision} · 源行 ${s.source_row_id}`]));
 async function render(params,token){
  const list=await api('order-baselines');if(!isCurrent(token))return;
  if(!list.rows.length){$('#main').innerHTML=header('订单与BOM基线','把试排批次放回订单、工单和版本化用料依据中核对。')+'<div class="empty">导入40号模拟工作簿后可读取基线。</div>';return}
  const key=params.get('study')||list.rows[0].id,policy=params.get('policy')||'due',q=new URLSearchParams({policy});if(params.get('receipt'))q.set('receipt',params.get('receipt'));
  const d=await api('order-baselines/'+encodeURIComponent(key)+'?'+q);if(!isCurrent(token))return;
  const current=++serial,alive=()=>isCurrent(token)&&serial===current,base='order-baselines/'+encodeURIComponent(key),url=(suffix,extra={})=>base+suffix+'?'+new URLSearchParams({policy,receipt:d.receipt,...extra});
  $('#main').innerHTML=header('订单与BOM基线','先看订单是否覆盖，再看批次能否完成；基线用量与当前资料分别保留。',`<a href="#joint-schedule?study=${encodeURIComponent(d.joint_study.id)}&policy=${policy}">重新读取物料人机试排 ↗</a>`)+
   `<div class="filterbar"><label>基线<select id="baseline-study">${list.rows.map(s=>`<option value="${esc(s.id)}" ${s.id===key?'selected':''}>${esc(s.id+' · '+s.name)}</option>`).join('')}</select></label><label>试排策略<select id="baseline-policy">${Object.entries(list.policies).map(([v,n])=>`<option value="${v}" ${v===policy?'selected':''}>${esc(n)}</option>`).join('')}</select></label><button id="baseline-csv">基线 CSV</button><button id="baseline-json">完整假设 JSON</button><button id="baseline-sources">全部来源 · ${d.source_count}</button></div>`+
   `<div class="source">${esc(d.study.series)} · 第 ${d.study.version} 版 · 模拟基线 ${esc(local(d.study.baseline_at))}<br>${esc(d.study.basis)}<br>${esc(d.notice)}</div>`+
   baselineOverview(d,h)+
   panel('批次如何映射到订单与工单',table(['基线映射 / 试排批次','订单行 / 工单 / 分配','安排台数 / BOM / 路线','内部目标 / 客户交期','批次完成 / 客户交期后分钟','当前试排 / 资料状态'],d.links.map(l=>[`<button class="row-link" data-baseline-link="${esc(l.id)}">${esc(l.id)}</button><small class="block">${esc(l.job_id)}</small>`,`${esc(l.order_line_id)}<br>${esc(l.work_order_id)}<br>${esc(l.allocation_id)}`,`${l.plan_qty} 台<br>${esc(l.bom_version)} / ${esc(l.route_version)}`,`${esc(local(l.internal_due))}<br>${esc(l.due)}`,`${esc(local(l.finished))}<br>${numeric(l.customer_late_minutes)}`,`${esc(l.trial_state)}<br>${l.source_changed?'来源字段需重核':'映射字段一致'}`])))+
   panel('基线BOM与当前试排用料',`<p class="source">以下需求使用基线复制的单耗、损耗和步长计算。当前BOM改版不会替换本表；资料变化或试排不一致须重核。</p>`+table(['快照 / BOM行','订单行 / 工序','物料 / 基线单位','单耗 × (1+损耗) / 步长','批量 / 基线需求','当前试排需求 / 核对'],d.bom.map(b=>[`${esc(b.id)}<small class="block">${esc(b.source_bom_id)}</small>`,`${esc(b.order_line_id)}<br>${esc(b.process+' · '+b.route_id)}`,`${esc(b.material_id)} / ${esc(b.unit)}`,`${esc(b.unit_qty)} × (1+${esc(b.scrap_allowance)})<br>步长 ${esc(b.quantum)}`,`${b.plan_qty} 台 / ${esc(b.required_qty)} ${esc(b.unit)}`,`${b.trial_demands.map(x=>`${esc(x.qty)} ${esc(x.unit)}`).join('；')||'缺少匹配需求'}<br>${b.matches_trial?'相符':'待核对'}`])))+
   panel('快照与当前字段差异',d.changes.length?table(['映射 / 来源对象','变化字段','基线字段','当前字段'],d.changes.map(c=>[`${esc(c.link_id)}<br>${esc(c.dataset+'/'+c.key)}`,esc(c.fields.join('、')),`<pre class="baseline-json">${esc(JSON.stringify(c.frozen,null,2))}</pre>`,`<pre class="baseline-json">${esc(JSON.stringify(c.current,null,2))}</pre>`])):'<p>本次读取未发现已核对字段差异；不证明现场资料完整或获得生产批准。</p>')+
   panel('版本关系',table(['版本','基线','模拟截止','前版'],d.versions.map(v=>[v.version,`<a href="#order-baselines?study=${encodeURIComponent(v.id)}&policy=${policy}">${esc(v.id+' · '+v.name)}</a>`,esc(local(v.baseline_at)),esc(v.supersedes_id||'首版')]))+'<p class="source">这里只核对版本关系；查看前版内容请打开对应基线。修订应使用新编号和版本，不冒充原始文件。</p>');
  on('#baseline-study','change',e=>go('order-baselines',{study:e.target.value,policy}));on('#baseline-policy','change',e=>go('order-baselines',{study:key,policy:e.target.value}));
  const detail=attempt(async id=>{const revision=getModalRevision(),p=await api(url('/links/'+encodeURIComponent(id)));if(!alive()||revision!==getModalRevision())return;modal('订单、工单和BOM快照依据',`<p>${esc(p.notice)}</p><pre class="code-block">${esc(JSON.stringify({映射:p.row,用料:p.bom,差异:p.changes},null,2))}</pre>`+sources(p.sources))});
  $$('[data-baseline-link]').forEach(el=>el.addEventListener('click',()=>detail(el.dataset.baselineLink)));
  async function evidence(page=1){const revision=getModalRevision(),s=await api(url('/sources',{page}));if(!alive()||revision!==getModalRevision())return;modal('基线及完整试排来源',sources(s.rows)+`<p>第 ${page} 页，共 ${s.total} 条。${s.can_download_original?'管理员可在导入页读取归档原件。':'来源索引不授予原件权限。'}</p><button id="baseline-prev" ${page===1?'disabled':''}>上一页</button> <button id="baseline-next" ${page*40>=s.total?'disabled':''}>下一页</button>`);on('#baseline-prev','click',attempt(()=>evidence(page-1)));on('#baseline-next','click',attempt(()=>evidence(page+1)))}
  on('#baseline-sources','click',attempt(()=>evidence()));
  async function download(format){const r=await fetch(exportPath(key,policy,d.receipt,format),{credentials:'same-origin',cache:'no-store'});if(!alive())return;if(!r.ok){const e=await r.json().catch(()=>({error:'基线导出失败'}));throw Error(e.error||'基线导出失败')}if(!r.headers.get('Content-Disposition')?.startsWith('attachment;'))throw Error('响应不是结果文件');const blob=await r.blob();if(!alive())return;const path=URL.createObjectURL(blob),a=document.createElement('a');a.href=path;a.download='order-baseline-'+key+'.'+format;document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(path),1000)}
  on('#baseline-csv','click',attempt(()=>download('csv')));on('#baseline-json','click',attempt(()=>download('json')));
 }
 return {render};
}
