import fs from 'node:fs';
import assert from 'node:assert/strict';
const source=fs.readFileSync(new URL('../static/analysis_scatter.js',import.meta.url),'utf8');
const {scatterSvg}=await import('data:text/javascript;base64,'+Buffer.from(source).toString('base64'));
const esc=v=>String(v).replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('"','&quot;');
const axes={x:{key:'m0',label:'产量',unit:'台'},y:{key:'d0',label:'单位成本',unit:'元/台'}};
const point=(i,x,y)=>({key:'g'+i,dimension:i===0?'<unsafe>':'G'+i,x,y,row_count:3,plotted:x!==null&&y!==null});
const series=(side,points)=>({side,label:side,result:{scatter:{points}}});
function render(items){const s=scatterSvg(items,axes,esc,String);assert(!/NaN|Infinity|undefined/.test(s));for(const m of s.matchAll(/(?:x1|x2|y1|y2|cx|cy)="([^"]+)"/g))assert(Number.isFinite(Number(m[1])),m[0]);return s;}
let s=render([series('primary',[point(0,0,-5),point(1,0,-5),point(2,null,9)]),series('reference',[point(3,10,20)])]);
assert.equal((s.match(/<circle /g)||[]).length,3);assert(s.includes('&lt;unsafe>'));assert(!s.includes('<unsafe>'));assert.equal((s.match(/cx="[^"]+" cy="[^"]+"/g)||[])[0],(s.match(/cx="[^"]+" cy="[^"]+"/g)||[])[1]);assert(s.includes('scatter-point reference'));assert(s.includes('tabindex="0"'));assert(s.includes('来源 3行'));
const coords=[...s.matchAll(/cx="([^"]+)" cy="([^"]+)"/g)].map(m=>[+m[1],+m[2]]);assert(coords[0][0]<coords[2][0]);assert(coords[0][1]>coords[2][1]);
for(const v of [0,Number.MIN_VALUE,Number.MAX_VALUE,-Number.MAX_VALUE])render([series('primary',[point(0,v,v)])]);
render([series('primary',[point(0,-Number.MAX_VALUE,Number.MAX_VALUE),point(1,Number.MAX_VALUE,-Number.MAX_VALUE)])]);
assert(render([series('primary',[])]).includes('没有完整'));assert(render([series('primary',[point(0,null,1)])]).includes('保留'));
console.log('Scatter rendering checks passed: zero/negative/extreme axes, overlapping identities, omitted nulls, shared two-range coordinates and safe accessible labels.');
