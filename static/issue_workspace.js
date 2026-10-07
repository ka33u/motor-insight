// Server scope governs summaries, paging, evidence and the whole-cohort CSV.
export const issueScopeKeys=['family','kind','status','severity','owner','q','focus'];
export function issueQuery(scope,extra={}){return new URLSearchParams({...Object.fromEntries(issueScopeKeys.map(k=>[k,scope[k]||''])),...extra}).toString()}
export function createIssueWorkspace(h){
 const {api,esc,num,header,panel,table,modal,toast,go,$,$$,on,localTime,isCurrent,getModalRevision}=h;
 let sequence=0,detailSequence=0;
 async function render(params,token){
  const seq=++sequence,scope=Object.fromEntries(issueScopeKeys.map(k=>[k,params.get(k)||'']));
  const d=await api('issue-workspace?'+issueQuery(scope,{page:params.get('page')||1}));if(!isCurrent(token)||seq!==sequence)return;
  const current=()=>isCurrent(token)&&seq===sequence;
  const select=(id,label,values,value)=>`<label>${label}<select id="${id}" aria-label="${label}"><option value="">全部</option>${values.map(v=>`<option value="${esc(v)}" ${v===value?'selected':''}>${esc(v)}</option>`).join('')}</select></label>`;
  const s=d.summary,pages=Math.max(1,Math.ceil(d.total/d.size));
  const stats=[['业务观察',s.observations],['不同业务对象',s.distinct_objects],['高等级观察',s.high],['跟进未核验',s.pending],['跟进期限逾期',s.followup_overdue],['来源行缺口',s.source_missing]];
  $('#main').innerHTML=header('业务观察与跟进','按当前规则找到对象、核对证据，再登记责任岗位与期限。',`<button id="issue-refresh">刷新范围</button><button id="issue-export">导出已应用范围全部 ${num(d.total)} 条</button>`)+
   `<div class="notice"><span>合成模拟数据 · 业务截止 ${esc(d.as_of.replace('T',' '))}</span><span>跟进日期 ${esc(d.today)} · 每页 ${d.size} 条</span></div><p class="panel-note">${esc(d.notice)}</p>`+
   `<div class="issue-stats">${stats.map(([label,value])=>`<div><small>${label}</small><b>${num(value)}</b></div>`).join('')}</div>`+
   `<p class="panel-note">已应用范围：产品族 ${esc(scope.family||'全部')} · 类别 ${esc(scope.kind||'全部')} · 状态 ${esc(scope.status||'全部')} · 等级 ${esc(scope.severity||'全部')} · 岗位 ${esc(scope.owner||'全部')} · 搜索 ${esc(scope.q||'未设')}。修改下方条件后点击“应用筛选”；导出始终对应已展示范围。</p><form id="issue-filters" class="issue-filters">${select('issue-family','产品族',d.options.families,scope.family)}${select('issue-kind','问题类别',d.options.kinds,scope.kind)}${select('issue-status','跟进状态',d.options.statuses,scope.status)}${select('issue-severity','等级',['高','待办'],scope.severity)}${select('issue-owner','责任岗位文字',d.options.owners,scope.owner)}<label>搜索编号 / 依据<input id="issue-q" value="${esc(scope.q)}" maxlength="255"></label><button class="primary">应用筛选</button><button type="button" id="issue-clear">清空筛选</button></form>`+
   (scope.focus?`<p class="panel-note">定位：${esc(scope.focus)} · ${d.focus_found?'已在当前范围找到，并跳转到所在页':'当前范围已无该观察；可查看协同中心保留的跟进历史'} <button id="issue-unfocus" class="ghost">取消定位</button></p>`:'')+
   panel('当前范围清单',`${num(d.total)} 条观察 · 第 ${d.page} / ${pages} 页`,table(['问题 / 等级','业务对象 / 范围','问题依据','责任岗位 / 跟进','期限 / 版本','查看'],d.rows.map(r=>[
    `${esc(r.kind)}<br><small>${esc(r.severity)}</small>`,`<a href="${esc(r.object_href)}">${esc(r.object)}</a><br><small>${esc(r.scope)}</small>`,esc(r.detail),`${esc(r.disposition.owner)}<br>${esc(r.disposition.status)}`,`${esc(r.disposition.due_date||'未设期限')} ${r.followup_overdue?'<b class="danger-text">已逾期</b>':''}<br><small>v${r.disposition.version} ${r.source_missing?'· 来源待核对':''}</small>`,`<button data-issue-open="${esc(r.key)}" class="ghost">证据与跟进 ↗</button>`
   ])),'','span2')+`<div class="toolbar"><button id="issue-prev" ${d.page<=1?'disabled':''}>上一页</button><span>第 ${d.page} 页 · 已显示 ${d.rows.length} / ${num(d.total)} 条</span><button id="issue-next" ${d.page>=pages?'disabled':''}>下一页</button><label>跳页 <input id="issue-page" type="number" min="1" max="${pages}" value="${d.page}" style="width:85px"></label><button id="issue-jump">跳转</button></div>`;
  const read=()=>({...scope,focus:'',...Object.fromEntries(['family','kind','status','severity','owner','q'].map(k=>[k,$('#issue-'+k).value]))});
  on('#issue-filters','submit',e=>{e.preventDefault();go('issues',read())});on('#issue-clear','click',()=>go('issues'));on('#issue-unfocus','click',()=>go('issues',{...scope,focus:''}));
  on('#issue-refresh','click',()=>render(params,token));on('#issue-prev','click',()=>go('issues',{...scope,page:d.page-1}));on('#issue-next','click',()=>go('issues',{...scope,page:d.page+1}));
  on('#issue-jump','click',()=>{const n=Number($('#issue-page').value);if(!Number.isInteger(n)||n<1||n>pages)throw Error('请输入有效页码');go('issues',{...scope,page:n})});
  on('#issue-export','click',async()=>{
   const button=$('#issue-export');button.disabled=true;
   try{
    const response=await fetch('/api/issue-workspace/export?'+issueQuery(scope,{receipt:d.receipt}),{cache:'no-store'});
    if(!response.ok){const error=await response.json();throw Error(error.error||'导出失败，请刷新范围')}
    const blob=await response.blob();if(!current())return;
    const url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download='业务观察_完整范围.csv';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);toast('已下载当前筛选范围全部观察，含业务截止与跟进日期');
   }finally{if(current())button.disabled=false}
  });
  $$('[data-issue-open]').forEach(b=>on('[data-issue-open="'+CSS.escape(b.dataset.issueOpen)+'"]','click',()=>open(b.dataset.issueOpen,1)));
  async function open(key,page){
   const attempt=++detailSequence,prior=getModalRevision(),wasOpen=$('#detail').open;
   const info=await api('issue-workspace/rows/'+encodeURIComponent(key)+'?'+issueQuery(scope,{receipt:d.receipt,page}));
   if(!current()||attempt!==detailSequence||prior!==getModalRevision()||wasOpen&&!$('#detail').open)return;
   const r=info.row,n=r.disposition;
   const evidence=info.sources.map(src=>`<details><summary>${esc(src.dataset)} · ${esc(src.key)} · v${src.revision} · ${esc(src.file)} / ${esc(src.sheet)} / 行 ${src.row}</summary><p class="muted">批次 ${esc(src.batch)} · SHA256 ${esc(src.file_hash)}</p>${table(['字段','该来源行的值'],src.fields.filter(f=>Object.hasOwn(src.values,f.name)).map(f=>[esc(f.label),esc(String(src.values[f.name]??''))]))}</details>`).join('');
   const history=table(['时间 / 记录人','状态 / 版本','责任岗位 / 期限','登记依据'],info.history.map(x=>{const a=x.detail.after||{};return [esc(localTime(x.created_at))+'<br>'+esc(x.actor),esc(a.status)+' · v'+a.version,esc(a.owner)+'<br>'+esc(a.due_date||'未设期限'),esc(a.note)]}));
   modal('观察 · '+r.object,`<p><b>${esc(r.kind)}</b> · ${esc(r.detail)}</p><p class="panel-note">${esc(info.notice)}</p><div class="toolbar"><a href="${esc(r.object_href)}">打开业务专题 ↗</a>${r.task_href?`<a href="${esc(r.task_href)}">建立账号协调任务 ↗</a>`:''}<a href="#coordination-hub">协同中心 ↗</a></div><div class="notice">${esc(n.status)} · ${esc(n.owner)} · v${n.version} · ${esc(n.due_date||'未设期限')}</div>`+
    (info.can_follow_up?`<form id="issue-follow" class="editor"><label>责任岗位文字<input name="owner" value="${esc(n.owner)}" maxlength="150" required></label><label>跟进状态<select name="status">${d.options.statuses.map(v=>`<option ${n.status===v?'selected':''}>${esc(v)}</option>`).join('')}</select></label><label>跟进期限<input type="date" name="due_date" value="${esc(n.due_date||'')}"></label><label>核查依据<textarea name="note" minlength="5" maxlength="2000" required>${esc(n.note)}</textarea></label><p class="muted">岗位文字不会自动分派账号。标记已核验只是本条观察的跟进记录，不批准业务放行，也不修改事实。</p><button class="primary">保存 v${n.version+1} 跟进</button></form>`:'<p class="muted">当前岗位只读取业务观察；跟进由质量、生产、分析或管理员登记。</p>')+
    `<h3>文件、工作表与来源行 · ${info.sources.length} 行</h3>${r.source_missing?'<p class="danger-text">部分来源行缺失，请先核对依据。</p>':''}${evidence||'<p>当前没有可读取的来源行。</p>'}<h3>本条观察跟进历史 · ${info.history_total} 条</h3>${history}<div class="toolbar"><button id="issue-hprev" ${page<=1?'disabled':''}>较新记录</button><span>第 ${page} 页 · 每页 ${info.size} 条</span><button id="issue-hnext" ${page*info.size>=info.history_total?'disabled':''}>较早记录</button></div>`);
   const revision=getModalRevision(),active=()=>current()&&revision===getModalRevision()&&$('#detail').open;
   $$('#dialog-content a').forEach(a=>a.addEventListener('click',()=>$('#detail').close()));
   on('#issue-hprev','click',()=>open(key,page-1));on('#issue-hnext','click',()=>open(key,page+1));
   const requestId=crypto.randomUUID();let attemptedPayload=null;
   on('#issue-follow','submit',async e=>{
    e.preventDefault();const button=e.target.querySelector('button');button.disabled=true;
    const values=Object.fromEntries(new FormData(e.target));const payload={...values,scope,receipt:info.receipt,version:n.version,request_id:requestId};
    if(attemptedPayload&&JSON.stringify(attemptedPayload)!==JSON.stringify(payload)){button.disabled=false;throw Error('本次操作已提交过其他内容，请重新读取后再修改')}
    attemptedPayload=payload;
    try{const saved=await api('issue-workspace/rows/'+encodeURIComponent(key)+'/follow-up',{method:'POST',body:payload});if(!active())return;$('#detail').close();toast(saved.notice);await render(params,token)}
    catch(error){if(active()){if(error.status===409){button.textContent='范围或版本变化，请关闭并刷新';button.disabled=true;}else button.disabled=false;}throw error}
   });
  }
 }
 return render;
}
