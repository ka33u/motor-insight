export function modelDiffMarkup(changes,esc,table){
 const value=(v,present)=>present?JSON.stringify(v,null,2):'未声明';
 return table(['定义项','原版本','候选版本'],changes.map(c=>[esc(c.path),`<pre class="code-block">${esc(value(c.before,c.before_present))}</pre>`,`<pre class="code-block">${esc(value(c.after,c.after_present))}</pre>`]));
}
export function trialSideMarkup(side,label,esc,num,table){
 if(!side.ready)return `<section class="panel"><h3>${esc(label)}</h3><p class="inline-error">试算暂停：${esc(side.error)}</p></section>`;
 const s=side.summary;
 return `<section class="panel"><h3>${esc(label)}</h3><p><b>${esc(side.display_label)}</b>：${s.value===null?'—':typeof s.value==='number'?num(s.value,4):esc(s.value)} ${esc(s.unit||'单位待核对')}</p><p>${esc(s.reason)}</p><p>来源 ${num(s.source_rows)} 条 · 有效 ${num(s.valid_rows)} 条 · 缺失 ${num(s.missing_rows)} 条${s.numerator!==null?`<br>分子 ${num(s.numerator,4)} / 分母 ${num(s.denominator,4)}`:''}</p><p class="source">粒度：${esc(side.grain)}；日期：${esc(side.date_label)}。${esc(side.sample_note)}</p><details><summary>查看分组预览 · 共 ${num(side.groups)} 组${side.truncated?'（原图形返回有上限）':''}</summary>${table([side.dimension_label,side.display_label],side.sample_groups.map(r=>[esc(r.dimension),r[side.display_metric]==null?'—':typeof r[side.display_metric]==='number'?num(r[side.display_metric],4):esc(r[side.display_metric])]))}</details></section>`;
}
export function impactMarkup(impact,esc,table){
 const rows=[...impact.topics.map(t=>['可访问专题',`${t.name} · v${t.version}`,`第 ${t.slots.map(i=>i+1).join('、')} 张卡使用候选新定义`]),
 ...impact.views.map(v=>['本人分析视角',`${v.name} · v${v.version}${v.archived?' · 已归档':''}`,v.scope_check]),
 ...impact.cards.map(c=>['本人口径卡',`${c.code} · v${c.revision}${c.archived?' · 已归档':''}`,'登记绑定需重核；旧版定义保留']),
 ...impact.pages.map(p=>['本人专题页面',`${p.code} · v${p.version}${p.archived?' · 已归档':''}`,`${p.relation}绑定需重核，历史布局保留`]),
 ...impact.snapshots.map(s=>['本人结果快照',s.name,'历史数值和定义保留；不可把新旧定义数值相减为改善'])];
 return `<h3>使用关系与影响</h3><p class="source">${esc(impact.notice)}</p>${rows.length?table(['对象','名称 / 版本','更新后的处理'],rows.map(r=>r.map(esc))):'<p>当前可列范围内未发现直接依赖，不代表没有其他使用者或外部引用。</p>'}`;
}
export function previewMarkup(d,esc,num,table){
 const p=d.population;
 return `<p><b>${esc(d.before.name)} v${d.before.version} → ${esc(d.candidate.name)} v${d.candidate.version}</b></p><p class="source">${esc(d.notice)} ${esc(d.delta_note)}</p>${modelDiffMarkup(d.changes,esc,table)}<div class="grid">${trialSideMarkup(d.original_result,'原定义',esc,num,table)}${trialSideMarkup(d.candidate_result,'候选定义',esc,num,table)}</div><p>${esc(p.reason)}${p.comparable?`<br>原范围 ${num(p.before)} 个对象 → 候选 ${num(p.after)} 个；共同 ${num(p.shared)} 个，新增纳入 ${num(p.added)} 个，移除 ${num(p.removed)} 个。`:''}</p><div class="toolbar">${d.original_result.ready?'<button data-change-side="before" data-change-subset="all">原范围来源</button>':''}${d.candidate_result.ready?'<button data-change-side="candidate" data-change-subset="all">候选范围来源</button>':''}${p.comparable?'<button data-change-side="candidate" data-change-subset="added">新增纳入来源</button><button data-change-side="before" data-change-subset="removed">移除来源</button><button data-change-side="candidate" data-change-subset="shared">共同来源</button>':''}</div><div id="change-evidence" aria-live="polite"></div>${impactMarkup(d.impact,esc,table)}<form id="model-change-confirm" class="editor"><label>变更依据<textarea name="reason" minlength="5" maxlength="1000" required placeholder="说明修改目的、核对结果及后续依赖处理"></textarea></label><label class="topic-check"><input type="checkbox" name="acknowledged" required> 已核对新旧定义、试算状态及当前可见影响；历史快照不改写</label><button class="primary" type="submit">保存模型 v${d.candidate.version}</button><p class="source">保存追加不可覆盖的定义变更记录，不保存本次经营数字。预演凭据10分钟有效，资料或依赖变化须重新预演。</p></form>`;
}
export function createModelChanges({api,esc,num,table,modal,toast,$,on,isCurrent,getModalRevision,localTime}){
 async function open(model,candidate,token,onSaved){
  const frozen=structuredClone(candidate);let serial=0,evidenceSerial=0,body=null,preview=null,requestId=null;
  modal('更新模型前预演','<div class="empty">正在读取试算范围…</div>');const revision=getModalRevision();
  const current=()=>isCurrent(token)&&getModalRevision()===revision&&$('#detail').open;
  let options;try{options=await api('scopes')}catch(error){if(current())$('#dialog-content').textContent=error.message;return}if(!current())return;
  $('#dialog-content').innerHTML=`<p>候选定义已从编辑器读取。下列范围只用于本次新旧试算，不写入模型；原模型局部条件仍各自保留。</p><form id="model-change-scope" class="editor"><div class="scope-grid"><label>产品族<select name="family"><option value="">全部</option>${options.families.map(f=>`<option>${esc(f)}</option>`).join('')}</select></label><label>客户<select name="customer_id"><option value="">全部</option>${options.customers.map(c=>`<option value="${esc(c.id)}">${esc(c.id+' · '+c.name)}</option>`).join('')}</select></label><label>业务开始日期<input name="from" type="date"></label><label>业务结束日期<input name="to" type="date"></label></div><button class="primary" type="submit">预演候选版本</button></form><p class="source">日期按两侧各自数据集口径选择对象；状态截至 ${esc(options.as_of.replace('T',' '))}。不自动带入某个专题的临时范围或联动。</p><div id="model-change-preview" aria-live="polite"></div>`;
  const root=$('#model-change-preview'),form=$('#model-change-scope');
  on('#model-change-scope','input',()=>{++serial;++evidenceSerial;preview=null;body=null;root.innerHTML='<p>试算范围已变，请重新预演。</p>'});
  async function showEvidence(side,subset,page=1){
   if(!preview||!body)return;const n=++evidenceSerial,b=structuredClone(body),stamp=preview.receipt,node=$('#change-evidence');node.textContent='正在核对本次试算来源…';
   try{
    const d=await api(`models/${model.id}/change-evidence`,{method:'POST',body:{...b,receipt:stamp,side,subset,page}});if(!current()||n!==evidenceSerial||preview?.receipt!==stamp||node!==$('#change-evidence'))return;
    node.innerHTML=table([...d.fields.map(f=>f.label),'Excel来源'],d.rows.map(r=>[...d.fields.map(f=>r.values[f.name]==null?'—':esc(r.values[f.name])),r.source?`${esc(r.source.filename)} / ${esc(r.source.sheet)} / 第 ${r.source.row} 行`:(r.references||[]).map(ref=>esc(ref.dataset+' · '+ref.key)).join('<br>')]))+`<div class="pagination"><span>${num(d.total)} 条来源 · 第 ${d.page} / ${d.pages} 页</span><div><button id="change-source-prev" ${d.page<=1?'disabled':''}>上一页</button><button id="change-source-next" ${d.page>=d.pages?'disabled':''}>下一页</button></div></div>`;
    on('#change-source-prev','click',()=>showEvidence(side,subset,page-1));on('#change-source-next','click',()=>showEvidence(side,subset,page+1));
   }catch(error){if(current()&&n===evidenceSerial)node.textContent=error.message}
  }
  on('#model-change-scope','submit',async e=>{
   e.preventDefault();const n=++serial;++evidenceSerial;preview=null;
   const scope=Object.fromEntries([...new FormData(form)].filter(([,v])=>v!==''));body={version:model.version,candidate:frozen,scope,links:null};const submitted=structuredClone(body);root.textContent='正在分别计算原定义与候选定义，并核对依赖…';
   try{
    const d=await api(`models/${model.id}/change-preview`,{method:'POST',body:submitted});if(!current()||n!==serial)return;
    preview=d;requestId=crypto.randomUUID();root.innerHTML=previewMarkup(d,esc,num,table);
    root.querySelectorAll('[data-change-side]').forEach(b=>b.addEventListener('click',()=>showEvidence(b.dataset.changeSide,b.dataset.changeSubset)));
    on('#model-change-confirm','submit',async event=>{
     event.preventDefault();if(!current()||n!==serial||preview!==d)return;const values=new FormData(event.target),button=$('button[type="submit"]',event.target);button.disabled=true;
     try{
      const result=await api(`models/${model.id}/change`,{method:'POST',body:{...submitted,receipt:d.receipt,reason:values.get('reason'),acknowledged:values.get('acknowledged')==='on',request_id:requestId}});
      if(!current()||n!==serial)return;await onSaved(result,()=>current()&&n===serial);if(current())$('#detail').close();
     }catch(error){if(current()&&n===serial){toast(error.message);button.disabled=false}}
    });
   }catch(error){if(current()&&n===serial)root.textContent=error.message}
  });
 }
 async function history(model,token,page=1){
  modal('模型更新记录','<div class="empty">正在读取定义历史…</div>');const revision=getModalRevision();
  const current=()=>isCurrent(token)&&revision===getModalRevision()&&$('#detail').open;
  try{
   const d=await api(`models/${model.id}/changes?page=${page}`);if(!current())return;
   $('#dialog-content').innerHTML=`<p>${esc(d.model.name)} · 当前 v${d.model.version} · 从 v${d.first_recorded_version} 起有新流程记录</p><p class="source">${esc(d.notice)}</p>${d.rows.map(r=>r.restricted?`<p>v${r.from_version} → v${r.to_version} · 此历史定义当前不可访问</p>`:`<details class="panel"><summary>v${r.from_version} → v${r.to_version} · ${esc(r.actor)} · ${esc(localTime(r.created_at))}</summary><p>${esc(r.payload.reason)}</p>${modelDiffMarkup(r.changes,esc,table)}<p class="source">仅核对范围：${esc(JSON.stringify(r.payload.scope))}；历史试算数字未保存。</p></details>`).join('')||'<p>当前模型还没有通过新流程保存的变更。</p>'}<div class="pagination"><span>第 ${d.page} / ${d.pages} 页 · ${d.total} 次变更</span><div><button id="change-history-prev" ${d.page<=1?'disabled':''}>上一页</button><button id="change-history-next" ${d.page>=d.pages?'disabled':''}>下一页</button></div></div>`;
   on('#change-history-prev','click',()=>history(model,token,page-1));on('#change-history-next','click',()=>history(model,token,page+1));
  }catch(error){if(current())$('#dialog-content').textContent=error.message}
 }
 return {open,history};
}
