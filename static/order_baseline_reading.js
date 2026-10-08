import {baselineTrialChanges} from './baseline_trial.js';
export const baselineTime=v=>typeof v==='string'&&v?v.replace('T',' '):'未形成时间';
export const baselineNumber=v=>typeof v==='number'&&Number.isFinite(v)?v.toLocaleString('zh-CN',{maximumFractionDigits:2}):'未计算';
export const baselineStatus=s=>({scheduled:'已排入',late:'晚于内部目标',blocked:'未排完',paused:'资料暂停'}[s]||s||'未计算');
const value=(v,esc)=>v==null?'缺失':esc(v);

// Selection is an in-memory reading lens over complete authorized results.
// It neither recalculates the study nor becomes an API/URL data filter.
export function baselineSelection(d,{order='',link='',bom='all'}={}){
 if(!['all','different','same'].includes(bom))throw Error('用料核对范围无效');
 if(order&&!d.orders.some(r=>r.id===order))throw Error('订单行不属于当前基线');
 const links=d.links.filter(r=>!order||r.order_line_id===order);
 if(link&&!links.some(r=>r.id===link))throw Error('批次映射不属于所选订单范围');
 const selected=links.filter(r=>!link||r.id===link),ids=new Set(selected.map(r=>r.id));
 const allBom=d.bom.filter(r=>ids.has(r.link_id));
 return {order,link,bom,links,selected,allBom,bomRows:allBom.filter(r=>bom==='all'||(bom==='same'?r.matches_trial===true:r.matches_trial===false)),
  changes:d.changes.filter(r=>ids.has(r.link_id)),orderRow:d.orders.find(r=>r.id===order)||null};
}

export function baselineSources(rows,{esc,table}){
 return table(['业务对象','Excel / 工作表 / 行','当前来源版本'],rows.map(s=>[
  `${esc(s.dataset)}<small class="block">${esc(s.key)}</small>`,s.missing?'来源缺失':`${esc(s.filename)}<br>${esc(s.sheet)} · 第 ${esc(s.row)} 行`,
  s.missing?'缺失':`v${esc(s.revision)} · 源行 ${esc(s.source_row_id)}`]));
}

export function baselineBom(rows,{esc,table}){
 if(!rows.length)return '<p class="empty">当前阅读范围没有用料行；不代表零需求或完整齐套。</p>';
 return table(['冻结快照 / 原 BOM / 版本','批次 / 订单行 / 工序','物料 / 冻结单位','单耗 × (1+损耗) / 步长','安排台数 / 冻结需求','当前试排需求与绑定 / 核对'],rows.map(b=>[
  `${esc(b.id)}<small class="block">${esc(b.source_bom_id)} / ${esc(b.version)}</small>`,`${esc(b.job_id)}<small class="block">${esc(b.order_line_id)}<br>${esc(b.process)} / ${esc(b.route_id)}</small>`,
  `${esc(b.material_id)} / ${esc(b.unit)}`,`${value(b.unit_qty,esc)} × (1+${value(b.scrap_allowance,esc)})<small class="block">步长 ${value(b.quantum,esc)}</small>`,
  `${value(b.plan_qty,esc)} 台 / ${value(b.required_qty,esc)} ${esc(b.unit)}`,
  `${b.trial_demands.map(x=>`${value(x.qty,esc)} ${esc(x.unit)}<small class="block">${esc(x.id)} / ${esc(x.route_id)} · 步长 ${value(x.quantum,esc)}</small>`).join('；')||'缺少匹配需求'}<b class="block">${b.matches_trial?'相符':'待核对'}</b>`]));
}

export function baselineLinks(rows,{esc,table},selected=''){
 if(!rows.length)return '<p class="empty">当前范围没有可核对的批次映射；不是已经完成。</p>';
 return table(['批次 / 基线映射','原订单行 / 工单 / 分配','安排台数 / BOM / 路线','内部目标 / 基线现承诺','加工完成 / 晚于客户日期分钟','当前试排 / 字段核对 / 依据'],rows.map(l=>[
  `<button class="row-link" data-baseline-focus="${esc(l.id)}" aria-pressed="${selected===l.id}">${esc(l.job_id)}</button><small class="block">${esc(l.id)}</small>`,
  `${esc(l.order_line_id)}<br>${esc(l.work_order_id)}<br>${esc(l.allocation_id)}`,`${value(l.plan_qty,esc)} 台<br>${esc(l.bom_version)} / ${esc(l.route_version)}`,
  `${esc(baselineTime(l.internal_due))}<br>${esc(l.due)}`,`${esc(baselineTime(l.finished))}<br>${baselineNumber(l.customer_late_minutes)}`,
  `${esc(baselineStatus(l.trial_state))}<small class="block">${l.source_changed?'字段变化，需重核':'已核对字段一致'}</small><button class="row-link" data-baseline-link="${esc(l.id)}">查看批次依据</button>`]));
}

export function baselineLinkDetail(d,h){
 const {esc,table,panel}=h,r=d.row;
 const identity=[['基线映射',r.id],['试排批次',r.job_id],['原订单 / 订单行',`${r.order_id} / ${r.order_line_id}`],['原工单 / 分配',`${r.work_order_id} / ${r.allocation_id}`],['配置编码',r.product_id],
  ['本批安排（台）',r.plan_qty],['基线订单 / 工单 / 分配（台）',`${r.order_qty} / ${r.work_order_qty} / ${r.allocation_qty}`],['工单 BOM / 路线版本',`${r.bom_version} / ${r.route_version}`],
  ['基线记录的配置 BOM / 路线版本',`${r.product_bom_version} / ${r.product_route_version}`],['基线工单状态',r.work_status],['分配生效日期',r.allocation_effective],['客户原承诺日期',r.original_due],
  ['基线现承诺日期',r.due],['试排内部完成目标',baselineTime(r.internal_due)],['当前试排加工完成',baselineTime(r.finished)],['晚于基线客户日期（分钟）',baselineNumber(r.customer_late_minutes)],
  ['当前试排状态',baselineStatus(r.trial_state)],['快照声明用料行数',r.bom_count],['映射依据',r.note]];
 return `<p class="source">${esc(d.notice)}</p>`+panel('批次、订单与版本','',table(['核对项目','基线或当前试排结果'],identity.map(([k,v])=>[k,value(v,esc)])))+
  panel('该批次冻结用料','单位和绑定逐行核对，不合计不同物料或单位。',baselineBom(d.bom,h))+
  panel('该批次字段差异','',baselineTrialChanges(d.changes,h))+
  panel('该批次直接来源','其他批次的共享竞争须另看全方案来源。',baselineSources(d.sources,h))+
  `<p class="source">${d.can_download_original?'管理员可在导入页读取归档原件。':'来源索引不授予原件下载权限。'}</p>`;
}
