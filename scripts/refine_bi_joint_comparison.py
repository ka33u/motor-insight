"""Document same-input policy trade-offs without claiming another scheduling engine."""
from copy import deepcopy
MARKER=' 联立派序对照：'
STATUS='新增同一物料、人机、BOM与时间范围下的两种派序并列对照。两列独立运行原有算法，先核对来源、规则及完整对象身份一致；按完整批次列更早、更晚、同刻、新获得/失去完整安排与两列均未排完，未排任务不以0替代时间。逐任务比较人机、开始/完成及首个阻断；按需求和供给编号对照预留量、触发任务和时点，物料按各自单位核对差值守恒。保留共同Excel来源、两列原始假设和完整CSV/JSON，暂停方案不产生健康零差值。只改变派序，不生成最优推荐、不修改BOM或库存、不批准计划；浏览器、手机、键盘及实际下载仍未验收。'
CONTRACT=dict(revision='joint-policy-compare-20261008',href='#joint-schedule?view=compare',state=STATUS,
 definition='同一方案、版本、时间范围和来源快照；左列应完成时间优先，右列批次优先级优先。差值始终为右减左；两列都完整排入才比较批次完成时间。',
 presentation='共同假设→两列完整批次/未排/晚交→三态转换矩阵与全部批次→任务/阻断差异→物料守恒与预留流水→共同来源和两列完整导出。',
 boundary='只读启发式结果对照，不是因果估计、全局最优计划或审批。不同方案不合并，批次数与台数只计一次，kg与件不求总量。清单局部筛选不改变整案汇总、来源及标明的完整两列导出。')
def refine_comparison(d):
    for group in d['domains']:
        for item in group['items']:
            if item['id'] in ('F-03','F-06','F-07'):item['gap']=item['gap'].split(MARKER)[0]+MARKER+STATUS
    for page in d['page_blueprints']:
        if page['id']=='P03':page['status']=page['status'].split(MARKER)[0]+MARKER+STATUS
    d['framework']['joint_policy_comparison']=deepcopy(CONTRACT)
    d['framework']['surfaces']=[s for s in d['framework']['surfaces'] if s.get('name')!='联立试排派序对照']+[dict(name='联立试排派序对照',href=CONTRACT['href'],question='改变派序后，哪些批次更早、哪些更晚、哪些仍未排完？',content=CONTRACT['presentation'],action='核对同一假设→逐批次看取舍→追到任务、人机和预留差异→交计划岗位评审',status=STATUS)]
    return d
