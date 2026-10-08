import {createBaselineTrialWorkspace,baselineTrialChanges} from './baseline_trial.js';
import {baselineTime as local,baselineNumber as numeric,baselineSelection,baselineBom,baselineLinks,baselineSources,baselineLinkDetail} from './order_baseline_reading.js';
export const canOrderBaseline=role=>['admin','analyst','operations'].includes(role);
export function exportPath(key,policy,receipt,format){
 if(!receipt||!['due','priority'].includes(policy)||!['csv','json'].includes(format))throw Error('请先读取当前基线核对');
 return '/api/order-baselines/'+encodeURIComponent(key)+'/export?'+new URLSearchParams({policy,receipt,format});
}
export function baselineOverview(d,{esc,table,panel},{order=''}={}){
 const s=d.summary,label=d.state==='aligned'?'基线资料对齐':d.state==='review'?'需要重新核对':'基线资料暂停';
 return `<div class="baseline-state ${d.state==='aligned'?'':d.state==='review'?'review':'paused'}"><b>${label}</b><span>资料对齐不等于批准生产或客户订单完成。</span></div>`+
  (s?`<div class="finite-summary" aria-label="完整基线汇总"><span>订单基线 <b>${esc(s.order_qty)}</b> 台 / ${esc(s.order_lines)} 行</span><span>本方案安排 <b>${esc(s.planned_qty)}</b> 台</span><span>尚未覆盖 <b>${esc(s.uncovered_qty)}</b> 台</span><span>全量覆盖订单行 <b>${esc(s.fully_covered_lines)} / ${esc(s.order_lines)}</b></span><span>客户交期后完成 <b>${s.scheduled_jobs?`${esc(s.customer_late_jobs)} / ${esc(s.scheduled_jobs)}`:'无完成时点'}</b><small>仅已形成完成时点的批次</small></span></div>`:'<div class="empty">基线完整性尚未通过，覆盖、用料与交期不计算。</div>')+
  (d.issues.length?panel('先修正基线资料','',`<ul>${d.issues.map(v=>`<li>${esc(v)}</li>`).join('')}</ul>`):'')+
  (d.warnings.length?panel('需要业务复核的差异','',`<ul>${d.warnings.map(v=>`<li>${esc(v)}</li>`).join('')}</ul>`):'')+
  panel('订单覆盖 · 完整基线','点选订单行查看关联批次与用料；顶部汇总始终保留整案范围。',d.orders.length?table(['订单行 / 配置','基线订单 / 登记发货','基线未发需求','本方案安排 / 未覆盖','覆盖范围','基线现承诺 / 映射批次完成','整单覆盖后的加工完成'],d.orders.map(o=>{
   const known=typeof o.coverage_percent==='number'&&Number.isFinite(o.coverage_percent),percent=known?Math.max(0,Math.min(100,o.coverage_percent)):null;
   return [`<button class="row-link" data-baseline-order="${esc(o.id)}" aria-pressed="${order===o.id}">${esc(o.id)}</button><small class="block">${esc(o.product_id)}</small>`,`${esc(o.order_qty)} / ${esc(o.registered_shipped_qty)}`,esc(o.baseline_open_qty),`${esc(o.planned_qty)} / ${esc(o.uncovered_qty)}`,`${known?`<div class="baseline-coverage" aria-label="登记需求覆盖 ${esc(numeric(o.coverage_percent))}%"><i style="width:${percent}%"></i></div>`:''}<small>${numeric(o.coverage_percent)}${known?'%':''}${o.overplanned_qty?` · 超排 ${esc(o.overplanned_qty)} 台`:''}</small>`,`${esc(o.due)}<br>${esc(local(o.mapped_jobs_finish))}`,o.order_finish?esc(local(o.order_finish)):d.state==='review'?'基线待重核，不确认整单参考完工':'未形成；可能尚未全量覆盖或存在未排批次'];
  })):'<p class="empty">订单覆盖未计算；不表示没有订单需求。</p>')+'<p class="source">客户日期按当日23:59:59比较加工完成，不包含检测放行、运输或签收，不能作为OTIF。登记发货按模拟基线时点取数。</p>';
}
export function createOrderBaselineWorkspace(h){
 const {api,esc,header,panel,table,modal,toast,go,$,$$,on,isCurrent,getModalRevision}=h;
 let serial=0,modalRequest=0;const trialWorkspace=createBaselineTrialWorkspace(h);
 on('#detail','close',()=>{modalRequest++});
 async function render(params,token){
  const current=++serial,alive=()=>isCurrent(token)&&serial===current;modalRequest++;
  if(params.get('view')==='trial')return trialWorkspace.render(params,token);
  trialWorkspace.cancel();
  const policy=params.get('policy')||'due';if(!['due','priority'].includes(policy))throw Error('试排策略无效');
  let list,d;
  try{list=await api('order-baselines')}catch(e){if(alive())throw e;return}
  if(!alive())return;
  if(!list.rows.length){$('#main').innerHTML=header('订单与BOM基线','')+'<div class="empty">导入40号模拟工作簿后可读取基线。</div>';return}
  const key=params.get('study')||list.rows[0].id,q=new URLSearchParams({policy});if(params.get('receipt'))q.set('receipt',params.get('receipt'));
  try{d=await api('order-baselines/'+encodeURIComponent(key)+'?'+q)}catch(e){if(alive())throw e;return}
  if(!alive())return;
  const base='order-baselines/'+encodeURIComponent(key),url=(suffix,extra={})=>base+suffix+'?'+new URLSearchParams({policy,receipt:d.receipt,...extra});
  const attempt=fn=>async(...a)=>{if(!alive())return;try{return await fn(...a)}catch(e){if(alive())toast(e.message)}};
  let selection={order:'',link:'',bom:'all'},bomPage=1;
  $('#main').innerHTML='<div class="baseline-reading-workspace">'+header('订单与BOM基线','核对订单覆盖、批次身份和冻结用料。',`<a href="#joint-schedule?study=${encodeURIComponent(d.joint_study.id)}&policy=${policy}">当前 BOM 物料人机试排 ↗</a>`)+
   `<div class="filterbar"><label>基线<select id="baseline-study">${list.rows.map(s=>`<option value="${esc(s.id)}" ${s.id===key?'selected':''}>${esc(s.id+' · '+s.name)}</option>`).join('')}</select></label><label>试排策略<select id="baseline-policy">${Object.entries(list.policies).map(([v,n])=>`<option value="${esc(v)}" ${v===policy?'selected':''}>${esc(n)}</option>`).join('')}</select></label><button id="baseline-trial-open">基线 BOM 假设试排</button><button id="baseline-refresh">重新读取</button><button id="baseline-csv">全基线 CSV</button><button id="baseline-json">全基线完整假设 JSON</button><button id="baseline-sources">全方案来源 · ${esc(d.source_count)}</button></div>`+
   `<div class="source">${esc(d.study.series)} · 第 ${esc(d.study.version)} 版 · 模拟基线 ${esc(local(d.study.baseline_at))}<br>${esc(d.study.basis)}<br>${esc(d.notice)}</div><div id="baseline-overview"></div><div id="baseline-reading"></div>`+
   panel('版本关系','',table(['版本','基线','模拟截止','前版'],d.versions.map(v=>[esc(v.version),`<a href="#order-baselines?study=${encodeURIComponent(v.id)}&policy=${policy}">${esc(v.id+' · '+v.name)}</a>`,esc(local(v.baseline_at)),esc(v.supersedes_id||'首版')]))+'<p class="source">点击前版重新读取其内容；不把版本关系解释为批准记录。</p>')+'</div>';
  on('#baseline-study','change',e=>go('order-baselines',{study:e.target.value,policy}));on('#baseline-policy','change',e=>go('order-baselines',{study:key,policy:e.target.value}));
  on('#baseline-trial-open','click',()=>go('order-baselines',{study:key,policy,view:'trial'}));
  on('#baseline-refresh','click',async()=>{if(!alive())return;const fresh=new URLSearchParams(params);fresh.delete('receipt');try{await render(fresh,token)}catch(e){if(isCurrent(token))toast(e.message)}});
  async function readModal(suffix,extra={}){
   const request=++modalRequest,revision=getModalRevision(),valid=()=>alive()&&request===modalRequest&&revision===getModalRevision();
   try{const v=await api(url(suffix,extra));return valid()?v:null}catch(e){if(valid())throw e;return null}
  }
  const detail=attempt(async id=>{const p=await readModal('/links/'+encodeURIComponent(id));if(p)modal('批次、订单与冻结用料依据',baselineLinkDetail(p,h))});
  const bind=(selector,field,handler)=>$$(selector).forEach(el=>el.addEventListener('click',()=>handler(el.dataset[field])));
  function select(next){
   if(!alive())return;baselineSelection(d,next);selection=next;bomPage=1;modalRequest++;draw();
  }
  function draw(){
   const focused=baselineSelection(d,selection);
   $('#baseline-overview').innerHTML=baselineOverview(d,h,selection);
   bind('[data-baseline-order]','baselineOrder',id=>select({order:id,link:'',bom:'all'}));
   if(!d.links.length){$('#baseline-reading').innerHTML='<p class="empty">没有可阅读的批次映射。基线暂停时仍可导出完整输入与全方案来源。</p>';return}
   $('#baseline-reading').innerHTML=panel('订单 → 批次 → 冻结用料','以下选择只缩小明细阅读范围，顶部汇总与全基线导出保持整案范围。',
    `<div class="filterbar"><label>阅读订单行<select id="baseline-order-filter"><option value="">全部订单行</option>${d.orders.map(o=>`<option value="${esc(o.id)}" ${o.id===selection.order?'selected':''}>${esc(o.id)}</option>`).join('')}</select></label><label>阅读批次<select id="baseline-link-filter"><option value="">全部关联批次</option>${focused.links.map(l=>`<option value="${esc(l.id)}" ${l.id===selection.link?'selected':''}>${esc(l.job_id+' / '+l.work_order_id)}</option>`).join('')}</select></label><button id="baseline-reset">恢复完整阅读范围</button></div>`+
    `<div class="baseline-reading-scope" aria-live="polite"><span>订单行 <b>${esc(selection.order||'全部')}</b></span><span>批次 <b>${esc(selection.link?focused.selected[0].job_id:'全部关联批次')}</b></span><span>${focused.selected.length} / ${d.links.length} 个映射 · ${focused.allBom.length} / ${d.bom.length} 行用料</span></div>`)+
    panel('关联批次与交期','点选批次可继续缩小用料范围；查看依据会核对当前凭据。',baselineLinks(focused.selected,h,selection.link))+
    panel('冻结用料与当前试排需求','用料核对筛选只作用本表，不隐藏订单、工单或版本字段差异。',
     `<div class="filterbar"><label>用料核对<select id="baseline-bom-filter"><option value="all" ${selection.bom==='all'?'selected':''}>全部用料行</option><option value="different" ${selection.bom==='different'?'selected':''}>待核对</option><option value="same" ${selection.bom==='same'?'selected':''}>相符</option></select></label></div><div id="baseline-bom-table"></div><div class="toolbar"><button id="baseline-bom-prev">上一页</button><span id="baseline-bom-page"></span><button id="baseline-bom-next">下一页</button></div>`)+
    panel('所选批次的字段差异','',baselineTrialChanges(focused.changes,h));
   on('#baseline-order-filter','change',attempt(e=>select({order:e.target.value,link:'',bom:'all'})));
   on('#baseline-link-filter','change',attempt(e=>select({...selection,link:e.target.value})));
   on('#baseline-bom-filter','change',attempt(e=>select({...selection,bom:e.target.value})));
   on('#baseline-reset','click',()=>select({order:'',link:'',bom:'all'}));
   bind('[data-baseline-focus]','baselineFocus',id=>select({...selection,link:id}));bind('[data-baseline-link]','baselineLink',detail);
   function drawBom(){
    $('#baseline-bom-table').innerHTML=baselineBom(focused.bomRows.slice((bomPage-1)*40,bomPage*40),h);
    $('#baseline-bom-page').textContent=`${bomPage} / ${Math.max(1,Math.ceil(focused.bomRows.length/40))} 页 · 当前核对 ${focused.bomRows.length} 行 / 当前批次范围 ${focused.allBom.length} 行 / 全基线 ${d.bom.length} 行`;
    $('#baseline-bom-prev').disabled=bomPage===1;$('#baseline-bom-next').disabled=bomPage*40>=focused.bomRows.length;
   }
   on('#baseline-bom-prev','click',()=>{if(bomPage>1){bomPage--;drawBom()}});on('#baseline-bom-next','click',()=>{if(bomPage*40<focused.bomRows.length){bomPage++;drawBom()}});drawBom();
  }
  draw();
  async function evidence(page=1){
   const s=await readModal('/sources',{page});if(!s)return;const size=s.size||40;
   modal('全方案来源 · 不受明细阅读选择影响',baselineSources(s.rows,h)+`<p>第 ${esc(s.page)} 页，共 ${esc(s.total)} 条。${s.can_download_original?'管理员可在导入页读取归档原件。':'来源索引不授予原件权限。'}</p><button id="baseline-prev" ${page===1?'disabled':''}>上一页</button><button id="baseline-next" ${page*size>=s.total?'disabled':''}>下一页</button>`);
   on('#baseline-prev','click',attempt(()=>evidence(page-1)));on('#baseline-next','click',attempt(()=>evidence(page+1)));
  }
  on('#baseline-sources','click',attempt(()=>evidence()));
  let downloading=false;
  async function download(format){
   if(downloading)return;downloading=true;
   try{
    const r=await fetch(exportPath(key,policy,d.receipt,format),{credentials:'same-origin',cache:'no-store'});if(!alive())return;
    if(!r.ok){const e=await r.json().catch(()=>({error:'基线导出失败'}));if(alive())throw Error(e.error||'基线导出失败');return}
    if(!r.headers.get('Content-Disposition')?.startsWith('attachment;'))throw Error('响应不是结果文件');
    const blob=await r.blob();if(!alive())return;const path=URL.createObjectURL(blob),a=document.createElement('a');a.href=path;a.download='order-baseline-'+key+'.'+format;
    document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(path),1000);
   }finally{downloading=false}
  }
  on('#baseline-csv','click',attempt(()=>download('csv')));on('#baseline-json','click',attempt(()=>download('json')));
 }
 return {render};
}
