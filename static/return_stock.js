export function returnStockRows(rows,{esc,table,amount,interactive=true}){
 return table(['退料 / 原领料','工单 / 原工单','物料 / 批次 / 退回库位','原退料量','单据关联','退料时 → 当前状态','证据核对'],rows.map(r=>[
  (interactive?`<button class="text-button" data-return-stock="${esc(r.id)}">${esc(r.id)}</button>`:esc(r.id))+`<small class="block">${esc(r.issue_id||'未关联')}</small>`,
  `${esc(r.work_order_id||'未登记')}<small class="block">${esc(r.original_work_order_id||'原工单未核对')}</small>`,
  `${esc(r.material_id)} · ${esc(r.material)}<small class="block">${esc(r.lot)} / ${esc(r.location)}</small>`,amount(r.qty_signed,r.unit),
  r.document_verified?'关联与累计量可核对':'单据待核对',
  `${esc(r.arrival_state||'待核对')} → ${esc(r.current_state||'待核对')}`,
  r.issues.length?r.issues.map(x=>`<p class="inline-error">${esc(x)}</p>`).join(''):'已导入证据未见问题'
 ]));
}

export function returnStockLot(lot,{esc,table,amount}){
 if(!lot)return '<p class="empty">库位台账缺失，数量与状态未知。</p>';
 return `<p>${esc(lot.material_id)} · ${esc(lot.lot)} / ${esc(lot.location)}<br>登记状态 ${esc(lot.recorded_state)}；可核对状态 ${esc(lot.state||'待核对')}<br>库位总余额 ${amount(lot.balance_qty,lot.unit)}，可用状态余额 ${amount(lot.usable_state_qty,lot.unit)}</p>`+
  '<p class="source">这是整组物料×批次×库位余额，不能认定为单笔退料的剩余量。</p>'+
  lot.issues.map(x=>`<p class="inline-error">${esc(x)}</p>`).join('')+
  table(['期初来源','期初日期','数量 / 状态'],lot.opening.map(r=>[esc(r.id),esc(r.as_of),amount(r.qty,lot.unit)+' / '+esc(r.status)]))+
  table(['时点 / 来源','事件','库存增减 → 运行余额','登记后状态','问题'],lot.timeline.map(r=>[
   esc(r.occurred)+'<small class="block">'+esc(r.id)+'</small>',esc(r.kind),amount(r.qty_signed,lot.unit)+' → '+amount(r.running_qty,lot.unit),esc(r.state),r.issues.map(esc).join('；')]))+
  table(['状态依据','原状态 → 新状态','登记批准工号','变更原因'],lot.status_events.map(r=>[esc(r.id),esc(r.from_status)+' → '+esc(r.to_status),esc(r.approver_id),esc(r.reason)]));
}

