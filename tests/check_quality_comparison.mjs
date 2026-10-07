import fs from 'node:fs';
import assert from 'node:assert/strict';
const source=fs.readFileSync(new URL('../static/quality_comparison.js',import.meta.url),'utf8');
const {boxPlot}=await import('data:text/javascript;base64,'+Buffer.from(source).toString('base64'));
const esc=v=>String(v).replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('"','&quot;');
const num=String;
const group={label:'D1',n:5,unique_units:4,min:0,max:100,q1:1,median:2,q3:3,lower_whisker:0,upper_whisker:3,outliers:1,outside:0,small_sample:false,outlier_points:[{value:100,count:1}],omitted_outlier_values:0};
const data={binary:false,compare_label:'设备',spec:{unit:'Ω',lsl:0,usl:10},groups:[group]};
function render(d=data,groups=d.groups){const s=boxPlot(d,groups,esc,num);assert(!/NaN|Infinity|undefined/.test(s));for(const m of s.matchAll(/(?:x1|x2|cx|width)="([^"]+)"/g))assert(Number.isFinite(Number(m[1])));return s;}
const svg=render();assert(svg.includes('LSL 0'));assert(svg.includes('USL 10'));assert(svg.includes('n=5 · SN=4'));assert.equal((svg.match(/<circle /g)||[]).length,1);assert(svg.includes('规范超限=0'));
const other={...group,label:'<script>',min:-100,max:-100,q1:-100,q3:-100,median:-100,lower_whisker:-100,upper_whisker:-100,outliers:0,outlier_points:[]};
const all={...data,groups:[group,other]};const a=render(all,[group]),b=render(all,[other]);
const axes=s=>[...s.matchAll(/text-anchor="middle">([^<]*)/g)].map(x=>x[1]);assert.deepEqual(axes(a),axes(b));assert(b.includes('&lt;script>'));assert(!b.includes('<script>'));
for(const value of [0,Number.MIN_VALUE,1e100,Number.MAX_VALUE,-Number.MAX_VALUE]){
 const g={...other,label:'single',n:1,unique_units:1,small_sample:true,min:value,max:value,q1:value,q3:value,median:value,lower_whisker:value,upper_whisker:value};
 assert(render({...data,spec:{unit:'V',lsl:null,usl:null},groups:[g]}).includes('小样本'));
}
assert(render({...data,groups:[]}).includes('未补零'));assert(render({...data,binary:true}).includes('不绘制'));
assert(render({...data,groups:[{...group,omitted_outlier_values:12}]}).includes('不截断'));
console.log('Quality boxplot checks passed: shared axes, zero limits, one/zero/binary samples, extremes, safe labels and visible source counts.');
