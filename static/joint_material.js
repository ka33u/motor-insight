// Material quantities come from the server's Decimal reconciliation, never JS totals.
const local=v=>v?.replace('T',' ')||'未形成时间';
export function jointMaterialLink(id,unit,label,{esc}) {
 return `<button class="row-link" data-joint-material-id="${esc(id)}" data-joint-material-unit="${esc(unit)}">${esc(label??id)}</button>`;
}
export function materialQuantityBars(e,{esc}) {
 const s=e.summary,scale=Math.max(Number(s.required_qty),Number(s.total_supply_qty));
 const tracks=[['需求', [['reserved','已预留',s.reserved_qty],['pending','未预留',s.unreserved_qty]]],
  ['供给', [['excluded','排除',s.excluded_qty],['reserved','已预留',s.reserved_qty],['remaining','范围内剩余',s.horizon_remaining_qty],['outside','范围外剩余',s.outside_remaining_qty]]]];
 if(!Number.isFinite(scale)||scale<=0||tracks.some(([,segments])=>segments.some(([,name,value])=>!Number.isFinite(Number(value))||Number(value)<0)))return '<p class="source">数量图未形成有效比例；请按下方原量核对。</p>';
 return '<div class="joint-material-bars">'+tracks.map(([label,segments])=>{
  const words=segments.map(([,name,value])=>`${name} ${value} ${e.balance.unit}`).join('；');
  return `<div><b>${label}</b><div class="joint-material-track" role="img" aria-label="${esc(label+'：'+words)}">${segments.map(([cls,name,value])=>`<i class="${cls}" style="width:${100*Number(value)/scale}%" title="${esc(name+' '+value+' '+e.balance.unit)}"></i>`).join('')}</div><p>${segments.map(([cls,name,value])=>`<span class="joint-material-key"><i class="${cls}" aria-hidden="true"></i>${esc(name+' '+value+' '+e.balance.unit)}</span>`).join('；')}</p></div>`;
 }).join('')+`<p class="source">两条数量刻度一致，上限 ${esc(String(scale))} ${esc(e.balance.unit)}；仅表示总量构成，不是到料时间轴或时间齐套判定。</p></div>`;
}
export function jointMaterialDetail(d,h) {
 const {esc,panel,table,sourceTable}=h,e=d.evidence,b=e.balance,s=e.summary;
 const task=id=>`<button class="row-link" data-joint-material-task="${esc(id)}">${esc(id)}</button>`;
 const status=v=>({blocked:'批次未排完',late:'晚于内部目标',scheduled:'按假设已排'}[v]||'未计算');
 return `<p class="source">${esc(b.material_id)} · ${esc(b.material_name)} / ${esc(b.unit)}<br>${esc(local(e.baseline))} — ${esc(local(e.horizon_end))}<br>${esc(e.notice)}</p>`+
  panel('需求与供给构成','同一物料原单位，完整方案内核对。',materialQuantityBars(e,h)+
   `<p>${s.demands} 条整批需求，其中 ${s.reserved_demands} 条已预留；涉及 ${s.jobs} 个批次、${s.lots} 个供给批次、${s.allocations} 笔分配。</p>`+
   table(['整批需求','范围内可用供给','原总量缺口','已预留','未预留'],[[esc(s.required_qty),esc(b.horizon_usable_qty),esc(b.initial_supply_gap_qty),esc(s.reserved_qty),esc(s.unreserved_qty)]]))+
  panel('同料批次用量','按整批需求汇总，不逐工序份号重复计量。',table(['批次 / 配置','台数 / 内部应完成','原试排批次状态','已预留行 / 需求行','所需 / 已预留 / 未预留（'+b.unit+'）'],e.jobs.map(j=>[
   `${esc(j.id)}<small class="block">${esc(j.product_id)}</small>`,`${esc(j.qty)}<small class="block">${esc(local(j.due))}</small>`,status(j.state),`${j.reserved_demands} / ${j.demands}`,`${esc(j.required_qty)} / ${esc(j.reserved_qty)} / ${esc(j.unreserved_qty)}`])))+
  panel('需求与适用任务','未预留须结合任务原阻断原因；同一路线各份号共用整批需求。',table(['需求 / BOM版本','批次 / 路线','所需 / 已预留 / 未预留','实际预留触发 / 时刻','适用任务'],e.demands.map(n=>[
   `${esc(n.id)}<small class="block">${esc(n.bom_id)} / ${esc(n.bom_version)}</small>`,`${esc(n.job_id)}<br>${esc(n.route_id)}`,`${esc(n.required_qty)} / ${esc(n.reserved_qty)} / ${esc(n.unreserved_qty)}`,
   n.reservation?task(n.reservation.task_id)+`<small class="block">${esc(local(n.reservation.reserved_at))}</small>`:'未预留',n.task_ids.map(task).join('<br>')])))+
  panel('供给批次与排除','隔离批次整批排除；可用 = 已预留 + 剩余。范围终点及之后到料不参与本次试排。',table(['供给 / 模拟批号','可用时间 / 范围','账面 / 其中不可预留','总排除 / 可用','已预留 / 剩余','原状态 / 类型'],e.lots.map(l=>[
   `${esc(l.id)}<small class="block">${esc(l.lot)}</small>`,`${esc(local(l.available_from))}<small class="block">${l.inside_horizon?'范围内到料':'范围外到料'}</small>`,`${esc(l.qty)} / ${esc(l.unavailable_qty)}`,`${esc(l.excluded_qty)} / ${esc(l.usable_qty)}`,`${esc(l.reserved_qty)} / ${esc(l.remaining_qty)}`,`${esc(l.status)} / ${esc(l.kind)}`])))+
  panel('原试排分配流水','原算法顺序；预留时刻可能不单调，不能据此解释现场领料先后。',table(['原流水序号','需求 / 供给','触发任务 / 批次','预留量（'+b.unit+'）','供给可用 / 预留时刻'],e.allocations.map(a=>[
   a.sequence,`${esc(a.demand_id)}<br>${esc(a.supply_id)}`,task(a.task_id)+`<small class="block">${esc(a.job_id)}</small>`,esc(a.qty),`${esc(local(a.available_from))}<br>${esc(local(a.reserved_at))}`])))+
  panel('适用任务状态','点完整编号核查候选人机、首阻断与任务直接来源。',table(['任务 / 工序','状态','原未排原因 / 首阻断'],e.tasks.map(t=>[task(t.id)+`<small class="block">${esc(t.process)} / ${esc(t.branch)}</small>`,t.state==='scheduled'?'已排入':'未排入',`${esc(t.reason||'无阻断')}<small class="block">${t.root_tasks.map(esc).join('、')}</small>`])))+
  panel('该物料直接 Excel 来源','派序与共享人机竞争仍需核对全方案；顶部完整导出不受物料阅读影响。',sourceTable(d.sources))+
  `<p class="source">${d.can_download_original?'管理员可在导入页读取归档原件。':'来源索引不授予原件下载权限。'}</p>`;
}
