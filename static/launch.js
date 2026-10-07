const labels={satisfied:'登记条件满足',blocked:'存在阻断',unknown:'资料或时点不足',not_required:'登记不适用'};
const local=v=>v?.replace('T',' ')||'未形成时点';
export const canLaunch=role=>['admin','analyst','operations'].includes(role);
export function selectTasks(rows,job='',status=''){return rows.filter(r=>(!job||r.job_id===job)&&(!status||r.state===status))}
export function exportPath(key,policy,receipt,format){
 if(!receipt||!['due','priority'].includes(policy)||!['csv','json'].includes(format))throw Error('请重新读取投产核对');
 return '/api/launch-review/'+encodeURIComponent(key)+'/export?'+new URLSearchParams({policy,receipt,format});
}
export function launchSummary(d,{esc,panel,table}){
 const s=d.summary;
 return (s?`<div class="finite-summary"><span>登记条件满足 <b>${s.satisfied} / ${s.tasks}</b> 个任务</span><span>存在阻断 <b>${s.blocked}</b></span><span>资料或时点不足 <b>${s.unknown}</b></span><span>全部任务满足的批次 <b>${s.satisfied_jobs} / ${s.jobs}</b></span><span>安排 <b>${s.plan_qty}</b> 台 · 订单仍未覆盖 <b>${s.uncovered_qty}</b> 台</span></div><p class="source">汇总始终为整个方案；任务清单筛选不改变共享工装预算。${s.conditions}条批次工序条件，${s.not_required}条显式不适用。登记条件满足不等于获准开工。</p>`:'<div class="empty">条件矩阵或基线完整性未通过，暂停核对；完整输入仍可导出。</div>')+
  (d.issues.length?panel('先修正输入范围',`<ul>${d.issues.map(v=>`<li>${esc(v)}</li>`).join('')}</ul>`):'')+
  panel('批次与订单',table(['批次 / 工单','订单行','安排台数','满足 / 阻断 / 资料不足','批次核对'],d.jobs.map(j=>[`${esc(j.job_id)}<small class="block">${esc(j.work_order_id)}</small>`,esc(j.order_line_id),j.qty,`${j.counts.satisfied||0} / ${j.counts.blocked||0} / ${j.counts.unknown||0}`,esc(labels[j.state])])));
}
export function createLaunchWorkspace(h){
 const {api,esc,header,panel,table,modal,toast,go,$,$$,on,isCurrent,getModalRevision}=h;let serial=0;
 const attempt=fn=>async(...args)=>{try{await fn(...args)}catch(e){toast(e.message)}};
 const sourceTable=rows=>table(['对象','Excel / 表 / 行','当前版本'],rows.map(r=>[`${esc(r.dataset)}<small class="block">${esc(r.key)}</small>`,r.missing?'来源缺失':`${esc(r.filename)}<br>${esc(r.sheet)} · 第${r.row}行`,r.missing?'未核对':`v${r.revision} · 源行${r.source_row_id}`]));
 const gate=g=>`<span class="launch-state ${esc(g.state)}">${esc(labels[g.state])}</span><small class="block">${esc(g.tool_id||g.subject||'')} ${esc(g.version||'')}</small>`;
 async function render(params,token){
  const list=await api('launch-review');if(!isCurrent(token))return;
  if(!list.rows.length){$('#main').innerHTML=header('投产条件核对','将试排任务与工装、工艺文件和质量条件关联。')+'<div class="empty">导入41号模拟工作簿后开始核对。</div>';return}
  const key=params.get('study')||list.rows[0].id,policy=params.get('policy')||'due',base='launch-review/'+encodeURIComponent(key),d=await api(base+'?'+new URLSearchParams({policy}));if(!isCurrent(token))return;
  const current=++serial,alive=()=>isCurrent(token)&&serial===current,url=(suffix,extra={})=>base+suffix+'?'+new URLSearchParams({policy,receipt:d.receipt,...extra});
  const job=params.get('job')||'',status=params.get('status')||'',selected=selectTasks(d.tasks,job,status),pages=Math.max(1,Math.ceil(selected.length/50));
  const page=Math.max(1,Math.min(pages,Number.parseInt(params.get('page')||'1',10)||1));
  $('#main').innerHTML=header('投产条件核对','资源排得进去，还要逐项核对开工依据。',`<a href="#order-baselines?study=${encodeURIComponent(d.baseline.id)}&policy=${policy}">查看订单与BOM基线 ↗</a>`)+
   `<div class="filterbar"><label>核对方案<select id="launch-study">${list.rows.map(r=>`<option value="${esc(r.id)}" ${r.id===key?'selected':''}>${esc(r.id+' · '+r.name)}</option>`).join('')}</select></label><label>试排策略<select id="launch-policy">${Object.entries(list.policies).map(([v,n])=>`<option value="${esc(v)}" ${v===policy?'selected':''}>${esc(n)}</option>`).join('')}</select></label><button id="launch-csv">整方案 CSV</button><button id="launch-json">完整假设 JSON</button><button id="launch-sources">全部来源 · ${d.source_count}</button></div>`+
   `<p class="source">资料截止 ${esc(local(d.study.assessed_at))} · 订单基线 ${esc(d.baseline.id)}<br>${esc(d.study.basis)}<br>${esc(d.notice)}</p>`+launchSummary(d,h)+
   panel('任务条件矩阵',`<div class="filterbar"><label>批次<select id="launch-job"><option value="">全部批次</option>${d.jobs.map(j=>`<option value="${esc(j.job_id)}" ${job===j.job_id?'selected':''}>${esc(j.job_id)}</option>`).join('')}</select></label><label>核对结果<select id="launch-status"><option value="">全部结果</option>${['satisfied','blocked','unknown'].map(s=>`<option value="${s}" ${status===s?'selected':''}>${labels[s]}</option>`).join('')}</select></label><span>${selected.length} / ${d.tasks.length} 个任务 · 第 ${page} / ${pages} 页</span></div>`+
    table(['任务 / 工序','原试排开始 / 完成','工装','工艺文件','质量条件','综合结果 / 前序影响'],selected.slice((page-1)*50,page*50).map(t=>[`<button class="row-link" data-launch-task="${esc(t.id)}">${esc(t.id)}</button><small class="block">${esc(t.process+' · '+t.route_id)}</small>`,`${esc(local(t.started))}<br>${esc(local(t.finished))}`,...t.gates.map(gate),`<span class="launch-state ${esc(t.state)}">${esc(labels[t.state])}</span><small class="block">${esc(t.upstream.length?'前序未满足：'+t.upstream.join('、'):t.blockers[0]||'所列登记核对一致')}</small>`]))+
    `<button id="launch-prev" ${page===1?'disabled':''}>上一页</button> <button id="launch-next" ${page===pages?'disabled':''}>下一页</button>`)+
   panel('工装保守占用与使用次数',`<p class="source">累计数来自当前台账；只列已分配工装的试排预算，未匹配需求不视为零需求。即使文件或质量条件受阻，也保留已分配的工装预算。到期日按当日00:00失效核对，不证明校准证书已验证。</p>`+
    table(['工装','当前累计 / 维护阈值','本方案分配使用次数','占用任务数','外部预占 / 停用'],d.tools.map(t=>[`${esc(t.id)}<small class="block">${esc(t.name||'原台账缺失')}</small>`,`${esc(t.baseline_uses??'未知')} / ${esc(t.limit??'未知')}`,t.proposed_uses,t.reservations.length,t.blocks.map(b=>`${esc(local(b.started))} → ${esc(local(b.ended))}<br>${esc(b.reason)}`).join('<br>')||'本方案未登记'])));
  const navigate=extra=>go('launch-review',{study:key,policy,job,status,...extra});
  on('#launch-study','change',e=>go('launch-review',{study:e.target.value,policy}));on('#launch-policy','change',e=>navigate({policy:e.target.value,page:1}));
  on('#launch-job','change',e=>navigate({job:e.target.value,page:1}));on('#launch-status','change',e=>navigate({status:e.target.value,page:1}));on('#launch-prev','click',()=>navigate({page:page-1}));on('#launch-next','click',()=>navigate({page:page+1}));
  const detail=attempt(async id=>{const revision=getModalRevision(),p=await api(url('/tasks/'+encodeURIComponent(id)));if(!alive()||revision!==getModalRevision())return;
   modal('任务开工条件 · '+id,`<p>${esc(p.notice)}</p>`+table(['条件','登记对象 / 要求版本','结果及原因','候选工装逐项依据'],p.row.gates.map(g=>[esc(g.kind),`${esc(g.subject||'不适用')} / ${esc(g.version||'')}`,`${gate(g)}<br>${g.reasons.map(esc).join('<br>')}`,g.candidates.map(c=>`${esc(c.tool_id)} · ${c.uses} 次<br>${c.reasons.length?c.reasons.map(esc).join('；'):'登记匹配'}`).join('<br>')||'见指定登记']))+`<p>前序影响：${esc(p.row.upstream.join('、')||'未发现前序条件阻断')}</p>`+sourceTable(p.sources));
  });$$('[data-launch-task]').forEach(el=>el.addEventListener('click',()=>detail(el.dataset.launchTask)));
  async function evidence(page=1){const revision=getModalRevision(),p=await api(url('/sources',{page}));if(!alive()||revision!==getModalRevision())return;modal('投产条件与完整竞争来源',sourceTable(p.rows)+`<p>第${page}页，共${p.total}条。${p.can_download_original?'管理员可从导入页查看原件。':'来源索引不授予原件权限。'}</p><button id="launch-source-prev" ${page===1?'disabled':''}>上一页</button><button id="launch-source-next" ${page*40>=p.total?'disabled':''}>下一页</button>`);on('#launch-source-prev','click',attempt(()=>evidence(page-1)));on('#launch-source-next','click',attempt(()=>evidence(page+1)))}
  on('#launch-sources','click',attempt(()=>evidence()));
  async function download(format){const response=await fetch(exportPath(key,policy,d.receipt,format),{credentials:'same-origin',cache:'no-store'});if(!alive())return;if(!response.ok){const p=await response.json().catch(()=>({error:'导出失败'}));throw Error(p.error||'导出失败')}if(!response.headers.get('Content-Disposition')?.startsWith('attachment;'))throw Error('返回内容不是文件');const blob=await response.blob();if(!alive())return;const path=URL.createObjectURL(blob),a=document.createElement('a');a.href=path;a.download='launch-'+key+'.'+format;document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(path),1000)}
  on('#launch-csv','click',attempt(()=>download('csv')));on('#launch-json','click',attempt(()=>download('json')));
 }
 return {render};
}
