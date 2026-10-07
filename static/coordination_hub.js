export function createCoordinationHub({api,esc,num,header,panel,table,modal,toast,go,$,$$,on,localTime,isCurrent}){
 let scope=new URLSearchParams(),token=0,serial=0,receipt='';
 const safe=fn=>(...args)=>Promise.resolve(fn(...args)).catch(e=>toast(e.message));
 const nav=change=>go('coordination-hub',{...Object.fromEntries(scope),...change,page:1});
 const options=(rows,value)=>rows.map(([k,v])=>`<option value="${esc(k)}" ${value===k?'selected':''}>${esc(v)}</option>`).join('');
 const sourceState={present:'主体档案已关联',missing:'主体档案未找到',derived:'派生对象，请到来源专题核对',unmapped:'来源待映射'};
 const badge=(text,kind='')=>`<span class="hub-badge ${kind}">${esc(text)}</span>`;
 function bindLinks(root){$$('a[href^="#"]',root).forEach(a=>a.addEventListener('click',()=>$('#detail').close()));}
 async function detail(id,page=1){
  const s=++serial,wasOpen=$('#detail').open;
  const d=await api('coordination-hub/rows/'+encodeURIComponent(id)+'?'+new URLSearchParams({receipt,page}));
  if(s!==serial||!isCurrent(token)||(wasOpen&&!$('#detail').open))return;
  const r=d.row,src=d.source;
  const beforeAfter=x=>Object.entries(x).map(([k,v])=>`${esc(({status:'状态',owner:'责任',note:'说明',due_date:'期限',version:'版本'})[k]||k)}：${esc(v??'未设定')}`).join('<br>')||'—';
  modal(r.title,`<div class="notice"><span>${esc(r.type_label)} · v${num(r.version)} · ${esc(r.status)}</span><span>${esc(sourceState[r.source_state])}</span></div>
   <dl class="definition-grid"><dt>责任${r.owner_kind==='账号'?'账号':'岗位原文'}</dt><dd>${esc(r.owner||'未登记')}</dd><dt>期限 / 当前日期</dt><dd>${esc(r.due_date||'未设定')} / ${esc(d.today)} ${r.overdue_days?badge('逾期 '+r.overdue_days+' 天','late'):''}</dd><dt>最近记录</dt><dd>${esc(r.updated_by)} · ${localTime(r.updated_at)}</dd><dt>业务事实截止</dt><dd>${esc(d.business_as_of)}</dd></dl>
   <div class="hub-note">${esc(r.note||'未填写说明')}</div><p class="source">${esc(d.notice)} ${esc(r.source_context||'')}</p>
   <div class="toolbar">${r.href?`<a class="button" href="${esc(r.href)}">进入来源${r.type==='task'?'任务':'专题'}处理 ↗</a>`:''}${r.source_href?`<a href="${esc(r.source_href)}">查询主体业务记录 ↗</a>`:''}</div>
   ${src?`<details class="hub-source"><summary>主体Excel资料 · ${esc(src.key)} · v${src.revision}</summary><p class="source">${esc(src.file)} → ${esc(src.sheet)} → 第 ${num(src.row)} 行</p>${table(['字段','当前登记值'],src.fields.map(f=>[esc(f.label),esc(src.values[f.name]??'—')]))}${d.can_download_original?`<a href="/api/imports/${esc(src.batch)}/file">下载存档原件 ↧</a>`:''}</details>`:`<p class="source">${esc(sourceState[r.source_state])}；跟进记录仍保留，不能由此认定原业务已取消或办结。</p>`}
   ${d.related.length?`<h3>同一主体的其他记录</h3><p class="source">仅按相同来源表和编号关联，不代表同一问题或可以合并。</p>${table(['记录','状态','入口'],d.related.map(x=>[esc(x.type_label+' · '+x.title),esc(x.status),`<button class="row-link" data-hub-related="${esc(x.id)}">查看记录</button>`]))}`:''}
   <h3>处理记录 · ${num(d.history_total)} 条</h3>${table(['时间 / 记录人','动作','此前','当次'],d.history.map(x=>[localTime(x.at)+'<br>'+esc(x.actor),esc(x.action),beforeAfter(x.before),beforeAfter(x.after)]))}
   <div class="pagination"><span>历史第 ${d.page} 页</span><button id="hub-history-prev" ${d.page<=1?'disabled':''}>上一页历史</button><button id="hub-history-next" ${d.page*d.size>=d.history_total?'disabled':''}>下一页历史</button></div>`);
  bindLinks($('#dialog-content'));on('#hub-history-prev','click',safe(()=>detail(id,page-1)));on('#hub-history-next','click',safe(()=>detail(id,page+1)));
  $$('[data-hub-related]').forEach(b=>b.addEventListener('click',safe(()=>detail(b.dataset.hubRelated))));
 }
 async function render(params,t){
  token=t;serial++;scope=new URLSearchParams(params);const d=await api('coordination-hub?'+scope);if(!isCurrent(t))return;receipt=d.receipt;
  const f=d.filters,s=d.summary,range=['overdue','today','next7','later','no_due'];
  const max=Math.max(1,...range.map(k=>s[k]));
  const bars=range.map(k=>`<button class="hub-distribution ${f.bucket===k?'selected':''}" data-hub-bucket="${k}" aria-label="${esc(d.buckets[k])}，${s[k]}条"><span>${esc(d.buckets[k])}</span><i><b class="${k==='overdue'?'late':''}" style="width:${s[k]/max*100}%"></b></i><strong>${num(s[k])}</strong></button>`).join('');
  const groups=table(['来源专题','待跟进','其中逾期','复查登记 / 任务关闭'],d.groups.map(g=>[`<button class="row-link" data-hub-domain="${esc(g.id)}">${esc(g.label)}</button>`,num(g.open),g.overdue?badge(g.overdue+' 条','late'):'0',`${num(g.note_reviewed)} / ${num(g.task_closed)}`]));
  const rows=table(['跟进对象 / 记录类型','原状态 / 资料','责任岗位或账号','期限','最近记录'],d.rows.map(r=>[
   `<button class="row-link hub-title" data-hub-open="${esc(r.id)}">${esc(r.title)}</button><br><small>${esc(r.type_label)} · ${esc(r.domain_label)} · v${r.version}</small>`,
   `${badge(r.status,r.phase==='unknown'?'late':'')}<br><small>${esc(sourceState[r.source_state])}</small>`,
   `${esc(r.owner||'未登记')}<br><small>${esc(r.owner_kind)}${r.assigned_to_me?' · 分派给我':''}</small>`,
   `${esc(r.due_date||'未设定')}<br>${r.bucket==='overdue'?badge('逾期 '+r.overdue_days+' 天','late'):esc(d.buckets[r.bucket])}`,
   `${esc(r.updated_by)}<br><small>${localTime(r.updated_at)}</small>`]));
  $('#main').innerHTML=header('跨部门跟进汇总','统一查找已保存的跟进记录，并返回原专题核实与处理。',`<button id="hub-refresh">刷新跟进</button>`)+
   `<div class="notice"><span>跟进日期 ${esc(d.today)} · Asia/Shanghai</span><span>模拟业务事实截止 ${esc(d.business_as_of)}</span></div>
   <details class="hub-filter-panel" ${innerWidth>700?'open':''}><summary>调整跟进范围 · ${esc(d.buckets[f.bucket])}</summary><form id="hub-filters" class="hub-filters"><label>记录类型<select name="type">${options(Object.entries(d.types),f.type)}</select></label><label>来源专题<select name="domain">${options([['','全部可访问专题'],...d.domains.map(x=>[x.id,x.label])],f.domain)}</select></label><label>期限范围<select name="bucket">${options(Object.entries(d.buckets),f.bucket)}</select></label><label>与我的关系<select name="relation">${options(Object.entries(d.relations),f.relation)}</select></label><label>责任原文<select name="owner">${options([['','全部责任岗位 / 账号'],...d.owners.map(x=>[x,x])],f.owner)}</select></label><label>查找记录<input name="q" value="${esc(f.q)}" maxlength="200" placeholder="对象、说明或责任岗位"></label><div class="hub-filter-actions"><button class="primary">应用跟进范围</button><button type="button" id="hub-reset">重置</button></div></form></details>
   <p class="source">${esc(d.notice)}</p><div class="quality-kpis">${[['待跟进记录',s.open,'原状态未登记办结'],['其中已逾期',s.overdue,'期限早于当前跟进日期'],['今日到期',s.today,'当日仍可处理，不提前算逾期'],['未设期限',s.no_due,'未办结且尚无期限']].map(([a,b,c])=>`<article><small>${a}</small><strong>${num(b)} 条</strong><span>${c}</span></article>`).join('')}</div>
   <p class="hub-meta">当前 ${num(s.total)} 条 · 专题已记录复查 ${num(s.note_reviewed)} 条 · 账号任务已关闭 ${num(s.task_closed)} 条 · 状态待核对 ${num(s.unknown)} 条 · 主体资料需核对 ${num(s.source_attention)} 条</p>
   <div class="hub-summary">${panel('待跟进期限分布','完整筛选范围内的未办结记录；条长使用同一条数刻度。',bars)}${panel('来源专题分布','点击来源专题继续筛选；专题复查与任务关闭分别计数。',groups)}</div>
   <div class="toolbar"><h2>跟进清单</h2><a href="/api/coordination-hub/export?${esc(new URLSearchParams({...f,receipt}).toString())}">导出当前全部跟进 CSV ↓</a></div>${rows}
   <div class="pagination"><span>第 ${d.page} / ${Math.max(1,Math.ceil(d.total/d.size))} 页 · ${num(d.total)} 条</span><button id="hub-prev" ${d.page<=1?'disabled':''}>上一页跟进</button><button id="hub-next" ${d.page*d.size>=d.total?'disabled':''}>下一页跟进</button></div>`;
  on('#hub-filters','submit',e=>{e.preventDefault();nav(Object.fromEntries(new FormData(e.target)))});on('#hub-reset','click',()=>go('coordination-hub'));on('#hub-refresh','click',()=>go('coordination-hub',Object.fromEntries(scope)));
  on('#hub-prev','click',()=>go('coordination-hub',{...Object.fromEntries(scope),page:d.page-1}));on('#hub-next','click',()=>go('coordination-hub',{...Object.fromEntries(scope),page:d.page+1}));
  $$('[data-hub-open]').forEach(b=>b.addEventListener('click',safe(()=>detail(b.dataset.hubOpen))));
  $$('[data-hub-bucket]').forEach(b=>b.addEventListener('click',()=>nav({bucket:b.dataset.hubBucket})));
  $$('[data-hub-domain]').forEach(b=>b.addEventListener('click',()=>nav({domain:b.dataset.hubDomain})));
 }
 return {render};
}