export function createReturnStock({api,esc,num,header,panel,table,chart,modal,toast,go,$,$$,on,isCurrent,getModalRevision}){
 let scope={},receipt='',token=0,serial=0;
 const amount=(v,u)=>`${v==null?'—':num(v,3)} ${esc(u||'单位待核对')}`,helpers={esc,table,amount};
 const query=extra=>new URLSearchParams({...scope,receipt,...extra});
 const nav=extra=>go('supply',{tab:'returns',...scope,...extra});
 const safe=fn=>(...args)=>Promise.resolve(fn(...args)).catch(e=>toast(e.message));
 async function requestDetail(key,sourcePage){
  const sn=++serial,activeToken=token;
  modal(sourcePage?'退料Excel来源':'退料与库位证据','<p role="status">正在读取同一版本的证据…</p>');
  const mr=getModalRevision();
  try{
   const d=await api('return-stock/rows/'+encodeURIComponent(key)+(sourcePage?'/evidence':'')+'?'+query(sourcePage?{page:sourcePage}:{}));
   if(!isCurrent(activeToken)||sn!==serial||mr!==getModalRevision()||!$('#detail').open)return;
   if(sourcePage){
    modal('退料Excel来源 · '+key,table(['对象 / 编号','Excel文件 / 工作表 / 行号','原件'],d.rows.map(r=>[
     esc(r.dataset)+'<br>'+esc(r.key),r.missing?'来源缺失':esc(r.filename)+'<br>'+esc(r.sheet)+' · 第'+esc(r.row)+'行',
     d.can_download_original&&r.batch_id?`<a href="/api/imports/${esc(r.batch_id)}/file">下载原件</a>`:'—']))+
     `<div class="pagination"><span>${d.total}条来源 · 第${d.page}页</span><button id="rs-source-prev" ${sourcePage<=1?'disabled':''}>上一页</button><button id="rs-source-next" ${sourcePage*d.size>=d.total?'disabled':''}>下一页</button><button id="rs-back">返回退料详情</button></div>`);
    on('#rs-source-prev','click',safe(()=>requestDetail(key,sourcePage-1)));on('#rs-source-next','click',safe(()=>requestDetail(key,sourcePage+1)));on('#rs-back','click',safe(()=>requestDetail(key)));return;
   }
   const r=d.row,origin=d.original_issue;
   modal('退料与库位证据 · '+key,returnStockRows([r],{...helpers,interactive:false})+`<p class="source">${esc(d.note)}<br>${esc(d.state_note)}</p>`+
    panel('原领料依据','保留原数量、发生时间与工单，不用净额覆盖原行。',origin?table(['原领料','时点','物料 / 批次 / 库位','数量增减','工单 / 来源单号'],[[esc(origin.id),esc(origin.occurred),esc(origin.material_id+' / '+origin.lot+' / '+origin.location),amount(origin.qty_signed,d.original_unit),esc(origin.work_order_id+' / '+origin.reference)]]):'<p class="empty">原领料未能关联。</p>')+
    panel('退回库位','状态变更按库存台账核对，不替代检验报告或授权有效性核对。',returnStockLot(d.target_lot,helpers))+
    `<details><summary>原领料库位的完整收发与状态</summary>${returnStockLot(d.origin_lot,helpers)}</details>`+
    `<div class="toolbar"><button id="rs-sources">查看完整Excel来源</button><button id="rs-material">打开物料库存</button><button id="rs-work">查看工单备料</button></div>`);
   on('#rs-sources','click',safe(()=>requestDetail(key,1)));
   on('#rs-material','click',()=>{$('#detail').close();go('supply',{tab:'stock',material_id:r.material_id});});
   on('#rs-work','click',()=>{$('#detail').close();go('material-planning',{work_order:r.original_work_order_id||r.work_order_id});});
  }catch(e){if(isCurrent(activeToken)&&sn===serial&&mr===getModalRevision()&&$('#detail').open)modal('退料证据读取失败',`<p class="inline-error" role="alert">${esc(e.message)}</p>`);}
 }
 return async function render(params,activeToken){
  token=activeToken;const sn=++serial;receipt='';
  scope=Object.fromEntries([...params].filter(([k])=>['material_id','work_order_id','q','stage','page'].includes(k)));
  const d=await api('return-stock?'+new URLSearchParams(scope));if(!isCurrent(activeToken)||sn!==serial)return;
  receipt=d.receipt;const s=d.summary,f=d.filters;
  const cards=[['退料登记',s.returns+'笔','当前应用范围'],['目标批次库位',s.target_lots+'组','多个退料指向同库位仅计一次'],['单据关联可核对',s.documents_verified+' / '+s.returns,'不代表质量放行'],['有证据待核对',s.attention+'笔','含关联、库位或同刻时序问题']];
  $('#main').innerHTML=header('退料与库存状态核对','并列核对单据、退料时状态和当前库位。','<a href="#material-planning">工单备料试配 ↗</a>')+
   `<div class="notice">已导入模拟Excel · 截至 ${esc(d.as_of.replace('T',' '))}</div><div class="catalog-tabs"><button id="rs-stock">物料与库存</button><button id="rs-purchase">采购与来料</button><button class="active" aria-current="page">退料与库存状态</button></div>`+
   `<form id="rs-scope" class="supply-filters"><label>物料编码<input name="material_id" value="${esc(f.material_id)}"></label><label>工单编号<input name="work_order_id" value="${esc(f.work_order_id)}"></label><label>退料、原领料、物料或批次<input name="q" value="${esc(f.q)}"></label><div><button class="primary">应用范围</button><button type="button" id="rs-reset">重置</button></div></form>`+
   `<p class="source">${esc(d.note)}</p><div class="quality-kpis">${cards.map(([a,b,c])=>`<article><small>${a}</small><strong>${b}</strong><span>${c}</span></article>`).join('')}</div>`+
   `<div class="grid">${panel('单据关联与当前库存状态','按退料笔数比较；同一退料只归入一个当前状态。',chart(d.matrix,'label','returns','bar','document_verified')+'<div class="legend"><span><i></i>全部退料</span><span><i class="pale"></i>单据关联可核对</span></div>'+table(['当前状态','全部退料笔数','单据关联可核对'],d.matrix.map(r=>[esc(r.label),num(r.returns),num(r.document_verified)])))}${panel('退回数量与库位现存量','目标余额按唯一库位去重，不分摊到退料；不同单位分别显示。',table(['单位','退料笔数 / 目标库位','可核对退回量','目标库位总余额','目标可用状态余额','未知库位数'],d.units.map(r=>[esc(r.unit),`${r.returns} / ${r.target_lots}`,amount(r.returned_qty,r.unit),amount(r.target_balance_qty,r.unit),amount(r.target_usable_qty,r.unit),num(r.unknown_lots)]))+`<p class="source">${esc(d.state_note)} 退料时状态明确 ${s.arrival_known} / ${s.returns}笔，当前库位证据可核对 ${s.current_verified} / ${s.returns}笔。</p>`)}</div>`+
   '<h2 class="quality-section-title">退料核对清单</h2><p class="source">上方使用完整应用范围；下方状态筛选清单与导出。“有证据待核对”可与当前可用或受限状态重叠。</p>'+
   `<div class="delivery-stage-filters">${Object.entries(d.stages).map(([k,v])=>`<button data-rs-stage="${esc(k)}" class="${f.stage===k?'active':''}">${esc(v)}<b>${d.facets[k]}</b></button>`).join('')}</div>`+
   `<div class="toolbar"><span>${d.total}笔符合清单条件</span><a href="/api/return-stock/export?${esc(query())}">导出完整清单与去重库位</a></div>`+returnStockRows(d.rows,helpers)+
   `<div class="pagination"><span>第${d.page} / ${Math.max(1,Math.ceil(d.total/d.size))}页</span><button id="rs-prev" ${d.page<=1?'disabled':''}>上一页</button><button id="rs-next" ${d.page*d.size>=d.total?'disabled':''}>下一页</button></div>`;
  $$('[data-return-stock]').forEach(b=>b.addEventListener('click',safe(()=>requestDetail(b.dataset.returnStock))));
  on('#rs-scope','submit',e=>{e.preventDefault();go('supply',{tab:'returns',...Object.fromEntries(new FormData(e.target))});});on('#rs-reset','click',()=>go('supply',{tab:'returns'}));
  on('#rs-stock','click',()=>go('supply',{tab:'stock',material_id:f.material_id}));on('#rs-purchase','click',()=>go('supply',{tab:'purchase',material_id:f.material_id}));
  $$('[data-rs-stage]').forEach(b=>b.addEventListener('click',()=>nav({stage:b.dataset.rsStage,page:1})));
  on('#rs-prev','click',()=>nav({page:d.page-1}));on('#rs-next','click',()=>nav({page:d.page+1}));
 };
}
