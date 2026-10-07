export function scopeSummaryMarkup(summary,esc,num,labels={primary:'当前范围',reference:'对照范围'}){
 if(!summary)return '<p class="panel-note">此旧快照未保存整范围摘要，历史结果按原有分组读取。</p>';
 const names={ready:'整范围已重算',partial:'仅有效部分',empty:'已知范围为空',no_source:'来源未采集',no_sample:'没有有效样本',undefined:'无有效结果',blocked:'摘要暂停'};
 const number=v=>typeof v==='number'?num(v,4):esc(v??'—');
 const sides=['primary','reference'].filter(side=>summary[side]).map(side=>{
  const s=summary[side],metric=s.metric_receipt;
  return `<div class="population-summary-side"><small>${esc(labels[side])} · ${esc(names[s.state]||s.state)}</small><div class="population-summary-value">${number(s.value)} <span>${esc(s.unit||'')}</span></div><small>来源 ${num(s.source_rows)} · 有效 ${num(s.valid_rows)} · 缺失 ${num(s.missing_rows)}</small><p>${esc(s.reason)}</p>${s.denominator!==null?`<small>分子 ${number(s.numerator)} / 分母 ${number(s.denominator)}</small>`:''}<small>${metric?'发布指标 '+esc(metric.key)+' v'+metric.version:'未发布分析定义'} · 模型v${s.model_version}</small></div>`;
 }).join('');
 const c=summary.comparison;
 return `<div class="population-summary"><b>所选度量 · 整个筛选范围</b><div class="population-summary-sides">${sides}</div>${c?`<p class="population-summary-comparison">${c.blocked?'差值暂停：'+esc(c.reason):'描述性差值 '+(c.delta>0?'+':'')+number(c.delta)+' '+esc(c.delta_unit)+(c.relative_pct!==null?' · 相对变化 '+(c.relative_pct>0?'+':'')+number(c.relative_pct)+'%':'')} </p>`:''}<details><summary>重算口径、样本与算法依据</summary><p>${esc(summary.notice)}</p>${['primary','reference'].filter(side=>summary[side]).map(side=>{const s=summary[side];return `<p><b>${esc(labels[side])}</b> · ${esc(s.label)} · ${esc(s.grain)} · 日期口径 ${esc(s.scope.date_label)}</p><pre class="code-block">${esc(JSON.stringify({measure:s.measure,scope:s.scope,definition_hash:s.definition_hash,model_version:s.model_version,published_metric:s.metric_receipt,components:s.components,quantile:s.quantile,missing_notes:s.notes,population_digest:s.population_digest,algorithm:s.algorithm},null,2))}</pre>`}).join('')}</details></div>`;
}
export function scopeSummaryComparisonMarkup(c,esc,num){
 if(!c)return '';
 return `<p class="population-summary-comparison">整范围摘要 · ${c.blocked?'差值暂停：'+esc(c.reason):'保存值 '+num(c.reference,4)+' → 当前值 '+num(c.primary,4)+' · 差值 '+(c.delta>0?'+':'')+num(c.delta,4)+' '+esc(c.delta_unit)}</p>`;
}
