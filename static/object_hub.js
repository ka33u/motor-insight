const MODES={contains:'编码或名称包含',exact:'编码精确匹配',prefix:'编码前缀匹配'};
const defaults=()=>({q:'',dataset:'',mode:'contains'});
export function objectRoute(params){
 if([...params.keys()].some(k=>!['record','from'].includes(k))||[...params.keys()].some(k=>params.getAll(k).length!==1))throw Error('对象入口参数无效');
 for(const key of ['record','from'])if(params.has(key)&&(!/^[1-9]\d{0,14}$/.test(params.get(key))||!Number.isSafeInteger(Number(params.get(key)))))throw Error('对象记录标识无效');
 if(params.has('from')&&!params.has('record'))throw Error('请指定当前对象');
 return {record:params.get('record'),from:params.get('from')};
}
export function objectHref(recordId,from=null){
 if(!Number.isSafeInteger(recordId)||recordId<=0)throw Error('对象记录标识无效');
 const params=new URLSearchParams({record:String(recordId)});if(from!=null){if(!Number.isSafeInteger(from)||from<=0)throw Error('来源对象标识无效');params.set('from',String(from))}return '#objects?'+params;
}
export function sourceMarkup(source,esc,download=false){
 return `<div class="source object-source"><b>Excel来源</b> · ${esc(source.filename)} / ${esc(source.sheet)} / 第 ${esc(source.row)} 行<br>导入批次：<span class="mono">${esc(source.batch_id)}</span> · 记录版本 ${esc(source.revision)}${download?`<br><a href="/api/imports/${encodeURIComponent(source.batch_id)}/file" download>读取原始Excel ↗</a>`:''}</div>`;
}
export function objectRows(rows,esc,table,from=null){
 return table(['业务对象','命中依据 / 登记说明','Excel来源'],rows.map(r=>[
  `<a class="mono" href="${esc(objectHref(r.record_id,from))}">${esc(r.key)} ↗</a><br><small>${esc(r.dataset_label)} · v${esc(r.revision)}</small>`,
  esc(r.matched_fields?r.matched_fields.map(f=>f.label+'精确引用').join('、'):r.matched.join('、'))+r.description.map(d=>`<br><small>${esc(d.label)}：${esc(d.value)}</small>`).join(''),
  `${esc(r.source.filename)}<br><small>${esc(r.source.sheet)} · 第 ${esc(r.source.row)} 行</small>`
 ]));
}
export function relationMarkup(data,esc,table){
 return table(['当前对象的引用字段','登记的完整编号','目标记录'],data.outgoing.map(r=>[esc(r.label),`<span class="mono">${esc(r.key)}</span>`,r.state==='found'?`<a href="${esc(objectHref(r.record_id,data.object.record_id))}">${esc(r.dataset_label)} ↗</a>`:r.state==='missing'?`<span class="inline-error">${esc(r.dataset_label)} · 当前未找到</span>`:'目标当前不可访问']));
}
export function businessEntrypoint(object,esc){
 const entries={units:['trace','sn','整机完整履历'],batches:['lineage','id','生产批次影响反查'],order_lines:['delivery','line','订单行交付核对']};
 const item=entries[object.dataset];if(!item)return '';
 const params=new URLSearchParams({[item[1]]:object.key});if(object.dataset==='batches')params.set('kind','batch');
 return `<a href="#${item[0]}?${esc(params.toString())}">${item[2]} ↗</a>`;
}
export function createObjectHub({api,esc,num,header,panel,table,toast,go,$,$$,on,getState,isCurrent}){
 const sessions=new Map();
 function memory(){const username=getState().user.username;if(!sessions.has(username))sessions.set(username,{filters:defaults(),page:1,receipt:null});return sessions.get(username)}
 function lookup(q){const saved=memory();saved.filters={...defaults(),q};saved.page=1;saved.receipt=null;go('objects')}
 function pagination(d,prefix){return `<div class="pagination"><span>第 ${d.page} / ${d.pages} 页 · ${num(d.total)} 条记录 · 每页 ${d.size} 条</span><div><button id="${prefix}-prev" ${d.page<=1?'disabled':''}>上一页</button><button id="${prefix}-next" ${d.page>=d.pages?'disabled':''}>下一页</button></div></div>`}
 async function render(params,token){
  const path=objectRoute(params);if(path.record)return detail(path,token);
  const saved=memory();let serial=0;
  $('#main').innerHTML=header('对象检索','从完整业务编号或名称查找登记对象，再沿明确引用查看资料与业务工作台。')+`<form id="object-search-form" class="toolbar object-search"><label>编号或名称<input name="q" maxlength="150" value="${esc(saved.filters.q)}" placeholder="订单、工单、批次、SN、物料、设备…"></label><label>匹配方式<select name="mode">${Object.entries(MODES).map(([key,label])=>`<option value="${key}" ${key===saved.filters.mode?'selected':''}>${label}</option>`).join('')}</select></label><label>对象类型<select name="dataset" id="object-type"><option value="">全部常用对象</option></select></label><button class="primary">查找</button><button type="button" id="object-reset">清空</button></form><div id="object-results" aria-live="polite"></div>`;
  const node=$('#object-results'),form=$('#object-search-form');
  async function draw(page=1,reset=false){
   const request=++serial,filters=structuredClone(saved.filters);node.innerHTML='<div class="empty">正在核对已导入对象…</div>';
   try{
    const d=await api('object-hub/search',{method:'POST',body:{filters,page,receipt:reset?null:saved.receipt}});if(!isCurrent(token)||request!==serial||node!==$('#object-results'))return;
    saved.filters=d.filters;saved.page=d.page;saved.receipt=d.receipt;
    $('#object-type').innerHTML='<option value="">全部常用对象</option>'+d.types.map(t=>`<option value="${esc(t.key)}" ${t.key===d.filters.dataset?'selected':''}>${esc(t.label)}${d.filters.q?' · '+num(d.counts[t.key]||0):''}</option>`).join('');
    node.innerHTML=`<p class="source">${esc(d.notice)} ${esc(d.time_note)}</p>${d.filters.q?`<p><b>已应用查找：</b>${esc(d.filters.q)} · ${esc(MODES[d.filters.mode])} · ${esc(d.types.find(t=>t.key===d.filters.dataset)?.label||'全部常用对象')}。更改上方条件后点击“查找”。</p><p>在 ${d.types.length} 类常用对象中找到 ${num(d.total_all)} 条匹配登记，当前类型显示 ${num(d.total)} 条。精确编码优先，其次编码前缀，再列其他包含匹配。</p>${d.rows.length?objectRows(d.rows,esc,table):'<div class="panel empty">没有匹配记录。请核对对象类型、完整编码及导入情况；当前不自动改号或猜测关联。</div>'}${pagination(d,'object')}`:`<div class="panel empty">输入编号开始检索，前导零会保留。支持${d.types.map(t=>esc(t.label)).join('、')}。<br>材料批号和多跳影响范围仍从“批次影响反查”入口核对。</div>`}`;
    on('#object-prev','click',()=>draw(d.page-1));on('#object-next','click',()=>draw(d.page+1));
   }catch(error){if(isCurrent(token)&&request===serial){node.innerHTML=`<div class="notice warn"><span>${esc(error.message)}</span><button id="object-reload">按当前条件重新检索</button></div>`;on('#object-reload','click',()=>draw(1,true))}}
  }
  on('#object-search-form','submit',e=>{e.preventDefault();saved.filters=Object.fromEntries(new FormData(form));saved.page=1;saved.receipt=null;draw(1,true)});
  on('#object-reset','click',()=>{saved.filters=defaults();saved.page=1;saved.receipt=null;go('objects')});
  await draw(saved.page);
 }
 async function detail(path,token){
  const d=await api('object-hub/'+encodeURIComponent(path.record));if(!isCurrent(token))return;
  const object=d.object;let serial=0;
  $('#main').innerHTML=header(object.dataset_label+' · '+object.key,'当前已导入记录；原编号、版本及Excel来源保持可核对。',`${path.from?`<a href="${esc(objectHref(Number(path.from)))}">← 上个对象</a>`:''}<a href="#objects">返回检索结果</a>`)+`<div class="toolbar">${businessEntrypoint(object,esc)}<a href="#field-catalog?dataset=${encodeURIComponent(object.dataset)}">字段与单位定义 ↗</a></div>${sourceMarkup(object.source,esc,d.can_download_excel)}<p class="source">${esc(d.relation_note)}</p><div class="grid">${panel('本对象的直接引用','按字段定义核对目标，缺少记录不自动补齐。',d.outgoing.length?relationMarkup(d,esc,table):'<p class="muted">此登记没有已填写的直接引用字段。</p>')}${panel('哪些登记直接引用此对象','仅统计当前账号可查的表；每表按记录去重，不跨业务表合计。',d.inbound.length?`<label>引用业务表<select id="object-related-type">${d.inbound.map(r=>`<option value="${esc(r.dataset)}">${esc(r.label)} · ${num(r.count)} 条</option>`).join('')}</select></label><div id="object-related" aria-live="polite"></div>`:'<p class="muted">当前可查范围内没有已声明的直接引用，不据此断言没有其他业务关系。</p>')}</div><details class="panel"><summary>当前记录的全部可见字段 · ${d.fields.length} 项</summary><dl class="definition-grid object-fields">${d.fields.map(f=>`<dt>${esc(f.label)}<br><small class="mono">${esc(f.name)}</small></dt><dd>${f.value===null?'—':f.type==='bool'?(f.value?'是':'否'):esc(f.value)}</dd>`).join('')}</dl></details>`;
  if(!d.inbound.length)return;
  const node=$('#object-related'),select=$('#object-related-type');
  async function related(page=1){
   const request=++serial,dataset=select.value;node.innerHTML='<div class="empty">正在核对直接引用…</div>';
   try{
    const result=await api(`object-hub/${object.record_id}/related`,{method:'POST',body:{dataset,page,receipt:d.receipt}});if(!isCurrent(token)||request!==serial||node!==$('#object-related'))return;
    const expected=d.inbound.find(r=>r.dataset===dataset);if(result.total!==expected.count)throw Error('引用数量变化，请重新读取对象');
    node.innerHTML=objectRows(result.rows,esc,table,object.record_id)+pagination(result,'related');
    on('#related-prev','click',()=>related(result.page-1));on('#related-next','click',()=>related(result.page+1));
   }catch(error){if(isCurrent(token)&&request===serial){node.innerHTML=`<p class="inline-error">${esc(error.message)}</p><button id="object-detail-reload">重新读取对象与引用</button>`;on('#object-detail-reload','click',()=>go('objects',{record:object.record_id,...(path.from?{from:path.from}:{})}))}}
  }
  select.onchange=()=>related(1);await related();
 }
 return {render,lookup};
}
