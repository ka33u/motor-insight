// Pure projection of the two original schedules. No new scheduling or capacity denominator.
export const OCCUPANCY_VERSION='joint-occupancy-v1';
const sides=['left','right'],policies={left:'应完成时间优先',right:'批次优先级优先'};
const field={resource:'resource_id',worker:'employee_id'};
const local=v=>v.replace('T',' ');
const minutes=v=>v.toLocaleString('zh-CN',{maximumFractionDigits:2});
function stamp(value){
 if(typeof value!=='string'||!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,6})?$/.test(value))throw Error('任务或范围时间不完整');
 const n=Date.parse(value+'Z');
 if(!Number.isFinite(n)||new Date(n).toISOString().slice(0,19)!==value.slice(0,19))throw Error('任务或范围时间无效');
 return n;
}
function need(ok,message){if(!ok)throw Error(message)}
export function occupancyReport(d){
 const base={version:OCCUPANCY_VERSION,state:'unavailable',reason:'',axes:{resource:[],worker:[]},summary:null};
 if(d?.state!=='compared'||!d.summary)return {...base,state:'paused',reason:'原对照暂停，占用未计算'};
 try{
  const start=stamp(d.resource_study.baseline),end=stamp(d.resource_study.horizon_end);need(end>start,'方案时间范围无效');
  need(d.tasks.length===d.summary.tasks,'任务范围不完整');
  const jobs=new Set(d.jobs.map(j=>j.id)),seen=new Set(),entries={left:[],right:[]};
  need(jobs.size===d.jobs.length,'批次身份重复');
  for(const row of d.tasks){
   need(typeof row.id==='string'&&row.id&& !seen.has(row.id),'任务身份缺失或重复');seen.add(row.id);
   need(jobs.has(row.job_id),'任务缺少批次依据');
   for(const side of sides){
    const t=row[side];need(t&&t.id===row.id&&t.job_id===row.job_id,'两列任务身份不一致');
    need(['scheduled','blocked'].includes(t.state),'任务安排状态无效');
    if(t.state==='blocked'){need(t.started==null&&t.process_started==null&&t.finished==null,'未排任务含有安排时间');continue}
    for(const k of Object.values(field))need(typeof t[k]==='string'&&t[k],'已排任务缺少设备或工号');
    const a=stamp(t.started),b=stamp(t.process_started),c=stamp(t.finished);
    need(start<=a&&a<=b&&b<c&&c<=end,'任务时间不在方案范围或次序无效');
    need(Number.isFinite(t.setup_minutes)&&Number.isFinite(t.process_minutes)&&Math.abs((b-a)-t.setup_minutes*60000)<=1&&Math.abs((c-b)-t.process_minutes*60000)<=1,'占用时点与换型加工分钟不一致');
    entries[side].push({id:row.id,job_id:row.job_id,process:row.process,resource_id:t.resource_id,employee_id:t.employee_id,started:t.started,process_started:t.process_started,finished:t.finished,start:a,process_start:b,end:c,setup_minutes:(b-a)/60000,process_minutes:(c-b)/60000});
   }
  }
  for(const [side,policy] of [['left','due'],['right','priority']]){
   const c=d.columns[policy];need(c.state==='trial'&&c.summary?.tasks===d.tasks.length&&c.summary.scheduled_tasks===entries[side].length&&c.summary.blocked_tasks===d.tasks.length-entries[side].length,'原策略摘要与完整任务不一致');
  }
  const axes={};
  for(const axis of Object.keys(field)){
   const ids=[...new Set(sides.flatMap(s=>entries[s].map(t=>t[field[axis]])))].sort();
   axes[axis]=ids.map(id=>{
    const row={id};
    for(const side of sides){
     const tasks=entries[side].filter(t=>t[field[axis]]===id).sort((a,b)=>a.start-b.start||a.id.localeCompare(b.id));
     for(let i=1;i<tasks.length;i++)need(tasks[i-1].end<=tasks[i].start,'同一设备或人员的占用发生重叠');
     row[side]={tasks,setup_minutes:tasks.reduce((n,t)=>n+t.setup_minutes,0),process_minutes:tasks.reduce((n,t)=>n+t.process_minutes,0)};
     row[side].busy_minutes=row[side].setup_minutes+row[side].process_minutes;
    }
    const signature=s=>JSON.stringify(row[s].tasks.map(t=>[t.id,t.started,t.process_started,t.finished,t.resource_id,t.employee_id]));
    row.changed=signature('left')!==signature('right');row.busy_delta_minutes=row.right.busy_minutes-row.left.busy_minutes;return row;
   });
  }
  const all=sides.flatMap(s=>entries[s]),extent=all.length?[Math.min(...all.map(t=>t.start)),Math.max(...all.map(t=>t.end))]:[start,end];
  return {...base,state:'ready',axes,range:[start,end],occupied_range:extent,summary:{tasks:d.tasks.length,left_scheduled:entries.left.length,right_scheduled:entries.right.length,left_blocked:d.tasks.length-entries.left.length,right_blocked:d.tasks.length-entries.right.length}};
 }catch(error){return {...base,reason:error.message}}
}
export function occupancyRows(report,{axis='resource',entity='',changed=false,page=1,size=8}={}){
 const all=report.axes?.[axis]||[],rows=all.filter(r=>(!entity||r.id===entity)&&(!changed||r.changed));
 return {all:all.length,total:rows.length,rows:rows.slice((page-1)*size,page*size)};
}
export function occupancyTasks(tasks,scope){
 if(!scope)return tasks;
 const key=field[scope.axis];return key?tasks.filter(r=>sides.some(s=>r[s].state==='scheduled'&&r[s][key]===scope.id)):[];
}
export function occupancyChart(report,rows,{axis='resource',range='occupied',esc}){
 if(report.state!=='ready')return `<p class="empty">占用对照未计算：${esc(report.reason)}</p>`;
 if(!rows.length)return '<p class="empty">当前条件没有占用对象；未排任务不绘成零时长，可到任务清单核查。</p>';
 const [a,b]=range==='full'?report.range:report.occupied_range,span=b-a;
 const percent=v=>(v-a)/span*100;
 const ticks=Array.from({length:5},(_,i)=>{const value=a+span*i/4;return `<span style="left:${i*25}%">${new Date(value).toISOString().slice(5,16).replace('T',' ')}</span>`}).join('');
 const rowHTML=rows.map(row=>`<section class="occupancy-object"><div class="occupancy-label"><b>${esc(row.id)}</b><button data-occupancy-entity="${esc(row.id)}" data-occupancy-axis="${axis}">查看两列相关任务</button><small>占用差值 ${minutes(row.busy_delta_minutes)} 分钟</small></div><div>${sides.map(side=>{
  const s=row[side];return `<div class="occupancy-lane ${side}"><div class="occupancy-caption">${policies[side]} · ${s.tasks.length} 项 · ${minutes(s.busy_minutes)} 分钟 <small>换型 ${minutes(s.setup_minutes)} / 加工 ${minutes(s.process_minutes)}</small></div><div class="occupancy-track">${s.tasks.length?s.tasks.map(t=>{const label=`${policies[side]} · ${t.id} · ${t.job_id} · ${t.process} · 设备 ${t.resource_id} / 工号 ${t.employee_id} · 准备 ${local(t.started)} / 加工 ${local(t.process_started)} / 完成 ${local(t.finished)}`;return `<button class="occupancy-task" data-occupancy-task="${esc(t.id)}" aria-label="${esc(label)}" title="${esc(label)}" style="left:${percent(t.start)}%;width:${(t.end-t.start)/span*100}%"><span class="occupancy-setup" style="width:${(t.process_start-t.start)/(t.end-t.start)*100}%"></span></button>`}).join(''):'<span class="occupancy-none">该策略未分配任务</span>'}</div></div>`}).join('')}</div></section>`).join('');
 return `<div class="occupancy-scroll"><div class="occupancy-plot"><div class="occupancy-axis"><b>${axis==='worker'?'原操作工号':'原设备资源位'}</b><div>${ticks}</div></div>${rowHTML}</div></div>`;
}
