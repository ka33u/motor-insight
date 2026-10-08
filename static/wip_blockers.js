// Read the original WIP dependency graph; never change scheduling or reservations.
export const WIP_BLOCKER_VERSION='wip-blocker-reading-v1';
const compare=(a,b)=>a<b?-1:a>b?1:0;
const states=['completed','carried','scheduled','blocked'];
const sorted=values=>[...values].sort(compare);
const same=(a,b)=>JSON.stringify(sorted(a))===JSON.stringify(sorted(b));
const stamp=v=>v.replace('T',' ');
function index(rows,label){
 if(!Array.isArray(rows)||rows.length>5000)throw Error(label+'清单缺失或超过5000项，未截断');
 const out=new Map();
 for(const row of rows){if(!row||typeof row.id!=='string'||!row.id||out.has(row.id))throw Error(label+'编号缺失或重复');out.set(row.id,row);}
 return out;
}
function wallTime(v){
 const parsed=typeof v==='string'&&/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}$/.test(v)?Date.parse(v+'Z'):NaN;
 return Number.isFinite(parsed)&&new Date(parsed).toISOString().slice(0,19)===v;
}
function qty(jobs){const value=jobs.reduce((n,j)=>n+j.qty,0);if(!Number.isSafeInteger(value))throw Error('工单台数超出可核对范围');return value;}
function identity(d){
 const rows=(values,fields)=>values.map(r=>fields.map(f=>Array.isArray(r[f])?sorted(r[f]):r[f])).sort((a,b)=>compare(a[0],b[0]));
 return JSON.stringify([d.study?.id,d.study?.version,d.policy,d.rule_version,d.source_hash,d.rule_hash,d.receipt,d.summary,
  rows(d.tasks,['id','job_id','state','process','branch','reason','predecessors','root_tasks','finished']),
  rows(d.jobs,['id','qty','due','finished','state','actual_completed_tasks','remaining_tasks']),rows(d.work_orders,['job_id','work_order_id'])]);
}
export function wipBlockerReport(d){
 const paused=message=>({version:WIP_BLOCKER_VERSION,state:'paused',identity:null,summary:null,rows:[],issues:[message]});
 if(d.state!=='trial')return paused('原在制方案暂停，首阻断关联未计算。');
 try{
  if(d.rule_version!=='WIP_REMAINDER_SHARED_POOLS_1'||!['due','priority'].includes(d.policy)||typeof d.study?.id!=='string'||!d.study.id||!Number.isSafeInteger(d.study.version)||d.study.version<1)throw Error('方案版本、策略或在制算法版本不受当前阅读定义支持');
  const tasks=index(d.tasks,'任务'),jobs=index(d.jobs,'工单批次'),links=new Map();
  if(!tasks.size||!jobs.size)throw Error('完整在制方案缺少任务或工单');
  if(!Array.isArray(d.work_orders)||d.work_orders.length!==jobs.size)throw Error('原工单映射不完整');
  const works=new Set();
  for(const link of d.work_orders){
   if(!jobs.has(link.job_id)||links.has(link.job_id)||typeof link.work_order_id!=='string'||!link.work_order_id||works.has(link.work_order_id))throw Error('原工单与批次须完整一一对应');
   links.set(link.job_id,link.work_order_id);works.add(link.work_order_id);
  }
  for(const job of jobs.values())if(!Number.isSafeInteger(job.qty)||job.qty<=0||!wallTime(job.due)||!['covered','late','blocked'].includes(job.state))throw Error('工单台数、假设交期或结果无法核对');
  const before=new Map(),after=new Map([...tasks.keys()].map(k=>[k,[]]));let memberships=0,dependencies=0;
  for(const task of tasks.values()){
   if(!jobs.has(task.job_id)||!states.includes(task.state)||!Array.isArray(task.predecessors)||!Array.isArray(task.root_tasks))throw Error('任务工单、状态或原依赖缺失');
   if(typeof task.process!=='string'||!task.process||typeof task.branch!=='string'||!task.branch||typeof task.reason!=='string'||(task.state==='blocked'&&!task.reason.trim()))throw Error('任务工序、分支或未排原因缺失');
   if(new Set(task.root_tasks).size!==task.root_tasks.length||new Set(task.predecessors).size!==task.predecessors.length)throw Error('任务前序或首阻断编号重复');
   dependencies+=task.predecessors.length;if(dependencies>200000)throw Error('前序关联超过200000条，未截断');
   memberships+=task.root_tasks.length;if(memberships>200000)throw Error('首阻断关联超过200000条，未截断');
   if(task.state==='blocked'?(task.root_tasks.length===0||task.finished!==null):(task.root_tasks.length!==0||!wallTime(task.finished)))throw Error('任务完成时点与阻断状态不一致');
   for(const id of task.predecessors){const pred=tasks.get(id);if(!pred||pred.job_id!==task.job_id||id===task.id)throw Error('前序缺失、跨工单或指向自身');after.get(id).push(task.id);}
   for(const id of task.root_tasks)if(!tasks.has(id))throw Error('首阻断任务缺失');
   before.set(task.id,task.predecessors.length);
  }
  // Rebuild original-root propagation through all predecessors, including joins.
  const queue=[...before].filter(([,n])=>!n).map(([id])=>id),roots=new Map();
  for(let i=0;i<queue.length;i++){
   const task=tasks.get(queue[i]),failed=task.predecessors.filter(id=>tasks.get(id).state==='blocked');
   if(task.state!=='blocked'&&failed.length)throw Error('已排或历史任务仍有未排前序');
   const expected=task.state!=='blocked'?[]:failed.length?sorted(new Set(failed.flatMap(id=>roots.get(id)))):[task.id];
   if(!same(expected,task.root_tasks))throw Error('首阻断关系不符合原前序传播，停止汇总');
   roots.set(task.id,expected);
   for(const id of after.get(task.id)){before.set(id,before.get(id)-1);if(!before.get(id))queue.push(id);}
  }
  if(queue.length!==tasks.size)throw Error('任务依赖存在环路，停止汇总');
  const byJob=new Map([...jobs.keys()].map(k=>[k,[]]));for(const task of tasks.values())byJob.get(task.job_id).push(task);
  for(const job of jobs.values()){
   const rows=byJob.get(job.id),blocked=rows.some(t=>t.state==='blocked'),completed=rows.filter(t=>t.state==='completed').length;
   if(!rows.length||job.actual_completed_tasks!==completed||job.remaining_tasks!==rows.length-completed)throw Error('工单历史/剩余任务计数不一致');
   const finish=blocked?null:sorted(rows.map(t=>t.finished)).at(-1),state=blocked?'blocked':finish>job.due?'late':'covered';
   if(job.finished!==finish||job.state!==state)throw Error('工单结果与完整任务不一致');
  }
  const blocked=d.tasks.filter(t=>t.state==='blocked'),affected=sorted(new Set(blocked.map(t=>t.job_id))).map(id=>jobs.get(id));
  const summary={tasks:tasks.size,jobs:jobs.size,qty:qty(d.jobs),historical_completed_tasks:d.tasks.filter(t=>t.state==='completed').length,
   carried_tasks:d.tasks.filter(t=>t.state==='carried').length,scheduled_tasks:d.tasks.filter(t=>t.state==='scheduled').length,blocked_tasks:blocked.length,
   covered_jobs:d.jobs.filter(j=>j.state!=='blocked').length,late_jobs:d.jobs.filter(j=>j.state==='late').length,blocked_jobs:affected.length};
  if(!d.summary||Object.entries(summary).some(([k,v])=>d.summary[k]!==v))throw Error('原汇总与完整工单/四类任务不一致');
  const members=new Map();for(const task of blocked)for(const id of task.root_tasks){if(!members.has(id))members.set(id,[]);members.get(id).push(task);}
  const rows=[...members].map(([id,linked])=>{
   const root=tasks.get(id),jobRows=sorted(new Set(linked.map(t=>t.job_id))).map(id=>jobs.get(id));
   return {id,job_id:root.job_id,work_order_id:links.get(root.job_id),process:root.process,branch:root.branch,reason:root.reason,
    task_ids:sorted(linked.map(t=>t.id)),job_ids:jobRows.map(j=>j.id),work_order_ids:jobRows.map(j=>links.get(j.id)),tasks:linked.length,jobs:jobRows.length,
    whole_job_qty:qty(jobRows),earliest_due:sorted(jobRows.map(j=>j.due))[0],overlapping_tasks:linked.filter(t=>t.root_tasks.length>1).length};
  }).sort((a,b)=>compare(a.earliest_due,b.earliest_due)||b.jobs-a.jobs||b.tasks-a.tasks||compare(a.id,b.id));
  return {version:WIP_BLOCKER_VERSION,state:rows.length?'blocked':'clear',identity:identity(d),summary:{roots:rows.length,tasks:blocked.length,jobs:affected.length,whole_job_qty:qty(affected),overlapping_tasks:blocked.filter(t=>t.root_tasks.length>1).length},rows,issues:[]};
 }catch(e){return paused(e.message);}
}
export function wipTaskSelection(d,report,{job='',state='',root=''}={}){
 if(job&&!d.jobs.some(j=>j.id===job))throw Error('工单批次不属于当前方案');
 if(!['',...states].includes(state))throw Error('任务状态无效');
 if(root){
  if(report.version!==WIP_BLOCKER_VERSION||report.state==='paused'||report.identity!==identity(d))throw Error('首阻断队列已变化，请重新读取');
  const task=d.tasks.find(t=>t.id===root);
  if(!report.rows.some(r=>r.id===root)||!task||!same(task.root_tasks,[root]))throw Error('首阻断不属于当前队列');
 }
 return d.tasks.filter(t=>(!job||t.job_id===job)&&(!state||t.state===state)&&(!root||t.root_tasks.includes(root)));
}
export function wipBlockerQueue(report,{esc,table,panel},{page=1,size=20,selected=''}={}){
 if(!Number.isSafeInteger(page)||page<1||!Number.isSafeInteger(size)||size<1||size>100)throw Error('首阻断页码无效');
 if(report.state==='paused')return panel('首阻断关联 · 未计算','',`<p class="empty">${report.issues.map(esc).join('；')}</p>`);
 if(report.state==='clear')return panel('首阻断关联','', '<p class="empty">本次假设没有未排入任务；仍须分别核对假设交期、实际物料及正式批准。</p>');
 const s=report.summary,last=Math.max(1,Math.ceil(report.rows.length/size));if(page>last)throw Error('首阻断页码超出范围');
 const rows=report.rows.slice((page-1)*size,page*size);
 return panel('首阻断关联 · 完整方案','按原前序图核对阻断传播；本队列不是现场根因诊断或派工优先级。',
  `<p class="source">${s.roots} 个首阻断，去重后 ${s.tasks} 项未排任务，涉及 ${s.jobs} 张工单 / 整单 ${s.whole_job_qty} 台。${s.overlapping_tasks} 项任务关联多个首阻断，任务、工单与台数不能跨行相加。整单台数不是剩余产量、损失产量或真实延期量。</p>`+
  table(['首阻断任务 / 原工单','原未排原因','影响任务 / 其中多首阻断','涉及工单 / 整单台数','最早假设交期'],rows.map(r=>[
   `<button class="row-link" data-wt-task="${esc(r.id)}">${esc(r.id)}</button><small class="block">${esc(r.process)} / ${esc(r.branch)}<br>${esc(r.work_order_id)} · ${esc(r.job_id)}</small>`,esc(r.reason),
   `<button class="row-link" data-wt-root-focus="${esc(r.id)}" aria-pressed="${selected===r.id}">查看 ${r.tasks} 项任务</button><small class="block">其中 ${r.overlapping_tasks} 项多首阻断</small>`,
   `${r.jobs} 单 / ${r.whole_job_qty} 台<small class="block">${r.work_order_ids.map(esc).join('、')}</small>`,esc(stamp(r.earliest_due))]))+
  `<div class="toolbar"><button id="wt-root-prev" ${page===1?'disabled':''}>上一页</button><span>${page} / ${last} 页 · ${report.rows.length} 个首阻断</span><button id="wt-root-next" ${page===last?'disabled':''}>下一页</button></div>`+
  '<p class="source">按最早假设交期、涉及工单数、关联任务数及编号排序。点数量重置工单和状态，聚焦该阻断的全部关联任务；之后可交叉筛选。全方案甘特、来源和完整导出范围不变。处理一个阻断后仍须重算全部物料与人机约束，不能把关联任务数当作可恢复产量。</p>');
}
