import assert from 'node:assert/strict';import fs from 'node:fs';
import {resultExportRequest,downloadCurrentResult} from '../static/model_card_exports.js';
let checks=0;const check=async fn=>{await fn();checks++};
const value={card:{id:'39963b5a-7ddf-4093-b5f7-a0052f3ad70f'},reading:{receipt:'synthetic+only/a:b?c'}};
await check(()=>{const r=resultExportRequest(value,'csv');assert.equal(new URL('http://localhost'+r.url).searchParams.get('receipt'),value.reading.receipt);assert(r.filename.endsWith('.csv'));assert.equal(r.mime,'text/csv')});
await check(()=>assert.equal(resultExportRequest(value,'json').mime,'application/json'));
await check(()=>assert.throws(()=>resultExportRequest(value,'xml')));
await check(()=>assert.throws(()=>resultExportRequest({...value,card:{id:'<script>'}},'csv')));
await check(()=>assert.throws(()=>resultExportRequest({...value,reading:{}},'csv')));
function io(options={}){const state={fetched:0,clicked:0,removed:0,revoked:0,timers:[]};const item={click:()=>state.clicked++,remove:()=>state.removed++};return {state,fetch:async(url,init)=>{state.fetched++;assert.equal(init.credentials,'same-origin');assert.equal(init.cache,'no-store');return {ok:options.ok!==false,headers:{get:key=>key==='Content-Type'?(options.mime||'text/csv; charset=utf-8'):(options.attachment===false?'inline':'attachment; filename="result.csv"')},json:async()=>({error:'资料已变化，请重新运行'}),blob:async()=>{options.onBlob?.();return {size:42}}}},document:{createElement:()=>item,body:{appendChild:()=>{}}},URL:{createObjectURL:()=> 'blob:synthetic',revokeObjectURL:()=>state.revoked++},setTimeout:(fn,ms)=>{assert.equal(ms,1000);state.timers.push(fn)}};}
await check(async()=>{const net=io();assert(await downloadCurrentResult(value,'csv',()=>true,net));assert.equal(net.state.clicked,1);assert.equal(net.state.removed,1);assert.equal(net.state.revoked,0);net.state.timers[0]();assert.equal(net.state.revoked,1)});
await check(async()=>{const net=io();assert.equal(await downloadCurrentResult(value,'csv',()=>false,net),false);assert.equal(net.state.fetched,0)});
await check(async()=>{let active=true;const net=io({onBlob:()=>{active=false}});assert.equal(await downloadCurrentResult(value,'csv',()=>active,net),false);assert.equal(net.state.clicked,0)});
await check(async()=>{const net=io({ok:false});await assert.rejects(downloadCurrentResult(value,'csv',()=>true,net),/资料已变化/);assert.equal(net.state.clicked,0)});
await check(async()=>{const net=io({mime:'text/html'});await assert.rejects(downloadCurrentResult(value,'csv',()=>true,net),/不是结果文件/);assert.equal(net.state.clicked,0)});
await check(async()=>{const net=io({attachment:false});await assert.rejects(downloadCurrentResult(value,'csv',()=>true,net),/不是结果文件/);assert.equal(net.state.clicked,0)});
const report={success:true,pure_checks:checks,browser_acceptance:false,mobile_acceptance:false,actual_download_acceptance:false};fs.writeFileSync(new URL('../data/model_exports_presentation_checks.json',import.meta.url),JSON.stringify(report,null,2)+'\n');console.log(JSON.stringify(report));
