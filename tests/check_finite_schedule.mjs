import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import {gantt,exportPath} from '../static/finite_schedule.js';
const d=JSON.parse(await fs.readFile(new URL('./fixtures/finite_schedule_board_001_due.json',import.meta.url),'utf8')),p=JSON.parse(await fs.readFile(new URL('./fixtures/finite_schedule_board_005_due.json',import.meta.url),'utf8'));
const image=gantt(d);assert.match(image,/有限资源试排甘特图/);assert.match(image,/换型占用/);assert.match(image,/假设不可用/);assert.equal((image.match(/data-finite-task=/g)||[]).length,198);assert.match(image,/tabindex="0"/);assert.match(image,/role="button"/);assert.match(image,/10-02/);assert.doesNotMatch(image,/NaN|Infinity/);assert.doesNotMatch(gantt(p),/<svg/);assert.match(gantt(p),/暂停/);
const x=structuredClone(d);x.tasks[0].id='<script>"&';assert.doesNotMatch(gantt(x),/<script>/);assert.match(gantt(x),/&lt;script&gt;/);
const path=exportPath('SP/1','priority','fixed receipt','json');assert.match(path,/SP%2F1/);assert.match(path,/policy=priority/);assert.match(path,/receipt=fixed\+receipt/);assert.throws(()=>exportPath('SP1','other','r','csv'));assert.throws(()=>exportPath('SP1','due','r','xlsx'));assert.throws(()=>exportPath('SP1','due','','json'));
console.log(JSON.stringify({success:true,checks:19,kind:'pure-presentation',actual_browser:false,actual_download:false}));
