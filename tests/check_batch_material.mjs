// Pure string/state tests; no browser or DOM automation.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {initialBatchMaterial,batchMaterialRows,batchMaterialChange,batchMaterialShell,batchMaterialTable} from '../static/joint_batch_material.js';
import {createJointComparison} from '../static/joint_compare.js';
const fixtures=JSON.parse(fs.readFileSync(new URL('fixtures/batch_material_comparisons.json',import.meta.url)));
const d={...fixtures['MP-261009-001'],receipt:'COMPARISON',policy_receipts:{due:'DUE',priority:'PRIORITY'},source_count:741};
const report=d.batch_materials,full=fixtures['MP-261009-002'].batch_materials,index=initialBatchMaterial(report);
const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const table=(headers,rows)=>{assert(rows.every(r=>r.length===headers.length));return `<table>${headers.join('|')}${rows.map(r=>'<tr>'+r.join('|')+'</tr>').join('')}</table>`};
const panel=(title,actions,content)=>{assert.equal(typeof content,'string');return title+actions+content};
const h={esc,table,panel},names=[];
async function check(name,fn){await fn();names.push(name)}
await check('normally imported recipient swap is visible even with zero net material delta',()=>{
 const m=report.materials[index];assert.equal(m.material_id,'01.01.0002');assert.equal(m.reserved_delta_qty,'0');
 const html=batchMaterialChange(m,esc);assert(html.includes('总预留量相同，获配批次有变化'));assert(html.includes('85.699 kg'));assert(html.includes('增加获配 1 批 / 减少获配 1 批'));
});
await check('equal recipient amounts with different timing remain a different condition',()=>{
 const m=full.materials[initialBatchMaterial(full)];assert.equal(m.more_jobs+m.less_jobs,0);assert(m.allocation_only_jobs>0);
 assert(batchMaterialChange(m,esc).includes('获配量相同，预留流水有变化'));
});
await check('paired quantities keep exact decimals and a common scale',()=>{
 const part=batchMaterialRows(report,index);const html=batchMaterialTable(part.rows,h);
 assert(html.includes('85.699'));assert(html.includes('width:100%'));assert(html.includes('width:0%'));assert(html.includes('role="img"'));assert(html.includes('未排完'));
 assert.equal(part.rows[0].left.reserved_percent,100);assert.equal(part.rows[1].right.reserved_percent,100);
});
await check('material and unit selection never blends another ledger',()=>{
 const r=structuredClone(report);r.rows.push({...r.rows[0],unit:'件'});assert.equal(batchMaterialRows(r,index).all,2);
 assert.equal(batchMaterialRows(report,-1).material,null);assert.equal(batchMaterialRows(report,999).total,0);
});
await check('empty and paused reports do not claim healthy zero results',()=>{
 assert.equal(initialBatchMaterial({state:'paused'}),-1);assert(batchMaterialShell({state:'paused'},-1,h).includes('未计算'));
 const r={state:'ready',materials:[],rows:[]};assert.equal(initialBatchMaterial(r),-1);assert.equal(batchMaterialRows(r,-1).all,0);
});
await check('pagination and changed-only selection preserve the complete material scale',()=>{
 const r=structuredClone(report);r.rows=Array.from({length:43},(_,i)=>({...r.rows[0],job_id:'JOB'+i,quantity_change:i%2?'same':'more',allocation_changed:false}));
 assert.equal(batchMaterialRows(r,index,{page:3}).rows.length,3);assert.equal(batchMaterialRows(r,index,{changed:true}).total,22);
 assert.equal(batchMaterialRows(r,index,{page:3}).material.chart_max_qty,'85.699');
});
await check('flow-only changes are included without inventing a quantity change',()=>{
 assert(batchMaterialRows(full,initialBatchMaterial(full),{changed:true}).rows.every(r=>r.quantity_change==='same'));
});
await check('invalid chart percentages remain explicitly unavailable',()=>{
 const r=structuredClone(report.rows[0]);r.left.reserved_percent=NaN;const html=batchMaterialTable([r],h);assert(html.includes('数量比例不可显示'));assert(!html.includes('width:NaN'));
});
await check('imported labels and navigation identities are escaped',()=>{
 const r=structuredClone(report.rows[0]);for(const k of ['job_id','product_id','unit','material_id'])r[k]='<img onerror="x">';
 const html=batchMaterialTable([r],h);assert(!html.includes('<img'));assert(html.includes('&lt;img'));assert(!html.includes('data-batch-material-unit="<'));
});
await check('presentation never mutates the reviewed comparison',()=>{
 const before=structuredClone(report);batchMaterialShell(report,index,h);batchMaterialTable(batchMaterialRows(report,index).rows,h);assert.deepEqual(report,before);
});
const pending=()=>{let resolve;const promise=new Promise(r=>resolve=r);return {promise,resolve}};
function setup(intercept){
 const nodes=new Map(),events=new Map(),requests=[],modals=[];let revision=0,active=true;
 const node=id=>{if(!nodes.has(id))nodes.set(id,{innerHTML:'',value:'',checked:true,textContent:'',disabled:false});return nodes.get(id)};
 const button={dataset:{batchMaterialJob:report.rows[0].job_id,batchMaterialId:report.rows[0].material_id,batchMaterialUnit:report.rows[0].unit},addEventListener:(name,fn)=>events.set('recipient:'+name,fn)};
 const task={dataset:{compareTask:d.tasks[0].id},addEventListener:(name,fn)=>events.set('task:'+name,fn)};
 const api=(path,options)=>{requests.push({path,options});if(intercept){const result=intercept(path,options);if(result!==undefined)return Promise.resolve(result)}
  if(path==='joint-schedule')return Promise.resolve({rows:[d.study]});
  if(path.endsWith('/sources'))return Promise.resolve({rows:[],page:1,size:40,total:741});
  if(path.includes('/tasks/'))return Promise.resolve({task:d.tasks[0],left:{demands:[],reservations:[]},right:{demands:[],reservations:[]},notice:'SIM'});
  return Promise.resolve(structuredClone(d));};
 const helpers={...h,api,$:node,$$:s=>s==='[data-batch-material-job]'?[button]:s==='[data-compare-task]'?[task]:[],on:(id,event,fn)=>events.set(id+':'+event,fn),header:(...v)=>v.join(''),modal:(...v)=>{revision++;modals.push(v)},toast:()=>{},go:()=>{},isCurrent:()=>active,getModalRevision:()=>revision};
 return {h:helpers,node,requests,modals,events,button,leave:()=>{active=false},fire:(id,event='click',value={})=>events.get(id+':'+event)(value)};
}
async function open(x){const w=createJointComparison(x.h);await w.render(new URLSearchParams({study:d.study.id}),1);x.fire('#compare-material-tab');return w}
await check('material tab exposes the selected shared pool and explicit full-scope export boundary',async()=>{
 const x=setup();await open(x);assert(x.node('#compare-body').innerHTML.includes('批次获料对照'));assert(x.node('#batch-material-context').innerHTML.includes('满宽 = 本物料最大单批需求 85.699 kg'));
 assert(x.node('#batch-material-rows').innerHTML.includes('SP-261009-001-B002'));assert(x.node('#compare-body').innerHTML.includes('完整两列导出保持不变'));
});
await check('recipient drill selects exact job and material tasks without changed-only loss',async()=>{
 const x=setup();await open(x);x.fire('recipient');assert.equal(x.node('#compare-job').value,'SP-261009-001-B001');assert.equal(x.node('#compare-changed').checked,false);
 assert(x.node('#compare-page').textContent.includes('当前清单 2 项 / 全案 52 项'));assert(x.node('#compare-body').innerHTML.includes('01.01.0002 / kg'));
});
await check('manual job selection intersects the selected material and reset restores all',async()=>{
 const x=setup();await open(x);x.fire('recipient');x.node('#compare-job').value='SP-261009-001-B002';x.fire('#compare-job','change');assert(x.node('#compare-page').textContent.includes('2 项 / 全案 52 项'));
 x.fire('#compare-task-reset');assert.equal(x.node('#compare-job').value,'');assert(x.node('#compare-page').textContent.includes('52 项 / 全案 52 项'));assert(x.node('#compare-body').innerHTML.includes('全部物料'));
});
await check('switching tabs preserves explicit material and task reading scope',async()=>{
 const x=setup();await open(x);x.fire('recipient');x.fire('#compare-material-tab');assert.equal(x.node('#batch-material-select').value,String(index));x.fire('#compare-task-tab');assert(x.node('#compare-page').textContent.includes('2 项 / 全案 52 项'));
});
await check('material changes and changes-only filters refresh rows and preserve quantities',async()=>{
 const x=setup();await open(x);x.node('#batch-material-select').value='1';x.fire('#batch-material-select','change');assert(x.node('#batch-material-rows').innerHTML.includes(report.materials[1].unit));
 x.node('#batch-material-changed').checked=true;x.fire('#batch-material-changed','change');assert(x.node('#batch-material-page').textContent.includes('本物料 2 批次'));
});
await check('recipient filters never narrow sources or complete export requests',async()=>{
 const p=pending(),x=setup(path=>path.endsWith('/export')?p.promise:undefined);await open(x);x.fire('recipient');await x.fire('#compare-sources');
 assert.deepEqual(x.requests.at(-1).options.body,{receipt:'COMPARISON',page:1});assert(x.modals.at(-1)[1].includes('741'));
 // Stop before any browser download; inspect the request and suppress its response.
 const request=x.fire('#compare-json');assert.deepEqual(x.requests.at(-1).options.body,{receipt:'COMPARISON',format:'json'});x.leave();p.resolve({text:'{}',mime:'application/json',filename:'all.json'});await request;
});
await check('changing reading scope cancels a pending task modal',async()=>{
 const p=pending(),x=setup(path=>path.includes('/tasks/')?p.promise:undefined);await open(x);x.fire('recipient');const request=x.fire('task');x.fire('#compare-material-tab');
 p.resolve({task:d.tasks[0],left:{demands:[],reservations:[]},right:{demands:[],reservations:[]},notice:'OLD'});await request;assert.equal(x.modals.length,0);
});
await check('rereading starts with fresh default scope and no old local selectors',async()=>{
 const x=setup();await open(x);x.fire('recipient');await x.fire('#compare-refresh');assert.equal(x.node('#compare-job').value,'');assert.equal(x.node('#compare-changed').checked,true);
});
await check('forged recipient identity cannot drill into another material or job',async()=>{
 const x=setup();await open(x);x.button.dataset.batchMaterialUnit='UNKNOWN';x.fire('recipient');assert(x.node('#compare-body').innerHTML.includes('批次获料对照'));
});
console.log(JSON.stringify({success:true,checks:names.length,names,source:'normally imported synthetic Excel comparisons',browser_acceptance:false}));
