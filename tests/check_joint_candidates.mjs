// Pure result rendering and asynchronous state checks; no browser/DOM automation.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {jointCandidateEvidence} from '../static/joint_candidates.js';
import {scheduleTaskDetail} from '../static/schedule_reading.js';
import {createJointScheduleWorkspace} from '../static/joint_schedule.js';
const read=name=>JSON.parse(fs.readFileSync(new URL('fixtures/'+name,import.meta.url)));
const fixtures=read('joint_candidate_details.json'),board={...read('joint_candidate_board_002_due.json'),receipt:'SIM-CANDIDATES',source_count:2030};
const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const table=(headers,rows)=>{assert(rows.every(r=>r.length===headers.length));return '<table><thead>'+headers.map(h=>'<th>'+esc(h)+'</th>').join('')+'</thead><tbody>'+rows.map(r=>'<tr>'+r.map(v=>'<td>'+v+'</td>').join('')+'</tr>').join('')+'</tbody></table>'};
const panel=(title,subtitle,content)=>{assert.equal(typeof content,'string');return `<section><h2>${esc(title)}</h2><p>${esc(subtitle)}</p>${content}</section>`};
const h={esc,table,panel},names=[];const check=async(name,fn)=>{await fn();names.push(name)};
await check('scheduled candidates keep exact selected option and worker identifiers',()=>{
 const d=fixtures.scheduled.candidate_evidence,html=jointCandidateEvidence(d,h);for(const row of d.resource_options)assert(html.includes(row.id));for(const row of d.people_candidates)assert(html.includes(row.credential_id));assert(html.includes('本次选中'));assert(html.includes('首次或跨族换型'));assert(!html.includes('undefined'));
});
await check('blocked tasks retain unselected candidates without fabricated selected capacity',()=>{
 const d=fixtures.no_window.candidate_evidence,html=jointCandidateEvidence(d,h);assert(d.resource_options.length&&d.people_candidates.length);assert(!d.resource_options.some(r=>r.selected));assert(html.includes('不代表当前剩余容量'));assert(html.includes('未选中'));assert(!html.includes('推荐设备'));
});
await check('batch limit is a separate gate from window availability',()=>{
 const d=structuredClone(fixtures.scheduled.candidate_evidence);d.resource_options[0].batch_fits=false;d.resource_options[0].max_batch_qty=1;const html=jointCandidateEvidence(d,h);assert(html.includes('超出批量上限'));assert(html.includes('批量符合只核对设备上限'));assert(html.includes('并行容量'));
});
await check('ineligible qualification retains registration dates and unknown effective time',()=>{
 const d=structuredClone(fixtures.no_window.candidate_evidence);Object.assign(d.people_candidates[0],{eligible:false,effective_from:null,effective_until:null,reason:'模拟资格失效'});const html=jointCandidateEvidence(d,h);assert(html.includes('资格交集不可用'));assert(html.includes('模拟资格失效'));assert(html.includes('未形成时间'));assert(html.includes('到期日包含'));assert(html.includes('右侧不包含'));
});
await check('raw windows and blocked intervals keep all identities and boundaries',()=>{
 const d=fixtures.no_window.candidate_evidence,html=jointCandidateEvidence(d,h);for(const kind of ['schedule_windows','schedule_blocks','crew_windows','crew_blocks'])for(const row of d[kind]){assert(html.includes(row.id));assert(html.includes(row.started.replace('T',' ')));assert(html.includes(row.finished.replace('T',' ')));}assert(html.includes('尚未扣除不可用段'));assert(html.includes('裁剪到试排范围'));
});
await check('missing candidate windows do not become zero wait or healthy capacity',()=>{
 const d=structuredClone(fixtures.no_window.candidate_evidence);d.crew_windows=[];d.resource_options=[];const html=jointCandidateEvidence(d,h);assert(html.includes('本任务没有登记候选设备'));assert(html.includes('未登记该类输入，不表示已经具备可用容量'));assert(!html.includes('undefined'));
});
await check('dependency links use complete IDs and self root remains plain text',()=>{
 const d=fixtures.downstream.candidate_evidence,html=jointCandidateEvidence(d,h);for(const row of [...d.predecessors,...d.root_tasks])assert(html.includes('data-joint-related-task="'+row.id+'"'));const self=fixtures.shortage.candidate_evidence,text=jointCandidateEvidence(self,h);assert(text.includes('（当前任务）'));assert(!text.includes('data-joint-related-task="'+self.task_id+'"'));assert(html.includes('不等于已经确认的现场根因'));
});
await check('imported identity basis and reason are escaped',()=>{
 const d=structuredClone(fixtures.downstream.candidate_evidence);d.resource_options[0].basis='<script>';d.people_candidates[0].reason='<img>';d.predecessors[0].id='X" onclick="bad';d.crew_windows[0].basis='<svg>';const html=jointCandidateEvidence(d,h);for(const bad of ['<script>','<img>','<svg>','onclick="bad'])assert(!html.includes(bad));assert(html.includes('&lt;script&gt;'));assert(html.includes('&quot;'));
});
await check('projection rendering does not mutate the result',()=>{
 const d=structuredClone(fixtures.downstream),before=JSON.stringify(d);const html=scheduleTaskDetail(d,h,'joint');assert.equal(JSON.stringify(d),before);assert(html.includes('候选人机与窗口依据'));assert(html.indexOf('沿任务依赖核查')<html.indexOf('任务直接 Excel 来源'));assert(!html.includes('<pre'));
});
await check('candidate inspection does not grant original-file permission',()=>{
 const d={...fixtures.scheduled,can_download_original:false};assert(scheduleTaskDetail(d,h,'joint').includes('来源索引不授予原件下载权限'));
});
const pending=()=>{let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b});return{promise,resolve,reject}};
function harness(respond){
 const nodes=new Map(),events=new Map(),groups=new Map(),requests=[],modals=[],toasts=[],close=[];let revision=0,active=true;
 const node=id=>{if(!nodes.has(id))nodes.set(id,{innerHTML:'',textContent:'',value:'',disabled:false});return nodes.get(id)};
 const controls={...h,api:(path,opts)=>{requests.push({path,opts});return respond(path,opts)},header:(t,s,a='')=>t+s+a,modal:(...args)=>{revision++;modals.push(args)},toast:v=>toasts.push(v),go:()=>{},$:node,$$:s=>groups.get(s)||[],on:(s,e,f)=>{if(s==='#detail')close.push(f);else events.set(s+':'+e,f)},isCurrent:()=>active,getModalRevision:()=>revision};
 return {h:controls,requests,modals,toasts,leave:()=>{active=false},close:()=>close.forEach(f=>f()),fire:(id,event='click')=>{assert(events.has(id+':'+event),id);return events.get(id+':'+event)()},button(selector,field,id){groups.set(selector,[{dataset:{[field]:id},addEventListener:(e,f)=>events.set(selector+':'+id+':'+e,f)}])}};
}
const task=fixtures.downstream.row.id,root=fixtures.downstream.candidate_evidence.root_tasks[0].id;
const normal=path=>Promise.resolve(structuredClone(path==='joint-schedule'?{rows:[board.study],policies:{due:'交期优先'}}:path.includes('/tasks/'+encodeURIComponent(task))?fixtures.downstream:path.includes('/tasks/'+encodeURIComponent(root))?fixtures.shortage:board));
function setup(respond=normal){const x=harness(respond);x.button('[data-joint-task]','jointTask',task);x.button('[data-joint-related-task]','jointRelatedTask',root);return x}
await check('related task follows exact ID with the same study policy and receipt',async()=>{
 const x=setup();await createJointScheduleWorkspace(x.h).render(new URLSearchParams({study:board.study.id}),1);await x.fire('[data-joint-task]:'+task);await x.fire('[data-joint-related-task]:'+root);assert.equal(x.modals.length,2);const url=x.requests.at(-1).path;assert(url.startsWith('joint-schedule/'+board.study.id+'/tasks/'+encodeURIComponent(root)+'?'));assert(url.includes('receipt=SIM-CANDIDATES'));assert(url.includes('policy=due'));assert(x.modals[1][1].includes(root));
});
await check('closing a modal while following a dependency suppresses the old result',async()=>{
 const wait=pending(),x=setup(path=>path.includes('/tasks/'+encodeURIComponent(root))?wait.promise:normal(path));await createJointScheduleWorkspace(x.h).render(new URLSearchParams(),1);await x.fire('[data-joint-task]:'+task);const request=x.fire('[data-joint-related-task]:'+root);x.close();wait.resolve(fixtures.shortage);await request;assert.equal(x.modals.length,1);
});
await check('full sources supersede a pending related-task failure',async()=>{
 const wait=pending(),x=setup(path=>path.includes('/tasks/'+encodeURIComponent(root))?wait.promise:path.includes('/sources?')?Promise.resolve({rows:[],total:2030,page:1,size:40}):normal(path));await createJointScheduleWorkspace(x.h).render(new URLSearchParams(),1);await x.fire('[data-joint-task]:'+task);const request=x.fire('[data-joint-related-task]:'+root);await x.fire('#joint-sources');wait.reject(Error('OLD'));await request;assert.equal(x.modals.length,2);assert(x.modals.at(-1)[0].includes('全部来源'));assert.deepEqual(x.toasts,[]);
});
console.log(JSON.stringify({success:true,checks:names.length,names,browser_acceptance:false,mobile_acceptance:false,actual_download_acceptance:false}));
