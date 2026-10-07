// Pure generated markup and module wiring, not a rendered browser test.
import fs from 'node:fs';import assert from 'node:assert/strict';
import {curveMarkup,curingStates,createCuringWorkspace} from '../static/curing.js';
const root=new URL('../',import.meta.url),d=JSON.parse(fs.readFileSync(new URL('data/curing_example.json',root),'utf8'));
const esc=v=>String(v??'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;');
const find=name=>d.result.rows.find(r=>r.run.note.includes(' '+name+'；'));
let curves=0;
for(const r of d.result.rows)for(const c of r.channels){const html=curveMarkup(r.run,c,esc);assert.doesNotMatch(html,/NaN|Infinity/);assert.match(html,/℃/);curves++}
const normal=find('normal'),before=structuredClone(normal),html=curveMarkup(normal.run,normal.channels[0],esc);assert.deepEqual(normal,before);assert.equal([...html.matchAll(/data-cure-point=/g)].length,19);assert.equal([...html.matchAll(/class="cure-line"/g)].length,18);assert.match(html,/tabindex="0"/);
const wrong=find('wrong_unit');assert.equal([...curveMarkup(wrong.run,wrong.channels[0],esc).matchAll(/data-cure-point=/g)].length,18);
const gap=find('gap');assert.equal([...curveMarkup(gap.run,gap.channels[0],esc).matchAll(/class="cure-line"/g)].length,15);
const hot=find('overtemp');assert.match(curveMarkup(hot.run,hot.channels[0],esc),/class="cure-hot"/);
const hostile=structuredClone(normal);hostile.channels[0].channel_code='<img src=x>';hostile.channels[0].points[0].id='<script>x</script>';assert.doesNotMatch(curveMarkup(hostile.run,hostile.channels[0],esc),/<img|<script/);
assert.equal(curingStates.open,'采集未闭合');const app=fs.readFileSync(new URL('static/app.js',root),'utf8'),source=fs.readFileSync(new URL('static/curing.js',root),'utf8');assert.match(app,/'thermal-curing':curingWorkspace.render/);assert.match(source,/method:'POST'/);assert.match(source,/id===boardSeq/);assert.match(source,/getModalRevision\(\)===rev/);
// Plain object harness only: no browser, DOM or renderer.
const summary={runs:34,states:{ready:5,out:3},sample_rows:1229,load_rows:32,grain:'炉次计数'},rows=d.result.rows.slice(0,25).map(r=>({run:r.run,state:r.state,label:r.label,issues:r.issues,missing:r.missing,loads:r.loads,sample_rows:r.sample_rows}));
const board={...d.result,rows,summary,total:34,page:1,size:25,scope:{},receipt:'fixture',source_count:d.sources.length,options:{resources:[],products:[]}};
const nodes=new Map(),handlers=new Map(),buttons=[];let route=1,rev=0,requests=[];
const $=key=>{if(!nodes.has(key))nodes.set(key,{innerHTML:'',textContent:'',open:false,close(){this.open=false}});return nodes.get(key)};
const h={esc,$,$$:()=>buttons,header:(title,desc,actions)=>title+desc+actions,panel:(title,desc,body)=>title+desc+body,table:(headers,rows)=>JSON.stringify([headers,rows]),modal:(title,body)=>{rev++;$('#detail').open=true;$('#dialog-title').textContent=title;$('#dialog-content').innerHTML=body},toast:msg=>{throw Error(msg)},on:(selector,event,fn)=>handlers.set(selector+':'+event,fn),isCurrent:t=>t===route,getModalRevision:()=>rev,
 api:(url,options)=>{assert.equal(options.method,'POST');return new Promise(resolve=>requests.push({url,body:structuredClone(options.body),resolve}))}};
const workspace=createCuringWorkspace(h),pending=workspace.render(new URLSearchParams(),1);route=2;requests.shift().resolve(board);await pending;assert.equal($('#main').innerHTML,'');
route=3;const rendering=workspace.render(new URLSearchParams(),3);requests.shift().resolve(board);await rendering;assert.match($('#main').innerHTML,/固化温度曲线/);
const originalFormData=globalThis.FormData;globalThis.FormData=class{constructor(form){return Object.entries(form.fields)}};
const submit=handlers.get('#cure-filter:submit'),a=submit({preventDefault(){},currentTarget:{fields:{q:'FIRST'}}}),b=submit({preventDefault(){},currentTarget:{fields:{q:'LATEST'}}});
assert.equal(requests[0].body.scope.q,'FIRST');assert.equal(requests[1].body.scope.q,'LATEST');requests[1].resolve({...board,scope:{q:'LATEST'},total:5,summary:{...summary,runs:5}});await b;requests[0].resolve({...board,scope:{q:'FIRST'}});await a;assert.match($('#main').innerHTML,/value="LATEST"/);assert.doesNotMatch($('#main').innerHTML,/value="FIRST"/);requests=[];globalThis.FormData=originalFormData;
const loadSources=handlers.get('#cure-sources:click'),s=loadSources();requests.shift().resolve({rows:[],total:80,size:40,notice:'全局来源',can_download_original:false});await s;
const next=handlers.get('#cure-source-next:click'),oldTable=$('#cure-source-table').innerHTML,late=next();$('#detail').close();requests.shift().resolve({rows:[{dataset:'cure_samples',key:'LATE',missing:true}],size:40,total:80});await late;assert.equal($('#cure-source-table').innerHTML,oldTable);
const proof={success:true,curves,all_points_no_silent_truncation:true,invalid_units_not_plotted:true,gaps_broken:true,accessible_source_points:true,escaping:true,route_wiring:true,late_route_discarded:true,latest_filter_wins:true,closed_modal_discarded:true,browser_acceptance:false,mobile_acceptance:false,actual_download_acceptance:false};fs.writeFileSync(new URL('data/curing_ui.json',root),JSON.stringify(proof,null,2)+'\n');console.log(JSON.stringify(proof));
