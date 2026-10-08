// The original scheduler supplies root_tasks. This module only groups that result.
export const BLOCKER_READING_VERSION = 'joint-blocker-reading-v1';
const order = (a,b) => a < b ? -1 : a > b ? 1 : 0;
const time = v => v.replace('T',' ');
const sum = rows => {
 const value = rows.reduce((n,r)=>n+r.qty,0);
 if (!Number.isSafeInteger(value)) throw Error('批次台数超出可核对范围');
 return value;
};
function index(rows, label) {
 const map = new Map();
 for (const row of rows) {
  if (typeof row.id !== 'string' || !row.id || map.has(row.id)) throw Error(label+'编号缺失或重复');
  map.set(row.id,row);
 }
 return map;
}
function wallTime(value) {
 const parsed = typeof value === 'string' && /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}$/.test(value) ? Date.parse(value+'Z') : NaN;
 return Number.isFinite(parsed) && new Date(parsed).toISOString().slice(0,19) === value;
}
export function jointBlockerReport(d) {
 if (d.state !== 'trial') return {version:BLOCKER_READING_VERSION,state:'paused',summary:null,rows:[],issues:['原试排资料暂停，首阻断关联不计算。']};
 try {
  const tasks=index(d.tasks,'任务'),jobs=index(d.jobs,'批次'),blocked=d.tasks.filter(t=>t.state==='blocked');
  for (const job of d.jobs) if (!Number.isSafeInteger(job.qty) || job.qty <= 0 || !wallTime(job.due) || !['scheduled','late','blocked'].includes(job.state)) throw Error('批次台数、内部目标或状态无法核对');
  for (const task of d.tasks) {
   if (!jobs.has(task.job_id) || !['blocked','scheduled'].includes(task.state) || !Array.isArray(task.root_tasks)) throw Error('任务批次或阻断关系无法核对');
   if (new Set(task.root_tasks).size !== task.root_tasks.length) throw Error('任务首阻断编号重复');
   if ((task.state==='blocked') !== (task.root_tasks.length>0)) throw Error('任务状态与首阻断关系不一致');
   for (const id of task.root_tasks) {
    const root=tasks.get(id);
    if (!root || root.state!=='blocked' || !Array.isArray(root.root_tasks) || root.root_tasks.length!==1 || root.root_tasks[0]!==id) throw Error('首阻断任务缺失或不是原始阻断点');
   }
  }
  const affectedJobs=[...new Set(blocked.map(t=>t.job_id))].sort(order).map(id=>jobs.get(id));
  if (d.jobs.some(j=>(j.state==='blocked') !== affectedJobs.some(a=>a.id===j.id))) throw Error('批次状态与未排任务不一致');
  const s=d.summary;
  if (!s || s.tasks!==d.tasks.length || s.jobs!==d.jobs.length || s.qty!==sum(d.jobs) || s.blocked_tasks!==blocked.length || s.blocked_jobs!==affectedJobs.length || s.scheduled_tasks!==d.tasks.length-blocked.length) throw Error('原试排汇总与完整任务清单不一致');
  const rootIds=[...new Set(blocked.flatMap(t=>t.root_tasks))];
  const rows=rootIds.map(id=>{
   const root=tasks.get(id),members=blocked.filter(t=>t.root_tasks.includes(id));
   const jobRows=[...new Set(members.map(t=>t.job_id))].sort(order).map(key=>jobs.get(key));
   return {id,job_id:root.job_id,process:root.process,branch:root.branch,reason:root.reason,
    task_ids:members.map(t=>t.id).sort(order),job_ids:jobRows.map(j=>j.id),tasks:members.length,jobs:jobRows.length,
    batch_qty:sum(jobRows),earliest_due:jobRows.map(j=>j.due).sort(order)[0],overlapping_tasks:members.filter(t=>t.root_tasks.length>1).length};
  }).sort((a,b)=>order(a.earliest_due,b.earliest_due)||b.jobs-a.jobs||b.tasks-a.tasks||order(a.id,b.id));
  return {version:BLOCKER_READING_VERSION,state:rows.length?'blocked':'clear',summary:{roots:rows.length,tasks:blocked.length,jobs:affectedJobs.length,batch_qty:sum(affectedJobs),overlapping_tasks:blocked.filter(t=>t.root_tasks.length>1).length},rows,issues:[]};
 } catch (e) { return {version:BLOCKER_READING_VERSION,state:'paused',summary:null,rows:[],issues:[e.message]}; }
}

export function jointTaskSelection(d, report, {job='',state='',root=''}={}) {
 if (job && !d.jobs.some(j=>j.id===job)) throw Error('批次不属于当前方案');
 if (!['','scheduled','blocked'].includes(state)) throw Error('任务状态无效');
 const row=root ? report.rows.find(r=>r.id===root) : null;
 if (root && !row) throw Error('首阻断不属于当前核对队列');
 const ids=row ? new Set(row.task_ids) : null;
 return d.tasks.filter(t=>(!job||t.job_id===job)&&(!state||t.state===state)&&(!ids||ids.has(t.id)));
}

export function jointBlockerQueue(report, {esc,table,panel}, {page=1,size=40,selected=''}={}) {
 if (!Number.isSafeInteger(page)||page<1||!Number.isSafeInteger(size)||size<1) throw Error('首阻断页码无效');
 if (report.state==='paused') return panel('首阻断关联 · 暂停核对','',`<p class="empty">${report.issues.map(esc).join('；')}</p>`);
 if (report.state==='clear') return panel('首阻断关联','', '<p class="empty">本次假设没有未排入任务；仍须分别核对晚于内部目标、订单覆盖和放行条件。</p>');
 const s=report.summary,rows=report.rows.slice((page-1)*size,page*size);
 return panel('首阻断关联 · 完整方案','按原算法的首阻断编号分组；不是现场根因或新的派工优先级。',
  `<p class="source">${s.roots} 个首阻断，去重后 ${s.tasks} 项未排入任务，涉及 ${s.jobs} 个批次 / ${s.batch_qty} 台。${s.overlapping_tasks} 项任务同时关联多个首阻断，表内任务、批次及台数不能跨行相加。涉及批次台数不是损失产量或客户逾期量。</p>`+
  table(['首阻断任务 / 工序','原试排未排原因','关联未排任务 / 其中多首阻断','涉及批次 / 台数（逐批次计一次）','最早内部应完成'],rows.map(r=>[
   `<button class="row-link" data-joint-root-detail="${esc(r.id)}">${esc(r.id)}</button><small class="block">${esc(r.process)} / ${esc(r.branch)} · ${esc(r.job_id)}</small>`,esc(r.reason),
   `<button class="row-link" data-joint-root-focus="${esc(r.id)}" aria-pressed="${selected===r.id}">查看 ${r.tasks} 项任务</button><small class="block">其中 ${r.overlapping_tasks} 项有多个首阻断</small>`,
   `${r.jobs} 批 / ${r.batch_qty} 台<small class="block">${r.job_ids.map(esc).join('、')}</small>`,esc(time(r.earliest_due))
  ]))+
  `<div class="toolbar"><button id="joint-root-prev" ${page===1?'disabled':''}>上一页</button><span>${page} / ${Math.max(1,Math.ceil(report.rows.length/size))} 页 · ${report.rows.length} 个首阻断</span><button id="joint-root-next" ${page*size>=report.rows.length?'disabled':''}>下一页</button></div>`+
  '<p class="source">阅读顺序按最早内部目标、涉及批次数、关联任务数及原编号排列；不是优先级优化或交付承诺。点任务读取完整依据；点数量查看该首阻断的全部关联任务并重置批次/状态选择。</p>');
}
