import {scopeSummaryMarkup} from './bi_card_summary.js';
import {mountPivot} from './analysis_pivot.js';
import {mountScatter} from './analysis_scatter.js';
import {quantileExplanation} from './quantiles.js';
export function resultSelection(kind,row){return kind==='pivot'?{row:row.row??'',column:row.column??''}:kind==='scatter'?{point:row.key}:{group:row.dimension};}
export function resultPage(rows,page,size=25){return rows.slice(page*size,(page+1)*size);}
export function resultConditions(reading,esc){
 const names={eq:'等于',ne:'不等于',gt:'大于',gte:'大于等于',lt:'小于',lte:'小于等于',contains:'包含'};
 return reading.conditions.length?reading.conditions.map(f=>`<span class="result-condition">${esc(f.label)} ${esc(names[f.op]||f.op)} ${esc(f.value)}</span>`).join(''):'<span class="result-condition">本模型没有附加字段条件</span>';
}
export function resultIntro(value,esc,num){
 const r=value.result,d=value.reading,s=d.summary;
 return `<div class="model-result-intro"><h3>${esc(value.card.metadata.question)}</h3><p>当前合成资料 · ${esc(d.dataset_label)} · 登记模型v${value.card.binding.source_model.version}</p><div class="model-result-context"><span>业务截止：${esc(d.business_as_of)}</span><span>日期口径：${esc(d.scope.date_label)}</span><span>粒度：${esc(d.grain)}</span></div><div class="model-result-counts"><span>筛选前 ${num(r.scanned)} 行</span><span>筛选后 ${num(r.matched)} 行</span><span>分组 ${num(r.groups)} 个</span><span>主度量有效 ${num(s.valid_rows)} / 缺失 ${num(s.missing_rows)}</span></div><div class="model-result-conditions">${resultConditions(d,esc)}</div><p>${esc(d.notice)}</p>${d.truncated?'<p class="notice warn">分组超过1000，当前分组结果仅返回前1000组；整范围摘要仍从全部来源重算，来源入口可查全部筛选对象。</p>':''}</div>`;
}
export function mountModelCardResult({root,value,esc,num,table,chart,onEvidence,onExport}){
 const r=value.result,d=value.reading;let page=0;
 root.innerHTML=resultIntro(value,esc,num)+scopeSummaryMarkup({primary:d.summary,notice:d.notice},esc,num,{primary:'本模型全部已筛选来源'})+`<div class="toolbar"><button class="model-result-all-source">查看全部筛选来源 ↗</button><a href="#analysis?model=${value.card.binding.source_model.id}">编辑原分析模型 ↗</a>${onExport?`<button data-model-result-export="csv">导出本次结果 CSV</button><button data-model-result-export="json">导出本次结果 JSON</button>`:''}</div><p class="panel-note">结果导出保留全部分组和实际范围、单位、样本及版本；资料变化或凭据过期后请重新运行。文件不是服务器冻结快照。</p><section class="model-result-chart"><h3>${esc(d.display_label)}</h3><div class="model-result-visual"></div></section><div class="model-result-groups"></div>${quantileExplanation(r,esc)}<details><summary>本次实际计算定义与技术结果</summary><pre class="code-block">${esc(JSON.stringify({definition:r.resolved_definition,measures:r.measures,metric:r.metric_receipt,grouping:r.grouping_receipt,components:r.components,derived_notes:r.derived_notes},null,2))}</pre></details>`;
 root.querySelector('.model-result-all-source').onclick=()=>onEvidence({});
 root.querySelectorAll('[data-model-result-export]').forEach(b=>b.onclick=async()=>{b.disabled=true;try{await onExport(b.dataset.modelResultExport)}finally{if(root.contains(b))b.disabled=false;}});
 const visual=root.querySelector('.model-result-visual'),groups=root.querySelector('.model-result-groups');
 if(r.pivot){mountPivot({root:visual,result:r,esc,num,onSelect:cell=>onEvidence(resultSelection('pivot',cell)),label:'登记模型当前资料'});groups.hidden=true;return;}
 if(r.scatter){mountScatter({root:visual,primary:r,esc,num,table,onSelect:(_,point)=>onEvidence(resultSelection('scatter',point))});groups.hidden=true;return;}
 const numericRows=r.rows.map(row=>({...row,[d.display_key]:typeof row[d.display_key]==='number'&&Number.isFinite(row[d.display_key])?row[d.display_key]:null}));
 visual.innerHTML=d.chart==='table'?'<p>按表格核对各组度量。</p>':chart(numericRows,'dimension',d.display_key,d.chart)+`<p class="panel-note">图形按返回结果绘制；分组值不是整范围摘要。${d.chart==='line'?'连线按归组排序，不补缺期；类别连线不表示时间趋势。':''}</p>`;
 function draw(){const rows=resultPage(r.rows,page),pages=Math.max(1,Math.ceil(r.rows.length/25));groups.innerHTML=`<h3>分组明细</h3>${table([r.dimension_label,...r.labels,'来源行数','核对'],rows.map((row,i)=>[esc(row.dimension),...r.measures.map(m=>typeof row[m.key]==='number'?num(row[m.key],4):esc(row[m.key]??'—')),num(row.row_count),`<button data-model-result-group="${i}">查看本组来源</button>`]))}<div class="pagination"><span>第 ${page+1} / ${pages} 页 · 返回 ${num(r.rows.length)} / 共 ${num(r.groups)} 组</span><div><button class="model-result-prev" ${page===0?'disabled':''}>上一页分组</button><button class="model-result-next" ${page+1>=pages?'disabled':''}>下一页分组</button></div></div>`;groups.querySelectorAll('[data-model-result-group]').forEach(b=>b.onclick=()=>onEvidence(resultSelection('group',rows[+b.dataset.modelResultGroup])));groups.querySelector('.model-result-prev').onclick=()=>{page--;draw()};groups.querySelector('.model-result-next').onclick=()=>{page++;draw()};}draw();
}
export function createModelResultEvidence({api,esc,num,table,modal,toast,$,getModalRevision,isCurrent,sourceLinks}){
 let serial=0;
 async function open(value,selection,token,page=1){
  const op=++serial;if(!isCurrent(token))return;modal('口径卡当前结果来源','<p>正在核对当前资料与结果范围…</p>');const revision=getModalRevision(),valid=()=>op===serial&&revision===getModalRevision()&&isCurrent(token);
  try{const query=new URLSearchParams({receipt:value.reading.receipt,page:String(page),...selection}),d=await api('model-cards/'+value.card.id+'/evidence?'+query);if(!valid())return;const fields=d.fields,brief=fields.slice(0,5),content=$('#dialog-content');
   content.innerHTML=`<p class="source">${esc(d.selection_label)} · ${num(d.total)} 条来源 · ${esc(d.notice)}</p>${table([...brief.map(f=>f.label),'核对'],d.rows.map((row,i)=>[...brief.map(f=>esc(row.values[f.name]??'—')),`<button data-model-result-source="${i}">全部字段与来源</button>`]))}<div class="pagination"><span>第 ${page} 页 · 每页30条</span><div><button class="model-source-prev" ${page===1?'disabled':''}>上一页来源</button><button class="model-source-next" ${page*30>=d.total?'disabled':''}>下一页来源</button></div></div><div class="model-source-detail"></div>`;
   content.querySelector('.model-source-prev').onclick=()=>open(value,selection,token,page-1);content.querySelector('.model-source-next').onclick=()=>open(value,selection,token,page+1);content.querySelectorAll('[data-model-result-source]').forEach(b=>b.onclick=()=>{const row=d.rows[+b.dataset.modelResultSource];content.querySelector('.model-source-detail').innerHTML=`<p class="source">${row.source?'Excel：'+esc(row.source.file)+' · '+esc(row.source.sheet)+' · 第'+row.source.row+'行':'语义模型先汇总再关联，以下是实际参与计算的来源对象。'}</p><dl class="definition-grid">${fields.map(f=>`<dt>${esc(f.label)}</dt><dd>${esc(row.values[f.name]??'—')}</dd>`).join('')}</dl>${sourceLinks(row.references)}`;content.querySelectorAll('[data-lineage]').forEach(a=>a.onclick=()=>$('#detail').close());});
  }catch(e){if(valid())$('#dialog-content').innerHTML=`<p class="notice warn">${esc(e.message)}</p><p>关闭后重新运行口径卡，再核对来源。</p>`;toast(e.message);}
 }
 return {open};
}
