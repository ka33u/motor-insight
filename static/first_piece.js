export const evidenceLabels={ready:'所列证据齐备',waiting:'到期待检',future:'尚未到期',out:'实测有超限',missing:'必检有漏项',metrology:'计量依据待核对',attention:'检验资料待核对'};
export function firstPieceSummary(d,{esc}){
 return `<div class="first-piece-summary">${Object.entries(evidenceLabels).map(([k,v])=>`<a href="#first-piece?${new URLSearchParams({...d.filters,state:k})}" class="first-piece-count ${k}"><span>${esc(v)}</span><b>${d.summary[k]}</b><small>个首件计划</small></a>`).join('')}</div><p class="source">当前筛选 ${d.summary.plans} / 全部 ${d.all_summary.plans} 个首件计划，${d.summary.work_orders} 个工单、${d.summary.measurements} 项最新实测。每个计划仅归入一个主状态；明细同时保留漏项、超限和计量问题。证据齐备不是首件批准。</p>`;
}
export function firstPieceTargets(d,{esc,table,panel}){
 if(!d)return '';
 return panel('新试排工单 · 首件候选依据',`<p>${esc(d.study.id+' · '+d.study.name)}</p><p class="source">${esc(d.notice)}</p><p>未见同范围计划 <b>${d.summary.missing}</b> · 找到候选 <b>${d.summary.candidates}</b> · 配置或路线待核对 <b>${d.summary.attention}</b>。本区始终显示所选投产方案全部 ${d.summary.rows} 条质量条件，不受历史计划筛选影响。</p>`+table(['开工条件 / 工单','工序 / 路线','开工登记原文','首件候选 / 后续动作'],d.rows.map(r=>[`${esc(r.id)}<small class="block">${esc(r.work_order_id)}</small>`,`${esc(r.process||'未匹配')} · ${esc(r.branch||'')}<small class="block">${esc(r.route_id)}</small>`,esc(r.clearance_status),`${r.plan_ids.map(id=>`<a href="#first-piece?${new URLSearchParams({q:id})}">${esc(id)}</a>`).join('、')||'未找到候选'}<small class="block">${esc(r.reason)}</small>`])));
}
export function firstPieceExportPath(filters,receipt,format){
 if(!receipt||!['csv','json'].includes(format))throw Error('请重新读取首件证据');
 return '/api/first-piece/export?'+new URLSearchParams({...filters,receipt,format});
}
export function createFirstPieceWorkspace(h){
 const {api,esc,header,panel,table,modal,toast,go,$,$$,on,isCurrent,getModalRevision}=h;let serial=0;
 const attempt=fn=>async(...args)=>{try{await fn(...args)}catch(e){toast(e.message)}};
 async function render(params,token){
  const filters=Object.fromEntries(['q','state','process','study'].map(k=>[k,params.get(k)||'']));
  const page=Math.max(1,Number.parseInt(params.get('page')||'1',10)||1),d=await api('first-piece?'+new URLSearchParams({...filters,page}));if(!isCurrent(token))return;
  const current=++serial,alive=()=>isCurrent(token)&&current===serial;
  $('#main').innerHTML=header('首件证据工作台','将应检计划、最新实测与计量登记放在同一条证据链中核对。','<a href="#process-quality">工艺参数与首件 ↗</a> · <a href="#metrology">计量影响核查 ↗</a>')+
   `<p class="source">截止 ${esc(d.as_of.replace('T',' '))}<br>${esc(d.notice)}</p>`+
   `<form id="first-piece-filter" class="filterbar"><label>计划 / 工单 / 配置 / 批次<input id="first-piece-q" value="${esc(filters.q)}" maxlength="150"></label><label>工序<select id="first-piece-process"><option value="">全部工序</option>${d.processes.map(p=>`<option value="${esc(p)}" ${filters.process===p?'selected':''}>${esc(p)}</option>`).join('')}</select></label><label>主状态<select id="first-piece-state"><option value="">全部状态</option>${Object.entries(evidenceLabels).map(([k,v])=>`<option value="${k}" ${filters.state===k?'selected':''}>${esc(v)}</option>`).join('')}</select></label><button>筛选</button><button type="button" id="first-piece-reset">清除筛选</button></form>`+
   `<div class="filterbar"><button id="first-piece-csv">当前范围 CSV</button><button id="first-piece-json">证据 JSON</button>${d.can_targets?'<a href="#launch-review">从投产方案查看对应工单缺口 ↗</a>':''}</div>`+
   firstPieceSummary(d,h)+firstPieceTargets(d.targets,h)+
   panel('首件计划 · 实测与计量一起看',table(['计划 / 对象','工单 / 配置','工序 / 分支','首次 → 最新实测','最新超限 / 漏项 / 计量疑点','当前证据'],d.rows.map(r=>[
    `<button class="row-link" data-first-piece="${esc(r.id)}">${esc(r.id)}</button><small class="block">${esc(r.object_id||'对象缺失')}</small>`,`${esc(r.work_order_id||'工单缺失')}<small class="block">${esc(r.product_id||'')}</small>`,`${esc(r.process||'')}<small class="block">${esc(r.branch||'')} · ${esc(r.route_version||'')}</small>`,`${esc(r.first_state)} → ${esc(r.latest_state)}<small class="block">${esc(r.latest_id||'未检')} · ${r.checks} 次有效检验</small>`,`${r.latest_out??'—'} / ${r.latest_missing??'—'} / ${r.meter_attention}`,`<span class="first-piece-state ${esc(r.evidence_state)}">${esc(r.evidence_label)}</span><small class="block">${esc(r.issues[0]||r.approval)}</small>`]))+
    `<p>第 ${page} 页 · 共 ${d.total} 个计划</p><button id="first-piece-prev" ${page===1?'disabled':''}>上一页</button> <button id="first-piece-next" ${page*25>=d.total?'disabled':''}>下一页</button>`);
  on('#first-piece-filter','submit',e=>{e.preventDefault();go('first-piece',{...filters,q:$('#first-piece-q').value,state:$('#first-piece-state').value,process:$('#first-piece-process').value})});
  on('#first-piece-reset','click',()=>go('first-piece',{}));on('#first-piece-prev','click',()=>go('first-piece',{...filters,page:page-1}));on('#first-piece-next','click',()=>go('first-piece',{...filters,page:page+1}));
  async function detail(key,sourcePage=1){
   const revision=getModalRevision(),p=await api('first-piece/'+encodeURIComponent(key)+'?'+new URLSearchParams({...filters,receipt:d.receipt,page:sourcePage}));if(!alive()||revision!==getModalRevision())return;
   modal('首件证据 · '+key,`<p>${esc(p.row.evidence_label)} · ${esc(p.row.approval)}</p><p class="source">${esc(p.notice)}</p>`+
    table(['参数 / 规范','最新实测 / 模拟限值','仪器 / 使用登记','测量时校准登记','已登记影响 / 核对事项'],p.measures.map(({reading:r,metrology:m})=>[`${esc(r.name||r.parameter||'规范缺失')}<small class="block">${esc(r.id)} · ${esc(r.spec_id)}</small>`,`${esc(r.value)} ${esc(r.unit)}<small class="block">${esc(r.lsl??'无下限')} ～ ${esc(r.usl??'无上限')} · ${r.out===true?'超限':r.out===false?'范围内':'待核对'}</small>`,`${esc(m.instrument_id||'待关联')}<small class="block">${esc(m.use_id||'')}</small>`,`${esc(p.calibration_labels[m.calibration_state]||m.calibration_state)}<small class="block">${esc(m.calibration_id||'无登记')}</small>`,`${esc(p.impact_labels[m.impact_state]||m.impact_state)}<small class="block">${[...(r.issues||[]),...(m.issues||[])].map(esc).join('；')}</small>`]))+
    `<h3>原检验履历与漏项</h3>`+table(['检验 / 时间','状态','漏检规范 / 资料问题'],p.executions.map(e=>[`${esc(e.row.id)}<small class="block">${esc(e.row.checked)}</small>`,esc(e.row.state),[...e.missing_specs.map(s=>s.id+' · '+s.name),...e.row.issues].map(esc).join('；')||'未发现']))+
    `<h3>直接来源 · ${p.source_total} 条</h3>`+table(['对象','Excel / 表 / 行','版本'],p.sources.map(s=>[`${esc(s.dataset)}<small class="block">${esc(s.key)}</small>`,s.missing?'来源缺失':`${esc(s.filename)}<small class="block">${esc(s.sheet)} · 第${s.row}行</small>`,s.missing?'待补':s.revision]))+
    `<p class="source">来源索引不授予原件下载或正式业务批准权限。完整受控来源见JSON。</p><button id="first-source-prev" ${sourcePage===1?'disabled':''}>来源上一页</button> <button id="first-source-next" ${sourcePage*40>=p.source_total?'disabled':''}>来源下一页</button>`);
   on('#first-source-prev','click',attempt(()=>detail(key,sourcePage-1)));on('#first-source-next','click',attempt(()=>detail(key,sourcePage+1)));
  }
  $$('[data-first-piece]').forEach(el=>el.addEventListener('click',attempt(()=>detail(el.dataset.firstPiece))));
  async function download(format){
   const r=await fetch(firstPieceExportPath(filters,d.receipt,format),{credentials:'same-origin',cache:'no-store'});if(!alive())return;
   if(!r.ok){const e=await r.json().catch(()=>({error:'导出失败'}));throw Error(e.error||'导出失败')}
   if(!r.headers.get('Content-Disposition')?.startsWith('attachment;'))throw Error('返回内容不是文件');
   const blob=await r.blob();if(!alive())return;const path=URL.createObjectURL(blob),a=document.createElement('a');a.href=path;a.download='first-piece.'+format;document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(path),1000);
  }
  on('#first-piece-csv','click',attempt(()=>download('csv')));on('#first-piece-json','click',attempt(()=>download('json')));
 }
 return {render};
}
