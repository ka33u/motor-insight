// UI for the server's restricted grouped-measure expressions.
export function derivedEditor({root,definition,locked,esc,toast,measureRows}){
 const q=s=>root.querySelector(s),all=s=>[...root.querySelectorAll(s)];
 const units=['元/台','%','倍','元','元/工单','台/工单','元/kWh','分钟/次','小时/台','台','分钟','小时','kWh'];
 root.innerHTML=`<div class="derived-editor"><div class="form-line"><strong>汇总后派生 · 最多3项</strong><button type="button" id="add-derived" ${locked?'disabled':''}>＋ 添加</button></div><p class="panel-note">使用基础度量编号 m0、m1 等和 + − * /。如 m0 / m1；选“元/台”自动由分换元，选“%”自动乘100。结果单位由系统校验。</p><div id="derived-rows"></div>${locked?'<p class="source">固定发布指标不允许追加未审核公式；可另建临时分析。</p>':''}<label>图形主指标 / 数值排序依据<select id="model-display"></select></label><details><summary>单位和空值规则</summary><p class="panel-note">公式仅引用基础度量，不引用其他派生值。基础字段须有已配置的单位约定；任一引用字段在组内缺失，派生值留空。零分母、资源证据异常及过大数值均留空，原因随结果保留。金额/时间可自动换算，异类单位不能相加。图形每次显示一项，表格显示全部。派生值不用于占比环图。</p><p class="panel-note">可用基本单位：分、元、分钟、小时、台、工单、订单行、计划行、采购行、发票、次、条、个、人、配置、设备、资源位、批、kg、件、kWh、倍、%。也可用“基本单位/基本单位”。</p></details></div>`;
 let current=definition.display_metric||'m0';
 function refresh(){
  const previous=q('#model-display').value||current;
  const base=locked?[{key:'m0',label:'发布指标'}]:measureRows().map((el,i)=>({key:'m'+i,label:el.querySelector('.metric-label')?.value||((el.querySelector('.metric-field')?.selectedOptions[0]?.textContent||'基础度量')+(['median','percentile'].includes(el.querySelector('.metric-agg')?.value)?' · P'+(el.querySelector('.metric-agg').value==='median'?50:el.querySelector('.metric-percentile').value):''))}));
  const derived=all('.derived-row').map((el,i)=>{el.querySelector('.derived-code').textContent='d'+i;return {key:'d'+i,label:el.querySelector('.derived-label').value||'派生指标'}});
  measureRows().forEach((el,i)=>el.querySelector('.measure-code').textContent='m'+i);
  q('#model-display').innerHTML=[...base,...derived].map(x=>`<option value="${x.key}">${x.key} · ${esc(x.label)}</option>`).join('');
  q('#model-display').value=[...base,...derived].some(x=>x.key===previous)?previous:'m0';current=q('#model-display').value;
 }
 function add(item={label:'',expression:'m0 / m1',unit:'元/台'}){
  if(all('.derived-row').length>=3)return toast('最多3项派生指标');
  const el=document.createElement('div');el.className='derived-row';
  el.innerHTML=`<div class="form-line"><b class="derived-code"></b><button class="ghost remove-derived" type="button" aria-label="删除派生指标">×</button></div><label>指标名称<input class="derived-label" maxlength="80" value="${esc(item.label)}" placeholder="如：暂估单位成本"></label><label>汇总后公式<input class="derived-expression mono" maxlength="200" value="${esc(item.expression)}" spellcheck="false"></label><label>结果单位<input class="derived-unit" value="${esc(item.unit)}" list="derived-unit-options" maxlength="40"></label>`;
  q('#derived-rows').append(el);el.querySelector('.remove-derived').onclick=()=>{el.remove();refresh()};el.querySelector('.derived-label').oninput=refresh;refresh();
 }
 root.insertAdjacentHTML('beforeend',`<datalist id="derived-unit-options">${units.map(u=>`<option value="${u}">`).join('')}</datalist>`);
 q('#add-derived').onclick=()=>add();(definition.derived||[]).forEach(add);refresh();
 if([...q('#model-display').options].some(x=>x.value===definition.display_metric))q('#model-display').value=definition.display_metric;
 return {refresh,hasRows:()=>all('.derived-row').length>0,collect:()=>({derived:all('.derived-row').map(el=>({label:el.querySelector('.derived-label').value.trim(),expression:el.querySelector('.derived-expression').value.trim(),unit:el.querySelector('.derived-unit').value.trim()})),display_metric:q('#model-display').value||'m0'})};
}

export function derivedExplanation(result,esc,selectedOnly=false){
 if(!result.derived_notice)return '';
 const readable=m=>m.expression.replace(/\bm\d\b/g,key=>'【'+(result.measures.find(x=>x.key===key)?.label||key)+'】').replaceAll('/','÷').replaceAll('*','×');
 return `<div class="derived-summary"><p>${esc(selectedOnly?'未发布派生 · 先汇总后计算，缺失与零分母留空。':result.derived_notice)}</p>${result.measures.filter(m=>m.expression&&(!selectedOnly||m.key===result.display_metric)).map(m=>`<p><b>${esc(m.label)}</b>：${esc(readable(m))}，换算为${esc(m.unit)}</p>`).join('')}${result.derived_notes.length?`<details><summary>${result.derived_notes.length} 项分组派生值未计算</summary><ul>${result.derived_notes.slice(0,50).map(n=>`<li>${esc(n.dimension)} · ${esc(n.metric)}：${esc(n.reason)}</li>`).join('')}</ul>${result.derived_notes.length>50?'<p>仅展开前50项；完整原因见口径。</p>':''}</details>`:''}</div>`;
}
