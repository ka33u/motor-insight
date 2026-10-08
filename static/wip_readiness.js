export const timeLabels={ended:'已结束时间登记',open:'截止时未结束',unknown:'时间待核对',future:'未来登记，不计截止前报工'};
export function readinessRows(rows,{esc,num,table,interactive=true}){
 const qty=v=>v==null?'—':num(v);
 return table(['工单 / 配置','工单登记','报工笔数：结束 / 未结束 / 待核','装配SN','定子 / 转子在制件数','待领资料 / 重排'],rows.map(r=>[
  (interactive?`<button class="text-button" data-wr-key="${esc(r.id)}">${esc(r.id)}</button>`:esc(r.id))+`<small class="block">${esc(r.product_id)} · ${esc(r.model)}</small>`,
  `${esc(r.status)}<small class="block">计划 ${qty(r.planned_qty)} 台 · ${esc(r.bom_version)}</small>`,
  `${r.ended_reports} / ${r.open_reports} / ${r.unknown_reports}<small class="block">未来 ${r.future_reports} 笔另列</small>`,
  `${r.assembled_sn}<small class="block">待核 ${r.unknown_sn}</small>`,
  r.wip_groups.map(g=>`${esc(g.kind)} ${qty(g.wip_qty)}<small class="block">${g.verified_roots} / ${g.roots} 原批次可核对</small>`).join(''),
  `${r.material_uncomputed?'整单待领未计算':r.material_attention?'整单待领资料待核对':r.material_count+'项物料可查'}<small class="block">剩余工序排程尚未计算</small>`
 ]));
}

export function readinessDetail(d,{esc,num,table,panel}){
 const quantity=(v,u='件')=>(v==null?'—':num(v,3))+' '+esc(u);
 return readinessRows([d.row],{esc,num,table,interactive:false})+`<p class="source">${esc(d.note)}<br>${esc(d.boundary)}</p>`+
  panel('需要补齐的重排依据','按责任岗位核对；目前没有工单被判定为可重排。',table(['责任岗位','待补证据'],d.gaps.map(g=>[esc(g.owner),esc(g.need)])))+
  panel('在制份额与位置','只汇总原批次份额；整箱数量可能包含其他工单，不累加。隔离与返工份额不表示可投入。',
   table(['分支','原批次 / 已核对','完整在制件数','已知部分 / 未知批次'],d.row.wip_groups.map(g=>[esc(g.kind),g.roots+' / '+g.verified_roots,quantity(g.wip_qty),quantity(g.known_wip_qty)+' / '+g.unknown_roots]))+
   table(['原批次','周转批次 / 位置','位置类别','分支','本批份额','整箱数量'],d.positions.map(p=>[esc(p.root_id),esc(p.lot_id+' / '+p.location),esc(p.location_kind),esc(p.kind),quantity(p.qty),quantity(p.whole_lot_qty)]))+
   table(['原批次','核对状态','证据问题'],d.roots.map(r=>[esc(r.id),esc(({active:'有在制份额',attention:'待核对',missing:'缺有效基准',consumed:'全部耗用',closed:'含报废的闭合批次'})[r.state]||r.state),r.issues.map(esc).join('；')]))+
   d.wip_global_issues.map(x=>`<p class="inline-error">${esc(x)}</p>`).join(''))+
  panel('报工时间与原数量','数量逐笔保留，不跨工序累加；同名路线仅是配置当前版本候选，不能推定报工已绑定。未来结束不算截止前完成。',
   table(['报工 / 对象','工序 / 人机','开始 → 结束','截止时分类','原投入 / 良品 / 报废 / 返工','当前路线同名候选'],d.operations.map(r=>[
    esc(r.id)+'<small class="block">'+esc(r.object_type+' / '+r.object_id)+'</small>',esc(r.process)+'<small class="block">'+esc([r.equipment_id,r.resource_id,r.employee_id].filter(Boolean).join(' / '))+'</small>',
    esc(r.started)+' → '+esc(r.finished||'未登记'),esc(timeLabels[r.time_state])+'<small class="block">原状态 '+esc(r.status)+'</small>',
    [r.input_qty,r.good_qty,r.scrap_qty,r.rework_qty].map(v=>v==null?'—':num(v)).join(' / '),
    (r.route_candidates.length?r.route_candidates.map(t=>esc(t.id+' / '+t.branch+' / '+t.version)).join('<br>'):'无候选')+'<small class="block">明确映射尚缺</small>'
   ])))+
  panel('整单定额与领退料','按原备料口径；整单待领不是剩余工序耗料，净领料不是线边实存，不按报工良品数扣料。',
   table(['物料','整单定额','累计领料','关联退料','净领料','整单待领','问题 / 提示'],d.materials.map(r=>[
    esc(r.material_id+' · '+r.material),...['gross_required','gross_issued_qty','returned_qty','issued_qty','remaining_required'].map(k=>quantity(r[k],r.unit)),[...r.issues,...r.warnings].map(esc).join('；')]))+
   d.material_issues.map(x=>`<p class="inline-error">${esc(x)}</p>`).join(''))+
  `<details><summary>装配SN原登记（未来记录另看原时间）</summary>${table(['SN','配置','装配时间','定子批次','转子批次'],d.units.map(r=>['id','product_id','assembly_at','stator_batch','rotor_batch'].map(k=>esc(r[k]))))}</details>`+
  `<p class="source">${esc(d.time_note)}</p>`;
}

