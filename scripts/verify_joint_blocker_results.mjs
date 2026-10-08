// Cross-check native HTTP/export results against an independent Python oracle.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {jointBlockerReport,jointTaskSelection} from '../static/joint_blockers.js';
const cases=JSON.parse(fs.readFileSync(0,'utf8'));let memberships=0;
for(const {key,result,expected} of cases){
 const before=JSON.stringify(result),actual=jointBlockerReport(result);
 assert.deepEqual({state:actual.state,summary:actual.summary,rows:actual.rows},expected,key);
 for(const row of actual.rows){
  const selected=jointTaskSelection(result,actual,{root:row.id});
  assert.deepEqual(selected.map(t=>t.id).sort(),row.task_ids,key+': exact members');
  memberships+=selected.length;
 }
 assert.equal(JSON.stringify(result),before,key+': immutable');
}
console.log(JSON.stringify({success:true,cases:cases.length,memberships,independent_python_oracle:true}));
