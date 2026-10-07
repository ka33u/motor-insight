// Personal fixed-study definitions and captured evidence; no generic model rewrite.
const labels={definitions_changed:'计算依据变化',baseline_evidence_changed:'基线资料更正',data_changed:'观测资料变化',same_observations:'观测与计算结果相同',source_missing:'当前来源不可读取'};
export function comparisonPresentation(d){
 return {label:labels[d.state]||'需要核对',comparable:d.pointwise_comparable===true,
  rows:(d.rows||[]).map(r=>({id:r.id,kinds:r.kinds,previous:r.before?.value??null,current:r.current?.value??null,
   previousReasons:r.before?.reasons||[],currentReasons:r.current?.reasons||[]}))};
}
const uuid=()=>crypto.randomUUID();
export async function personalSPCTopicMarkup(topic,h){
 const {api,esc,panel,table,localTime}=h;
 const q=new URLSearchParams({topic_id:topic.id});
 const [views,snapshots]=await Promise.all([api('spc-analysis-views?'+q),api('spc-result-snapshots?'+q)]);
 const link=(mode,id,label)=>`<a href="#spc?${mode}=${encodeURIComponent(id)}">${esc(label)} ↗</a>`;
 return panel('我的受控试验与冻结结果','仅显示当前账号关联到本专题的内容',
  `<p class="source">受控试验有独立的固定采样方案；未应用专题的通用日期筛选或卡片联动。</p>`+
  table(['个人视角 / 编码','试验与版本','读取'],views.rows.map(v=>[esc(v.name)+'<small class="block">'+esc(v.code)+'</small>',esc(v.study_id)+' · v'+v.revision,link('view',v.id,'当前结果')]))+
  table(['冻结快照','创建时间 / 捕获版本','读取'],snapshots.rows.map(s=>s.available?[esc(s.name),esc(localTime(s.created_at))+'<small class="block">'+esc(s.view_code)+' · v'+s.view_revision+'</small>',link('snapshot',s.id,'冻结结果')]:['不可读取','权限或完整性需要核对','—']))+
  `<p class="panel-note">${views.total} 个使用中视角，${snapshots.total} 份快照；本页快照列出前20份。</p>`,
  `<a href="#spc-workspace?topic=${topic.id}">管理我的视角与全部快照 ↗</a>`,'span2');
}

