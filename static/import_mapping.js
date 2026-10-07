export function importMappingMarkup(){return `<form id="import-wizard"><div class="upload-zone"><h3>先核对工作表和来源列</h3><p class="panel-note">可使用部门原有表头；字段映射不会换算单位、补编号或批准更正。</p><input id="mapping-file" type="file" accept=".xlsx" required aria-label="选择Excel工作簿"><button id="mapping-inspect" class="primary" type="submit">读取工作表与表头</button></div><div id="mapping-workspace"></div><p id="mapping-error" class="inline-error" role="alert"></p></form>`}

export function createImportMappingWorkspace({api,esc,num,table,toast,isCurrent,onStaged}){
 let generation=0,token=0,source=null,selection=[],file=null,receipt=null,batches=[],templates=[],templateReceipt=null,activation=null;
 const q=s=>document.querySelector(s),all=s=>[...document.querySelectorAll(s)];
 const current=g=>g===generation&&isCurrent(token);
 const types={str:'文本',int:'整数',float:'数值',bool:'是/否',date:'日期',datetime:'日期时间'};
 const schema=key=>source?.schemas.find(s=>s.key===key);
 function invalidate(message='映射已改变，请重新核对。'){
  receipt=null;templateReceipt=null;activation=null;const stage=q('#mapping-stage');if(stage)stage.disabled=true;
  if(q('#mapping-template-result'))q('#mapping-template-result').innerHTML='<p class="panel-note">本次尚未绑定有效模板依据；修改映射后需重新核对模板，或作为自定义映射导入。</p>';
  if(q('#mapping-preview-result'))q('#mapping-preview-result').innerHTML=`<p class="panel-note">${esc(message)}</p>`;
 }
 function readMapping(){
  const mapping={},problems=[];
  source.sheets.forEach((s,i)=>{
   const v=selection[i];
   if(s.metadata_sheet||v.dataset==='skip'){mapping[s.name]={skip:true};return}
   if(!schema(v.dataset)){problems.push(s.name+'：请选择业务表或明确忽略整页');return}
   const fields={},used=new Set();
   schema(v.dataset).fields.forEach(f=>{const h=v.bindings[f.name];if(!h)return;if(used.has(h))problems.push(s.name+'：来源列“'+h+'”被多次选择');used.add(h);fields[h]=f.name});
   mapping[s.name]={dataset:v.dataset,fields,ignore:s.headers.filter(h=>h&&!used.has(h))};
  });
  return {mapping,problems};
 }
 function initial(s){return {dataset:s.metadata_sheet?'skip':s.dataset||'',bindings:{...s.bindings}}}
 function datasetOptions(value){
  const groups=new Map();source.schemas.forEach(s=>{const dept=s.department.replace(/^\d+_/,'');if(!groups.has(dept))groups.set(dept,[]);groups.get(dept).push(s)});
  return `<option value="">请选择业务表</option><option value="skip" ${value==='skip'?'selected':''}>明确忽略该页</option>`+[...groups].map(([dept,rows])=>`<optgroup label="${esc(dept)}">${rows.map(s=>`<option value="${esc(s.key)}" ${s.key===value?'selected':''}>${esc(s.label)}</option>`).join('')}</optgroup>`).join('');
 }
 function sheetBody(s,i){
  const v=selection[i],target=schema(v.dataset);
  const fields=target?`<div class="mapping-fields">${target.fields.map(f=>`<label><span>${esc(f.label)} ${f.required?'<b class="mapping-required">必填列</b>':'可选'}<small>${esc(types[f.type]||f.type)}${f.reference?' · 关联'+esc(schema(f.reference)?.label||f.reference):''}</small></span><select data-mapping-field="${esc(f.name)}" data-sheet="${i}" aria-label="${esc(s.name+' '+f.label+'的来源列')}"><option value="">不提供此列</option>${s.headers.filter(Boolean).map(h=>`<option value="${esc(h)}" ${v.bindings[f.name]===h?'selected':''}>${esc(h)}</option>`).join('')}</select></label>`).join('')}</div>`:`<p class="panel-note">${v.dataset==='skip'?'此页不生成业务记录，原文件仍随上传批次归档。':'选择业务表后逐字段核对；不会按文件名猜测业务身份。'}</p>`;
  return `<article class="mapping-sheet"><h3>${esc(s.name)}</h3><p class="panel-note">工作表申报末行：${s.declared_last_row==null?'未知':num(s.declared_last_row)}；这是文件维度信息，实际非空记录数由逐行校验确定。</p>${s.metadata_sheet?'<p>系统说明页，固定不导入。</p>':`<label>这张表对应什么<select data-mapping-dataset="${i}" aria-label="${esc(s.name+'的目标业务表')}">${datasetOptions(v.dataset)}</select></label>${fields}`}<details><summary>核对原始表头与前3行样例</summary>${s.headers.length?table(['Excel行',...s.headers.map((h,i)=>h||'空表头·第'+(i+1)+'列')],s.samples.map(row=>[num(row.row),...s.headers.map((_,i)=>esc(row.values[i]??'—'))])):'<p>首行没有表头。</p>'}</details>${s.issues.length?`<p class="mapping-attention">首次读取提示：${esc(s.issues.join('；'))}；修改后以重新预检为准。</p>`:''}</article>`;
 }
 function draw(){
  const reusable=batches.filter(b=>Object.keys(b.mapping||{}).length);
  q('#mapping-workspace').innerHTML=`<div class="mapping-context"><strong>${esc(source.filename)}</strong><p>${esc(source.notice)}</p><p>只读取每页前3行样例，未进行全量校验，也未产生导入批次或业务记录。</p></div><label>复用已上传批次的映射<select id="mapping-reuse"><option value="">本次逐字段选择${reusable.length?'':'（尚无历史自定义映射）'}</option>${reusable.map(b=>`<option value="${esc(b.id)}">${esc(b.filename)} · ${esc(b.id.slice(0,8))}</option>`).join('')}</select></label><p class="panel-note">历史映射可复制作为起点，需与本次文件及当前字段定义重新核对；它不是批准的模板或版本发布。</p><div id="mapping-sheets">${source.sheets.map(sheetBody).join('')}</div><details><summary>查看本次明确忽略的列与整页</summary><div id="mapping-unused"></div></details><div class="toolbar"><button type="button" id="mapping-export">下载映射配置</button><button type="button" id="mapping-preview" class="primary">核对映射与必填列</button></div><div id="mapping-preview-result" aria-live="polite"></div><button type="button" id="mapping-stage" class="primary" disabled>按已核对映射进入完整校验批次</button><p class="panel-note">新文件保留原Excel并检查全部业务行；相同文件和映射可复用原批次，重新校验须使用批次中的重新校验入口。入库需另行检查并提交。文件、账号、字段或映射改变需重新预检。</p>`;
  q('#mapping-workspace').insertAdjacentHTML('beforeend',templateMarkup());
  bind();bindTemplates();unused();
 }
 function templateMarkup(){
  const usable=templates.flatMap(t=>t.versions.filter(v=>v.can_use).map(v=>({t,v})));
  return `<fieldset class="mapping-template-library"><legend>命名模板与版本</legend><p class="panel-note">启用模板只固定映射与表头约定；数据内容、单位和业务批准仍须核查。版本内容保留，状态变更有依据。</p><label>用已启用模板核对当前文件<select id="mapping-template"><option value="">请选择模板版本</option>${usable.map(({t,v})=>`<option value="${v.id}">${esc(t.code+' · '+t.name+' · v'+v.number)}</option>`).join('')}</select></label><div id="mapping-template-result" aria-live="polite"></div><details><summary>保存本次已核对映射为草稿版本</summary><label>目标模板<select id="mapping-template-target"><option value="">新建命名模板</option>${templates.filter(t=>t.can_manage).map(t=>`<option value="${t.id}">${esc(t.code+' · '+t.name+' · 修订'+t.revision)}</option>`).join('')}</select></label><div id="mapping-template-new" class="mapping-fields"><label>自定义编码<input id="mapping-template-code" maxlength="40" placeholder="TPL-PUR-SUP-001"></label><label>模板名称<input id="mapping-template-name" maxlength="100" placeholder="采购供应商清单"></label><label>来源部门<input id="mapping-template-dept" maxlength="80" placeholder="采购部"></label></div><label>保存或状态变更依据<textarea id="mapping-template-reason" maxlength="1000" rows="2" placeholder="说明表头、单位及忽略项的核对依据"></textarea></label><button id="mapping-template-save" type="button">保存不可覆盖的草稿版本</button></details><details><summary>模板维护人、启用状态与历史版本</summary>${templates.length?templates.map(t=>`<article><h4>${esc(t.code+' · '+t.name)}</h4><p class="panel-note">${esc(t.department)} · 维护人 ${esc(t.owner)} · 修订 ${t.revision} · 当前 ${t.current_version?'v'+t.current_version:'未启用'}</p>${table(['版本','状态/规则','保存依据','操作'],t.versions.map(v=>['v'+v.number,esc(({draft:'草稿',active:'已启用',retired:'已停用'})[v.state]||v.state)+' / '+(v.rules_current?'当前规则':'规则已变化'),esc(v.reason),`<button type="button" data-template-detail="${t.id}">定义与历史</button>${t.can_manage&&v.state!=='active'?` <button type="button" data-template-activate-check="${v.id}">用当前文件核对并启用</button>`:''}${t.can_manage&&v.state==='active'?` <button type="button" data-template-retire="${t.id}">停用当前版本</button>`:''}`]))}</article>`).join(''):'<p>尚未保存命名模板；可先逐字段核对，再保存草稿。</p>'}</details>`;
 }
 async function refreshTemplates(g){const d=await api('import-templates');if(current(g))templates=d}
 function bindTemplates(){
  q('#mapping-template-target').onchange=e=>{q('#mapping-template-new').hidden=!!e.target.value};
  q('#mapping-template').onchange=e=>{if(e.target.value)checkTemplate(+e.target.value,'use')};
  q('#mapping-template-save').onclick=saveTemplate;
  all('[data-template-activate-check]').forEach(el=>el.onclick=()=>checkTemplate(+el.dataset.templateActivateCheck,'activate'));
  all('[data-template-retire]').forEach(el=>el.onclick=()=>retireTemplate(el.dataset.templateRetire));
  all('[data-template-detail]').forEach(el=>el.onclick=()=>showTemplate(el.dataset.templateDetail));
 }
 async function saveTemplate(){
  if(!file||!source)return toast('请先读取当前工作簿');
  const {mapping,problems}=readMapping();if(!receipt||problems.length)return toast('请先核对当前映射与必填列');
  const selected=templates.find(t=>t.id===q('#mapping-template-target').value),reason=q('#mapping-template-reason').value.trim();
  const definition=selected?{template_id:selected.id,revision:selected.revision,reason}:{code:q('#mapping-template-code').value.trim(),name:q('#mapping-template-name').value.trim(),department:q('#mapping-template-dept').value.trim(),reason};
  const g=generation,d=form(mapping);d.append('inspection_receipt',receipt);d.append('definition',JSON.stringify(definition));lock(true);
  try{const r=await api('import-templates',{method:'POST',body:d});if(!current(g))return;await refreshTemplates(g);if(!current(g))return;activation=null;templateReceipt=null;draw();toast(r.repeated?'已有相同版本，已保留原内容':'草稿已保存，请用当前文件核对后启用')}
  catch(e){if(current(g))q('#mapping-error').textContent=e.message}finally{if(current(g))lock(false)}
 }
 async function checkTemplate(version,purpose){
  if(!file||!source)return toast('请先读取当前工作簿，再核对模板');
  const g=generation,d=form();d.append('version_id',version);d.append('purpose',purpose);invalidate('正在比较当前文件与模板…');lock(true);
  try{const r=await api('import-templates/preview',{method:'POST',body:d});if(!current(g))return;
   if(purpose==='use'&&r.template_can_apply){source=r;selection=r.sheets.map(initial);receipt=r.receipt;templateReceipt=r.template_receipt;draw()}
   const diff=r.drift.length?table(['工作表','变化','是否阻断'],r.drift.map(x=>[esc(x.sheet),esc(x.detail),x.blocking?'需新版本核对':'按名称可继续'])):'<p>所列业务页表头与模板一致。</p>';
   q('#mapping-template-result').innerHTML=`<p><b>${esc(r.template.code+' · v'+(r.template.versions.find(v=>v.id===version)?.number||''))}</b> · ${r.template_can_apply?'核对通过':'需处理差异或状态'}</p>${diff}${r.issues.length?`<p class="inline-error">${esc(r.issues.join('；'))}</p>`:''}<p class="panel-note">前3行样例中的值问题 ${num(r.sheets.reduce((a,s)=>a+s.sample_issues.length,0))} 项；进入批次仍检查全部行。</p>${purpose==='activate'&&r.template_can_apply?'<label>本次启用依据<textarea id="mapping-template-activate-reason" maxlength="1000" rows="2" placeholder="确认映射和忽略项，说明本次启用依据"></textarea></label><button type="button" id="mapping-template-confirm-activate">确认启用此版本</button>':''}${purpose==='use'&&r.template_can_apply?'<p>本次导入将记录该模板版本。修改映射后需重新核对，且不再沿用这份模板依据。</p>':''}`;
   if(purpose==='activate'&&r.template_can_apply){activation={receipt:r.template_receipt,revision:r.template.revision};q('#mapping-template-confirm-activate').onclick=activateTemplate}
  }catch(e){if(current(g))q('#mapping-error').textContent=e.message}finally{if(current(g))lock(false)}
 }
 async function activateTemplate(){
  if(!activation)return;const g=generation,d=form();d.append('template_receipt',activation.receipt);d.append('definition',JSON.stringify({revision:activation.revision,reason:q('#mapping-template-activate-reason').value.trim()}));lock(true);
  try{await api('import-templates/activate',{method:'POST',body:d});if(!current(g))return;await refreshTemplates(g);if(current(g)){activation=null;draw();toast('模板版本已启用；使用时仍须核对本次文件')}}
  catch(e){if(current(g))q('#mapping-error').textContent=e.message}finally{if(current(g))lock(false)}
 }
 async function retireTemplate(id){
  const selected=templates.find(t=>t.id===id),reason=q('#mapping-template-reason').value.trim();if(!reason)return toast('请在保存或状态变更依据中填写停用原因');const g=generation;invalidate('模板状态将变化，请重新核对。');lock(true);
  try{await api('import-templates/'+id+'/retire',{method:'POST',body:{revision:selected.revision,reason}});if(!current(g))return;await refreshTemplates(g);if(current(g)){source?draw():drawLibrary();toast('已停用；旧批次模板依据仍保留')}}
  catch(e){if(current(g))q('#mapping-error').textContent=e.message}finally{if(current(g))lock(false)}
 }
 async function showTemplate(id,page=1){
  const g=generation;lock(true);try{const t=await api('import-templates/'+id+'?page='+page);if(!current(g))return;q('#mapping-template-result').innerHTML=`<h4>${esc(t.code+' · '+t.name)}</h4>${t.versions.map(v=>`<details><summary>v${v.number} · ${esc(v.state)} · ${esc(v.content_hash.slice(0,12))}</summary><p>${esc(v.reason)} · 保存人 ${esc(v.created_by)} · 启用人 ${esc(v.activated_by||'未启用')}</p><pre class="mapping-template-json">${esc(JSON.stringify(v.payload,null,2))}</pre></details>`).join('')}<h4>状态与使用依据 · ${num(t.history.total)}条</h4>${table(['发生时间','动作/版本','账号','依据'],t.history.rows.map(e=>[esc(e.created_at),esc(({draft:'保存草稿',activate:'启用',retire:'停用',use:'使用',recheck_reference:'历史引用'})[e.action.split('.').pop()]||e.action)+' · v'+(e.detail.number||e.detail.header_review?.version_number||'—'),esc(e.actor),esc(e.detail.reason||e.detail.source_batch_id||e.detail.batch_id||e.detail.content_hash||'固定内容摘要留存')]))}<div class="pagination"><button type="button" id="mapping-template-history-prev" ${page<=1?'disabled':''}>上一页</button><span>第${page}页 · 每页30条</span><button type="button" id="mapping-template-history-next" ${page*30>=t.history.total?'disabled':''}>下一页</button></div>`;q('#mapping-template-history-prev').onclick=()=>showTemplate(id,page-1);q('#mapping-template-history-next').onclick=()=>showTemplate(id,page+1)}
  catch(e){if(current(g))q('#mapping-error').textContent=e.message}finally{if(current(g))lock(false)}
 }
 function drawLibrary(){q('#mapping-workspace').innerHTML=templateMarkup();bindTemplates()}
 function unused(){
  const {mapping,problems}=readMapping();
  q('#mapping-unused').innerHTML=table(['工作表','明确忽略内容'],Object.entries(mapping).map(([sheet,conf])=>[esc(sheet),conf.skip?'整页（含系统说明页）':esc(conf.ignore.join('、')||'无')]));
  q('#mapping-error').textContent=problems.join('；');
 }
 function bind(){
  all('[data-mapping-dataset]').forEach(el=>el.onchange=()=>{const i=Number(el.dataset.mappingDataset),s=source.sheets[i];selection[i]={dataset:el.value,bindings:{}};const target=schema(el.value);if(target)target.fields.forEach(f=>{const h=s.headers.filter(h=>h===f.name||h===f.label);if(h.length===1)selection[i].bindings[f.name]=h[0]});receipt=null;draw()});
  all('[data-mapping-field]').forEach(el=>el.onchange=()=>{selection[Number(el.dataset.sheet)].bindings[el.dataset.mappingField]=el.value;invalidate();unused()});
  q('#mapping-reuse').onchange=e=>{
   const b=batches.find(b=>b.id===e.target.value);if(!b)return;
   selection=source.sheets.map(s=>{const c=b.mapping[s.name];if(s.metadata_sheet)return initial(s);if(!c)return {dataset:'',bindings:{}};if(c.skip)return {dataset:'skip',bindings:{}};const target=schema(c.dataset||s.dataset),bindings={};if(target)target.fields.forEach(f=>{const explicit=Object.entries(c.fields||{}).filter(([,t])=>t===f.name||t===f.label).map(([h])=>h).filter(h=>s.headers.includes(h));const defaults=s.headers.filter(h=>(h===f.name||h===f.label)&&!(c.ignore||[]).includes(h));if(explicit.length===1)bindings[f.name]=explicit[0];else if(!explicit.length&&defaults.length===1)bindings[f.name]=defaults[0]});return {dataset:target?.key||'',bindings}});receipt=null;draw();toast('已复制历史映射，请逐项核对本次来源列');
  };
  q('#mapping-preview').onclick=preview;
  q('#mapping-stage').onclick=stage;
  q('#mapping-export').onclick=()=>{const {mapping,problems}=readMapping();if(problems.length)return toast('请先完成各工作表的选择');const blob=new Blob([JSON.stringify(mapping,null,2)],{type:'application/json;charset=utf-8'}),url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download='Excel字段映射_配置.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000)};
 }
 function form(mapping){const d=new FormData();d.append('file',file);if(mapping)d.append('mapping',JSON.stringify(mapping));return d}
 function lock(value){q('#mapping-file').disabled=value;q('#mapping-inspect').disabled=value;all('#mapping-workspace select,#mapping-workspace button,#mapping-workspace input,#mapping-workspace textarea').forEach(el=>{if(value){if(!el.hasAttribute('data-lock-previous'))el.dataset.lockPrevious=el.disabled?'1':'0';el.disabled=true}else if(el.hasAttribute('data-lock-previous')){el.disabled=el.dataset.lockPrevious==='1';delete el.dataset.lockPrevious}});if(!value&&q('#mapping-stage'))q('#mapping-stage').disabled=!receipt}
 async function inspect(e){
  e.preventDefault();file=q('#mapping-file').files[0];if(!file)return;
  const g=++generation;receipt=null;templateReceipt=null;activation=null;source=null;q('#mapping-workspace').innerHTML='';q('#mapping-error').textContent='';lock(true);
  try{const d=await api('imports/inspect',{method:'POST',body:form()});if(!current(g))return;source=d;selection=d.sheets.map(initial);draw()}
  catch(e){if(current(g))q('#mapping-error').textContent=e.message}
  finally{if(current(g))lock(false)}
 }
 async function preview(){
  const {mapping,problems}=readMapping();if(problems.length){q('#mapping-error').textContent=problems.join('；');return}
  const g=generation;invalidate('正在核对映射…');q('#mapping-error').textContent='';lock(true);
  try{const d=await api('imports/mapping/preview',{method:'POST',body:form(mapping)});if(!current(g))return;
   const samples=d.sheets.flatMap(s=>s.sample_issues.map(i=>[esc(s.name),num(i.row),esc(i.label),esc(i.message)]));
   receipt=d.can_stage?d.receipt:null;
   q('#mapping-preview-result').innerHTML=`<div class="${d.can_stage?'notice':'inline-error'}"><b>${d.can_stage?'表头及必填列已核对，可以进入逐行校验':'映射尚有问题，请修改后重新核对'}</b>${d.issues.length?`<p>${esc(d.issues.join('；'))}</p>`:''}</div>${samples.length?`<h3>前3行样例中的值问题</h3>${table(['工作表','Excel行','字段','需核查'],samples)}<p>完整校验会将问题行留在批次中，不因此判定其他行合格。</p>`:'<p class="panel-note">前3行未发现类型问题；这不代表所有数据行或关联已通过。</p>'}`;
  }catch(e){if(current(g))q('#mapping-error').textContent=e.message}
  finally{if(current(g))lock(false)}
 }
 async function stage(){
  if(!receipt)return;const {mapping,problems}=readMapping();if(problems.length)return;
  const g=generation,d=form(mapping);d.append('inspection_receipt',receipt);if(templateReceipt)d.append('template_receipt',templateReceipt);lock(true);q('#mapping-error').textContent='';
  try{const result=await api('imports',{method:'POST',body:d});if(current(g)){invalidate('已生成校验批次，请检查明细。');await onStaged(result,token)}}
  catch(e){if(current(g)){q('#mapping-error').textContent=e.message;invalidate('请重新核对映射后再上传。')}}
  finally{if(current(g))lock(false)}
 }
 function mount(options){generation++;token=options.token;batches=options.batches;templates=options.templates||[];source=null;selection=[];file=null;receipt=null;templateReceipt=null;activation=null;drawLibrary();q('#import-wizard').onsubmit=inspect;q('#mapping-file').onchange=()=>{generation++;source=null;selection=[];receipt=null;templateReceipt=null;activation=null;drawLibrary();q('#mapping-error').textContent=''}}
 return {mount};
}
