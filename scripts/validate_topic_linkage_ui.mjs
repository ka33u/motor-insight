// Pure markup/data checks; this is deliberately not a browser or mobile test.
import fs from 'node:fs';import assert from 'node:assert/strict';
import {markRows,linkPicker,linkMarkup} from '../static/topic_linkage.js';
const root=new URL('../',import.meta.url),app=fs.readFileSync(new URL('static/app.js',root),'utf8');
const start=app.indexOf('function chart('),end=app.indexOf('\nconst nav=',start);assert(start>=0&&end>start);
const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const chart=Function('esc','num',app.slice(start,end)+';return chart')(esc,v=>String(v));
const choices=[{group:'<工单"0001>',label:'生产工单',kind:'work_order'},{group:'WO2',label:'生产工单',kind:'work_order'}],raw=[{dimension:'<工单"0001>',m0:10},{dimension:'WO2',m0:20},{dimension:'无声明',m0:30}];
const marked=markRows(raw,choices);assert.equal(marked[0]._topic_link_i,0);assert.equal(marked[1]._topic_link_i,1);assert.equal(marked[2]._topic_link_i,undefined);assert.equal(raw[0]._topic_link_i,undefined);
for(const kind of ['bar','line','donut']){
 const html=chart(marked,'dimension','m0',kind,null,true);assert.equal((html.match(/data-topic-link-index=/g)||[]).length,2);assert(html.includes('tabindex="0"'));assert(html.includes('&lt;工单&quot;0001&gt;'));assert(!html.includes('联动筛选 <工单'));
 assert(!chart(raw,'dimension','m0',kind).includes('data-topic-link-index'));
}
const many=Array.from({length:10},(_,i)=>({dimension:'WO'+i,m0:i+1})),all=markRows(many,many.map(r=>({group:r.dimension})));
assert.equal((chart(all,'dimension','m0','donut',null,true).match(/data-topic-link-index=/g)||[]).length,8); // “Other” never pretends to be an actual group.
assert.equal((chart(marked.map(r=>({...r,reference:r.m0})),'dimension','m0','bar','reference',true).match(/data-topic-link-index=/g)||[]).length,4);
const picker=linkPicker({model:{name:'<车间>'},link_choices:choices},esc);assert(picker.includes('&lt;车间&gt;'));assert(picker.includes('value="0"'));assert.equal(linkPicker({link_choices:[]},esc),'');
assert.equal((chart(marked.map(r=>({...r,reference:r.m0})),'dimension','m0','bar','reference',true).match(/data-topic-link-side="reference"/g)||[]).length,2);
const ctx={cards:[{available:true,model:{name:'车间电量'},link_contract:{work_order:{label:'生产工单',field:'work_order_id'}}},{available:false}],linkage:{notice:'直接身份'}};
const html=linkMarkup(ctx,{links:{selections:[{kind:'work_order',value:'<"0001>'}]}},esc);assert(html.includes('移除生产工单 &lt;&quot;0001&gt;'));assert(html.includes('work_order_id'));assert(html.includes('未读取字段关系'));
console.log(JSON.stringify({pure_markup_and_data_checks:true,bar_line_donut_exact_indices:true,other_group_not_linkable:true,escaped_labels:true,legacy_noninteractive_charts_unchanged:true,browser_rendered_verified:false}));