export function createSPCNotebook(h){
 const {api,esc,num,header,panel,table,modal,toast,go,$,$$,on,isCurrent,localTime,getModalRevision}=h;
 const close=()=>{if($('#detail').open)$('#detail').close()};
 const href=(kind,id)=>'#spc?'+new URLSearchParams({[kind]:id});
 const timestamp=v=>esc(localTime(v));
 const f=v=>v==null?'—':num(v,6);
 async function editor(v,study,topicId,token){
  const revision=getModalRevision();
  const [studies,topics]=await Promise.all([api('spc'),api('topics')]);
  if(!isCurrent(token)||revision!==getModalRevision())return;
  const conf=v?.definition.display||{show_spec:true,decimals:6};
  modal(v?'更新个人受控试验视角':'保存个人受控试验视角',`<form id="spc-view-editor" class="editor">
   <p class="source">固定试验身份、采样方案、产品规范和计算版本。更正后的定义要填写依据并形成新版本；结果另外保存为快照。</p>
   <label>自定义编码<input name="code" value="${esc(v?.code||'SPC.R.SIM.001')}" pattern="[A-Z][A-Z0-9._\\-]{2,79}" maxlength="80" required></label>
   <label>视角名称<input name="name" value="${esc(v?.name||'我的受控试验')}" maxlength="150" required></label>
   <label>试验<select name="study_id" required>${studies.rows.map(s=>`<option value="${esc(s.id)}" ${s.id===(v?.study_id||study)?'selected':''}>${esc(s.id+' · '+s.name)}</option>`).join('')}</select></label>
   <div class="form-grid"><label>显示小数位<select name="decimals">${[4,5,6,7,8].map(n=>`<option ${n===conf.decimals?'selected':''}>${n}</option>`).join('')}</select></label>
   <label>关联专题<select name="topic_id"><option value="">不关联</option>${topics.map(t=>`<option value="${t.id}" ${t.id===(v?.topic?.id||Number(topicId))?'selected':''}>${esc(t.name)}</option>`).join('')}</select></label></div>
   <label><input name="show_spec" type="checkbox" ${conf.show_spec?'checked':''}> 默认显示产品公差线</label>
   <label>保存 / 更新依据<textarea name="note" minlength="5" maxlength="1000" required>${esc(v?.note||'保留合成试验的固定采样定义，供后续复核。')}</textarea></label>
   <p class="panel-note">${v?'当前版本 v'+v.revision+'；并发更新会暂停保存。':'编码在本人视角中唯一。'}关联内容仍属于本人。</p>
   <div id="spc-view-error" class="inline-error" role="alert"></div><button class="primary" type="submit">${v?'更新视角版本':'保存个人视角'}</button></form>`);
  const modalRevision=getModalRevision();let pending=null;
  on('#spc-view-editor','submit',async e=>{
   e.preventDefault();const form=e.target,b=$('button[type="submit"]',form);b.disabled=true;
   try{
    const values=new FormData(form),fields={code:values.get('code'),name:values.get('name'),note:values.get('note'),study_id:values.get('study_id'),
     display:{show_spec:values.has('show_spec'),decimals:Number(values.get('decimals'))},topic_id:values.get('topic_id')?Number(values.get('topic_id')):null};
    const input=JSON.stringify(fields);
    if(!pending||pending.input!==input){const d=await api('spc/'+encodeURIComponent(fields.study_id));pending={input,body:{...fields,receipt:d.receipt,...(v?{revision:v.revision}:{request_id:uuid()})}}}
    if(!isCurrent(token)||getModalRevision()!==modalRevision)return;
    const result=await api('spc-analysis-views'+(v?'/'+v.id:''),{method:'POST',body:pending.body});
    if(!isCurrent(token)||getModalRevision()!==modalRevision)return;
    close();toast('个人视角已保存，版本 v'+result.view.revision);go('spc',{view:result.view.id});
   }catch(err){if(isCurrent(token)&&getModalRevision()===modalRevision)$('#spc-view-error').textContent=err.message}
   finally{b.disabled=false}
  });
 }
 async function capture(v,token){
  const revision=getModalRevision(),d=await api('spc-analysis-views/'+v.id+'/run');if(!isCurrent(token)||revision!==getModalRevision())return;
  modal('冻结完整受控试验',`<form id="spc-capture-editor" class="editor"><p class="source">${esc(v.code)} · v${v.revision} · ${esc(d.study.id)}<br>固定全部 ${d.total} 条观测与Excel来源，当前页码不限制保存范围。${d.limits?'候选算法试算':'控制限暂停，仍保留不适用原因'}。</p>
   <label>快照名称<input name="name" maxlength="120" value="${esc((v.name+' · 冻结试算').slice(0,120))}" required></label>
   <label>冻结依据<textarea name="note" minlength="5" maxlength="1000" required>固定本次合成试验结果和来源，用于后续资料更正核对。</textarea></label>
   <p class="panel-note">快照创建后不可覆盖。它保存本试验，不构成业务批准或全库历史重放。</p><div id="spc-capture-error" class="inline-error" role="alert"></div><button class="primary" type="submit">冻结全部观测与来源</button></form>`);
  const modalRevision=getModalRevision();let pending=null;
  on('#spc-capture-editor','submit',async e=>{
   e.preventDefault();const b=$('button[type="submit"]',e.target);b.disabled=true;
   try{const values=new FormData(e.target),fields={name:values.get('name'),note:values.get('note')},input=JSON.stringify(fields);
    if(!pending||pending.input!==input)pending={input,body:{...fields,request_id:uuid(),view_id:v.id,revision:v.revision,receipt:d.receipt}};
    const result=await api('spc-result-snapshots',{method:'POST',body:pending.body});
    if(!isCurrent(token)||getModalRevision()!==modalRevision)return;close();toast('完整试验快照已冻结');go('spc',{snapshot:result.snapshot.id});
   }catch(err){if(isCurrent(token)&&getModalRevision()===modalRevision)$('#spc-capture-error').textContent=err.message}
   finally{b.disabled=false}
  });
 }
 async function compare(key,token,page=1,receipt=null){
  const revision=getModalRevision(),q=new URLSearchParams({page});if(receipt)q.set('receipt',receipt);
  const d=await api('spc-result-snapshots/'+key+'/compare-current?'+q);if(!isCurrent(token)||revision!==getModalRevision())return;
  const p=comparisonPresentation(d),reason=(reasons)=>esc(reasons.join('；'));
  modal('冻结结果与当前资料核对',`<p class="source">${esc(d.notice)}</p><div class="notice"><b>${esc(p.label)}</b><span>${p.comparable?'按同一定义核对资料':'计算依据不同或当前不可读取，不作同口径差值判断'}</span></div>
   ${d.source_changed&&d.total===0?'<p class="source">来源摘要变化，但本次观测与派生结果相同；仍需核对引用资料。</p>':''}
   ${d.limits_before||d.limits_current?table(['控制限','冻结时','当前'],[['基线均值',f(d.limits_before?.center),f(d.limits_current?.center)],['I LCL / UCL',f(d.limits_before?.i_lcl)+' / '+f(d.limits_before?.i_ucl),f(d.limits_current?.i_lcl)+' / '+f(d.limits_current?.i_ucl)],['MR UCL',f(d.limits_before?.mr_ucl),f(d.limits_current?.mr_ucl)]]):''}
   ${d.definition_changes?.length?'<p class="notice warn">定义变化：'+esc(d.definition_changes.join('、'))+'</p>':''}
   ${table(['观测','变化类型','冻结值 / 原因','当前值 / 原因'],p.rows.map(r=>[esc(r.id),esc(r.kinds.join('、')),f(r.previous)+'<small class="block">'+reason(r.previousReasons)+'</small>',f(r.current)+'<small class="block">'+reason(r.currentReasons)+'</small>']))}
   <div class="pagination"><span>${d.total} 条变化观测 · 变化不等于改善或原因</span>${d.receipt?`<button id="spc-compare-prev" ${page<=1?'disabled':''}>上一页</button><button id="spc-compare-next" ${page*d.size>=d.total?'disabled':''}>下一页</button>`:''}</div>`);
  on('#spc-compare-prev','click',()=>compare(key,token,page-1,d.receipt));on('#spc-compare-next','click',()=>compare(key,token,page+1,d.receipt));
 }
 async function render(params,token){
  const topic=params.get('topic')||'',page=params.get('page')||'1',archived=params.get('archived')==='1',q=new URLSearchParams({archived:archived?'1':'0'}),sq=new URLSearchParams({page});
  if(topic){q.set('topic_id',topic);sq.set('topic_id',topic)}
  const [views,snapshots]=await Promise.all([api('spc-analysis-views?'+q),api('spc-result-snapshots?'+sq)]);if(!isCurrent(token))return;
  $('#main').innerHTML=header('我的受控试验工作簿','保存有编码的分析视角，冻结来源，复核资料变化。','<a href="#spc">过程稳定性试验 ↗</a>')+
   `<div class="notice"><b>个人内容 · 全部合成试算</b><span>当前筛选 ${topic?'专题 '+esc(topic):'全部专题'}</span></div><p class="source">${esc(views.notice)}</p>`+
   `<div class="toolbar"><button class="primary" id="spc-create-view">创建编码视角</button><button id="spc-archive-toggle">${archived?'查看使用中':'查看已归档'}</button>${topic?'<a href="#spc-workspace">清除专题筛选 ↗</a>':''}</div>`+
   panel(archived?'已归档视角':'使用中视角','定义与显示条件有版本；重新计算使用当前来源',table(['名称 / 编码','试验 / 定义版本','专题','操作'],views.rows.map(v=>[
    esc(v.name)+'<small class="block">'+esc(v.code)+'</small>',esc(v.study_id)+' · v'+v.revision,v.topic?.available?esc(v.topic.name):v.topic?'关联专题不可读取':'未关联',
    `${!v.archived?`<a href="${href('view',v.id)}">当前结果 ↗</a> <button data-spc-freeze="${v.id}">冻结</button>`:''} <button data-spc-edit="${v.id}">编辑</button> <button data-spc-archive="${v.id}">${v.archived?'恢复':'归档'}</button>`])))+
   panel('冻结试验结果',snapshots.total+'份 · 创建时的结果与完整来源',table(['快照 / 试验','捕获视角','创建时间','操作'],snapshots.rows.map(s=>s.available?[
    esc(s.name)+'<small class="block">'+esc(s.study_id)+' · '+s.observations+'条观测</small>',esc(s.view_code)+' · v'+s.view_revision,timestamp(s.created_at),`<a href="${href('snapshot',s.id)}">冻结结果 ↗</a> <button data-spc-compare="${s.id}">核对当前资料</button>`]:['不可读取','权限或完整性待核对',timestamp(s.created_at),'—'])))+
   `<div class="pagination"><span>快照第 ${esc(page)} 页 · 每页20份</span><button id="spc-book-prev" ${Number(page)<=1?'disabled':''}>上一页</button><button id="spc-book-next" ${Number(page)*20>=snapshots.total?'disabled':''}>下一页</button></div><p class="source">${esc(snapshots.notice)}</p>`;
  const nav=fields=>go('spc-workspace',{...(topic?{topic}:{}),archived:archived?'1':'0',...fields});
  on('#spc-create-view','click',()=>editor(null,params.get('study'),topic,token));on('#spc-archive-toggle','click',()=>nav({archived:archived?'0':'1'}));
  on('#spc-book-prev','click',()=>nav({page:Number(page)-1}));on('#spc-book-next','click',()=>nav({page:Number(page)+1}));
  $$('[data-spc-edit]').forEach(b=>b.addEventListener('click',()=>editor(views.rows.find(v=>v.id===b.dataset.spcEdit),null,topic,token).catch(e=>toast(e.message))));
  $$('[data-spc-freeze]').forEach(b=>b.addEventListener('click',()=>capture(views.rows.find(v=>v.id===b.dataset.spcFreeze),token).catch(e=>toast(e.message))));
  $$('[data-spc-compare]').forEach(b=>b.addEventListener('click',()=>compare(b.dataset.spcCompare,token).catch(e=>toast(e.message))));
  $$('[data-spc-archive]').forEach(b=>b.addEventListener('click',async()=>{b.disabled=true;try{const v=views.rows.find(v=>v.id===b.dataset.spcArchive);await api('spc-analysis-views/'+v.id+'/archive',{method:'POST',body:{revision:v.revision,archived:!v.archived}});if(isCurrent(token)){toast(v.archived?'视角已恢复':'视角已归档，快照保留');nav({})}}catch(e){if(isCurrent(token))toast(e.message)}finally{b.disabled=false}}));
  if(params.get('create'))await editor(null,params.get('study'),topic,token);
  if(params.get('capture')){const v=(await api('spc-analysis-views/'+params.get('capture'))).view;if(isCurrent(token))await capture(v,token)}
  if(params.get('compare'))await compare(params.get('compare'),token);
 }
 return {render};
}
