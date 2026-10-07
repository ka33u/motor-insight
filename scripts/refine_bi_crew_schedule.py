"""Add a verified joint-capacity example without replacing legacy BI definitions."""
import copy
MARKER=' 资源人员联立补充：'
NEEDS=('F-02','F-06','F-07','Q-02','Q-07')
STATUS='已提供独立合成联立试排：共享工号跨资源和工序容量1，完整换型/加工同时落入设备、人员和资格交集；缺候选、未来窗口或有效资格保留阻断并传播至后序。设备/人员两种甘特、批次交期与资源参考差值、全部任务与共同等待、资格交集、直接/全方案Excel依据及完整CSV/JSON。仅模拟部分覆盖：全程一人假设，物料、工装、自动工序看护比例、费用、替补能力评估、正式排班与实际派工未联立。未来窗口不由历史考勤推定，短资格窗口不改原技能登记。仅管理员、分析师、运营人员可读；不授予原件权限。浏览器、手机和实际下载未验收。'
CONTRACT=dict(revision='crew-resource-trial-20261007',href='#crew-schedule',needs=list(NEEDS),state=STATUS,
 reading=['选择人员假设及共同资源方案','检查当前技能登记与未来资格交集','切换设备与人员甘特','分开看未排入、已排但晚于与暂停','比较同资源状态人员等待及完整批次差值','追到候选、窗口和Excel来源，再评审假设'],
 definition='对象：独立联立方案×任务×资源位×工号×资格窗口；批次总台数计一次。候选工号可跨设备、工序共享，不能按设备复制人员容量；当前登记与独立未来假设取交集。',
 measures='同资源状态人员新增等待=当前选中设备、此前资源预订与前序准备固定时，联立开始−不含人员约束的可开始时间；不是人员效率因果损失。人员假设占用比例=全部换型加工占用/方案人员窗口减不可用交集；不是考勤、绩效或人工成本。完整批次完成差值可为正或负；未排入不判准时。',
 method='沿用两种拓扑就绪排序，选择资源尾部与人员尾部之后、双侧日历与资格交集中最早完成的候选；每任务一人全程，换型也占人，不回填空档，不证明最优。',
 visuals='设备/人员甘特切换保留同一方案和策略，选任务查看共同窗口与资格依据；批次参考对照、所有任务等待和阻断、人员占用、有效资格交集、全部来源分别呈现。异常数据暂停结果，已知缺人保留不可行任务，不补零。',
 boundary='全部合成、只读试算；不改旧工单、考勤、技能登记或实际派工，不证明未来业务授权。自动工序多机看护、无人运行、多人协作、替补资格分析、物料、模具与费用仍待建设。')
def refine_crew(d):
 for group in d['domains']:
  for n in group['items']:
   if n['id'] in NEEDS:n['gap']=n['gap'].split(MARKER)[0]+MARKER+STATUS
 for p in d['page_blueprints']:
  if p['id'] in ('P03','P10','P16'):p['status']=p['status'].split(MARKER)[0]+MARKER+STATUS
 d['framework']['crew_schedule_trial']=copy.deepcopy(CONTRACT)
 d['framework']['surfaces']=[s for s in d['framework']['surfaces'] if s['href']!='#crew-schedule']+[dict(name='设备与人员联立试排',question='资源有空时，是否有同工号、相同资格与窗口可执行？',content=CONTRACT['visuals'],action='核对资格和未来假设，定位双侧竞争与完整批次影响，再交计划岗位评审',href='#crew-schedule',status=STATUS)]
 return d
def remove_crew(d):
 for group in d['domains']:
  for n in group['items']:
   if n['id'] in NEEDS:n['gap']=n['gap'].split(MARKER)[0]
 for p in d['page_blueprints']:
  if p['id'] in ('P03','P10','P16'):p['status']=p['status'].split(MARKER)[0]
 d['framework'].pop('crew_schedule_trial',None);d['framework']['surfaces']=[s for s in d['framework']['surfaces'] if s['href']!='#crew-schedule'];return d
