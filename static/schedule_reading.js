import {jointMaterialLink} from './joint_material.js';
// Read-only rendering and request lifetimes shared by the three trial workspaces.
import {jointCandidateEvidence} from './joint_candidates.js';
const time = v => typeof v === 'string' && v ? v.replace('T', ' ') : '未形成时间';
const number = v => typeof v === 'number' && Number.isFinite(v) ? v.toLocaleString('zh-CN', {maximumFractionDigits: 2}) : '未计算';
const state = v => ({scheduled: '已排入', blocked: '未排入', late: '晚于假设交期'}[v] || '未计算');

export function scheduleSources(rows, {esc, table}) {
 return table(['业务对象', 'Excel / 工作表 / 行', '当前来源版本'], rows.map(s => [
  `${esc(s.dataset)}<small class="block">${esc(s.key)}</small>`,
  s.missing ? '来源缺失' : `${esc(s.filename)}<br>${esc(s.sheet)} · 第 ${esc(s.row)} 行`,
  s.missing ? '缺失' : `v${esc(s.revision)} · 源行 ${esc(s.source_row_id)}`
 ]));
}

export function scheduleTaskDetail(d, h, mode) {
 if (!['finite', 'crew', 'joint'].includes(mode)) throw Error('任务阅读类型无效');
 const {esc, table, panel} = h, r = d.row;
 const fields = rows => table(['核对项目', '原假设或本次试排结果'], rows.map(([label, v]) => [label, v == null ? '未计算 / 未安排' : esc(v)]));
 const ids = values => values?.length ? values.join('、') : '无';
 const common = [['任务编号', r.id], ['独立批次', r.job_id], ['配置编码', r.product_id], ['路线行', r.route_id], ['工序 / 分支', `${r.process} / ${r.branch}`],
  ['任务处理台数（不跨工序累加）', r.qty], ['当前安排状态', state(r.state)], ['未排原因', r.reason || (r.state === 'scheduled' ? '无阻断' : '未提供原因')],
  ['直接前序任务', ids(r.predecessors)], ['首个阻断任务', ids(r.root_tasks)]];
 if ('portion' in r) common.push(['批内份号', r.portion], ['换型族', r.family]);
 const timing = [['前序准备时点', time(r.dependency_ready)], ['准备开始', time(r.started)], ['加工开始', time(r.process_started)], ['加工完成', time(r.finished)],
  ['换型分钟', number(r.setup_minutes)], ['假设加工分钟', number(r.process_minutes)], ['等待分钟', number(r.wait_minutes)]];
 if ('release' in r) timing.unshift(['假设最早可开始', time(r.release)]);
 const selection = [['选中资源位', r.resource_id], ['资源候选编号', r.option_id], ['资源窗口编号', r.window_id]];
 if (mode !== 'finite') selection.push(['操作工号', r.employee_id], ['技能依据', r.skill_id], ['资格假设编号', r.credential_id], ['人员候选编号', r.candidate_id], ['人员窗口编号', r.worker_window_id]);
 if (mode === 'crew') timing.push(['同资源状态参考时点', time(r.resource_ready)], ['同资源状态人员新增等待分钟', number(r.staff_additional_wait_minutes)]);
 if (mode === 'joint') timing.push(['物料可用时点', time(r.material_ready)], ['物料就绪等待分钟', number(r.material_readiness_delay_minutes)]);
 let html = `<p class="source">${esc(d.notice)}</p>` + panel('任务身份与阻断', '', fields(common)) +
  panel('时点与占用', mode === 'finite' ? '日期均为厂内假设时间，等待不是现场停工损失。' : '日期均为厂内假设时间。各等待指标含义不同，不能相加或视为现场损失。', fields(timing)) +
  panel('选中资源与资格依据', '', fields(selection));
 if (d.predecessors) html += panel('直接前序结果', '', table(['任务 / 工序', '安排状态', '完成时点', '未排原因'], d.predecessors.map(t => [esc(t.id) + '<br>' + esc(t.process), state(t.state), esc(time(t.finished)), esc(t.reason || (t.state === 'scheduled' ? '无阻断' : '未提供原因'))])));
 if (mode === 'joint') {
  html += panel('该工序整批需求', '同工序不同份号可共用一次整批预留；需求已预留不等于本任务新领料。',
   table(['需求 / BOM版本 / 路线', '物料 / 单位', '单耗 × (1+损耗) / 步长', '整批需求 / 已预留', '预留触发任务 / 时点'], d.demands.map(n => [
    `${esc(n.id)}<small class="block">${esc(n.bom_id)} / ${esc(n.bom_version)}<br>${esc(n.route_id)}</small>`,
    `${jointMaterialLink(n.material_id,n.unit,n.material_id,h)} / ${esc(n.unit)}`, `${esc(n.bom_qty)} × (1+${esc(n.scrap_allowance)})<small class="block">步长 ${esc(n.quantum)}</small>`,
    `${esc(n.required_qty)} / ${esc(n.reserved_qty)}`, n.reservation ? `${esc(n.reservation.task_id)}<br>${esc(time(n.reservation.reserved_at))}` : '未预留，结合阻断核查'
   ])) + `<p class="source">本任务新增预留的需求号：${esc(ids(r.new_reservation_ids))}。不同物料与单位不合计。</p>`);
  html += panel('相关整批预留流水', '', table(['需求 / 供给批次', '实际触发任务', '物料 / 单位', '预留量', '供给可用 / 预留时点'], d.reservations.map(a => [
   `${esc(a.demand_id)}<br>${esc(a.supply_id)}`, esc(a.task_id), `${esc(a.material_id)} / ${esc(a.unit)}`, esc(a.qty), `${esc(time(a.available_from))}<br>${esc(time(a.reserved_at))}`
  ])));
  if (r.shortages?.length) html += panel('本次安排的物料缺口', '按原结果逐项列示，不由未预留状态推断缺料。', table(['物料 / 单位', '所需 / 可用 / 缺口'], r.shortages.map(s => [
   `${jointMaterialLink(s.material_id,s.unit,s.material_id,h)} / ${esc(s.unit)}`, `${esc(s.required_qty)} / ${esc(s.available_qty)} / ${esc(s.shortage_qty)}`
  ])));
 }
 if (mode === 'joint' && d.candidate_evidence) html += jointCandidateEvidence(d.candidate_evidence, h);
 html += panel('任务直接 Excel 来源', '共享竞争仍须核对全方案来源与完整导出。', scheduleSources(d.sources, h));
 return html + `<p class="source">${d.can_download_original ? '管理员可在导入页读取归档原件。' : '来源索引不授予原件下载权限。'}</p>`;
}

export function createScheduleReadGuard(h) {
 let generation = 0, modalRequest = 0;
 const cancelModal = () => { modalRequest++; };
 const cancel = () => { generation++; cancelModal(); };
 h.on('#detail', 'close', cancelModal);
 function begin(token) {
  const current = ++generation;
  cancelModal();
  const alive = () => h.isCurrent(token) && generation === current;
  const attempt = fn => async (...args) => {
   if (!alive()) return;
   try { return await fn(...args); } catch (e) { if (alive()) h.toast(e.message); }
  };
  async function read(load) {
   try { const value = await load(); return alive() ? value : null; }
   catch (e) { if (alive()) throw e; return null; }
  }
  async function modalRead(load) {
   const request = ++modalRequest, revision = h.getModalRevision();
   const valid = () => alive() && request === modalRequest && revision === h.getModalRevision();
   try { const value = await load(); return valid() ? value : null; }
   catch (e) { if (valid()) throw e; return null; }
  }
  function modalLease() {
   const request = modalRequest, revision = h.getModalRevision();
   return () => alive() && request === modalRequest && revision === h.getModalRevision();
  }
  return {alive, attempt, read, modalRead, cancelModal, modalLease};
 }
 return {begin, cancel};
}
