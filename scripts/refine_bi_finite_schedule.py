"""Publish explicit partial trial coverage without claiming an APS system."""
import copy
MARKER=' 有限资源试排：';NEEDS=('F-02','F-05','F-06','F-07')
STATUS='新增独立合成有限资源试排：第36份Excel含6方案、36批次、1188任务、1417依赖、2374候选、961资源窗口及24不可用段。前段批量、装配起逐台；每路线数量核对到批次。按应完成时间或批次优先级选已就绪任务，在资源尾部选择最早完成窗口；换型也占用单容量，单任务不跨窗口，空档不回填，不证明最优。资源甘特、独立批次交期、全部任务及等待/根阻断、资源负载、直接与全方案Excel来源、同范围CSV/JSON已提供。环路、声明数量不完整或窗口重叠暂停整方案；候选不足或连续窗口不足保留未排入并传到后序。600秒凭据绑定假设、策略、全部来源、规则、结果与当前账号；导出审计不改业务事实。资源窗口和工时是独立假设，不与真实未完量或历史产量混用；共享人员、技能、物料、模具、跨班连续加工、优化、正式审批与U8/MES同步待建设。浏览器、手机和实际下载未验收。'
CONTRACT=dict(revision='finite-resource-trial-20261007',href='#finite-schedule',needs=list(NEEDS),state=STATUS,
 reading=['选择独立方案和策略','先看约束与来源完整性','读资源窗口与任务甘特','分开核对未排入和已排但晚交','定位工序与Excel依据','同范围导出或修改假设后重算'],
 definition='粒度：独立试排方案×批次×路线任务×明确批内份号；数量按批次计一次，每条路线任务数量合计回到批次；份号不是实际SN。',
 measures='任务加工分钟=任务台数×假设每台分钟；首次或跨族换型按候选假设，同族为0；两阶段向上取整到秒。可安排分钟=截至内资源窗口减不可用交集；假设负载=试排换型与加工占用/可安排分钟，不是实际OEE。批次所有任务已排入才给完成时间和晚于分钟，未排入不充当准时。',
 method='两种确定性策略；拓扑就绪任务按应完成时间或优先级排序，候选资源尾部寻找能连续容纳换型和加工的窗口，以最早完成者安排。无空档回填，无全局最优证明。',
 visuals='资源为行、厂内假设时间为横轴；定子/转子/整机分色，换型、可用窗和不可用段独立显示；完整批次风险表、所有工序表、资源负载表；暂停时不绘制健康甘特或填0。',
 boundary='完全独立合成假设，仅只读试排；不写回工单、不实际派工、不新增审批或原件权限。物料齐套、共享员工、技能、工装和费用约束仍未联立。')
def refine_schedule(d):
 for group in d['domains']:
  for n in group['items']:
   if n['id'] in NEEDS:n['gap']=n['gap'].split(MARKER)[0]+MARKER+STATUS
   if n['id'] in ('F-05','F-06'):
    n['implementation']='模拟部分覆盖';n['decision_spec']['implementation']='模拟部分覆盖'
 for p in d['page_blueprints']:
  if p['id']=='P03':p['status']=p['status'].split(MARKER)[0]+MARKER+STATUS
 d['framework']['finite_schedule_trial']=copy.deepcopy(CONTRACT)
 d['framework']['surfaces']=[s for s in d['framework']['surfaces'] if s['href']!='#finite-schedule']+[dict(name='有限资源试排',question='在本次假设下哪些任务可以排入，等待和交期风险来自哪里？',content=CONTRACT['visuals'],action='核对假设、未排入及来源，再交计划员评审；试算不派工',href='#finite-schedule',status=STATUS)]
 return d
def remove_schedule(d):
 for group in d['domains']:
  for n in group['items']:
   if n['id'] in NEEDS:n['gap']=n['gap'].split(MARKER)[0]
   if n['id'] in ('F-05','F-06'):n['implementation']='待建设';n['decision_spec']['implementation']='待建设'
 for p in d['page_blueprints']:
  if p['id']=='P03':p['status']=p['status'].split(MARKER)[0]
 d['framework'].pop('finite_schedule_trial',None);d['framework']['surfaces']=[s for s in d['framework']['surfaces'] if s['href']!='#finite-schedule'];return d
