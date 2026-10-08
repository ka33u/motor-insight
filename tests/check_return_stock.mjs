import assert from 'node:assert/strict';
import {returnStockRows,returnStockLot,createReturnStock} from '../static/return_stock.js';
let groups=0;const check=async(name,fn)=>{await fn();groups++;console.log('PASS '+name)};
const esc=v=>String(v??'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;').replaceAll("'",'&#39;');
const table=(headers,rows)=>headers.join('|')+'\n'+rows.map(r=>r.join('|')).join('\n');
const amount=(v,u)=>`${v==null?'—':v} ${esc(u||'单位待核对')}`,helpers={esc,table,amount};
const row={id:'T1',issue_id:'I1',work_order_id:'W1',original_work_order_id:'W1',material_id:'M1',material:'铜线',lot:'L1',location:'QC',qty_signed:4,unit:'kg',document_verified:true,arrival_state:'待检',current_state:'可用',issues:[]};
const lot={material_id:'M1',lot:'L1',location:'QC',unit:'kg',recorded_state:'可用',state:'可用',balance_qty:3,usable_state_qty:3,issues:[],opening:[],timeline:[],status_events:[]};
await check('return and state axes stay explicit without quality approval claim',()=>{
 const html=returnStockRows([row],helpers);for(const s of ['T1','I1','W1','M1','L1 / QC','4 kg','待检 → 可用','关联与累计量可核对'])assert.ok(html.includes(s));assert.ok(!html.includes('检验合格'));assert.ok(!returnStockRows([row],{...helpers,interactive:false}).includes('<button'));
});
await check('unknown state is distinct from zero and documented available state',()=>{
 const html=returnStockLot({...lot,state:null,usable_state_qty:null,issues:['状态链不匹配']},helpers);
 for(const s of ['登记状态 可用','可核对状态 待核对','3 kg','— kg','状态链不匹配'])assert.ok(html.includes(s));assert.ok(!html.includes('可用状态余额 0 kg'));
});
await check('lot balance is not silently attributed to a return',()=>{
 const html=returnStockLot(lot,helpers);assert.ok(html.includes('3 kg'));assert.ok(html.includes('不能认定为单笔退料的剩余量'));assert.ok(returnStockLot(null,helpers).includes('台账缺失'));
});
await check('raw event evidence and registered actor remain inspectable',()=>{
 const html=returnStockLot({...lot,timeline:[{id:'CK2',occurred:'2026-10-01T10:00:00',kind:'生产领料',qty_signed:-1,running_qty:3,state:'可用',issues:[]}],status_events:[{id:'S1',from_status:'待检',to_status:'可用',approver_id:'E1',reason:'模拟登记'}]},helpers);
 for(const s of ['CK2','-1 kg → 3 kg','S1','待检 → 可用','E1','模拟登记'])assert.ok(html.includes(s));
});
await check('all imported labels and issues are escaped',()=>{
 const html=returnStockRows([{...row,id:'<script>',issues:['<img>'],material:'<svg>'}],helpers)+returnStockLot({...lot,recorded_state:'<iframe>'},helpers);
 for(const s of ['<script>','<img>','<svg>','<iframe>'])assert.ok(!html.includes(s));assert.ok(html.includes('&lt;script&gt;'));
});
function fixture(){
 let current=1,revision=0;const main={innerHTML:''},dialog={open:false,close(){this.open=false;revision++}},handlers=new Map(),calls=[],pending=[];let detailHTML='';
 const board={receipt:'r1',as_of:'2026-10-01T18:00:00',note:'共享库位去重',state_note:'未知留空',filters:{material_id:'',work_order_id:'',q:'',stage:'all'},summary:{returns:1,target_lots:1,documents_verified:1,attention:0,arrival_known:1,current_verified:1},matrix:[],units:[],stages:{all:'全部退料'},facets:{all:1},rows:[row],total:1,page:1,size:25};
 const context={esc,num:String,table,chart:()=>'',header:()=>'',panel:(a,b,c)=>a+b+c,toast:()=>{},go:(...args)=>calls.push(args),$:(key)=>key==='#main'?main:dialog,
  $$:selector=>selector==='[data-return-stock]'?[{dataset:{returnStock:'T1'},addEventListener:(ev,fn)=>handlers.set('row',fn)}]:[],on:(key,event,fn)=>handlers.set(key,fn),
  isCurrent:t=>t===current,getModalRevision:()=>revision,modal:(title,html)=>{revision++;dialog.open=true;detailHTML=title+html},
  api:url=>{calls.push(url);if(url.startsWith('return-stock?'))return Promise.resolve(board);return new Promise((resolve,reject)=>pending.push({resolve,reject,url}));}};
 return {render:createReturnStock(context),main,dialog,handlers,calls,pending,board,detail:()=>detailHTML,switchPage:()=>{current++},changeModal:()=>context.modal('Other','new content')};
}
const detail={row,original_issue:{id:'I1',occurred:'2026-09-29',material_id:'M1',lot:'L1',location:'A',qty_signed:-10,work_order_id:'W1',reference:'W1'},original_unit:'件',origin_lot:lot,target_lot:lot,note:'边界',state_note:'状态说明'};
await check('page scope and receipt are included in detail and export',async()=>{
 const f=fixture();await f.render(new URLSearchParams('tab=returns&q=Q001'),1);assert.ok(f.main.innerHTML.includes('receipt=r1'));assert.ok(f.main.innerHTML.includes('q=Q001'));
 const p=f.handlers.get('row')();assert.ok(f.pending[0].url.includes('q=Q001&receipt=r1'));f.pending[0].resolve(detail);await p;
 assert.ok(f.detail().includes('-10 件'));assert.ok(!f.detail().includes('data-return-stock'));assert.ok(f.handlers.has('#rs-sources'));
});
await check('closed or replaced dialogs reject late detail responses',async()=>{
 for(const action of ['close','replace','navigate']){
  const f=fixture();await f.render(new URLSearchParams(),1);const p=f.handlers.get('row')();
  if(action==='close')f.dialog.close();else if(action==='replace')f.changeModal();else f.switchPage();
  const before=f.detail();f.pending[0].resolve(detail);await p;assert.equal(f.detail(),before);
 }
});
await check('source pages preserve receipt, pagination, and permission-controlled originals',async()=>{
 const f=fixture();await f.render(new URLSearchParams(),1);const first=f.handlers.get('row')();f.pending[0].resolve(detail);await first;
 const request=f.handlers.get('#rs-sources')();assert.ok(f.pending[1].url.endsWith('receipt=r1&page=1'));
 f.pending[1].resolve({rows:[{dataset:'inventory_movements',key:'T1',filename:'test.xlsx',sheet:'库存流水',row:4,batch_id:'B1',missing:false}],total:41,page:1,size:40,can_download_original:false});await request;
 assert.ok(f.detail().includes('test.xlsx'));assert.ok(f.detail().includes('第4行'));assert.ok(!f.detail().includes('/api/imports/B1/file'));assert.ok(f.handlers.has('#rs-source-next'));
});
await check('stale receipt failures display a failure instead of an empty result',async()=>{
 const f=fixture();await f.render(new URLSearchParams(),1);const p=f.handlers.get('row')();f.pending[0].reject(new Error('范围已变化，请刷新'));await p;assert.ok(f.detail().includes('读取失败'));assert.ok(f.detail().includes('范围已变化'));
});
console.log(JSON.stringify({success:true,groups,browser_acceptance:false}));
