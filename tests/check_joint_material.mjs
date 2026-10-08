// Result rendering and asynchronous request-state checks; no browser/DOM automation.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {jointMaterialDetail,jointMaterialLink,materialQuantityBars} from '../static/joint_material.js';
import {createJointScheduleWorkspace} from '../static/joint_schedule.js';
import {scheduleSources,scheduleTaskDetail} from '../static/schedule_reading.js';
const read=name=>JSON.parse(fs.readFileSync(new URL('fixtures/'+name,import.meta.url)));
const fixture=read('joint_material_details.json'),taskFixture=read('joint_candidate_details.json');
const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const table=(headers,rows)=>{assert(rows.every(r=>r.length===headers.length));return '<table><thead>'+headers.map(h=>'<th>'+esc(h)+'</th>').join('')+'</thead>'+rows.map(r=>'<tr>'+r.map(v=>'<td>'+v+'</td>').join('')+'</tr>').join('')+'</table>'};
const panel=(title,subtitle,content)=>{assert.equal(typeof content,'string');return `<section><h2>${esc(title)}</h2><p>${esc(subtitle)}</p>${content}</section>`};
const h={esc,table,panel,sourceTable:rows=>scheduleSources(rows,{esc,table})},names=[];async function check(name,fn){await fn();names.push(name)}
await check('quantity bars share the same scale and keep exact decimal labels',()=>{
 const e=fixture['2'].evidence,html=materialQuantityBars(e,h),widths=[...html.matchAll(/style="width:([0-9.e+-]+)%"/g)].map(m=>Number(m[1]));assert.equal(widths.length,6);
 assert(Math.abs(widths[0]+widths[1]-100)<1e-10);assert(Math.abs(widths.slice(2).reduce((a,b)=>a+b,0)-100*35.108/87.769)<1e-10);
 for(const v of ['30.719','57.05','4.389','不是到料时间轴','数量刻度一致','aria-label="需求：'])assert(html.includes(v));
});
await check('reserved unreserved excluded and outside quantities remain semantically separate',()=>{
 const isolated=jointMaterialDetail(fixture['5'],h),outside=jointMaterialDetail(fixture['10'],h),staff=jointMaterialDetail(fixture['6'],h);
 assert(isolated.includes('排除 87.769 kg'));assert(outside.includes('范围外剩余 87.769 kg'));assert(outside.includes('范围外到料'));assert(staff.includes('未预留不等于缺料'));assert(staff.includes('范围内剩余 44.216 kg'));
});
await check('mixed units are separate inspectors and have explicit headers',()=>{
 const html=jointMaterialDetail(fixture.pieces,h);assert(html.includes('预留量（件）'));assert(html.includes('已预留 25 件'));assert(!html.includes(' kg'));assert(jointMaterialDetail(fixture['1'],h).includes('预留量（kg）'));
});
await check('whole-batch demand keeps all portion task links without multiplying quantity',()=>{
 const e=fixture.pieces.evidence,html=jointMaterialDetail(fixture.pieces,h);assert.equal(e.summary.demands,1);assert(e.demands[0].task_ids.length>1);
 for(const id of e.demands[0].task_ids)assert(html.includes('data-joint-material-task="'+id+'"'));assert(html.includes('共用整批需求'));assert(html.includes('1 条整批需求'));
});
await check('FIFO split preserves complete allocation pairs and algorithm sequence',()=>{
 const e=fixture['4'].evidence,html=jointMaterialDetail(fixture['4'],h);assert.equal(e.allocations.length,3);for(const row of e.allocations){assert(html.includes(row.supply_id));assert(html.includes(row.demand_id));assert(html.includes('<td>'+row.sequence+'</td>'));}assert(html.includes('预留时刻可能不单调'));
});
await check('direct Excel sources and original permission remain explicit',()=>{
 const d=fixture['2'],html=jointMaterialDetail({...d,can_download_original:false},h);for(const row of d.sources){assert(html.includes(esc(row.filename)));assert(html.includes(esc(row.key)));}assert(html.includes('来源索引不授予原件下载权限'));assert(html.includes('完整导出不受物料阅读影响'));
});
await check('identity notes reasons units and source names cannot inject markup',()=>{
 const d=structuredClone(fixture['2']);d.evidence.balance.material_name='<script>';d.evidence.balance.unit='kg<svg>';d.evidence.lots[0].lot='<img>';d.evidence.tasks[0].reason='<iframe>';d.sources[0].filename='X" onclick="bad';
 const html=jointMaterialDetail(d,h);for(const value of ['<script>','<svg>','<img>','<iframe>','onclick="bad'])assert(!html.includes(value));assert(html.includes('&lt;script&gt;'));assert(jointMaterialLink('X" onclick="bad','<svg>','<img>',h).includes('&quot;'));
});
await check('plot rejects unavailable ratios without inventing zero availability',()=>{
 const e=structuredClone(fixture['1'].evidence);e.summary.required_qty='NaN';assert(materialQuantityBars(e,h).includes('未形成有效比例'));e.summary.required_qty='0';e.summary.total_supply_qty='0';assert(!materialQuantityBars(e,h).includes('style="width:'));
});
await check('rendering leaves original Decimal strings and result identity untouched',()=>{
 const before=JSON.stringify(fixture);for(const d of Object.values(fixture)){const html=jointMaterialDetail(d,h);assert(!html.includes('undefined'));assert(!html.includes('<pre'));}assert.equal(JSON.stringify(fixture),before);
});
await check('task demands and shortage rows link exact same-material context',()=>{
 const d=taskFixture.shortage,html=scheduleTaskDetail(d,h,'joint');for(const need of d.demands){assert(html.includes('data-joint-material-id="'+need.material_id+'"'));assert(html.includes('data-joint-material-unit="'+need.unit+'"'));}for(const missing of d.row.shortages)assert(html.includes('data-joint-material-id="'+missing.material_id+'"'));
});
const pending=()=>{let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b});return{promise,resolve,reject}};
function harness(respond){
 const nodes=new Map(),events=new Map(),groups=new Map(),requests=[],modals=[],toasts=[],close=[];let revision=0,active=true;
 const node=id=>{if(!nodes.has(id))nodes.set(id,{innerHTML:'',value:'',disabled:false});return nodes.get(id)};
 const controls={...h,api:(path,opts)=>{requests.push({path,opts});return respond(path,opts)},header:(t,s,a='')=>t+s+a,modal:(...args)=>{revision++;modals.push(args)},toast:v=>toasts.push(v),go:()=>{},$:node,$$:s=>groups.get(s)||[],on:(s,e,f)=>{if(s==='#detail')close.push(f);else events.set(s+':'+e,f)},isCurrent:()=>active,getModalRevision:()=>revision};
 return {h:controls,node,requests,modals,toasts,leave:()=>{active=false},replace:()=>{revision++},close:()=>close.forEach(f=>f()),fire:(id,event='click')=>{assert(events.has(id+':'+event),id);return events.get(id+':'+event)()},button(selector,data){groups.set(selector,[{dataset:data,addEventListener:(e,f)=>events.set(selector+':'+e,f)}])}};
}
const board={...read('joint_candidate_board_002_due.json'),receipt:'MAT-READ',source_count:2030},mat=fixture['2'].evidence.balance,task=taskFixture.shortage.row.id;
const page='#joint-body [data-joint-material-id]',inside='#dialog-content [data-joint-material-id]',link='#dialog-content [data-joint-material-task]';
const normal=path=>Promise.resolve(structuredClone(path==='joint-schedule'?{rows:[board.study],policies:{due:'内部目标优先'}}:path.includes('/materials/')?fixture['2']:path.includes('/tasks/')?taskFixture.shortage:path.includes('/sources?')?{rows:[],page:1,size:40,total:2030}:board));
function setup(respond=normal){const x=harness(respond);x.button(page,{jointMaterialId:mat.material_id,jointMaterialUnit:mat.unit});x.button(inside,{jointMaterialId:mat.material_id,jointMaterialUnit:mat.unit});x.button(link,{jointMaterialTask:task});x.button('[data-joint-task]',{jointTask:task});return x}
await check('material page opens exact material unit policy and receipt',async()=>{
 const x=setup();await createJointScheduleWorkspace(x.h).render(new URLSearchParams(),1);x.fire('#joint-tab-material');assert(x.node('#joint-body').innerHTML.includes('data-joint-material-id'));await x.fire(page);assert.equal(x.requests.at(-1).path,'joint-schedule/'+board.study.id+'/materials/'+mat.material_id+'?policy=due&receipt=MAT-READ&unit=kg');assert(x.modals[0][1].includes('需求与供给构成'));
});
await check('material to task and back retain exact original scope',async()=>{
 const x=setup();await createJointScheduleWorkspace(x.h).render(new URLSearchParams(),1);x.fire('#joint-tab-material');await x.fire(page);await x.fire(link);assert(x.modals.at(-1)[1].includes('返回物料核对'));assert(x.modals.at(-1)[1].includes('候选人机与窗口依据'));await x.fire(inside);assert.equal(x.modals.length,3);assert(x.requests.at(-1).path.includes('/materials/'+mat.material_id+'?policy=due&receipt=MAT-READ&unit=kg'));
});
await check('task demand drill reaches material inspector with same receipt',async()=>{
 const x=setup();await createJointScheduleWorkspace(x.h).render(new URLSearchParams(),1);await x.fire('[data-joint-task]');await x.fire(inside);assert(x.requests.at(-1).path.includes('/materials/'));assert.equal(x.modals.length,2);
});
await check('newer sources or task suppress pending material result and failure',async()=>{
 for(const target of ['#joint-sources','[data-joint-task]'])for(const fail of [false,true]){
  const p=pending(),x=setup(path=>path.includes('/materials/')?p.promise:normal(path));await createJointScheduleWorkspace(x.h).render(new URLSearchParams(),1);x.fire('#joint-tab-material');const request=x.fire(page);await x.fire(target);if(fail)p.reject(Error('OLD'));else p.resolve(fixture['2']);await request;assert.equal(x.modals.length,1);assert.deepEqual(x.toasts,[]);
 }
});
await check('close replace leave and reread invalidate pending material detail',async()=>{
 for(const action of ['close','replace','leave','refresh']){
  const p=pending(),x=setup(path=>path.includes('/materials/')?p.promise:normal(path));await createJointScheduleWorkspace(x.h).render(new URLSearchParams(),1);x.fire('#joint-tab-material');const request=x.fire(page);if(action==='refresh')await x.fire('#joint-refresh');else x[action]();p.resolve(fixture['2']);await request;assert.equal(x.modals.length,0);
 }
});
await check('current material API conflict is shown without reusing an old report',async()=>{
 const x=setup(path=>path.includes('/materials/')?Promise.reject(Error('请重新读取')):normal(path));await createJointScheduleWorkspace(x.h).render(new URLSearchParams(),1);x.fire('#joint-tab-material');await x.fire(page);assert.deepEqual(x.toasts,['请重新读取']);assert.equal(x.modals.length,0);
});
await check('material inspection does not narrow complete export or all-source request',async()=>{
 const previous=globalThis.fetch,p=pending(),calls=[];globalThis.fetch=(...args)=>{calls.push(args);return p.promise};
 try{const x=setup();await createJointScheduleWorkspace(x.h).render(new URLSearchParams(),1);x.fire('#joint-tab-material');await x.fire(page);await x.fire('#joint-sources');assert(x.requests.at(-1).path.endsWith('policy=due&receipt=MAT-READ&page=1'));const request=x.fire('#joint-json');assert.equal(calls[0][0],'/api/joint-schedule/'+board.study.id+'/export?policy=due&receipt=MAT-READ&format=json');x.leave();p.resolve({ok:true});await request;}finally{globalThis.fetch=previous}
});
console.log(JSON.stringify({success:true,checks:names.length,names,browser_acceptance:false,mobile_acceptance:false,actual_download_acceptance:false}));
