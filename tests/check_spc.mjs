import assert from 'node:assert/strict';
import {spcChart} from '../static/spc.js';
const d={study:{id:'S1',unit:'Ω',method:'I_MR',order_basis:'设备计数（模拟）'},spec:{lsl:-2,usl:2,unit:'Ω'},baseline_policy:{baseline_end:2},coverage:{planned:5},limits:{center:0,i_lcl:-1,i_ucl:1,mr_lcl:0,mr_mean:.5,mr_ucl:1.6},chart_points:[
 {id:'P1',sequence:1,value:0,mr:null,eligible:true},{id:'P2',sequence:2,value:.5,mr:.5,eligible:true},
 {id:'P4',sequence:4,value:1.3,mr:null,eligible:true,i_signal:true},{id:'P5',sequence:5,value:999,mr:null,eligible:false}]};
const before=JSON.stringify(d),i=spcChart(d),mr=spcChart(d,'mr',false);
assert.equal(JSON.stringify(d),before);assert.match(i,/产品LSL/);assert.match(i,/I UCL/);assert.match(i,/role="button" tabindex="0"/);
const path=i.match(/<path d="([^"]*)"/)[1];assert.equal((path.match(/M/g)||[]).length,2);assert.equal((path.match(/L/g)||[]).length,1);
assert.equal((mr.match(/<path d="([^"]*)"/)[1].match(/M/g)||[]).length,1);assert.ok(!mr.includes('产品LSL'));
assert.ok(!spcChart(d,'i',false).includes('产品LSL'));assert.match(i,/spc-held/);assert.match(i,/spc-signal/);
const unsafe=structuredClone(d);unsafe.chart_points[0].id='"><script>SIM</script>';assert.ok(!spcChart(unsafe).includes('<script>SIM'));
const binary=structuredClone(d);binary.spec.unit='bool';binary.category_counts={'0':3,'1':2};assert.match(spcChart(binary),/0 值 3 条/);assert.ok(!spcChart(binary).includes('<svg'));
const unknown=structuredClone(d);unknown.study.order_basis='未知';assert.ok(!spcChart(unknown).includes('<svg'));
const empty=structuredClone(d);empty.chart_points=[];empty.limits=null;empty.spec.lsl=empty.spec.usl=null;assert.ok(!spcChart(empty).includes('<svg'));
console.log(JSON.stringify({success:true,pure_svg_checks:15,browser_acceptance:false,fixed_baseline:true,no_gap_bridge:true,binary_no_continuous_chart:true}));
