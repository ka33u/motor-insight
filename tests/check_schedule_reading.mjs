// Pure data, HTML-string and request-state checks. No browser or DOM automation.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {createFiniteScheduleWorkspace,gantt} from '../static/finite_schedule.js';
import {createCrewScheduleWorkspace,crewGantt} from '../static/crew_schedule.js';
import {createJointScheduleWorkspace} from '../static/joint_schedule.js';
import {createJointComparison} from '../static/joint_compare.js';
import {scheduleTaskDetail,scheduleSources} from '../static/schedule_reading.js';
const read=name=>JSON.parse(fs.readFileSync(new URL('fixtures/'+name,import.meta.url)));
const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const table=(headers,rows)=>{assert(rows.every(row=>row.length===headers.length));return '<table><thead><tr>'+headers.map(h=>'<th>'+esc(h)+'</th>').join('')+'</tr></thead><tbody>'+rows.map(r=>'<tr>'+r.map(v=>'<td>'+v+'</td>').join('')+'</tr>').join('')+'</tbody></table>'};
const panel=(title,subtitle,content)=>{assert.equal(typeof content,'string','Missing panel content: '+title);return `<section><h2>${esc(title)}</h2><p>${esc(subtitle)}</p>${content}</section>`};
assert(fs.readFileSync(new URL('../static/app.js',import.meta.url),'utf8').includes("function panel(title,subtitle,content,action='',cls='')"));
const helpers={esc,table,panel},details=read('schedule_task_reading.json');
const deferred=()=>{let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b});return{promise,resolve,reject}};
const tick=()=>new Promise(r=>setImmediate(r));
function harness(respond){
 const nodes=new Map(),events=new Map(),groups=new Map(),requests=[],modals=[],toasts=[],moves=[],close=[];let active=true,revision=0;
 const node=id=>{if(!nodes.has(id))nodes.set(id,{innerHTML:'',textContent:'',value:'',checked:true,disabled:false});return nodes.get(id)};
 const h={...helpers,api:(...args)=>{requests.push(args);return respond(...args)},header:(t,s,a='')=>`<header>${esc(t)}${esc(s)}${a}</header>`,modal:(...args)=>{revision++;modals.push(args)},toast:t=>toasts.push(t),go:(...args)=>moves.push(args),$:node,$$:s=>groups.get(s)||[],on:(s,e,f)=>{if(s==='#detail'&&e==='close')close.push(f);else events.set(s+':'+e,f)},isCurrent:()=>active,getModalRevision:()=>revision};
 return {h,node,events,requests,modals,toasts,moves,leave:()=>{active=false},replace:()=>{revision++},close:()=>close.forEach(f=>f()),fire:(s,e='click',value={})=>{assert(events.has(s+':'+e),'missing '+s+':'+e);return events.get(s+':'+e)(value)},button(selector,field,id){const item={tagName:'BUTTON',dataset:{[field]:id},addEventListener:(e,f)=>events.set(selector+':'+id+':'+e,f)};groups.set(selector,[...(groups.get(selector)||[]),item])}};
}
const names=[];async function check(name,fn){await fn();names.push(name)}
const factories={finite:createFiniteScheduleWorkspace,crew:createCrewScheduleWorkspace,joint:createJointScheduleWorkspace};
for(const [mode,factory] of Object.entries(factories)){
 const d={...read(mode+'_schedule_board_001_due.json'),receipt:'SIM-READING',source_count:81},list={rows:[d.study],policies:{due:'应完成时间优先',priority:'批次优先级优先'}};
 const source={rows:details[mode].scheduled.sources.slice(0,2),page:1,size:20,total:81,can_download_original:false};
 const normal=path=>Promise.resolve(structuredClone(path===mode+'-schedule'?list:path.includes('/sources?')?source:path.includes('/tasks/')?details[mode].scheduled:d));
 const setup=respond=>{const x=harness(respond||normal);x.button('[data-'+mode+'-task]',mode+'Task',d.tasks[0].id);return x};
 await check(mode+': actual panel contract exposes tables and complete chart',async()=>{
  const x=setup();await factory(x.h).render(new URLSearchParams(),1);const html=x.node('#main').innerHTML+x.node('#joint-body').innerHTML;
  assert(html.includes('<table>'));assert(html.includes('<svg'));assert(!html.includes('&lt;table'));assert(!html.includes('undefined'));assert(html.includes('50'));assert(html.includes('198'));assert(html.includes('重新读取'));
  if(mode==='joint'){x.fire('#joint-tab-material');assert(x.node('#joint-body').innerHTML.includes('<table>'));assert(x.node('#joint-body').innerHTML.includes('FIFO预留流水'));x.fire('#joint-tab-schedule');}
 });
 await check(mode+': source-backed task detail keeps identifiers times units and original permission',async()=>{
  const x=setup();await factory(x.h).render(new URLSearchParams(),1);await x.fire('[data-'+mode+'-task]:'+d.tasks[0].id);const html=x.modals[0][1];
  assert(html.includes(d.tasks[0].id));assert(html.includes('<table>'));assert(!html.includes('<pre'));assert(!html.includes('dependency_ready'));assert(html.includes('前序准备时点'));assert(html.includes('原件'));assert(x.requests.at(-1)[0].includes('receipt=SIM-READING'));
 });
 await check(mode+': missing completion and zero wait stay distinct',()=>{
  const html=scheduleTaskDetail(details[mode].blocked,helpers,mode);assert(html.includes('未形成时间'));assert(html.includes('未排入'));assert(!html.includes('undefined'));
  const complete=scheduleTaskDetail(details[mode].scheduled,helpers,mode);assert(complete.includes('<td>0</td>'));assert(complete.includes('换型分钟'));assert(complete.includes('加工开始'));
 });
 await check(mode+': latest modal intent wins across task and sources including old rejection',async()=>{
  for(const reject of [false,true]){const a=deferred(),b=deferred(),x=setup(path=>path.includes('/tasks/')?a.promise:path.includes('/sources?')?b.promise:normal(path));await factory(x.h).render(new URLSearchParams(),1);const old=x.fire('[data-'+mode+'-task]:'+d.tasks[0].id),latest=x.fire('#'+mode+'-sources');b.resolve(source);await latest;if(reject)a.reject(Error('STALE'));else a.resolve(details[mode].scheduled);await old;assert.equal(x.modals.length,1);assert(x.modals[0][1].includes('81 条'));assert.deepEqual(x.toasts,[])}
 });
 await check(mode+': closing replacing and leaving discard pending task',async()=>{
  for(const action of ['close','replace','leave']){const a=deferred(),x=setup(path=>path.includes('/tasks/')?a.promise:normal(path));await factory(x.h).render(new URLSearchParams(),1);const request=x.fire('[data-'+mode+'-task]:'+d.tasks[0].id);x[action]();a.resolve(details[mode].scheduled);await request;assert.deepEqual(x.modals,[])}
 });
 await check(mode+': older board and failure cannot override latest same-route read',async()=>{
  for(const reject of [false,true]){let reads=0;const a=deferred(),x=setup(path=>path===mode+'-schedule'?Promise.resolve(list):++reads===1?a.promise:Promise.resolve({...d,study:{...d.study,assumptions:'LATEST'}})),w=factory(x.h),first=w.render(new URLSearchParams(),1);await tick();await w.render(new URLSearchParams(),1);if(reject)a.reject(Error('STALE'));else a.resolve({...d,study:{...d.study,assumptions:'STALE'}});await first;assert(x.node('#main').innerHTML.includes('LATEST'));assert(!x.node('#main').innerHTML.includes('STALE'));}
 });
 await check(mode+': refresh discards expired receipt and shows current failure',async()=>{
  let reads=0;const x=setup(path=>path===mode+'-schedule'?Promise.resolve(list):++reads===1?Promise.resolve(d):Promise.reject(Error('CURRENT')));await factory(x.h).render(new URLSearchParams({receipt:'OLD'}),1);await x.fire('#'+mode+'-refresh');assert(!x.requests.at(-1)[0].includes('receipt='));assert.deepEqual(x.toasts,['CURRENT']);
 });
 await check(mode+': full sources honor returned page size and remain unfiltered',async()=>{
  const x=setup();await factory(x.h).render(new URLSearchParams(),1);if(mode==='joint'){x.node('#joint-job').value=d.jobs[0].id;x.fire('#joint-job','change');assert(x.node('#joint-tasks').innerHTML.includes('不改变上方汇总'));}
  await x.fire('#'+mode+'-sources');assert(!x.modals[0][1].includes('id="'+mode+'-next" disabled'));await x.fire('#'+mode+'-next');assert(x.requests.at(-1)[0].includes('page=2'));assert(!x.requests.at(-1)[0].includes('job='));
 });
 await check(mode+': duplicate export and stale download are suppressed',async()=>{
  const previous=globalThis.fetch,a=deferred(),calls=[];globalThis.fetch=(...args)=>{calls.push(args);return a.promise};
  try{const x=setup();await factory(x.h).render(new URLSearchParams(),1);const request=x.fire('#'+mode+'-csv');await x.fire('#'+mode+'-json');assert.equal(calls.length,1);assert(calls[0][0].includes('receipt=SIM-READING'));assert(!calls[0][0].includes('job='));x.leave();a.resolve({ok:true});await request;}finally{globalThis.fetch=previous}
 });
 await check(mode+': paused input remains explicit and inspectable',async()=>{
  const paused=read(mode+'_schedule_board_'+(mode==='joint'?'007':'005')+'_due.json');const x=setup(path=>Promise.resolve(path===mode+'-schedule'?list:{...paused,receipt:'PAUSED',source_count:2}));await factory(x.h).render(new URLSearchParams(),1);assert(x.node('#main').innerHTML.includes('未计算'));assert(x.events.has('#'+mode+'-sources:click'));assert(!x.node('#main').innerHTML.includes('finite-summary'));
 });
}
await check('task evidence escapes IDs notes reasons and Excel names',()=>{
 const d=structuredClone(details.joint.blocked);d.row.reason='<script>';d.sources[0].filename='<img onerror="bad">';d.demands[0].material_id='<svg>';d.notice='<b>bad';const html=scheduleTaskDetail(d,helpers,'joint');for(const raw of ['<script>','<img','<svg>','<b>bad'])assert(!html.includes(raw));assert(html.includes('&lt;script&gt;'));assert(html.includes('&lt;svg&gt;'));assert(!html.includes('undefined'));
});
await check('material shortage stays per unit with exact demand and reservation identity',()=>{
 const d=details.joint.blocked,html=scheduleTaskDetail(d,helpers,'joint');assert(d.row.shortages.length);for(const field of ['required_qty','available_qty','shortage_qty'])assert(html.includes(d.row.shortages[0][field]));assert(html.includes('本任务新增预留的需求号'));assert(html.includes('不同物料与单位不合计'));assert(html.includes('kg'));
 const good=details.joint.scheduled,text=scheduleTaskDetail(good,helpers,'joint');for(const a of good.reservations){assert(text.includes(a.supply_id));assert(text.includes(a.task_id));assert(text.includes(a.qty));}
});
await check('shared reservation by another task is not presented as new material issue',()=>{
 const d=structuredClone(details.joint.scheduled);d.row.new_reservation_ids=[];d.reservations[0].task_id='OTHER-PORTION';d.demands[0].reservation.task_id='OTHER-PORTION';const html=scheduleTaskDetail(d,helpers,'joint');assert(html.includes('OTHER-PORTION'));assert(html.includes('新增预留的需求号：无'));assert(html.includes('不等于本任务新领料'));
});
await check('crew versus resource axes are named accurately',()=>{
 const d=read('crew_schedule_board_001_due.json');assert(crewGantt(d,'worker').includes('纵轴是操作工号'));assert(crewGantt(d,'resource').includes('纵轴是独立资源位'));assert(gantt(read('finite_schedule_board_001_due.json')).includes('纵轴是独立资源位'));
});
await check('missing sources and original access remain explicit',()=>{
 const html=scheduleSources([{dataset:'schedule_tasks',key:'missing',missing:true}],helpers);assert(html.includes('来源缺失'));assert(!html.includes('undefined'));const d=structuredClone(details.crew.scheduled);d.can_download_original=false;assert(scheduleTaskDetail(d,helpers,'crew').includes('不授予原件下载权限'));
});
const comparison={...read('joint_comparison_board_001.json'),receipt:'COMPARE-SIM',policy_receipts:{due:'DUE-SIM',priority:'PRIORITY-SIM'}},list={rows:[comparison.study]};
const normalCompare=path=>Promise.resolve(structuredClone(path==='joint-schedule'?list:comparison));
await check('comparison uses real three-argument panels in both tabs',async()=>{
 const x=harness(normalCompare);await createJointComparison(x.h).render(new URLSearchParams(),1);assert(x.node('#main').innerHTML.includes('<table>'));assert(!x.node('#main').innerHTML.includes('&lt;table'));x.fire('#compare-material-tab');assert(x.node('#compare-body').innerHTML.includes('<table>'));x.fire('#compare-task-tab');assert(x.node('#compare-body').innerHTML.includes('只看发生变化'));
});
await check('comparison source intent supersedes a pending task and its failure',async()=>{
 const a=deferred(),x=harness(path=>path.includes('/tasks/')?a.promise:path.endsWith('/sources')?Promise.resolve({rows:[],page:1,size:20,total:41}):normalCompare(path));const id=comparison.tasks[0].id;x.button('[data-compare-task]','compareTask',id);await createJointComparison(x.h).render(new URLSearchParams(),1);const old=x.fire('[data-compare-task]:'+id);await x.fire('#compare-sources');a.reject(Error('OLD'));await old;assert.equal(x.modals.length,1);assert(x.modals[0][0].includes('完整Excel来源'));assert.deepEqual(x.toasts,[]);
});
await check('switching between single and comparison discards previous view reads',async()=>{
 const base=read('joint_schedule_board_001_due.json');for(const firstCompare of [true,false]){const a=deferred();let wait=true;const x=harness(path=>path==='joint-schedule'?Promise.resolve({rows:[base.study],policies:{due:'到期优先'}}):wait?a.promise:Promise.resolve(path.startsWith('joint-comparison/')?comparison:{...base,receipt:'SINGLE',source_count:0}));const w=createJointScheduleWorkspace(x.h),old=w.render(new URLSearchParams(firstCompare?{view:'compare'}:{}),1);await tick();wait=false;await w.render(new URLSearchParams(firstCompare?{}:{view:'compare'}),1);const latest=x.node('#main').innerHTML;a.resolve(firstCompare?comparison:{...base,receipt:'OLD',source_count:0});await old;assert.equal(x.node('#main').innerHTML,latest);}
});
console.log(JSON.stringify({success:true,checks:names.length,names,browser_acceptance:false,mobile_acceptance:false,actual_download_acceptance:false}));
