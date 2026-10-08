import assert from 'node:assert/strict';
import {returnEvidence,issueBalance} from '../static/material_returns.js';
let groups=0;const check=(name,fn)=>{fn();groups++;console.log('PASS '+name)};
const esc=v=>String(v??'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;').replaceAll("'",'&#39;');
const h={esc,table:(headers,rows)=>`<table><thead>${headers.join('|')}</thead><tbody>${rows.map(r=>r.join('|')).join('\n')}</tbody></table>`,amount:(v,u='')=>(v==null?'—':esc(v))+(u?' '+esc(u):'')};
const row={id:'TL-0001',issue_id:'CK-0001',work_order_id:'MO-0001',issue:{work_order_id:'MO-0001'},material_id:'01.01.9001',lot:'RT01',location:'QC01',occurred:'2026-09-30T09:00:00',qty_signed:1.5,unit:'kg',verified:true,issues:[]};
const report=rows=>({return_reconciliation:{notice:'净领料不是实际消耗',rows}});
check('original movement, work, location, exact quantity and boundary remain together',()=>{
 const html=returnEvidence(report([row]),h);for(const value of ['TL-0001','CK-0001','MO-0001','01.01.9001','QC01','1.5 kg','净领料不是实际消耗'])assert.ok(html.includes(value));assert.ok(html.includes('<details open>'));
});
check('invalid links retain declared identities and reasons',()=>{
 const html=returnEvidence(report([{...row,work_order_id:'MO-OTHER',verified:false,issues:['工单不一致','累计退料超过领料']}]),h);
 for(const value of ['MO-0001 / MO-OTHER','工单不一致','累计退料超过领料'])assert.ok(html.includes(value));assert.ok(!html.includes('关联与累计量可核对'));
});
check('absent original is distinct from a resolved original',()=>{
 const html=returnEvidence(report([{...row,issue:null,issue_id:null,unit:null,verified:false,issues:['未指向原领料']}]),h);assert.ok(html.includes('未关联'));assert.ok(html.includes('未核对 / MO-0001'));assert.ok(html.includes('单位待核对'));
});
check('empty and unavailable reports do not imply zero consumption',()=>{
 assert.equal(returnEvidence({},h),'');const html=returnEvidence(report([]),h);assert.ok(html.includes('没有关联'));assert.ok(!html.includes('<details open>'));assert.ok(!html.includes('0 kg'));
});
check('source labels are escaped',()=>{
 const html=returnEvidence(report([{...row,id:'<script>',issue_id:'<img>',lot:'<svg>',verified:false,issues:['<iframe>']}]),h);
 for(const value of ['<script>','<img>','<svg>','<iframe>'])assert.ok(!html.includes(value));assert.ok(html.includes('&lt;script&gt;'));
});
check('zero net is retained after a complete return',()=>{
 const html=issueBalance({unit:'kg',gross_issued_qty:20,returned_qty:20,issued_qty:0,remaining_required:57.132,issue_balance_known:true,issue_rows:[{id:'CK1',occurred:'2026-09-28',lot:'L1',location:'A',qty:20}]},h);
 assert.ok(html.includes('20 kg|20 kg|0 kg|57.132 kg'));assert.ok(html.includes('CK1'));assert.ok(!html.includes('留空'));
});
check('unknown net and cumulative amounts stay unavailable',()=>{
 const html=issueBalance({unit:'件',gross_issued_qty:null,returned_qty:null,issued_qty:null,remaining_required:null,issue_balance_known:false,issue_rows:[]},h);
 assert.ok(html.includes('— 件|— 件|— 件|— 件'));assert.ok(html.includes('不以部分记录代替完整结果'));assert.ok(!html.includes('0 件'));
});
console.log(JSON.stringify({success:true,groups,browser_acceptance:false}));
