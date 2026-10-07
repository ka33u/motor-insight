export function firstReviewSummary(d,{esc,panel,table}){
 if(!d.review_summary)return '';
 return panel('实测证据 × 复核登记',`<p class="source">${esc(d.review_notice)}</p><p class="source">按当前完整筛选范围统计，一个计划只落入一格。点击非零数量，查看同时符合两种状态的计划。</p>`+
  table(['实测证据 / 复核登记',...Object.values(d.review_labels)],Object.entries(d.states).map(([state,label])=>[esc(label),...Object.keys(d.review_labels).map(review=>{const n=d.review_matrix[state][review];return n?`<a href="#first-piece?${new URLSearchParams({...d.filters,state,review})}">${n}</a>`:'0'})]))+
  `<p>${Object.entries(d.review_labels).map(([k,label])=>`${esc(label)} ${d.review_summary[k]}`).join(' · ')}</p>${d.unmatched_reviews?.length?`<p>另有 ${d.unmatched_reviews.length} 条登记未对应首件队列：${d.unmatched_reviews.map(r=>`${esc(r.id)} / ${esc(r.plan_id)}`).join('；')}。请从业务数据核对来源计划。</p>`:''}`);
}
export function firstReviewCell(review,{esc}){
 if(!review)return '无生效复核';
 const s=review.selected;
 return `<span>${esc(review.label)}</span><small class="block">${s?`${esc(s.id)} · v${esc(s.version)}<br>${esc(s.decision)} · ${esc(s.reviewer_id)}`:'未见已知有效版本'}<br>${review.reasons.map(esc).join('；')}</small>`;
}
export function firstReviewDetail(review,{esc,table,panel}){
 if(!review)return '';
 return panel('复核依据与完整版本',firstReviewCell(review,{esc})+`<p class="source">台账文件号不证明原件已审阅或电子签名有效。未来登记和草稿保留在履历中，不替代当前生效版本。</p>`+
  table(['版本 / 状态','登记原结论','依据检验 / 截止','复核 / 登记时间','人员 / 文件 / 原因'],review.history.map(r=>[`${esc(r.id)}<small class="block">v${esc(r.version)} · ${esc(r.status)} · 前版 ${esc(r.previous_id||'无')}</small>`,esc(r.decision),`${esc(r.check_id||'未检')}<small class="block">${esc(r.basis_at)}</small>`,`${esc(r.reviewed)}<small class="block">${esc(r.registered)}</small>`,`${esc(r.reviewer_id)} · ${esc(r.reference)}<small class="block">${esc(r.note)}</small>`]))+
  `<details><summary>查看登记与当前依据摘要</summary><p class="mono" style="overflow-wrap:anywhere">登记依据：${esc(review.selected?.basis_hash||'无')}<br>按登记截止重放：${esc(review.replayed_basis_hash||'未计算')}<br>当前依据：${esc(review.current_basis_hash)}<br>当前规则：${esc(review.current_rule_hash)}</p><p class="source">重放使用当前导入事实；摘要不能证明历史数据库或人员签字真实性。</p></details>`);
}
