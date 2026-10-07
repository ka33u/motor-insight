// Pure rendering contracts only: no browser, DOM, screenshots or download automation.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {baselineOverview, canOrderBaseline, exportPath} from '../static/order_baseline.js';
const root=new URL('../',import.meta.url);
const read=n=>JSON.parse(fs.readFileSync(new URL(`data/order_baseline_board_${String(n).padStart(3,'0')}_due.json`,root),'utf8'));
const esc=v=>String(v??'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;').replaceAll("'",'&#39;');
const h={esc,panel:(title,body)=>`<section><h2>${esc(title)}</h2>${body}</section>`,table:(titles,rows)=>`<table><thead>${titles.map(t=>`<th>${esc(t)}</th>`).join('')}</thead><tbody>${rows.map(r=>`<tr>${r.map(v=>`<td>${v}</td>`).join('')}</tr>`).join('')}</tbody></table>`};
const base=read(1),html=baselineOverview(base,h);
assert.match(html,/135<\/b> 台 \/ 6 行/);
assert.match(html,/50<\/b> 台/);
assert.match(html,/85<\/b> 台/);
assert.match(html,/6 \/ 6/);
for(const row of base.orders)assert.ok(html.includes(esc(row.id)));
assert.match(html,/可能尚未全量覆盖或存在未排批次/);
assert.match(html,/不能作为OTIF/);
assert.match(baselineOverview(read(4),h),/无完成时点/);
for(const n of [5,6,7,10]){
 const value=baselineOverview(read(n),h);
 assert.match(value,/覆盖、用料与交期不计算/);
 assert.doesNotMatch(value,/class="finite-summary"/);
}
for(const n of [8,9])assert.match(baselineOverview(read(n),h),/基线待重核，不确认整单参考完工/);
const injected=structuredClone(base);
injected.issues=['<img src=x onerror=alert(1)>'];
injected.orders[0].id='<script>bad()</script>';
const safe=baselineOverview(injected,h);
assert.doesNotMatch(safe,/<script>|<img/);
assert.match(safe,/&lt;script&gt;/);
assert.equal(canOrderBaseline('quality'),false);
for(const role of ['admin','analyst','operations'])assert.equal(canOrderBaseline(role),true);
for(const role of ['finance','viewer',undefined])assert.equal(canOrderBaseline(role),false);
const path=exportPath('OB/1','due','x&y','json');
assert.match(path,/OB%2F1\/export/);
assert.equal(new URL(path,'http://example.invalid').searchParams.get('receipt'),'x&y');
for(const args of [['OB','due','','csv'],['OB','bad','x','json'],['OB','due','x','xls']])assert.throws(()=>exportPath(...args));
const proof={success:true,pure_js_rendering:true,cases:10,coverage_totals:true,uncomputed_states:true,escaping:true,export_parameters:true,role_gate:true,browser_acceptance:false,mobile_acceptance:false,actual_download_acceptance:false};
fs.writeFileSync(new URL('data/order_baseline_ui.json',root),JSON.stringify(proof,null,2)+'\n');
console.log(JSON.stringify(proof));
