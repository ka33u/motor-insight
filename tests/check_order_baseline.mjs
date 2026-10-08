// Pure data/string/state verification; not browser or DOM automation.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {baselineOverview,createOrderBaselineWorkspace,exportPath} from '../static/order_baseline.js';
import {baselineSelection,baselineBom,baselineLinkDetail} from '../static/order_baseline_reading.js';
const read=n=>JSON.parse(fs.readFileSync(new URL('fixtures/order_baseline_board_'+n+'_due.json',import.meta.url)));
const d={...read('008'),receipt:'SIM-READING-TICKET',source_count:41},aligned=read('001');
const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const table=(headers,rows)=>{assert(rows.every(r=>r.length===headers.length));return '<table><thead>'+headers.map(x=>`<th>${esc(x)}</th>`).join('')+'</thead><tbody>'+rows.map(r=>'<tr>'+r.map(x=>`<td>${x}</td>`).join('')+'</tr>').join('')+'</tbody></table>'};
// The production panel uses (title, subtitle, content); a two-argument fake
// would hide the regression that formerly escaped tables into the subtitle.
const panel=(title,subtitle,content)=>{assert.equal(typeof content,'string','Missing panel content: '+title);return `<section><h2>${esc(title)}</h2><p>${esc(subtitle)}</p>${content}</section>`};
assert(fs.readFileSync(new URL('../static/app.js',import.meta.url),'utf8').includes("function panel(title,subtitle,content,action='',cls='')"));
const h={esc,table,panel},list={rows:[d.study],policies:{due:'应完成时间优先',priority:'批次优先级优先'}};
const order=d.orders[0].id,link=d.links[0].id;
const detail={row:d.links[0],bom:d.bom.filter(r=>r.link_id===link),changes:d.changes.filter(r=>r.link_id===link),sources:[{dataset:'order_baseline_bom',key:d.bom[0].id,filename:'40_订单与BOM基线_模拟.xlsx',sheet:'用料',row:2,revision:1,source_row_id:123}],notice:'批次直接来源；整案另读',can_download_original:false};
const pending=()=>{let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b});return{promise,resolve,reject}};
const tick=()=>new Promise(r=>setImmediate(r));
function harness(api){
 const nodes=new Map(),events=new Map(),moves=[],modals=[],toasts=[],requests=[];let active=true,revision=0;
 const node=id=>{if(!nodes.has(id))nodes.set(id,{innerHTML:'',textContent:'',value:'',disabled:false});return nodes.get(id)};
 const groups=new Map();
 const controls={api:(path,options)=>{requests.push({path,options});return api(path,options)},...h,header:(title,sub,action='')=>`<header>${esc(title)}${esc(sub)}${action}</header>`,modal:(...a)=>{revision++;modals.push(a)},toast:v=>toasts.push(v),go:(...a)=>moves.push(a),$:node,$$:key=>groups.get(key)||[],on:(id,event,fn)=>events.set(id+':'+event,fn),isCurrent:()=>active,getModalRevision:()=>revision};
 return{h:controls,node,events,moves,modals,toasts,requests,leave:()=>{active=false},replaceModal:()=>{revision++},fire:(id,event='click',value={})=>{const fn=events.get(id+':'+event);assert(fn,'missing '+id+':'+event);return fn(value)},button(selector,field,id){const b={dataset:{[field]:id},addEventListener:(event,fn)=>events.set(selector+':'+id+':'+event,fn)};groups.set(selector,[...(groups.get(selector)||[]),b])}};
}
const normal=path=>Promise.resolve(structuredClone(path==='order-baselines'?list:d));
let checks=0;const names=[];
async function check(name,fn){await fn();checks++;names.push(name)}
await check('all baseline panels use actual content position and preserve complete totals',()=>{
 const html=baselineOverview(d,h);assert(html.includes('<table>'));assert(!html.includes('&lt;table'));assert(!html.includes('undefined'));for(const n of [135,50,85])assert(html.includes('<b>'+n+'</b>'));assert(html.includes('完整基线'));assert(html.includes('基线现承诺'));assert(html.includes('不能作为OTIF'));
});
await check('exact order membership selects one job and nine copied BOM rows',()=>{
 const v=baselineSelection(d,{order});assert.equal(v.selected.length,1);assert.equal(v.allBom.length,9);assert.equal(v.selected[0].plan_qty,6);assert.equal(v.bomRows[0].required_qty,'50.134');assert.equal(v.changes.length,1);
 const ids=[];for(const o of d.orders)ids.push(...baselineSelection(d,{order:o.id}).allBom.map(b=>b.id));assert.equal(ids.length,54);assert.equal(new Set(ids).size,54);
});
await check('different and same BOM membership remain distinct from business field changes',()=>{
 const different=baselineSelection(d,{order,link,bom:'different'}),same=baselineSelection(d,{order,link,bom:'same'});
 assert.equal(different.bomRows.length,1);assert.equal(different.bomRows[0].required_qty,'50.134');assert.equal(same.bomRows.length,8);assert.equal(same.changes.length,1);assert.equal(different.allBom.length,9);
});
await check('cross-order selections and unknown values are rejected without guessing identity',()=>{
 for(const sel of [{order:'OTHER'},{order,link:d.links[1].id},{link:'OTHER'},{bom:'UNKNOWN'}])assert.throws(()=>baselineSelection(d,sel));
});
await check('selection does not mutate the server result or recalculate complete summary',()=>{
 const before=structuredClone(d);baselineSelection(d,{order,link,bom:'different'});assert.deepEqual(d,before);assert.deepEqual(baselineSelection(d).allBom,d.bom);assert.equal(d.summary.uncovered_qty,85);
});
await check('same product on another order cannot leak into selection',()=>{
 const x=structuredClone(d);x.links[1].product_id=x.links[0].product_id;const v=baselineSelection(x,{order});assert.equal(v.selected.length,1);assert.equal(v.allBom.length,9);
});
await check('paused and undefined denominators do not render healthy zero bars',()=>{
 const paused={...d,state:'paused',summary:null,orders:[],issues:['资料缺失'],warnings:[]};const html=baselineOverview(paused,h);assert(!html.includes('finite-summary'));assert(!html.includes('baseline-coverage'));assert(html.includes('订单覆盖未计算'));
 const x=structuredClone(aligned);x.orders[0].coverage_percent=null;x.orders[0].overplanned_qty=2;const text=baselineOverview(x,h);assert.equal((text.match(/class="baseline-coverage"/g)||[]).length,5);assert(text.includes('超排 2 台'));
});
await check('no completion time remains unknown while numeric zero remains meaningful',()=>{
 const x=structuredClone(detail);x.row.finished=null;x.row.customer_late_minutes=0;const html=baselineLinkDetail(x,h);assert(html.includes('未形成时间'));assert(html.includes('<td>0</td>'));assert(!html.includes('<pre'));assert(!html.includes('source_changed'));assert(html.includes('客户原承诺日期'));assert(html.includes('基线现承诺日期'));
});
await check('detail lists frozen version units rounding and current binding with source rows',()=>{
 const html=baselineLinkDetail(detail,h);for(const part of ['50.134','55.704','8.073','0.035','0.001','kg','40_订单与BOM基线_模拟.xlsx','第 2 行','来源索引不授予原件下载权限'])assert(html.includes(part),part);assert(!html.includes('unit_qty'));assert(!html.includes('<pre'));assert(html.includes('待核对'));
});
await check('business content escapes imported names notes IDs and source file text',()=>{
 const x=structuredClone(detail);x.row.note='<img onerror="bad">';x.bom[0].material_id='<script>';x.sources[0].filename='<svg>';x.notice='<b>unsafe';const html=baselineLinkDetail(x,h);for(const literal of ['<img','<script>','<svg>','<b>unsafe'])assert(!html.includes(literal));for(const safe of ['&lt;img','&lt;script&gt;','&lt;svg&gt;'])assert(html.includes(safe));
});
await check('unknown or empty BOM scope is not a statement of zero demand',()=>{
 assert(baselineBom([],h).includes('不代表零需求'));const x=structuredClone(detail);x.bom[0].unit='g';const html=baselineBom(x.bom,h);assert(html.includes(' g'));assert(html.includes(' kg'));assert(html.includes('待核对'));
});
await check('workspace initial all view contains business tables and complete source/export scope',async()=>{
 const x=harness(normal);await createOrderBaselineWorkspace(x.h).render(new URLSearchParams(),1);assert(x.node('#baseline-overview').innerHTML.includes('<table>'));assert(x.node('#baseline-reading').innerHTML.includes('<table>'));assert(x.node('#baseline-bom-table').innerHTML.includes('<table>'));assert(x.node('#baseline-bom-page').textContent.includes('54 行'));assert(x.node('#main').innerHTML.includes('全基线 CSV'));assert(!x.node('#baseline-reading').innerHTML.includes('undefined'));
});
await check('order then batch then mismatch lens preserve header totals and reset All',async()=>{
 const x=harness(normal);await createOrderBaselineWorkspace(x.h).render(new URLSearchParams(),1);await x.fire('#baseline-order-filter','change',{target:{value:order}});assert(x.node('#baseline-reading').innerHTML.includes('1 / 6 个映射 · 9 / 54 行用料'));await x.fire('#baseline-link-filter','change',{target:{value:link}});await x.fire('#baseline-bom-filter','change',{target:{value:'different'}});assert(x.node('#baseline-bom-page').textContent.includes('当前核对 1 行'));assert(x.node('#baseline-bom-table').innerHTML.includes('50.134'));assert(!x.node('#baseline-bom-table').innerHTML.includes('29.995'));assert(x.node('#baseline-overview').innerHTML.includes('<b>135</b>'));x.fire('#baseline-reset');assert(x.node('#baseline-bom-page').textContent.includes('当前核对 54 行'));assert.equal(x.requests.length,2);
});
await check('BOM pagination reaches remaining fourteen rows and resets on reading change',async()=>{
 const x=harness(normal);await createOrderBaselineWorkspace(x.h).render(new URLSearchParams(),1);assert.equal((x.node('#baseline-bom-table').innerHTML.match(/<tr>/g)||[]).length,40);x.fire('#baseline-bom-next');assert.equal((x.node('#baseline-bom-table').innerHTML.match(/<tr>/g)||[]).length,14);assert(x.node('#baseline-bom-page').textContent.startsWith('2 /'));await x.fire('#baseline-order-filter','change',{target:{value:order}});assert(x.node('#baseline-bom-page').textContent.startsWith('1 /'));assert(x.node('#baseline-bom-next').disabled);
});
await check('a changed order clears incompatible batch and mismatch selection',async()=>{
 const x=harness(normal);await createOrderBaselineWorkspace(x.h).render(new URLSearchParams(),1);await x.fire('#baseline-link-filter','change',{target:{value:link}});await x.fire('#baseline-bom-filter','change',{target:{value:'different'}});await x.fire('#baseline-order-filter','change',{target:{value:d.orders[1].id}});assert(x.node('#baseline-reading').innerHTML.includes('全部关联批次'));assert(x.node('#baseline-bom-page').textContent.includes('当前核对 9 行'));assert(!x.node('#baseline-bom-table').innerHTML.includes('50.134'));
});
await check('order and batch row buttons drive the same selection contract',async()=>{
 const x=harness(normal);x.button('[data-baseline-order]','baselineOrder',order);x.button('[data-baseline-focus]','baselineFocus',link);await createOrderBaselineWorkspace(x.h).render(new URLSearchParams(),1);x.fire('[data-baseline-order]:'+order);x.fire('[data-baseline-focus]:'+link);assert(x.node('#baseline-reading').innerHTML.includes('aria-pressed="true"'));assert(x.node('#baseline-overview').innerHTML.includes('aria-pressed="true"'));assert(x.node('#baseline-bom-page').textContent.includes('当前核对 9 行'));
});
await check('source scope remains complete after local selection and honors server page size',async()=>{
 const x=harness(path=>path.includes('/sources?')?Promise.resolve({rows:detail.sources,total:41,size:20,page:1}):normal(path));await createOrderBaselineWorkspace(x.h).render(new URLSearchParams(),1);await x.fire('#baseline-order-filter','change',{target:{value:order}});await x.fire('#baseline-sources');assert(x.modals[0][0].includes('不受明细阅读选择影响'));assert(!x.requests.at(-1).path.includes(order));assert(x.requests.at(-1).path.includes('receipt=SIM-READING-TICKET'));await x.fire('#baseline-next');assert(x.requests.at(-1).path.includes('page=2'));
});
await check('latest detail or source intent wins and superseded failures stay silent',async()=>{
 for(const reject of [false,true]){const a=pending(),b=pending(),x=harness(path=>path.includes('/links/')?a.promise:path.includes('/sources?')?b.promise:normal(path));x.button('[data-baseline-link]','baselineLink',link);await createOrderBaselineWorkspace(x.h).render(new URLSearchParams(),1);const first=x.fire('[data-baseline-link]:'+link),last=x.fire('#baseline-sources');b.resolve({rows:[],total:0,page:1,size:40});await last;if(reject)a.reject(Error('old'));else a.resolve(detail);await first;assert.equal(x.modals.length,1);assert(x.modals[0][0].includes('全方案来源'));assert.deepEqual(x.toasts,[])}
});
await check('closing replacing or changing scope cancels a pending drill',async()=>{
 for(const action of ['close','replace','select']){const wait=pending(),x=harness(path=>path.includes('/links/')?wait.promise:normal(path));x.button('[data-baseline-link]','baselineLink',link);await createOrderBaselineWorkspace(x.h).render(new URLSearchParams(),1);const first=x.fire('[data-baseline-link]:'+link);if(action==='close')x.fire('#detail','close');if(action==='replace')x.replaceModal();if(action==='select')await x.fire('#baseline-order-filter','change',{target:{value:order}});wait.resolve(detail);await first;assert.equal(x.modals.length,0)}
});
await check('current drill renders human-readable detail with exact selected identity',async()=>{
 const x=harness(path=>path.includes('/links/')?Promise.resolve(detail):normal(path));x.button('[data-baseline-link]','baselineLink',link);await createOrderBaselineWorkspace(x.h).render(new URLSearchParams(),1);await x.fire('[data-baseline-link]:'+link);assert(x.modals[0][1].includes('50.134'));assert(!x.modals[0][1].includes('<pre'));assert(x.requests.at(-1).path.includes(encodeURIComponent(link)));
});
await check('navigation discards stale board and stale failures',async()=>{
 for(const reject of [false,true]){const wait=pending(),x=harness(path=>path==='order-baselines'?Promise.resolve(list):wait.promise),task=createOrderBaselineWorkspace(x.h).render(new URLSearchParams(),1);await tick();x.leave();if(reject)wait.reject(Error('old'));else wait.resolve(d);await task;assert.equal(x.node('#main').innerHTML,'');assert.deepEqual(x.toasts,[])}
});
await check('refresh drops expired receipt and current errors remain visible',async()=>{
 let count=0;const x=harness(path=>path==='order-baselines'?Promise.resolve(list):++count===1?Promise.resolve(d):Promise.reject(Error('reload failure')));await createOrderBaselineWorkspace(x.h).render(new URLSearchParams({receipt:'OLD'}),1);await x.fire('#baseline-refresh');assert(!x.requests.at(-1).path.includes('receipt='));assert.deepEqual(x.toasts,['reload failure']);
});
await check('download is always complete study and prevents duplicate or stale writes',async()=>{
 const original=globalThis.fetch,wait=pending();let calls=[];globalThis.fetch=(path,opts)=>{calls.push({path,opts});return wait.promise};
 try{const x=harness(normal);await createOrderBaselineWorkspace(x.h).render(new URLSearchParams(),1);await x.fire('#baseline-order-filter','change',{target:{value:order}});const first=x.fire('#baseline-csv');await x.fire('#baseline-json');assert.equal(calls.length,1);assert(!calls[0].path.includes(order));assert.equal(calls[0].path,exportPath(d.study.id,'due',d.receipt,'csv'));x.leave();wait.resolve({ok:true});await first}finally{globalThis.fetch=original}
});
await check('paused view exposes full evidence without an empty healthy reading queue',async()=>{
 const x=harness(path=>path==='order-baselines'?Promise.resolve(list):Promise.resolve({...d,state:'paused',summary:null,orders:[],links:[],bom:[],changes:[],issues:['bad snapshot']}));await createOrderBaselineWorkspace(x.h).render(new URLSearchParams(),1);assert(x.node('#baseline-reading').innerHTML.includes('没有可阅读的批次映射'));assert(x.events.has('#baseline-sources:click'));assert(x.events.has('#baseline-json:click'));assert(!x.node('#baseline-overview').innerHTML.includes('finite-summary'));
});
console.log(JSON.stringify({success:true,checks,names,source:'normally imported synthetic Excel result fixtures',browser_acceptance:false,mobile_acceptance:false,actual_browser_download:false}));
