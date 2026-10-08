export function returnEvidence(data,{esc,table,amount}){
 const report=data.return_reconciliation;
 if(!report)return '';
 const rows=report.rows;
 return `<details ${rows.length?'open':''}><summary>生产退料与原领料核对 · ${rows.length} 条</summary><p class="source">${esc(report.notice)}</p>`+
 (rows.length?table(['退料流水 / 原领料','原工单 / 退料工单','物料 / 原批次 / 退回库位','时间与原登记数量','关联核对'],rows.map(r=>[
  `${esc(r.id)}<small class="block">${esc(r.issue_id||'未关联')}</small>`,
  `${esc(r.issue?.work_order_id||'未核对')} / ${esc(r.work_order_id||'未登记')}`,
  `${esc(r.material_id)}<small class="block">${esc(r.lot+' / '+r.location)}</small>`,
  `${esc(r.occurred)}<small class="block">库存增减 ${amount(r.qty_signed,r.unit||'单位待核对')}</small>`,
  r.verified?'关联与累计量可核对':r.issues.map(x=>`<p class="inline-error">${esc(x)}</p>`).join('')])):'<p class="empty">截至时点没有关联的生产退料登记。</p>')+'</details>';
}

export function issueBalance(item,{esc,table,amount}){
 const known=item.issue_balance_known!==false;
 return `<h4>累计领料与退料</h4>`+table(['累计领料','可核对退料','净领料','待领需求'],[[amount(item.gross_issued_qty,item.unit),amount(item.returned_qty,item.unit),amount(item.issued_qty,item.unit),amount(item.remaining_required,item.unit)]])+
 (known?'':'<p class="inline-error">领退料证据待核对，累计量、净领料和待领需求留空，不以部分记录代替完整结果。</p>')+
 table(['领料记录','发生时间','批次 / 库位','已领数量'],item.issue_rows.map(r=>[esc(r.id),esc(r.occurred),esc(r.lot+' / '+r.location),amount(r.qty,item.unit)]));
}
