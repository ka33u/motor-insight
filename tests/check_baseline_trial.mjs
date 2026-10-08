// Pure rendering and asynchronous state contracts; no browser or DOM automation.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {TRIAL_BOUNDARY,trialTaskRows,baselineTrialOverview,baselineTrialComparison,baselineTrialChanges,baselineTrialTask,createBaselineTrialWorkspace} from '../static/baseline_trial.js';
import {createOrderBaselineWorkspace} from '../static/order_baseline.js';

const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const table=(headers,rows)=>{assert(rows.every(r=>r.length===headers.length));return `<table>${JSON.stringify({headers,rows})}</table>`};
// Match the application's real three-argument panel helper.
const panel=(title,subtitle,content)=>`<section><h2>${esc(title)}</h2><p>${esc(subtitle)}</p>${content}</section>`;
const h={esc,table,panel};
const trial=JSON.parse(fs.readFileSync(new URL('fixtures/joint_schedule_board_001_due.json',import.meta.url)));
const d={state:'trial',study:{id:'OB/1',name:'合成基线',version:1},policy:'due',policy_name:'应完成时间优先',notice:'仅计算声明集合',history_verified:false,cutoff:'2026-10-01T18:00:00',issues:[],warnings:[],changes:[],receipt:'SYNTHETIC<&>',source_count:41,source_hash:'s',rule_hash:'r',trial,
 coverage:[{id:'OL1',product_id:'P1',order_qty:135,registered_shipped_qty:0,baseline_open_qty:135,planned_qty:50,uncovered_qty:85,overplanned_qty:0}],
 comparison:{available:true,notice:'同一派序与人机供给',jobs:trial.jobs.map(j=>({id:j.id,qty:j.qty,current_state:j.state,frozen_state:j.state,current_finished:j.finished,frozen_finished:j.finished,delta_minutes:0})),materials:[{material_id:'M1',unit:'kg',current_required_qty:'55.704',frozen_required_qty:'50.134',delta_qty:'-5.570'}]}};
const list={rows:[d.study],policies:{due:'应完成时间优先',priority:'批次优先级优先'}};
const detail={task:trial.tasks[0],demands:trial.demands.filter(n=>trial.tasks[0].demand_ids.includes(n.id)),reservations:trial.reservations.filter(r=>trial.tasks[0].demand_ids.includes(r.demand_id)),sources:[],notice:'声明冻结集合的任务依据'};
const pending=()=>{let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b});return{promise,resolve,reject}};
const tick=()=>new Promise(r=>setImmediate(r));
function harness(api){
 const nodes=new Map(),events=new Map(),groups=new Map(),moves=[],modals=[],toasts=[],requests=[];let active=true,revision=0;
 const node=id=>{if(!nodes.has(id))nodes.set(id,{innerHTML:'',textContent:'',value:'',disabled:false});return nodes.get(id)};
 const controls={api:(path,options)=>{requests.push({path,options});return api(path,options)},esc,table,panel,header:(a,b,c='')=>`<header>${esc(a)}${esc(b)}${c}</header>`,modal:(...v)=>{revision++;modals.push(v)},toast:v=>toasts.push(v),go:(...v)=>moves.push(v),$:node,$$:selector=>groups.get(selector)||[],on:(id,event,fn)=>events.set(id+':'+event,fn),isCurrent:()=>active,getModalRevision:()=>revision};
 return{h:controls,node,events,groups,moves,modals,toasts,requests,leave:()=>{active=false},replaceModal:()=>{revision++},fire:(id,event='click',value={})=>{const fn=events.get(id+':'+event);assert(fn,'missing handler '+id+':'+event);return fn(value)},taskButton(id){const b={dataset:{baselineTrialTask:id},addEventListener:(event,fn)=>events.set('task:'+id+':'+event,fn)};groups.set('[data-baseline-trial-task]',[...(groups.get('[data-baseline-trial-task]')||[]),b]);return b}};
}
const normal=path=>Promise.resolve(path==='order-baselines'?structuredClone(list):structuredClone(d));
let checks=0;const names=[];
async function check(name,fn){await fn();checks++;names.push(name)}

