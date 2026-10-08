"""Describe paired occupancy without changing published metrics or coverage."""
from copy import deepcopy
MARKER=' 人机占用对照：'
STATUS=('两策略对照页新增设备资源位/原工号两种占用视角，同一对象上下两行并用共同时间轴，分别显示换型与加工、任务数和占用分钟。'
        '对象并集含两策略任一已分配对象，未排任务不绘成零时长；总分钟相同但任务、时点或搭配变化仍可筛查。'
        '完整方案/两策略全部已排时段的刻度均不随对象选择和分页改变。点任务读取原两列依据；点对象进入任一列匹配的任务，可与批次及变化条件取交集，重置恢复全部。'
        '共同来源与完整导出保持全方案，原结果可复原此图。只读展示，不计算可插单容量、设备利用率、人员绩效或最优策略。'
        '纯JS、六岗位原生HTTP及原任务时点独立核对；浏览器布局、手机、键盘和实际下载仍未验收。')
CONTRACT=dict(revision='joint-occupancy-v1',href='#joint-schedule?view=compare',state=STATUS,
 definition='同一方案两种派序的已安排任务；以原设备资源位或工号分组，两种视角不得相加。原时间为工厂本地假设时点，无浏览器时区转换。',
 measures='占用分钟=各任务完成−准备开始，换型=加工开始−准备开始，加工=完成−加工开始；差值为优先级优先减应完成时间优先。只有已排任务参与，无可用窗口分母。',
 presentation='完整批次结果→同一对象两行同轴占用→原任务两列明细→Excel来源。共用完整方案范围或两策略全部安排时段；对象、变化筛选与分页保留刻度。',
 boundary='空白未核对资源/人员可用窗口，不能读成可插单时间。仅任一策略被占用的对象进入图，不等于候选人机全集；未安排及资料暂停保留，不推断现场效率或业务批准。')
def refine_occupancy(d):
 for group in d['domains']:
  for item in group['items']:
   if item['id'] in ('F-02','F-06','F-07'):item['gap']=item['gap'].split(MARKER)[0]+MARKER+STATUS
 for page in d['page_blueprints']:
  if page['id']=='P03':page['status']=page['status'].split(MARKER)[0]+MARKER+STATUS
 for surface in d['framework']['surfaces']:
  if surface.get('href')==CONTRACT['href']:surface['status']=surface['status'].split(MARKER)[0]+MARKER+STATUS
 d['framework']['joint_occupancy_comparison']=deepcopy(CONTRACT)
 return d
