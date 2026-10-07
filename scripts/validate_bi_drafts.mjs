import assert from 'node:assert/strict';
import {readFile,writeFile} from 'node:fs/promises';
import {buildBiDesignDraft} from '../static/catalog_planning.js';

const d=JSON.parse(await readFile(new URL('../data/bi_design.json',import.meta.url),'utf8'));
const before=JSON.stringify(d),f=d.framework;
let checked=0;
for(const m of f.model_library){
 for(const p of f.presentation_choices){
  const input={model:m.id,need:m.example_need_id,metric:m.metric_ids[0]||'',format:p.id,code:'ANA.'+m.id+'.DRAFT',question:m.question,owner:'业务责任岗位待确认',scope:'业务日期类型与观察期、截止点、可比配置待业务确认'};
  const {errors,draft}=buildBiDesignDraft(d,input);
  assert.deepEqual(errors,[]);assert.equal(draft.model.id,m.id);assert.equal(draft.presentation.id,p.id);
  assert.equal(draft.requirement.id,m.example_need_id);assert.equal(draft.state,'设计草稿，待业务与数据评审');
  assert.equal(draft.data_contract.code,draft.requirement.id.split('-')[0]);
  assert.equal(draft.metric_candidate?.id||'',input.metric);
  assert.ok(draft.pending_confirmations.length>=7);assert.ok(!('result' in draft));
  checked++;
 }
}
const base={model:'STATUS',need:'C-02',metric:'K02',format:'workbench',code:'ANA.DELIVERY.DRAFT',question:'哪些订单需要协调？',owner:'计划',scope:'承诺交付日期范围与截止时点待确认'};
const bad=[['code','../test'],['code','a'],['code','A'.repeat(81)],['question',''],['question','字'.repeat(501)],['owner',''],['owner','字'.repeat(201)],['scope',''],['scope','字'.repeat(2001)],['model','UNREGISTERED'],['need','C-999'],['format','unsupported'],['metric','K999']];
for(const [field,value] of bad){const r=buildBiDesignDraft(d,{...base,[field]:value});assert.ok(r.errors.length,field);assert.equal(r.draft,null)}
const emptyMetric=buildBiDesignDraft(d,{...base,metric:''});assert.equal(emptyMetric.draft.metric_candidate,null);assert.ok(emptyMetric.draft.pending_confirmations.includes('主指标及可计算定义'));
assert.equal(JSON.stringify(d),before,'design drafting must not mutate the catalog');
const evidence={version:d.version,model_format_combinations:checked,rejected_invalid_inputs:bad.length,empty_metric_explicitly_pending:true,catalog_unchanged:true,scope:'Design-only draft validation; no business calculation, query, publication or source write.'};
await writeFile(new URL('../data/bi_drafts_validation.json',import.meta.url),JSON.stringify(evidence,null,2)+'\n');
console.log(JSON.stringify(evidence));
