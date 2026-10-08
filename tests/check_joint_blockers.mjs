// Independent hand oracles, HTML strings and request-state harness; no browser/DOM.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {BLOCKER_READING_VERSION,jointBlockerReport,jointTaskSelection,jointBlockerQueue} from '../static/joint_blockers.js';
import {createJointScheduleWorkspace} from '../static/joint_schedule.js';
const read=name=>JSON.parse(fs.readFileSync(new URL('fixtures/'+name,import.meta.url)));
const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const table=(headers,rows)=>{assert(rows.every(r=>r.length===headers.length));return '<table><thead>'+headers.map(v=>'<th>'+esc(v)+'</th>').join('')+'</thead>'+rows.map(r=>'<tr>'+r.map(v=>'<td>'+v+'</td>').join('')+'</tr>').join('')+'</table>'};
const panel=(title,subtitle,content)=>{assert.equal(typeof content,'string');return `<section><h2>${esc(title)}</h2><p>${esc(subtitle)}</p>${content}</section>`};
const h={esc,table,panel},names=[];async function check(name,fn){await fn();names.push(name)}
const job=(id,qty,due,state='blocked')=>({id,qty,due,state});
const task=(id,job_id,root_tasks)=>({id,job_id,root_tasks,state:root_tasks.length?'blocked':'scheduled',process:'模拟工序',branch:'模拟分支',reason:'模拟原因'});
const manual={state:'trial',jobs:[job('J1',8,'2026-10-10T12:00:00'),job('J2',12,'2026-10-09T12:00:00'),job('J3',3,'2026-10-08T12:00:00','scheduled')],tasks:[task('A','J1',['A']),task('B','J1',['B']),task('C','J1',['A','B']),task('D','J2',['A']),task('E','J3',[])],summary:{jobs:3,qty:23,tasks:5,blocked_tasks:4,blocked_jobs:2,scheduled_tasks:1}};
const report=jointBlockerReport(manual),five=read('joint_blocker_board_005_due.json'),six=read('joint_blocker_board_006_due.json');
await check('hand oracle deduplicates jobs and tasks with multiple roots',()=>{
 assert.equal(report.version,BLOCKER_READING_VERSION);assert.equal(report.state,'blocked');assert.deepEqual(report.summary,{roots:2,tasks:4,jobs:2,batch_qty:20,overlapping_tasks:1});
 assert.deepEqual(report.rows.map(r=>[r.id,r.task_ids,r.job_ids,r.tasks,r.jobs,r.batch_qty,r.earliest_due,r.overlapping_tasks]),[['A',['A','C','D'],['J1','J2'],3,2,20,'2026-10-09T12:00:00',1],['B',['B','C'],['J1'],2,1,8,'2026-10-10T12:00:00',1]]);
});
await check('actual dual material case has 32 tasks and 8 units despite 56 memberships',()=>{
 const r=jointBlockerReport(five);assert.deepEqual(r.summary,{roots:2,tasks:32,jobs:1,batch_qty:8,overlapping_tasks:24});assert.equal(r.rows.reduce((s,r)=>s+r.tasks,0),56);assert.equal(r.rows.reduce((s,r)=>s+r.batch_qty,0),16);
});
await check('actual absent worker case preserves 198 tasks 6 jobs 50 units and 150 overlaps',()=>{
 const r=jointBlockerReport(six);assert.deepEqual(r.summary,{roots:12,tasks:198,jobs:6,batch_qty:50,overlapping_tasks:150});assert.equal(r.rows.reduce((s,r)=>s+r.tasks,0),348);assert.equal(r.rows.reduce((s,r)=>s+r.batch_qty,0),100);
});
await check('reading order uses earliest internal target then deterministic tie breakers',()=>{
 const d=structuredClone(manual);d.jobs[1].due=d.jobs[0].due;assert.deepEqual(jointBlockerReport(d).rows.map(r=>r.id),['A','B']);
 const a=jointBlockerReport(six),b=jointBlockerReport({...six,tasks:[...six.tasks].reverse(),jobs:[...six.jobs].reverse()});assert.deepEqual(a,b);for(let i=1;i<a.rows.length;i++)assert(a.rows[i-1].earliest_due<=a.rows[i].earliest_due);
});
await check('clear and paused states cannot masquerade as zero-risk operations',()=>{
 const clear=jointBlockerReport(read('joint_schedule_board_001_due.json')),paused=jointBlockerReport(read('joint_schedule_board_007_due.json'));
 assert.equal(clear.state,'clear');assert.equal(paused.state,'paused');assert.equal(paused.summary,null);assert(jointBlockerQueue(clear,h).includes('仍须分别核对'));assert(jointBlockerQueue(paused,h).includes('暂停核对'));
});
await check('reject missing duplicate and non-original root links',()=>{
 for(const edit of [d=>d.tasks[0].root_tasks=['MISSING'],d=>d.tasks[2].root_tasks=['A','A'],d=>d.tasks[2].root_tasks=['D'],d=>delete d.tasks[0].root_tasks,d=>d.tasks[0].state='scheduled']){const d=structuredClone(manual);edit(d);const r=jointBlockerReport(d);assert.equal(r.state,'paused');assert.equal(r.summary,null);assert.equal(r.rows.length,0);}
});
await check('reject duplicate identities orphan jobs and summary truncation',()=>{
 for(const edit of [d=>d.tasks.push(d.tasks[0]),d=>d.jobs.push(d.jobs[0]),d=>d.tasks[0].job_id='ABSENT',d=>d.summary.tasks++,d=>d.tasks.pop(),d=>d.jobs[0].state='late',d=>d.summary.qty--]){const d=structuredClone(manual);edit(d);assert.equal(jointBlockerReport(d).state,'paused');}
});
await check('reject missing fractional negative or unsafe batch quantities',()=>{
 for(const value of [undefined,null,0,-1,1.5,'8',Number.MAX_SAFE_INTEGER+1]){const d=structuredClone(manual);d.jobs[0].qty=value;assert.equal(jointBlockerReport(d).state,'paused');}
 const d=structuredClone(manual);d.jobs[0].qty=Number.MAX_SAFE_INTEGER;assert.equal(jointBlockerReport(d).state,'paused');
});
await check('strict internal wall dates reject missing offset and invalid calendar values',()=>{
 for(const due of [null,'','2026-02-30T12:00:00','2026-10-09','2026-10-09T12:00:00Z','2026-10-09T12:00:00+08:00']){const d=structuredClone(manual);d.jobs[0].due=due;assert.equal(jointBlockerReport(d).state,'paused');}
});
await check('exact root selection intersects job and state without substring matching',()=>{
 assert.deepEqual(jointTaskSelection(manual,report,{root:'A'}).map(t=>t.id),['A','C','D']);assert.deepEqual(jointTaskSelection(manual,report,{root:'A',job:'J1',state:'blocked'}).map(t=>t.id),['A','C']);assert.deepEqual(jointTaskSelection(manual,report,{root:'A',state:'scheduled'}),[]);assert.deepEqual(jointTaskSelection(manual,report,{}),manual.tasks);
 for(const scope of [{root:'a'},{job:'J'},{state:'late'}])assert.throws(()=>jointTaskSelection(manual,report,scope));
});
await check('queue states whole scope and nonadditive quantities without inventing dispatch priority',()=>{
 const html=jointBlockerQueue(report,h);for(const text of ['4 项未排入任务','2 个批次 / 20 台','不能跨行相加','不是损失产量或客户逾期量','不是优先级优化或交付承诺','最早内部应完成'])assert(html.includes(text));assert(!html.includes('undefined'));
});
await check('queue pagination covers every root without truncating full-scope summary',()=>{
 const r={...report,summary:{...report.summary,roots:81},rows:Array.from({length:81},(_,i)=>({...report.rows[0],id:'ROOT-'+String(i).padStart(3,'0')}))};
 const seen=[];for(const page of [1,2,3]){const html=jointBlockerQueue(r,h,{page});seen.push(...[...html.matchAll(/data-joint-root-detail="([^"]+)"/g)].map(m=>m[1]));assert(html.includes('81 个首阻断'));}assert.deepEqual(seen,r.rows.map(r=>r.id));assert(jointBlockerQueue(r,h,{page:3}).includes('id="joint-root-next" disabled'));assert.throws(()=>jointBlockerQueue(r,h,{page:0}));
});
await check('all imported identifiers labels reasons and dates are escaped',()=>{
 const r=structuredClone(report);Object.assign(r.rows[0],{id:'X" onclick="bad',process:'<script>',branch:'<svg>',reason:'<img>',job_ids:['<b>']});const html=jointBlockerQueue(r,h);for(const value of ['onclick="bad','<script>','<svg>','<img>','<b>'])assert(!html.includes(value));assert(html.includes('&lt;script&gt;'));
});
await check('report filters and presentation leave complete source result immutable',()=>{
 const d=structuredClone(six),before=JSON.stringify(d),r=jointBlockerReport(d);jointTaskSelection(d,r,{root:r.rows[0].id});jointBlockerQueue(r,h);assert.equal(JSON.stringify(d),before);
});
const pending=()=>{let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b});return{promise,resolve,reject}};
function harness(respond){
 const nodes=new Map(),events=new Map(),groups=new Map(),requests=[],modals=[],toasts=[],moves=[],close=[];let revision=0,active=true;
 const node=id=>{if(!nodes.has(id))nodes.set(id,{innerHTML:'',value:'',disabled:false});return nodes.get(id)};
 const controls={...h,api:(path,opts)=>{requests.push({path,opts});return respond(path,opts)},header:(t,s,a='')=>t+s+a,modal:(...args)=>{revision++;modals.push(args)},toast:v=>toasts.push(v),go:(...a)=>moves.push(a),$:node,$$:s=>groups.get(s)||[],on:(s,e,f)=>{if(s==='#detail')close.push(f);else events.set(s+':'+e,f)},isCurrent:()=>active,getModalRevision:()=>revision};
 return {h:controls,node,requests,modals,toasts,moves,leave:()=>{active=false},close:()=>close.forEach(f=>f()),fire:(id,event='click',value={})=>{assert(events.has(id+':'+event),id);return events.get(id+':'+event)(value)},button(selector,field,id){groups.set(selector,[{dataset:{[field]:id},addEventListener:(e,f)=>events.set(selector+':'+id+':'+e,f)}])}};
}
const board={...six,receipt:'SIM-BLOCKERS',source_count:2030},first=jointBlockerReport(board).rows[0],list={rows:[board.study],policies:{due:'内部目标优先',priority:'批次优先级'}};
const normal=path=>Promise.resolve(structuredClone(path==='joint-schedule'?list:path.includes('/sources?')?{rows:[],total:2030,page:1,size:40}:board));
function setup(respond=normal){const x=harness(respond);x.button('[data-joint-root-focus]','jointRootFocus',first.id);x.button('[data-joint-root-detail]','jointRootDetail',first.id);return x}
await check('click association resets contradictory filters and displays every exact member',async()=>{
 const x=setup();await createJointScheduleWorkspace(x.h).render(new URLSearchParams(),1);x.node('#joint-job').value=board.jobs.find(j=>j.id!==first.job_id).id;x.fire('#joint-job','change');x.node('#joint-state').value='scheduled';x.fire('#joint-state','change');x.fire('[data-joint-root-focus]:'+first.id);
 assert.equal(x.node('#joint-job').value,'');assert.equal(x.node('#joint-state').value,'blocked');assert.equal(x.node('#joint-root').value,first.id);assert(x.node('#joint-tasks').innerHTML.includes('34 / 全方案 198'));assert.deepEqual([...x.node('#joint-tasks').innerHTML.matchAll(/data-joint-task="([^"]+)"/g)].map(m=>m[1]).sort(),first.task_ids);assert(x.node('#joint-root-queue').innerHTML.includes('aria-pressed="true"'));assert(x.node('#main').innerHTML.includes('198'));
});
await check('manual filters intersect and reset restores complete tasks without changing queue',async()=>{
 const x=setup();await createJointScheduleWorkspace(x.h).render(new URLSearchParams(),1);x.node('#joint-root').value=first.id;x.fire('#joint-root','change');x.node('#joint-state').value='scheduled';x.fire('#joint-state','change');assert(x.node('#joint-tasks').innerHTML.includes('0 / 全方案 198'));assert(x.node('#joint-tasks').innerHTML.includes('不表示全方案没有阻断'));assert(x.node('#joint-root-queue').innerHTML.includes('198 项未排入任务'));x.fire('#joint-task-reset');assert(x.node('#joint-tasks').innerHTML.includes('198 / 全方案 198'));assert.equal(x.node('#joint-root').value,'');
});
await check('reading tabs preserve filters and chart axis while reread clears old scope',async()=>{
 const x=setup(),workspace=createJointScheduleWorkspace(x.h);await workspace.render(new URLSearchParams(),1);x.fire('[data-joint-root-focus]:'+first.id);x.fire('#joint-worker');x.fire('#joint-tab-material');x.fire('#joint-tab-schedule');assert.equal(x.node('#joint-root').value,first.id);assert(x.node('#joint-body').innerHTML.includes('纵轴是操作工号'));assert(x.node('#joint-tasks').innerHTML.includes('34 / 全方案 198'));await x.fire('#joint-refresh');assert.equal(x.node('#joint-root').value,'');assert(x.node('#joint-body').innerHTML.includes('纵轴是独立资源位'));assert(x.node('#joint-tasks').innerHTML.includes('198 / 全方案 198'));
});
await check('changing study or policy retains only explicit study and policy navigation',async()=>{
 const x=setup();await createJointScheduleWorkspace(x.h).render(new URLSearchParams(),1);x.fire('[data-joint-root-focus]:'+first.id);x.fire('#joint-policy','change',{target:{value:'priority'}});x.fire('#joint-study','change',{target:{value:'MP-261002-005'}});assert.deepEqual(x.moves,[['joint-schedule',{study:board.study.id,policy:'priority'}],['joint-schedule',{study:'MP-261002-005',policy:'due'}]]);
});
await check('root detail uses existing candidate API exact ID current policy and receipt',async()=>{
 const b={...read('joint_candidate_board_002_due.json'),receipt:'ROOT-DETAIL',source_count:2030},detail=read('joint_candidate_details.json').shortage,id=detail.row.id;
 const x=harness(path=>Promise.resolve(path==='joint-schedule'?{rows:[b.study],policies:list.policies}:path.includes('/tasks/')?detail:b));x.button('[data-joint-root-detail]','jointRootDetail',id);await createJointScheduleWorkspace(x.h).render(new URLSearchParams({policy:'priority'}),1);await x.fire('[data-joint-root-detail]:'+id);assert.equal(x.requests.at(-1).path,'joint-schedule/'+b.study.id+'/tasks/'+encodeURIComponent(id)+'?policy=priority&receipt=ROOT-DETAIL');assert(x.modals[0][1].includes('候选人机与窗口依据'));
});
await check('filter change suppresses pending old root detail and its rejection',async()=>{
 for(const fail of [false,true]){const p=pending(),x=setup(path=>path.includes('/tasks/')?p.promise:normal(path));await createJointScheduleWorkspace(x.h).render(new URLSearchParams(),1);const request=x.fire('[data-joint-root-detail]:'+first.id);x.fire('#joint-task-reset');if(fail)p.reject(Error('OLD'));else p.resolve(read('joint_candidate_details.json').shortage);await request;assert.deepEqual(x.modals,[]);assert.deepEqual(x.toasts,[]);}
});
await check('full source request and export remain receipt bound and unfiltered',async()=>{
 const previous=globalThis.fetch,p=pending(),calls=[];globalThis.fetch=(...args)=>{calls.push(args);return p.promise};
 try{const x=setup();await createJointScheduleWorkspace(x.h).render(new URLSearchParams(),1);x.fire('[data-joint-root-focus]:'+first.id);await x.fire('#joint-sources');assert(x.requests.at(-1).path.endsWith('policy=due&receipt=SIM-BLOCKERS&page=1'));const request=x.fire('#joint-json');assert.equal(calls[0][0],'/api/joint-schedule/'+board.study.id+'/export?policy=due&receipt=SIM-BLOCKERS&format=json');x.leave();p.resolve({ok:true});await request;}finally{globalThis.fetch=previous}
});
console.log(JSON.stringify({success:true,checks:names.length,names,browser_acceptance:false,mobile_acceptance:false,actual_download_acceptance:false}));
