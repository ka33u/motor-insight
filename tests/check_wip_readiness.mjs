import assert from 'node:assert/strict';
import {readinessRows,readinessDetail,createWipReadiness,timeLabels} from '../static/wip_readiness.js';
let groups=0;const check=async(name,fn)=>{await fn();groups++;console.log('PASS '+name)};
const esc=v=>String(v??'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;').replaceAll("'",'&#39;');
const table=(h,rows)=>h.join('|')+'\n'+rows.map(r=>r.join('|')).join('\n');
const helpers={esc,num:String,table,panel:(a,b,c)=>a+b+c};
const row={id:'W1',product_id:'P1',model:'模拟电机',status:'生产中',planned_qty:10,bom_version:'B1',ended_reports:2,open_reports:1,unknown_reports:1,future_reports:1,assembled_sn:1,unknown_sn:0,wip_groups:[{kind:'定子',roots:2,verified_roots:1,wip_qty:null,known_wip_qty:3,unknown_roots:1},{kind:'转子',roots:1,verified_roots:1,wip_qty:0,known_wip_qty:0,unknown_roots:0}],material_uncomputed:false,material_attention:false,material_count:1};
const detail={row,note:'三种粒度分开',boundary:'当前未计算剩余排程',time_note:'登记双时点',gaps:[{owner:'计划',need:'明确报工映射'}],positions:[{root_id:'R1',lot_id:'L1',location:'隔离区',location_kind:'隔离区',kind:'定子',qty:3,whole_lot_qty:8}],roots:[{id:'R1',state:'attention',issues:['缺完整登记']}],wip_global_issues:[],operations:[{id:'BG1',object_type:'生产批次',object_id:'R1',process:'冲片',equipment_id:'EQ1',resource_id:'RS1',employee_id:'E1',started:'2026-10-01',finished:'2026-10-02',time_state:'open',input_qty:10,good_qty:10,scrap_qty:0,rework_qty:0,status:'完成',route_candidates:[{id:'RT1',branch:'定子',version:'R1'}]}],materials:[{material_id:'M1',material:'铜线',unit:'kg',gross_required:4,gross_issued_qty:2,returned_qty:1,issued_qty:1,remaining_required:3,issues:[],warnings:[]}],material_issues:[],units:[]};
await check('unknown quantity differs from verified zero and report counts do not imply finished units',()=>{
 const html=readinessRows([row],helpers);for(const s of ['定子 —','转子 0','2 / 1 / 1','剩余工序排程尚未计算'])assert.ok(html.includes(s));assert.ok(!html.includes('完成率'));
});
await check('detail retains lineage, units, candidate limits and isolation',()=>{
 const html=readinessDetail(detail,helpers);for(const s of ['3 件','8 件','隔离区','RT1 / 定子 / R1','明确映射尚缺','截止时未结束','4 kg','1 kg','3 kg','线边实存'])assert.ok(html.includes(s));assert.ok(!html.includes('data-wr-key'));assert.equal(timeLabels.future,'未来登记，不计截止前报工');
});
await check('all imported strings escaped',()=>{
 const d=structuredClone(detail);d.row.id='<svg>';d.gaps[0].need='<script>';d.operations[0].process='<img>';d.material_issues=['<iframe>'];const html=readinessDetail(d,helpers);for(const tag of ['svg','script','img','iframe']){assert.ok(!html.includes('<'+tag+'>'));assert.ok(html.includes('&lt;'+tag+'&gt;'));}
});
function fixture(){
 let current=1,revision=0,modalHTML='';const main={innerHTML:''},dialog={open:false,close(){this.open=false;revision++}},handlers=new Map(),calls=[],pending=[];
 const board={receipt:'receipt-1',as_of:'2026-10-01T18:00:00',filters:{q:'',work_order_id:'',stage:'all'},summary:{work_orders:1,reported:1,positions:1,closed_wip:0,open:1,unknown:1,unknown_reports:1},matrix:[],note:'定义',boundary:'边界',stages:{all:'全部',open:'未结束'},facets:{all:1,open:1},rows:[row],total:1,page:1,size:25};
 const context={...helpers,chart:()=>'',header:()=>'',toast:()=>{},go:(...a)=>calls.push(a),$:(k)=>k==='#main'?main:dialog,
  $$:q=>q==='[data-wr-key]'?[{dataset:{wrKey:'W1'},addEventListener:(ev,fn)=>handlers.set('row',fn)}]:q==='[data-wr-stage]'?[{dataset:{wrStage:'open'},addEventListener:(ev,fn)=>handlers.set('stage',fn)}]:[],on:(k,e,fn)=>handlers.set(k,fn),
  isCurrent:t=>t===current,getModalRevision:()=>revision,modal:(title,html)=>{revision++;dialog.open=true;modalHTML=title+html},
  api:url=>{calls.push(url);return url.startsWith('wip-readiness?')?Promise.resolve(board):new Promise((resolve,reject)=>pending.push({resolve,reject,url}));}};
 return {render:createWipReadiness(context),main,dialog,handlers,calls,pending,board,html:()=>modalHTML,navigate:()=>{current++},replace:()=>context.modal('another','replacement')};
}
await check('scope, receipt, full export and reset are preserved',async()=>{
 const f=fixture();await f.render(new URLSearchParams('q=W1&page=2'),1);assert.ok(f.main.innerHTML.includes('q=W1&amp;page=2&amp;receipt=receipt-1'));f.handlers.get('stage')();assert.deepEqual(f.calls.at(-1),['wip-readiness',{q:'W1',page:1,stage:'open'}]);f.handlers.get('#wr-reset')();assert.deepEqual(f.calls.at(-1),['wip-readiness',{}]);
 const p=f.handlers.get('row')();assert.ok(f.pending[0].url.includes('q=W1&page=2&receipt=receipt-1'));f.pending[0].resolve(detail);await p;assert.ok(f.html().includes('BG1'));f.handlers.get('#wr-wip')();assert.deepEqual(f.calls.at(-1),['wip-flow',{work_order_id:'W1'}]);
});
await check('source pages and back button keep selected work order',async()=>{
 const f=fixture();await f.render(new URLSearchParams(),1);let p=f.handlers.get('row')();f.pending.at(-1).resolve(detail);await p;p=f.handlers.get('#wr-sources')();assert.ok(f.pending.at(-1).url.includes('rows/W1/evidence?receipt=receipt-1&page=1'));f.pending.at(-1).resolve({rows:[{dataset:'operations',key:'BG1',filename:'模拟.xlsx',sheet:'报工',row:2,batch_id:'B1'}],total:1,page:1,size:40,can_download_original:false});await p;assert.ok(f.html().includes('模拟.xlsx'));assert.ok(!f.html().includes('下载原件'));p=f.handlers.get('#wr-back')();f.pending.at(-1).resolve(detail);await p;assert.ok(f.html().includes('BG1'));
});
await check('closed, replaced and navigated modals reject late detail',async()=>{
 for(const action of ['close','replace','navigate']){
  const f=fixture();await f.render(new URLSearchParams(),1);const p=f.handlers.get('row')();if(action==='close')f.dialog.close();else f[action]();const before=f.html();f.pending[0].resolve(detail);await p;assert.equal(f.html(),before);
 }
});
await check('newer detail wins and stale error cannot overwrite it',async()=>{
 const f=fixture();await f.render(new URLSearchParams(),1);const a=f.handlers.get('row')(),b=f.handlers.get('row')();f.pending[1].resolve(detail);await b;const before=f.html();f.pending[0].reject(new Error('old'));await a;assert.equal(f.html(),before);
});
await check('current failures stay visible and escaped',async()=>{
 const f=fixture();await f.render(new URLSearchParams(),1);const p=f.handlers.get('row')();f.pending[0].reject(new Error('<bad>'));await p;assert.ok(f.html().includes('role="alert"'));assert.ok(f.html().includes('&lt;bad&gt;'));
});
console.log(JSON.stringify({success:true,groups,browser_acceptance:false}));