await check('task filtering preserves complete scope and pagination',()=>{
 const rows=Array.from({length:85},(_,i)=>({id:i,job_id:i<45?'A':'B',state:i%2?'blocked':'scheduled'}));
 assert.equal(trialTaskRows(rows,{job:'A'}).total,45);assert.equal(trialTaskRows(rows,{job:'A',page:2}).rows.length,5);assert.equal(trialTaskRows(rows,{state:'blocked'}).total,42);assert.equal(trialTaskRows(rows,{job:'absent'}).rows.length,0);
});
await check('historical and approval boundary remains visible with coverage',()=>{
 const html=baselineTrialOverview(d,h);assert(html.includes(TRIAL_BOUNDARY));assert(html.includes('不是新增业务事实'));assert(html.includes('135 / 0'));assert(html.includes('50 / 85'));assert(html.includes('<table>'));assert(!html.includes('&lt;table&gt;'));
});
await check('paused and empty coverage never become zero results',()=>{
 const paused={...d,state:'paused',trial:null,coverage:[],issues:[{code:'UNIT_MISMATCH',dataset:'materials',key:'<img>',field:'unit',message:'<script>kg / g'}]};
 const html=baselineTrialOverview(paused,h);assert(html.includes('暂停不表示零需求'));assert(html.includes('覆盖未计算'));assert(html.includes('UNIT_MISMATCH'));assert(html.includes('&lt;script&gt;'));assert(!html.includes('finite-summary'));assert(!html.includes('<img>'));
});
await check('comparison requires both trial columns and both completion times',()=>{
 const sample=structuredClone(d);sample.comparison.jobs[0].current_finished=null;sample.comparison.jobs[0].delta_minutes=-999;
 const html=baselineTrialComparison(sample,h);assert(html.includes('不可比较'));assert(!html.includes('-999'));assert(html.includes('-5.570'));assert(html.includes('负表示'));assert(!baselineTrialComparison({...d,comparison:{...d.comparison,available:false}},h).includes('55.704'));assert(!baselineTrialComparison({...d,state:'paused'},h).includes('55.704'));
});
await check('business differences retain all fields with Chinese labels and explicit absence',()=>{
 let cells;
 const changes=[{link_id:'L1',dataset:'bom',key:'B1',fields:['qty','effective'],frozen:{id:'B1',qty:0,scrap_allowance:.035,effective:'2026-09-01'},current:{id:'B1',qty:50.134,scrap_allowance:.035,effective:null}},
  {link_id:'L2',dataset:'routes',key:'<route>',fields:['mandatory'],frozen:{id:'<route>',mandatory:false,process:'<script>'},current:null}];
 const html=baselineTrialChanges(changes,{esc,table:(headers,rows)=>{cells=rows;return table(headers,rows)}});
 assert.equal(cells.length,7);assert(cells[1][1].includes('单位用量'));assert.equal(cells[1][2],'0');assert.equal(cells[1][3],'50.134');assert.equal(cells[2][1],'损耗定额');assert.equal(cells[3][3],'缺失');assert.equal(cells[5][2],'否');assert.equal(cells[5][3],'缺失');assert(html.includes('已变化'));assert(html.includes('2026-09-01'));assert(html.includes('&lt;script&gt;'));assert(!html.includes('<pre'));assert(!html.includes('scrap_allowance'));assert(!html.includes('mandatory'));assert(!html.includes('<script>'));
});
await check('known order and version difference fields all have business labels',()=>{
 const changes=[{link_id:'L1',dataset:'order_lines',key:'OL1',fields:['qty'],frozen:{id:'OL1',order_id:'SO1',product_id:'P1',qty:2,original_due:'2026-09-01',due:'2026-09-02'},current:null},
  {link_id:'L1',dataset:'work_orders',key:'W1',fields:['bom_version'],frozen:{id:'W1',product_id:'P1',planned_qty:2,bom_version:'A',route_version:'R',status:'未开工'},current:null},
  {link_id:'L1',dataset:'allocations',key:'A1',fields:['effective'],frozen:{id:'A1',work_order_id:'W1',order_line_id:'OL1',qty:2,effective:'2026-08-01'},current:null},
  {link_id:'L1',dataset:'products',key:'P1',fields:['bom_version'],frozen:{id:'P1',bom_version:'A',route_version:'R'},current:null},
  {link_id:'L1',dataset:'materials',key:'M1',fields:['unit'],frozen:{id:'M1',unit:'kg'},current:{id:'M1',unit:'g'}}];
 const html=baselineTrialChanges(changes,h);for(const label of ['订单台数','工单计划台数','工单 BOM 版本','分配台数','分配生效日期','配置当前 BOM 版本','计量单位'])assert(html.includes(label));for(const field of ['order_id','planned_qty','bom_version','route_version','work_order_id','order_line_id'])assert(!html.includes(field));
});
await check('task detail escapes evidence and retains reservation identity',()=>{
 const sample=structuredClone(detail);sample.task.id='<script>';sample.notice='<img>';sample.sources=[{dataset:'bom',key:'<source>',missing:true}];
 const html=baselineTrialTask(sample,h);assert(html.includes('&lt;script&gt;'));assert(html.includes('共享供给预留'));assert(html.includes('资格 / 人员窗口'));assert(html.includes('来源缺失'));assert(!html.includes('<script>'));assert(!html.includes('<img>'));
});
await check('workspace renders schedule materials and policy controls',async()=>{
 const x=harness(normal);await createBaselineTrialWorkspace(x.h).render(new URLSearchParams(),1);
 assert(x.node('#main').innerHTML.includes(TRIAL_BOUNDARY));assert(x.node('#baseline-trial-body').innerHTML.includes('<svg'));assert(x.node('#baseline-trial-page').textContent.includes(`全案 ${trial.tasks.length} 项`));
 x.fire('#baseline-trial-next');assert(x.node('#baseline-trial-page').textContent.startsWith('2 /'));x.node('#baseline-trial-state').value='blocked';x.fire('#baseline-trial-state','change');assert(x.node('#baseline-trial-page').textContent.startsWith('1 /'));
 x.fire('#baseline-trial-worker');assert(x.node('#baseline-trial-chart').innerHTML.includes('人员'));x.fire('#baseline-trial-material');assert(x.node('#baseline-trial-body').innerHTML.includes('不按产品合并版本'));assert(x.node('#baseline-trial-body').innerHTML.includes('可用 = 预留 + 剩余'));
 x.fire('#baseline-trial-return');x.fire('#baseline-trial-policy','change',{target:{value:'priority'}});assert.deepEqual(x.moves,[['order-baselines',{study:d.study.id,policy:'due'}],['order-baselines',{view:'trial',study:d.study.id,policy:'priority'}]]);
});
await check('all receipt-bearing API requests are POST bodies',async()=>{
 const x=harness((path,options)=>path.endsWith('/sources')?Promise.resolve({rows:[],page:1,size:40,total:0}):normal(path));
 await createBaselineTrialWorkspace(x.h).render(new URLSearchParams({policy:'priority',receipt:'INPUT<&>'}),1);await x.fire('#baseline-trial-sources');
 assert.equal(x.requests[1].path,'baseline-trial/OB%2F1');assert.deepEqual(x.requests[1].options,{method:'POST',body:{policy:'priority',receipt:'INPUT<&>'}});assert.deepEqual(x.requests.at(-1).options.body,{policy:'priority',receipt:d.receipt,page:1});assert(x.requests.every(r=>!r.path.includes('receipt')));
});
await check('refresh removes stale receipt before rereading',async()=>{
 const x=harness(normal);await createBaselineTrialWorkspace(x.h).render(new URLSearchParams({receipt:'OLD'}),1);await x.fire('#baseline-trial-refresh');
 assert.deepEqual(x.requests.at(-1).options.body,{policy:'due'});
});
await check('current refresh error remains visible after request generation changes',async()=>{
 let reads=0;const x=harness(path=>path==='order-baselines'?Promise.resolve(list):++reads===1?Promise.resolve(d):Promise.reject(Error('CURRENT FAILURE')));await createBaselineTrialWorkspace(x.h).render(new URLSearchParams(),1);await x.fire('#baseline-trial-refresh');assert.deepEqual(x.toasts,['CURRENT FAILURE']);
});
await check('navigation suppresses a pending board',async()=>{
 const wait=pending(),x=harness(path=>path==='order-baselines'?Promise.resolve(list):wait.promise),w=createBaselineTrialWorkspace(x.h),run=w.render(new URLSearchParams(),1);await tick();x.leave();wait.resolve(d);await run;assert.equal(x.node('#main').innerHTML,'');
});
await check('newer render wins over an older response in the same route',async()=>{
 const wait=pending();let reads=0;const x=harness(path=>path==='order-baselines'?Promise.resolve(list):++reads===1?wait.promise:Promise.resolve({...d,study:{...d.study,name:'CURRENT'}})),w=createBaselineTrialWorkspace(x.h),run=w.render(new URLSearchParams(),1);await tick();await w.render(new URLSearchParams(),1);wait.resolve({...d,study:{...d.study,name:'STALE'}});await run;assert(x.node('#main').innerHTML.includes('CURRENT'));assert(!x.node('#main').innerHTML.includes('STALE'));
});
await check('cancellation suppresses late response and rejection',async()=>{
 const wait=pending(),x=harness(path=>path==='order-baselines'?Promise.resolve(list):wait.promise),w=createBaselineTrialWorkspace(x.h),run=w.render(new URLSearchParams(),1);await tick();w.cancel();wait.reject(Error('STALE'));await run;assert.equal(x.node('#main').innerHTML,'');assert.equal(x.toasts.length,0);
});
await check('task clicks use POST and latest modal intent wins across task and sources',async()=>{
 const task=pending(),source=pending(),x=harness(path=>path.includes('/tasks/')?task.promise:path.endsWith('/sources')?source.promise:normal(path));x.taskButton('TASK/1');await createBaselineTrialWorkspace(x.h).render(new URLSearchParams(),1);
 const earlier=x.events.get('task:TASK/1:click')();const latest=x.fire('#baseline-trial-sources');source.resolve({rows:[],total:0,size:40,page:1});await latest;task.resolve(detail);await earlier;assert.equal(x.modals.length,1);assert(x.modals[0][0].includes('共享来源'));const call=x.requests.find(r=>r.path.includes('/tasks/'));assert.equal(call.path,'baseline-trial/OB%2F1/tasks/TASK%2F1');assert.deepEqual(call.options.body,{policy:'due',receipt:d.receipt});
});
await check('external modal replacement and close discard pending evidence',async()=>{
 for(const close of [false,true]){const wait=pending(),x=harness(path=>path.endsWith('/sources')?wait.promise:normal(path));await createBaselineTrialWorkspace(x.h).render(new URLSearchParams(),1);const open=x.fire('#baseline-trial-sources');if(close)x.fire('#detail','close');else x.replaceModal();wait.resolve({rows:[],total:0,size:40,page:1});await open;assert.equal(x.modals.length,0)}
});
await check('superseded modal errors do not toast over the current user action',async()=>{
 const wait=pending(),x=harness(path=>path.endsWith('/sources')?wait.promise:normal(path));await createBaselineTrialWorkspace(x.h).render(new URLSearchParams(),1);const open=x.fire('#baseline-trial-sources');x.replaceModal();wait.reject(Error('STALE MODAL'));await open;assert.deepEqual(x.toasts,[]);
});
await check('task detail opens when its view and modal remain current',async()=>{
 const x=harness(path=>path.includes('/tasks/')?Promise.resolve(detail):normal(path));x.taskButton('T1');await createBaselineTrialWorkspace(x.h).render(new URLSearchParams(),1);await x.events.get('task:T1:click')();assert.equal(x.modals.length,1);assert(x.modals[0][1].includes('冻结整批需求'));
});
await check('source pagination honors returned page size',async()=>{
 const x=harness(path=>path.endsWith('/sources')?Promise.resolve({rows:[],total:41,size:20,page:1}):normal(path));await createBaselineTrialWorkspace(x.h).render(new URLSearchParams(),1);await x.fire('#baseline-trial-sources');assert(!x.modals[0][1].includes('id="baseline-trial-source-next" disabled'));await x.fire('#baseline-trial-source-next');assert.equal(x.requests.at(-1).options.body.page,2);
});
await check('paused workspace remains inspectable without task or material controls',async()=>{
 const paused={...d,state:'paused',trial:null,comparison:{available:false},issues:[{code:'WIP_REGISTERED',message:'已登记报工'}]},x=harness(path=>path==='order-baselines'?Promise.resolve(list):Promise.resolve(paused));await createBaselineTrialWorkspace(x.h).render(new URLSearchParams(),1);assert(x.node('#main').innerHTML.includes('WIP_REGISTERED'));assert(!x.events.has('#baseline-trial-material:click'));assert(x.events.has('#baseline-trial-json:click'));assert.equal(x.node('#baseline-trial-body').innerHTML,'');
});
await check('export suppresses duplicate clicks and a stale download',async()=>{
 const wait=pending(),x=harness(path=>path.endsWith('/export')?wait.promise:normal(path));await createBaselineTrialWorkspace(x.h).render(new URLSearchParams(),1);const first=x.fire('#baseline-trial-json');await x.fire('#baseline-trial-csv');assert.equal(x.requests.filter(r=>r.path.endsWith('/export')).length,1);assert.deepEqual(x.requests.at(-1).options.body,{policy:'due',receipt:d.receipt,format:'json'});x.leave();wait.resolve({filename:'synthetic.json',mime:'application/json',text:'{}'});await first;
});
await check('CSV download preserves server bytes and its UTF-8 BOM exactly once',async()=>{
 const originalDocument=globalThis.document,originalCreate=URL.createObjectURL,originalRevoke=URL.revokeObjectURL;let blob,anchor,clicked=0;
 globalThis.document={createElement:()=>anchor={click:()=>{clicked++},remove:()=>{}},body:{append:()=>{}}};URL.createObjectURL=value=>{blob=value;return 'blob:synthetic'};URL.revokeObjectURL=()=>{};
 try{const text='\ufeff数量,单位\r\n50.134,kg',x=harness(path=>path.endsWith('/export')?Promise.resolve({filename:'baseline-trial.csv',mime:'text/csv',text}):normal(path));await createBaselineTrialWorkspace(x.h).render(new URLSearchParams(),1);await x.fire('#baseline-trial-csv');assert.equal(clicked,1);assert.equal(anchor.download,'baseline-trial.csv');const bytes=new Uint8Array(await blob.arrayBuffer());assert.deepEqual([...bytes.slice(0,3)],[239,187,191]);assert.deepEqual(bytes,new TextEncoder().encode(text));assert((await blob.text()).includes('50.134,kg'))}finally{globalThis.document=originalDocument;URL.createObjectURL=originalCreate;URL.revokeObjectURL=originalRevoke}
});
await check('order baseline router opens independent trial view',async()=>{
 const x=harness(normal);await createOrderBaselineWorkspace(x.h).render(new URLSearchParams({view:'trial',study:d.study.id}),1);assert(x.node('#main').innerHTML.includes(TRIAL_BOUNDARY));assert(x.requests.some(r=>r.path==='baseline-trial/OB%2F1'));assert(!x.requests.some(r=>r.path.startsWith('order-baselines/')));
});
const oldBoard={state:'aligned',summary:null,study:d.study,joint_study:{id:'MP1'},issues:[],warnings:[],orders:[],links:[],bom:[],changes:[],versions:[],source_count:0,receipt:'BASELINE-RECEIPT'};
await check('existing baseline view retains GET reads and links to trial without its receipt',async()=>{
 const x=harness(path=>path==='order-baselines'?Promise.resolve(list):Promise.resolve(oldBoard));await createOrderBaselineWorkspace(x.h).render(new URLSearchParams(),1);assert(x.node('#main').innerHTML.includes('订单与BOM基线'));assert(x.requests[1].path.startsWith('order-baselines/OB%2F1?'));assert.equal(x.requests[1].options,undefined);x.fire('#baseline-trial-open');assert.deepEqual(x.moves,[['order-baselines',{study:d.study.id,policy:'due',view:'trial'}]]);
});
await check('switching between old and new view suppresses pending previous view',async()=>{
 for(const fromTrial of [false,true]){const wait=pending(),x=harness(path=>path==='order-baselines'?Promise.resolve(list):path.startsWith('baseline-trial/')?(fromTrial?wait.promise:Promise.resolve(d)):(fromTrial?Promise.resolve(oldBoard):wait.promise)),w=createOrderBaselineWorkspace(x.h);const earlier=w.render(new URLSearchParams(fromTrial?{view:'trial'}:{}),1);await tick();await w.render(new URLSearchParams(fromTrial?{}:{view:'trial'}),1);wait.resolve(fromTrial?d:oldBoard);await earlier;assert.equal(x.node('#main').innerHTML.includes(TRIAL_BOUNDARY),!fromTrial)}
});
await check('unknown policy is rejected before requesting data',async()=>{
 const x=harness(normal);await assert.rejects(createBaselineTrialWorkspace(x.h).render(new URLSearchParams({policy:'<bad>'}),1),/策略无效/);assert.equal(x.requests.length,0);
});
console.log(JSON.stringify({success:true,checks,names,pure_js_state_harness:true,browser_acceptance:false,mobile_acceptance:false,actual_download_acceptance:false}));
