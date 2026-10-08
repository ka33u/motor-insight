"""Track bounded WIP remainder simulation without promoting formal scheduling."""
from copy import deepcopy
MARKER=' 在制剩余试排：'
STATUS=('新增完整Excel版本驱动的剩余任务试排：明确原工单与报工，已完成仅保留实际时点，加工中固定原人机续作，暂停待续增加恢复准备。'
        '逐任务剩余定额扣声明已投入量，独立余料分共享与工单专属，联合物料、人机日历及资格。'
        '提供工单覆盖、历史/续作/新排/阻断、双视角甘特、物料守恒、任务明细、版本来源和完整CSV/JSON可重算导出。'
        '任务明细新增派序当时的完整资源×人员候选、批量/资格、准备与共同窗口、预留前余料、人机尾部和关联任务跳转；可单任务导出完整依据复算。'
        '首阻断队列按原依赖图核对传播，列去重任务、工单及整单台数；支持工单×状态×首阻断交集及同版详情，不把交叠关联数当作恢复收益。'
        '当前交集可导出一行一任务CSV或带完整输入的JSON，空交集保留条件；筛选不重算工单、共享余料或人机安排。'
        '48号模拟Excel包含2工单12台、52任务及8方案；保留旧联立算法。'
        '仍是合成局部试排，尚缺报废补产、返工路线、替代料、模具、多机看护、冻结历史资格与正式批准；浏览器及手机未验收。')
CONTRACT=dict(revision='WIP_REMAINDER_SHARED_POOLS_1',href='#wip-trial',state=STATUS,
 definition='一个完整方案版本×一种派序策略；逐任务完成量+剩余量=原任务量。工单覆盖按完整工单计，不把跨工序任务台数加成产量。',
 measures='历史完成任务、锁定续作任务、新排剩余任务、未排任务互斥；工单仅在所有任务有实际或未来完成时计算完工与交期。暂停时摘要空值，不记零阻断。',
 material='逐任务剩余量×BOM(1+损耗)按步长向上取整，减声明已投入量；已投入量不进库存。独立尚未耗用池按物料/批次/位置去重，专属先用且不能跨工单，共享池一次预留。',
 presentation='方案/版本与策略→暂停原因或四类任务计数→工单覆盖与交期→首阻断队列及交集任务→设备/人员未来时间轴→完整候选比较及原报工→前序/首阻断/尾部占用任务→预留前余料和最终预留→同版来源与可重算任务导出。',
 blocker_revision='wip-blocker-reading-v1',
 blocker_definition='一个完整方案版本×策略×首阻断任务；按完整前序图核对根关系，关联未排任务、原工单和整单台数分别去重。多首阻断关联交叠，不能跨行相加；整单台数不是剩余量、损失产量、真实逾期或恢复收益。',
 blocker_presentation='先读完整方案首阻断队列（最早假设交期→工单数→任务数→编号）→点数量聚焦关联任务→工单/四类状态/首阻断取交集→点任务核对人机候选与原Excel。筛选仅限任务清单，完整导出仍是全方案原始根关系。',
 blocker_boundary='仅支持WIP_REMAINDER_SHARED_POOLS_1及已知策略/完整版本；验证依赖可达、四类状态、工单一一映射和全量摘要；缺项/环路/错误传播即暂停队列。最多5000任务、前序和根关联各200000条，不截断。解除一根不能推断其余约束也满足，需另作完整重算。',
 selection_revision='WIP_TASK_SELECTION_1',
 selection_definition='当前完整方案版本×策略×工单批次/四类状态/原首阻断交集；按原任务编号逐行保留派序顺序，完整保留各任务原根集合，不重算或分摊共享资源。',
 selection_delivery='筛选任务CSV：条件、当前/全案任务数、原任务、原工单映射及完整来源；筛选JSON：上述清单加完整输入/原结果，可校验全方案后复算交集。合法空交集为零行；暂停、未知范围或旧凭据拒绝。',
 selection_boundary='工单台数、完成时点仍来自整单原结果；不能跨工序相加，也不代表局部恢复收益。筛选变化、重置、切页或后发下载使旧响应失效。来源、账号、规则及筛选定义变更须重读。',
 decision_revision='WIP_DISPATCH_EVIDENCE_1',
 decision_definition='一个完整版本×派序策略×任务×资源候选×人员候选；捕获此任务派序前共享池，重新核对全结果及可行组合。未开始/待续按完成、开始、人机、候选、资格编号及准备秒数升序；加工中按候选、资格编号升序。不是全局优化。',
 decision_limits='上限1000组合、200000窗口交集与阻断核对工作量；超过即明确不可用，不显示截断候选。前序/缺料阻断未尝试窗口，不能推断无产能；历史完成不生成假想候选。',
 boundary='整单精确映射，报工必须全部明确覆盖；加工中从截止时点原人机连续续作。版本链、数量、用料或摘要冲突暂停。单容量、单人全程陪同、尾部追加，不抢占或回填，不声称最优及真实可派工。')

def refine_wip_trial(d):
 for group in d['domains']:
  for item in group['items']:
   if item['id'] in ('F-01','F-03','F-07','G-02','J-09'):
    for obj,key in [(item,'gap'),(item['display_design'],'availability'),(item['presentation_contract'],'detail_contract')]:obj[key]=obj[key].split(MARKER)[0]+MARKER+STATUS
 d['framework']['surfaces']=[r for r in d['framework']['surfaces'] if r['href']!='#wip-trial']+[dict(name='在制剩余试排',question='已发生报工之后，剩余任务能否在料、人、机约束下完成？',content=CONTRACT['presentation'],action='先核对完整版本→区分历史与未来→查首阻断、原报工和余料→导出复算后走正式业务流程',href='#wip-trial',status=STATUS)]
 d['framework'].pop('wip_trial',None);d['framework']['wip_trial']=deepcopy(CONTRACT)
 return d