export function createWipReadiness({api,esc,num,header,panel,table,chart,modal,toast,go,$,$$,on,isCurrent,getModalRevision}){
 let scope={},receipt='',token=0,serial=0;
 const helpers={esc,num,table,panel};
 const query=extra=>new URLSearchParams({...scope,receipt,...extra});
 const safe=fn=>(...args)=>Promise.resolve(fn(...args)).catch(e=>toast(e.message));
 async function detail(key,sourcePage){
  const sn=++serial,activeToken=token;
  modal(sourcePage?'工单Excel来源':'在制重排准备核对','<p role="status">正在读取同版工单证据…</p>');const mr=getModalRevision();
  try{
   const d=await api('wip-readiness/rows/'+encodeURIComponent(key)+(sourcePage?'/evidence':'')+'?'+query(sourcePage?{page:sourcePage}:{}));
   if(!isCurrent(activeToken)||sn!==serial||mr!==getModalRevision()||!$('#detail').open)return;
   if(sourcePage){
    modal('工单Excel来源 · '+key,table(['对象 / 编号','Excel文件 / 工作表 / 行号','原件'],d.rows.map(r=>[
     esc(r.dataset)+'<br>'+esc(r.key),r.missing?'来源缺失':esc(r.filename)+'<br>'+esc(r.sheet)+' · 第'+esc(r.row)+'行',
     d.can_download_original&&r.batch_id?`<a href="/api/imports/${esc(r.batch_id)}/file">下载原件</a>`:'—']))+
     `<div class="pagination"><span>${d.total}条来源 · 第${d.page}页</span><button id="wr-source-prev" ${sourcePage<=1?'disabled':''}>上一页</button><button id="wr-source-next" ${sourcePage*d.size>=d.total?'disabled':''}>下一页</button><button id="wr-back">返回工单核对</button></div>`);
    on('#wr-source-prev','click',safe(()=>detail(key,sourcePage-1)));on('#wr-source-next','click',safe(()=>detail(key,sourcePage+1)));on('#wr-back','click',safe(()=>detail(key)));return;
   }
   modal('在制重排准备核对 · '+key,readinessDetail(d,helpers)+'<div class="toolbar"><button id="wr-sources">查看完整Excel来源</button><button id="wr-wip">查看在制批次</button><button id="wr-material">查看整单备料</button></div>');
   on('#wr-sources','click',safe(()=>detail(key,1)));
   on('#wr-wip','click',()=>{$('#detail').close();go('wip-flow',{work_order_id:key});});
   on('#wr-material','click',()=>{$('#detail').close();go('material-planning',{work_order:key});});
  }catch(e){if(isCurrent(activeToken)&&sn===serial&&mr===getModalRevision()&&$('#detail').open)modal('工单证据读取失败',`<p role="alert" class="inline-error">${esc(e.message)}</p>`);}
 }
 return async function render(params,activeToken){
  token=activeToken;const sn=++serial;receipt='';scope=Object.fromEntries([...params].filter(([k])=>['q','work_order_id','stage','page'].includes(k)));
  const d=await api('wip-readiness?'+new URLSearchParams(scope));if(!isCurrent(activeToken)||sn!==serial)return;receipt=d.receipt;
  const s=d.summary,f=d.filters;
  $('#main').innerHTML=header('在制重排准备核对','按工单核对报工、位置与整单待领资料。','<a href="#joint-schedule">独立联立试排 ↗</a>')+
   `<div class="notice">已导入模拟Excel · 业务与登记截止 ${esc(d.as_of.replace('T',' '))}</div>`+
   `<form id="wr-scope" class="supply-filters"><label>工单编号<input name="work_order_id" value="${esc(f.work_order_id)}"></label><label>工单、配置或型号<input name="q" value="${esc(f.q)}"></label><div><button class="primary">应用范围</button><button type="button" id="wr-reset">重置</button></div></form>`+
   `<div class="quality-kpis">${[['范围内工单',s.work_orders,'以工单为粒度'],['有截止前报工',s.reported,'记录存在，不表示路线已完工'],['有核定在制份额',s.positions,'仅已知部分，分支不合计台数'],['完工登记仍有在制',s.closed_wip,'核对耗用、报废与结单登记']].map(([a,b,c])=>`<article><small>${a}</small><strong>${b}</strong><span>${c}</span></article>`).join('')}</div>`+
   `<p class="source">${esc(d.note)}</p>`+
   panel('工单登记状态与在制证据','同一工单可同时有报工和在制份额；两列有交叠，不能相加。',chart(d.matrix,'label','reported','bar','positions')+'<div class="legend"><span><i></i>有截止前报工的工单</span><span><i class="pale"></i>有核定在制份额的工单</span></div>'+table(['登记状态','工单数','有截止前报工','有核定在制份额'],d.matrix.map(r=>[esc(r.label),r.orders,r.reported,r.positions])))+
   `<p class="source">${esc(d.boundary)}<br>范围内 ${s.open} 张工单有未结束时间登记；${s.unknown} 张工单在制位置资料待核对；${s.unknown_reports} 笔报工时间待核对。</p>`+
   '<h2 class="quality-section-title">工单证据清单</h2><p class="source">上方始终使用完整应用范围；下方分类筛选清单及完整导出，类别可交叠。</p>'+
   `<div class="delivery-stage-filters">${Object.entries(d.stages).map(([k,v])=>`<button data-wr-stage="${esc(k)}" class="${f.stage===k?'active':''}">${esc(v)}<b>${d.facets[k]}</b></button>`).join('')}</div>`+
   `<div class="toolbar"><span>${d.total}张工单符合清单条件</span><a href="/api/wip-readiness/export?${esc(query())}">导出全部符合条件的工单与证据</a></div>`+
   readinessRows(d.rows,helpers)+`<div class="pagination"><span>第${d.page} / ${Math.max(1,Math.ceil(d.total/d.size))}页</span><button id="wr-prev" ${d.page<=1?'disabled':''}>上一页</button><button id="wr-next" ${d.page*d.size>=d.total?'disabled':''}>下一页</button></div>`;
  $$('[data-wr-key]').forEach(b=>b.addEventListener('click',safe(()=>detail(b.dataset.wrKey))));
  $$('[data-wr-stage]').forEach(b=>b.addEventListener('click',()=>go('wip-readiness',{...scope,stage:b.dataset.wrStage,page:1})));
  on('#wr-scope','submit',e=>{e.preventDefault();go('wip-readiness',Object.fromEntries(new FormData(e.target)));});on('#wr-reset','click',()=>go('wip-readiness',{}));
  on('#wr-prev','click',()=>go('wip-readiness',{...scope,page:d.page-1}));on('#wr-next','click',()=>go('wip-readiness',{...scope,page:d.page+1}));
 };
}
