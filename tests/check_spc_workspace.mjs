import assert from 'node:assert/strict';
import {comparisonPresentation,personalSPCTopicMarkup} from '../static/spc_workspace.js';
let checks=0;const check=(condition)=>{assert.ok(condition);checks++};
const source={state:'definitions_changed',pointwise_comparable:false,rows:[
 {id:'zero',kinds:['observation_changed'],before:{value:0,reasons:[]},current:{value:2,reasons:['核对'] }},
 {id:'gone',kinds:['missing_current'],before:{value:-2,reasons:[]},current:null},
 {id:'new',kinds:['added'],before:null,current:{value:0,reasons:[]}}]};
const before=JSON.stringify(source),p=comparisonPresentation(source);
check(p.label==='计算依据变化');check(!p.comparable);check(p.rows[0].previous===0);check(p.rows[1].previous===-2);
check(p.rows[1].current===null);check(p.rows[2].previous===null);check(p.rows[2].current===0);check(JSON.stringify(source)===before);
check(comparisonPresentation({state:'baseline_evidence_changed',rows:[]}).label==='基线资料更正');
check(comparisonPresentation({state:'source_missing',rows:[]}).rows.length===0);
const calls=[],escape=v=>String(v).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const h={api:async path=>{calls.push(path);return path.startsWith('spc-analysis-views')?{rows:[{id:'own',code:'SPC.R.01',name:'<SIM>',study_id:'S',revision:2}],total:1}:{rows:[{id:'frozen',available:true,name:'<CAPTURE>',created_at:'t',view_code:'SPC.R.01',view_revision:1},{id:'blocked',available:false,name:'PRIVATE',created_at:'t'}],total:2}},
 esc:escape,panel:(title,sub,body,action)=>title+sub+body+action,table:(headers,rows)=>rows.map(r=>r.join('|')).join('\n'),localTime:v=>v};
const html=await personalSPCTopicMarkup({id:4},h);
check(calls.length===2&&calls.every(c=>c.endsWith('topic_id=4')));check(html.includes('view=own'));check(html.includes('snapshot=frozen'));
check(!html.includes('<SIM>')&&html.includes('&lt;SIM&gt;'));check(!html.includes('PRIVATE'));check(html.includes('未应用专题的通用日期筛选'));
console.log(JSON.stringify({success:true,pure_presentation_checks:checks,browser_acceptance:false,no_missing_as_zero:true,personal_topic_listing:true}));
