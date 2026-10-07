// Pure rendering contracts, not DOM, browser or download acceptance.
import fs from 'node:fs';
import assert from 'node:assert/strict';
import {firstPieceSummary,firstPieceTargets,firstPieceExportPath} from '../static/first_piece.js';
const root=new URL('../',import.meta.url),d=JSON.parse(fs.readFileSync(new URL('data/first_piece_example.json',root),'utf8'));
const esc=v=>String(v??'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;');
const h={esc,panel:(t,b)=>`<section><h2>${esc(t)}</h2>${b}</section>`,table:(headers,rows)=>`<table>${headers.map(esc).join('')}${rows.map(r=>`<tr>${r.map(c=>`<td>${c}</td>`).join('')}</tr>`).join('')}</table>`};
const before=structuredClone(d),summary=firstPieceSummary({summary:d.result.summary,all_summary:d.result.summary,filters:{q:'',state:'',process:'',study:''}},h);
assert.match(summary,/>219<\/b>/);assert.match(summary,/288 \/ 全部 288/);assert.match(summary,/证据齐备不是首件批准/);
assert.match(summary,/529 项最新实测/);
const targets=firstPieceTargets(d.targets,h);assert.match(targets,/全部 66 条质量条件/);assert.equal((targets.match(/未找到候选/g)||[]).length,66);assert.match(targets,/不受历史计划筛选影响/);
assert.deepEqual(d,before);
const hostile=structuredClone(d.targets);hostile.rows[0].process='<img src=x onerror=1>';hostile.rows[0].plan_ids=['A/B?x=<svg>'];assert.doesNotMatch(firstPieceTargets(hostile,h),/<img|<svg/);
const url=new URL(firstPieceExportPath({q:'A&B',study:'L/1'},'x+y','json'),'http://example.invalid');assert.equal(url.searchParams.get('receipt'),'x+y');assert.equal(url.searchParams.get('q'),'A&B');
assert.throws(()=>firstPieceExportPath({},'','json'));assert.throws(()=>firstPieceExportPath({},'x','xlsx'));
const proof={success:true,pure_render_contracts:true,counts:true,target_scope:true,escaping:true,export_scope:true,browser_acceptance:false,mobile_acceptance:false,actual_download_acceptance:false};
fs.writeFileSync(new URL('data/first_piece_ui.json',root),JSON.stringify(proof,null,2)+'\n');console.log(JSON.stringify(proof));
