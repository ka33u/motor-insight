export function quantileExplanation(result,esc,label=''){
 if(!result?.quantile_notice)return '';
 const labels=new Map((result.measures||[]).map(m=>[m.key,m.label]));
 const rows=result.pivot?[...result.pivot.row_totals,...result.pivot.column_totals.map(r=>({...r,dimension:'列合计 · '+r.dimension})),{...result.pivot.grand_total,dimension:'总计'}]:result.rows||[];
 const details=rows.flatMap(r=>Object.entries(r.quantiles||{}).map(([key,q])=>({dimension:r.dimension,key,...q})));
 return `<div class="quantile-summary"><p><b>${label?esc(label)+' · ':''}分位统计</b> · 按每条有效来源记录等权计算；中位数为 P50。</p><details><summary>计算方法与样本依据 · ${details.length} 项分组度量</summary><p class="panel-note">${esc(result.quantile_notice)}</p><div class="table-wrap"><table><thead><tr><th>分组</th><th>度量 / 分位</th><th>有效 / 来源</th><th>缺失</th><th>排序位置（从1起）</th><th>端点值</th></tr></thead><tbody>${details.map(q=>`<tr><td>${esc(q.dimension)}</td><td>${esc(labels.get(q.key)||q.key)} · P${esc(q.percentile)}</td><td>${esc(q.valid_rows)} / ${esc(q.source_rows)}</td><td>${esc(q.missing_rows)}</td><td>${q.valid_rows?esc(q.lower_rank)+'–'+esc(q.upper_rank):'—'}</td><td>${q.valid_rows?esc(q.lower_value)+' / '+esc(q.upper_value)+(q.interpolated?' · 插值':' · 实际排序值'):'无有效数值'}</td></tr>`).join('')}</tbody></table></div>${result.pivot?'<p class="panel-note">此处列出各合计；交叉单元格显示有效样本数，点击可查该格计算依据。</p>':''}</details></div>`;
}
