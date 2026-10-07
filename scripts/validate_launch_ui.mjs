// Pure functions only. This is not browser or DOM acceptance.
import fs from 'node:fs';
import assert from 'node:assert/strict';
import {launchSummary,selectTasks,canLaunch,exportPath} from '../static/launch.js';
const root=new URL('../',import.meta.url),read=n=>JSON.parse(fs.readFileSync(new URL(`data/launch_board_${String(n).padStart(3,'0')}_due.json`,root),'utf8'));
const esc=v=>String(v??'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;');
const h={esc,panel:(title,body)=>`<section><h2>${esc(title)}</h2>${body}</section>`,table:(titles,rows)=>`<table><thead>${titles.map(v=>`<th>${esc(v)}</th>`).join('')}</thead>${rows.map(row=>`<tr>${row.map(v=>`<td>${v}</td>`).join('')}</tr>`).join('')}</table>`};
const base=read(1),before=structuredClone(base),html=launchSummary(base,h);
assert.match(html,/10 \/ 198/);assert.match(html,/182<\/b>/);assert.match(html,/85<\/b> 台/);
assert.match(html,/登记条件满足不等于获准开工/);
assert.equal(selectTasks(base.tasks,'','satisfied').length,10);
assert.equal(selectTasks(base.tasks,base.jobs[0].job_id).length,26);
assert.deepEqual(base,before);
assert.match(launchSummary(read(9),h),/198<\/b>/);
for(const n of [6,10]){const v=launchSummary(read(n),h);assert.match(v,/暂停核对/);assert.doesNotMatch(v,/finite-summary/)}
const hostile=read(6);hostile.issues=['<img src=x onerror=alert(1)>'];assert.doesNotMatch(launchSummary(hostile,h),/<img/);
for(const role of ['admin','analyst','operations'])assert.ok(canLaunch(role));
for(const role of ['quality','finance','viewer',null])assert.equal(canLaunch(role),false);
assert.equal(new URL(exportPath('A/B','due','x&y','json'),'http://example.invalid').searchParams.get('receipt'),'x&y');
for(const args of [['A','bad','x','csv'],['A','due','','json'],['A','due','x','xlsx']])assert.throws(()=>exportPath(...args));
const proof={success:true,pure_js_rendering:true,whole_scope_summary:true,filtered_rows:true,uncomputed_states:true,escaping:true,roles:true,export_parameters:true,browser_acceptance:false,mobile_acceptance:false,actual_download_acceptance:false};
fs.writeFileSync(new URL('data/launch_ui.json',root),JSON.stringify(proof,null,2)+'\n');console.log(JSON.stringify(proof));
