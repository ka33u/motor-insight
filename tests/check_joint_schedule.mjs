import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import {jointOverview,exportPath,canJoint} from '../static/joint_schedule.js';
import {crewGantt} from '../static/crew_schedule.js';
const d=JSON.parse(await fs.readFile(new URL('./fixtures/joint_schedule_board_001_due.json',import.meta.url),'utf8'));
const p=JSON.parse(await fs.readFile(new URL('./fixtures/joint_schedule_board_007_due.json',import.meta.url),'utf8'));
const esc=v=>String(v??'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;').replaceAll("'",'&#39;');
const table=(headers,rows)=>'<table><thead>'+headers.map(h=>`<th>${esc(h)}</th>`).join('')+'</thead><tbody>'+rows.map(r=>'<tr>'+r.map(v=>`<td>${v}</td>`).join('')+'</tr>').join('')+'</tbody></table>';
const panel=(title,body)=>`<section><h2>${esc(title)}</h2>${body}</section>`;
const helpers={esc,table,panel};
const html=jointOverview(d,helpers);
assert.match(html,/已排任务/);assert.match(html,/198 \/ 198/);assert.match(html,/54 \/ 54/);assert.match(html,/6 \/ 50/);
assert.match(html,/差值分钟/);assert.match(html,/不能相加/);assert.doesNotMatch(html,/NaN|Infinity|undefined/);
const paused=jointOverview(p,helpers);assert.match(paused,/资料约束未通过/);assert.match(paused,/未完整绑定/);assert.doesNotMatch(paused,/class="finite-summary"/);
for(const mode of ['resource','worker']){
 const chart=crewGantt(d,mode);assert.equal((chart.match(/data-finite-task=/g)||[]).length,198);assert.match(chart,/role="button"/);assert.match(chart,/tabindex="0"/);assert.doesNotMatch(chart,/NaN|Infinity/);
}
assert.doesNotMatch(crewGantt(p),/<svg/);
const hostile=structuredClone(d);hostile.jobs[0].id='<script>"&';assert.doesNotMatch(jointOverview(hostile,helpers),/<script>/);assert.match(jointOverview(hostile,helpers),/&lt;script&gt;/);
for(const role of ['admin','analyst','operations'])assert.equal(canJoint(role),true);
for(const role of ['quality','finance','viewer'])assert.equal(canJoint(role),false);
const path=exportPath('MP/1','priority','fixed receipt','json');assert.match(path,/MP%2F1/);assert.match(path,/policy=priority/);assert.match(path,/receipt=fixed\+receipt/);
for(const args of [['MP1','other','r','csv'],['MP1','due','r','xlsx'],['MP1','due','','json']])assert.throws(()=>exportPath(...args));
console.log(JSON.stringify({success:true,kind:'pure-presentation',browser_acceptance:false,mobile_acceptance:false,actual_download:false}));
